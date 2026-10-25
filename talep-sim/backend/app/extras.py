"""Güvenilirlik, duyarlılık analizi, başa baş noktası, beden dağılımı ve mevsim uyumu.

Hepsi ya ajan eğrisinden (fiyat etkisi) ya da açıkça etiketlenmiş kural varsayımlarından hesaplanır.
"""
import re
from decimal import Decimal
from typing import List, Optional, Sequence

from .forecast import HORIZON, DemandModel
from .models import (Assumptions, BreakEven, Confidence, Seasonality, SensitivityRow, SalesForecast, SizeShare)
from .pricing import AgentPriceAnswer, purchase_probability
from .returns import net_profit_per_sale

MONTHS = ["", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
WINTER = {10: 1.15, 11: 1.15, 12: 1.15, 1: 1.15, 2: 1.15, 3: 0.9, 9: 0.9, 4: 0.7, 8: 0.7, 5: 0.5, 6: 0.5, 7: 0.5}
SUMMER = {5: 1.15, 6: 1.15, 7: 1.15, 4: 1.0, 8: 1.0, 3: 0.85, 9: 0.85, 10: 0.6, 2: 0.6, 11: 0.5, 12: 0.5, 1: 0.5}


def _d(x: float) -> Decimal:
    return Decimal(str(round(x, 2)))


def season_kind(card: dict) -> str:
    feats = card.get("features", {}) or {}
    fit = str(card.get("climate_fit", "")).lower()
    if fit == "soğuk" or feats.get("warmth") or feats.get("heavy"):
        return "winter"
    if fit == "sıcak":
        return "summer"
    return "neutral"


def seasonal_factor(card: dict, region: str, a: Assumptions) -> Optional[Seasonality]:
    """Lansman ayından başlayan 4 aylık satış penceresinin ortalama mevsim uyumu (kural varsayımı)."""
    if not a.launch_month:
        return None
    kind = season_kind(card)
    if kind == "neutral":
        return Seasonality(launch_month=a.launch_month, factor=1.0, note="Ürün mevsimsel görünmüyor; mevsim etkisi uygulanmadı.")
    table = WINTER if kind == "winter" else SUMMER
    months = [((a.launch_month - 1 + i) % 12) + 1 for i in range(4)]
    f = sum(table[m] for m in months) / 4
    if region == "MENA" and kind == "winter":
        f *= 0.8  # Körfez'de kış ürününe talep daha sınırlı
    f = round(max(0.3, min(1.3, f)), 2)
    label = "kışlık" if kind == "winter" else "yazlık"
    span = f"{MONTHS[months[0]]}-{MONTHS[months[-1]]}"
    verdict = "uyumlu" if f >= 1.0 else "kısmen uyumsuz" if f >= 0.8 else "uyumsuz"
    return Seasonality(launch_month=a.launch_month, factor=f,
                       note=f"Ürün {label}; {span} satış penceresi bu ürün için {verdict}. Talep x{f} ile çarpıldı.")


SIZE_BASE = {"EU": {"XS": 6, "S": 20, "M": 32, "L": 25, "XL": 13, "XXL": 4},
             "US": {"XS": 5, "S": 17, "M": 28, "L": 27, "XL": 16, "XXL": 7},
             "MENA": {"XS": 3, "S": 14, "M": 30, "L": 29, "XL": 17, "XXL": 7},
             "CIS": {"XS": 7, "S": 24, "M": 33, "L": 22, "XL": 11, "XXL": 3},
             "TR": {"XS": 5, "S": 19, "M": 31, "L": 26, "XL": 14, "XXL": 5}}


def size_curve(region: str, card: dict) -> List[SizeShare]:
    """Bölgeye göre beden dağılımı önerisi (kural varsayımı); bol kalıpta uçlar kısılır."""
    base = dict(SIZE_BASE.get(region, SIZE_BASE["EU"]))
    feats = card.get("features", {}) or {}
    if feats.get("oversize"):
        for k, w in {"XS": 0.5, "S": 0.9, "M": 1.15, "L": 1.1, "XL": 0.8, "XXL": 0.5}.items():
            base[k] *= w
    total = sum(base.values())
    return [SizeShare(size=k, share_pct=round(v / total * 100, 1)) for k, v in base.items()]


def sensitivity(model: DemandModel, answers: Sequence[AgentPriceAnswer], price: float, unit_cost: float, qty: int,
                rate_pct: float, a: Assumptions, season: float = 1.0) -> List[SensitivityRow]:
    def profit(p: float, c: float):
        prob = purchase_probability(answers, p)
        units = int(min(qty, model.demand(0, HORIZON, prob) * season))
        return units, net_profit_per_sale(p, c, rate_pct, a) * units

    _, base = profit(price, unit_cost)
    rows: List[SensitivityRow] = []
    for pct in (-20, -10, 0, 10, 20):
        p = price * (1 + pct / 100)
        u, pr = profit(p, unit_cost)
        rows.append(SensitivityRow(kind="price", label=f"Fiyat {pct:+d}%" if pct else "Önerilen fiyat", price=_d(p),
                                   unit_cost=_d(unit_cost), units=u, net_profit=_d(pr),
                                   vs_base_pct=round((pr / base - 1) * 100, 1) if base else 0.0))
    for pct in (-10, 10, 20):
        c = unit_cost * (1 + pct / 100)
        u, pr = profit(price, c)
        rows.append(SensitivityRow(kind="cost", label=f"Maliyet {pct:+d}%", price=_d(price), unit_cost=_d(c), units=u,
                                   net_profit=_d(pr), vs_base_pct=round((pr / base - 1) * 100, 1) if base else 0.0))
    return rows


def break_even(price: float, unit_cost: float, qty: int, rate_pct: float, a: Assumptions, forecast: SalesForecast) -> BreakEven:
    """Üretim maliyetini (adet x birim maliyet) karşılayan satış adedi; iade sonrası net gelirle."""
    r = rate_pct / 100
    net_rev = price * (1 - r) - r * price * a.reverse_logistics_pct / 100
    cost_total = qty * unit_cost
    units = int(cost_total / net_rev) + 1 if net_rev > 0 else 0
    day = next((p.day for p in forecast.curve if p.sold >= units), None) if units <= qty else None
    if units > qty:
        note = "Üretimin tamamı satılsa bile maliyet çıkmıyor (iade ve lojistik sonrası)."
    elif day is None:
        note = f"120 günde bu adede ulaşılmıyor (orta senaryo); {HORIZON}. günde {forecast.milestones[-1].units:,} satış."
    else:
        note = f"Orta senaryoda yaklaşık {day}. günde ulaşılır."
    return BreakEven(units=units, pct_of_production=round(units / qty * 100, 1) if qty else 0.0, day=day, note=note)


def confidence(meta: dict, brand_known: Optional[bool], a: Assumptions, region: str) -> Confidence:
    reasons: List[str] = []
    score = 2  # 0 düşük, 1 orta, 2 yüksek; düşüşler aşağıda
    engine = meta.get("engine", "mock")
    if engine != "mirofish":
        return Confidence(level="düşük", reasons=[
            "Mock motor: ürün anahtar kelimelerinden üretilen deterministik örnek; gerçek ajan görüşü değil.",
            "Gerçek ajan simülasyonu için SIM_ENGINE=mirofish kullan."])
    n = meta.get("n_valid", 0)
    if n < 8:
        score -= 1
        reasons.append(f"Bölge başına {n} ajan cevap verdi; küçük örneklem (öneri: 8-10+).")
    if meta.get("price_source") == "brand_fallback":
        score -= 2
        reasons.append("Fiyat eğrisi ajanlardan değil marka/maliyet varsayımından kuruldu.")
    elif meta.get("n_estimated"):
        score -= 1
        reasons.append(f"{meta['n_estimated']} ajanın bazı fiyat eşikleri tahmin edildi.")
    if meta.get("n_valid", 0) < meta.get("n_agents", 0):
        reasons.append("Bazı ajanlar zaman aşımı/bozuk cevap yüzünden hesaba katılmadı.")
    if brand_known is False:
        score -= 1
        reasons.append("Marka modelce tanınmıyor; marka profili genel varsayım.")
    if region not in a.audience:
        reasons.append("Hedef kitle büyüklüğü varsayım (satış tahmini buna bağlı).")
    level = "düşük" if score <= 0 else "orta" if score == 1 else "yüksek"
    return Confidence(level=level, reasons=reasons)
