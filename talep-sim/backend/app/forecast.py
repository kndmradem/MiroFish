"""30/60/90/120 günlük satış potansiyeli.

Model: 120 günlük talep potansiyeli = ulaşılabilir kitle x ilgi (ajan talep skoru) x fiyat kabulü (ajan
fiyat eşiklerinden satın alma olasılığı) x dönüşüm tavanı. Satış hızı moda ürünleri gibi öne yüklüdür
(üstel doygunluk); fiyat "ideal" bölgeden pahalıya kaydıkça hız düşer. Satış üretim miktarıyla sınırlanır.

Ajan cevabından gelenler: talep skoru ve fiyat kabulü. Varsayım olanlar: kitle büyüklüğü, dönüşüm tavanı,
zaman sabiti ve düşük/yüksek senaryo çarpanları. Hepsi sonuçta açıkça listelenir.
"""
import math
from decimal import Decimal
from typing import List, Optional

from .models import (Assumptions, BrandProfile, ForecastMilestone, ForecastPoint, RegionPredictionResult,
                     SalesForecast)

# 120 günde ulaşılabilir hedef kitle varsayımı (kişi); marka bilinirliğiyle ölçeklenir. Kendi verinle ez.
DEFAULT_AUDIENCE = {"EU": 100_000, "US": 100_000, "MENA": 70_000, "CIS": 40_000, "TR": 50_000}
HORIZON = 120
TAU_BASE = 45.0            # gün; fiyat ideal bölgedeyken satışın %63'ü bu sürede gelir
LOW_MULT, HIGH_MULT = 0.65, 1.4
MILESTONES = (30, 60, 90, 120)


def _price_position(best: float, zones: list) -> float:
    """Fiyatın ideal bölgeye göre konumu: 0 ideal, 1 pahalı bölgenin üst sınırı; üstü daha da yavaş."""
    ideal = next((z for z in zones if z.key == "ideal"), None)
    exp = next((z for z in zones if z.key == "expensive"), None)
    if ideal is None or exp is None or exp.high is None:
        return 0.0
    hi_ideal, hi_exp = float(ideal.high), float(exp.high)
    if best <= hi_ideal:
        return 0.0
    return (best - hi_ideal) / max(1e-9, hi_exp - hi_ideal)


class DemandModel:
    """Talep modeli: 120 gün kümülatif talep = taban (kitle x ilgi x dönüşüm) x fiyat kabulü x zaman payı."""

    def __init__(self, region, demand_score, price, zones, brand, assumptions):
        base_audience = DEFAULT_AUDIENCE.get(region, 150_000)
        strength = (brand.regional_strength.get(region, 50) / 50) if brand else 1.0
        user = assumptions.audience.get(region)
        self.user_audience = user is not None
        self.audience = user if user is not None else int(base_audience * max(0.4, min(1.8, strength)))
        self.base = self.audience * (demand_score / 100) * assumptions.conversion_ceiling_pct / 100
        self.tau = TAU_BASE * (1 + 0.6 * _price_position(price, zones))

    def share(self, t: float) -> float:
        return (1 - math.exp(-t / self.tau)) / (1 - math.exp(-HORIZON / self.tau))

    def demand(self, t0: float, t1: float, prob: float, mult: float = 1.0) -> float:
        """[t0, t1] günleri arasında, verilen satın alma olasılığıyla stoksuz talep."""
        return self.base * prob * mult * (self.share(t1) - self.share(t0))


def forecast_sales(region: str, demand_score: int, price: float, purchase_prob: float, zones: list,
                   qty: int, returns_pct: float, brand: Optional[BrandProfile],
                   assumptions: Assumptions) -> SalesForecast:
    model = DemandModel(region, demand_score, price, zones, brand, assumptions)
    audience, user_audience, tau = model.audience, model.user_audience, model.tau
    conv = assumptions.conversion_ceiling_pct / 100
    potential = model.base * purchase_prob  # 120. günde, sınırsız stokla
    pos = _price_position(price, zones)
    share = model.share

    def cum_demand(t: int, mult: float) -> float:
        return potential * mult * share(t)

    def sold(t: int, mult: float) -> int:
        return int(min(qty, cum_demand(t, mult)))

    days = list(range(0, HORIZON + 1, 10))
    curve = [ForecastPoint(day=d, demand=int(cum_demand(d, 1)), sold=sold(d, 1),
                           sold_low=sold(d, LOW_MULT), sold_high=sold(d, HIGH_MULT)) for d in days]
    ms: List[ForecastMilestone] = []
    prev = 0
    for d in MILESTONES:
        u = sold(d, 1)
        rev = Decimal(str(round(u * price, 2)))
        ms.append(ForecastMilestone(
            day=d, units_low=sold(d, LOW_MULT), units=u, units_high=sold(d, HIGH_MULT), period_units=u - prev,
            revenue=rev, net_revenue=Decimal(str(round(u * price * (1 - returns_pct / 100), 2))), stock_left=qty - u))
        prev = u
    stockout = next((d for d in range(1, HORIZON + 1) if cum_demand(d, 1) >= qty), None) if qty > 0 else 0
    total_demand = int(cum_demand(HORIZON, 1))
    final = sold(HORIZON, 1)

    notes = [
        f"Ulaşılabilir hedef kitle {audience:,} kişi" + (" (senin girdin)." if user_audience else
                                                          " (varsayım, marka bilinirliğiyle ölçeklendi; kendi verinle değiştir)."),
        f"Dönüşüm tavanı %{assumptions.conversion_ceiling_pct:g}: ilgili ve fiyatı kabul eden kitlenin bu kadarı alıma dönüşür (varsayım).",
        f"Talep skoru {demand_score}/100 ve satın alma olasılığı %{purchase_prob * 100:.0f} ajan cevaplarından gelir.",
        f"Satış hızı öne yüklü (zaman sabiti {tau:.0f} gün); fiyat ideal bölgenin üstündeyse yavaşlar (varsayım).",
        f"Düşük/yüksek senaryo orta talebin x{LOW_MULT:g} ve x{HIGH_MULT:g} katıdır (varsayım aralığı, istatistiksel güven aralığı değil).",
        "Satış üretim miktarıyla sınırlıdır; stok biterse kaçan talep 'kaçan satış' olarak gösterilir.",
        *([f"Talep üretimin üzerinde: stok {stockout}. günde bitiyor, yaklaşık {max(0, total_demand - qty):,} adetlik talep karşılanamıyor; "
           "üretimi artırmak ya da fiyatı yükseltmek değerlendirilebilir."] if stockout and stockout <= 60 else []),
        "Mevsimsellik, kampanya ve rakip etkisi bu temel tahmine dahil değildir.",
    ]
    return SalesForecast(
        milestones=ms, curve=curve, stockout_day=stockout if stockout and stockout <= HORIZON else None,
        leftover_units=qty - final, lost_units=max(0, total_demand - qty),
        sell_through_pct=round(final / qty * 100, 1) if qty else 0.0, audience=audience,
        purchase_prob_pct=round(purchase_prob * 100, 1), assumptions=notes)
