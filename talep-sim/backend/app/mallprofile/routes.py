"""AVM arama ve AVM profili uçları (ağa çıkmaz; yerel katalogdan okur)."""
import os
import re
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import settings
from ..panel.erp_cases import COUNTRY_REGION
from .catalog import MallStore
from .models import MallProfile, Tenant, Tier
from .signals import build_profile, city_index
from .tiers import TierMap

router = APIRouter(prefix="/api/malls", tags=["avm"])
_PANEL_DATA = Path(__file__).resolve().parents[2] / "panel_data"
_store = MallStore(os.getenv("MALL_DATA_DIR") or None)
_tiers_cache: dict = {}


def tiers() -> TierMap:
    path = Path(os.getenv("BRAND_TIERS_FILE") or _PANEL_DATA / "marka_katmanlari.csv")
    mtime = path.stat().st_mtime if path.exists() else 0
    hit = _tiers_cache.get(path)
    if hit is None or hit[0] != mtime:
        hit = (mtime, TierMap.load(path))
        _tiers_cache[path] = hit
    return hit[1]


def _library(region: Optional[str]):
    if not region:
        return None
    from ..main import panel_store
    try:
        return panel_store(settings).personas(region)
    except Exception:  # kütüphane yoksa ya da onaysızsa panel etkisi gösterilmez, profil yine döner
        return None


class MallHit(BaseModel):
    id: str
    name: str
    aliases: List[str]
    apparel_count: int
    dense_area: bool


class ManualMall(BaseModel):
    name: str = Field(..., min_length=1, examples=["Yeni AVM"])
    tenants: List[str] = Field(default_factory=list, description="Kiracı markalar, her biri bir öğe")
    visitors_yearly: Optional[float] = Field(None, ge=0)
    visitors_source: Optional[str] = None


class ProfileRequest(BaseModel):
    ulke: str
    sehir: str
    mall_id: Optional[str] = None
    manual: Optional[ManualMall] = None
    brand_tier: Optional[Tier] = Field(None, description="Değerlendirilen markanın katmanı (rakipleri ayırmak için)")


@router.get("/cities")
async def cities() -> list:
    return _store.cities()


@router.get("/search", response_model=List[MallHit])
async def search(ulke: str, sehir: str, q: str = "", limit: int = 15) -> List[MallHit]:
    return [MallHit(id=m.id, name=m.name, aliases=m.aliases[:3], apparel_count=m.apparel_count,
                    dense_area=m.dense_area) for m in _store.search(ulke, sehir, q, min(limit, 50))]


def split_tenants(text: str) -> List[str]:
    return [t.strip() for t in re.split(r"[\n,;]+", text or "") if t.strip()]


@router.post("/profile", response_model=MallProfile)
async def profile(req: ProfileRequest) -> MallProfile:
    ulke = req.ulke.upper()
    region = COUNTRY_REGION.get(ulke)
    lib = _library(region)
    cat = _store.catalog(ulke, req.sehir)
    city_idx = city_index(cat.malls, tiers()) if cat else None
    if req.manual is not None:
        names = [n for t in req.manual.tenants for n in split_tenants(t)]
        prof = build_profile(name=req.manual.name, ulke=ulke, sehir=req.sehir, region=region,
                             tenants=[Tenant(name=n, brand=n) for n in names], tiers=tiers(), lib=lib,
                             city_idx=city_idx, manual=True, brand_tier=req.brand_tier,
                             visitors=req.manual.visitors_yearly, visitors_source=req.manual.visitors_source)
        if cat is None:
            prof.warnings = [w for w in prof.warnings if not w.startswith("Bu şehirde karşılaştırılacak")]
            prof.warnings.append("Bu şehir için AVM kataloğu yok: şehir ortalamasıyla karşılaştırılamadı, "
                                 "panel ağırlıkları değiştirilmedi.")
        return prof
    if not req.mall_id:
        raise HTTPException(status_code=400, detail="mall_id ya da manual verilmeli.")
    if cat is None:
        raise HTTPException(status_code=404, detail=f"{ulke} {req.sehir} için AVM kataloğu yok.")
    mall = _store.get(ulke, req.sehir, req.mall_id)
    if mall is None:
        raise HTTPException(status_code=404, detail="AVM katalogda bulunamadı.")
    return build_profile(name=mall.name, ulke=ulke, sehir=cat.sehir, region=region, tenants=mall.tenants,
                         tiers=tiers(), lib=lib, city_idx=city_idx, mall=mall, source=cat.source,
                         verified=cat.verified, brand_tier=req.brand_tier, visitors=mall.visitors_yearly,
                         visitors_source=mall.visitors_source)
