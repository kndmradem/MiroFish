"""Sapma (drift) izleme: bölge bazında tahmin isabetinin zaman içindeki seyri.

Tüketici alışkanlıkları ve moda değiştikçe aynı persona seti zamanla kötüleşir. Her ürünün gerçekleşen
satışı geldiğinde (ör. ERP'den 120. gün) tahminle karşılaştırılıp kaydedilir. Son dönem hatası uzun dönem
hatasından belirgin kötüyse ya da tahminler hep aynı yöne kayıyorsa bölge "sapma var" olarak işaretlenir:
persona/bağlam güncellemesi ve yeniden kalibrasyon zamanı demektir.
"""
import json
import math
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .calibration import Observation

DRIFT_RATIO = 1.3     # son dönem WAPE > uzun dönem WAPE x 1.3 ise sapma
BIAS_LIMIT = 0.25     # log oran ortalaması |ort| > 0.25 (~%28) ise sistematik yön sapması
MIN_RECENT = 3


@dataclass
class AccuracyRecord:
    day: str
    region: str
    product: str
    persona_version: str
    predicted_units: float
    actual_units: float


class DriftMonitor:
    def __init__(self, path: Path):
        self.path = Path(path)

    def record(self, obs: Iterable[Observation], product: str, persona_version: str,
               day: Optional[date] = None) -> None:
        day = (day or date.today()).isoformat()
        with self.path.open("a", encoding="utf-8") as f:
            for o in obs:
                f.write(json.dumps(asdict(AccuracyRecord(day, o.region, product, persona_version,
                                                         o.predicted_units, o.actual_units)),
                                   ensure_ascii=False) + "\n")

    def records(self) -> List[AccuracyRecord]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(AccuracyRecord(**json.loads(line)))
            except (ValueError, TypeError):
                continue
        return out

    def report(self, today: Optional[date] = None, recent_days: int = 90, baseline_days: int = 365) -> Dict[str, dict]:
        today = today or date.today()
        out: Dict[str, dict] = {}
        recs = self.records()
        for region in sorted({r.region for r in recs}):
            rs = [r for r in recs if r.region == region]
            recent = [r for r in rs if date.fromisoformat(r.day) > today - timedelta(days=recent_days)]
            base = [r for r in rs if today - timedelta(days=baseline_days) < date.fromisoformat(r.day)
                    <= today - timedelta(days=recent_days)]
            w_recent, w_base = wape(recent), wape(base)
            b = bias(recent)
            reasons = []
            if len(recent) >= MIN_RECENT and w_base is not None and w_recent is not None and w_recent > w_base * DRIFT_RATIO:
                reasons.append(f"son {recent_days} gün hata %{w_recent:.0f}, önceki dönem %{w_base:.0f}")
            if len(recent) >= MIN_RECENT and b is not None and abs(b) > BIAS_LIMIT:
                reasons.append(("tahminler sistematik olarak yüksek" if b < 0 else "tahminler sistematik olarak düşük")
                               + f" (ortalama oran {math.exp(b):.2f})")
            out[region] = {"recent_wape_pct": w_recent, "baseline_wape_pct": w_base, "recent_n": len(recent),
                           "baseline_n": len(base), "bias_ratio": round(math.exp(b), 2) if b is not None else None,
                           "drift": bool(reasons), "reasons": reasons}
        return out


def wape(recs: List[AccuracyRecord]) -> Optional[float]:
    """Ağırlıklı mutlak yüzde hata: Σ|tahmin-gerçek| / Σgerçek."""
    actual = sum(r.actual_units for r in recs)
    if not recs or actual <= 0:
        return None
    return round(sum(abs(r.predicted_units - r.actual_units) for r in recs) / actual * 100, 1)


def bias(recs: List[AccuracyRecord]) -> Optional[float]:
    logs = [math.log(r.actual_units / r.predicted_units) for r in recs if r.actual_units > 0 and r.predicted_units > 0]
    return sum(logs) / len(logs) if logs else None
