"""Üretim bütçesi dağıtım algoritması (teknik doküman §5)."""
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Dict, List


@dataclass(frozen=True)
class RegionSignal:
    region: str
    demand_score: int  # 0-100
    optimal_price: Decimal


@dataclass(frozen=True)
class RegionAllocation:
    region: str
    weight: Decimal
    budget: Decimal
    quantity: int


def allocate_production_budget(
    signals: List[RegionSignal],
    total_budget: Decimal,
    unit_cost: Decimal,
) -> Dict[str, RegionAllocation]:
    """Toplam bütçeyi bölgelere talep x birim kâr ağırlığıyla dağıtır.

    1. Ağırlık = Talep Skoru x (Optimal Fiyat - Maliyet)
    2. Toplam Ağırlık = Σ Ağırlık
    3. Bölge Bütçesi = (Ağırlık / Toplam Ağırlık) x Toplam Bütçe
    4. Adet = floor(Bölge Bütçesi / Birim Maliyet)

    Fiyatı maliyetin altında/eşit kalan bölge zarar ettireceği için ağırlığı 0
    kabul edilir ve üretim almaz. Hiçbir bölge kârlı değilse hepsi 0 döner.
    """
    if unit_cost <= 0:
        raise ValueError("unit_cost must be positive")
    total_budget = Decimal(total_budget)

    weights = {
        s.region: max(Decimal(0), Decimal(s.demand_score) * (s.optimal_price - unit_cost))
        for s in signals
    }
    total_weight = sum(weights.values(), Decimal(0))

    result: Dict[str, RegionAllocation] = {}
    for s in signals:
        w = weights[s.region]
        budget = (w / total_weight * total_budget) if total_weight > 0 else Decimal(0)
        budget = budget.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        qty = int((budget / unit_cost).to_integral_value(rounding=ROUND_DOWN))
        result[s.region] = RegionAllocation(s.region, w, budget, qty)
    return result
