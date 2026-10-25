"""Ajan cevaplarını yapılandırılmış veriye çevirir.

Küçük yerel modeller (Qwen 7B) sayı yerine cümle yazar, dili karıştırır, JSON'u bozar. Bu yüzden:
1. Ajana serbest fiyat yerine sabit bir fiyat merdiveni (9 fiyat) sorulur ve her basamak için tek
   kelimelik karar istenir (supheli / uygun / pahali / cok_pahali). Küçük modeller bunu çok daha iyi yapar.
2. Cevap hoşgörülü okunur (kod bloğu, metin içi JSON, sayı yerine yazı, etiket eş anlamlıları).
3. Olmazsa cevap ayrı bir LLM çağrısıyla (örnekli, katı prompt) aynı şemaya çevrilir.
4. Fiyat bilgisi hiç çıkmasa bile ilgi puanı varsa cevap kısmi olarak geçerlidir (talep skoru için).
"""
import json
import math
import re
from typing import Dict, List, Optional

from .llm import LLMClient, LLMError

LADDER_MULTIPLIERS = (0.5, 0.65, 0.8, 0.95, 1.1, 1.3, 1.5, 1.8, 2.2)
LABELS = ("supheli", "uygun", "pahali", "cok_pahali")

SYSTEM = (
    "Bir tüketici röportajı cevabından yapılandırılmış veri çıkaran bir asistansın. "
    "Sadece JSON dön, başka metin yazma. Sayı istenen yere asla cümle yazma."
)

PROMPT = """Bir tüketiciye yeni bir ürün için şu fiyatlar soruldu:
{ladder}

Tüketicinin cevabı:
\"\"\"
{text}
\"\"\"

Cevaba göre doldur:
- "interest": satın alma ilgisi, 0 ile 100 arası TEK BİR SAYI (isteksiz 10-30, kararsız 40-60, hevesli 70-95)
- "ladder": her fiyat numarası için TAM OLARAK şu dört etiketten biri: "supheli" (bu kadar ucuzsa kaliteden şüphelenir),
  "uygun" (makul, alır), "pahali" (pahalı ama düşünür), "cok_pahali" (asla almaz). Fiyat arttıkça etiket genelde
  supheli -> uygun -> pahali -> cok_pahali yönünde ilerler. Cevap bir fiyattan açıkça söz etmiyorsa tonundan çıkar.
- "objection": en büyük itiraz, tek kısa cümle (yoksa "")
{currency}
Örnek çıktı:
{{"interest": 65, "ladder": {example}, "objection": "Kumaş biraz kalın"}}"""


def make_ladder(reference: float) -> List[float]:
    """Referans fiyatın etrafında 9 basamaklı, yuvarlanmış artan fiyat merdiveni (USD)."""
    out: List[float] = []
    for m in LADDER_MULTIPLIERS:
        v = reference * m
        step = 1 if v < 50 else 5 if v < 200 else 10
        v = max(1.0, round(v / step) * step)
        out.append(v if not out or v > out[-1] else out[-1] + step)
    return out


def ladder_text(ladder: List[float], try_rate: Optional[float] = None) -> str:
    lines = []
    for i, p in enumerate(ladder, 1):
        tl = f" (≈ ₺{p * try_rate:,.0f})".replace(",", ".") if try_rate else ""
        lines.append(f"{i}) ${p:,.0f}{tl}")
    return "\n".join(lines)


def example_ladder(n: int) -> str:
    cycle = ["supheli", "uygun", "uygun", "uygun", "pahali", "pahali", "pahali", "cok_pahali", "cok_pahali"]
    return json.dumps({str(i + 1): cycle[min(i, len(cycle) - 1)] for i in range(n)})


def label_rank(value) -> Optional[int]:
    """Etiket (eş anlamlılar ve Türkçe/İngilizce yazımlar dahil) -> 0..3."""
    if isinstance(value, bool) or value is None:
        return None
    s = str(value).lower().strip()
    s = s.translate(str.maketrans("şğıöüçâî", "sgioucai"))
    if not s:
        return None
    if re.search(r"cok.?pahal|asla|never|way too|too.?exp|overpriced|very.?exp|reddet|almam", s):
        return 3
    if re.search(r"supheli|suspic|too.?cheap|cok.?ucuz|kalitesiz|dusuk kalite", s):
        return 0
    if re.search(r"pahal|expens|belki|maybe|dusunur|consider", s):
        return 2
    if re.search(r"uygun|makul|kelepir|bargain|good|fair|ok\b|alir|buy|evet|yes|cheap|ucuz", s):
        return 1
    return None


def to_number(value) -> Optional[float]:
    """Sayı ya da içinde sayı geçen kısa metin ("$55", "65/100", "%70") -> float. Sayısız metin None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    m = re.search(r"-?\d+(?:[.,]\d+)?", str(value))
    return float(m.group(0).replace(",", ".")) if m else None


def _mid(a: float, b: float) -> float:
    return math.sqrt(a * b)


def thresholds_from_ladder(prices: List[float], ranks: List[Optional[int]]):
    """Merdiven kararlarından Van Westendorp eşikleri: (4 eşik, tahmin_edildi, kullanılan_basamak)."""
    pts = [(p, r) for p, r in zip(prices, ranks) if r is not None]
    if len(pts) < 3:
        return None
    ps = [p for p, _ in pts]
    rs = [r for _, r in pts]
    estimated = len(pts) < len(prices)

    def first_at_least(k):
        return next((i for i, r in enumerate(rs) if r >= k), None)

    zero = [i for i, r in enumerate(rs) if r == 0]
    if zero:
        j = zero[-1]
        too_cheap = _mid(ps[j], ps[j + 1]) if j + 1 < len(ps) else ps[j] * 1.15
    else:
        too_cheap, estimated = ps[0] * 0.8, True
    i2 = first_at_least(2)
    if i2 is None:
        expensive, estimated = ps[-1] * 1.25, True
    else:
        expensive = _mid(ps[i2 - 1], ps[i2]) if i2 > 0 else ps[0] * 0.9
    i3 = first_at_least(3)
    if i3 is None:
        too_expensive, estimated = max(expensive * 1.3, ps[-1] * 1.4), True
    else:
        too_expensive = _mid(ps[i3 - 1], ps[i3]) if i3 > 0 else ps[0] * 0.95
    too_expensive = max(too_expensive, expensive * 1.05)
    too_cheap = min(too_cheap, expensive * 0.9)
    cheap = _mid(too_cheap, expensive)
    return [too_cheap, cheap, expensive, too_expensive], estimated


def _objects(text: str):
    dec = json.JSONDecoder()
    pos = 0
    while (i := text.find("{", pos)) != -1:
        try:
            obj, end = dec.raw_decode(text, i)
        except ValueError:
            pos = i + 1
            continue
        if isinstance(obj, dict):
            yield obj
        pos = end


def _ladder_ranks(raw, n: int) -> Optional[List[Optional[int]]]:
    if isinstance(raw, dict):
        items = [raw.get(str(i + 1), raw.get(i + 1)) for i in range(n)]
    elif isinstance(raw, list):
        items = list(raw[:n]) + [None] * (n - len(raw))
    else:
        return None
    return [label_rank(x) for x in items]


def answer_from_obj(raw: dict, ladder: Optional[List[float]] = None) -> Optional[dict]:
    """Ham sözlük -> cevap. Fiyat yoksa ama ilgi varsa kısmi cevap (prices=None)."""
    interest = None
    for key in ("interest", "ilgi", "intent", "purchase_intent"):
        interest = to_number(raw.get(key))
        if interest is not None:
            break
    if interest is None:
        return None
    interest = max(0.0, min(100.0, interest))
    out = {"interest": interest, "prices": None, "estimated": False, "price_source": None,
           "objection": str(raw.get("objection") or raw.get("itiraz") or "").strip()}
    if ladder:
        for key in ("ladder", "fiyatlar", "prices", "merdiven"):
            ranks = _ladder_ranks(raw.get(key), len(ladder))
            if ranks and (res := thresholds_from_ladder(ladder, ranks)):
                out.update(prices=res[0], estimated=res[1], price_source="ladder", ranks=ranks)
                return out
    vals = [to_number(raw.get(k)) for k in ("too_cheap", "cheap", "expensive", "too_expensive")]
    if all(v is not None and v > 0 for v in vals):
        vals = sorted(vals)
        if len(set(vals)) == 4:
            out.update(prices=vals, price_source="numeric")
    return out


def parse_agent_answer(text: str, ladder: Optional[List[float]] = None) -> Optional[dict]:
    """Cevapta (kod bloğu içinde de olsa) cevap nesnesi arar; fiyatlı olanı kısmi olana tercih eder."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    partial = None
    for obj in _objects(text):
        ans = answer_from_obj(obj, ladder)
        if ans is None:
            continue
        if ans["prices"] is not None:
            return ans
        partial = partial or ans
    return partial


class AnswerExtractor:
    def __init__(self, llm: LLMClient, max_chars: int = 2000):
        self.llm = llm
        self.max_chars = max_chars
        self.last_error: Optional[str] = None

    async def extract(self, text: str, ladder: List[float], currency_note: str = "",
                      try_rate: Optional[float] = None) -> Optional[dict]:
        """Serbest/bozuk cevabı LLM ile merdiven şemasına çevirir; başarısızsa None."""
        prompt = PROMPT.format(
            ladder=ladder_text(ladder, try_rate), text=(text or "")[: self.max_chars],
            currency=f"{currency_note}\n" if currency_note else "", example=example_ladder(len(ladder)))
        self.last_error = None
        try:
            raw = await self.llm.chat_json(SYSTEM, prompt, retries=1)
        except LLMError as e:
            self.last_error = str(e)
            return None
        return answer_from_obj(raw, ladder) if isinstance(raw, dict) else None
