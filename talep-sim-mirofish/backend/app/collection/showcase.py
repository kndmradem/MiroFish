"""Vitrin turu: panel kişileri koleksiyonu ürün ürün değil, gruplar halinde bir arada görür ve seçim yapar.

- Her kişi, ürünleri en fazla `block_size` ürünlük gruplar halinde görür (7B model için 8 önerilir; uzun listede
  model baştakileri unutur).
- Sıra etkisini azaltmak için her kişi farklı sırayla görür: koleksiyon küçükse (tek grup) temel sıra kişiden kişiye
  döndürülür, böylece her ürün her konumda yaklaşık eşit sayıda görünür; büyükse her kişi için ürünler iki kez farklı
  karıştırılıp gruplara bölünür (her ürün iki kez, farklı komşularla görünür).
- Ürün kodu ve dosya adı prompta konmaz; ürünler A, B, C... harfleriyle verilir.
- Sorular: en çok almak istediği (en fazla 3), kesinlikle almayacağı (en fazla 2), birlikte alacağı çiftler,
  birinden birini alacağı (birbirinin yerine geçen) çiftler, gruptan kaç parça alacağı, tek cümle yorum.
- Seçilen ürünlerin konumu kaydedilir; ilk ya da son konum belirgin fazla seçiliyorsa sonuçta uyarı çıkar.
"""
import asyncio
import hashlib
import json
import math
import random
import string
from typing import Callable, Dict, List, Optional, Sequence

from .. import brand as brandlib
from ..models import BrandProfile
from ..panel import prompts
from ..panel.library import sample_panel
from ..services.answer_extractor import _objects

LETTERS = string.ascii_uppercase
MAX_BEST, MAX_WORST, MAX_PAIRS = 3, 2, 3
MARKER = "VİTRİN TURU"


def _rng(*parts) -> random.Random:
    return random.Random(int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:12], 16))


def plan_blocks(skus: Sequence[str], person: int, n_persons: int, block_size: int, seed: str) -> List[List[str]]:
    """Bir kişinin göreceği gruplar (her biri ürün listesi, gösterim sırasıyla)."""
    skus = list(skus)
    n = len(skus)
    if n == 0:
        return []
    base = skus[:]
    _rng(seed, "base").shuffle(base)
    if n <= block_size:
        # Döndürme: kişi k, temel sırayı kaydırılmış görür; her ürün her konumda yaklaşık eşit sayıda (Latin kare
        # benzeri). Kişi sayısı ürün sayısını aşınca sonraki tur ters sırayla döner (komşular da değişsin).
        step = max(1, n // n_persons) if n_persons < n else 1
        k = (person * step) % n
        order = base[k:] + base[:k]
        if (person * step // n) % 2:
            order.reverse()
        return [order]
    blocks: List[List[str]] = []
    n_blocks = math.ceil(n / block_size)
    for rep in range(2):
        order = base[:]
        _rng(seed, person, rep).shuffle(order)
        size = math.ceil(n / n_blocks)        # grupları eşit boyda tut (ör. 12 ürün -> 6+6, 8+4 değil)
        blocks += [order[i:i + size] for i in range(0, n, size)]
    return blocks


def item_line(letter: str, card: dict, price_usd: Optional[float], try_rate: Optional[float]) -> str:
    price = ""
    if price_usd:
        price = f" Fiyat: ${price_usd:.0f}" + (f" (yaklaşık ₺{price_usd * try_rate:,.0f})".replace(",", ".") if try_rate else "") + "."
    feats = ", ".join(k for k, v in (card.get("features") or {}).items() if v)
    parts = [f"{letter}) {card.get('product_name', '-')}."]
    if card.get("visual_description"):
        parts.append(f"Görünüm: {str(card['visual_description'])[:220]}.")
    if card.get("fabric_texture") or card.get("composition"):
        parts.append(f"Kumaş: {card.get('fabric_texture') or ''} {card.get('composition') or ''}".strip() + ".")
    if card.get("style_category"):
        parts.append(f"Stil: {card['style_category']}.")
    if feats:
        parts.append(f"Öne çıkan: {feats}.")
    return " ".join(parts) + price


def user_prompt(lines: List[str], letters: List[str], ctx, brand: Optional[BrandProfile], region: str) -> str:
    brand_block = ""
    if brand is not None:
        brand_block = (f"Marka: {brand.name} ({brandlib.TIER_LABEL[brand.price_tier]} segment). {brand.positioning} "
                       f"Bu bölgedeki bilinirliği: {brandlib.region_strength(brand, region)}/100.\n")
    last = letters[-1]
    return (
        f"{prompts.context_text(ctx)}\n\n"
        f"{MARKER}: Bir mağazanın yeni koleksiyonundan şu ürünler yan yana sergileniyor. Hepsine birlikte bak ve kendi "
        "gözünle seç. Fiyatlar ABD doları.\n"
        f"{brand_block}\n" + "\n".join(lines) + "\n\n"
        f"Sorular (yalnızca A-{last} harflerini kullan):\n"
        f"- best: en çok almak istediğin en fazla {MAX_BEST} ürün (hiçbirini istemiyorsan boş liste)\n"
        f"- worst: kesinlikle almayacağın en fazla {MAX_WORST} ürün\n"
        f"- together: birlikte alıp kombinleyeceğin ürün çiftleri, en fazla {MAX_PAIRS} (ör. [[\"A\",\"C\"]])\n"
        "- substitutes: birbirinin yerine geçen, 'ikisinden birini alırım' dediğin çiftler\n"
        "- n_buy: bu ürünlerden toplam kaç parça alırdın (0 olabilir)\n"
        "- comment: bu ürünlerin bir arada nasıl göründüğü hakkında tek kısa cümle\n"
        "Herkes her ürünü beğenmez; listedeki sıraya göre değil, kendi zevkine göre seç.\n"
        'Sadece şu biçimde JSON yaz: {"best": ["B"], "worst": ["D"], "together": [["B","E"]], '
        '"substitutes": [], "n_buy": 1, "comment": "..."}'
    )


def schema(letters: List[str]) -> dict:
    L = {"type": "string", "enum": letters}
    pair = {"type": "array", "items": L, "minItems": 2, "maxItems": 2}
    return {
        "type": "object",
        "properties": {
            "best": {"type": "array", "items": L, "maxItems": MAX_BEST},
            "worst": {"type": "array", "items": L, "maxItems": MAX_WORST},
            "together": {"type": "array", "items": pair, "maxItems": MAX_PAIRS},
            "substitutes": {"type": "array", "items": pair, "maxItems": MAX_PAIRS},
            "n_buy": {"type": "integer", "minimum": 0, "maximum": 20},
            "comment": {"type": "string"},
        },
        "required": ["best", "worst", "together", "substitutes", "n_buy", "comment"],
        "additionalProperties": False,
    }


def parse(text: str, letters: List[str]) -> Optional[dict]:
    """Hoşgörülü okuma: geçersiz harfler atılır, aynı ürün hem en iyi hem en kötüde ise ikisinden de çıkar."""
    ok = set(letters)

    def lst(v, cap):
        out = []
        for x in v if isinstance(v, list) else []:
            x = str(x).strip().upper()[:1]
            if x in ok and x not in out:
                out.append(x)
        return out[:cap]

    def pairs(v):
        out = []
        for p in v if isinstance(v, list) else []:
            if isinstance(p, (list, tuple)) and len(p) >= 2:
                a, b = str(p[0]).strip().upper()[:1], str(p[1]).strip().upper()[:1]
                if a in ok and b in ok and a != b and sorted((a, b)) not in out:
                    out.append(sorted((a, b)))
        return out[:MAX_PAIRS]

    for obj in _objects(text):
        if not any(k in obj for k in ("best", "worst")):
            continue
        best, worst = lst(obj.get("best"), MAX_BEST), lst(obj.get("worst"), MAX_WORST)
        both = set(best) & set(worst)
        try:
            n_buy = max(0, min(20, int(obj.get("n_buy") or 0)))
        except (TypeError, ValueError):
            n_buy = 0
        return {"best": [x for x in best if x not in both], "worst": [x for x in worst if x not in both],
                "together": pairs(obj.get("together")), "substitutes": pairs(obj.get("substitutes")),
                "n_buy": n_buy, "comment": str(obj.get("comment") or "")[:300]}
    return None


async def run_region(engine, region: str, panel_seed: str, brand: Optional[BrandProfile], cards: Dict[str, dict],
                     prices_usd: Dict[str, Optional[float]], try_rate: Optional[float], block_size: int,
                     done: Dict[str, dict], save: Callable[[dict], None], note: Callable[[str], None]) -> List[dict]:
    """Bir bölgede vitrin turu. `done`: önceden cevaplanmış (kişi|grup) kayıtları; tekrar sorulmaz."""
    lib = engine.store.personas(region, engine.persona_version)
    ctx = engine.store.context(region, engine.as_of)
    cal = engine.calibration.for_region(region)
    seed = f"{panel_seed}|{brand.name if brand else ''}|{region}"     # tek tek turla aynı kişiler
    members = sample_panel(lib, engine.panel_size, seed, cal.sensitivity_scale, cal.trend_scale)
    skus = sorted(cards)
    jobs = []
    for m in members:
        for bi, block in enumerate(plan_blocks(skus, m.index - 1, len(members), block_size, seed)):
            if len(block) >= 2:
                jobs.append((m, bi, block))
    out: List[dict] = [done[k] for k in done]
    todo = [(m, bi, b) for m, bi, b in jobs if f"{m.index}|{bi}" not in done]
    count = {"n": len(jobs) - len(todo)}

    async def one(m, bi, block):
        letters = list(LETTERS[:len(block)])
        lines = [item_line(L, cards[s], prices_usd.get(s), try_rate) for L, s in zip(letters, block)]
        rep = await engine.llm.ask_json(prompts.system_prompt(m), user_prompt(lines, letters, ctx, brand, region),
                                        schema(letters), lambda t: parse(t, letters),
                                        seed=int(hashlib.sha256(f"{seed}|{m.index}|{bi}|vitrin".encode()).hexdigest()[:8], 16))
        rec = {"key": f"{m.index}|{bi}", "region": region, "person": m.index, "segment": m.segment.label, "block": bi,
               "order": block, "letters": dict(zip(letters, block)), "status": rep.status,
               "answer": rep.answer, "text": (rep.text or rep.error)[:800]}
        out.append(rec)
        save(rec)
        count["n"] += 1
        note(f"{region} vitrin turu: {count['n']}/{len(jobs)} grup cevaplandı")

    await asyncio.gather(*(one(*j) for j in todo))
    return out


def load_jsonl(path) -> Dict[str, dict]:
    out = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
                out[r["key"]] = r
            except (ValueError, KeyError):
                continue
    return out
