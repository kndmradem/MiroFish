"""Bağlam paketi taslağı: BİZİM sunucumuzda, web aramalı bulut modelle (yalnızca kamuya açık bilgi).

Müşteri verisi bu modüle hiç girmez: `DraftRequest` yalnızca bölge kodu, tarih ve genel kategori adı alır.
Ürün, maliyet, satış ya da müşteri bilgisi taşıyan bir alan yoktur; kategori adları da kısa genel ifade olmak
zorundadır. Bu modül müşteri kurulumunda çalıştırılmaz (orada yalnızca bundle.import_bundle vardır).

Taslaktaki kaynaksız her bilgi atılır ve raporda listelenir; taslak her zaman verified=false'tur, insan onayı
(review.approve) olmadan dağıtılamaz.
"""
import json
import re
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional, Protocol, Tuple

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator

from ..models import ALL_REGIONS
from ..panel.library import CompetitorPrice, ContextPack, Macro, Source, Trend
from ..services.llm import extract_json, http_error_text

REGION_NAMES = {"TR": "Türkiye", "EU": "Avrupa Birliği (özellikle Almanya, Fransa, İtalya, İspanya, Hollanda)",
                "MENA": "Körfez ülkeleri ve Kuzey Afrika (BAE, Suudi Arabistan, Katar, Mısır)",
                "CIS": "Kazakistan, Azerbaycan, Özbekistan, Rusya", "US": "Amerika Birleşik Devletleri"}
MAX_SOURCE_AGE_DAYS = 120


class DraftRequest(BaseModel):
    region: str
    as_of: date
    categories: List[str] = Field(default_factory=lambda: ["kadın giyim", "erkek giyim", "dış giyim"], max_length=10)

    @field_validator("region")
    @classmethod
    def _region(cls, v):
        if v not in ALL_REGIONS:
            raise ValueError(f"bölge {ALL_REGIONS} içinden olmalı")
        return v

    @field_validator("categories")
    @classmethod
    def _generic(cls, v):
        # Yalnızca kısa genel kategori adları: ürün kodu, fiyat, sayı ya da uzun metin (müşteri bilgisi) giremez
        for c in v:
            if len(c) > 40 or re.search(r"\d|@|\$|₺|€", c):
                raise ValueError(f"kategori genel ve kısa olmalı (sayı/kod/fiyat içeremez): {c!r}")
        return v


class Researcher(Protocol):
    async def research(self, system: str, prompt: str) -> str: ...


class OpenAICompatResearcher:
    """OpenAI uyumlu uç nokta (OpenAI, Gemini'nin OpenAI uyumlu ucu, OpenRouter vb.).

    Web araması sağlayıcıya özeldir; `extra_body` ile açılır (ör. sağlayıcının arama aracı tanımı). Hangi
    modelin hangi koşulla arama yaptığı sağlayıcının güncel dokümanından kontrol edilmeli.
    """

    def __init__(self, base_url: str, model: str, api_key: str, extra_body: Optional[dict] = None,
                 client: Optional[httpx.AsyncClient] = None, timeout: float = 300):
        self.base_url, self.model, self.api_key = base_url.rstrip("/"), model, api_key
        self.extra_body = extra_body or {}
        self.client = client or httpx.AsyncClient(timeout=timeout)

    async def research(self, system: str, prompt: str) -> str:
        body = {"model": self.model, "temperature": 0.1,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                **self.extra_body}
        resp = await self.client.post(f"{self.base_url}/chat/completions", json=body,
                                      headers={"Authorization": f"Bearer {self.api_key}"})
        if resp.status_code >= 400:
            raise httpx.HTTPStatusError(http_error_text(resp), request=resp.request, response=resp)
        return resp.json()["choices"][0]["message"]["content"] or ""


SYSTEM = ("Bir perakende araştırma asistanısın. Web aramasıyla yalnızca güncel ve kaynağı gösterilebilen bilgileri "
          "topla. Her bilgi için gerçekten açtığın sayfanın linkini ve yayın tarihini ver. Linki bilmiyorsan o bilgiyi "
          "YAZMA. Tahmin, yorum ya da kendi bilgini ekleme. Sadece JSON dön.")

PROMPT = """Bölge: {region_name} ({region})
Tarih: {as_of} itibarıyla
Kategoriler: {categories}

Bu bölgedeki giyim tüketicisi için şu bilgileri topla (son {max_age} gün içinde yayımlanmış kaynaklardan):
- inflation_yoy_pct: yıllık tüketici enflasyonu (sayı) ve resmi kaynağı
- consumer_confidence: tüketici güveni, kısa cümle ve kaynağı
- purchasing_power: alım gücü/hane harcaması eğilimi, kısa cümle ve kaynağı
- fx_note: yerel paranın USD'ye karşı son durumu, kısa cümle ve kaynağı
- season_notes: önümüzdeki 4-8 haftanın hava/mevsim beklentisi ve kaynağı
- shopping_notes: önümüzdeki 4-8 haftadaki indirim dönemleri ve özel günler ve kaynağı
- trends: kategorilerle ilgili en fazla 6 güncel trend notu, her biri kaynaklı
- competitor_prices: benzer giyim ürünleri için en fazla 5 örnek perakende fiyatı (USD), her biri kaynaklı

Biçim:
{{"macro": {{"inflation_yoy_pct": 0.0, "consumer_confidence": "...", "purchasing_power": "...", "fx_note": "..."}},
 "season_notes": "...", "shopping_notes": "...",
 "field_sources": {{"inflation_yoy_pct": [{{"url": "https://...", "title": "...", "published_at": "YYYY-MM-DD"}}], "...": []}},
 "trends": [{{"note": "...", "as_of": "YYYY-MM-DD", "sources": [{{"url": "https://...", "title": "...", "published_at": "YYYY-MM-DD"}}]}}],
 "competitor_prices": [{{"item": "...", "price_usd": 0.0, "as_of": "YYYY-MM-DD", "sources": [{{"url": "https://..."}}]}}]}}
Bulamadığın alanı boş bırak ("" ya da null)."""

FIELDS = ("inflation_yoy_pct", "consumer_confidence", "purchasing_power", "fx_note", "season_notes", "shopping_notes")


@dataclass
class DraftReport:
    kept: List[str] = field(default_factory=list)
    dropped: List[str] = field(default_factory=list)
    old_sources: List[str] = field(default_factory=list)


def _sources(raw, today: date) -> List[Source]:
    out = []
    for s in raw or []:
        try:
            src = Source.model_validate(s)
        except ValidationError:
            continue
        out.append(src.model_copy(update={"retrieved_at": src.retrieved_at or today}))
    return out


def build_draft(req: DraftRequest, raw: dict, today: Optional[date] = None) -> Tuple[ContextPack, DraftReport]:
    """Model çıktısını pakete çevirir; kaynaksız bilgi atılır. Saf fonksiyon (testlenebilir)."""
    today = today or date.today()
    rep = DraftReport()
    fsrc_raw = raw.get("field_sources") or {}
    macro_raw = raw.get("macro") or {}
    values = {f: (macro_raw.get(f) if f in Macro.model_fields else raw.get(f)) for f in FIELDS}
    field_sources, kept_vals = {}, {}
    for f, v in values.items():
        if v in (None, ""):
            continue
        srcs = _sources(fsrc_raw.get(f), today)
        if not srcs:
            rep.dropped.append(f"{f}: kaynak linki yok")
            continue
        field_sources[f], kept_vals[f] = srcs, v
        rep.kept.append(f)

    def items(key, model):
        out = []
        for i, it in enumerate(raw.get(key) or []):
            srcs = _sources(it.get("sources"), today) if isinstance(it, dict) else []
            if not srcs:
                rep.dropped.append(f"{key}[{i}]: kaynak linki yok")
                continue
            try:
                out.append(model.model_validate({**it, "sources": [s.model_dump() for s in srcs],
                                                 "source": srcs[0].url}))
                rep.kept.append(f"{key}[{i}]")
            except ValidationError as e:
                rep.dropped.append(f"{key}[{i}]: geçersiz ({e.errors()[0]['msg']})")
        return out

    trends, comps = items("trends", Trend), items("competitor_prices", CompetitorPrice)
    for name, srcs in [(k, v) for k, v in field_sources.items()] + \
            [(f"trend: {t.note[:40]}", t.sources) for t in trends] + \
            [(f"rakip fiyatı: {c.item[:40]}", c.sources) for c in comps]:
        if all(s.published_at and (today - s.published_at).days > MAX_SOURCE_AGE_DAYS for s in srcs):
            rep.old_sources.append(name)
    try:
        inflation = float(kept_vals["inflation_yoy_pct"]) if "inflation_yoy_pct" in kept_vals else None
    except (TypeError, ValueError):
        inflation = None
        rep.dropped.append("inflation_yoy_pct: sayı değil")
        field_sources.pop("inflation_yoy_pct", None)
    pack = ContextPack(
        region=req.region, version=f"{req.as_of.isoformat()}-taslak", as_of=req.as_of,
        source="Bulut model taslağı (web aramalı); insan onayı bekliyor", owner="", verified=False,
        macro=Macro(inflation_yoy_pct=inflation, consumer_confidence=kept_vals.get("consumer_confidence"),
                    purchasing_power=kept_vals.get("purchasing_power"), fx_note=kept_vals.get("fx_note")),
        season_notes=kept_vals.get("season_notes", ""), shopping_notes=kept_vals.get("shopping_notes", ""),
        trends=trends, competitor_prices=comps, field_sources=field_sources)
    return pack, rep


async def draft_pack(req: DraftRequest, researcher: Researcher, today: Optional[date] = None) -> Tuple[ContextPack, DraftReport]:
    prompt = PROMPT.format(region=req.region, region_name=REGION_NAMES[req.region], as_of=req.as_of.isoformat(),
                           categories=", ".join(req.categories), max_age=MAX_SOURCE_AGE_DAYS)
    raw = extract_json(await researcher.research(SYSTEM, prompt))
    if not isinstance(raw, dict):
        raise ValueError("Model JSON nesnesi dönmedi")
    return build_draft(req, raw, today)


def report_text(rep: DraftReport) -> str:
    lines = [f"Tutulan bilgi: {len(rep.kept)}", f"Atılan (kaynaksız/geçersiz): {len(rep.dropped)}"]
    lines += [f"  - {d}" for d in rep.dropped]
    if rep.old_sources:
        lines.append(f"{MAX_SOURCE_AGE_DAYS} günden eski kaynağa dayanan: " + "; ".join(rep.old_sources))
    lines.append("Sonraki adım: her linki açıp kontrol et, gerekirse düzelt, sonra 'onayla'.")
    return "\n".join(lines)


def dump(pack: ContextPack) -> str:
    return json.dumps(json.loads(pack.model_dump_json()), ensure_ascii=False, indent=2)
