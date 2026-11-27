"""Renk bazlı plan: modelin adedini renklere böler, renk başına minimum adedin altında kalan rengi eler ve
koleksiyonun renk dağılımını çıkarır.

Renk payının kaynağı değiştirilebilir:
- ERP (canlı kullanım): RENK_ERP_DOSYASI ile verilen CSV'de geçmiş satışlar (kategori, renk, adet; isteğe bağlı
  bolge). Bir kategoride yeterli satış varsa (RENK_ERP_MIN_ADET) renk ailelerinin satış payı kullanılır, dayanak "ERP".
- Kural varsayımı (şimdilik): panel_data/renk/renk_aileleri.csv içindeki aile ağırlıkları. Dosya düzenlenebilir;
  marka ya da kategoriye özel satır eklenebilir (kategori sütunu). Değerler doğrulanmamış taslaktır.

Ekran ve alanlar iki kaynakta da aynıdır; yalnızca dayanak etiketi ve açıklama değişir.
"""
import csv
import os
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

DATA_DIR = Path(__file__).resolve().parents[2] / "panel_data" / "renk"
DEFAULT_MIN_QTY = 300          # renk başına minimum adet (boya partisi); kural varsayımı
MIX_SLOPE = 0.5                # renk karışımı gücünün model adedine yansıma oranı
MIX_CLIP = (0.85, 1.15)        # renk karışımı çarpanının sınırları
ERP_MIN_UNITS = 200            # bir kategoride ERP renk payı kullanmak için gereken en az satış adedi
CONCENTRATION_PCT = 50.0       # bir renk ailesi koleksiyon adedinin bu kadarını geçerse uyarı
OVERLAP_MODELS = 3             # aynı kategoride baskın rengi aynı olan model sayısı bu kadarsa uyarı


def _fold(s: str) -> str:
    s = (s or "").lower().replace("ı", "i").replace("İ", "i")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


class FamilyTable:
    def __init__(self, rows: List[dict]):
        self.rows = rows
        self.labels = {r["aile"]: r.get("etiket") or r["aile"] for r in rows}
        self.keywords: List[Tuple[str, str]] = []
        for r in rows:
            for k in (r.get("eslesme") or "").split("|"):
                k = _fold(k)
                if k:
                    self.keywords.append((k, r["aile"]))
        self.keywords.sort(key=lambda x: -len(x[0]))        # uzun eşleşme önce (ör. "off white", "indigo blue")
        self.weights: Dict[str, Dict[str, float]] = {}      # kategori ("" = hepsi) -> aile -> ağırlık
        for r in rows:
            try:
                w = float(r.get("agirlik") or 1)
            except ValueError:
                w = 1.0
            self.weights.setdefault(_fold(r.get("kategori") or ""), {})[r["aile"]] = w
        self.unverified = any((r.get("dogrulandi") or "").strip().lower() not in ("evet", "yes", "true", "1") for r in rows)

    def family(self, color: str) -> str:
        c = f" {_fold(color)} "
        for k, fam in self.keywords:
            if f" {k} " in c:
                return fam
        return "diger"

    def label(self, fam: str) -> str:
        return self.labels.get(fam, fam)

    def weight(self, fam: str, category: str) -> float:
        cat = self.weights.get(_fold(category), {})
        return cat.get(fam, self.weights.get("", {}).get(fam, 1.0))


@lru_cache(maxsize=4)
def _load_table(path: str, mtime: float) -> FamilyTable:
    with open(path, encoding="utf-8") as f:
        return FamilyTable([r for r in csv.DictReader(f) if r.get("aile")])


def family_table() -> FamilyTable:
    p = Path(os.getenv("RENK_DIR", str(DATA_DIR))) / "renk_aileleri.csv"
    if not p.exists():
        return FamilyTable([{"aile": "diger", "etiket": "Diğer", "agirlik": "1"}])
    return _load_table(str(p), p.stat().st_mtime)


class ErpShares:
    """Geçmiş satışlardan renk ailesi payları. Sütunlar: kategori, renk, adet, (bolge)."""

    def __init__(self, path: Optional[str], table: FamilyTable):
        self.path = path
        self.units: Dict[Tuple[str, str], Dict[str, float]] = {}    # (kategori, bölge) -> aile -> adet
        if not path or not Path(path).exists():
            return
        with open(path, encoding="utf-8-sig") as f:
            sample = f.read(2048)
            f.seek(0)
            delim = ";" if sample.count(";") > sample.count(",") else ","
            for r in csv.DictReader(f, delimiter=delim):
                r = {_fold(k): v for k, v in r.items() if k}
                try:
                    n = float(str(r.get("adet") or r.get("satis adedi") or 0).replace(",", "."))
                except ValueError:
                    continue
                fam = table.family(r.get("renk") or r.get("renk aciklamasi") or "")
                for cat in (_fold(r.get("kategori") or ""), "*"):
                    for reg in (str(r.get("bolge") or "").upper().strip(), "*"):
                        d = self.units.setdefault((cat, reg or "*"), {})
                        d[fam] = d.get(fam, 0) + n

    @property
    def available(self) -> bool:
        return bool(self.units)

    def shares(self, category: str, region: str = "*") -> Optional[Dict[str, float]]:
        min_units = float(os.getenv("RENK_ERP_MIN_ADET", ERP_MIN_UNITS))
        for key in ((_fold(category), region), (_fold(category), "*"), ("*", region), ("*", "*")):
            d = self.units.get(key)
            if d and sum(d.values()) >= min_units:
                tot = sum(d.values())
                return {k: v / tot for k, v in d.items()}
        return None


def erp_source() -> ErpShares:
    return ErpShares(os.getenv("RENK_ERP_DOSYASI"), family_table())


def item_colors(it) -> List[Tuple[str, str]]:
    """(renk, renk kodu) listesi. Renk adı yoksa renk kodu kullanılır."""
    codes = [c.strip() for c in (it.attributes.get("Renk kodu") or "").split(",") if c.strip()]
    if it.colors:
        return [(c, codes[i] if len(codes) == len(it.colors) else "") for i, c in enumerate(it.colors)]
    return [(c, c) for c in codes]


def color_weights(it, regions: List[str], table: FamilyTable, erp: ErpShares
                  ) -> Tuple[List[Tuple[str, str, str]], Dict[str, Dict[str, float]], str]:
    """Bir modelin renkleri ve bölge bazında payları. Dönüş: [(renk, kod, aile)], bölge -> renk -> pay (0-1), dayanak."""
    cols = item_colors(it)
    fams = [(c, code, table.family(c)) for c, code in cols]
    out: Dict[str, Dict[str, float]] = {}
    basis = "kural varsayımı"
    for reg in regions or ["*"]:
        sh = erp.shares(it.category, reg) if erp.available else None
        if sh is not None:
            basis = "ERP"
            floor = min(sh.values()) / 2 if sh else 0.01        # ERP'de hiç satmamış aile: en küçük payın yarısı
            w = [sh.get(f, floor) for _, _, f in fams]
        else:
            w = [table.weight(f, it.category) for _, _, f in fams]
        tot = sum(w) or 1
        out[reg] = {c: x / tot for (c, _, _), x in zip(fams, w)}
    return fams, out, basis


def mix_strength(fams, shares: Dict[str, Dict[str, float]], table: FamilyTable, erp: ErpShares, category: str) -> Optional[float]:
    """Renk karışımının gücü: payla ağırlıklı ortalama renk ağırlığı / bütün ailelerin ortalama ağırlığı."""
    if not fams:
        return None
    sh = erp.shares(category) if erp.available else None
    base = sh if sh is not None else {f: table.weight(f, category) for f in table.labels}
    mean = sum(base.values()) / max(1, len(base))
    if not mean:
        return None
    first = next(iter(shares.values()))
    floor = min(base.values()) / 2 if base else 1
    return sum(first[c] * base.get(f, floor) for c, _, f in fams) / mean


def split_qty(qty_by_region: Dict[str, int], shares: Dict[str, Dict[str, float]], keep: List[str]) -> Dict[str, Dict[str, int]]:
    """Bölge adedini tutulan renklere paylarına göre böler (en büyük kalan yöntemi; toplam korunur)."""
    out: Dict[str, Dict[str, int]] = {c: {} for c in keep}
    for reg, q in qty_by_region.items():
        sh = shares.get(reg) or next(iter(shares.values()))
        tot = sum(sh[c] for c in keep) or 1
        raw = {c: q * sh[c] / tot for c in keep}
        base = {c: int(v) for c, v in raw.items()}
        rest = q - sum(base.values())
        for c in sorted(keep, key=lambda c: -(raw[c] - base[c]))[:rest]:
            base[c] += 1
        for c in keep:
            if base[c]:
                out[c][reg] = base[c]
    return out
