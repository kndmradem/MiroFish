from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.mallprofile import overture
from app.mallprofile.catalog import MallStore, catalog_path
from app.mallprofile.models import Tenant
from app.mallprofile.signals import CLAMP, MIN_KNOWN, build_profile
from app.mallprofile.tiers import TierMap
from app.panel.library import PanelStore

TIERS = TierMap.load(Path(__file__).resolve().parents[1] / "panel_data" / "marka_katmanlari.csv")


def test_tier_match_handles_noisy_names():
    assert TIERS.match("Abdullah Kiğılı Azerbaijan") == ("Kiğılı", "mass")
    assert TIERS.match(None, "Cacharel Türkiye") == ("Cacharel", "upper_mass")
    assert TIERS.match("Beymen Club Kanyon")[0] == "Beymen Club"   # en uzun eşleşme
    assert TIERS.match("Hugo Boss")[0] == "Hugo Boss"
    assert TIERS.match("The Gap Cafe") is None                         # kısa ad yalnızca başta
    assert TIERS.match("Bilinmeyen Butik") is None


def _row(i, cat, name, x, y, conf=0.9, brand=None):
    return {"id": f"id{i}", "names": {"primary": name}, "basic_category": cat, "confidence": conf,
            "operating_status": "open", "brand": {"names": {"primary": brand}} if brand else None,
            "bbox": {"xmin": x, "xmax": x, "ymin": y, "ymax": y}}


def test_build_catalog_dedupes_and_skips_store_records():
    rows = [_row(1, "shopping_mall", "Alfa AVM", 29.0, 41.0),
            _row(2, "shopping_mall", "Alfa Meydan", 29.001, 41.0, conf=0.7),          # ~85 m, ortak kelime
            _row(3, "shopping_mall", "Beta Center", 29.0015, 41.0005, conf=0.8),     # ~140 m, ayrı AVM
            _row(4, "shopping_mall", "Zara", 29.0, 41.0, conf=0.95, brand="Zara")]   # mağaza kaydı
    rows += [_row(10 + i, "fashion_and_apparel_store", f"Mağaza {i}", 29.0 + i * 1e-4, 41.0, brand="Zara" if i == 0 else None)
             for i in range(6)]
    cat = overture.build_catalog(rows, "TR", "Test", (28.9, 40.9, 29.1, 41.1), tiers=TIERS)
    names = {m.name: m for m in cat.malls}
    assert "Zara" not in names
    assert "Alfa Meydan" in names["Alfa AVM"].aliases
    assert "Beta Center" in names
    assert names["Alfa AVM"].apparel_count == 6


def _tenants(brands):
    return [Tenant(name=b, brand=b) for b in brands]


LUX = ["Gucci", "CHANEL", "Dior", "Prada", "Bulgari", "Cartier", "Burberry"]
BUDGET = ["LC Waikiki", "DeFacto", "H&M", "Flo", "Deichmann", "Splash", "Primark"]


def test_luxury_mall_shifts_panel_to_high_income_within_bounds():
    lib = PanelStore().personas("TR")
    p = build_profile(name="X", ulke="TR", sehir="Istanbul", region="TR", tenants=_tenants(LUX), tiers=TIERS,
                      lib=lib, city_idx=0.3)
    assert p.price_segment == "lüks"
    by_band = {s.income_band: s.multiplier for s in p.segments}
    assert by_band["orta-üst"] > 1 > by_band["orta-alt"]
    assert all(CLAMP[0] <= s.multiplier <= CLAMP[1] for s in p.segments)
    assert abs(sum(s.mall_weight for s in p.segments) - 1) < 0.01
    assert any(s.key == "visitors" and s.basis == "bilinmiyor" for s in p.signals)


def test_too_few_known_brands_keeps_region_panel():
    lib = PanelStore().personas("TR")
    p = build_profile(name="X", ulke="TR", sehir="Istanbul", region="TR",
                      tenants=_tenants(LUX[: MIN_KNOWN - 1] + ["Bilinmeyen"]), tiers=TIERS, lib=lib, city_idx=0.3)
    assert p.price_index is None
    assert all(s.multiplier == 1 for s in p.segments)
    assert any("en az" in w for w in p.warnings)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app.mallprofile import routes
    rows = [_row(1, "shopping_mall", "Lüks AVM", 29.0, 41.0), _row(2, "shopping_mall", "Halk AVM", 29.05, 41.0),
            _row(3, "shopping_mall", "Orta AVM", 29.0, 41.05)]
    for i, b in enumerate(LUX):
        rows.append(_row(100 + i, "fashion_and_apparel_store", b, 29.0 + i * 1e-4, 41.0, brand=b))
    for i, b in enumerate(BUDGET):
        rows.append(_row(200 + i, "fashion_and_apparel_store", b, 29.05 + i * 1e-4, 41.0, brand=b))
    for i, b in enumerate(["Zara", "Mango", "Koton", "Mavi", "Bershka", "Gap", "Nike"]):
        rows.append(_row(300 + i, "fashion_and_apparel_store", b, 29.0 + i * 1e-4, 41.05, brand=b))
    cat = overture.build_catalog(rows, "TR", "Teststadt", (28.9, 40.9, 29.1, 41.1), tiers=TIERS)
    path = catalog_path(tmp_path, "TR", "Teststadt")
    path.parent.mkdir(parents=True)
    path.write_text(cat.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(routes, "_store", MallStore(tmp_path))
    from app.main import app
    return TestClient(app)


def test_routes_search_profile_manual_and_fallback(client):
    hits = client.get("/api/malls/search", params={"ulke": "TR", "sehir": "teststadt", "q": "lüks"}).json()
    assert hits[0]["name"] == "Lüks AVM"
    prof = client.post("/api/malls/profile", json={"ulke": "TR", "sehir": "Teststadt", "mall_id": hits[0]["id"],
                                                   "brand_tier": "luxury"}).json()
    assert prof["price_segment"] == "lüks" and prof["city_price_index"] is not None
    assert len(prof["rivals"]) == len(LUX)
    assert any("onaylanmadı" in w for w in prof["warnings"])
    man = client.post("/api/malls/profile", json={"ulke": "SA", "sehir": "Yok", "manual": {
        "name": "Elle", "tenants": [", ".join(BUDGET)], "visitors_yearly": 1e6, "visitors_source": "AVM bülteni"}}).json()
    assert man["manual"] and man["price_segment"] == "ekonomik"
    assert any(s["key"] == "visitors" and s["basis"] == "kullanıcı girdisi" for s in man["signals"])
    assert any("kataloğu yok" in w for w in man["warnings"])
    assert client.post("/api/malls/profile", json={"ulke": "TR", "sehir": "Yok", "mall_id": "x"}).status_code == 404
    assert client.get("/api/malls/search", params={"ulke": "TR", "sehir": "Yok"}).json() == []
