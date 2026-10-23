"""API sözleşmesi (teknik doküman §4). Dokümandaki modellere ek olarak
dashboard'un Van Westendorp grafiğini çizebilmesi için fiyat eğrisi alanları var."""
from decimal import Decimal
from typing import List, Literal

from pydantic import BaseModel, Field, field_validator

Region = Literal["EU", "MENA", "CIS", "US"]


# --- Girdi (Request) Modeli ---
class PredictionRequest(BaseModel):
    product_name: str = Field(..., examples=["Kışlık Oversize Yün Kaban"])
    image_base64: str = Field(..., description="Yüklenen görselin base64 formatı")
    technical_specs: str = Field(..., examples=["GSM: 450g, %80 Yün %20 Polyamid, Su itici astar."])
    unit_cost: Decimal = Field(..., gt=0, examples=[25.50])
    total_production_budget: int = Field(..., gt=0, examples=[100000])
    target_regions: List[Region] = Field(..., min_length=1, examples=[["EU", "MENA", "CIS"]])

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


class PredictionResponse(BaseModel):
    session_id: str
    status: str = "COMPLETED"
    total_produced_qty: int
    unallocated_budget: Decimal = Field(..., description="Aşağı yuvarlamadan artan bütçe")
    product_card: dict = Field(..., description="Vision+Text füzyonundan çıkan ürün kartı")
    regional_breakdown: List[RegionPredictionResult]
