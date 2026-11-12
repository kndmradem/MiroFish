"""Takvim turu: ürünün takvim etkinliklerine uygunluğu ve büyük indirimi bekleme eğilimi.

Panel kişilerinin her birine tek LLM çağrısıyla sorulur (koleksiyon vitrin turuyla aynı altyapı):
- Her etkinlik için 0-3 uygunluk (0 almam, 1 belki, 2 muhtemelen, 3 kesin bu dönemde alırım). Soru metni
  etkinlik_turleri.csv'den gelir; etkinliğe özel kod yoktur.
- Penceredeki ilk büyük indirim etkinliği için: bugün tam fiyatla mı alır, o indirimi mi bekler, hiç mi almaz.

Motor davranışı:
- panel: kişiler doğrudan sorulur (dayanak "ajan").
- hybrid: MiroFish'te bu soru yok; panel tarafı kullanılır ve sonuçta yazılır.
- mirofish (yalnız): ajan sorusu yapılmaz, yalnızca kural varsayımı (segment eşleşmesi) kullanılır.
- mock: deterministik sahte cevap (yalnızca akışı sınar, "mock" etiketli).

Ajanlar kampanyanın satışı kaç kat artırdığını söyleyemez; bu sayı etkinlik türü aralığından (kural varsayımı)
gelir ve ajanların uygunluk payıyla ölçeklenir.
"""
import asyncio
import csv
import hashlib
import string
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from .data import DEFAULT_DIR, Event, Takvim

LETTERS = string.ascii_uppercase
MARKER = "TAKVİM TURU"
MAX_EVENTS = 8
WAIT_CHOICES = ("hemen", "bekle", "almam")


@dataclass
class EventFit:
    code: str
    fit: float                    # 0-1
    basis: str                    # ajan | kural varsayımı | mock
    n: int = 0
    rule_fit: float = 0.5
    comments: List[str] = field(default_factory=list)


@dataclass
class FitResult:
    fits: Dict[str, EventFit]
    wait_event: Optional[str] = None
    wait_share: Optional[float] = None      # bekle / (hemen + bekle)
    wait_n: int = 0
    wait_basis: str = ""
    engine: str = "kural"
    note: str = ""
    raw: List[dict] = field(default_factory=list)


def _norm(s: str) -> str:
    return (s or "").lower().replace("ı", "i").replace("İ", "i")


def load_synonyms(folder: Optional[str] = None) -> Dict[str, List[str]]:
    p = (Path(folder) if folder else DEFAULT_DIR) / "segment_esanlam.csv"
    if not p.exists():
        return {}
    with p.open(encoding="utf-8-sig", newline="") as f:
        return {r["etiket"].strip().lower(): [_norm(w.strip()) for w in r["kelimeler"].split(";") if w.strip()]
                for r in csv.DictReader(f)}


def product_text(card: dict, extra: str = "") -> str:
    parts = [card.get("product_name", ""), card.get("style_category", ""), card.get("visual_description", ""),
             card.get("fabric_texture", ""), card.get("composition", ""), extra]
    return _norm(" ".join(str(p) for p in parts if p))


def rule_fit(event: Event, text: str, syn: Dict[str, List[str]]) -> float:
    """Kural varsayımı: etkinliğin segment etiketleri ürün metninde geçiyorsa 0,8; etiket yok ya da 'genel' ise 0,5;
    etiketler var ama hiçbiri eşleşmiyorsa 0,25."""
    tags = [t for t in event.segments if t != "genel"]
    if not tags:
        return 0.5
    for t in tags:
        words = syn.get(t, [_norm(t.replace("_", " "))])
        if any(w and w in text for w in words):
            return 0.8
    return 0.25


def _pick_events(events: Sequence[Event]) -> List[Event]:
    seen, out = set(), []
    for e in events:
        if e.code not in seen:
            seen.add(e.code)
            out.append(e)
    return out[:MAX_EVENTS]


def wait_event_of(events: Sequence[Event], takvim: Takvim) -> Optional[Event]:
    """Bekleme sorusu penceredeki en büyük indirim etkinliği için sorulur (tür aralığının üst ucu en yüksek olan,
    eşitlikte en erken)."""
    cands = [e for e in events if takvim.types[e.kind].ask_wait]
    return min(cands, key=lambda e: (-takvim.types[e.kind].lift_high_pct, e.start)) if cands else None


def user_prompt(card: dict, events: List[Event], letters: List[str], takvim: Takvim, wait: Optional[Event],
                price_usd: float, try_rate: Optional[float], ctx_text: str, brand_line: str) -> str:
    feats = ", ".join(k for k, v in (card.get("features") or {}).items() if v)
    price = f"${price_usd:.0f}" + (f" (yaklaşık ₺{price_usd * try_rate:,.0f})".replace(",", ".") if try_rate else "")
    lines = []
    for L, e in zip(letters, events):
        q = takvim.types[e.kind].question.replace("{etkinlik}", e.name)
        lines.append(f"{L}) {e.name} ({e.start.strftime('%d.%m.%Y')}"
                     f"{'' if e.end == e.start else ' - ' + e.end.strftime('%d.%m.%Y')}): {q}")
    wait_q = ""
    if wait is not None:
        wait_q = (f"- wait: bu ürünü bugün {price} tam fiyatla görsen ne yaparsın? \"hemen\" (şimdi alırım), "
                  f"\"bekle\" ({wait.name} indirimini beklerim), \"almam\"\n")
    return (
        f"{ctx_text}\n\n{MARKER}: Aşağıdaki ürünü önümüzdeki aylardaki alışveriş dönemleri açısından değerlendir.\n"
        f"{brand_line}"
        f"Ürün: {card.get('product_name', '-')}. "
        + (f"Görünüm: {str(card['visual_description'])[:220]}. " if card.get("visual_description") else "")
        + (f"Stil: {card['style_category']}. " if card.get("style_category") else "")
        + (f"Öne çıkan: {feats}. " if feats else "")
        + f"Fiyat: {price}.\n\nDönemler:\n" + "\n".join(lines) + "\n\n"
        f"Sorular:\n- fit: her harf için 0-3 puan (0 bu dönemde almam, 1 belki, 2 muhtemelen, 3 kesin bu dönemde alırım "
        "ya da hediye ederim). Her dönem herkese uymaz; kendi hayatına göre puanla.\n"
        f"{wait_q}- comment: tek kısa cümle\n"
        # Örnek değer verilmez: küçük model örnekteki puanı ("1") ve "hemen"i her ürün için aynen kopyalıyordu.
        "Sadece şu biçimde JSON yaz; <...> yerlerine KENDİ cevabını koy (yer tutucuları kopyalama):\n"
        '{"fit": {' + ", ".join(f'"{L}": <0-3>' for L in letters) + "}"
        + (', "wait": "<hemen|bekle|almam>"' if wait is not None else "") + ', "comment": "<tek kısa cümle>"}'
    )


def schema(letters: List[str], with_wait: bool) -> dict:
    props = {"fit": {"type": "object", "properties": {L: {"type": "integer", "minimum": 0, "maximum": 3} for L in letters},
                     "required": letters, "additionalProperties": False},
             "comment": {"type": "string"}}
    req = ["fit", "comment"]
    if with_wait:
        props["wait"] = {"type": "string", "enum": list(WAIT_CHOICES)}
        req.insert(1, "wait")
    return {"type": "object", "properties": props, "required": req, "additionalProperties": False}


def parse(text: str, letters: List[str], with_wait: bool) -> Optional[dict]:
    from ..services.answer_extractor import _objects
    for obj in _objects(text):
        fit = obj.get("fit")
        if not isinstance(fit, dict):
            continue
        out = {}
        for L in letters:
            v = fit.get(L, fit.get(L.lower()))
            try:
                out[L] = max(0, min(3, int(round(float(v)))))
            except (TypeError, ValueError):
                continue
        if len(out) < max(1, len(letters) // 2):
            continue
        wait = _norm(str(obj.get("wait") or "")).strip()
        wait = next((w for w in WAIT_CHOICES if wait.startswith(w[:3])), None) if with_wait else None
        return {"fit": out, "wait": wait, "comment": str(obj.get("comment") or "")[:300]}
    return None


def _h(*parts) -> int:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


def _aggregate(answers: List[dict], events: List[Event], letters: List[str], rules: Dict[str, float], basis: str,
               wait: Optional[Event]) -> FitResult:
    fits = {}
    for L, e in zip(letters, events):
        vals = [a["fit"][L] for a in answers if L in a["fit"]]
        if vals:
            fits[e.code] = EventFit(e.code, round(sum(vals) / len(vals) / 3, 3), basis, len(vals), rules[e.code])
        else:
            fits[e.code] = EventFit(e.code, rules[e.code], "kural varsayımı", 0, rules[e.code])
    res = FitResult(fits)
    if wait is not None:
        w = [a["wait"] for a in answers if a.get("wait") in ("hemen", "bekle")]
        res.wait_event = wait.code
        if w:
            res.wait_share, res.wait_n, res.wait_basis = round(w.count("bekle") / len(w), 3), len(w), basis
    return res


async def ask_panel(panel, card: dict, region: str, events: List[Event], takvim: Takvim, brand, price_usd: float,
                    try_rate: Optional[float], rules: Dict[str, float]) -> FitResult:
    from .. import brand as brandlib
    from ..panel import prompts
    from ..panel.library import sample_panel
    lib = panel.store.personas(region, panel.persona_version)
    ctx = panel.store.context(region, panel.as_of)
    cal = panel.calibration.for_region(region)
    seed = f"{card.get('panel_seed') or card.get('product_name')}|{brand.name if brand else ''}|{region}"  # tek tek turla aynı kişiler
    from ..audience import plan_from_card
    members = sample_panel(lib, panel.panel_size, seed, cal.sensitivity_scale, cal.trend_scale,
                           audience=plan_from_card(card, region, panel.store.root))   # hedef kitleye göre aynı kişiler
    letters = list(LETTERS[:len(events)])
    wait = wait_event_of(events, takvim)
    brand_line = ""
    if brand is not None:
        brand_line = f"Marka: {brand.name} ({brandlib.TIER_LABEL[brand.price_tier]} segment). {brand.positioning}\n"
    up = user_prompt(card, events, letters, takvim, wait, price_usd, try_rate, prompts.context_text(ctx), brand_line)
    sch = schema(letters, wait is not None)

    async def one(m):
        rep = await panel.llm.ask_json(prompts.system_prompt(m), up, sch, lambda t: parse(t, letters, wait is not None),
                                       seed=_h(seed, m.index, "takvim"))
        return m, rep

    reps = await asyncio.gather(*(one(m) for m in members))
    answers = [r.answer for _, r in reps if r.answer]
    res = _aggregate(answers, events, letters, rules, "ajan", wait)
    res.engine = "panel"
    res.raw = [{"agent": m.index, "segment": m.segment.label, "status": r.status, "text": (r.text or r.error)[:600]}
               for m, r in reps]
    for (m, r) in reps:
        if r.answer and r.answer.get("comment"):
            for L, e in zip(letters, events):
                if r.answer["fit"].get(L, 0) >= 2 and len(res.fits[e.code].comments) < 3:
                    res.fits[e.code].comments.append(r.answer["comment"])
    if len(answers) < max(2, len(members) // 3):
        res.note = f"Takvim turunda {len(members)} kişiden yalnızca {len(answers)} geçerli cevap; eksik etkinlikler kural varsayımıyla."
    return res


def mock_fit(card: dict, region: str, events: List[Event], takvim: Takvim, rules: Dict[str, float], n: int = 12) -> FitResult:
    """Deterministik sahte cevap: kural uygunluğu etrafında kişi x etkinlik gürültüsü. Tüketici görüşü DEĞİLDİR."""
    letters = list(LETTERS[:len(events)])
    wait = wait_event_of(events, takvim)
    name = card.get("product_name", "")
    answers = []
    for i in range(n):
        fit = {}
        for L, e in zip(letters, events):
            x = rules[e.code] * 3 + ((_h(name, region, e.code, i) % 100) / 100 - 0.5) * 1.6
            fit[L] = max(0, min(3, round(x)))
        wait_ans = None
        if wait is not None:
            r = _h(name, region, "wait", i) % 100
            wait_ans = "bekle" if r < 35 else "almam" if r > 90 else "hemen"
        answers.append({"fit": fit, "wait": wait_ans, "comment": ""})
    res = _aggregate(answers, events, letters, rules, "mock", wait)
    res.engine = "mock"
    res.note = "Mock motor: takvim uygunluğu deterministik sahte cevaplardan; gerçek tüketici görüşü değildir."
    return res


async def evaluate(engine, card: dict, region: str, events: Sequence[Event], takvim: Takvim, brand, price_usd: float,
                   try_rate: Optional[float], extra_text: str = "", ask_agents: bool = True,
                   folder: Optional[str] = None) -> FitResult:
    events = _pick_events(events)
    syn = load_synonyms(folder)
    text = product_text(card, extra_text)
    rules = {e.code: rule_fit(e, text, syn) for e in events}
    if not events:
        return FitResult({}, engine="kural")
    rule_only = FitResult({e.code: EventFit(e.code, rules[e.code], "kural varsayımı", 0, rules[e.code]) for e in events},
                          engine="kural")
    w = wait_event_of(events, takvim)
    rule_only.wait_event = w.code if w else None
    if not ask_agents:
        rule_only.note = "Takvim turu kapalı (TAKVIM_TURU=false): uygunluk yalnızca segment eşleşmesinden (kural varsayımı)."
        return rule_only
    panel, note = engine, ""
    if hasattr(engine, "panel") and hasattr(engine, "mirofish"):
        panel, note = engine.panel, "MiroFish'te takvim sorusu yok: takvim turu persona paneliyle yapıldı."
    if hasattr(panel, "llm") and hasattr(panel, "store") and hasattr(panel.llm, "ask_json"):
        try:
            res = await ask_panel(panel, card, region, list(events), takvim, brand, price_usd, try_rate, rules)
        except Exception as e:  # LLM erişimi yoksa plan kural varsayımıyla devam eder
            rule_only.note = f"Takvim turu yapılamadı ({type(e).__name__}: {e}); uygunluk kural varsayımıyla."
            return rule_only
        res.note = " ".join(x for x in (note, res.note) if x)
        return res
    if type(engine).__name__ == "MockSimulationEngine":
        return mock_fit(card, region, list(events), takvim, rules)
    rule_only.note = "Bu motorda (yalnız MiroFish) takvim sorusu yok: uygunluk segment eşleşmesinden (kural varsayımı)."
    return rule_only
