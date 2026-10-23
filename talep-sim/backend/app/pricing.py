"""Van Westendorp fiyat duyarlılığı analizi.

Her ajan dört eşik fiyat verir: çok ucuz (kaliteden şüphelenir), ucuz,
pahalı, çok pahalı (asla almaz). Bunlardan kümülatif eğriler ve kesişim
noktaları hesaplanır.
"""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable, List, Sequence, Tuple

from .models import PricePoint, VanWestendorpResult


@dataclass(frozen=True)
class AgentPriceAnswer:
    too_cheap: float
    cheap: float
    expensive: float
    too_expensive: float


def _money(x: float) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _curves(answers: Sequence[AgentPriceAnswer], p: float) -> Tuple[float, float, float, float]:
    n = len(answers)
    return (
        sum(a.too_cheap >= p for a in answers) / n,
        sum(a.cheap >= p for a in answers) / n,
        sum(a.expensive <= p for a in answers) / n,
        sum(a.too_expensive <= p for a in answers) / n,
    )


def _crossing(grid: List[float], f: Callable[[float], float], g: Callable[[float], float]) -> float:
    """f azalan, g artan iki eğrinin kesiştiği fiyat (doğrusal interpolasyon)."""
    prev_p, prev_d = grid[0], f(grid[0]) - g(grid[0])
    if prev_d <= 0:
        return prev_p
    for p in grid[1:]:
        d = f(p) - g(p)
        if d <= 0:
            return prev_p + (p - prev_p) * prev_d / (prev_d - d)
        prev_p, prev_d = p, d
    return grid[-1]


def analyze(answers: Sequence[AgentPriceAnswer], unit_cost: float, steps: int = 60) -> Tuple[VanWestendorpResult, Decimal]:
    """Van Westendorp sonucunu ve en kârlı satış fiyatını döner.

    En kârlı fiyat: kabul edilebilir aralıkta (PMC..PME) beklenen birim kârı
    (fiyat - maliyet) x satın alma olasılığı en yüksek olan fiyat. Fiyatı
    'çok ucuz' ya da 'çok pahalı' bulan ajan almaz; 'pahalı' bulan yarı
    olasılıkla alır.
    """
    if not answers:
        raise ValueError("answers must not be empty")
    lo = min(a.too_cheap for a in answers) * 0.8
    hi = max(a.too_expensive for a in answers) * 1.15
    grid = [lo + (hi - lo) * i / steps for i in range(steps + 1)]
    fine_grid = [lo + (hi - lo) * i / 1000 for i in range(1001)]

    tc = lambda p: _curves(answers, p)[0]
    ch = lambda p: _curves(answers, p)[1]
    ex = lambda p: _curves(answers, p)[2]
    te = lambda p: _curves(answers, p)[3]

    opp = _crossing(fine_grid, tc, te)
    ipp = _crossing(fine_grid, ch, ex)
    pmc = _crossing(fine_grid, tc, ex)
    pme = _crossing(fine_grid, ch, te)

    fine = [pmc + (pme - pmc) * i / 100 for i in range(101)] if pme > pmc else [opp]
    best = max(fine, key=lambda p: (p - unit_cost) * (1 - tc(p) - te(p) - 0.5 * (ex(p) - te(p))))

    curve = [
        PricePoint(price=_money(p), too_cheap=round(a, 3), cheap=round(b, 3),
                   expensive=round(c, 3), too_expensive=round(d, 3))
        for p in grid
        for a, b, c, d in [_curves(answers, p)]
    ]
    result = VanWestendorpResult(
        optimal_price_point=_money(opp),
        indifference_price_point=_money(ipp),
        acceptable_range_low=_money(pmc),
        acceptable_range_high=_money(pme),
        curve=curve,
    )
    return result, _money(best)
