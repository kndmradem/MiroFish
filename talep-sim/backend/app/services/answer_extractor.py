"""Ajanların serbest metin cevaplarından yapılandırılmış veri çıkarır.

MiroFish ajanları persona gibi konuşur ve çoğu zaman (özellikle küçük yerel modellerde) istenen
JSON'u vermez. Bu yüzden önce hoşgörülü bir ayrıştırıcı denenir (kod bloğu, metin içindeki ilk
JSON nesnesi); olmazsa cevap ayrı, küçük ve JSON modundaki bir LLM çağrısıyla alanlara çevrilir.
"""
import json
import re
from typing import Optional

from .llm import LLMClient, LLMError

KEYS = ("interest", "too_cheap", "cheap", "expensive", "too_expensive")

SYSTEM = (
    "Bir tüketici röportajı cevabından yapılandırılmış veri çıkaran bir asistansın. "
    "Sadece JSON dön, başka metin yazma."
)

PROMPT = """Aşağıda bir tüketicinin yeni bir ürün hakkındaki cevabı var (Türkçe, İngilizce ya da başka dilde olabilir).
Cevaptan şu alanları çıkar. Tüm fiyatlar ABD doları olmalı.{currency}

Cevap:
\"\"\"
{text}
\"\"\"

JSON şeması:
{{
 "interest": 0-100 arası satın alma ilgisi (isteksizse düşük, hevesliyse yüksek),
 "too_cheap": bu fiyatın altında kaliteden şüphelenir (USD),
 "cheap": bu fiyat uygun / kelepir (USD),
 "expensive": pahalı ama düşünür (USD),
 "too_expensive": bu fiyatın üstünde asla almaz (USD),
 "objection": ürüne en büyük itiraz, tek kısa cümle (yoksa ""),
 "estimated": fiyat eşiklerinden en az biri cevapta açıkça yazmıyor, cevabın tonundan tahmin ettiysen true
}}
Kurallar: fiyatlar artan olmalı (too_cheap < cheap < expensive < too_expensive). Cevapta hiç fiyat ya da
fiyat algısı yoksa fiyat alanlarına null yaz; uydurma."""


def _objects(text: str):
    """Metindeki tüm üst düzey JSON nesnelerini sırayla üretir."""
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


def validate_answer(raw: dict) -> Optional[dict]:
    """Ham sözlüğü doğrular; fiyat sırası bozuksa sıralar. Eksik/geçersizse None."""
    try:
        vals = sorted(float(raw[k]) for k in ("too_cheap", "cheap", "expensive", "too_expensive"))
        interest = max(0.0, min(100.0, float(raw["interest"])))
    except (ValueError, KeyError, TypeError):
        return None
    if vals[0] <= 0 or len(set(vals)) < 4:
        return None
    return {"interest": interest, "prices": vals, "objection": str(raw.get("objection") or "").strip(),
            "estimated": bool(raw.get("estimated", False))}


def parse_agent_answer(text: str) -> Optional[dict]:
    """Ajan cevabında (kod bloğu içinde de olsa) geçerli bir JSON nesnesi arar."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    for obj in _objects(text):
        if (answer := validate_answer(obj)) is not None:
            return answer
    return None


class AnswerExtractor:
    def __init__(self, llm: LLMClient, max_chars: int = 2000):
        self.llm = llm
        self.max_chars = max_chars

    async def extract(self, text: str, currency_note: str = "") -> Optional[dict]:
        """Serbest metni LLM ile alanlara çevirir; başarısızsa None (hata ayrıntısı `last_error`)."""
        prompt = PROMPT.format(text=(text or "")[: self.max_chars], currency=f"\n{currency_note}" if currency_note else "")
        self.last_error: Optional[str] = None
        try:
            raw = await self.llm.chat_json(SYSTEM, prompt, retries=1)
        except LLMError as e:
            self.last_error = str(e)
            return None
        return validate_answer(raw) if isinstance(raw, dict) else None
