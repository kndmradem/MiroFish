import json
import shutil
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app, get_engine
from app.models import PredictionRequest
from app.panel import calibration as callib
from app.panel.backtest import Actual, BacktestCase, Candidate, compare, pipeline_predictor, promote
from app.panel.calibration import Calibration, Observation, RegionCalibration, fit
from app.panel.drift import DriftMonitor
from app.panel.engine import DirectPanelEngine, PanelUnavailable
from app.panel.library import (DEFAULT_DATA_DIR, LibraryError, PanelStore, PersonaLibrary, freshness_warnings,
                               library_status, sample_panel)
from app.panel.mock_llm import handle
from app.panel.questioner import PanelLLM
from app.services.engine import MockSimulationEngine

REGIONS = ["EU", "MENA", "CIS", "US", "TR"]
BODY = {"product_name": "Kaban", "image_base64": "x", "technical_specs": "GSM: 450, yün",
        "unit_cost": "25", "total_production_budget": 100000, "target_regions": ["EU", "TR"]}
TODAY = date(2026, 10, 26)


class FakeLLMServer:
    """OpenAI uyumlu sunucunun test çifti (app.panel.mock_llm ile aynı cevaplar); istekleri kaydeder."""

    def __init__(self, no_schema=False, broken_first=False, fail=False):
        self.no_schema, self.broken_first, self.fail = no_schema, broken_first, fail
        self.bodies = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.bodies.append(body)
        if self.fail:
            return httpx.Response(500, text="model yüklenemedi")
        code, data = handle(body, self.no_schema, self.broken_first)
        return httpx.Response(code, json=data)


def make_llm(server, **kw) -> PanelLLM:
    return PanelLLM("http://llm.test/v1", "qwen2.5:7b-instruct", client=httpx.AsyncClient(
        transport=httpx.MockTransport(server)), **kw)


def make_engine(server=None, store=None, **kw) -> DirectPanelEngine:
    return DirectPanelEngine(store or PanelStore(), make_llm(server or FakeLLMServer()),
                             MockSimulationEngine(latency_s=0).fuse_product_card, as_of=TODAY, **kw)


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "panel_data"
    shutil.copytree(DEFAULT_DATA_DIR, root)
    return PanelStore(root)


# --- persona kütüphanesi ve bağlam paketleri ------------------------------
def test_bundled_library_loads_all_regions():
    s = PanelStore()
    assert s.active_version() == "v1"
    for r in REGIONS:
        lib = s.personas(r)
        assert lib.region == r and lib.segments and lib.as_of and lib.source and lib.owner
        assert s.context(r, TODAY) is not None


def test_library_rejects_duplicate_segments():
    seg = {"id": "a", "label": "x", "city": "y", "weight": 1}
    with pytest.raises(ValueError):
        PersonaLibrary.model_validate({"region": "EU", "version": "v", "as_of": "2026-01-01", "segments": [seg, seg]})


def test_sampling_is_deterministic_and_follows_weights():
    lib = PanelStore().personas("TR")
    a, b = sample_panel(lib, 20, "ürün"), sample_panel(lib, 20, "ürün")
    assert [(m.segment.id, m.age, m.price_sensitivity) for m in a] == [(m.segment.id, m.age, m.price_sensitivity) for m in b]
    counts = {s.id: sum(m.segment.id == s.id for m in a) for s in lib.segments}
    assert sum(counts.values()) == 20
    assert counts["tr-urban-young"] == 5  # ağırlık 0.25
    # kalibrasyon çarpanı duyarlılığı kaydırır
    hi = sample_panel(lib, 20, "ürün", sensitivity_scale=1.2)
    assert sum(m.price_sensitivity for m in hi) > sum(m.price_sensitivity for m in a)


def test_context_pack_selected_by_date_and_staleness(store):
    ctx_dir = store.root / "context" / "EU"
    newer = json.loads((ctx_dir / "2026-10-26.json").read_text())
    newer.update(version="2027-01", as_of="2027-01-15", verified=True)
    (ctx_dir / "2027-01-15.json").write_text(json.dumps(newer))
    assert store.context("EU", date(2026, 12, 1)).version == "2026-10-taslak"  # geleceğin paketi sızmaz
    assert store.context("EU", date(2027, 2, 1)).version == "2027-01"
    assert store.context("EU", date(2020, 1, 1)) is None
    lib = store.personas("EU")
    old = freshness_warnings(lib, store.context("EU", date(2027, 1, 10)), date(2027, 1, 10))
    assert any("gün önce" in w for w in old)
    assert any("persona seti" in w and "gözden geçirilmeli" not in w for w in old)
    assert any("gözden geçirilmeli" in w for w in freshness_warnings(lib, None, date(2027, 3, 1)))
    assert any("bağlam paketi yok" in w for w in freshness_warnings(lib, None, TODAY))


def test_missing_region_file_is_clear_error(store):
    (store.root / "personas" / "v1" / "CIS.json").unlink()
    with pytest.raises(LibraryError, match="CIS"):
        store.personas("CIS")
    assert "error" in library_status(store, ["CIS"])["CIS"]


# --- yapılandırılmış sorgulama ---------------------------------------------
async def test_guided_json_schema_is_sent_and_parsed():
    server = FakeLLMServer()
    sim = await make_engine(server, panel_size=6).simulate_region(
        {"product_name": "Kaban", "features": {}}, "EU", 25.0)
    assert server.bodies[0]["response_format"]["type"] == "json_schema"
    schema = server.bodies[0]["response_format"]["json_schema"]["schema"]
    assert set(schema["properties"]["ladder"]["required"]) == {str(i) for i in range(1, 10)}
    assert len(server.bodies) == 6 and sim.meta["n_valid"] == 6 and sim.meta["price_source"] == "agents"
    assert sim.meta["engine"] == "panel" and sim.meta["persona_version"] == "v1"
    assert sim.meta["context_as_of"] == "2026-10-26" and len(sim.price_answers) == 6
    assert all(r["segment"] for r in sim.meta["raw_answers"])
    user = server.bodies[0]["messages"][1]["content"]
    assert "GÜNCEL BAĞLAM (2026-10-26" in user and "eskidir" in server.bodies[0]["messages"][0]["content"]


async def test_falls_back_when_server_rejects_schema():
    server = FakeLLMServer(no_schema=True)
    engine = make_engine(server, panel_size=4)
    sim = await engine.simulate_region({"product_name": "Kaban", "features": {}}, "TR", 25.0, fx_rates={"TRY": 42})
    assert engine.llm.guided == "json_object" and sim.meta["n_valid"] == 4
    assert server.bodies[-1]["response_format"] == {"type": "json_object"}
    assert "₺" in server.bodies[-1]["messages"][1]["content"]  # TR için TL karşılığı


async def test_repair_retry_fixes_broken_answers():
    server = FakeLLMServer(broken_first=True)
    sim = await make_engine(server, panel_size=4).simulate_region({"product_name": "Kaban", "features": {}}, "US", 25.0)
    assert sim.meta["n_valid"] == 4 and sim.meta["n_extracted"] == 4
    assert {r["status"] for r in sim.meta["raw_answers"]} == {"repaired"}
    assert len(server.bodies) == 8 and server.bodies[1]["messages"][2]["role"] == "assistant"


async def test_region_unavailable_when_llm_down():
    with pytest.raises(PanelUnavailable) as e:
        await make_engine(FakeLLMServer(fail=True), panel_size=4).simulate_region(
            {"product_name": "Kaban", "features": {}}, "EU", 25.0)
    assert "HTTP 500" in str(e.value) and len(e.value.raw_answers) == 4


async def test_peer_round_is_optional():
    server = FakeLLMServer()
    sim = await make_engine(server, panel_size=4, peer_round=True).simulate_region(
        {"product_name": "Kaban", "features": {}}, "EU", 25.0)
    assert len(server.bodies) == 8 and sim.meta["peer_round"]
    assert "Diğer tüketicilerin" in server.bodies[-1]["messages"][1]["content"]


async def test_calibration_scales_demand_and_prices():
    card = {"product_name": "Kaban", "features": {}}
    base = await make_engine(panel_size=6).simulate_region(card, "EU", 25.0)
    cal = Calibration(regions={"EU": RegionCalibration(demand_scale=0.5, price_scale=1.2, n_obs=8)})
    adj = await make_engine(panel_size=6, calibration=cal).simulate_region(card, "EU", 25.0)
    assert abs(adj.demand_score - base.demand_score / 2) <= 1
    assert adj.price_answers[0].cheap == pytest.approx(base.price_answers[0].cheap * 1.2)


def test_full_api_run_with_panel_engine(isolated_app):
    isolated_app[get_engine] = lambda: make_engine(panel_size=6)
    r = TestClient(app).post("/api/predict", json=BODY)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["engine"] == "panel"
    row = data["regional_breakdown"][0]
    assert row["data_basis"]["context_as_of"] == "2026-10-26"
    assert row["data_basis"]["freshness_warnings"]
    assert row["confidence"]["level"] in ("düşük", "orta")  # kalibre edilmemiş panel 'yüksek' olamaz
    assert any("kalibre" in x for x in row["confidence"]["reasons"])
    assert row["forecast"] and row["price_plan"] and row["campaigns"]
    assert any("persona paneli" in n for n in data["methodology_notes"])
    demand = next(e for e in row["explanations"] if e["key"] == "demand")
    assert "persona paneli" in demand["how"]


def test_panel_status_endpoint():
    r = TestClient(app).get("/api/panel/status")
    assert r.status_code == 200
    data = r.json()
    assert data["active_persona_version"] == "v1" and set(data["regions"]) == set(REGIONS)


# --- kalibrasyon, sapma, backtest -------------------------------------------
def test_fit_shrinks_with_few_observations():
    many = [Observation("EU", 1000, 500, 100, 90) for _ in range(20)]
    few = [Observation("EU", 1000, 500)]
    c_many, c_few = fit(many), fit(few)
    assert 0.5 < c_many.for_region("EU").demand_scale < 0.6
    assert 0.85 < c_few.for_region("EU").demand_scale < 0.95
    assert c_many.for_region("EU").price_scale == pytest.approx(0.9, abs=0.02)
    assert c_few.notes
    # stoğu biten ve tahminden az satan gözlem, talebi düşürmek için kanıt sayılmaz
    assert fit([Observation("TR", 1000, 400, stocked_out=True)]).for_region("TR").demand_scale == 1.0


def test_calibration_roundtrip(tmp_path):
    cal = fit([Observation("EU", 100, 150)], persona_version="v1")
    callib.save(cal, tmp_path / "c.json")
    assert callib.load(tmp_path / "c.json").for_region("EU") == cal.for_region("EU")
    assert callib.load(tmp_path / "yok.json").is_identity


def test_drift_monitor_flags_recent_degradation(tmp_path):
    mon = DriftMonitor(tmp_path / "acc.jsonl")
    for d in (date(2026, 2, 1), date(2026, 3, 1), date(2026, 4, 1)):
        mon.record([Observation("EU", 1000, 950), Observation("TR", 500, 480)], "eski", "v1", d)
    for d in (date(2026, 9, 1), date(2026, 9, 20), date(2026, 10, 10)):
        mon.record([Observation("EU", 1000, 500), Observation("TR", 500, 490)], "yeni", "v1", d)
    rep = mon.report(TODAY)
    assert rep["EU"]["drift"] and any("sistematik olarak yüksek" in x for x in rep["EU"]["reasons"])
    assert not rep["TR"]["drift"]


def _case(i: int, truth_scale: float) -> BacktestCase:
    req = PredictionRequest(**{**BODY, "product_name": f"Ürün {i}", "target_regions": ["EU"]})
    return BacktestCase(f"Ürün {i}", date(2026, 1 + i, 1), req, {"EU": Actual(units=1000 * truth_scale)})


async def test_compare_promotes_more_accurate_version(store):
    shutil.copytree(store.root / "personas" / "v1", store.root / "personas" / "v2")
    cases = [_case(i, 1.0) for i in range(6)]

    async def predictor(case, cand, cal):  # v1 hep 1.8 kat fazla ve dağınık, v2 gerçeğe yakın
        noise = 1 + (0.3 if int(case.product.split()[-1]) % 2 else -0.3)
        units = 1800 * noise if cand.persona_version == "v1" else 1050
        return {"EU": (units * cal.for_region("EU").demand_scale, 100.0)}

    results = await compare(cases, [Candidate("v1", "v1"), Candidate("v2", "v2")], predictor)
    assert results[0].persona_version == "v2"
    v1 = next(r for r in results if r.persona_version == "v1")
    assert v1.calibrated_wape_pct < v1.raw_wape_pct  # kalibrasyon sistematik fazlayı düzeltir
    ok, msg = promote(store, results)
    assert ok and store.active_version() == "v2"
    assert callib.load(store.root / "calibration.json").persona_version == "v2"
    # aktif sürümden yeterince iyi olmayan aday terfi etmez
    ok, msg = promote(store, sorted(results, key=lambda r: r.persona_version == "v2"), min_gain_pct=1e9)
    assert not ok and store.active_version() == "v2"


async def test_pipeline_predictor_runs_full_chain(store):
    pred = pipeline_predictor(store, make_llm(FakeLLMServer()), MockSimulationEngine(latency_s=0).fuse_product_card,
                              panel_size=4, min_valid=2)
    out = await pred(_case(1, 1.0), Candidate("v1", "v1"), Calibration())
    units, price = out["EU"]
    assert units > 0 and price > 25


def _write_csv(path, header, rows):
    path.write_text("\n".join([",".join(header)] + [",".join(map(str, r)) for r in rows]) + "\n", encoding="utf-8")


def test_erp_cases_from_contract_csvs(tmp_path):
    from app.panel.erp_cases import load_cases
    _write_csv(tmp_path / "urunler.csv", ["urun_kodu", "urun_adi", "kategori", "ilk_satis_tarihi", "birim_maliyet",
                                          "maliyet_para_birimi", "kumas_karisimi", "kalip", "desen"],
               [["U1", "Yün kaban", "kaban", "2025-09-01", "840", "TRY", "%80 yün", "oversize", "duz"]])
    _write_csv(tmp_path / "skular.csv", ["sku_kodu", "urun_kodu"], [["U1-M", "U1"]])
    _write_csv(tmp_path / "magazalar.csv", ["magaza_kodu", "ulke", "para_birimi"],
               [["M-IST", "TR", "TRY"], ["M-BER", "DE", "EUR"]])
    _write_csv(tmp_path / "doviz_kurlari.csv", ["tarih", "para_birimi", "try_karsiligi"],
               [["2025-08-01", "USD", "42"], ["2025-08-01", "EUR", "48"]])
    _write_csv(tmp_path / "satislar.csv", ["tarih", "magaza_kodu", "sku_kodu", "adet", "net_tutar", "kampanya_kodu"],
               [["2025-09-02", "M-IST", "U1-M", 2, 4200, ""], ["2025-10-01", "M-IST", "U1-M", 1, 1500, "K1"],
                ["2025-09-10", "M-BER", "U1-M", 3, 300, ""], ["2026-03-01", "M-IST", "U1-M", 9, 1, ""]])
    [case] = load_cases(tmp_path)
    assert case.launch_date == date(2025, 9, 1) and float(case.request.unit_cost) == 20.0
    assert case.actuals["TR"].units == 3  # 120 gün dışındaki satış sayılmaz
    assert case.actuals["TR"].full_price == pytest.approx(50.0)  # kampanyasız: 4200 TL / 2 / 42
    assert case.actuals["EU"].full_price == pytest.approx(100 * 48 / 42)
    assert case.request.target_regions == ["EU", "TR"]
