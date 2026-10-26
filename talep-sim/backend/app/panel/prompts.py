"""Panel üyesine sorulan prompt: persona (veriden) + tarihli bağlam paketi + ürün kartı + fiyat merdiveni.

Modelin kendi moda/trend bilgisi eğitim tarihinde kalmıştır; prompt bunu açıkça söyler ve modeli yalnızca
verilen güncel bağlama dayanmaya yönlendirir. Bağlamda olmayan bir trendi model uydurmamalı.
"""
from typing import Dict, List, Optional

from .. import brand as brandlib
from ..models import BrandProfile
from ..services.answer_extractor import LABELS, example_ladder, ladder_text
from .library import ContextPack, PanelMember

_INCOME = {"düşük": "düşük gelirli", "orta-alt": "orta-alt gelirli", "orta": "orta gelirli",
           "orta-üst": "orta-üst gelirli", "yüksek": "yüksek gelirli"}


def _level(x: float, low: str, mid: str, high: str) -> str:
    return low if x < 0.35 else high if x > 0.65 else mid


def persona_text(m: PanelMember) -> str:
    s = m.segment
    parts = [f"Sen {s.city} şehrinde yaşayan {m.age} yaşında {'bir kadın' if m.female else 'bir erkek'} tüketicisin "
             f"({s.label}, {_INCOME[s.income_band]})."]
    if s.style_affinity:
        parts.append(f"Tarzın: {', '.join(s.style_affinity)}.")
    parts.append(f"Fiyata duyarlılığın {_level(m.price_sensitivity, 'düşük', 'orta', 'yüksek')} "
                 f"({m.price_sensitivity:.2f}/1); yeni trendlere ilgin "
                 f"{_level(m.trend_affinity, 'düşük, kanıtlanmış parçaları seversin', 'orta', 'yüksek, yeniyi erken denersin')}.")
    if s.channel_habits:
        parts.append(f"Alışveriş alışkanlıkların: {', '.join(s.channel_habits)}.")
    if s.climate:
        parts.append(f"İklim: {s.climate}.")
    if s.dress_norms:
        parts.append(f"Giyim normların: {s.dress_norms}.")
    if s.notes:
        parts.append(s.notes)
    return " ".join(parts)


def context_text(ctx: Optional[ContextPack]) -> str:
    if ctx is None:
        return ("GÜNCEL BAĞLAM: verilmedi. Ekonomik durum ve güncel trendler hakkında varsayım yapma; "
                "ürünü yalnızca kendi ihtiyacına ve fiyata göre değerlendir.")
    lines = [f"GÜNCEL BAĞLAM ({ctx.as_of.isoformat()} itibarıyla, kaynak: {ctx.source or '-'}):"]
    m = ctx.macro
    if m.inflation_yoy_pct is not None:
        lines.append(f"- Yıllık enflasyon: %{m.inflation_yoy_pct:g}")
    for label, val in (("Alım gücü", m.purchasing_power), ("Tüketici güveni", m.consumer_confidence),
                       ("Kur", m.fx_note)):
        if val:
            lines.append(f"- {label}: {val}")
    if ctx.season_notes:
        lines.append(f"- Sezon/hava: {ctx.season_notes}")
    if ctx.shopping_notes:
        lines.append(f"- Alışveriş dönemi: {ctx.shopping_notes}")
    for t in ctx.trends[:6]:
        lines.append(f"- Trend: {t.note}" + (f" ({t.as_of.isoformat()})" if t.as_of else ""))
    for c in ctx.competitor_prices[:5]:
        lines.append(f"- Rakip fiyatı: {c.item} yaklaşık ${c.price_usd:g}")
    return "\n".join(lines)


SYSTEM_SUFFIX = (
    "Moda, trend ve ekonomi hakkındaki kendi bilgin eğitim verinden gelir ve eskidir. Güncel durum için yalnızca "
    "kullanıcı mesajındaki GÜNCEL BAĞLAM bölümüne güven; orada olmayan bir trendi ya da fiyatı varsayma. "
    "Kendi persona özelliklerine sadık kal; herkes her ürünü beğenmez. Sadece istenen JSON'u yaz."
)


def system_prompt(m: PanelMember) -> str:
    return f"{persona_text(m)}\n\n{SYSTEM_SUFFIX}"


def user_prompt(card: dict, ctx: Optional[ContextPack], ladder: List[float], brand: Optional[BrandProfile],
                region: str, unit_cost: Optional[float], try_rate: Optional[float] = None,
                peer_summary: Optional[str] = None) -> str:
    features = ", ".join(k for k, v in card.get("features", {}).items() if v) or "belirtilmemiş"
    brand_block = ""
    if brand is not None:
        ref = (f" Bu marka bu tür ürünleri genelde yaklaşık ${brandlib.reference_price(brand, unit_cost):.0f} civarında satar."
               if unit_cost else "")
        brand_block = (f"Marka: {brand.name} ({brandlib.TIER_LABEL[brand.price_tier]} segment). {brand.positioning} "
                       f"Bu bölgedeki bilinirliği: {brandlib.region_strength(brand, region)}/100.{ref}\n")
    peer = (f"\nDiğer tüketicilerin bu ürün hakkındaki yorumlarının özeti (katılmak zorunda değilsin):\n{peer_summary}\n"
            if peer_summary else "")
    return (
        f"{context_text(ctx)}\n\n"
        "Aşağıdaki yeni ürünü kendi gözünle değerlendir. Fiyatlar ABD doları.\n"
        f"{brand_block}"
        f"Ürün: {card.get('product_name')}\n"
        f"Kumaş: {card.get('fabric_texture', '-')}; bileşim: {card.get('composition', '-')}; gramaj: {card.get('gsm') or '-'}\n"
        f"İklim uyumu: {card.get('climate_fit', '-')}; stil: {card.get('style_category', '-')}\n"
        f"Görünüm: {card.get('visual_description', '-')}\n"
        f"Öne çıkan özellikler: {features}\n"
        f"{peer}\n"
        "Ürün şu fiyatlardan biriyle satılsa ne düşünürsün? Her fiyat için TEK etiket seç:\n"
        f"{ladder_text(ladder, try_rate)}\n"
        'Etiketler: "supheli" (bu kadar ucuzsa kaliteden şüphelenirim), "uygun" (makul, alırım), '
        '"pahali" (pahalı ama düşünürüm), "cok_pahali" (asla almam).\n'
        "interest: bu ürünü satın alma isteğin, 0-100 arası TEK SAYI (isteksiz 10-30, kararsız 40-60, hevesli 70-95).\n"
        "Sadece şu biçimde JSON yaz:\n"
        f'{{"interest": 55, "ladder": {example_ladder(len(ladder))}, "objection": "en büyük itirazın, tek kısa cümle", '
        '"reason": "kararının kısa nedeni"}'
    )


def answer_schema(n_steps: int) -> Dict:
    """Kılavuzlu çözümleme (vLLM guided decoding / Ollama format / OpenAI json_schema) için şema."""
    steps = {str(i + 1): {"type": "string", "enum": list(LABELS)} for i in range(n_steps)}
    return {
        "type": "object",
        "properties": {
            "interest": {"type": "integer", "minimum": 0, "maximum": 100},
            "ladder": {"type": "object", "properties": steps, "required": list(steps), "additionalProperties": False},
            "objection": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": ["interest", "ladder", "objection", "reason"],
        "additionalProperties": False,
    }


def repair_prompt(problem: str, n_steps: int) -> str:
    return (f"Önceki cevabın istenen biçime uymadı: {problem}. Aynı görüşünü koruyarak yalnızca düzeltilmiş JSON'u yaz. "
            f'"interest" 0-100 arası tek sayı, "ladder" 1..{n_steps} numaralı her fiyat için '
            f"{', '.join(LABELS)} etiketlerinden biri olmalı.")


def peer_summary(objections: List[str], mean_interest: float, n: int) -> str:
    top = "; ".join(objections[:4]) or "belirgin itiraz yok"
    return f"{n} kişinin ortalama satın alma isteği {mean_interest:.0f}/100. Sık dile getirilen itirazlar: {top}."
