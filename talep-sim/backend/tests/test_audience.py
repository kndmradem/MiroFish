"""Hedef kitle: girdi/tahmin, bölge bazında kalibre dağılım, panelin kitleye göre seçimi ve MiroFish ağırlıklandırması."""
import json
from collections import Counter

import httpx
import pytest
from fastapi.testclient import TestClient

from app import audience as aud
from app.main import app
from app.models import PredictionRequest
from app.panel import prompts
from app.panel.library import PanelStore, sample_panel
from app.services.personas import SEED_CONSUMERS, SEED_GENDER, seed_person

from .test_mirofish_engine import FakeMiroFish, make_engine as make_mf_engine
from .test_panel import FakeLLMServer, make_engine as make_panel_engine

BODY = {"image_base64": "x", "technical_specs": "%100 pamuk", "unit_cost": "12",
        "total_production_budget": 50000, "target_regions": ["EU", "TR"]}


# ---------------------------------------------------------------- girdi ve tahmin
@pytest.mark.parametrize("text,value,child", [
    ("Kadın", "kadin", None), ("BAYAN", "kadin", None), ("women", "kadin", None),
    ("erkek", "erkek", None), ("Men", "erkek", None),
    ("çocuk", "cocuk", None), ("Kız Çocuk", "cocuk", "kız"), ("erkek çocuk", "cocuk", "erkek"),
    ("bebek", "cocuk", None), ("Unisex", "unisex", None),
])
def test_user_value_is_normalized(text, value, child):
    info = aud.normalize(text)
    assert info.value == value and info.child_gender == child and info.source == "kullanıcı girdisi"


@pytest.mark.parametrize("name,category,sizes,value", [
    ("Çiçek desenli midi elbise", "Elbise", "", "kadin"),
    ("Erkek çocuk eşofman takımı", "", "", "cocuk"),       # "erkek" geçse de çocuk ürünü
    ("Kravat", "Aksesuar", "", "erkek"),
    ("Basic tişört", "Üst giyim", "", "unisex"),           # ipucu yok: karışık panel
    ("Body", "Alt", "0-3 ay", "cocuk"),                      # beden aralığı ay/yaş ile
    ("Kadın erkek ortak sweat", "", "", "unisex"),
])
def test_empty_audience_is_guessed_and_labeled(name, category, sizes, value):
    info = aud.resolve(None, name, category, sizes=sizes)
    assert info.value == value and info.source == "tahmin" and info.reason


def test_unknown_user_value_falls_back_to_guess_with_reason():
    info = aud.resolve("yetişkin", "Midi etek")
    assert info.value == "kadin" and info.source == "tahmin" and "tanınmadı" in info.reason


# ---------------------------------------------------------------- bölge kalibrasyonu
def test_eu_and_tr_have_their_own_distribution_and_others_use_default():
    kad = aud.normalize("kadın")
    eu, tr, us = (aud.plan_for(kad, r) for r in ("EU", "TR", "US"))
    assert eu.region_specific and tr.region_specific and not us.region_specific
    assert eu.dist.age_bands != tr.dist.age_bands                       # TR nüfusu daha genç
    young = lambda p: sum(w for lo, hi, w in p.dist.age_bands if hi <= 34)
    assert young(tr) > young(eu)
    assert any("ayrı kalibre edilmedi" in w for w in us.warnings)
    assert all(any("doğrulanmamış" in w for w in p.warnings) for p in (eu, tr))


# ---------------------------------------------------------------- panel seçimi (kota)
def _panel(value, region="EU", n=12, child=None):
    info = aud.normalize(value)
    if child:
        info = info.model_copy(update={"child_gender": child})
    lib = PanelStore().personas(region)
    return sample_panel(lib, n, "ürün", audience=aud.plan_for(info, region)), aud.plan_for(info, region)


def test_women_product_gets_mostly_women_with_exact_quota():
    members, plan = _panel("kadın")
    women = sum(m.female for m in members)
    assert women == round(12 * plan.dist.female_share) == 10
    assert {m.buyer_role for m in members if not m.female} == {"hediye"}
    assert {m.buyer_role for m in members if m.female} == {"kendisi"}


def test_men_product_gets_mostly_men():
    members, plan = _panel("erkek", "TR")
    men = sum(not m.female for m in members)
    assert men == 12 - round(12 * plan.dist.female_share) and men > 6


def test_child_product_panel_is_parents():
    members, plan = _panel("çocuk", "TR", child="kız")
    assert all(m.buyer_role == "ebeveyn" and m.child_female is True for m in members)
    lo, hi = plan.dist.child_age_range
    assert all(lo <= m.child_age <= hi for m in members)
    bands = plan.dist.age_bands
    assert all(any(b_lo <= m.age <= b_hi for b_lo, b_hi, _ in bands) for m in members)   # ebeveyn yaşı
    text = prompts.persona_text(members[0])
    assert ("Annesin" in text or "Babasın" in text) and "kızın" in text


def test_unisex_is_mixed_and_age_bands_follow_region_calibration():
    members, plan = _panel("unisex", "EU", n=20)
    women = sum(m.female for m in members)
    assert 8 <= women <= 13
    got = Counter(next(i for i, (lo, hi, _) in enumerate(plan.dist.age_bands) if lo <= m.age <= hi) for m in members)
    want = aud._allocate([w for _, _, w in plan.dist.age_bands], 20)
    assert [got.get(i, 0) for i in range(len(want))] == want


def test_panel_is_deterministic_and_differs_by_audience():
    a, _ = _panel("kadın")
    b, _ = _panel("kadın")
    c, _ = _panel("erkek")
    assert [(m.age, m.female) for m in a] == [(m.age, m.female) for m in b]
    assert [(m.age, m.female) for m in a] != [(m.age, m.female) for m in c]


def test_without_audience_old_behaviour_is_unchanged():
    lib = PanelStore().personas("EU")
    m = sample_panel(lib, 12, "ürün")
    assert all(x.buyer_role == "kendisi" and x.audience == "" for x in m)


# ---------------------------------------------------------------- panel motoru uçtan uca
async def test_panel_engine_reports_who_was_asked():
    server = FakeLLMServer()
    engine = make_panel_engine(server)
    card = await engine.fuse_product_card(PredictionRequest(product_name="Midi elbise", **BODY))
    card["target_audience"] = aud.resolve(None, "Midi elbise").model_dump(mode="json")
    sim = await engine.simulate_region(card, "TR", 12.0)
    a = sim.meta["audience"]
    assert a["value"] == "kadin" and a["source"] == "tahmin" and a["method"] == "kota"
    assert a["composition"]["n_female"] == 11 and a["calibration"]["region_specific"]   # TR: 12 x 0,88
    assert all(r.get("who") for r in sim.meta["raw_answers"])
    systems = [m["content"] for b in server.bodies for m in b["messages"] if m["role"] == "system"]
    users = [m["content"] for b in server.bodies for m in b["messages"] if m["role"] == "user"]
    assert any("kendin giymezsin" in s for s in systems)                  # erkekler yakını için değerlendirir
    assert all("Ürünün hedef kitlesi: Kadın" in u for u in users)


# ---------------------------------------------------------------- MiroFish: sabit havuz, ağırlık
def test_every_seed_person_has_gender_entry():
    names = {p.split(",")[0] for ps in SEED_CONSUMERS.values() for p in ps}
    assert names == set(SEED_GENDER)
    assert seed_person(SEED_CONSUMERS["TR"][0]) == {"name": "Elif Demir", "age": 29, "female": True}


class GenderedMiroFish(FakeMiroFish):
    """Kadınlar ürünü çok, erkekler az beğenir: ağırlıklandırmanın talebi kadın tarafına çektiğini sınar."""

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path != "/api/simulation/interview/batch":
            return super().handler(request)
        body = json.loads(request.content)
        self.prompts = getattr(self, "prompts", []) + [i["prompt"] for i in body["interviews"]]
        names = {p["user_id"]: p["name"] for p in self.profiles}
        out = {}
        for i in body["interviews"]:
            female = SEED_GENDER.get(names[i["agent_id"]]) == "K"
            out[f"reddit_{i['agent_id']}"] = {"agent_id": i["agent_id"], "response": json.dumps({
                "interest": 80 if female else 20, "too_cheap": 30, "cheap": 55, "expensive": 90, "too_expensive": 130,
                "objection": "Kumaş ince"})}
        return httpx.Response(200, json={"success": True, "data": {"result": {"results": out}}})


async def test_mirofish_answers_are_weighted_to_target_audience(tmp_path):
    fake = GenderedMiroFish()
    engine = make_mf_engine(tmp_path, fake, agents_per_region=10)
    card = await engine.fuse_product_card(PredictionRequest(product_name="Elbise", **BODY))
    card["target_audience"] = aud.normalize("kadın").model_dump(mode="json")
    sim = await engine.simulate_region(card, "EU", 12.0, scope=["EU"])
    a = sim.meta["audience"]
    assert a["method"] == "ağırlık" and a["unweighted_demand"] == 56          # 6 kadın x 80 + 4 erkek x 20
    assert sim.demand_score > a["unweighted_demand"] + 10                     # hedef %85 kadın
    assert a["composition"]["female_pct"] > a["composition"]["n_female"] * 10   # ağırlıklı pay ham paydan büyük
    assert all("Kadınsan kendin için" in p for p in fake.prompts)
    men = [r for r in sim.meta["raw_answers"] if "Erkek" in (r.get("who") or "")]
    assert men and all(r["weight"] < 1 for r in men)

    card["target_audience"] = aud.normalize("erkek").model_dump(mode="json")
    sim_m = await engine.simulate_region(card, "EU", 12.0, scope=["EU"])
    assert sim_m.demand_score < 56


async def test_mirofish_old_world_without_people_map_fetches_profiles(tmp_path):
    fake = GenderedMiroFish()
    engine = make_mf_engine(tmp_path, fake, agents_per_region=10)
    card = await engine.fuse_product_card(PredictionRequest(product_name="Elbise", **BODY))
    await engine.simulate_region(card, "EU", 12.0, scope=["EU"])                 # dünya kurulur
    saved = json.loads((tmp_path / "world.json").read_text())
    for w in saved.values():
        w.pop("people", None)                                                  # eski biçim
    (tmp_path / "world.json").write_text(json.dumps(saved))
    engine2 = make_mf_engine(tmp_path, fake, agents_per_region=10)
    card["target_audience"] = aud.normalize("kadın").model_dump(mode="json")
    sim = await engine2.simulate_region(card, "EU", 12.0, scope=["EU"])
    assert sim.meta["audience"]["composition"]["n_unknown"] == 0
    assert fake.calls.count("/api/graph/ontology/generate") == 1                 # dünya yeniden kurulmadı


# ---------------------------------------------------------------- API
def test_api_uses_user_value_or_labels_guess():
    c = TestClient(app)
    r = c.post("/api/predict", json={**BODY, "product_name": "Oversize sweat", "target_audience": "erkek"}).json()
    assert r["target_audience"]["value"] == "erkek" and r["target_audience"]["source"] == "kullanıcı girdisi"
    assert all(x["audience_panel"]["value"] == "erkek" for x in r["regional_breakdown"])
    g = c.post("/api/predict", json={**BODY, "product_name": "Saten gecelik"}).json()
    assert g["target_audience"]["value"] == "kadin" and g["target_audience"]["source"] == "tahmin"
    assert "gecelik" in g["target_audience"]["reason"]
