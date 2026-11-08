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


def test_tiny_sample_zones_are_ordered_with_minimum_width():
    from app.pricing import AgentPriceAnswer, analyze
    answers = [AgentPriceAnswer(40, 55, 60, 61), AgentPriceAnswer(40, 55, 60, 61)]  # neredeyse çakışık eşikler
    vw, best = analyze(answers, 25.0)
    zs = vw.zones
    assert vw.quality == "low" and "ajan" in vw.quality_note
    for a, b in zip(zs, zs[1:]):
        assert a.high == b.low
    for z in zs[1:4]:
        assert float(z.high) > float(z.low) * 1.02
    curve = vw.curve
    assert all(x.too_cheap >= y.too_cheap for x, y in zip(curve, curve[1:]))  # yumuşatılmış, monoton eğri
    assert all(0 <= p.too_expensive <= 1 for p in curve)


def _sig(region, demand, price=60.0):
    from app.allocation import DemandSignal
    return DemandSignal(region, demand, price)


def test_balanced_allocation_equalizes_sell_through_when_budget_is_short():
    from app.allocation import allocate_by_sales_velocity, allocate_production_budget, RegionSignal
    # EU talebi düşük ama kâr ağırlığı yüksek; MENA/TR talebi yüksek
    sigs = [_sig("EU", 444), _sig("MENA", 1200), _sig("TR", 900)]
    res = allocate_by_sales_velocity(sigs, Decimal(40000), Decimal("25"), "balanced")
    q = {r: a.quantity for r, a in res.allocations.items()}
    assert sum(q.values()) * 25 <= 40000
    cover = {r: q[r] / s.demand_units for r, s in zip(q, sigs)}
    assert max(cover.values()) - min(cover.values()) < 0.1  # kapsama oranları dengeli
    assert not res.budget_exceeds_demand


def test_balanced_does_not_overproduce_when_budget_exceeds_demand():
    from app.allocation import allocate_by_sales_velocity
    sigs = [_sig("EU", 300), _sig("TR", 200)]
    res = allocate_by_sales_velocity(sigs, Decimal(100000), Decimal("25"), "balanced")
    q = {r: a.quantity for r, a in res.allocations.items()}
    assert q["EU"] <= 300 * 1.05 and q["TR"] <= 200 * 1.05 and q["EU"] >= 280
    assert res.budget_exceeds_demand and res.unspent > Decimal(80000)


def test_unprofitable_region_gets_nothing_in_balanced():
    from app.allocation import allocate_by_sales_velocity
    res = allocate_by_sales_velocity([_sig("EU", 500, 20.0), _sig("TR", 500, 60.0)], Decimal(10000), Decimal("25"))
    assert res.allocations["EU"].quantity == 0 and res.allocations["TR"].quantity > 0


def test_profit_objective_overproduces_more_than_balanced():
    from app.allocation import allocate_by_sales_velocity
    sigs = [_sig("EU", 300, 120.0)]
    bal = allocate_by_sales_velocity(sigs, Decimal(100000), Decimal("25"), "balanced").allocations["EU"].quantity
    prof = allocate_by_sales_velocity(sigs, Decimal(100000), Decimal("25"), "profit").allocations["EU"].quantity
    assert prof >= bal


def test_predict_returns_allocation_view_and_objective_switch():
    client = TestClient(app)
    body = {"product_name": "K", "image_base64": "iVBORw0KGgo=", "technical_specs": "GSM: 450g, yün",
            "unit_cost": "25.50", "total_production_budget": 5000000, "target_regions": ["EU", "MENA"]}
    d = client.post("/api/predict", json=body).json()
    assert d["allocation_objective"] == "balanced" and "bütçe" in d["allocation_note"].lower()
    for x in d["regional_breakdown"]:
        a = x["allocation"]
        assert a["units"] == x["recommended_production_qty"] and a["leftover"] >= 0 and a["why"]
    assert d["total_produced_qty"] * 25.5 < 5000000
    p = client.post("/api/predict", json={**body, "allocation_objective": "profit"}).json()
    assert p["regional_breakdown"][0]["allocation"]["objective"] == "profit"
