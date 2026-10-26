"""Kalibrasyon: panel tahminlerini gerçek satışa yaklaştıran küçük, açıklanabilir katsayı seti.

Persona paneli mutlak talebi bilemez; ancak ERP'deki gerçek satışlarla karşılaştırıldığında sistematik
sapmalar (ör. "EU talebini hep %30 fazla tahmin ediyor", "TR'de fiyatı hep yüksek buluyor") düzeltilebilir.

Katsayılar (bölge başına, varsayılan 1.0 = düzeltme yok):
- demand_scale:      talep skoru çarpanı (satış adedi talep skoruyla doğrusal ölçeklenir)
- price_scale:       ajanların fiyat eşiklerinin çarpanı (gerçekleşen tam fiyat / önerilen fiyat)
- sensitivity_scale: personaların fiyat duyarlılığı çarpanı (promptu değiştirir; backtest ızgarasıyla uydurulur)
- trend_scale:       personaların trend ilgisi çarpanı (aynı şekilde)

demand_scale ve price_scale kapalı formülle uydurulur: log-oranların ortalaması, az gözlemde 1.0'a doğru
büzülür (shrinkage), uç değerler kırpılır. Böylece 2-3 ürünle aşırı düzeltme yapılmaz.
"""
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Sequence

SHRINK_K = 5          # k gözlemde ağırlık %50: w = n / (n + k)
CLAMP = (0.4, 2.5)    # tek katsayının alabileceği aralık


@dataclass
class RegionCalibration:
    demand_scale: float = 1.0
    price_scale: float = 1.0
    sensitivity_scale: float = 1.0
    trend_scale: float = 1.0
    n_obs: int = 0


@dataclass
class Calibration:
    persona_version: str = ""
    fitted_at: Optional[str] = None
    regions: Dict[str, RegionCalibration] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)

    def for_region(self, region: str) -> RegionCalibration:
        return self.regions.get(region, RegionCalibration())

    @property
    def is_identity(self) -> bool:
        return all(r == RegionCalibration(n_obs=r.n_obs) for r in self.regions.values())

    def to_json(self) -> str:
        return json.dumps({"persona_version": self.persona_version, "fitted_at": self.fitted_at,
                           "regions": {k: asdict(v) for k, v in self.regions.items()}, "notes": self.notes},
                          ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, d: dict) -> "Calibration":
        return cls(persona_version=d.get("persona_version", ""), fitted_at=d.get("fitted_at"),
                   regions={k: RegionCalibration(**v) for k, v in (d.get("regions") or {}).items()},
                   notes=list(d.get("notes") or []))


def load(path: Path) -> Calibration:
    try:
        return Calibration.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return Calibration()


def save(cal: Calibration, path: Path) -> None:
    path.write_text(cal.to_json(), encoding="utf-8")


@dataclass(frozen=True)
class Observation:
    """Bir ürünün bir bölgede tahmin ve gerçekleşen değeri (ERP'den). Aynı dönem (ör. ilk 120 gün) olmalı."""
    region: str
    predicted_units: float
    actual_units: float
    predicted_price: Optional[float] = None
    actual_full_price: Optional[float] = None   # indirimsiz dönemdeki ortalama satış fiyatı
    stocked_out: bool = False                   # stok bittiyse gerçek talep satıştan büyüktür


def _clamp(x: float) -> float:
    return max(CLAMP[0], min(CLAMP[1], x))


def _shrunk_ratio(logs: Sequence[float]) -> float:
    if not logs:
        return 1.0
    n = len(logs)
    mean = sum(logs) / n
    return _clamp(math.exp(mean * n / (n + SHRINK_K)))


def fit(observations: Sequence[Observation], base: Optional[Calibration] = None,
        persona_version: str = "") -> Calibration:
    """demand_scale ve price_scale'i gözlemlerden uydurur; diğer katsayılar `base`ten korunur.

    Gözlemler *kalibrasyonsuz* tahminlerle verilmeli (yoksa düzeltme üst üste biner); bkz. backtest.py.
    Stoğu biten gözlemde gerçek talep bilinmez: tahmin gerçekten azsa düşük tahmin kanıtıdır, fazlaysa atlanır.
    """
    cal = Calibration(persona_version=persona_version or (base.persona_version if base else ""),
                      fitted_at=date.today().isoformat())
    regions = sorted({o.region for o in observations} | set(base.regions if base else {}))
    for r in regions:
        prev = base.for_region(r) if base else RegionCalibration()
        obs = [o for o in observations if o.region == r and o.predicted_units > 0 and o.actual_units > 0]
        d_logs = [math.log(o.actual_units / o.predicted_units) for o in obs
                  if not (o.stocked_out and o.actual_units < o.predicted_units)]
        p_logs = [math.log(o.actual_full_price / o.predicted_price) for o in obs
                  if o.predicted_price and o.actual_full_price]
        cal.regions[r] = RegionCalibration(
            demand_scale=round(_shrunk_ratio(d_logs), 3) if d_logs else prev.demand_scale,
            price_scale=round(_shrunk_ratio(p_logs), 3) if p_logs else prev.price_scale,
            sensitivity_scale=prev.sensitivity_scale, trend_scale=prev.trend_scale, n_obs=len(obs))
        if 0 < len(obs) < 3:
            cal.notes.append(f"{r}: yalnızca {len(obs)} gözlem; katsayılar 1.0'a doğru güçlü biçimde büzüldü.")
    return cal
