"""Van Westendorp fiyat duyarlılığı analizi.

Her ajan dört eşik fiyat verir: çok ucuz (kaliteden şüphelenir), ucuz,
pahalı, çok pahalı (asla almaz). Bunlardan kümülatif eğriler ve kesişim
noktaları hesaplanır.
"""
import math
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable, List, Sequence, Tuple

from .models import PricePoint, PriceStep, PriceZone, VanWestendorpResult


@dataclass(frozen=True)
class AgentPriceAnswer:
    too_cheap: float
    cheap: float
    expensive: float
    too_expensive: float


def _money(x: float) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def bandwidth(n: int) -> float:
    """Az ajanda eşikler basamaklı (tek tek sıçrayan) eğri verir; eşikleri log-fiyatta yumuşatırız.

    Örneklem küçüldükçe her ajanın eşiği daha belirsiz sayılır (log-normal), 30+ ajanda yumuşatma kapanır.
    """
    return 0.0 if n >= 30 else 0.18 if n < 6 else 0.14 if n < 12 else 0.10


def quality_of(n: int) -> Tuple[str, str]:
    if n < 6:
        return "low", f"Yalnızca {n} ajan: eğriler yumuşatıldı, bölgeler yaklaşık değerdir (aralık olarak okuyun)."
    if n < 12:
        return "medium", f"{n} ajan: eğriler hafif yumuşatıldı; bölge sınırları ±%10-15 oynayabilir."
    return "high", f"{n} ajan: örneklem makul; yine de gerçek müşteri verisi değil, simülasyon çıktısıdır."


def _ge(t: float, p: float, sigma: float) -> float:
    """P(eşik >= p): sigma=0 ise kesin karşılaştırma, değilse log-normal yumuşatma."""
    if sigma <= 0:
        return 1.0 if t >= p else 0.0
    z = (math.log(p) - math.log(max(t, 1e-9))) / sigma
    return 0.5 * math.erfc(z / math.sqrt(2))


def _curves(answers: Sequence[AgentPriceAnswer], p: float, sigma: float | None = None) -> Tuple[float, float, float, float]:
    n = len(answers)
    sg = bandwidth(n) if sigma is None else sigma
    if p <= 0:
        return 1.0, 1.0, 0.0, 0.0
    return (
        sum(_ge(a.too_cheap, p, sg) for a in answers) / n,
        sum(_ge(a.cheap, p, sg) for a in answers) / n,
        sum(1 - _ge(a.expensive, p, sg) for a in answers) / n,
        sum(1 - _ge(a.too_expensive, p, sg) for a in answers) / n,
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
    lo = min(a.too_cheap for a in answers) * 0.6
    hi = max(a.too_expensive for a in answers) * 1.3
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
    quality, quality_note = quality_of(len(answers))
    result = VanWestendorpResult(
        zones=price_zones(pmc, opp, ipp, pme),
        quality=quality,
        quality_note=quality_note,
        optimal_price_point=_money(opp),
        indifference_price_point=_money(ipp),
        acceptable_range_low=_money(pmc),
        acceptable_range_high=_money(pme),
        curve=curve,
    )
    return result, _money(best)


MIN_ZONE_PCT = 0.04  # her bölge en az fiyatın %4'ü kadar geniş olmalı (sıfır genişlikli bölge olmaz)


def price_zones(pmc: float, opp: float, ipp: float, pme: float) -> List[PriceZone]:
    """Fiyat eksenini, Van Westendorp kesişimlerinden türeyen 5 bölgeye ayırır (boşluk ve sıfır genişlik kalmaz)."""
    ideal_lo, ideal_hi = sorted((opp, ipp))
    mid = max((ideal_lo + ideal_hi) / 2, 1e-6)
    w = mid * MIN_ZONE_PCT
    ideal_hi = max(ideal_hi, ideal_lo + w)
    pmc = min(pmc, ideal_lo - w)
    pme = max(pme, ideal_hi + w)
    pmc = max(pmc, 0.0 + w / 2)
    return [
        PriceZone(key="too_cheap", label="Çok ucuz", low=_money(0), high=_money(pmc),
                  description="Çoğu ajan bu fiyatta kaliteden şüphelenir."),
        PriceZone(key="cheap", label="Ucuz / avantajlı", low=_money(pmc), high=_money(ideal_lo),
                  description="Kabul edilebilir ama kâr bırakılıyor; satışı hızlandırır."),
        PriceZone(key="ideal", label="İdeal bölge", low=_money(ideal_lo), high=_money(ideal_hi),
                  description="Ucuz-pahalı dengesi; en az direnç."),
        PriceZone(key="expensive", label="Pahalı ama kabul edilebilir", low=_money(ideal_hi), high=_money(pme),
                  description="Marjı yüksek, satış hızı düşer; kararsız müşteri artar."),
        PriceZone(key="too_expensive", label="Çok pahalı", low=_money(pme), high=None,
                  description="Çoğu ajan bu fiyatın üstünde almaz."),
    ]


def verdict(a: AgentPriceAnswer, p: float) -> int:
    """Ajanın eşiklerine göre bir fiyata kararı: 0 şüpheli, 1 uygun, 2 pahalı, 3 çok pahalı."""
    if p <= a.too_cheap:
        return 0
    if p < a.expensive:
        return 1
    return 2 if p < a.too_expensive else 3


def steps_from_answers(answers: Sequence[AgentPriceAnswer], prices: Sequence[float]) -> List[PriceStep]:
    out = []
    for p in prices:
        counts = [0, 0, 0, 0]
        for a in answers:
            counts[verdict(a, p)] += 1
        out.append(PriceStep(price=_money(p), suspicious=counts[0], fair=counts[1], expensive=counts[2],
                             too_expensive=counts[3], n=len(answers), basis="threshold"))
    return out


def steps_from_votes(ladder: Sequence[float], votes: Sequence[Sequence[int]]) -> List[PriceStep]:
    """Merdiven oylarından (her ajanın her basamağa verdiği 0..3 karar) adım tablosu."""
    out = []
    for i, p in enumerate(ladder):
        counts = [0, 0, 0, 0]
        n = 0
        for v in votes:
            if v[i] is not None:
                counts[v[i]] += 1
                n += 1
        out.append(PriceStep(price=_money(p), suspicious=counts[0], fair=counts[1], expensive=counts[2],
                             too_expensive=counts[3], n=n, basis="ladder"))
    return out


def purchase_probability(answers: Sequence[AgentPriceAnswer], p: float) -> float:
    """Fiyatta satın alma olasılığı: çok ucuz/çok pahalı bulan almaz, pahalı bulan yarı olasılıkla alır."""
    tc, _, ex, te = _curves(answers, p)
    return max(0.0, min(1.0, 1 - tc - te - 0.5 * (ex - te)))
