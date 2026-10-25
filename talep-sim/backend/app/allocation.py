"""Üretim bütçesi dağıtım algoritması (teknik doküman §5)."""
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Dict, List, Optional


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


# --- Satış hızına göre dengeli dağıtım ---------------------------------------------------------------
# Talep belirsizdir: orta talebin bu çarpanlarda gerçekleştiği varsayılır (varsayım, istatistiksel aralık değil).
DEMAND_SCENARIOS = ((0.6, 0.1), (0.8, 0.2), (1.0, 0.4), (1.2, 0.2), (1.4, 0.1))
OBJECTIVES = ("balanced", "profit", "blended")
# Üretilen son birimin satılma olasılığı bu eşiğin altına düşünce üretim durur (hedef: orta talebi karşılamak).
STOP_P = {"balanced": 0.5, "blended": 0.4, "profit": 0.0}


@dataclass(frozen=True)
class DemandSignal:
    region: str
    demand_units: float      # 120 günde beklenen (orta senaryo) brüt satış adedi, stok sınırsızken
    net_price: float         # iade ve iade lojistiği düşüldükten sonra satış başına gelir ($)
    return_pct: float = 0.0
    restock_share: float = 0.7


@dataclass(frozen=True)
class BalancedResult:
    allocations: Dict[str, RegionAllocation]
    objective: str
    total_demand: float
    budget_exceeds_demand: bool   # bütçe tüm talebi karşılamaya yetecekten fazla: daha az üretmek önerilir
    unspent: Decimal


def p_sells(demand: float, q: float) -> float:
    """Q. birimden sonraki bir birimin satılma olasılığı: talep > q olan senaryoların ağırlığı."""
    return sum(w for m, w in DEMAND_SCENARIOS if demand * m > q)


def allocate_by_sales_velocity(
    signals: List[DemandSignal], total_budget: Decimal, unit_cost: Decimal, objective: str = "balanced",
) -> BalancedResult:
    """Bütçeyi bölgelerin 120 günlük beklenen satışına göre dengeli dağıtır.

    Açgözlü yinelemeli yaklaşım: her adımda bir parti üretim, o an "bir sonraki birimi satılma olasılığı" en yüksek
    bölgeye verilir (azalan getiri: stok arttıkça olasılık düşer). Böylece stoğu kalan bölgeden birim alınıp talebi
    karşılanmamış bölgeye kayar ve bölgelerin satış oranları (satılan/üretilen) birbirine yaklaşır.
    - balanced: tek ölçüt satılma olasılığı; son birimin satılma olasılığı %50'nin altına düşünce üretim durur.
    - profit: beklenen marjinal kâr (olasılık x net fiyat - maliyet) pozitif oldukça üretir.
    - blended: ikisinin ortalaması; %40 eşiği.
    Net fiyatı maliyetin altındaki bölge üretim almaz. Bütçe tüm talebi aşıyorsa kalan bütçe harcanmaz.
    """
    if unit_cost <= 0:
        raise ValueError("unit_cost must be positive")
    if objective not in OBJECTIVES:
        raise ValueError(f"objective must be one of {OBJECTIVES}")
    cost = float(unit_cost)
    units_cap = int(Decimal(total_budget) / unit_cost)
    live = [s for s in signals if s.demand_units > 0 and s.net_price > cost]
    q = {s.region: 0 for s in signals}
    step = max(1, units_cap // 500)
    stop_p = STOP_P[objective]
    max_np = max((s.net_price for s in live), default=1.0)

    def score(s: DemandSignal) -> Optional[float]:
        p = p_sells(s.demand_units, q[s.region])
        profit = p * s.net_price - cost
        if p <= 0 or p < stop_p or profit <= 0:
            return None
        if objective == "profit":
            return profit
        if objective == "balanced":
            # olasılık basamaklı olduğundan eşitlikte önce kapsama oranı düşük bölge, sonra kârlı bölge
            return p - 1e-3 * q[s.region] / s.demand_units + 1e-9 * s.net_price
        return 0.5 * p + 0.5 * profit / max_np - 1e-3 * q[s.region] / s.demand_units

    used = 0
    while used < units_cap:
        best, best_s = None, None
        for s in live:
            sc = score(s)
            if sc is not None and (best_s is None or sc > best_s):
                best, best_s = s, sc
        if best is None:
            break
        n = min(step, units_cap - used)
        q[best.region] += n
        used += n

    total_demand = sum(s.demand_units for s in signals)
    out = {}
    for s in signals:
        budget = (Decimal(q[s.region]) * unit_cost).quantize(Decimal("0.01"))
        out[s.region] = RegionAllocation(s.region, Decimal(str(round(s.demand_units, 2))), budget, q[s.region])
    spent = sum((a.budget for a in out.values()), Decimal(0))
    return BalancedResult(out, objective, total_demand, used < units_cap and bool(live), Decimal(total_budget) - spent)
