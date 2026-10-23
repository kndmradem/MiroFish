"""Somut öneriler: önce LLM'den (simülasyon özetine bakarak), olmazsa veriden türeyen kurallarla."""
import json
from decimal import Decimal
from typing import Dict, List, Optional

from . import brand as brandlib
from . import economy
from .models import BrandProfile, Recommendation, RegionPredictionResult
from .services.llm import LLMClient, LLMError

_CATEGORIES = ("fiyat", "bölge", "tasarım", "üretim", "marka")

_DESIGN_HINTS = [
    (("kalın", "ağır", "hantal", "sıcak"), "Daha hafif gramajlı ya da yazlık/ara sezon bir varyant üret."),
    (("dar", "kalıp", "beden"), "Kalıbı gevşet ve beden tablosunu netleştir; iade riskini azaltır."),
    (("sentetik", "sürdürülebilir", "geri dönüş", "sertifika"), "Organik/geri dönüştürülmüş içerik ve sertifika bilgisi ekle."),
    (("parlak", "mat", "lüks", "premium", "gösteriş"), "Yüzey/aksesuar detayıyla premium algıyı güçlendir."),
    (("su", "rüzgar", "yalıtım", "ısı"), "Su itici/rüzgar kesici astar ve ısı yalıtımını ürün açıklamasında öne çıkar."),
    (("marka", "hikâye", "farklı"), "Markalaşma detayı (etiket, hikâye, imza detay) ekle."),
]


def _summary(regions: List[RegionPredictionResult], brand: Optional[BrandProfile], unit_cost: float,
             budget: int, unallocated: Decimal, product_card: dict) -> dict:
    return {
        "marka": brand.model_dump(exclude={"warning"}) if brand else None,
        "birim_maliyet_usd": unit_cost, "toplam_butce_usd": budget, "artan_butce_usd": float(unallocated),
        "urun": {k: product_card.get(k) for k in ("product_name", "fabric_texture", "composition", "gsm",
                                                  "climate_fit", "style_category", "features")},
        "bolgeler": [{"bolge": r.region, "talep": r.demand_score_100, "fiyat_usd": float(r.optimal_sale_price),
                      "marj_pct": r.estimated_margin_percentage, "adet": r.recommended_production_qty,
                      "itirazlar": r.key_objections} for r in regions],
    }


def rule_recommendations(regions: List[RegionPredictionResult], brand: Optional[BrandProfile], unit_cost: float,
                         budget: int, unallocated: Decimal) -> List[Recommendation]:
    recs: List[Recommendation] = []
    live = [r for r in regions if r.recommended_production_qty > 0] or regions
    prices = {r.region: float(r.optimal_sale_price) for r in regions}
    hi, lo = max(prices, key=prices.get), min(prices, key=prices.get)

    # Fiyat
    if prices[hi] / prices[lo] > 1.15:
        recs.append(Recommendation(category="fiyat", title=f"Bölgeye göre farklı fiyat: {lo} ${prices[lo]:.0f}, {hi} ${prices[hi]:.0f}",
                                   detail=f"{hi} bölgesi {lo} bölgesinden %{(prices[hi] / prices[lo] - 1) * 100:.0f} daha yüksek fiyat kaldırıyor. "
                                          "Tek fiyat yerine bölgesel fiyat listesi marjı artırır.",
                                   based_on="Bölgelere göre Van Westendorp sonuçları"))
    else:
        avg = sum(prices.values()) / len(prices)
        recs.append(Recommendation(category="fiyat", title=f"Tek küresel fiyat uygun: yaklaşık ${avg:.0f}",
                                   detail="Bölgeler arası optimal fiyat farkı %15'in altında; tek fiyat operasyonu sadeleştirir.",
                                   based_on="Bölgelerin optimal fiyatları"))
    if brand is not None:
        lo_m, hi_m = brandlib.TIER_MULTIPLE_RANGE[brand.price_tier]
        mult = sum(prices.values()) / len(prices) / unit_cost
        if mult < lo_m:
            recs.append(Recommendation(category="marka", title=f"Fiyat {brand.name} segmentinin altında kalıyor",
                                       detail=f"Önerilen fiyat maliyetin {mult:.1f} katı; {brandlib.TIER_LABEL[brand.price_tier]} segment için "
                                              f"tipik aralık {lo_m:.1f}–{hi_m:.1f}. Maliyet yapısı bu markanın fiyat politikasını desteklemiyor olabilir: "
                                              "kumaş/işçilik kalitesini yükseltmek ya da daha ekonomik bir alt hat düşünülebilir.",
                                       based_on=f"{brand.name} profili ve simülasyon fiyatı"))
        elif mult > hi_m:
            recs.append(Recommendation(category="marka", title=f"Fiyat {brand.name} segmentinin üstüne çıkıyor",
                                       detail=f"Önerilen fiyat maliyetin {mult:.1f} katı; segment için tipik üst sınır {hi_m:.1f}. "
                                              "Marka bu fiyatı taşıyamayabilir; fiyatı düşürmek hacmi artırabilir.",
                                       based_on=f"{brand.name} profili ve simülasyon fiyatı"))
        if brand.confidence == "low" or brand.source == "generic_default":
            recs.append(Recommendation(category="marka", title="Marka profilini doğrula",
                                       detail="Marka bilgisi düşük güvenle üretildi. Fiyat ve talep sonuçları bu profile bağlı; "
                                              "profil alanlarını gerçek bilginle düzeltip yeniden çalıştır.",
                                       based_on="Marka profili güven düzeyi"))

    # Kur riski olan bölgeler (ör. Türkiye)
    for r in regions:
        if r.local_price is not None and r.fx_rate:
            price = float(r.optimal_sale_price)
            before = (price - unit_cost) / price * 100
            after = economy.margin_after_fx_shock(price, unit_cost)
            recs.append(Recommendation(
                category="fiyat", title=f"{r.region}: TL fiyatı ₺{int(r.local_price):,}, kur riskini planla",
                detail=(f"Kur %{economy.FX_SHOCK_PCT:.0f} kayarsa ve TL fiyatı sabit kalırsa marj %{before:.0f}'den %{after:.0f}'e düşer. "
                        "TL fiyat listesini kur ve enflasyona göre düzenli güncelle; taksit seçeneği ve sezon kampanyalarıyla "
                        "fiyat algısını yönet, liste fiyatını gereksiz yükseltmek yerine indirim dönemlerinde marjı koru."),
                based_on=f"1 USD = {r.fx_rate:g} TL varsayımı ve {r.region} fiyatı"))

    # Bölge
    total = sum(r.recommended_production_qty for r in regions) or 1
    top = max(regions, key=lambda r: r.recommended_production_qty)
    recs.append(Recommendation(category="bölge", title=f"Önce {top.region}: üretimin %{top.recommended_production_qty / total * 100:.0f}'i",
                               detail=f"{top.region} talep {top.demand_score_100}/100 ve %{top.estimated_margin_percentage:.0f} marjla en yüksek bütçe payını aldı.",
                               based_on="Talep × birim kâr ağırlıkları"))
    weak = [r for r in regions if r.demand_score_100 < 40]
    for r in weak:
        recs.append(Recommendation(category="bölge", title=f"{r.region} için küçük pilot ya da hiç",
                                   detail=f"Talep endeksi {r.demand_score_100}/100. Ana itiraz: {r.key_objections[0] if r.key_objections else 'belirsiz'}. "
                                          "Bu bölgede tam üretim yerine küçük bir deneme partisi ya da ürün uyarlaması düşün.",
                                   based_on=f"{r.region} talep endeksi"))

    # Tasarım: bölgeler arası en sık itirazlar
    counts: Dict[str, int] = {}
    for r in regions:
        for o in r.key_objections:
            counts[o] = counts.get(o, 0) + 1
    for objection, n in sorted(counts.items(), key=lambda kv: -kv[1])[:2]:
        low = objection.lower()
        action = next((a for keys, a in _DESIGN_HINTS if any(k in low for k in keys)), "İtirazı ürün açıklaması ya da tasarımla gider.")
        recs.append(Recommendation(category="tasarım", title=f"İtiraz: “{objection}”", detail=action,
                                   based_on=f"{n} bölgedeki ajanlardan"))

    # Üretim
    if unallocated > Decimal(budget) * Decimal("0.02"):
        recs.append(Recommendation(category="üretim", title=f"${float(unallocated):,.0f} bütçe kullanılmadı",
                                   detail="Aşağı yuvarlama ve kârsız bölgeler yüzünden bütçenin bir kısmı artıyor; ek renk/beden ya da yeni bölge testine ayrılabilir.",
                                   based_on="Bütçe dağıtımı sonucu"))
    return recs


class Advisor:
    def __init__(self, llm: Optional[LLMClient]):
        self.llm = llm

    async def recommend(self, regions: List[RegionPredictionResult], brand: Optional[BrandProfile], unit_cost: float,
                        budget: int, unallocated: Decimal, product_card: dict) -> List[Recommendation]:
        rules = rule_recommendations(regions, brand, unit_cost, budget, unallocated)
        if self.llm is None:
            return rules
        prompt = (
            "Aşağıdaki simülasyon özetine bakarak bir moda üreticisine 4-5 somut öneri yaz. Markanın fiyat politikasını "
            "(segment, müşteri, marj normu) mutlaka dikkate al. Sadece özette olan sayıları kullan, sayı uydurma. "
            'JSON: {"oneriler": [{"category": "fiyat|bölge|tasarım|üretim|marka", "title": "kısa başlık", '
            '"detail": "1-3 cümle, somut ve bu veriye özgü", "based_on": "hangi sayıya dayandığı"}]}\n\n'
            + json.dumps(_summary(regions, brand, unit_cost, budget, unallocated, product_card), ensure_ascii=False))
        try:
            raw = await self.llm.chat_json("Sen deneyimli bir moda perakende stratejistisin. Türkçe yaz. Sadece JSON dön.", prompt)
            items = raw.get("oneriler") if isinstance(raw, dict) else raw
            recs = [Recommendation(category=i["category"], title=str(i["title"])[:140], detail=str(i["detail"])[:600],
                                   based_on=str(i.get("based_on", ""))[:160], source="model")
                    for i in items if isinstance(i, dict) and i.get("category") in _CATEGORIES and i.get("title") and i.get("detail")]
        except (LLMError, KeyError, TypeError, AttributeError):
            return rules
        # Model önerileri öne; sayıya dayalı sabit uyarılar (marka doğrulama, kur riski) sona eklenir
        keep = [r for r in rules if r.title == "Marka profilini doğrula" or "kur riskini planla" in r.title]
        return recs[:5] + keep if recs else rules
