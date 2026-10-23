"""FastAPI giriş noktası: ürün talep ve fiyat simülasyonu."""
import asyncio
import json
import os
import uuid
from decimal import Decimal

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .allocation import RegionSignal, allocate_production_budget
from .models import FailedRegion, BrandProfile, BrandProfileRequest, PredictionRequest, PredictionResponse, RegionPredictionResult
from .advisor import Advisor
from .explain import explain_region, methodology_notes
from . import economy
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
        batch_size=cfg.mirofish_batch_size, timeout_retries=cfg.mirofish_timeout_retries,
        max_concurrency=cfg.mirofish_concurrency, min_valid=cfg.mirofish_min_valid,
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


async def _noop(_: dict) -> None:
    return None


async def run_prediction(req: PredictionRequest, engine: SimulationEngine, profiler: BrandProfiler,
                         advisor: Advisor, emit=_noop) -> PredictionResponse:
    """Tahmin hattı. `emit` ilerleme olayları alır; bölge hataları tüm çalıştırmayı düşürmez."""
    unit_cost = float(req.unit_cost)
    fx_rate = req.usd_try_rate or settings.usd_try_rate
    fx_rates = {"TRY": fx_rate}
    brand = req.brand_profile
    try:
        if brand is None and req.brand and req.brand.strip():
            await emit({"stage": "brand", "detail": f"{req.brand} marka profili çıkarılıyor"})
            brand = await profiler.profile(req.brand, req.brand_notes)
        await emit({"stage": "card", "detail": "Görsel ve teknik metin ürün kartına çevriliyor"})
        card = await engine.fuse_product_card(req)
    except (MiroFishError, LLMError, httpx.HTTPError) as e:
        raise HTTPException(status_code=502, detail=f"Simülasyon servisi hatası: {type(e).__name__}: {e}") from e

    # Yavaş yerel modelde bölgeler sırayla koşar (motorun max_concurrency'si); mock'ta hepsi paralel.
    gate = asyncio.Semaphore(getattr(engine, "max_concurrency", len(req.target_regions)))
    total = len(req.target_regions)
    done = 0

    async def one(region: str):
        nonlocal done
        async with gate:
            await emit({"stage": "region_start", "region": region, "done": done, "total": total,
                        "detail": f"{region} bölgesi değerlendiriliyor"})
            try:
                sim = await engine.simulate_region(card, region, unit_cost, brand, fx_rates, progress=emit)
            except (MiroFishError, LLMError, httpx.HTTPError) as e:
                done += 1
                reason = f"{type(e).__name__}: {e}"
                await emit({"stage": "region_failed", "region": region, "done": done, "total": total, "detail": reason})
                return FailedRegion(region=region, reason=reason)
            done += 1
            await emit({"stage": "region_done", "region": region, "done": done, "total": total,
                        "detail": f"{region} tamamlandı"})
            return sim

    outcomes = await asyncio.gather(*(one(r) for r in req.target_regions))
    sims = [o for o in outcomes if not isinstance(o, FailedRegion)]
    failed = [o for o in outcomes if isinstance(o, FailedRegion)]
    if not sims:
        detail = "; ".join(f"{f.region}: {f.reason}" for f in failed)
        raise HTTPException(status_code=502, detail=f"Hiçbir bölge hesaplanamadı. {detail}")
    await emit({"stage": "finalize", "detail": "Fiyat analizi, bütçe dağıtımı ve öneriler hazırlanıyor"})

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
        currency = economy.currency_of(region)
        local = {"local_currency": currency, "local_price": economy.local_price(best, fx_rate),
                 "fx_rate": fx_rate} if currency == "TRY" else {}
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
                                        req.total_production_budget, brand, fx_rate),
            **local,
        ))

    spent = sum((a.quantity * req.unit_cost for a in allocations.values()), Decimal(0))
    unallocated = Decimal(req.total_production_budget) - spent
    engine_name = sims[0].meta.get("engine", "mock")
    notes = methodology_notes(engine_name, brand)
    if failed:
        notes.append("Hesaplanamayan bölgeler (" + ", ".join(f.region for f in failed) +
                     ") dağıtıma katılmadı; bütçe yalnızca hesaplanan bölgeler arasında paylaştırıldı.")
    return PredictionResponse(
        session_id=str(uuid.uuid4()),
        total_produced_qty=sum(a.quantity for a in allocations.values()),
        unallocated_budget=unallocated,
        product_card=card,
        engine=engine_name,
        brand_profile=brand,
        recommendations=await advisor.recommend(breakdown, brand, unit_cost, req.total_production_budget, unallocated, card),
        methodology_notes=notes,
        regional_breakdown=breakdown,
        failed_regions=failed,
    )


@app.post("/api/predict", response_model=PredictionResponse)
async def predict(req: PredictionRequest, engine: SimulationEngine = Depends(get_engine),
                  profiler: BrandProfiler = Depends(get_profiler),
                  advisor: Advisor = Depends(get_advisor)) -> PredictionResponse:
    return await run_prediction(req, engine, profiler, advisor)


@app.post("/api/predict/stream")
async def predict_stream(req: PredictionRequest, engine: SimulationEngine = Depends(get_engine),
                         profiler: BrandProfiler = Depends(get_profiler),
                         advisor: Advisor = Depends(get_advisor)) -> StreamingResponse:
    """NDJSON akışı: her satır {"type":"progress",...} / {"type":"result","data":...} / {"type":"error",...}."""
    queue: asyncio.Queue = asyncio.Queue()

    async def emit(event: dict) -> None:
        await queue.put({"type": "progress", **event})

    async def work() -> None:
        try:
            result = await run_prediction(req, engine, profiler, advisor, emit)
            await queue.put({"type": "result", "data": json.loads(result.model_dump_json())})
        except HTTPException as e:
            await queue.put({"type": "error", "status": e.status_code, "detail": e.detail})
        except Exception as e:  # akış kopmasın, hata istemciye iletilsin
            await queue.put({"type": "error", "status": 500, "detail": f"{type(e).__name__}: {e}"})
        await queue.put(None)

    async def body():
        task = asyncio.create_task(work())
        try:
            while (event := await queue.get()) is not None:
                yield json.dumps(event, ensure_ascii=False) + "\n"
        finally:
            task.cancel()

    return StreamingResponse(body(), media_type="application/x-ndjson")
