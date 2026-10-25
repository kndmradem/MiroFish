import json
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient

from app.advisor import Advisor
from app.main import app, get_advisor, get_profiler
from app.models import BrandProfile
from app.services.brand_profiler import BrandProfiler, parse_brand_profile
from app.services.engine import MockSimulationEngine
from app.services.llm import LLMClient, LLMError
from app.services.mirofish_engine import build_interview_prompt

BODY = {
    "product_name": "Kışlık Oversize Yün Kaban", "image_base64": "x",
    "technical_specs": "GSM: 450g, %80 Yün %20 Polyamid, Su itici astar.",
    "unit_cost": "25.50", "total_production_budget": 100000, "target_regions": ["EU", "MENA", "CIS", "US"],
}

LUXURY = BrandProfile(name="LuxA", price_tier="luxury", price_multiple=10, price_sensitivity=0.1, brand_pull=95,
                      margin_norm_pct=75, regional_strength={"EU": 80, "MENA": 95, "CIS": 55, "US": 85},
                      known_brand=True, confidence="high", source="llm_knowledge")
MASS = BrandProfile(name="MassB", price_tier="mass", price_multiple=2.5, price_sensitivity=0.9, brand_pull=70,
                    margin_norm_pct=50, regional_strength={"EU": 85, "MENA": 60, "CIS": 60, "US": 50},
                    known_brand=True, confidence="high", source="llm_knowledge")


def fake_llm(reply) -> LLMClient:
    """`reply`: sabit cevap metni ya da (istek) -> metin üreten fonksiyon."""
    def handler(request: httpx.Request) -> httpx.Response:
        text = reply(json.loads(request.content)) if callable(reply) else reply
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})
    return LLMClient("k", "http://llm/v1", "m", httpx.AsyncClient(transport=httpx.MockTransport(handler)))


PROFILE_JSON = {"known_brand": True, "confidence": "high", "positioning": "Türk kadın giyim, modern şık",
                "price_tier": "upper_mass", "price_multiple": 4.0, "price_sensitivity": 0.5, "brand_pull": 60,
                "typical_customer": "25-45 çalışan kadın", "margin_norm_pct": 60,
                "regional_strength": {"EU": 30, "MENA": 50, "CIS": 55, "US": 15}}


def test_parse_clamps_multiple_into_tier_range():
    p = parse_brand_profile({**PROFILE_JSON, "price_multiple": 40, "brand_pull": 400}, "X", False)
    assert p.price_multiple == 5.5 and p.brand_pull == 100 and p.source == "llm_knowledge"
    assert "doğrulanmış veri değildir" in p.warning


def test_parse_rejects_bad_schema():
    with pytest.raises(LLMError):
        parse_brand_profile({"price_tier": "uzay"}, "X", False)


async def test_unknown_brand_is_flagged_low_confidence():
    llm = fake_llm(json.dumps({**PROFILE_JSON, "known_brand": False, "confidence": "high"}))
    p = await BrandProfiler(llm).profile("BilinmeyenMarka")
    assert p.known_brand is False and p.confidence == "low" and "tanımıyor" in p.warning


async def test_user_notes_reach_the_prompt_and_set_source():
    seen = {}
    llm = fake_llm(lambda body: seen.update(body=body) or json.dumps(PROFILE_JSON))
    p = await BrandProfiler(llm).profile("Ipekyol", "Daha çok iş kadını, orta-üst fiyat")
    assert p.source == "user_notes"
    assert "Ipekyol" in seen["body"]["messages"][1]["content"] and "iş kadını" in seen["body"]["messages"][1]["content"]


async def test_garbage_llm_answer_falls_back_with_warning():
    p = await BrandProfiler(fake_llm("hiç json yok")).profile("Ipekyol")
    assert p.source == "generic_default" and p.confidence == "low" and "üretilemedi" in p.warning


async def test_no_llm_falls_back_with_warning():
    p = await BrandProfiler(None).profile("Ipekyol")
    assert p.source == "generic_default" and "LLM ayarlı olmadığı" in p.warning


def test_brand_profile_endpoint(isolated_app):
    isolated_app[get_profiler] = lambda: BrandProfiler(fake_llm(json.dumps(PROFILE_JSON)))
    r = TestClient(app).post("/api/brand-profile", json={"brand": "Ipekyol"})
    assert r.status_code == 200 and r.json()["price_tier"] == "upper_mass" and r.json()["price_multiple"] == 4.0


def _predict(**extra):
    r = TestClient(app).post("/api/predict", json={**BODY, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def test_brand_changes_price_policy_demand_and_quantities():
    lux, mass = _predict(brand_profile=LUXURY.model_dump()), _predict(brand_profile=MASS.model_dump())
    lp = {x["region"]: Decimal(x["optimal_sale_price"]) for x in lux["regional_breakdown"]}
    mp = {x["region"]: Decimal(x["optimal_sale_price"]) for x in mass["regional_breakdown"]}
    assert all(lp[r] > mp[r] * 2 for r in lp)  # lüks marka çok daha yüksek fiyat politikası
    assert lux["brand_profile"]["name"] == "LuxA"
    assert [x["regional_breakdown"] for x in (lux, mass)][0] != [x["regional_breakdown"] for x in (lux, mass)][1]


def test_regional_brand_strength_shifts_demand():
    mena = MASS.model_copy(update={"regional_strength": {"EU": 20, "MENA": 95, "CIS": 50, "US": 50}})
    eu = MASS.model_copy(update={"regional_strength": {"EU": 95, "MENA": 20, "CIS": 50, "US": 50}})
    a, b = [{x["region"]: x["demand_score_100"] for x in _predict(brand_profile=p.model_dump())["regional_breakdown"]}
            for p in (mena, eu)]
    assert a["MENA"] > b["MENA"] + 15 and b["EU"] > a["EU"] + 15


def test_no_brand_keeps_neutral_behaviour_and_says_so():
    data = _predict()
    assert data["brand_profile"] is None
    assert any("Marka girilmedi" in n for n in data["methodology_notes"])


def test_explanations_use_real_numbers_and_brand():
    data = _predict(brand_profile=LUXURY.model_dump())
    for row in data["regional_breakdown"]:
        keys = {e["key"]: e for e in row["explanations"]}
        assert set(keys) == {"demand", "price", "margin", "quantity"}
        assert all(e["how"] and e["assumptions"] for e in keys.values())
        assert str(row["demand_score_100"]) in keys["demand"]["how"]
        assert "LuxA" in keys["price"]["how"] and "10.0 katına" in keys["price"]["how"]
        assert "%75" in keys["margin"]["how"]
        assert f"{row['recommended_production_qty']:,}" == keys["quantity"]["value"]


def test_brand_name_only_uses_profiler(isolated_app):
    isolated_app[get_profiler] = lambda: BrandProfiler(fake_llm(json.dumps(PROFILE_JSON)))
    data = _predict(brand="Ipekyol")
    assert data["brand_profile"]["name"] == "Ipekyol" and data["brand_profile"]["price_multiple"] == 4.0


def test_recommendations_rules_are_data_driven_and_flag_weak_brand_knowledge():
    unknown = LUXURY.model_copy(update={"confidence": "low", "known_brand": False})
    data = _predict(brand_profile=unknown.model_dump())
    titles = " | ".join(r["title"] for r in data["recommendations"])
    assert "Marka profilini doğrula" in titles
    assert {r["category"] for r in data["recommendations"]} >= {"fiyat", "bölge", "marka"}
    assert all(r["source"] == "kural" for r in data["recommendations"])


def test_model_recommendations_used_when_valid_else_rules(isolated_app):
    good = json.dumps({"oneriler": [{"category": "fiyat", "title": "Fiyatı $95 yap", "detail": "MENA'da marj yüksek.",
                                     "based_on": "MENA fiyat"}]})
    isolated_app[get_advisor] = lambda: Advisor(fake_llm(good))
    recs = _predict(brand_profile=MASS.model_dump())["recommendations"]
    assert recs[0]["source"] == "model" and recs[0]["title"] == "Fiyatı $95 yap"

    isolated_app[get_advisor] = lambda: Advisor(fake_llm("bozuk"))
    assert all(r["source"] == "kural" for r in _predict(brand_profile=MASS.model_dump())["recommendations"])


def test_interview_prompt_contains_brand_block():
    card = {"product_name": "Kaban", "features": {}}
    prompt = build_interview_prompt(card, "MENA", LUXURY, 25.0)
    assert "LuxA" in prompt and "lüks segment" in prompt and "$250" in prompt and "95/100" in prompt
    assert "Marka:" not in build_interview_prompt(card, "MENA")


def test_every_region_always_has_explanations():
    cheap_brand = MASS.model_copy(update={"price_multiple": 1.2})
    data = _predict(unit_cost="300", total_production_budget=5000, brand_profile=cheap_brand.model_dump())
    for row in data["regional_breakdown"]:
        assert len(row["explanations"]) == 4


def test_zero_weight_region_is_explained():
    from app.allocation import RegionAllocation
    from app.explain import explain_region
    from app.pricing import AgentPriceAnswer, analyze
    from app.services.engine import RegionSimulation

    answers = [AgentPriceAnswer(8 + i, 12 + i, 20 + i, 30 + i) for i in range(5)]
    sim = RegionSimulation("US", 30, answers, [], {"engine": "mirofish", "n_agents": 5, "n_valid": 5, "mean_interest": 30})
    vw, best = analyze(answers, 25.0)
    exps = explain_region(sim, vw, best, 25.0, RegionAllocation("US", Decimal(0), Decimal(0), 0), Decimal(0), 1000, None)
    assert "üretim ayrılmadı" in exps[3].how


def test_explanations_work_for_mirofish_style_meta():
    from app.allocation import RegionAllocation
    from app.explain import explain_region
    from app.pricing import AgentPriceAnswer, analyze
    from app.services.engine import RegionSimulation

    answers = [AgentPriceAnswer(20 + i, 40 + i, 80 + i, 120 + i) for i in range(5)]
    sim = RegionSimulation("EU", 64, answers, ["Kalın"], {"engine": "mirofish", "n_agents": 5, "n_valid": 4,
                                                           "mean_interest": 64, "objection_counts": [("Kalın", 3)]})
    vw, best = analyze(answers, 25.0)
    alloc = RegionAllocation("EU", Decimal(640), Decimal(1000), 40)
    exps = explain_region(sim, vw, best, 25.0, alloc, Decimal(640), 1000, LUXURY)
    assert [e.key for e in exps] == ["demand", "price", "margin", "quantity"]
    assert "4 ajandan geçerli cevap" in exps[0].how


def _tr(**extra):
    return _predict(target_regions=["EU", "TR"], **extra)


def test_turkey_has_lower_price_than_eu_and_shows_try():
    data = _tr(brand_profile=MASS.model_dump(), usd_try_rate=40)
    rows = {r["region"]: r for r in data["regional_breakdown"]}
    assert Decimal(rows["TR"]["optimal_sale_price"]) < Decimal(rows["EU"]["optimal_sale_price"])  # düşük alım gücü
    assert rows["TR"]["local_currency"] == "TRY" and rows["TR"]["fx_rate"] == 40
    assert Decimal(rows["TR"]["local_price"]) == (Decimal(rows["TR"]["optimal_sale_price"]) * 40).quantize(Decimal("1"))
    assert rows["EU"]["local_price"] is None


def test_turkey_explanation_states_fx_assumption_and_shock():
    row = [r for r in _tr(usd_try_rate=50)["regional_breakdown"] if r["region"] == "TR"][0]
    price = [e for e in row["explanations"] if e["key"] == "price"][0]
    assert "1 USD = 50 TRY" in price["how"] and "Kur riski" in price["how"]
    assert any("canlı kur değildir" in a for a in price["assumptions"])
    assert any("alım gücü" in a for a in price["assumptions"])


def test_turkey_price_band_is_narrower_than_same_profile_elsewhere():
    rows = {r["region"]: r["van_westendorp"] for r in _tr(brand_profile=MASS.model_dump())["regional_breakdown"]}

    def width(vw):
        return (Decimal(vw["acceptable_range_high"]) - Decimal(vw["acceptable_range_low"])) / Decimal(vw["optimal_price_point"])
    assert width(rows["TR"]) < width(rows["EU"])  # +0.15 fiyat duyarlılığı bandı daraltır


def test_turkey_recommendation_includes_fx_risk_with_numbers():
    recs = _tr(usd_try_rate=42)["recommendations"]
    fx = [r for r in recs if "kur riskini planla" in r["title"]]
    assert fx and "marj" in fx[0]["detail"] and "42" in fx[0]["based_on"]


def test_default_fx_rate_used_when_not_given():
    row = [r for r in _tr()["regional_breakdown"] if r["region"] == "TR"][0]
    assert row["fx_rate"] == 42.0


def test_turkey_seed_and_region_mapping():
    from app.services.personas import SEED_CONSUMERS, build_seed_document, region_of, seed_hash
    assert len(SEED_CONSUMERS["TR"]) == 5 and "TR paneli" in build_seed_document()
    assert region_of("Elif Demir, pazarlama uzmanı") == "TR" and region_of("someone in Izmir") == "TR"
    assert len(seed_hash()) == 12


def test_interview_prompt_has_turkey_economic_context_and_rate():
    prompt = build_interview_prompt({"product_name": "Kaban", "features": {}}, "TR", None, 25.0, {"TRY": 42})
    assert "Ekonomik bağlam" in prompt and "1 USD = 42 TRY" in prompt
    assert "Ekonomik bağlam" not in build_interview_prompt({"product_name": "Kaban", "features": {}}, "EU")


def test_model_recommendations_keep_fx_risk_warning_for_turkey(isolated_app):
    good = json.dumps({"oneriler": [{"category": "fiyat", "title": "Fiyatı $95 yap", "detail": "x", "based_on": "y"}]})
    isolated_app[get_advisor] = lambda: Advisor(fake_llm(good))
    recs = _tr(brand_profile=MASS.model_dump())["recommendations"]
    assert recs[0]["source"] == "model" and any("kur riskini planla" in r["title"] for r in recs)


def test_price_zones_cover_axis_without_gaps():
    from app.pricing import AgentPriceAnswer, analyze, steps_from_answers
    answers = [AgentPriceAnswer(20 + i, 35 + i, 60 + i, 90 + i) for i in range(10)]
    vw, best = analyze(answers, 15.0)
    zones = vw.zones
    assert [z.key for z in zones] == ["too_cheap", "cheap", "ideal", "expensive", "too_expensive"]
    for a, b in zip(zones, zones[1:]):
        assert a.high == b.low and a.low <= a.high
    assert zones[-1].high is None and zones[1].low == vw.acceptable_range_low
    steps = steps_from_answers(answers, [10, 40, 70, 120])
    assert steps[0].suspicious == 10 and steps[-1].too_expensive == 10 and all(s.n == 10 for s in steps)


def _card(**kw):
    base = {"product_name": "Elbise", "features": {}, "composition": "pamuk", "climate_fit": "ılıman", "visual_description": ""}
    base.update(kw)
    return base


def test_returns_revealing_cut_raises_mena_more_than_eu():
    from app.models import Assumptions
    from app.returns import estimate_returns
    a = Assumptions()
    card = _card(visual_description="derin V dekolteli, kolsuz elbise")
    mena = estimate_returns(card, "MENA", 80, 25, 100, None, a)
    eu = estimate_returns(card, "EU", 80, 25, 100, None, a)
    assert any("Açık kesim" in d.label and d.points == 6.0 for d in mena.drivers)
    assert not any(d.points > 0 and "Açık kesim" in d.label for d in eu.drivers)
    plain = estimate_returns(_card(), "MENA", 80, 25, 100, None, a)
    assert mena.rate_pct == plain.rate_pct + 6.0


def test_returns_user_base_store_channel_and_net_margin():
    from app.models import Assumptions
    from app.returns import estimate_returns
    online = estimate_returns(_card(), "TR", 100, 30, 1000, None, Assumptions(return_base_pct={"TR": 20}))
    assert online.base_pct == 20 and online.drivers[0].basis == "kullanıcı verisi"
    store = estimate_returns(_card(), "TR", 100, 30, 1000, None, Assumptions(channel="store", return_base_pct={"TR": 20}))
    assert store.rate_pct < online.rate_pct * 0.6
    assert online.net_margin_pct < online.gross_margin_pct
    assert online.low_pct < online.rate_pct < online.high_pct
    assert online.net_qty_if_sold_out == int(1000 * (1 - online.rate_pct / 100))


def test_predict_endpoint_includes_returns_with_assumptions():
    from fastapi.testclient import TestClient
    from app.main import app
    body = {"product_name": "Elbise", "image_base64": "x", "technical_specs": "Saten, derin dekolte, slim fit",
            "unit_cost": "20", "total_production_budget": 50000, "target_regions": ["EU", "MENA"],
            "assumptions": {"channel": "online", "restock_share": 0.5}}
    r = TestClient(app).post("/api/predict", json=body)
    assert r.status_code == 200, r.text
    rows = {x["region"]: x["returns"] for x in r.json()["regional_breakdown"]}
    assert rows["MENA"]["rate_pct"] > 0 and rows["MENA"]["net_margin_pct"] < rows["MENA"]["gross_margin_pct"]
    assert any("dekolte" in d["label"].lower() or "Açık kesim" in d["label"] for d in rows["MENA"]["drivers"])
