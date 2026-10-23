import json

import httpx
import pytest

from app.models import PredictionRequest
from app.pricing import analyze
from app.services.engine import MockSimulationEngine
from app.services.mirofish_client import MiroFishClient, MiroFishError
from app.services.mirofish_engine import MiroFishSimulationEngine, parse_agent_answer
from app.services.personas import SEED_CONSUMERS, build_seed_document, region_of


def test_parse_agent_answer_accepts_wrapped_json():
    text = 'Tabii: {"interest": 80, "too_cheap": 20, "cheap": 40, "expensive": 80, "too_expensive": 120, "objection": "Kalın"} bu kadar.'
    a = parse_agent_answer(text)
    assert a == {"interest": 80.0, "prices": [20.0, 40.0, 80.0, 120.0], "objection": "Kalın"}


@pytest.mark.parametrize("text", [
    "", "no json",
    '{"interest": 50, "too_cheap": 90, "cheap": 40, "expensive": 80, "too_expensive": 120}',  # sırasız
    '{"interest": 50, "cheap": 40}',  # eksik
])
def test_parse_agent_answer_rejects_bad(text):
    assert parse_agent_answer(text) is None


def test_region_mapping_from_seed_names_and_cities():
    assert region_of("Fatima Al Mansoori, marketing manager") == "MENA"
    assert region_of("Someone living in Novosibirsk") == "CIS"
    assert region_of("bir kişi") is None
    assert "Lena Hoffmann" in build_seed_document()


class FakeMiroFish:
    """MiroFish Flask API'sinin test çifti; çağrı sırasını kaydeder."""

    def __init__(self, bad_json=False, fail_first=False):
        self.fail_first = fail_first
        self.interview_calls = 0
        self.calls = []
        self.bad_json = bad_json
        self.started = False
        names = [(i, p.split(",")[0]) for i, p in enumerate(p for ps in SEED_CONSUMERS.values() for p in ps)]
        self.profiles = [{"user_id": i, "name": n, "bio": "", "persona": ""} for i, n in names]

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append(path)
        ok = lambda data: httpx.Response(200, json={"success": True, "data": data})
        if path == "/api/graph/ontology/generate":
            return ok({"project_id": "proj_1"})
        if path == "/api/graph/build":
            return ok({"task_id": "t1"})
        if path == "/api/graph/task/t1":
            return ok({"status": "completed"})
        if path == "/api/simulation/create":
            return ok({"simulation_id": "sim_1"})
        if path == "/api/simulation/prepare":
            return ok({"task_id": "t2"})
        if path == "/api/simulation/prepare/status":
            return ok({"status": "ready", "already_prepared": True})
        if path == "/api/simulation/sim_1/profiles":
            return ok({"profiles": self.profiles})
        if path == "/api/simulation/start":
            self.started = True
            return ok({"runner_status": "running"})
        if path == "/api/simulation/env-status":
            return ok({"env_alive": self.started})
        if path == "/api/simulation/interview/batch":
            body = json.loads(request.content)
            self.interview_calls += 1
            broken = self.bad_json or (self.fail_first and self.interview_calls == 1)
            reply = "bozuk" if broken else json.dumps({
                "interest": 70, "too_cheap": 30, "cheap": 55, "expensive": 90, "too_expensive": 130,
                "objection": "Kumaş kalın"})
            return ok({"result": {"results": {
                f"reddit_{i['agent_id']}": {"agent_id": i["agent_id"], "response": reply}
                for i in body["interviews"]}}})
        return httpx.Response(404, json={"success": False, "error": path})


def make_engine(tmp_path, fake):
    client = MiroFishClient("http://mf", httpx.AsyncClient(
        base_url="http://mf", transport=httpx.MockTransport(fake.handler)))
    mock = MockSimulationEngine(latency_s=0)
    return MiroFishSimulationEngine(client, mock.fuse_product_card, str(tmp_path / "world.json"),
                                    poll_s=0, env_wait_s=1)


REQ = PredictionRequest(product_name="Kaban", image_base64="x", technical_specs="GSM: 450, yün",
                        unit_cost="25", total_production_budget=10000, target_regions=["EU", "CIS"])


async def test_world_built_once_and_regions_interviewed(tmp_path):
    fake = FakeMiroFish()
    engine = make_engine(tmp_path, fake)
    card = await engine.fuse_product_card(REQ)
    eu, cis = [await engine.simulate_region(card, r, 25.0) for r in ("EU", "CIS")]

    assert fake.calls.count("/api/graph/ontology/generate") == 1  # ikinci bölge dünyayı yeniden kurmaz
    assert eu.demand_score == 70 and len(eu.price_answers) == 5
    assert eu.objections == ["Kumaş kalın"]
    vw, best = analyze(cis.price_answers, 25.0)
    assert vw.acceptable_range_low < best <= vw.acceptable_range_high


async def test_saved_world_reused_after_restart(tmp_path):
    fake = FakeMiroFish()
    card = await make_engine(tmp_path, fake).fuse_product_card(REQ)
    await make_engine(tmp_path, fake).simulate_region(card, "EU", 25.0)
    fake.calls.clear()
    await make_engine(tmp_path, fake).simulate_region(card, "MENA", 25.0)
    assert "/api/graph/ontology/generate" not in fake.calls


async def test_unparseable_agent_answers_raise(tmp_path):
    engine = make_engine(tmp_path, FakeMiroFish(bad_json=True))
    card = await engine.fuse_product_card(REQ)
    with pytest.raises(MiroFishError):
        await engine.simulate_region(card, "EU", 25.0)


async def test_invalid_answers_are_retried_once(tmp_path):
    fake = FakeMiroFish(fail_first=True)
    engine = make_engine(tmp_path, fake)
    card = await engine.fuse_product_card(REQ)
    sim = await engine.simulate_region(card, "EU", 25.0)
    assert fake.interview_calls == 2 and len(sim.price_answers) == 5


async def test_stale_world_without_turkey_is_rebuilt(tmp_path):
    fake = FakeMiroFish()
    (tmp_path / "world.json").write_text(json.dumps(
        {"project_id": "p", "simulation_id": "sim_1", "agents": {"EU": [0]}, "seed_hash": "eskiseed"}))
    fake.started = True  # ortam canlı görünse bile seed değiştiği için yeniden kurulmalı
    engine = make_engine(tmp_path, fake)
    card = await engine.fuse_product_card(REQ)
    sim = await engine.simulate_region(card, "TR", 25.0, None, {"TRY": 42})
    assert "/api/graph/ontology/generate" in fake.calls and len(sim.price_answers) == 5
