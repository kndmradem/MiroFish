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
    usd_try_rate: Optional[float] = Field(None, gt=0, description="1 USD kaç TL (Türkiye için TL gösterimi); boşsa varsayılan kur")

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


class VanWestendorpResult(BaseModel):
    optimal_price_point: Decimal = Field(..., description="OPP: too_cheap ∩ too_expensive")
    indifference_price_point: Decimal = Field(..., description="IPP: cheap ∩ expensive")
    acceptable_range_low: Decimal = Field(..., description="PMC: too_cheap ∩ expensive")
    acceptable_range_high: Decimal = Field(..., description="PME: cheap ∩ too_expensive")
    curve: List[PricePoint]


class RawAnswer(BaseModel):
    agent: int
    status: str = Field(..., description="json | extracted | failed | empty")
    text: str = Field("", description="Ajanın ham cevabı (kısaltılmış)")
    interest: Optional[float] = None


# --- Çıktı (Response) Modeli ---
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
    unallocated_budget: Decimal = Field(..., description="Aşağı yuvarlamadan artan bütçe")
    product_card: dict = Field(..., description="Vision+Text füzyonundan çıkan ürün kartı")
    engine: str = "mock"
    brand_profile: Optional[BrandProfile] = None
    recommendations: List[Recommendation] = []
    methodology_notes: List[str] = []
    regional_breakdown: List[RegionPredictionResult]
    failed_regions: List[FailedRegion] = []
