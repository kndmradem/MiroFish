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
