"""FastAPI giriş noktası: ürün talep ve fiyat simülasyonu."""
import asyncio
import os
import uuid
from decimal import Decimal

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .allocation import RegionSignal, allocate_production_budget
from .models import PredictionRequest, PredictionResponse, RegionPredictionResult
from .pricing import analyze
from .services.engine import MockSimulationEngine, SimulationEngine

app = FastAPI(title="Talep Simülasyonu API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

_engine = MockSimulationEngine()


def get_engine() -> SimulationEngine:
    return _engine


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/api/predict", response_model=PredictionResponse)
async def predict(req: PredictionRequest, engine: SimulationEngine = Depends(get_engine)) -> PredictionResponse:
    unit_cost = float(req.unit_cost)
    card = await engine.fuse_product_card(req)

    # Bölge simülasyonları birbirinden bağımsız, paralel koşar.
    sims = await asyncio.gather(*(engine.simulate_region(card, r, unit_cost) for r in req.target_regions))

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
