"""FastAPI giriş noktası: ürün talep ve fiyat simülasyonu."""
import asyncio
import os
import uuid
from decimal import Decimal

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .allocation import RegionSignal, allocate_production_budget
from .models import BrandProfile, BrandProfileRequest, PredictionRequest, PredictionResponse, RegionPredictionResult
from .advisor import Advisor
from .explain import explain_region, methodology_notes
from .pricing import analyze
from .config import Settings, settings
from .services.brand_profiler import BrandProfiler
from .services.llm import LLMClient, LLMError
from .services.mirofish_client import MiroFishError
from .services.engine import MockSimulationEngine, SimulationEngine

app = FastAPI(title="Talep Simülasyonu API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

def build_engine(cfg: Settings) -> SimulationEngine:
    """SIM_ENGINE=mirofish ise gerçek ajan sürüsü, aksi halde mock."""
    mock = MockSimulationEngine()
    if cfg.sim_engine != "mirofish":
        return mock

    from .services.mirofish_client import MiroFishClient
    from .services.mirofish_engine import MiroFishSimulationEngine
    from .services.vision import VisionFusion

    fuser = mock.fuse_product_card
    if cfg.vision_enabled:
        fuser = VisionFusion(cfg.vision_api_key, cfg.vision_base_url, cfg.vision_model).fuse_product_card
    return MiroFishSimulationEngine(
        MiroFishClient(cfg.mirofish_url), fuser, cfg.mirofish_state_file,
        max_rounds=cfg.mirofish_max_rounds, interview_timeout=cfg.mirofish_interview_timeout,
    )


_engine = build_engine(settings)
_llm = LLMClient(settings.llm_api_key, settings.llm_base_url, settings.llm_model) if settings.llm_enabled else None
_profiler = BrandProfiler(_llm)
_advisor = Advisor(_llm)


def get_engine() -> SimulationEngine:
    return _engine


def get_profiler() -> BrandProfiler:
    return _profiler


def get_advisor() -> Advisor:
    return _advisor


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "engine": settings.sim_engine, "vision": settings.vision_enabled, "llm": settings.llm_enabled}


@app.post("/api/brand-profile", response_model=BrandProfile)
async def brand_profile(req: BrandProfileRequest, profiler: BrandProfiler = Depends(get_profiler)) -> BrandProfile:
    """Marka adından fiyat/konumlandırma profili çıkarır; kullanıcı sonucu düzenleyip /api/predict'e verebilir."""
    return await profiler.profile(req.brand, req.notes)


@app.post("/api/predict", response_model=PredictionResponse)
async def predict(req: PredictionRequest, engine: SimulationEngine = Depends(get_engine),
                  profiler: BrandProfiler = Depends(get_profiler),
                  advisor: Advisor = Depends(get_advisor)) -> PredictionResponse:
    unit_cost = float(req.unit_cost)
    brand = req.brand_profile
    if brand is None and req.brand and req.brand.strip():
        brand = await profiler.profile(req.brand, req.brand_notes)
    try:
        card = await engine.fuse_product_card(req)
        # Bölge simülasyonları birbirinden bağımsız, paralel koşar.
        sims = await asyncio.gather(*(engine.simulate_region(card, r, unit_cost, brand) for r in req.target_regions))
    except (MiroFishError, LLMError, httpx.HTTPError) as e:
        raise HTTPException(status_code=502, detail=f"Simülasyon servisi hatası: {type(e).__name__}: {e}") from e

    priced = {s.region: (s, *analyze(s.price_answers, unit_cost)) for s in sims}
    allocations = allocate_production_budget(
        [RegionSignal(r, s.demand_score, best) for r, (s, _, best) in priced.items()],
        Decimal(req.total_production_budget),
        req.unit_cost,
    )

    total_weight = sum((a.weight for a in allocations.values()), Decimal(0))
    breakdown = []
    for region, (sim, vw, best) in priced.items():
        alloc = allocations[region]
        margin = float((best - req.unit_cost) / best * 100) if best > 0 else 0.0
        breakdown.append(RegionPredictionResult(
            region=region,
            demand_score_100=sim.demand_score,
            optimal_sale_price=best,
            recommended_production_qty=alloc.quantity,
            allocated_budget=alloc.budget,
            estimated_margin_percentage=round(margin, 1),
            key_objections=sim.objections,
            van_westendorp=vw,
            explanations=explain_region(sim, vw, best, unit_cost, alloc, total_weight,
                                        req.total_production_budget, brand),
        ))

    spent = sum((a.quantity * req.unit_cost for a in allocations.values()), Decimal(0))
    unallocated = Decimal(req.total_production_budget) - spent
    engine_name = sims[0].meta.get("engine", "mock")
    return PredictionResponse(
        session_id=str(uuid.uuid4()),
        total_produced_qty=sum(a.quantity for a in allocations.values()),
        unallocated_budget=unallocated,
        product_card=card,
        engine=engine_name,
        brand_profile=brand,
        recommendations=await advisor.recommend(breakdown, brand, unit_cost, req.total_production_budget, unallocated, card),
        methodology_notes=methodology_notes(engine_name, brand),
        regional_breakdown=breakdown,
    )
