"""Geriye dönük test (backtest): geçmiş ürünleri panelle yeniden tahmin edip ERP'deki gerçek satışla karşılaştırır.

Kullanım alanları:
- Persona sürümü karşılaştırma: aynı ürünler v1 ve v2 personalarıyla koşulur, hangisi gerçeğe yakınsa o terfi eder
  (`active.json`). Böylece "daha iyi görünen" değil, ölçülerek daha isabetli olan persona seti kullanılır.
- Kalibrasyon: zaman sırasına göre eski ürünlerde katsayılar uydurulur, yeni ürünlerde sınanır (geleceği
  görmeden). Aynı kurgu sensitivity/trend çarpanlarının ızgara aramasında da kullanılır (`Candidate`).
- Sızıntı önlemi: her ürün kendi lansman tarihindeki bağlam paketiyle koşulur (`DirectPanelEngine.as_of`).

Veri kaynağı ERP'den bağımsızdır: `BacktestCase` listesini Nebim V3 / PostgreSQL aktarımı ya da sentetik veri
üretir. Tahminci (`Predictor`) değiştirilebilir; varsayılanı tam tahmin hattını çalıştırır.
"""
import math
from dataclasses import dataclass, field
from datetime import date
from typing import Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

from ..models import PredictionRequest
from .calibration import Calibration, Observation, fit
from .drift import AccuracyRecord, bias, wape
from .library import PanelStore


@dataclass(frozen=True)
class Actual:
    units: float                       # aynı ufuktaki (varsayılan ilk 120 gün) satış adedi
    full_price: Optional[float] = None # indirimsiz dönem ortalama fiyatı (USD)
    stocked_out: bool = False


@dataclass
class BacktestCase:
    product: str
    launch_date: date
    request: PredictionRequest
    actuals: Dict[str, Actual]


@dataclass
class Candidate:
    """Sınanacak kurgu: persona sürümü + taban kalibrasyon (sensitivity/trend çarpanları burada denenir)."""
    label: str
    persona_version: str
    base: Calibration = field(default_factory=Calibration)


# (vaka, aday, uygulanacak kalibrasyon) -> {bölge: (tahmini adet, önerilen fiyat)}
Predictor = Callable[[BacktestCase, Candidate, Calibration], Awaitable[Dict[str, Tuple[float, float]]]]


@dataclass
class CandidateResult:
    label: str
    persona_version: str
    train_n: int
    test_n: int
    raw_wape_pct: Optional[float]          # kalibrasyonsuz, test vakalarında
    calibrated_wape_pct: Optional[float]   # eğitim vakalarında uydurulan katsayılarla, test vakalarında
    bias_ratio: Optional[float]
    by_region: Dict[str, Optional[float]]
    calibration: Calibration

    @property
    def score(self) -> float:
        v = self.calibrated_wape_pct if self.calibrated_wape_pct is not None else self.raw_wape_pct
        return v if v is not None else math.inf


def _observations(case: BacktestCase, preds: Dict[str, Tuple[float, float]]) -> List[Observation]:
    out = []
    for region, (units, price) in preds.items():
        a = case.actuals.get(region)
        if a is not None:
            out.append(Observation(region, units, a.units, price, a.full_price, a.stocked_out))
    return out


def _records(obs: Sequence[Observation], label: str) -> List[AccuracyRecord]:
    return [AccuracyRecord("", o.region, "", label, o.predicted_units, o.actual_units) for o in obs]


def _with_scales(base: Calibration, fitted: Calibration) -> Calibration:
    """Uydurulan demand/price katsayılarını adayın sensitivity/trend çarpanlarıyla birleştirir."""
    out = Calibration(persona_version=fitted.persona_version, fitted_at=fitted.fitted_at, notes=fitted.notes)
    for r in set(base.regions) | set(fitted.regions):
        f, b = fitted.for_region(r), base.for_region(r)
        f.sensitivity_scale, f.trend_scale = b.sensitivity_scale, b.trend_scale
        out.regions[r] = f
    return out


async def evaluate(cases: Sequence[BacktestCase], candidate: Candidate, predictor: Predictor,
                   train_frac: float = 0.6) -> CandidateResult:
    """Zaman sıralı böl: ilk %train_frac vakada kalibrasyon uydur, kalanında sına."""
    ordered = sorted(cases, key=lambda c: c.launch_date)
    k = max(1, int(len(ordered) * train_frac)) if len(ordered) > 1 else 0
    train, test = ordered[:k], ordered[k:] or ordered
    train_obs: List[Observation] = []
    for c in train:
        train_obs += _observations(c, await predictor(c, candidate, candidate.base))
    cal = _with_scales(candidate.base, fit(train_obs, candidate.base, candidate.persona_version))
    raw_obs: List[Observation] = []
    cal_obs: List[Observation] = []
    for c in test:
        raw_obs += _observations(c, await predictor(c, candidate, candidate.base))
        cal_obs += _observations(c, await predictor(c, candidate, cal))
    recs = _records(cal_obs, candidate.label)
    b = bias(recs)
    return CandidateResult(
        label=candidate.label, persona_version=candidate.persona_version, train_n=len(train), test_n=len(test),
        raw_wape_pct=wape(_records(raw_obs, candidate.label)), calibrated_wape_pct=wape(recs),
        bias_ratio=round(math.exp(b), 2) if b is not None else None,
        by_region={r: wape([x for x in recs if x.region == r]) for r in sorted({x.region for x in recs})},
        calibration=cal)


async def compare(cases: Sequence[BacktestCase], candidates: Sequence[Candidate], predictor: Predictor,
                  train_frac: float = 0.6) -> List[CandidateResult]:
    """Adayları sınar, en isabetliden en kötüye sıralı döner."""
    results = [await evaluate(cases, c, predictor, train_frac) for c in candidates]
    return sorted(results, key=lambda r: r.score)


def promote(store: PanelStore, results: List[CandidateResult], min_gain_pct: float = 5.0) -> Tuple[bool, str]:
    """En iyi aday, şu anki aktif sürümden en az `min_gain_pct` puan iyiyse aktif yapılır ve kalibrasyonu yazılır."""
    if not results:
        return False, "Sınanan aday yok."
    best = results[0]
    active = store.active_version()
    current = next((r for r in results if r.persona_version == active), None)
    if current is not None and best.persona_version != active and current.score - best.score < min_gain_pct:
        return False, (f"{best.label} (%{best.score:.1f}) aktif sürümden ({active}, %{current.score:.1f}) "
                       f"yeterince iyi değil (eşik {min_gain_pct} puan); değişiklik yapılmadı.")
    store.set_active(best.persona_version, reason=f"backtest: {best.label} WAPE %{best.score:.1f}")
    from .calibration import save
    save(best.calibration, store.root / "calibration.json")
    return True, f"{best.label} aktif yapıldı (test hatası %{best.score:.1f}); kalibrasyon kaydedildi."


def pipeline_predictor(store: PanelStore, llm, fuser, panel_size: int = 12, min_valid: int = 4,
                       peer_round: bool = False) -> Predictor:
    """Tam tahmin hattını (fiyat, iade, 120 gün satış) panel motoruyla çalıştıran varsayılan tahminci.

    Tahmini adet: 120 günlük stok sınırsız talep (forecast eğrisinin son noktası), fiyat: önerilen fiyat.
    """
    from ..advisor import Advisor
    from ..main import run_prediction
    from ..services.brand_profiler import BrandProfiler
    from .engine import DirectPanelEngine

    async def predict(case: BacktestCase, cand: Candidate, cal: Calibration) -> Dict[str, Tuple[float, float]]:
        engine = DirectPanelEngine(store, llm, fuser, panel_size, min_valid, peer_round, cal,
                                   persona_version=cand.persona_version, as_of=case.launch_date)
        res = await run_prediction(case.request, engine, BrandProfiler(None), Advisor(None))
        return {r.region: (float(r.forecast.curve[-1].demand), float(r.optimal_sale_price))
                for r in res.regional_breakdown if r.forecast}

    return predict
