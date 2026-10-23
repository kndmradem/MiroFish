import json

from fastapi.testclient import TestClient

from app.main import app, get_engine
from app.services.engine import MockSimulationEngine
from app.services.mirofish_client import MiroFishTimeout

BODY = {"product_name": "Kaban", "image_base64": "x", "technical_specs": "GSM: 450, yün",
        "unit_cost": "25", "total_production_budget": 100000, "target_regions": ["EU", "MENA", "CIS"]}


class FlakyEngine(MockSimulationEngine):
    """MENA bölgesinde yavaş modeli taklit eder."""

    def __init__(self, bad=("MENA",)):
        super().__init__(latency_s=0)
        self.bad = bad
        self.max_concurrency = 1

    async def simulate_region(self, card, region, unit_cost, brand=None, fx_rates=None, progress=None):
        if progress:
            await progress({"stage": "interview", "region": region, "detail": "röportaj"})
        if region in self.bad:
            raise MiroFishTimeout("/api/simulation/interview/batch zaman aşımı (504): 等待IPC响应超时")
        return await super().simulate_region(card, region, unit_cost, brand, fx_rates)


def test_failed_region_does_not_fail_run(isolated_app):
    isolated_app[get_engine] = lambda: FlakyEngine()
    r = TestClient(app).post("/api/predict", json=BODY)
    assert r.status_code == 200, r.text
    data = r.json()
    assert {x["region"] for x in data["regional_breakdown"]} == {"EU", "CIS"}
    assert data["failed_regions"][0]["region"] == "MENA"
    assert "zaman aşımı" in data["failed_regions"][0]["reason"]
    assert any("MENA" in n for n in data["methodology_notes"])
    assert data["total_produced_qty"] > 0


def test_all_regions_failed_returns_502(isolated_app):
    isolated_app[get_engine] = lambda: FlakyEngine(bad=("EU", "MENA", "CIS"))
    r = TestClient(app).post("/api/predict", json=BODY)
    assert r.status_code == 502 and "Hiçbir bölge" in r.json()["detail"]


def test_stream_reports_progress_then_result(isolated_app):
    isolated_app[get_engine] = lambda: FlakyEngine()
    with TestClient(app).stream("POST", "/api/predict/stream", json=BODY) as r:
        events = [json.loads(line) for line in r.iter_lines() if line]
    stages = [(e.get("stage"), e.get("region")) for e in events if e["type"] == "progress"]
    assert ("region_start", "EU") in stages and ("region_failed", "MENA") in stages
    assert events[-1]["type"] == "result"
    assert events[-1]["data"]["failed_regions"][0]["region"] == "MENA"


def test_stream_reports_error_event(isolated_app):
    isolated_app[get_engine] = lambda: FlakyEngine(bad=("EU", "MENA", "CIS"))
    with TestClient(app).stream("POST", "/api/predict/stream", json=BODY) as r:
        events = [json.loads(line) for line in r.iter_lines() if line]
    assert events[-1]["type"] == "error" and events[-1]["status"] == 502
