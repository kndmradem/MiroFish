"""Persona kütüphanesi ve bağlam paketleri: dosyadan okunan, sürümlü, müşterinin düzenleyebildiği veri.

Neden veri dosyası: dil modellerinin moda/trend ve ekonomi bilgisi eğitim tarihinde donmuştur. Tüketici
alışkanlıkları ve moda değiştikçe doğru sonucu ancak güncel veri verir. Bu yüzden personalar ve bağlam
(enflasyon, kur, sezon, trend, rakip fiyatı) promptlara koddan ya da modelin hafızasından değil, tarihli ve
kaynaklı dosyalardan girer. Her dosya `as_of` (geçerlilik tarihi), `source`, `owner` ve `verified` taşır;
eskiyen ya da doğrulanmamış veri sonuçta uyarı olarak görünür.

Klasör yapısı (PANEL_DATA_DIR, varsayılan backend/panel_data):
    active.json                       {"persona_version": "v1"}  -> backtest ile terfi eden sürüm
    personas/<sürüm>/<BÖLGE>.json     segmentler ve ağırlıkları
    context/<BÖLGE>/<YYYY-MM-DD>.json tarihli bağlam paketleri; referans tarihten önceki en yenisi seçilir
    calibration.json                  gerçek satışa göre uydurulan katsayılar (bkz. calibration.py)
"""
import hashlib
import json
import random
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, field_validator, model_validator

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "panel_data"
IncomeBand = Literal["düşük", "orta-alt", "orta", "orta-üst", "yüksek"]


class Segment(BaseModel):
    """Bir bölgedeki tüketici segmenti. Panel, segment ağırlıklarına göre örneklenir."""
    id: str
    label: str
    city: str
    weight: float = Field(..., gt=0, description="Segmentin hedef alıcı kitlesindeki payı (göreli)")
    age_range: Tuple[int, int] = (25, 45)
    female_share: float = Field(0.6, ge=0, le=1)
    income_band: IncomeBand = "orta"
    style_affinity: List[str] = []
    price_sensitivity: float = Field(0.5, ge=0, le=1, description="1 = fiyata çok duyarlı")
    trend_affinity: float = Field(0.5, ge=0, le=1, description="1 = yeni trendi ilk deneyen")
    channel_habits: List[str] = []
    climate: str = ""
    dress_norms: str = ""
    notes: str = ""

    @field_validator("age_range")
    @classmethod
    def _ordered(cls, v):
        lo, hi = v
        if not 14 <= lo <= hi <= 90:
            raise ValueError("age_range 14-90 arasında ve artan olmalı")
        return v


class _Dated(BaseModel):
    region: str
    version: str
    as_of: date
    source: str = ""
    owner: str = ""
    verified: bool = Field(False, description="Veri bir insan tarafından kaynağıyla doğrulandı mı")


class PersonaLibrary(_Dated):
    schema_version: int = 1
    review_by: Optional[date] = Field(None, description="Bu tarihten sonra segmentler gözden geçirilmeli")
    price_level: float = Field(2.7, gt=0.5, lt=10, description="Bölgede tipik perakende fiyatı / maliyet (nötr 2.7)")
    segments: List[Segment] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _unique(self):
        ids = [s.id for s in self.segments]
        if len(ids) != len(set(ids)):
            raise ValueError(f"{self.region}: segment id'leri benzersiz olmalı")
        return self


class Source(BaseModel):
    """Bir bilginin dayanağı: link ve tarih zorunlu (onaylı pakette)."""
    url: str = Field(..., pattern=r"^https?://\S+$")
    title: str = ""
    published_at: Optional[date] = None
    retrieved_at: Optional[date] = None


class Trend(BaseModel):
    note: str
    as_of: Optional[date] = None
    source: str = ""
    sources: List[Source] = []


class CompetitorPrice(BaseModel):
    item: str
    price_usd: float = Field(..., gt=0)
    as_of: Optional[date] = None
    source: str = ""
    sources: List[Source] = []


class Macro(BaseModel):
    inflation_yoy_pct: Optional[float] = None
    consumer_confidence: Optional[str] = None
    purchasing_power: Optional[str] = None
    fx_note: Optional[str] = None


class ContextPack(_Dated):
    schema_version: int = 1
    valid_days: int = Field(45, gt=0, description="Bu kadar günden eskiyse bayat sayılır")
    macro: Macro = Field(default_factory=Macro)
    season_notes: str = ""
    trends: List[Trend] = []
    competitor_prices: List[CompetitorPrice] = []
    shopping_notes: str = ""
    # Kaynak ve onay (bkz. app/contextpacks): makro/sezon alanı adı -> kaynaklar
    field_sources: Dict[str, List[Source]] = Field(default_factory=dict)
    approved_by: Optional[str] = None
    approved_at: Optional[date] = None


@dataclass(frozen=True)
class PanelMember:
    """Örneklenmiş tek bir panel üyesi (segmentten türetilmiş birey)."""
    index: int
    segment: Segment
    age: int
    female: bool
    price_sensitivity: float
    trend_affinity: float


class LibraryError(ValueError):
    pass


def _read(path: Path, model):
    try:
        return model.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as e:
        raise LibraryError(f"{path}: {e}") from e


class PanelStore:
    """Veri klasörüne erişim. Müşteri kendi klasörünü PANEL_DATA_DIR ile verir; varsayılan klasör örnektir."""

    def __init__(self, root: Optional[Path | str] = None, require_verified: bool = False):
        self.root = Path(root) if root else DEFAULT_DATA_DIR
        # Üretimde true: yerel model yalnızca insan onaylı (verified) bağlam paketlerini görür
        self.require_verified = require_verified

    # --- personalar -----------------------------------------------------
    def persona_versions(self) -> List[str]:
        d = self.root / "personas"
        return sorted(p.name for p in d.iterdir() if p.is_dir()) if d.exists() else []

    def active_version(self) -> str:
        path = self.root / "active.json"
        if path.exists():
            try:
                v = json.loads(path.read_text(encoding="utf-8")).get("persona_version")
                if v in self.persona_versions():
                    return v
            except (OSError, ValueError):
                pass
        versions = self.persona_versions()
        if not versions:
            raise LibraryError(f"{self.root}/personas altında persona sürümü yok")
        return versions[-1]

    def set_active(self, version: str, reason: str = "") -> None:
        if version not in self.persona_versions():
            raise LibraryError(f"Bilinmeyen persona sürümü: {version}")
        (self.root / "active.json").write_text(json.dumps(
            {"persona_version": version, "promoted_at": date.today().isoformat(), "reason": reason},
            ensure_ascii=False, indent=2), encoding="utf-8")

    def personas(self, region: str, version: Optional[str] = None) -> PersonaLibrary:
        version = version or self.active_version()
        path = self.root / "personas" / version / f"{region}.json"
        if not path.exists():
            raise LibraryError(f"{region} için {version} sürümünde persona dosyası yok ({path})")
        lib = _read(path, PersonaLibrary)
        if lib.region != region:
            raise LibraryError(f"{path}: dosyadaki bölge {lib.region}, beklenen {region}")
        return lib

    # --- bağlam paketleri -------------------------------------------------
    def context(self, region: str, at: Optional[date] = None) -> Optional[ContextPack]:
        """`at` tarihinde (varsayılan bugün) geçerli olan, yani as_of <= at olan en yeni paket.

        Backtest'te ürünün lansman tarihi verilir: geleceğin bilgisi geçmiş tahmine sızmaz.
        """
        d = self.root / "context" / region
        if not d.exists():
            return None
        at = at or date.today()
        packs = [_read(p, ContextPack) for p in sorted(d.glob("*.json"))]
        valid = [p for p in packs if p.as_of <= at and (p.verified or not self.require_verified)]
        return max(valid, key=lambda p: p.as_of) if valid else None


def freshness_warnings(lib: PersonaLibrary, ctx: Optional[ContextPack], today: Optional[date] = None) -> List[str]:
    """Kullanıcıya gösterilecek eskime/doğrulama uyarıları (boşsa veri taze ve doğrulanmış)."""
    today = today or date.today()
    out: List[str] = []
    if ctx is None:
        out.append(f"{lib.region}: güncel bağlam paketi yok; ajanlar ekonomi, sezon ve trend bilgisi olmadan cevap verdi.")
    else:
        age = (today - ctx.as_of).days
        if age > ctx.valid_days:
            out.append(f"{lib.region}: bağlam paketi {ctx.as_of.isoformat()} tarihli ({age} gün önce), "
                       f"geçerlilik süresi {ctx.valid_days} gün; enflasyon, kur ve trend notlarını güncelle.")
        if not ctx.verified:
            out.append(f"{lib.region}: bağlam paketi ({ctx.version}) doğrulanmamış taslak; enflasyon, kur, trend ve rakip "
                       "fiyatı alanlarını kaynağıyla doldurup verified=true yap.")
        old = [t for t in ctx.trends if t.as_of and (today - t.as_of).days > 180]
        if old:
            out.append(f"{lib.region}: {len(old)} trend notu 6 aydan eski.")
    if lib.review_by and today > lib.review_by:
        out.append(f"{lib.region}: persona seti ({lib.version}) {lib.review_by.isoformat()} tarihinde gözden geçirilmeliydi.")
    if not lib.verified:
        out.append(f"{lib.region}: persona seti ({lib.version}) doğrulanmamış taslak; segment ağırlıkları gerçek "
                   "müşteri verisiyle (ERP, CRM, pazar araştırması) güncellenmeli.")
    return out


def _seed(*parts: str) -> int:
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:12], 16)


def _allocate(weights: List[float], n: int) -> List[int]:
    """En büyük kalan yöntemiyle n kişiyi ağırlıklara dağıtır (toplam tam n)."""
    total = sum(weights)
    raw = [w / total * n for w in weights]
    counts = [int(r) for r in raw]
    for i in sorted(range(len(raw)), key=lambda i: raw[i] - counts[i], reverse=True)[: n - sum(counts)]:
        counts[i] += 1
    return counts


def sample_panel(lib: PersonaLibrary, n: int, seed: str = "", sensitivity_scale: float = 1.0,
                 trend_scale: float = 1.0) -> List[PanelMember]:
    """Segment ağırlıklarına göre n kişilik deterministik panel. Aynı seed aynı paneli verir.

    `sensitivity_scale` ve `trend_scale` kalibrasyondan gelir (gerçek satışa göre ayarlanan çarpanlar).
    """
    rng = random.Random(_seed(lib.region, lib.version, seed))
    members: List[PanelMember] = []
    for seg, k in zip(lib.segments, _allocate([s.weight for s in lib.segments], n)):
        for _ in range(k):
            clamp = lambda x: round(max(0.0, min(1.0, x)), 2)
            members.append(PanelMember(
                index=len(members) + 1, segment=seg, age=rng.randint(*seg.age_range),
                female=rng.random() < seg.female_share,
                price_sensitivity=clamp(seg.price_sensitivity * sensitivity_scale + rng.uniform(-0.08, 0.08)),
                trend_affinity=clamp(seg.trend_affinity * trend_scale + rng.uniform(-0.1, 0.1))))
    return members


def stale_after(ctx: ContextPack) -> date:
    return ctx.as_of + timedelta(days=ctx.valid_days)


def library_status(store: PanelStore, regions: List[str], today: Optional[date] = None) -> Dict[str, dict]:
    """Arayüz ve /api/panel/status için bölge bazında sürüm, tarih ve uyarılar."""
    out: Dict[str, dict] = {}
    for r in regions:
        try:
            lib = store.personas(r)
        except LibraryError as e:
            out[r] = {"error": str(e)}
            continue
        ctx = store.context(r, today)
        out[r] = {"persona_version": lib.version, "persona_as_of": lib.as_of.isoformat(),
                  "segments": len(lib.segments), "persona_verified": lib.verified,
                  "context_version": ctx.version if ctx else None,
                  "context_as_of": ctx.as_of.isoformat() if ctx else None,
                  "context_stale_after": stale_after(ctx).isoformat() if ctx else None,
                  "warnings": freshness_warnings(lib, ctx, today)}
    return out
