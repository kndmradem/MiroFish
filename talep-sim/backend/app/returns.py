"""İade oranı tahmini: ürün özellikleri ve bölgeye göre kural tabanlı, açıklanabilir model.

Bu modelin tüm katsayıları ajan cevabı değil, moda e-ticaretinden bilinen genel eğilimlere dayanan
VARSAYIMLARDIR; gerçek iade verin varsa `assumptions.return_base_pct` ile taban oranı değiştir.
Her faktör, iade oranına kaç yüzde puanı eklediği/çıkardığı ve nedeniyle birlikte döner.
"""
import re
from decimal import Decimal
from typing import Dict, List, Optional

from .models import Assumptions, BrandProfile, ReturnDriver, ReturnEstimate

# Online moda için taban iade oranı (%): bölge iade kültürü + kapıda ödeme/ret alışkanlığı dahil.
BASE_RETURN_PCT = {"EU": 24.0, "US": 20.0, "MENA": 15.0, "CIS": 14.0, "TR": 17.0}
BASE_NOTE = {
    "EU": "Ücretsiz iade ve çoklu beden sipariş kültürü yaygın.",
    "US": "İade kolay ama AB kadar yaygın değil.",
    "MENA": "Kapıda ödemede kapıda ret ve değişim payı var; iade süreçleri daha zahmetli.",
    "CIS": "İade süreçleri daha zahmetli, iade alışkanlığı daha düşük.",
    "TR": "Kolay iade ve değişim beklentisi yüksek; kapıda ödeme payı var.",
}
STORE_FACTOR = 0.45  # mağazada deneme imkânı iadeyi belirgin azaltır

REVEALING = r"dekolte|décolleté|decollete|derin v|v yaka|açık sırt|sırt dekolte|kolsuz|sleeveless|mini|crop|transparan|şeffaf|sheer|yırtmaç|strapless|straplez|halter|backless"
FITTED = r"slim|dar kesim|fitted|bodycon|vücuda oturan|korse|body"
STRETCH = r"elastan|elastane|spandex|lycra|streç|stretch|örme|knit|jersey|viskon|interlok"
DELICATE = r"ipek|silk|saten|satin|şifon|chiffon|dantel|lace|organze|tül|kadife|velvet|keten|linen"
ITCHY = r"yün|wool|akrilik|acrylic|angora"
SYNTH_SHEEN = r"polyester|polyamid|naylon|nylon"

# Muhafazakâr/örtünmeye duyarlı pazarlarda açık kesim iadeyi (ve talebi) artırır.
REVEAL_POINTS = {"MENA": 6.0, "TR": 3.0, "CIS": 1.5, "EU": 0.0, "US": 0.0}
SIZE_MISMATCH = {"MENA": 1.5, "TR": 1.0, "CIS": 0.0, "EU": 0.0, "US": 1.0}
SIZE_NOTE = {"MENA": "Yerel beden kalıbı ve vücut ölçüleri standart tablodan sapabilir.",
             "TR": "Bölgesel kalıp beklentisi farkı küçük bir ek beden riski yaratır.",
             "US": "ABD beden sistemi farklı; yanlış beden seçimi artar."}
CLIMATE = {"EU": "ılıman", "US": "ılıman", "MENA": "sıcak", "CIS": "soğuk", "TR": "ılıman"}


def _text(card: dict, extra: str) -> str:
    parts = [str(v) for k, v in card.items() if isinstance(v, (str, int, float))]
    return (" ".join(parts) + " " + (extra or "")).lower()


def estimate_returns(card: dict, region: str, price: float, unit_cost: float, qty: int,
                     brand: Optional[BrandProfile], assumptions: Assumptions, specs_text: str = "") -> ReturnEstimate:
    text = _text(card, specs_text)
    feats = card.get("features", {}) or {}
    user_base = assumptions.return_base_pct.get(region)
    base = user_base if user_base is not None else BASE_RETURN_PCT.get(region, 18.0)
    base_basis = "kullanıcı verisi" if user_base is not None else "kural varsayımı"
    drivers: List[ReturnDriver] = [ReturnDriver(
        label=f"Bölge taban oranı ({region})", points=0.0, basis=base_basis,
        detail=f"Taban %{base:g}. " + (BASE_NOTE.get(region, "") if user_base is None else "Senin girdiğin gerçek veriden alındı."))]

    def add(label: str, pts: float, detail: str) -> None:
        if pts:
            drivers.append(ReturnDriver(label=label, points=round(pts, 1), detail=detail))

    # Kalıp / beden uyumu
    if feats.get("oversize") or re.search(r"oversize|bol kesim|relaxed|loose", text):
        add("Bol kalıp", -2.0, "Bol kesimde beden hatası toleransı yüksek; beden kaynaklı iade azalır.")
    elif re.search(FITTED, text):
        add("Vücuda oturan kalıp", 3.5, "Dar/oturan kesimde beden ve kalıp uyumsuzluğu iade nedenlerinin başında gelir.")
    if (pts := SIZE_MISMATCH.get(region, 0.0)):
        add("Bölgesel beden uyumu", pts, SIZE_NOTE.get(region, ""))

    # Kumaş
    if re.search(STRETCH, text):
        add("Esnek kumaş", -1.5, "Esneyen kumaş küçük beden farklarını tolere eder.")
    if re.search(DELICATE, text):
        add("Hassas/kırışan kumaş", 2.0, "İpek, saten, keten gibi kumaşlarda doku ve kırışma beklentisi tutmayabilir.")
    if re.search(ITCHY, text) or feats.get("heavy"):
        add("Batma/ağırlık riski", 1.0, "Yün/akrilik veya ağır kumaşlarda konfor beklentisi sapabilir.")
    if feats.get("sheen") or (re.search(SYNTH_SHEEN, text) and feats.get("synthetic")):
        add("Görsel-gerçek renk/parlaklık farkı", 2.0, "Parlak/sentetik yüzeyler fotoğrafta ve gerçekte farklı görünür.")

    # Kesim / örtünme uyumu (bölgeye göre)
    if re.search(REVEALING, text):
        pts = REVEAL_POINTS.get(region, 0.0)
        add("Açık kesim (dekolte/kolsuz/transparan)", pts,
            f"Bu kesim {region} pazarında örtünme normlarıyla çelişebilir; iade ve vazgeçme artar." if pts
            else f"{region} pazarında açık kesim norm dışı değil; ek iade riski yok.")

    # İklim uyumsuzluğu
    fit = str(card.get("climate_fit", "")).lower()
    if fit and CLIMATE.get(region) and fit != CLIMATE[region] and {fit, CLIMATE[region]} == {"sıcak", "soğuk"}:
        add("İklim uyumsuzluğu", 2.5, f"Ürün {fit} iklime uygun, {region} ağırlıklı {CLIMATE[region]} iklim.")

    # Fiyat segmenti
    if brand is not None:
        pts = {"budget": 2.0, "mass": 1.0, "upper_mass": 0.0, "premium": -1.5, "luxury": -3.0}[brand.price_tier]
        add("Marka segmenti", pts, "Pahalı segment müşterisi daha bilinçli seçer; ucuz segmentte dürtüsel alım ve iade fazladır.")

    total = base + sum(d.points for d in drivers)
    # Kanal etkisi çarpan olarak uygulanır
    if assumptions.channel == "store":
        delta = total * (STORE_FACTOR - 1)
        drivers.append(ReturnDriver(label="Satış kanalı: mağaza", points=round(delta, 1),
                                    detail="Mağazada deneme imkânı iadeyi yaklaşık yarıya indirir (varsayım)."))
        total += delta
    rate = max(2.0, min(55.0, total))
    low, high = max(1.0, rate * 0.75), min(70.0, rate * 1.3)  # belirsizlik aralığı (varsayım)

    price_f, cost_f = float(price), float(unit_cost)
    r = rate / 100
    logistics = price_f * assumptions.reverse_logistics_pct / 100
    loss_per_return = logistics + (1 - assumptions.restock_share) * cost_f
    return_cost = r * loss_per_return
    kept_revenue = price_f * (1 - r)
    kept_profit = (price_f - cost_f) * (1 - r)
    net_profit = kept_profit - return_cost
    net_margin = net_profit / kept_revenue * 100 if kept_revenue > 0 else 0.0
    gross = (price_f - cost_f) / price_f * 100 if price_f > 0 else 0.0
    return ReturnEstimate(
        rate_pct=round(rate, 1), low_pct=round(low, 1), high_pct=round(high, 1), base_pct=round(base, 1),
        drivers=drivers, gross_margin_pct=round(gross, 1), net_margin_pct=round(net_margin, 1),
        return_cost_per_sale=Decimal(str(round(return_cost, 2))),
        net_qty_if_sold_out=int(qty * (1 - r)),
    )
