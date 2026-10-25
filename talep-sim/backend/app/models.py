"""API sözleşmesi (teknik doküman §4). Dokümandaki modellere ek olarak
dashboard'un Van Westendorp grafiğini çizebilmesi için fiyat eğrisi alanları var."""
from decimal import Decimal
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

Region = Literal["EU", "MENA", "CIS", "US", "TR"]


PriceTier = Literal["budget", "mass", "upper_mass", "premium", "luxury"]
ALL_REGIONS = ("EU", "MENA", "CIS", "US", "TR")


class BrandProfile(BaseModel):
    """Markanın fiyat ve konumlandırma profili. LLM üretir, kullanıcı düzenleyebilir."""
    name: str
    positioning: str = Field("", description="Markanın konumlandırması, kısa metin")
    price_tier: PriceTier = "mass"
    price_multiple: float = Field(2.7, ge=1.2, le=30, description="Tipik perakende fiyatı / birim üretim maliyeti")
    price_sensitivity: float = Field(0.5, ge=0, le=1, description="Müşterinin fiyata duyarlılığı (1 = çok duyarlı)")
    brand_pull: int = Field(50, ge=0, le=100, description="Marka çekim gücü / bilinirlik")
    typical_customer: str = ""
    margin_norm_pct: float = Field(55, ge=10, le=95, description="Markanın tipik brüt kâr marjı (%)")
    regional_strength: Dict[str, int] = Field(default_factory=lambda: {r: 50 for r in ALL_REGIONS})
    known_brand: bool = False
    confidence: Literal["low", "medium", "high"] = "low"
    source: Literal["llm_knowledge", "user_notes", "generic_default"] = "generic_default"
    edited: bool = Field(False, description="Kullanıcı üretilen profili elle düzenledi")
    warning: Optional[str] = None


class BrandProfileRequest(BaseModel):
    brand: str = Field(..., min_length=1, examples=["Ipekyol"])
    notes: Optional[str] = Field(None, description="Marka hakkında kullanıcı notları (profile öncelik verilir)")


class Explanation(BaseModel):
    key: Literal["demand", "price", "margin", "quantity"]
    label: str
    value: str
    how: str = Field(..., description="Değerin nasıl türetildiği, sade Türkçe")
    assumptions: List[str] = []


class Recommendation(BaseModel):
    category: Literal["fiyat", "bölge", "tasarım", "üretim", "marka"]
    title: str
    detail: str
    based_on: str = ""
    source: Literal["model", "kural"] = "kural"


class Assumptions(BaseModel):
    """Kullanıcının düzenleyebildiği varsayımlar; boş bırakılanlar varsayılanla çalışır."""
    channel: Literal["online", "store"] = Field("online", description="Satış kanalı; iade oranını etkiler")
    return_base_pct: Dict[str, float] = Field(default_factory=dict, description="Bölge bazında taban iade oranı (%) ezmesi, ör. gerçek verin varsa")
    restock_share: float = Field(0.7, ge=0, le=1, description="İade edilenlerin yeniden satılabilir oranı")
    reverse_logistics_pct: float = Field(8.0, ge=0, le=50, description="İade lojistiği + işleme maliyeti, satış fiyatının %'si")
    audience: Dict[str, int] = Field(default_factory=dict, description="Bölge bazında 120 günde ulaşılabilir hedef kitle (kişi) ezmesi")
    launch_month: Optional[int] = Field(None, ge=1, le=12, description="Lansman ayı; mevsim uyumu hesabına girer, boşsa mevsim etkisi uygulanmaz")
    competitor_price_usd: Dict[str, float] = Field(default_factory=dict, description="Bölge bazında rakip ürün fiyatı ($); girilirse rakip savunma senaryosu bunu kullanır")
    conversion_ceiling_pct: float = Field(2.0, ge=0.1, le=30, description="İlgili ve fiyatı kabul eden kitlenin alıma dönüşme tavanı (%)")


# --- Girdi (Request) Modeli ---
class PredictionRequest(BaseModel):
    product_name: str = Field(..., examples=["Kışlık Oversize Yün Kaban"])
    image_base64: str = Field(..., description="Yüklenen görselin base64 formatı")
    technical_specs: str = Field(..., examples=["GSM: 450g, %80 Yün %20 Polyamid, Su itici astar."])
    unit_cost: Decimal = Field(..., gt=0, examples=[25.50])
    total_production_budget: int = Field(..., gt=0, examples=[100000])
    target_regions: List[Region] = Field(..., min_length=1, examples=[["EU", "MENA", "CIS"]])
    brand: Optional[str] = Field(None, examples=["Ipekyol"], description="Marka adı; fiyat politikası markaya göre belirlenir")
    brand_notes: Optional[str] = Field(None, description="Marka profili üretilirken kullanılacak kullanıcı notları")
    brand_profile: Optional[BrandProfile] = Field(None, description="Hazır/düzenlenmiş profil; verilirse yeniden üretilmez")
    assumptions: Assumptions = Field(default_factory=Assumptions)
    usd_try_rate: Optional[float] = Field(None, gt=0, description="1 USD kaç TL (Türkiye için TL gösterimi); boşsa varsayılan kur")
    allocation_objective: Literal["balanced", "profit", "blended"] = Field(
        "balanced", description="Üretim dağıtım hedefi: balanced = satış hızı/dengeli stok, profit = kâr ağırlıklı, blended = karışık")
    reset_world: bool = Field(False, description="Seçili bölgelerin önbellekteki MiroFish dünyasını (ve Zep grafiğini) silip baştan kurar")

    @field_validator("target_regions")
    @classmethod
    def dedupe_regions(cls, v: List[str]) -> List[str]:
        return list(dict.fromkeys(v))


# --- Van Westendorp eğrileri (dashboard grafiği için) ---
class PricePoint(BaseModel):
    price: Decimal
    too_cheap: float = Field(..., description="Bu fiyatı 'şüphe uyandıracak kadar ucuz' bulan ajan oranı")
    cheap: float = Field(..., description="'Uygun / ucuz' bulan oran")
    expensive: float = Field(..., description="'Pahalı ama düşünülebilir' bulan oran")
    too_expensive: float = Field(..., description="'Asla almam, çok pahalı' bulan oran")


class PriceZone(BaseModel):
    key: str = Field(..., description="too_cheap | cheap | ideal | expensive | too_expensive")
    label: str
    low: Decimal
    high: Optional[Decimal] = Field(None, description="Üst sınır; en üst bölgede None (sınırsız)")
    description: str = ""


class PriceStep(BaseModel):
    """Bir fiyat basamağında ajanların karar dağılımı (adet)."""
    price: Decimal
    suspicious: int = Field(0, description="Çok ucuz, kalite şüphesi")
    fair: int = Field(0, description="Uygun / alırım")
    expensive: int = Field(0, description="Pahalı ama düşünürüm")
    too_expensive: int = Field(0, description="Çok pahalı, almam")
    n: int = 0
    basis: str = Field("threshold", description="ladder = ajanın o fiyata verdiği karar; threshold = ajan eşiklerinden hesaplandı")


class VanWestendorpResult(BaseModel):
    optimal_price_point: Decimal = Field(..., description="OPP: too_cheap ∩ too_expensive")
    indifference_price_point: Decimal = Field(..., description="IPP: cheap ∩ expensive")
    acceptable_range_low: Decimal = Field(..., description="PMC: too_cheap ∩ expensive")
    acceptable_range_high: Decimal = Field(..., description="PME: cheap ∩ too_expensive")
    curve: List[PricePoint]
    zones: List[PriceZone] = []
    quality: str = Field("high", description="low | medium | high: ajan sayısına göre güvenilirlik")
    quality_note: str = ""


class RawAnswer(BaseModel):
    agent: int
    status: str = Field(..., description="json | extracted | failed | empty")
    text: str = Field("", description="Ajanın ham cevabı (kısaltılmış)")
    interest: Optional[float] = None


class ReturnDriver(BaseModel):
    label: str
    points: float = Field(..., description="İade oranına etkisi, yüzde puanı (+ artırır, - azaltır)")
    detail: str
    basis: str = Field("kural varsayımı", description="kural varsayımı | kullanıcı verisi | ajan cevabı")


class ReturnEstimate(BaseModel):
    rate_pct: float
    low_pct: float
    high_pct: float
    base_pct: float
    drivers: List[ReturnDriver] = []
    gross_margin_pct: float
    net_margin_pct: float = Field(..., description="İade maliyeti ve iade edilen adetler düşüldükten sonra marj")
    return_cost_per_sale: Decimal = Field(..., description="Satış başına beklenen iade maliyeti ($)")
    net_qty_if_sold_out: int = Field(..., description="Önerilen üretimin tamamı satılırsa iade sonrası elde kalan satış adedi")
    basis: str = "kural tabanlı varsayım (ajan cevabı değil)"


class ForecastMilestone(BaseModel):
    day: int
    units_low: int
    units: int
    units_high: int
    period_units: int = Field(..., description="Bu dönemde (önceki kilometre taşından beri) satılan, orta senaryo")
    revenue: Decimal = Field(..., description="Kümülatif brüt ciro, orta senaryo ($)")
    net_revenue: Decimal = Field(..., description="İade sonrası kümülatif ciro, orta senaryo ($)")
    stock_left: int


class ForecastPoint(BaseModel):
    day: int
    demand: int = Field(..., description="Kümülatif talep (stok sınırı yokmuş gibi), orta")
    sold: int = Field(..., description="Kümülatif satış (stokla sınırlı), orta")
    sold_low: int
    sold_high: int


class SalesForecast(BaseModel):
    milestones: List[ForecastMilestone]
    curve: List[ForecastPoint]
    stockout_day: Optional[int] = Field(None, description="Orta senaryoda stoğun bittiği gün; bitmezse None")
    leftover_units: int = Field(..., description="120. günde kalan stok, orta senaryo")
    lost_units: int = Field(..., description="Stok yetmediği için kaçan talep, orta senaryo")
    sell_through_pct: float
    audience: int
    purchase_prob_pct: float
    assumptions: List[str] = []
    basis: str = "varsayım tabanlı model (ajan cevabı: talep skoru ve fiyat kabulü; kitle ve dönüşüm: varsayım)"


class PricePhase(BaseModel):
    name: str
    day_from: int
    day_to: int
    price: Decimal
    discount_pct: float = Field(..., description="Lansman fiyatına göre indirim %")
    zone: str = Field("", description="Fiyatın düştüğü bölge etiketi")
    purchase_prob_pct: float = Field(..., description="Ajan eğrisinden bu fiyatta satın alma olasılığı")
    units: int
    revenue: Decimal
    net_profit: Decimal = Field(..., description="İade maliyeti düşüldükten sonra kâr ($)")
    net_margin_pct: float
    note: str = ""


class PricePlan(BaseModel):
    phases: List[PricePhase]
    total_units: int
    total_revenue: Decimal
    total_net_profit: Decimal
    leftover_units: int
    flat_units: int = Field(..., description="Aynı dönemde tek fiyatla (lansman fiyatı) satış")
    flat_revenue: Decimal
    flat_net_profit: Decimal
    flat_leftover_units: int
    verdict: str = Field("", description="Üç aşamalı plan ile tek fiyatın karşılaştırmalı yorumu")
    assumptions: List[str] = []
    basis: str = "fiyat kabulü ajan eğrisinden; aşama süreleri ve satış hızı varsayım"


class CampaignLever(BaseModel):
    label: str
    uplift_low_pct: float
    uplift_high_pct: float
    cost_pct: float = Field(0.0, description="Ciroya oranla maliyet %")
    basis: str = "kural varsayımı"


class CampaignScenario(BaseModel):
    goal: Literal["clear_stock", "boost_sales", "defend_competition"]
    goal_label: str
    name: str
    recommended: bool = False
    why: str = ""
    start_day: int
    window_days: int
    discount_pct: float
    campaign_price: Decimal
    levers: List[CampaignLever]
    baseline_units: int
    units_low: int
    units: int
    units_high: int
    extra_units: int
    extra_revenue: Decimal
    profit_delta: Decimal
    margin_impact_pts: float
    timing: str = ""
    rationale: str = ""
    assumptions: List[str] = []
    basis: str = "fiyat etkisi ajan eğrisinden; kampanya kaldıraçları kural varsayımı"


class SensitivityRow(BaseModel):
    kind: Literal["price", "cost"]
    label: str
    price: Decimal
    unit_cost: Decimal
    units: int
    net_profit: Decimal
    vs_base_pct: float


class BreakEven(BaseModel):
    units: int = Field(..., description="Üretim maliyetini çıkaran satış adedi (iade sonrası)")
    pct_of_production: float
    day: Optional[int] = Field(None, description="Orta senaryoda bu adede ulaşılan gün; 120 günde ulaşılmazsa None")
    note: str = ""


class Confidence(BaseModel):
    level: Literal["düşük", "orta", "yüksek"]
    reasons: List[str]


class SizeShare(BaseModel):
    size: str
    share_pct: float


class Seasonality(BaseModel):
    launch_month: int
    factor: float
    note: str
    basis: str = "kural varsayımı"


# --- Çıktı (Response) Modeli ---
class AllocationView(BaseModel):
    """Bölgenin üretim kararı: eski (kâr ağırlıklı) ve yeni (seçilen hedef) dağıtımın yan yana karşılaştırması."""
    objective: str
    demand_units: int = Field(..., description="120 günde beklenen brüt satış adedi (stok sınırsızken)")
    net_demand_units: int = Field(..., description="İade sonrası kalıcı satış (iade x yeniden satılamayanlar düşülmüş)")
    units_before: int
    units: int
    sold_before: int
    sold: int
    leftover_before: int
    leftover: int
    unmet_before: int
    unmet: int
    sell_through_before_pct: float
    sell_through_pct: float
    why: str


class RegionPredictionResult(BaseModel):
    region: str
    demand_score_100: int = Field(..., ge=0, le=100, description="0-100 arası talep skoru")
    optimal_sale_price: Decimal = Field(..., description="Simülasyonun bulduğu en kârlı fiyat")
    recommended_production_qty: int = Field(..., description="Dağıtılan üretim adedi")
    allocated_budget: Decimal = Field(..., description="Bölgeye ayrılan üretim bütçesi")
    estimated_margin_percentage: float = Field(..., description="Brüt kâr marjı yüzdesi")
    key_objections: List[str] = Field(..., description="Ajanlardan gelen top 3 eleştiri")
    van_westendorp: VanWestendorpResult
    explanations: List[Explanation] = []
    allocation: Optional[AllocationView] = None
    price_steps: List[PriceStep] = []
    returns: Optional[ReturnEstimate] = None
    forecast: Optional[SalesForecast] = None
    price_plan: Optional[PricePlan] = None
    campaigns: List[CampaignScenario] = []
    sensitivity: List[SensitivityRow] = []
    break_even: Optional[BreakEven] = None
    confidence: Optional[Confidence] = None
    size_curve: List[SizeShare] = []
    seasonality: Optional[Seasonality] = None
    raw_answers: List[RawAnswer] = Field([], description="Ajanların ham cevapları ve nasıl çözümlendikleri (MiroFish motoru)")
    local_currency: Optional[str] = Field(None, description="Bölgenin yerel para birimi (yalnızca TL gösterilen bölgelerde)")
    local_price: Optional[Decimal] = Field(None, description="Önerilen fiyatın yerel para karşılığı")
    fx_rate: Optional[float] = Field(None, description="Kullanılan kur: 1 USD = fx_rate yerel para")


class FailedRegion(BaseModel):
    region: str
    reason: str = Field(..., description="Bölgenin neden hesaplanamadığı (ör. model zaman aşımı)")
    raw_answers: List[RawAnswer] = []


class PredictionResponse(BaseModel):
    session_id: str
    status: str = "COMPLETED"
    total_produced_qty: int
    unallocated_budget: Decimal = Field(..., description="Harcanmayan bütçe (yuvarlama ya da talep bütçeden azsa üretmemek için)")
    allocation_objective: str = "balanced"
    allocation_note: str = ""
    product_card: dict = Field(..., description="Vision+Text füzyonundan çıkan ürün kartı")
    engine: str = "mock"
    brand_profile: Optional[BrandProfile] = None
    recommendations: List[Recommendation] = []
    methodology_notes: List[str] = []
    disclaimer: str = "Bu çıktılar model tabanlı tahmindir, ölçülmüş satış verisi değildir. Her bölüm dayanağını (ajan cevabı, kural varsayımı, kullanıcı girdisi) belirtir; varsayımları kendi verinle değiştir."
    regional_breakdown: List[RegionPredictionResult]
    failed_regions: List[FailedRegion] = []
