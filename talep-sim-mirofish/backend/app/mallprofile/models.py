"""AVM kataloğu ve AVM profili veri modelleri."""
from datetime import date
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

Basis = Literal["dış veri", "kural varsayımı", "kullanıcı girdisi", "bilinmiyor"]
Tier = Literal["budget", "mass", "upper_mass", "premium", "luxury"]


class CatalogSource(BaseModel):
    dataset: str = Field(..., examples=["Overture Maps Places"])
    release: str = Field("", examples=["2026-10-21.0"])
    license: str = Field("", examples=["CDLA-Permissive-2.0 / Apache-2.0 / CC0-1.0"])
    url: str = ""
    retrieved_at: date


class Tenant(BaseModel):
    name: str
    brand: Optional[str] = None
    wikidata: Optional[str] = None
    category: Optional[str] = None
    distance_m: Optional[int] = None


class Mall(BaseModel):
    id: str
    name: str
    aliases: List[str] = []
    lat: float
    lon: float
    confidence: Optional[float] = Field(None, description="Kaynağın kayıt güveni (0-1)")
    radius_m: int = Field(200, description="Kiracı sayılan yarıçap (kural varsayımı)")
    apparel_count: int = Field(0, description="Yarıçap içindeki giyim/ayakkabı/aksesuar mağazası sayısı")
    tenants: List[Tenant] = []
    dense_area: bool = Field(False, description="Çevrede çok mağaza var; liste AVM dışını da içerebilir")
    visitors_yearly: Optional[float] = Field(None, description="Yalnızca kaynaklı beyan; yoksa boş")
    visitors_source: Optional[str] = None
    visitors_date: Optional[date] = None


class MallCatalog(BaseModel):
    schema_version: int = 1
    ulke: str
    sehir: str
    bbox: List[float] = Field(..., min_length=4, max_length=4, description="xmin, ymin, xmax, ymax")
    source: CatalogSource
    verified: bool = False
    approved_by: Optional[str] = None
    approved_at: Optional[date] = None
    malls: List[Mall]


class Signal(BaseModel):
    key: str
    label: str
    value: Optional[str] = None
    basis: Basis
    note: str = ""


class SegmentShift(BaseModel):
    id: str
    label: str
    income_band: str
    base_weight: float
    mall_weight: float
    multiplier: float


class MallProfile(BaseModel):
    mall_id: Optional[str]
    name: str
    ulke: str
    sehir: str
    region: Optional[str]
    source: Optional[CatalogSource] = None
    verified: bool = False
    manual: bool = False
    tenant_count: int
    known_brands: List[Dict[str, str]] = Field(default_factory=list, description="[{name, tier}]")
    unknown_brands: List[str] = []
    tier_counts: Dict[str, int] = {}
    price_index: Optional[float] = Field(None, description="0 ekonomik … 1 lüks; bilinen markaların ortalaması")
    city_price_index: Optional[float] = None
    price_segment: Optional[str] = None
    rivals: List[str] = []
    signals: List[Signal]
    segments: List[SegmentShift] = []
    warnings: List[str] = []
