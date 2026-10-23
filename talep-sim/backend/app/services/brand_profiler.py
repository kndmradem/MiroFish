"""Marka profili çıkarımı: herhangi bir marka adı için LLM'den, sabit marka listesi olmadan.

Model markayı tanımıyorsa ya da LLM yoksa/başarısızsa nötr bir profil döner ve bu
açıkça `warning` ile işaretlenir; sessizce uydurma bilgi sunulmaz.
"""
from typing import Optional

from ..brand import TIER_MULTIPLE_RANGE, generic_profile
from ..models import ALL_REGIONS, BrandProfile
from .llm import LLMClient, LLMError

SYSTEM = (
    "Sen moda ve perakende sektöründe marka konumlandırma ve fiyatlama uzmanısın. "
    "Yalnızca gerçekten bildiğin bilgiyi kullan. Markayı tanımıyorsan known_brand=false ve "
    "confidence=low yaz, uydurma; yalnızca genel bir segment tahmini yap. Sadece JSON dön."
)

PROMPT = """Marka: {brand}
{notes}
Bu markanın giyim/tekstil ürünleri için fiyat profilini çıkar. Şu JSON şemasıyla cevap ver:
{{
 "known_brand": true|false,
 "confidence": "low"|"medium"|"high",
 "positioning": "markanın konumlandırması, 1-2 cümle",
 "price_tier": "budget"|"mass"|"upper_mass"|"premium"|"luxury",
 "price_multiple": markanın tipik perakende satış fiyatının birim üretim maliyetine oranı (sayı, ör. 2.5-12),
 "price_sensitivity": 0-1 arası (1 = müşteri fiyata çok duyarlı, 0 = fiyata duyarsız),
 "brand_pull": 0-100 (marka bilinirliği ve çekim gücü),
 "typical_customer": "tipik müşteri, 1 cümle",
 "margin_norm_pct": markanın tipik brüt kâr marjı yüzdesi (sayı),
 "regional_strength": {{"EU": 0-100, "MENA": 0-100, "CIS": 0-100, "US": 0-100}}
}}
regional_strength, markanın o bölgedeki bilinirliği ve satış gücüdür."""

_TIERS = tuple(TIER_MULTIPLE_RANGE)


def _num(raw: dict, key: str, default: float, lo: float, hi: float) -> float:
    try:
        return max(lo, min(hi, float(raw.get(key, default))))
    except (TypeError, ValueError):
        return default


def parse_brand_profile(raw: dict, name: str, has_notes: bool) -> BrandProfile:
    """LLM cevabını doğrular ve sınırlar. Zorunlu alan eksikse LLMError yükseltir."""
    if not isinstance(raw, dict) or raw.get("price_tier") not in _TIERS or "price_multiple" not in raw:
        raise LLMError(f"Profil şemaya uymuyor: {str(raw)[:160]}")
    tier = raw["price_tier"]
    lo, hi = TIER_MULTIPLE_RANGE[tier]
    known = bool(raw.get("known_brand", False))
    confidence = raw.get("confidence") if raw.get("confidence") in ("low", "medium", "high") else "low"
    if not known:
        confidence = "low"
    strengths_raw = raw.get("regional_strength") if isinstance(raw.get("regional_strength"), dict) else {}
    strengths = {r: int(_num(strengths_raw, r, 50, 0, 100)) for r in ALL_REGIONS}

    warning = "Bu profil modelin genel bilgisinden üretildi; doğrulanmış veri değildir."
    if not known or confidence == "low":
        warning += " Model bu markayı iyi tanımıyor olabilir; değerleri kontrol edip düzenle."
    return BrandProfile(
        name=name,
        positioning=str(raw.get("positioning", ""))[:400],
        price_tier=tier,
        price_multiple=round(_num(raw, "price_multiple", 2.7, lo, hi), 2),
        price_sensitivity=round(_num(raw, "price_sensitivity", 0.5, 0, 1), 2),
        brand_pull=int(_num(raw, "brand_pull", 50, 0, 100)),
        typical_customer=str(raw.get("typical_customer", ""))[:300],
        margin_norm_pct=round(_num(raw, "margin_norm_pct", 55, 10, 95), 1),
        regional_strength=strengths,
        known_brand=known,
        confidence=confidence,
        source="user_notes" if has_notes else "llm_knowledge",
        warning=warning,
    )


class BrandProfiler:
    def __init__(self, llm: Optional[LLMClient]):
        self.llm = llm

    async def profile(self, brand: str, notes: Optional[str] = None) -> BrandProfile:
        brand = brand.strip()
        if self.llm is None:
            return generic_profile(brand, "LLM ayarlı olmadığı için marka profili çıkarılamadı; nötr varsayılanlar "
                                           "kullanıldı. Değerleri elle girebilirsin.")
        notes_block = f"Kullanıcı notları (bunlara öncelik ver): {notes.strip()}" if notes and notes.strip() else ""
        try:
            raw = await self.llm.chat_json(SYSTEM, PROMPT.format(brand=brand, notes=notes_block))
            return parse_brand_profile(raw, brand, bool(notes_block))
        except LLMError as e:
            return generic_profile(brand, f"Marka profili model tarafından üretilemedi ({e}); nötr varsayılanlar "
                                          "kullanıldı. Değerleri elle girebilirsin.")
