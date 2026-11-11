"""Perakende takvimi veri dosyaları: kodda sabit tarih, oran ya da kampanya yoktur.

Klasör (TAKVIM_DIR, boşsa backend/panel_data/takvim):
- perakende_takvimi.csv  : etkinlik penceresi (yıl x bölge/ülke). Hicri takvimli bayramlar elle girilir.
- etkinlik_turleri.csv   : etkinlik türü başına ajan sorusu ve kural varsayımı aralıkları (indirimsiz etki,
                           indirim yapılırsa ek etki, bekleme/erteleme oranları).
- ulke_bolge.csv         : ülke kodu (ISO2) -> bizim bölgemiz (TR/EU/MENA/CIS/US).
- kampanya_kaldiraclari.csv : bölge x hedef kampanya kaldıraçları (eski scenarios.CATALOG).

Her satırda kaynak ve doğrulandı alanı vardır; doğrulanmamış satırlar sonuçta uyarıyla gösterilir.
"""
import csv
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "panel_data" / "takvim"
CORE = ("TR", "EU", "MENA", "CIS", "US")
YES = {"evet", "e", "yes", "true", "1", "x"}


class TakvimError(ValueError):
    pass


@dataclass(frozen=True)
class EventType:
    key: str
    label: str
    question: str
    lift_low_pct: float
    lift_high_pct: float
    promo_low_pct: float      # etkinlikte indirim yapılırsa ek etki (indirim görünürlüğü, fırsat arayanlar)
    promo_high_pct: float
    use_lead: bool
    ask_wait: bool
    defer_share: float        # bekleyeceğini söyleyenlerin gerçekten erteleme oranı (kural varsayımı)
    return_share: float       # etkinlikte indirim yoksa erteleyenlerin sonra tam fiyata dönme oranı (kural varsayımı)
    source: str
    verified: bool


@dataclass(frozen=True)
class Event:
    code: str
    name: str
    year: int
    scope: str                # dosyadaki bölge ya da ülke kodu
    region: str               # bizim bölgemiz
    start: date
    end: date
    lead_days: int
    kind: str
    segments: Tuple[str, ...]
    mechanic: str
    legal_note: str
    date_rule: str
    source: str
    verified: bool

    @property
    def country_only(self) -> bool:
        return self.scope != self.region


@dataclass
class Takvim:
    events: List[Event]
    types: Dict[str, EventType]
    folder: str
    problems: List[str] = field(default_factory=list)

    def window(self, region: str, start: date, days: int, verified_only: bool = False) -> List[Event]:
        """[start, start+days) ile kesişen etkinlikler (ön pencere dahil), tarihe göre."""
        end = start + timedelta(days=days)
        out = []
        for e in self.events:
            if e.region != region or (verified_only and not e.verified):
                continue
            lead = e.lead_days if self.types[e.kind].use_lead else 0
            if e.end >= start and e.start - timedelta(days=lead) < end:
                out.append(e)
        return sorted(out, key=lambda e: (e.start, e.code))


def _read(path: Path) -> List[dict]:
    if not path.exists():
        raise TakvimError(f"Takvim dosyası yok: {path}")
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [{(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]


def _f(v: str, default: float = 0.0) -> float:
    try:
        return float(v.replace(",", ".")) if v else default
    except ValueError:
        return default


def load_types(folder: Path) -> Dict[str, EventType]:
    out = {}
    for r in _read(folder / "etkinlik_turleri.csv"):
        lo, hi = _f(r.get("etki_alt_pct")), _f(r.get("etki_ust_pct"))
        out[r["tur"]] = EventType(
            key=r["tur"], label=r.get("ad") or r["tur"], question=r.get("soru") or "{etkinlik} döneminde bu ürünü alır mısın?",
            lift_low_pct=min(lo, hi), lift_high_pct=max(lo, hi),
            promo_low_pct=min(_f(r.get("indirim_ek_alt_pct")), _f(r.get("indirim_ek_ust_pct"))),
            promo_high_pct=max(_f(r.get("indirim_ek_alt_pct")), _f(r.get("indirim_ek_ust_pct"))), use_lead=r.get("on_pencere_kullan", "").lower() in YES,
            ask_wait=r.get("bekleme_sorulur", "").lower() in YES, defer_share=max(0.0, min(1.0, _f(r.get("erteleme_orani")))),
            return_share=max(0.0, min(1.0, _f(r.get("katilmazsa_geri_donus")))), source=r.get("kaynak", ""),
            verified=r.get("dogrulandi", "").lower() in YES)
    return out


def load_country_map(folder: Path) -> Dict[str, str]:
    p = folder / "ulke_bolge.csv"
    return {r["ulke"].upper(): r["bolge"].upper() for r in _read(p)} if p.exists() else {}


def _parse_date(v: str, what: str) -> date:
    try:
        return date.fromisoformat(v)
    except ValueError as e:
        raise TakvimError(f"{what}: tarih YYYY-AA-GG olmalı, '{v}' okunamadı") from e


@lru_cache(maxsize=8)
def _load_cached(folder: str, mtimes: tuple) -> Takvim:
    base = Path(folder)
    types = load_types(base)
    cmap = load_country_map(base)
    events, problems = [], []
    for i, r in enumerate(_read(base / "perakende_takvimi.csv"), start=2):
        where = f"perakende_takvimi.csv satır {i} ({r.get('etkinlik_kodu', '?')})"
        try:
            scope = r["bolge"].upper()
            region = scope if scope in CORE else cmap.get(scope)
            if not region:
                raise TakvimError(f"{where}: '{scope}' bölgesi/ülkesi ulke_bolge.csv'de yok")
            kind = r["tur"]
            if kind not in types:
                raise TakvimError(f"{where}: tür '{kind}' etkinlik_turleri.csv'de yok")
            s, e = _parse_date(r["baslangic"], where), _parse_date(r["bitis"], where)
            if e < s:
                raise TakvimError(f"{where}: bitiş başlangıçtan önce")
            events.append(Event(
                code=r["etkinlik_kodu"], name=r.get("etkinlik_adi") or r["etkinlik_kodu"], year=int(r.get("yil") or s.year),
                scope=scope, region=region, start=s, end=e, lead_days=int(_f(r.get("on_pencere_gun"))), kind=kind,
                segments=tuple(x.strip().lower() for x in (r.get("ilgili_segmentler") or "").split(";") if x.strip()),
                mechanic=r.get("pazar_mekanigi", ""), legal_note=r.get("yasal_not", ""), date_rule=r.get("tarih_kurali", ""),
                source=r.get("kaynak", ""), verified=r.get("dogrulandi", "").lower() in YES))
        except (KeyError, TakvimError, ValueError) as ex:
            problems.append(str(ex) if isinstance(ex, TakvimError) else f"{where}: eksik alan {ex}")
    return Takvim(events, types, folder, problems)


def load(folder: Optional[str] = None) -> Takvim:
    base = Path(folder) if folder else DEFAULT_DIR
    files = ("perakende_takvimi.csv", "etkinlik_turleri.csv", "ulke_bolge.csv")
    mt = tuple((base / f).stat().st_mtime if (base / f).exists() else 0 for f in files)
    return _load_cached(str(base), mt)


# --- Kampanya kaldıraçları (eski scenarios.CATALOG) ---

@lru_cache(maxsize=8)
def _catalog_cached(path: str, mtime: float) -> dict:
    out: dict = {}
    for r in _read(Path(path)):
        reg = out.setdefault(r["bolge"].upper(), {})
        goal = reg.get(r["hedef"])
        if goal is None:
            goal = reg[r["hedef"]] = [r["kampanya_adi"], _num(r["indirim_pct"]), [], r.get("zamanlama", ""), r.get("gerekce", "")]
        goal[2].append((r["kaldirac"], _num(r["artis_alt_pct"]), _num(r["artis_ust_pct"]), _num(r["maliyet_pct"])))
    return {reg: {g: tuple(v) for g, v in goals.items()} for reg, goals in out.items()}


def _num(v: str):
    x = _f(v)
    return int(x) if x == int(x) else x


def load_catalog(folder: Optional[str] = None) -> dict:
    """bölge -> hedef -> (ad, indirim %, [(kaldıraç, alt %, üst %, maliyet %)], zamanlama, gerekçe)"""
    p = (Path(folder) if folder else DEFAULT_DIR) / "kampanya_kaldiraclari.csv"
    if not p.exists():
        raise TakvimError(f"Kampanya kaldıraç dosyası yok: {p}")
    return _catalog_cached(str(p), p.stat().st_mtime)
