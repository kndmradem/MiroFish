import json

import httpx
import pytest

from app.models import PredictionRequest
from app.pricing import analyze
from app.services.engine import MockSimulationEngine
from app.services.mirofish_client import MiroFishClient, MiroFishError
from app.services.mirofish_engine import MiroFishSimulationEngine, RegionUnavailable, parse_agent_answer
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

    def __init__(self, bad_json=False, fail_first=False, timeout_calls=(), always_timeout=False):
        self.timeout_calls = set(timeout_calls)
        self.always_timeout = always_timeout
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
            self.uploaded_seed = request.content.decode(errors="ignore")
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
            if self.always_timeout or self.interview_calls in self.timeout_calls:
                return httpx.Response(504, json={"success": False, "error": "等待IPC响应超时"})
            broken = self.bad_json or (self.fail_first and self.interview_calls == 1)
            reply = "bozuk" if broken else json.dumps({
                "interest": 70, "too_cheap": 30, "cheap": 55, "expensive": 90, "too_expensive": 130,
                "objection": "Kumaş kalın"})
            return ok({"result": {"results": {
                f"reddit_{i['agent_id']}": {"agent_id": i["agent_id"], "response": reply}
                for i in body["interviews"]}}})
        return httpx.Response(404, json={"success": False, "error": path})


def make_engine(tmp_path, fake, **kw):
    client = MiroFishClient("http://mf", httpx.AsyncClient(
        base_url="http://mf", transport=httpx.MockTransport(fake.handler)))
    mock = MockSimulationEngine(latency_s=0)
    return MiroFishSimulationEngine(client, mock.fuse_product_card, str(tmp_path / "world.json"),
                                    poll_s=0, env_wait_s=1, **kw)


REQ = PredictionRequest(product_name="Kaban", image_base64="x", technical_specs="GSM: 450, yün",
                        unit_cost="25", total_production_budget=10000, target_regions=["EU", "CIS"])


async def test_world_built_once_and_regions_interviewed(tmp_path):
    fake = FakeMiroFish()
    engine = make_engine(tmp_path, fake)
    card = await engine.fuse_product_card(REQ)
    eu, cis = [await engine.simulate_region(card, r, 25.0, scope=["EU", "CIS"]) for r in ("EU", "CIS")]

    assert fake.calls.count("/api/graph/ontology/generate") == 1  # ikinci bölge dünyayı yeniden kurmaz
    assert eu.demand_score == 70 and len(eu.price_answers) == 5
    assert eu.objections == ["Kumaş kalın"]
    vw, best = analyze(cis.price_answers, 25.0)
    assert vw.acceptable_range_low < best <= vw.acceptable_range_high


async def test_saved_world_reused_after_restart(tmp_path):
    fake = FakeMiroFish()
    card = await make_engine(tmp_path, fake).fuse_product_card(REQ)
    await make_engine(tmp_path, fake).simulate_region(card, "EU", 25.0, scope=["EU", "MENA"])
    fake.calls.clear()
    await make_engine(tmp_path, fake).simulate_region(card, "MENA", 25.0, scope=["EU", "MENA"])
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
    assert fake.interview_calls == 3 and len(sim.price_answers) == 5  # 2 grup + 1 yeniden deneme


async def test_stale_world_without_turkey_is_rebuilt(tmp_path):
    fake = FakeMiroFish()
    (tmp_path / "world.json").write_text(json.dumps(
        {"project_id": "p", "simulation_id": "sim_1", "agents": {"EU": [0]}, "seed_hash": "eskiseed"}))
    fake.started = True  # ortam canlı görünse bile seed değiştiği için yeniden kurulmalı
    engine = make_engine(tmp_path, fake)
    card = await engine.fuse_product_card(REQ)
    sim = await engine.simulate_region(card, "TR", 25.0, None, {"TRY": 42})
    assert "/api/graph/ontology/generate" in fake.calls and len(sim.price_answers) == 5


async def test_interviews_are_chunked_into_small_batches(tmp_path):
    fake = FakeMiroFish()
    engine = make_engine(tmp_path, fake, batch_size=2)
    card = await engine.fuse_product_card(REQ)
    sim = await engine.simulate_region(card, "EU", 25.0)
    assert fake.interview_calls == 3  # 5 ajan -> 2+2+1
    assert sim.meta["n_valid"] == 5


async def test_timeout_is_retried_and_succeeds(tmp_path):
    fake = FakeMiroFish(timeout_calls=[1])
    engine = make_engine(tmp_path, fake)
    card = await engine.fuse_product_card(REQ)
    sim = await engine.simulate_region(card, "EU", 25.0)
    assert sim.meta["n_valid"] == 5 and sim.meta["n_timed_out"] == 0


async def test_partial_result_when_one_chunk_times_out(tmp_path):
    # batch 2: grup1 iki kez zaman aşımı (çağrı 1,2) -> atlanır; kalan 3 ajan cevaplar.
    fake = FakeMiroFish(timeout_calls=[1, 2])
    engine = make_engine(tmp_path, fake, batch_size=2, retries=0)
    card = await engine.fuse_product_card(REQ)
    sim = await engine.simulate_region(card, "EU", 25.0)
    assert sim.meta["n_valid"] == 3 and sim.meta["n_timed_out"] == 2


async def test_stuck_model_aborts_region_with_clear_error(tmp_path):
    fake = FakeMiroFish(always_timeout=True)
    engine = make_engine(tmp_path, fake, batch_size=1)
    card = await engine.fuse_product_card(REQ)
    with pytest.raises(RegionUnavailable, match="zaman aşımına"):
        await engine.simulate_region(card, "EU", 25.0)
    assert fake.interview_calls == 4  # 2 grup x (1 + 1 yeniden deneme), sonra vazgeçer


async def test_world_contains_only_selected_regions(tmp_path):
    fake = FakeMiroFish()
    engine = make_engine(tmp_path, fake)
    card = await engine.fuse_product_card(REQ)
    await engine.simulate_region(card, "EU", 25.0, scope=["EU", "TR"])
    assert "EU paneli" in fake.uploaded_seed and "TR paneli" in fake.uploaded_seed
    for other in ("MENA paneli", "CIS paneli", "US paneli"):
        assert other not in fake.uploaded_seed
    world = json.loads((tmp_path / "world.json").read_text())
    (w,) = world.values()
    assert set(w["agents"]) == {"EU", "TR"}


async def test_different_selection_builds_separate_world(tmp_path):
    fake = FakeMiroFish()
    engine = make_engine(tmp_path, fake)
    card = await engine.fuse_product_card(REQ)
    await engine.simulate_region(card, "EU", 25.0, scope=["EU"])
    await engine.simulate_region(card, "EU", 25.0, scope=["EU", "US"])
    assert fake.calls.count("/api/graph/ontology/generate") == 2
    await engine.simulate_region(card, "EU", 25.0, scope=["US", "EU"])  # sıra önemsiz, yeniden kurulmaz
    assert fake.calls.count("/api/graph/ontology/generate") == 2


async def test_world_build_reports_progress_and_uses_long_timeout(tmp_path):
    fake = FakeMiroFish()
    engine = make_engine(tmp_path, fake)
    card = await engine.fuse_product_card(REQ)
    events = []

    async def progress(ev):
        events.append(ev)

    await engine.simulate_region(card, "TR", 25.0, scope=["TR"], progress=progress)
    world = [e["detail"] for e in events if e["stage"] == "world"]
    assert len(world) == 6 and "10-30 dk" in world[0] and "TR" in world[0]
    assert engine.client.build_timeout >= 1800


async def test_ontology_read_timeout_is_clear_error(tmp_path):
    def handler(request):
        raise httpx.ReadTimeout("")
    client = MiroFishClient("http://mf", httpx.AsyncClient(base_url="http://mf", transport=httpx.MockTransport(handler)))
    with pytest.raises(MiroFishError, match="ollama ps"):
        await client.generate_ontology("a.md", "x", "y", "z")
