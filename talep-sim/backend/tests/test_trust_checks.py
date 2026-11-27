"""Güven kontrolleri: önerilen fiyat ya da adet ürünleri ayırt etmiyorsa (maliyetten / kitle varsayımından türemişse) uyarı."""
from decimal import Decimal

from app.collection.models import ItemRegion
from app.collection.summary import trust_checks
from app.panel import prompts
from app.pricing import AgentPriceAnswer, analyze, anchor_note


def _reg(price, units, region="EU"):
    return ItemRegion(region=region, demand=55, optimal_price=price, range_low=price * 0.8, range_high=price * 1.2,
                      margin_pct=50, return_pct=20, demand_units=units)


def test_cost_anchored_prices_and_flat_units_are_flagged():
    costs = {"a": 10.0, "b": 20.0, "c": 5.0}
    regs = {s: [_reg(c * 2.45, 394)] for s, c in costs.items()}          # Suwen koşusunda görülen desen
    keys = [k for k, _ in trust_checks(regs, costs)]
    assert keys == ["fiyat", "adet"]


def test_discriminating_panel_is_not_flagged():
    costs = {"a": 10.0, "b": 20.0, "c": 5.0}
    regs = {"a": [_reg(30, 500)], "b": [_reg(41, 150)], "c": [_reg(16, 900)]}
    assert trust_checks(regs, costs) == []


def test_too_few_items_not_judged():
    assert trust_checks({"a": [_reg(20, 100)], "b": [_reg(40, 100)]}, {"a": 10, "b": 20}) == []


def test_anchor_note_downgrades_when_opp_sits_on_ladder_center():
    ans = [AgentPriceAnswer(15, 22, 33, 45) for _ in range(12)] + [AgentPriceAnswer(14, 21, 32, 44) for _ in range(12)]
    vw, _ = analyze(ans, 10)
    ref = float(vw.optimal_price_point)
    flagged = anchor_note(vw, ref, "agents")
    assert flagged.quality != "high" and "merkezine" in flagged.quality_note
    assert anchor_note(vw, ref * 2, "agents").quality_note == vw.quality_note       # merkezden uzak: not yok
    assert anchor_note(vw, ref, "brand_fallback").quality_note == vw.quality_note   # yedek eşik: zaten kural


def test_prompt_does_not_tell_panel_the_expected_price():
    from app.models import BrandProfile
    b = BrandProfile(name="X", price_multiple=3.0)
    p = prompts.user_prompt({"product_name": "Body"}, None, [10, 20, 30], b, "TR", unit_cost=Decimal("10"))
    assert "genelde" not in p and "civarında satar" not in p
