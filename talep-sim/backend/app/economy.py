"""Bölgesel ekonomik bağlam: alım gücü, kur ve enflasyon etkisi.

Fiyat bantları USD cinsinden hesaplanır. Türkiye gibi yüksek enflasyonlu ve kur riski taşıyan
pazarlarda ek olarak fiyata duyarlılık artırılır, yerel para karşılığı gösterilir ve kur şoku
senaryosu hesaplanır. Marka bilgisi içermez; tüm değerler varsayımdır ve metinlerde belirtilir.
"""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, Optional

DEFAULT_USD_TRY = 42.0  # Örnek varsayılan kur; kullanıcı arayüzden günceller.
FX_SHOCK_PCT = 10.0     # "TL %10 değer kaybederse" senaryosu


@dataclass(frozen=True)
class RegionEconomy:
    currency: Optional[str]            # yerel para birimi kodu (gösterim için), yoksa None
    sensitivity_adj: float             # marka fiyat duyarlılığına eklenen düzeltme
    context: str                       # ajan promptlarına eklenen ekonomik bağlam (Türkçe)
    assumptions: tuple                 # açıklamalara eklenen varsayımlar


REGION_ECONOMY: Dict[str, RegionEconomy] = {
    "TR": RegionEconomy(
        currency="TRY",
        sensitivity_adj=0.15,
        context=("Türkiye'de yüksek enflasyon ve kur dalgalanması var; alım gücün uluslararası pazarlara göre düşük. "
                 "Fiyatı gelirine göre değerlendirirsin, indirim dönemlerini ve kampanyaları beklersin, taksitle "
                 "alışveriş yaygındır ve yerli markalarla fiyat karşılaştırırsın."),
        assumptions=("Türkiye'de alım gücü diğer bölgelere göre düşük kabul edildi (fiyat merkezi aşağı çekildi).",
                     "Enflasyon ve kur belirsizliği nedeniyle fiyata duyarlılık +0.15 artırıldı (fiyat bandı daralır).",
                     "Taksit ve kampanya alışkanlıkları ajan davranışına yansıtıldı ama ayrı bir indirim modeli yok."),
    ),
}


def sensitivity_adj(region: str) -> float:
    eco = REGION_ECONOMY.get(region)
    return eco.sensitivity_adj if eco else 0.0


def currency_of(region: str) -> Optional[str]:
    eco = REGION_ECONOMY.get(region)
    return eco.currency if eco else None


def local_price(usd_price: Decimal, rate: float) -> Decimal:
    return (usd_price * Decimal(str(rate))).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def margin_after_fx_shock(usd_price: float, unit_cost: float, shock_pct: float = FX_SHOCK_PCT) -> float:
    """Yerel para shock_pct kadar değer kaybederse (fiyat TL'de sabit kalırsa) USD marjı, % olarak."""
    shocked = usd_price / (1 + shock_pct / 100)
    return (shocked - unit_cost) / shocked * 100
