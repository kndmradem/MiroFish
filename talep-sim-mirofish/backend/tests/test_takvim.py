"""Perakende takvimi: veri dosyaları, takvim turu ve takvime bağlı kampanya planı."""
import json
import shutil

import pytest
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app, get_engine
from app.models import Assumptions
from app.takvim import data as td
from app.takvim import fit as tf
from app.takvim import plan as tp

from .test_brand import _scenario_inputs
from .test_panel import FakeLLMServer, make_engine

START = date(2026, 11, 9)
BODY = {"product_name": "Kadın triko hırka", "image_base64": "x", "technical_specs": "%70 yün, kadın triko",
        "unit_cost": "20", "total_production_budget": 60000, "target_regions": ["TR", "EU"],
        "assumptions": {"calendar_start": START.isoformat()}}


def _copy(tmp_path) -> Path:
    d = tmp_path / "takvim"
    shutil.copytree(td.DEFAULT_DIR, d)
    return d


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# --- veri dosyaları ----------------------------------------------------------
def test_bundled_calendar_loads_without_problems_and_filters_by_region():
    t = td.load()
    assert not t.problems and len(t.events) > 20
    tr = [e.code for e in t.window("TR", START, 120)]
    assert "BLACK_FRIDAY" in tr and "SOLDES_KIS" not in tr            # Fransa'ya özel satır TR'de yok
    eu = t.window("EU", START, 120)
    soldes = next(e for e in eu if e.code == "SOLDES_KIS")
    assert soldes.scope == "FR" and soldes.country_only               # ülke -> bölge eşlemesi veri dosyasından
    assert not any(e.verified for e in t.events)                       # taslak: hiçbiri doğrulanmadı


def test_calendar_is_data_not_code(tmp_path):
    d = _copy(tmp_path)
    rows = (d / "perakende_takvimi.csv").read_text(encoding="utf-8").splitlines()
    rows.append("YENI_GUN,Marka Günü,2026,TR,2026-12-01,2026-12-03,0,hediye,genel,,,elle,marka,evet,Adem,2026-11-09")
    rows.append("BOZUK,Bozuk,2026,XX,2026-12-01,2026-12-03,0,hediye,,,,,,hayir,,")
    rows.append("BOZUK2,Bozuk tür,2026,TR,2026-12-01,2026-12-03,0,yok_tur,,,,,,hayir,,")
    (d / "perakende_takvimi.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    t = td.load(str(d))
    new = next(e for e in t.window("TR", START, 120) if e.code == "YENI_GUN")
    assert new.verified and new.start == date(2026, 12, 1)
    assert len(t.problems) == 2 and any("XX" in p for p in t.problems) and any("yok_tur" in p for p in t.problems)


def test_campaign_catalog_moved_to_data_file_unchanged():
    snap = json.loads((Path(__file__).parent / "fixtures" / "catalog_snapshot.json").read_text(encoding="utf-8"))
    assert json.loads(json.dumps(td.load_catalog())) == snap


# --- takvim turu ---------------------------------------------------------------
def test_rule_fit_uses_segment_synonyms():
    t = td.load()
    syn = tf.load_synonyms()
    anne = next(e for e in t.events if e.code == "ANNELER_GUNU" and e.region == "TR")
    assert tf.rule_fit(anne, tf.product_text({"product_name": "Kadın ipek şal"}), syn) == 0.8
    assert tf.rule_fit(anne, tf.product_text({"product_name": "Erkek kargo pantolon"}), syn) == 0.25
    bf = next(e for e in t.events if e.code == "BLACK_FRIDAY")
    assert tf.rule_fit(bf, "herhangi", syn) == 0.5


def test_parse_is_tolerant():
    a = tf.parse('cevap: {"fit": {"A": 3, "b": "2", "C": 9}, "wait": "Bekleyeceğim", "comment": "ok"}', list("ABC"), True)
    assert a["fit"] == {"A": 3, "B": 2, "C": 3} and a["wait"] == "bekle"
    assert tf.parse("bilmiyorum", list("AB"), False) is None


def test_wait_question_targets_biggest_sale_event():
    t = td.load()
    w = tf.wait_event_of(t.window("TR", START, 120), t)
    assert w.code == "BLACK_FRIDAY"                                    # 11.11 daha erken ama daha küçük


# --- plan ------------------------------------------------------------------------
def _plan(qty, fits=None, **assump):
    t = td.load()
    answers, vw, best, dm, fc, a = _scenario_inputs(qty=qty, **assump)
    evs = t.window("TR", START, 120)
    fits = fits or tf.FitResult({e.code: tf.EventFit(e.code, 0.8, "test") for e in evs},
                                wait_event="BLACK_FRIDAY", wait_share=0.4, wait_basis="test", wait_n=10)
    return tp.build_calendar_plan("TR", dm, answers, best, 25.0, qty, 20.0, a, t, evs, fits, START), best, vw, dm, answers, a


def test_overstock_plan_uses_calendar_campaigns_and_respects_constraints():
    cp, best, *_ = _plan(100_000, max_campaigns=2, min_campaign_gap_days=21, residual_value_pct=0)
    rec = next(o for o in cp.options if o.recommended)
    none = next(o for o in cp.options if o.key == "none")
    assert rec.campaigns and float(rec.total_value) >= float(none.total_value)
    assert rec.units > none.units
    for o in cp.options:
        assert len(o.campaigns) <= 2 and o.units + o.leftover_units == 100_000
        assert o.units_low <= o.units <= o.units_high
        cs = sorted(o.campaigns, key=lambda c: c.day_from)
        assert all(b.day_from - a.day_to - 1 >= 21 for a, b in zip(cs, cs[1:]))
        for c in cs:
            assert float(c.price) >= 25.0 * 1.05 and c.discount_pct in (20.0, 30.0, 40.0)
            assert c.date_from >= START
    assert cp.warnings and any("Doğrulanmamış" in w for w in cp.warnings)
    assert any("Bekleme" in x for x in cp.assumptions)


def test_scarce_stock_prefers_no_discount():
    cp, *_ = _plan(50)
    rec = next(o for o in cp.options if o.recommended)
    assert not rec.campaigns and "kampanyasız" in cp.verdict


def test_back_to_back_discounts_shrink_advertised_discount():
    cp, *_ = _plan(100_000, max_campaigns=3, min_campaign_gap_days=0, discount_steps=[30])
    for o in cp.options:
        cs = sorted(o.campaigns, key=lambda c: c.day_from)
        for a, b in zip(cs, cs[1:]):
            if b.day_from - a.day_to <= 30:
                assert b.advertised_discount_pct < b.discount_pct


def test_price_plan_phases_follow_calendar():
    cp, best, vw, dm, answers, a = _plan(100_000, residual_value_pct=0)
    from app.scenarios import _zone_of
    pp = tp.to_price_plan(cp, dm, answers, vw, best, 25.0, 100_000, 20.0, a, _zone_of)
    rec = next(o for o in cp.options if o.recommended)
    assert any("kampanyası" in p.name for p in pp.phases)
    assert pp.phases[0].day_from == 0 and pp.phases[-1].day_to == 120
    assert sum(p.units for p in pp.phases) == rec.units
    assert all(p.day_from < p.day_to for p in pp.phases)


def test_no_events_only_no_campaign_option():
    t = td.load()
    answers, vw, best, dm, fc, a = _scenario_inputs(qty=1000)
    cp = tp.build_calendar_plan("TR", dm, answers, best, 25.0, 1000, 20.0, a, t, [], tf.FitResult({}), date(2030, 1, 1))
    assert [o.key for o in cp.options] == ["none"] and not cp.options[0].campaigns and cp.options[0].recommended
    assert any("etkinlik yok" in w for w in cp.warnings)


# --- uçtan uca -------------------------------------------------------------------
def test_api_with_mock_engine_labels_mock(client):
    row = client.post("/api/predict", json=BODY).json()["regional_breakdown"][0]
    cp = row["calendar_plan"]
    assert cp["engine"] == "mock" and cp["events"] and all(e["fit_basis"] == "mock" for e in cp["events"])
    assert any("sahte" in w for w in cp["warnings"])


def test_api_with_panel_engine_asks_calendar_round(isolated_app):
    server = FakeLLMServer()
    isolated_app[get_engine] = lambda: make_engine(server=server, panel_size=4)
    r = TestClient(app).post("/api/predict", json=BODY)
    assert r.status_code == 200, r.text
    prompts = [b for b in server.bodies if tf.MARKER in b["messages"][1]["content"]]
    assert len(prompts) == 4 * 2                                     # 4 kişi x 2 bölge
    assert "Black Friday" in prompts[0]["messages"][1]["content"]
    row = r.json()["regional_breakdown"][0]
    cp = row["calendar_plan"]
    assert cp["engine"] == "panel" and any(e["fit_basis"] == "ajan" and e["fit_n"] > 0 for e in cp["events"])
    assert cp["wait_event"] == "BLACK_FRIDAY" and cp["wait_basis"] == "ajan"


def test_calendar_round_can_be_disabled(client):
    body = {**BODY, "assumptions": {**BODY["assumptions"], "calendar_plan": False}}
    row = client.post("/api/predict", json=body).json()["regional_breakdown"][0]
    assert row["calendar_plan"] is None
    assert [p["name"] for p in row["price_plan"]["phases"]] == ["Lansman", "İlk kampanya sonrası", "Stok eritme"]


def test_hybrid_engine_uses_panel_for_calendar_round():
    import asyncio
    t = td.load()
    evs = t.window("TR", START, 120)

    class Hybrid:
        def __init__(self):
            self.panel = make_engine(panel_size=3)
            self.mirofish = object()

    res = asyncio.run(tf.evaluate(Hybrid(), {"product_name": "Kadın triko"}, "TR", evs, t, None, 40.0, None))
    assert res.engine == "panel" and "MiroFish'te takvim sorusu yok" in res.note

    class OnlyMiroFish:
        pass

    res = asyncio.run(tf.evaluate(OnlyMiroFish(), {"product_name": "Kadın triko"}, "TR", evs, t, None, 40.0, None))
    assert res.engine == "kural" and all(f.basis == "kural varsayımı" for f in res.fits.values())
