from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import Settings
from app.newstore import Candidate, LocationProfile, estimate, load_profiles, store_stats


def _csv(path, header, rows):
    path.write_text("\n".join([",".join(header)] + [",".join(map(str, r)) for r in rows]) + "\n", encoding="utf-8")


STORES = [  # kod, ülke, şehir, tip, m2, para, günlük ciro (yerel), kapanış
    ("M-IST", "TR", "Istanbul", "avm", 500, "TRY", 42_000, ""),
    ("M-ANK", "TR", "Ankara", "avm", 400, "TRY", 25_200, ""),
    ("M-IZM", "TR", "Izmir", "cadde", 300, "TRY", 12_600, ""),
    ("M-DXB", "AE", "Dubai", "avm", 500, "USD", 1_500, ""),
    ("M-RUH", "SA", "Riyadh", "avm", 400, "USD", 1_000, "2025-12-31"),
]
PROFILES = [("TR", "Istanbul", 15600000, 15000), ("TR", "Ankara", 5800000, 13000), ("TR", "Izmir", 4500000, 12500),
            ("AE", "Dubai", 3600000, 50000), ("SA", "Riyadh", 7000000, 32000), ("SA", "Jeddah", 4700000, 32000)]


@pytest.fixture
def data(tmp_path):
    _csv(tmp_path / "magazalar.csv", ["magaza_kodu", "kanal", "ulke", "sehir", "lokasyon_tipi", "metrekare",
                                      "acilis_tarihi", "kapanis_tarihi", "para_birimi"],
         [[c, "magaza", u, s, t, m, "2024-01-01", k, p] for c, u, s, t, m, p, _, k in STORES]
         + [["O-TR", "online", "TR", "Istanbul", "online", "", "2020-01-01", "", "TRY"]])
    _csv(tmp_path / "doviz_kurlari.csv", ["tarih", "para_birimi", "try_karsiligi"], [["2024-01-01", "USD", "42"]])
    rows = []
    for c, *_rest in STORES:
        daily = _rest[5]
        for i in range(0, 540, 3):  # 2024-01-01'den itibaren 3 günde bir, 3 günlük ciro
            rows.append([(date(2024, 1, 1) + timedelta(days=i)).isoformat(), c, "SKU", 1, daily * 3])
    rows.append(["2024-03-01", "O-TR", "SKU", 1, 10**9])  # online kanal sayılmaz
    _csv(tmp_path / "satislar.csv", ["tarih", "magaza_kodu", "sku_kodu", "adet", "net_tutar"], rows)
    _csv(tmp_path / "prof.csv", ["ulke", "sehir", "nufus", "kisi_basi_gelir_usd", "kaynak_url", "tarih"],
         [[u, s, n, g, "https://stat.example.org/x", "2026-01-01"] for u, s, n, g in PROFILES])
    return tmp_path


def test_store_stats_use_mature_period_and_usd(data):
    stats, notes = store_stats(data)
    by = {s.code: s for s in stats}
    assert set(by) == {"M-IST", "M-ANK", "M-IZM", "M-DXB", "M-RUH"}  # online yok, kapanan dahil
    assert by["M-IST"].annual_usd == pytest.approx(42_000 / 42 * 365, rel=0.02)
    assert by["M-DXB"].annual_usd == pytest.approx(1_500 * 365, rel=0.02)
    assert by["M-RUH"].closed and notes == []


def test_known_city_vs_new_region(data):
    stats, notes = store_stats(data)
    prof = load_profiles(data / "prof.csv")
    jed = estimate(Candidate(ulke="SA", sehir="Jeddah", metrekare=400), stats, prof, data_notes=notes)
    assert jed.own_data == "ülke" and jed.low_usd < jed.annual_revenue_usd < jed.high_usd
    assert jed.analogs[0].magaza in ("M-RUH", "M-ANK")
    assert any("kapanmış" in w for w in jed.warnings)
    ath = estimate(Candidate(ulke="GR", sehir="Athens", lokasyon_tipi="cadde", metrekare=300), stats, prof)
    assert ath.own_data == "yok" and ath.confidence == "düşük"
    assert ath.warnings[0].startswith("Bu bölgede (EU) kendi mağaza verin yok")
    assert any("lokasyon profili (dış veri) yok" in w for w in ath.warnings)
    # bölge verisi yokken aralık, bilinen ülkedekinden göreli olarak daha geniş
    assert ath.high_usd / ath.low_usd > jed.high_usd / jed.low_usd


def test_extrapolation_is_flagged(data):
    stats, _ = store_stats(data)
    big = LocationProfile(ulke="US", sehir="New York", nufus=8.3e6, kisi_basi_gelir_usd=85000, kaynak_url="https://x.org")
    est = estimate(Candidate(ulke="US", sehir="New York", metrekare=300, profil=big), stats, load_profiles(data / "prof.csv"))
    assert any("aralığının dışında" in w for w in est.warnings) and est.confidence == "düşük"


def test_missing_fx_is_reported(data, tmp_path):
    (data / "doviz_kurlari.csv").unlink()
    stats, notes = store_stats(data)
    assert stats == [] and "M-DXB (USD)" in notes[0]  # USD kuru olmadan hiçbir mağaza USD'ye çevrilemez
    stats, notes = store_stats(data, {"USD": 42})
    assert len(stats) == 5


def test_api_endpoint(data, monkeypatch):
    monkeypatch.setattr(main, "settings", Settings(newstore_erp_dir=str(data), newstore_profiles=str(data / "prof.csv")))
    c = TestClient(main.app)
    r = c.post("/api/new-store/estimate", json={"ulke": "SA", "sehir": "Jeddah", "metrekare": 400})
    assert r.status_code == 200, r.text
    assert r.json()["own_data"] == "ülke" and r.json()["analogs"]
    assert len(c.get("/api/new-store/locations").json()) == len(PROFILES)
    monkeypatch.setattr(main, "settings", Settings(newstore_erp_dir=None))
    assert c.post("/api/new-store/estimate", json={"ulke": "SA", "sehir": "Jeddah", "metrekare": 400}).status_code == 400
