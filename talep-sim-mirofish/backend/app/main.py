"""FastAPI giriş noktası: ürün talep ve fiyat simülasyonu."""
import asyncio
import json
import logging
import traceback
import os
import time
import uuid
from decimal import Decimal
from typing import Dict, Optional

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .allocation import DemandSignal, RegionSignal, allocate_by_sales_velocity, allocate_production_budget
from .models import Explanation, FailedRegion, BrandProfile, BrandProfileRequest, PredictionRequest, PredictionResponse, RegionPredictionResult
from .advisor import Advisor
from .newstore import Candidate as NewStoreCandidate, NewStoreEstimate
from .explain import allocation_note, allocation_view, explain_region, methodology_notes
from . import economy
from .forecast import HORIZON, DemandModel, forecast_sales
from .extras import break_even, confidence, seasonal_factor, sensitivity, size_curve
from .scenarios import _zone_of, build_campaigns, build_price_plan
from .takvim import data as takvim_data, fit as takvim_fit, plan as takvim_plan
from .returns import estimate_returns
from .pricing import analyze, purchase_probability, steps_from_answers, steps_from_votes
from .config import Settings, settings
from .services.brand_profiler import BrandProfiler
from .services.llm import LLMClient, LLMError
from .services.mirofish_client import MiroFishError
from .services.engine import MockSimulationEngine, SimulationEngine

app = FastAPI(title="Talep Simülasyonu API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3200,http://127.0.0.1:3200").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

def _fuser(cfg: Settings, mock: MockSimulationEngine):
    if cfg.vision_enabled:
        from .services.vision import VisionFusion
        return VisionFusion(cfg.vision_api_key, cfg.vision_base_url, cfg.vision_model).fuse_product_card
    return mock.fuse_product_card


def panel_store(cfg: Settings):
    from .panel.library import PanelStore
    return PanelStore(cfg.panel_data_dir, require_verified=cfg.panel_require_verified)


def build_panel_engine(cfg: Settings, mock: MockSimulationEngine):
    from .panel import calibration
    from .panel.engine import DirectPanelEngine
    from .panel.questioner import PanelLLM

    store = panel_store(cfg)
    llm = PanelLLM(cfg.panel_llm_base_url or cfg.llm_base_url, cfg.panel_llm_model or cfg.llm_model,
                   cfg.llm_api_key or "local", guided=cfg.panel_guided, temperature=cfg.panel_temperature,
                   timeout=cfg.panel_timeout, concurrency=cfg.panel_concurrency,
                   repair_retries=cfg.panel_repair_retries)
    return DirectPanelEngine(store, llm, _fuser(cfg, mock), panel_size=cfg.panel_size, min_valid=cfg.panel_min_valid,
                             peer_round=cfg.panel_peer_round,
                             calibration=calibration.load(store.root / "calibration.json"))


def build_engine(cfg: Settings) -> SimulationEngine:
    """SIM_ENGINE=hybrid: MiroFish + yapamadığı yerde persona paneli, panel: yalnız persona paneli,
    mirofish: yalnız MiroFish ajan sürüsü, aksi halde mock."""
    mock = MockSimulationEngine()
    if cfg.sim_engine == "panel":
        return build_panel_engine(cfg, mock)
    if cfg.sim_engine == "hybrid":
        from .services.hybrid_engine import HybridEngine
        return HybridEngine(build_mirofish_engine(cfg, mock), build_panel_engine(cfg, mock),
                            fallback_on_error=cfg.hybrid_fallback, mirofish_url=cfg.mirofish_url)
    if cfg.sim_engine != "mirofish":
        return mock
    return build_mirofish_engine(cfg, mock)


def build_mirofish_engine(cfg: Settings, mock: MockSimulationEngine):

    from .services.mirofish_client import MiroFishClient
    from .services.mirofish_engine import MiroFishSimulationEngine

    fuser = _fuser(cfg, mock)
    extractor = None
    if cfg.llm_enabled:  # ajan serbest metni, yerel/uzak LLM ile alanlara çevrilir
        from .services.answer_extractor import AnswerExtractor
        extractor = AnswerExtractor(LLMClient(cfg.llm_api_key, cfg.llm_base_url, cfg.llm_model))
    return MiroFishSimulationEngine(
        MiroFishClient(cfg.mirofish_url, build_timeout=cfg.mirofish_build_timeout), fuser, cfg.mirofish_state_file,
        max_rounds=cfg.mirofish_max_rounds, interview_timeout=cfg.mirofish_interview_timeout,
        batch_size=cfg.mirofish_batch_size, timeout_retries=cfg.mirofish_timeout_retries,
        max_concurrency=cfg.mirofish_concurrency, env_wait_s=cfg.mirofish_build_timeout, min_valid=cfg.mirofish_min_valid, extractor=extractor,
        agents_per_region=cfg.mirofish_agents_per_region,
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
    mirofish = None
    if settings.sim_engine in ("hybrid", "mirofish"):
        try:
            async with httpx.AsyncClient(timeout=2) as c:
                mirofish = (await c.get(settings.mirofish_url.rstrip("/") + "/health")).status_code == 200
        except httpx.HTTPError:
            mirofish = False
    return {"status": "ok", "engine": settings.sim_engine, "mirofish_url": settings.mirofish_url, "mirofish_ok": mirofish, "vision": settings.vision_enabled, "llm": settings.llm_enabled}


@app.get("/api/panel/status")
async def panel_status() -> dict:
    """Persona ve bağlam verisinin sürümü, tarihi ve eskime uyarıları (panel motoru için)."""
    from .models import ALL_REGIONS
    from .panel import calibration
    from .panel.drift import DriftMonitor
    from .panel.library import LibraryError, library_status
    store = panel_store(settings)
    try:
        active = store.active_version()
    except LibraryError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    cal = calibration.load(store.root / "calibration.json")
    return {"data_dir": str(store.root), "active_persona_version": active, "versions": store.persona_versions(),
            "regions": library_status(store, list(ALL_REGIONS)),
            "calibration": {"fitted_at": cal.fitted_at, "regions": {k: vars(v) for k, v in cal.regions.items()}},
            "drift": DriftMonitor(store.root / "accuracy.jsonl").report()}


_NEWSTORE_CACHE: dict = {}


def _newstore_data(cfg: Settings):
    """(mağaza istatistikleri, veri notları, profiller); ERP dosyaları değişmedikçe önbellekten."""
    from pathlib import Path
    from . import newstore
    default = Path(__file__).resolve().parents[1] / "panel_data"
    # NEWSTORE_ERP_DIR yoksa SENTETİK örnek klasör kullanılır (ekranda açıkça etiketlenir); gerçek veri gelince ayarla
    synthetic = not cfg.newstore_erp_dir
    erp = default / "ornek_erp" if synthetic else Path(cfg.newstore_erp_dir)
    prof_path = Path(cfg.newstore_profiles) if cfg.newstore_profiles else (
        default / "lokasyon_profilleri.csv" if (default / "lokasyon_profilleri.csv").exists()
        else default / "lokasyon_profilleri.ornek.csv")
    rates = {k.strip(): float(v) for k, v in (x.split("=") for x in cfg.newstore_fixed_rates.split(",") if "=" in x)}
    try:
        stamp = tuple((erp / f).stat().st_mtime for f in ("magazalar.csv", "satislar.csv")) + (prof_path.stat().st_mtime,)
    except OSError as e:
        raise HTTPException(status_code=400, detail=f"Yeni mağaza verisi okunamadı: {e}") from e
    key = (str(erp), str(prof_path), tuple(sorted(rates.items())))
    hit = _NEWSTORE_CACHE.get(key)
    if hit is None or hit[0] != stamp:
        stats, notes = newstore.store_stats(erp, rates)
        if synthetic:
            notes.insert(0, "SENTETİK ÖRNEK VERİ: mağaza satışları uydurma deneme verisidir (ORNEK-* mağazaları), gerçek "
                            "ERP'den gelmiyor. Sonuçlar yalnızca ekranı denemek içindir; gerçek veri için NEWSTORE_ERP_DIR ayarla.")
        if prof_path.name.endswith(".ornek.csv"):
            notes.append("Lokasyon profilleri ÖRNEK dosyadan geldi (yaklaşık, kaynaksız değerler); gerçek dış veriyle değiştir.")
        hit = (stamp, stats, notes, newstore.load_profiles(prof_path), synthetic)
        _NEWSTORE_CACHE[key] = hit
    return hit[1], hit[2], hit[3], hit[4]


@app.get("/api/new-store/locations")
async def new_store_locations() -> list:
    _, _, profiles, _ = _newstore_data(settings)
    return [p.model_dump(mode="json") for p in profiles.values()]


@app.post("/api/new-store/estimate", response_model=NewStoreEstimate)
async def new_store_estimate(cand: NewStoreCandidate) -> NewStoreEstimate:
    """Aday lokasyon için yıllık ciro aralığı, benzer mağazalar ve uyarılar."""
    from . import newstore
    stats, notes, profiles, synthetic = _newstore_data(settings)
    try:
        est = newstore.estimate(cand, stats, profiles, data_notes=notes)
        est.synthetic_data = synthetic
        return est
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/brand-profile", response_model=BrandProfile)
async def brand_profile(req: BrandProfileRequest, profiler: BrandProfiler = Depends(get_profiler)) -> BrandProfile:
    """Marka adından fiyat/konumlandırma profili çıkarır; kullanıcı sonucu düzenleyip /api/predict'e verebilir."""
    return await profiler.profile(req.brand, req.notes)


def _price_steps(sim, vw, best):
    """Ajanların fiyat basamaklarına verdiği kararlar; merdiven oyu yoksa eşiklerden hesaplanır."""
    if sim.meta.get("ladder_votes"):
        return steps_from_votes(sim.meta["ladder"], sim.meta["ladder_votes"])
    lo, hi = float(vw.curve[0].price), float(vw.curve[-1].price)
    return steps_from_answers(sim.price_answers, [lo + (hi - lo) * i / 7 for i in range(8)])


def _data_basis(meta: dict):
    """Panel motorunda kullanılan persona/bağlam sürümü ve tarihleri (arayüzde 'as of' olarak gösterilir)."""
    if meta.get("engine") != "panel":
        return None
    keys = ("persona_version", "persona_as_of", "context_version", "context_as_of", "freshness_warnings",
            "calibration", "peer_round", "segments", "elapsed_s")
    return {k: meta.get(k) for k in keys}


async def _noop(_: dict) -> None:
    return None


async def _calendar_fits(req: PredictionRequest, engine, card: dict, brand, priced: dict, fx_rate: float, emit):
    """Takvim penceresindeki etkinlikler ve bölge başına takvim turu (etkinlik uygunluğu + bekleme). Hata planı düşürmez."""
    from datetime import date as _date
    if not req.assumptions.calendar_plan:
        return None
    try:
        tk = takvim_data.load(settings.takvim_dir)
    except (takvim_data.TakvimError, OSError) as e:
        await emit({"stage": "finalize", "detail": f"Takvim dosyası okunamadı, takvim planı atlandı: {e}"})
        return None
    start = req.assumptions.calendar_start or _date.today()
    events = {r: tk.window(r, start, HORIZON, settings.takvim_dogrulanmis_zorunlu) for r in priced}
    await emit({"stage": "finalize", "detail": "Takvim turu: etkinlik uygunluğu ve bekleme eğilimi soruluyor"})
    text = f"{req.product_name} {req.technical_specs}"

    async def one(r):
        s_, _, best_ = priced[r]
        return r, await takvim_fit.evaluate(engine, card, r, events[r], tk, brand, float(best_),
                                            fx_rate if r == "TR" else None, text, settings.takvim_turu, settings.takvim_dir)

    fits = dict(await asyncio.gather(*(one(r) for r in priced)))
    return {"takvim": tk, "start": start, "events": events, "fits": fits}


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

    if req.reset_world and hasattr(engine, "reset_world"):
        await emit({"stage": "world", "detail": "Dünya sıfırlanıyor: eski proje/Zep grafiği siliniyor, baştan kurulacak"})
        try:
            for note in await engine.reset_world(req.target_regions, emit):
                await emit({"stage": "world", "detail": note})
        except (MiroFishError, httpx.HTTPError, OSError) as e:
            await emit({"stage": "world", "detail": f"Sıfırlama kısmen başarısız ({type(e).__name__}: {e}); yeni dünya yine de kurulacak"})

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
                sim = await engine.simulate_region(card, region, unit_cost, brand, fx_rates, progress=emit,
                                                scope=req.target_regions)
            except (MiroFishError, LLMError, httpx.HTTPError) as e:
                done += 1
                reason = f"{type(e).__name__}: {e}"
                await emit({"stage": "region_failed", "region": region, "done": done, "total": total, "detail": reason})
                return FailedRegion(region=region, reason=reason, raw_answers=getattr(e, "raw_answers", []))
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
    fx = req.assumptions
    pre = {}
    for r, (s_, vw_, best_) in priced.items():
        prob_ = purchase_probability(s_.price_answers, float(best_))
        season_ = seasonal_factor(card, r, fx)
        ret_ = estimate_returns(card, r, float(best_), unit_cost, 0, brand, fx, f"{req.product_name} {req.technical_specs}")
        dm_ = DemandModel(r, s_.demand_score, float(best_), vw_.zones, brand, fx, season_.factor if season_ else 1.0)
        pre[r] = (dm_.base * prob_, ret_.rate_pct)
    before = allocate_production_budget(
        [RegionSignal(r, s.demand_score, best) for r, (s, _, best) in priced.items()],
        Decimal(req.total_production_budget), req.unit_cost)
    if req.allocation_objective == "profit":
        allocations = before
    else:
        bal = allocate_by_sales_velocity(
            [DemandSignal(r, pre[r][0], float(best) * (1 - pre[r][1] / 100 * (1 + fx.reverse_logistics_pct / 100)),
                          pre[r][1], fx.restock_share) for r, (s, _, best) in priced.items()],
            Decimal(req.total_production_budget), req.unit_cost, req.allocation_objective)
        allocations = bal.allocations

    total_weight = sum((a.weight for a in allocations.values()), Decimal(0))
    cal = await _calendar_fits(req, engine, card, brand, priced, fx_rate, emit)
    breakdown = []
    for region, (sim, vw, best) in priced.items():
        alloc = allocations[region]
        currency = economy.currency_of(region)
        local = {"local_currency": currency, "local_price": economy.local_price(best, fx_rate),
                 "fx_rate": fx_rate} if currency == "TRY" else {}
        margin = float((best - req.unit_cost) / best * 100) if best > 0 else 0.0
        view = allocation_view(region, req.allocation_objective, pre[region][0], pre[region][1], fx.restock_share,
                               before[region].quantity, alloc.quantity, float(req.unit_cost), float(best))
        ret = estimate_returns(card, region, float(best), unit_cost, alloc.quantity, brand,
                               req.assumptions, f"{req.product_name} {req.technical_specs}")
        prob = purchase_probability(sim.price_answers, float(best))
        season = seasonal_factor(card, region, req.assumptions)
        sf = season.factor if season else 1.0
        fc = forecast_sales(region, sim.demand_score, float(best), prob, vw.zones, alloc.quantity,
                            ret.rate_pct, brand, req.assumptions, sf)
        dm = DemandModel(region, sim.demand_score, float(best), vw.zones, brand, req.assumptions, sf)
        plan = build_price_plan(dm, sim.price_answers, vw, float(best), unit_cost, alloc.quantity, ret.rate_pct, req.assumptions)
        camps = build_campaigns(region, dm, sim.price_answers, float(best), unit_cost, alloc.quantity, ret.rate_pct,
                                req.assumptions, fc)
        cplan = None
        if cal is not None and region in cal["fits"]:
            tk, start = cal["takvim"], cal["start"]
            cplan = takvim_plan.build_calendar_plan(region, dm, sim.price_answers, float(best), unit_cost, alloc.quantity,
                                                    ret.rate_pct, req.assumptions, tk, cal["events"][region],
                                                    cal["fits"][region], start)
            plan = takvim_plan.to_price_plan(cplan, dm, sim.price_answers, vw, float(best), unit_cost, alloc.quantity,
                                             ret.rate_pct, req.assumptions, _zone_of) or plan
        breakdown.append(RegionPredictionResult(
            region=region,
            demand_score_100=sim.demand_score,
            optimal_sale_price=best,
            recommended_production_qty=alloc.quantity,
            allocated_budget=alloc.budget,
            estimated_margin_percentage=round(margin, 1),
            key_objections=sim.objections,
            van_westendorp=vw,
            price_steps=_price_steps(sim, vw, best),
            returns=ret,
            forecast=fc, price_plan=plan, campaigns=camps, calendar_plan=cplan,
            sensitivity=sensitivity(dm, sim.price_answers, float(best), unit_cost, alloc.quantity, ret.rate_pct,
                                    req.assumptions),
            break_even=break_even(float(best), unit_cost, alloc.quantity, ret.rate_pct, req.assumptions, fc),
            confidence=confidence(sim.meta, brand.known_brand if brand else None, req.assumptions, region),
            size_curve=size_curve(region, card), seasonality=season,
            raw_answers=sim.meta.get("raw_answers", []),
            data_basis=_data_basis(sim.meta),
            engine=sim.meta.get("engine"),
            engine_note=(f"MiroFish bu bölgeyi hesaplayamadı, persona paneli kullanıldı: {sim.meta['fallback_reason']}"
                         if sim.meta.get("fallback_from") else None),
            explanations=[e if e.key != "quantity" else Explanation(
                key="quantity", label=e.label, value=f"{alloc.quantity:,}", how=view.why,
                assumptions=["Talep 120 günlük ajan talebi + kural varsayımlarından (kitle, dönüşüm) gelir; stok sınırsız varsayıldığında beklenen satıştır.",
                             "Üretim adedi minimum sipariş adedi ve sezon sonu indirimi hesaba katılmadan belirlendi."])
                          for e in explain_region(sim, vw, best, unit_cost, alloc, total_weight,
                                                  req.total_production_budget, brand, fx_rate)],
            allocation=view,
            **local,
        ))

    spent = sum((a.quantity * req.unit_cost for a in allocations.values()), Decimal(0))
    unallocated = Decimal(req.total_production_budget) - spent
    used = {s.meta.get("engine", "mock") for s in sims}
    engine_name = "hybrid" if (len(used) > 1 or any(s.meta.get("fallback_from") for s in sims)) else used.pop()
    notes = methodology_notes(engine_name, brand)
    fell_back = [s for s in sims if s.meta.get("fallback_from")]
    if fell_back:
        notes.append("MiroFish şu bölgeleri hesaplayamadı, bu bölgeler persona paneliyle (yerel model) hesaplandı: " +
                     "; ".join(f"{s.region} ({s.meta.get('fallback_reason', '')[:120]})" for s in fell_back) +
                     ". Bu bölgelerin sonuçları MiroFish ajanlarından değil, panel kişilerinden gelir.")
    if failed:
        notes.append("Hesaplanamayan bölgeler (" + ", ".join(f.region for f in failed) +
                     ") dağıtıma katılmadı; bütçe yalnızca hesaplanan bölgeler arasında paylaştırıldı.")
    return PredictionResponse(
        session_id=str(uuid.uuid4()),
        total_produced_qty=sum(a.quantity for a in allocations.values()),
        unallocated_budget=unallocated,
        allocation_objective=req.allocation_objective,
        allocation_note=allocation_note(req.allocation_objective, unallocated, req.unit_cost,
                                        sum(pre[r][0] for r in pre), sum(a.quantity for a in allocations.values())),
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


class Run:
    """Sunucu tarafında yürüyen bir tahmin koşusu. İstemci kopsa/sayfa yenilense de koşu sürer, olaylar saklanır."""

    def __init__(self) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.events: list = []
        self.done = False
        self.started = time.time()
        self.cond = asyncio.Condition()
        self.task: Optional[asyncio.Task] = None

    async def publish(self, event: dict) -> None:
        async with self.cond:
            self.events.append({"seq": len(self.events), **event})
            self.cond.notify_all()


RUNS: Dict[str, Run] = {}
RUN_TTL_S = 3600
HEARTBEAT_S = 5.0


def _gc_runs() -> None:
    for rid in [r for r, run in RUNS.items() if run.done and time.time() - run.started > RUN_TTL_S]:
        RUNS.pop(rid, None)


async def _follow(run: Run, start: int):
    """Olayları `start` sırasından itibaren NDJSON satırı olarak verir; sessizlikte kalp atışı (ping) yollar."""
    i = start
    while True:
        while i < len(run.events):
            yield json.dumps(run.events[i], ensure_ascii=False) + "\n"
            i += 1
        if run.done:
            return
        try:
            async with run.cond:
                await asyncio.wait_for(run.cond.wait(), timeout=HEARTBEAT_S)
        except asyncio.TimeoutError:
            yield json.dumps({"type": "ping", "elapsed": round(time.time() - run.started)}) + "\n"


_STREAM_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


@app.post("/api/predict/stream")
async def predict_stream(req: PredictionRequest, engine: SimulationEngine = Depends(get_engine),
                         profiler: BrandProfiler = Depends(get_profiler),
                         advisor: Advisor = Depends(get_advisor)) -> StreamingResponse:
    """NDJSON akışı: run / progress / ping / result / error. Koşu istemciden bağımsız sürer;
    bağlantı koparsa GET /api/runs/{id}/events?from=N ile kaldığı yerden devam edilir."""
    _gc_runs()
    run = Run()
    RUNS[run.id] = run

    async def work() -> None:
        await run.publish({"type": "run", "id": run.id, "started": run.started})
        try:
            result = await run_prediction(req, engine, profiler, advisor,
                                          lambda ev: run.publish({"type": "progress", **ev}))
            await run.publish({"type": "result", "data": json.loads(result.model_dump_json())})
        except HTTPException as e:
            await run.publish({"type": "error", "status": e.status_code, "detail": e.detail})
        except Exception as e:  # akış kopmasın, hata istemciye iletilsin
            logging.getLogger("talep-sim").exception("Koşu beklenmedik hatayla düştü")
            tb = traceback.extract_tb(e.__traceback__)[-1]
            where = f"{os.path.basename(tb.filename)}:{tb.lineno} ({tb.name})"
            await run.publish({"type": "error", "status": 500, "detail": (
                f"Beklenmedik hata: {type(e).__name__}: {e} [{where}]. Eski/bozuk önbellek şüphesinde "
                "'Dünyayı sıfırla' kutusunu işaretleyip tekrar dene; sorun sürerse API terminalindeki hata dökümünü paylaş.")})
        run.done = True
        async with run.cond:
            run.cond.notify_all()

    run.task = asyncio.create_task(work())  # referans tutulur; istemci kopsa da iptal edilmez
    return StreamingResponse(_follow(run, 0), media_type="application/x-ndjson", headers=_STREAM_HEADERS)


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str, start: int = 0) -> StreamingResponse:
    """Çalışan ya da biten bir koşunun olaylarını `start` sırasından itibaren yeniden akıtır."""
    run = RUNS.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Koşu bulunamadı (sunucu yeniden başlatılmış ya da süresi dolmuş olabilir)")
    return StreamingResponse(_follow(run, max(0, start)), media_type="application/x-ndjson", headers=_STREAM_HEADERS)


# Koleksiyon modu (toplu ürün değerlendirme). Döngüsel içe aktarmayı önlemek için en sonda.
from .collection.routes import router as collection_router  # noqa: E402

app.include_router(collection_router)

from .mallprofile.routes import router as mall_router  # noqa: E402

app.include_router(mall_router)
