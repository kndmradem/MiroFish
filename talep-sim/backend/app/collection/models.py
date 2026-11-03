"""Koleksiyon modu veri modelleri. Her sayının yanında dayanağı (basis) taşınır."""
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from ..models import Assumptions, BrandProfile, Region

Basis = Literal["ajan", "kural varsayımı", "LLM tahmini", "ERP", "kullanıcı girdisi"]
Role = Literal["hero", "çekirdek", "tamamlayıcı", "destek", "riskli", "belirsiz"]
DeclaredRole = Literal["hero", "çekirdek", "tamamlayıcı", "deneme"]
Currency = Literal["TRY", "USD"]


class CollectionItem(BaseModel):
    sku: str
    name: str
    category: str = ""
    subcategory: str = ""
    technical_specs: str = ""
    unit_cost: Optional[float] = Field(None, description="Koleksiyon para biriminde")
    planned_price: Optional[float] = Field(None, description="Koleksiyon para biriminde")
    images: List[str] = Field(default_factory=list, description="Koleksiyon klasöründeki dosya adları; ilki ana görsel")
    colors: List[str] = Field(default_factory=list)
    sizes: str = ""
    planned_qty: Optional[int] = None
    declared_role: Optional[DeclaredRole] = None
    outfit_group: str = ""
    launch_month: Optional[int] = Field(None, ge=1, le=12)
    moq: Optional[int] = None
    attributes: Dict[str, str] = Field(default_factory=dict)


class CollectionMeta(BaseModel):
    name: str = "Adsız koleksiyon"
    brand: Optional[str] = None
    brand_notes: str = Field("", description="Marka profili çıkarılırken kullanılan notlar")
    brand_profile: Optional[BrandProfile] = Field(None, description="Ekranda çıkarılan/düzenlenen profil; verilirse yeniden üretilmez")
    season: str = ""
    total_budget: Optional[float] = Field(None, description="Koleksiyon para biriminde toplam üretim bütçesi")
    currency: Currency = "TRY"
    target_regions: List[Region] = Field(default_factory=lambda: ["TR"])
    channel: Literal["online", "store"] = "online"
    launch_month: Optional[int] = Field(None, ge=1, le=12)
    usd_try_rate: Optional[float] = Field(None, gt=0)
    notes: str = ""


class Issue(BaseModel):
    level: Literal["hata", "uyarı", "bilgi"]
    sku: Optional[str] = None
    row: Optional[int] = None
    message: str


class ItemPreview(BaseModel):
    row: int
    item: CollectionItem
    status: Literal["ok", "uyarı", "hata", "belirsiz"]
    match_rule: str = ""
    candidates: List[str] = Field(default_factory=list, description="Belirsiz görsel için aday SKU'lar")


class OrphanImage(BaseModel):
    file: str
    suggestion: Optional[str] = Field(None, description="Yazım hatası olabilecek benzer SKU")
    candidates: List[str] = Field(default_factory=list)


class ImportPreview(BaseModel):
    collection_id: str
    meta: CollectionMeta
    items: List[ItemPreview]
    orphans: List[OrphanImage]
    issues: List[Issue]
    column_map: Dict[str, str] = Field(default_factory=dict, description="Excel başlığı -> alan")
    ignored_columns: List[str] = Field(default_factory=list)
    counts: Dict[str, int] = Field(default_factory=dict)


class Collection(BaseModel):
    id: str
    meta: CollectionMeta
    items: List[CollectionItem]
    created: float = 0
    status: Literal["taslak", "hazır", "koşuyor", "bitti", "hata"] = "taslak"


class ConfirmRequest(BaseModel):
    meta: CollectionMeta
    items: List[CollectionItem]


class BrandEffect(BaseModel):
    """Marka profilinin sonuca etkisi: hangi profil kullanıldı ve hangi hesaba nasıl girdi."""
    name: Optional[str]
    tier: str
    price_multiple: float
    neutral_multiple: float
    price_level_pct: float = Field(..., description="Marka çarpanının nötr çarpana göre fiyat merdivenini kaydırdığı oran (%)")
    brand_pull: int
    price_sensitivity: float
    regional_strength: Dict[str, int]
    demand_points: Dict[str, float] = Field(default_factory=dict, description="Bölge: marka gücünün talep endeksine kural etkisi (puan)")
    source: str
    confidence: str
    edited: bool
    basis: Basis
    lines: List[str] = Field(default_factory=list)
    warning: Optional[str] = None


class MetaUpdate(BaseModel):
    meta: CollectionMeta


class RunOptions(BaseModel):
    regions: Optional[List[Region]] = None
    only: Optional[List[str]] = Field(None, description="Yalnızca bu SKU'lar (deneme için)")
    rerun: bool = Field(False, description="Önceden hesaplanmış ürünleri de yeniden koş")
    allocation_objective: Literal["balanced", "profit", "blended"] = "balanced"
    showcase: bool = Field(True, description="Vitrin turu: panel ürünleri gruplar halinde birlikte görüp seçer (panel motoru)")
    block_size: int = Field(8, ge=3, le=15, description="Vitrinde bir grupta gösterilen en fazla ürün")


class RunStatus(BaseModel):
    collection_id: str
    running: bool
    done: int = 0
    total: int = 0
    failed: List[str] = Field(default_factory=list)
    current: Optional[str] = None
    detail: str = ""
    started: Optional[float] = None
    finished: Optional[float] = None
    error: Optional[str] = None
    log: List[str] = Field(default_factory=list)


class WhatIf(BaseModel):
    exclude: List[str] = Field(default_factory=list)
    planned_prices: Dict[str, float] = Field(default_factory=dict, description="SKU -> yeni planlanan fiyat (koleksiyon para birimi)")
    total_budget: Optional[float] = None
    allocation_objective: Optional[Literal["balanced", "profit", "blended"]] = None


# ---------- Sonuç ----------

class Metric(BaseModel):
    value: Optional[float]
    low: Optional[float] = None
    high: Optional[float] = None
    basis: Basis
    how: str = ""


class ItemRegion(BaseModel):
    region: str
    demand: int
    enthusiast_pct: Optional[float] = None
    optimal_price: float              # USD
    range_low: float                  # USD, panelin kabul edilebilir fiyat aralığı
    range_high: float
    margin_pct: float
    return_pct: float
    demand_units: int                 # 120 gün, stok sınırsız
    price_fit: Optional[Literal["altında", "içinde", "üstünde"]] = None
    objections: List[str] = Field(default_factory=list)
    confidence: str = ""


class ShowcaseItem(BaseModel):
    shown: int
    best: int
    worst: int
    score: float = Field(..., description="(en iyi - en kötü) / gösterim, -1..1")
    best_pct: float
    worst_pct: float
    rank: int
    single_rank: Optional[int] = Field(None, description="Tek tek bakıştaki sıra")
    together: int = Field(0, description="Kombin çiftlerinde seçilme sayısı")


class PairCount(BaseModel):
    a: str
    b: str
    count: int
    pct: float = Field(..., description="İkisinin birlikte gösterildiği grupların yüzde kaçında seçildi")


class PositionBias(BaseModel):
    position: str
    pick_pct: float
    expected_pct: float


class ShowcaseSummary(BaseModel):
    n_answers: int
    n_failed: int
    n_persons: int
    block_size: int
    by_region: Dict[str, int] = Field(default_factory=dict)
    together_pairs: List[PairCount] = Field(default_factory=list)
    substitute_pairs: List[PairCount] = Field(default_factory=list)
    position: List[PositionBias] = Field(default_factory=list)
    position_warning: Optional[str] = None
    mean_n_buy: Optional[float] = None
    comments: List[str] = Field(default_factory=list)
    agreement_pct: Optional[float] = Field(None, description="Tek tek ve vitrin sıralamasının uyumu (sıra korelasyonu x100)")


class ItemResult(BaseModel):
    sku: str
    name: str
    category: str
    image: Optional[str] = None
    unit_cost_usd: Optional[float]
    planned_price_usd: Optional[float]
    declared_role: Optional[str]
    regions: List[ItemRegion]
    appeal: Metric
    relative: Metric
    rank: Metric
    enthusiast_pct: Metric
    role: Role
    role_why: str
    recommended_qty: Metric
    qty_by_region: Dict[str, int] = Field(default_factory=dict)
    planned_qty: Optional[int] = None
    flags: List[str] = Field(default_factory=list)
    failed_regions: List[str] = Field(default_factory=list)
    showcase: Optional[ShowcaseItem] = None


class ReachPoint(BaseModel):
    k: int
    sku: str
    name: str
    reach_pct: float
    added_pct: float


class CannibalPair(BaseModel):
    a: str
    b: str
    category: str
    overlap_pct: float
    why: str


class CategorySummary(BaseModel):
    category: str
    count: int
    roles: Dict[str, int]
    price_min: Optional[float]
    price_max: Optional[float]
    mean_appeal: float
    in_zone: int
    out_zone: int


class Action(BaseModel):
    kind: Literal["çıkar", "fiyat", "kanibalizasyon", "derinlik", "eksik", "veri", "kombin", "vitrin"]
    text: str
    skus: List[str] = Field(default_factory=list)
    basis: Basis


class CollectionSummary(BaseModel):
    n_items: int
    n_evaluated: int
    n_failed: int
    reach: Metric
    reach_by_region: Dict[str, float] = Field(default_factory=dict)
    reach_curve: List[ReachPoint] = Field(default_factory=list)
    roles: Dict[str, int]
    mean_appeal: Metric
    categories: List[CategorySummary]
    cannibal_pairs: List[CannibalPair]
    budget_total_usd: Optional[float]
    budget_used_usd: float
    total_qty: int
    expected_units: Metric
    actions: List[Action]


class CollectionResult(BaseModel):
    collection_id: str
    name: str
    currency: str
    fx_rate: float
    regions: List[str]
    items: List[ItemResult]
    summary: CollectionSummary
    notes: List[str]
    data_basis: Optional[dict] = None
    panel_shared: bool = Field(False, description="Bütün ürünlere aynı kişiler mi baktı (panel motoru)")
    brand_profile: Optional[BrandProfile] = None
    brand_effect: Optional[BrandEffect] = None
    showcase: Optional[ShowcaseSummary] = None
