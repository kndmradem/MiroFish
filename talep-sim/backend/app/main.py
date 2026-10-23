"""FastAPI giriş noktası: ürün talep ve fiyat simülasyonu."""
import asyncio
import os
import uuid
from decimal import Decimal

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .allocation import RegionSignal, allocate_production_budget
from .models import PredictionRequest, PredictionResponse, RegionPredictionResult
from .pricing import analyze
from .config import Settings, settings
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


def get_engine() -> SimulationEngine:
    return _engine


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "engine": settings.sim_engine, "vision": settings.vision_enabled}


@app.post("/api/predict", response_model=PredictionResponse)
async def predict(req: PredictionRequest, engine: SimulationEngine = Depends(get_engine)) -> PredictionResponse:
    unit_cost = float(req.unit_cost)
    try:
        card = await engine.fuse_product_card(req)
        # Bölge simülasyonları birbirinden bağımsız, paralel koşar.
        sims = await asyncio.gather(*(engine.simulate_region(card, r, unit_cost) for r in req.target_regions))
    except (MiroFishError, httpx.HTTPError) as e:
        raise HTTPException(status_code=502, detail=f"Simülasyon servisi hatası: {e}") from e

    priced = {s.region: (s, *analyze(s.price_answers, unit_cost)) for s in sims}
    allocations = allocate_production_budget(
        [RegionSignal(r, s.demand_score, best) for r, (s, _, best) in priced.items()],
        Decimal(req.total_production_budget),
        req.unit_cost,
    )

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
        ))

    spent = sum((a.quantity * req.unit_cost for a in allocations.values()), Decimal(0))
    return PredictionResponse(
        session_id=str(uuid.uuid4()),
        total_produced_qty=sum(a.quantity for a in allocations.values()),
        unallocated_budget=Decimal(req.total_production_budget) - spent,
        product_card=card,
        regional_breakdown=breakdown,
    )
