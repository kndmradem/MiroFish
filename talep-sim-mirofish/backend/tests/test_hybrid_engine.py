"""Karma motor: MiroFish yapabildiği yerde, kalan yerde persona paneli (etiketli)."""
import asyncio

import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.models import PredictionRequest
from app.main import app, build_engine, get_engine
from app.services.engine import MockSimulationEngine
from app.services.hybrid_engine import HybridEngine
from app.services.mirofish_client import MiroFishTimeout

BODY = {"product_name": "Kaban", "image_base64": "x", "technical_specs": "GSM: 450, yün",
        "unit_cost": "25", "total_production_budget": 100000, "target_regions": ["EU", "MENA", "CIS"]}


def _label(sim, engine):
    """Mock sonucunu gerçek motorun meta alanlarıyla etiketler (açıklama metinleri bu alanları okur)."""
    n = sim.meta["n_agents"]
    sim.meta.update(engine=engine, n_valid=n, n_priced=n, mean_interest=sim.demand_score, calibration={},
                    persona_version="test", persona_as_of="2026-11-01", context_version=None, context_as_of=None,
                    freshness_warnings=[], segments={},
                    raw_answers=[])
    return sim


class FakeMiroFish(MockSimulationEngine):
    def __init__(self, bad=(), exc=None):
        super().__init__(latency_s=0)
        self.bad, self.exc, self.calls = bad, exc, []
        self.max_concurrency = 1

    async def simulate_region(self, card, region, unit_cost, brand=None, fx_rates=None, progress=None, scope=None):
        self.calls.append(region)
        if region in self.bad:
            raise self.exc or MiroFishTimeout("interview/batch zaman aşımı (504)")
        sim = await super().simulate_region(card, region, unit_cost, brand, fx_rates)
        return _label(sim, "mirofish")


class FakePanel(MockSimulationEngine):
    def __init__(self):
        super().__init__(latency_s=0)
        self.calls = []

    async def simulate_region(self, card, region, unit_cost, brand=None, fx_rates=None, progress=None, scope=None):
        self.calls.append(region)
        sim = await super().simulate_region(card, region, unit_cost, brand, fx_rates)
        return _label(sim, "panel")


def test_default_engine_is_hybrid(monkeypatch):
    monkeypatch.delenv("SIM_ENGINE", raising=False)
    eng = build_engine(Settings())
    assert isinstance(eng, HybridEngine)
    assert hasattr(eng.panel, "llm") and hasattr(eng.panel, "store")   # vitrin turu panel tarafını kullanır


def test_mirofish_used_where_it_works_panel_for_the_rest(isolated_app):
    mf, panel = FakeMiroFish(bad=("MENA",)), FakePanel()
    isolated_app[get_engine] = lambda: HybridEngine(mf, panel)
    r = TestClient(app).post("/api/predict", json=BODY)
    assert r.status_code == 200, r.text
    data = r.json()
    eng = {x["region"]: x["engine"] for x in data["regional_breakdown"]}
    assert eng == {"EU": "mirofish", "MENA": "panel", "CIS": "mirofish"}
    assert data["engine"] == "hybrid" and not data["failed_regions"]
    mena = next(x for x in data["regional_breakdown"] if x["region"] == "MENA")
    assert "MiroFish" in mena["engine_note"] and "zaman aşımı" in mena["engine_note"]
    assert any("persona paneliyle" in n and "MENA" in n for n in data["methodology_notes"])
    assert panel.calls == ["MENA"]


def test_all_mirofish_keeps_mirofish_label(isolated_app):
    isolated_app[get_engine] = lambda: HybridEngine(FakeMiroFish(), FakePanel())
    data = TestClient(app).post("/api/predict", json=BODY).json()
    assert data["engine"] == "mirofish"
    assert all(x["engine_note"] is None for x in data["regional_breakdown"])


def test_fallback_can_be_disabled(isolated_app):
    isolated_app[get_engine] = lambda: HybridEngine(FakeMiroFish(bad=("MENA",)), FakePanel(), fallback_on_error=False)
    data = TestClient(app).post("/api/predict", json=BODY).json()
    assert data["failed_regions"][0]["region"] == "MENA"


def test_unreachable_mirofish_is_not_retried_for_every_region():
    mf = FakeMiroFish(bad=("EU", "MENA", "CIS"), exc=httpx.ConnectError("Connection refused"))
    panel = FakePanel()
    eng = HybridEngine(mf, panel)

    async def run():
        card = await MockSimulationEngine(latency_s=0).fuse_product_card(PredictionRequest(**BODY))
        return [await eng.simulate_region(card, r, 25.0) for r in ("EU", "MENA", "CIS")]

    sims = asyncio.run(run())
    assert mf.calls == ["EU"]                       # ilk bağlantı hatasından sonra MiroFish beklenmez
    assert [s.meta["engine"] for s in sims] == ["panel"] * 3
    assert all("ulaşılamıyor" in s.meta["fallback_reason"] or "ConnectError" in s.meta["fallback_reason"] for s in sims)


def test_collection_does_not_pair_mirofish_agents_with_fallback_panel_persons():
    from app.collection.summary import PANEL_FALLBACK_OFFSET, _item_regions

    def rb(note):
        return {"region": "MENA", "demand_score_100": 60, "optimal_sale_price": "50", "estimated_margin_percentage": 40,
                "van_westendorp": {"acceptable_range_low": "30", "acceptable_range_high": "70"},
                "returns": {"rate_pct": 10}, "raw_answers": [{"agent": 1, "interest": 70}], "engine_note": note}

    _, a, _ = _item_regions({"regional_breakdown": [rb(None)]}, None)
    _, b, _ = _item_regions({"regional_breakdown": [rb("MiroFish bu bölgeyi hesaplayamadı")]}, None)
    assert list(a) == [("MENA", 1)] and list(b) == [("MENA", PANEL_FALLBACK_OFFSET + 1)]
