from decimal import Decimal

from fastapi.testclient import TestClient

from app.allocation import RegionSignal, allocate_production_budget
from app.main import app


def test_weighted_allocation_matches_spec_formula():
    # Ağırlıklar: EU 80*(60-25)=2800, MENA 50*(95-25)=3500, CIS 70*(40-25)=1050 -> toplam 7350
    res = allocate_production_budget(
        [RegionSignal("EU", 80, Decimal("60")), RegionSignal("MENA", 50, Decimal("95")),
         RegionSignal("CIS", 70, Decimal("40"))],
        Decimal(100000), Decimal("25"),
    )
    assert res["EU"].budget == Decimal("38095.23")
    assert res["EU"].quantity == 1523  # floor(38095.23 / 25)
    assert res["MENA"].quantity == 1904
    assert res["CIS"].quantity == 571
    assert sum(a.budget for a in res.values()) <= 100000


def test_unprofitable_region_gets_nothing():
    res = allocate_production_budget(
        [RegionSignal("EU", 90, Decimal("20")), RegionSignal("US", 40, Decimal("50"))],
        Decimal(10000), Decimal("25"),
    )
    assert res["EU"].quantity == 0
    assert res["US"].quantity == 400


def test_all_unprofitable_returns_zero():
    res = allocate_production_budget([RegionSignal("EU", 90, Decimal("10"))], Decimal(10000), Decimal("25"))
    assert res["EU"].quantity == 0 and res["EU"].budget == 0


def test_predict_endpoint_end_to_end():
    client = TestClient(app)
    body = {
        "product_name": "Kışlık Oversize Yün Kaban",
        "image_base64": "iVBORw0KGgo=",
        "technical_specs": "GSM: 450g, %80 Yün %20 Polyamid, Su itici astar.",
        "unit_cost": "25.50",
        "total_production_budget": 100000,
        "target_regions": ["EU", "MENA", "CIS"],
    }
    r = client.post("/api/predict", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    rows = {x["region"]: x for x in data["regional_breakdown"]}
    assert set(rows) == {"EU", "MENA", "CIS"}
    # Yün + ağır kaban: soğuk iklim talebi sıcak iklimden yüksek olmalı
    assert rows["CIS"]["demand_score_100"] > rows["MENA"]["demand_score_100"]
    assert data["total_produced_qty"] == sum(x["recommended_production_qty"] for x in rows.values())
    for x in rows.values():
        assert len(x["key_objections"]) == 3
        assert Decimal(x["optimal_sale_price"]) > Decimal("25.50")
    # Aynı girdi aynı sonucu vermeli (deterministik mock)
    again = client.post("/api/predict", json=body).json()
    assert again["regional_breakdown"] == data["regional_breakdown"]
