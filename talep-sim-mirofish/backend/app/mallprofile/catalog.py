"""Yerel AVM kataloğu: `panel_data/malls/<ÜLKE>/<şehir>.json`. Müşteri kurulumunda yalnızca okunur, ağa çıkmaz."""
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .models import Mall, MallCatalog
from .tiers import norm_tokens

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "panel_data" / "malls"


def city_slug(sehir: str) -> str:
    return "-".join(norm_tokens(sehir)) or "sehir"


def catalog_path(root: Path, ulke: str, sehir: str) -> Path:
    return root / ulke.upper() / f"{city_slug(sehir)}.json"


class MallStore:
    def __init__(self, root: Optional[Path | str] = None):
        self.root = Path(root) if root else DEFAULT_DIR
        self._cache: Dict[Path, Tuple[float, MallCatalog]] = {}

    def cities(self) -> List[dict]:
        out = []
        for path in sorted(self.root.glob("*/*.json")):
            cat = self._read(path)
            out.append({"ulke": cat.ulke, "sehir": cat.sehir, "mall_count": len(cat.malls),
                        "verified": cat.verified, "source": cat.source.model_dump(mode="json")})
        return out

    def catalog(self, ulke: str, sehir: str) -> Optional[MallCatalog]:
        path = catalog_path(self.root, ulke, sehir)
        if path.exists():
            return self._read(path)
        # Şehir adı farklı yazılmış olabilir (İstanbul / Istanbul): katalogdaki sehir alanıyla karşılaştır
        want = norm_tokens(sehir)
        for p in (self.root / ulke.upper()).glob("*.json"):
            cat = self._read(p)
            if norm_tokens(cat.sehir) == want:
                return cat
        return None

    def search(self, ulke: str, sehir: str, q: str = "", limit: int = 15) -> List[Mall]:
        cat = self.catalog(ulke, sehir)
        if cat is None:
            return []
        qt = norm_tokens(q)

        def score(m: Mall) -> Optional[int]:
            if not qt:
                return m.apparel_count
            best = None
            for name in [m.name, *m.aliases]:
                toks = norm_tokens(name)
                if all(any(t.startswith(w) for t in toks) for w in qt):
                    s = 1000 + m.apparel_count + (500 if toks[: len(qt)] == qt else 0)
                    best = max(best or 0, s)
            return best

        scored = [(s, m) for m in cat.malls for s in [score(m)] if s is not None]
        return [m for _, m in sorted(scored, key=lambda x: -x[0])[:limit]]

    def get(self, ulke: str, sehir: str, mall_id: str) -> Optional[Mall]:
        cat = self.catalog(ulke, sehir)
        return next((m for m in cat.malls if m.id == mall_id), None) if cat else None

    def _read(self, path: Path) -> MallCatalog:
        mtime = path.stat().st_mtime
        hit = self._cache.get(path)
        if hit is None or hit[0] != mtime:
            hit = (mtime, MallCatalog.model_validate(json.loads(path.read_text(encoding="utf-8"))))
            self._cache[path] = hit
        return hit[1]
