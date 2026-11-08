"""Marka → fiyat katmanı eşlemesi (kural varsayımı, `panel_data/marka_katmanlari.csv`).

Kaynaklardaki marka adları gürültülüdür ("Abdullah Kiğılı Azerbaijan", "Cacharel Türkiye", "Damat Tween Baghdad").
Eşleme, normalize edilmiş bilinen marka adının kiracı adı içinde ardışık kelimeler olarak geçmesine bakar;
en uzun eşleşme kazanır. Kısa adlar (5 harften az: "gap", "next", "boss") yalnızca ad bu kelimeyle başlıyorsa eşleşir.
"""
import csv
import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Tuple

TIER_SCORE = {"budget": 0.0, "mass": 0.25, "upper_mass": 0.5, "premium": 0.75, "luxury": 1.0}
TIER_TR = {"budget": "ekonomik", "mass": "kitlesel", "upper_mass": "üst-kitlesel", "premium": "premium", "luxury": "lüks"}


def norm_tokens(text: str) -> Tuple[str, ...]:
    t = (text or "").replace("ı", "i").replace("İ", "i").casefold()
    t = unicodedata.normalize("NFKD", t)
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = t.replace("&", " and ")
    return tuple(w for w in re.split(r"[^0-9a-z]+", t) if w)


class TierMap:
    def __init__(self, entries: Dict[Tuple[str, ...], Tuple[str, str]]):
        self._entries = entries  # tokens -> (görünen ad, katman)

    @classmethod
    def load(cls, path: Path) -> "TierMap":
        entries: Dict[Tuple[str, ...], Tuple[str, str]] = {}
        if not path.exists():
            return cls(entries)
        with path.open(encoding="utf-8") as f:
            rows = [line for line in f if line.strip() and not line.lstrip().startswith("#")]
        for row in csv.DictReader(rows):
            tier = (row.get("katman") or "").strip()
            name = (row.get("marka") or "").strip()
            if tier in TIER_SCORE and name:
                entries[norm_tokens(name)] = (name, tier)
        return cls(entries)

    def __len__(self) -> int:
        return len(self._entries)

    def match(self, *names: Optional[str]) -> Optional[Tuple[str, str]]:
        """(bilinen marka adı, katman) ya da None. Önce marka alanı, sonra mekân adı denenir."""
        for name in names:
            toks = norm_tokens(name or "")
            if not toks:
                continue
            best: Optional[Tuple[int, Tuple[str, str]]] = None
            for key, val in self._entries.items():
                n = len(key)
                if n > len(toks):
                    continue
                short = n == 1 and len(key[0]) < 5
                starts = range(1) if short else range(len(toks) - n + 1)
                if any(toks[i:i + n] == key for i in starts):
                    score = sum(len(k) for k in key)
                    if best is None or score > best[0]:
                        best = (score, val)
            if best:
                return best[1]
        return None


def segment_label(index: Optional[float]) -> Optional[str]:
    if index is None:
        return None
    for limit, tier in ((0.125, "budget"), (0.375, "mass"), (0.625, "upper_mass"), (0.875, "premium")):
        if index < limit:
            return TIER_TR[tier]
    return TIER_TR["luxury"]


def known_scores(tenants, tiers: TierMap) -> List[Tuple[str, str]]:
    """Kiracılardan tekil (marka, katman) listesi; aynı marka iki kez sayılmaz."""
    seen: Dict[str, str] = {}
    for t in tenants:
        hit = tiers.match(t.brand, t.name)
        if hit and hit[0] not in seen:
            seen[hit[0]] = hit[1]
    return sorted(seen.items())
