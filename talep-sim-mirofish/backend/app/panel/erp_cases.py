"""ERP veri sözleşmesindeki CSV'lerden (talep-sim/tahmin, Nebim V3 aktarımı ya da sentetik veri) backtest vakaları.

Okunan tablolar: urunler, skular, satislar, magazalar, doviz_kurlari. Her ürün için ilk satış tarihinden
itibaren `horizon_days` gündeki satış adedi bölge bazında toplanır; tam fiyat, kampanyasız satışların adet
başı net tutarıdır. Tutarlar doviz_kurlari.try_karsiligi ile USD'ye çevrilir.

Sınır: stok bitişi bu adaptörde tespit edilmez (stocked_out=False); stoğu erken biten ürünler gerçek talebi
olduğundan düşük gösterir. Ülke -> bölge eşlemesi tahmin/bolgeler.py ile aynı tutulmalı.
"""
import csv
from bisect import bisect_right
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from ..models import PredictionRequest
from .backtest import Actual, BacktestCase

COUNTRY_REGION: Dict[str, str] = {
    "TR": "TR",
    **{c: "EU" for c in ("DE", "NL", "FR", "BE", "AT", "IT", "ES", "PL", "RO", "BG", "GR", "SE", "DK", "CH", "GB",
                         "CZ", "HU", "PT", "IE")},
    **{c: "MENA" for c in ("AE", "SA", "QA", "KW", "BH", "OM", "EG", "MA", "JO", "LB", "IQ", "DZ", "TN", "LY")},
    **{c: "CIS" for c in ("KZ", "AZ", "UZ", "RU", "UA", "BY", "GE", "AM", "KG", "TM", "TJ", "MD")},
    **{c: "US" for c in ("US", "CA")},
}


def _rows(folder: Path, name: str, optional: bool = False) -> List[dict]:
    path = folder / f"{name}.csv"
    if optional and not path.exists():
        return []
    if not path.exists():
        raise FileNotFoundError(f"{path} yok (ERP veri sözleşmesindeki tablo)")
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


class _Fx:
    """Tarihe göre 1 birim para = kaç TRY (tarihten önceki en yakın kur)."""

    def __init__(self, rows: List[dict], usd_try: Optional[float] = None):
        series: Dict[str, List[tuple]] = defaultdict(list)
        if usd_try:  # doviz_kurlari yoksa ya da USD içermiyorsa sabit kur (varsayım)
            series["USD"].append((date.min, float(usd_try)))
        for r in rows:
            series[r["para_birimi"].upper()].append((date.fromisoformat(r["tarih"]), float(r["try_karsiligi"])))
        self.series = {k: sorted(v) for k, v in series.items()}

    def try_of(self, currency: str, day: date) -> Optional[float]:
        currency = (currency or "TRY").upper()
        if currency == "TRY":
            return 1.0
        s = self.series.get(currency)
        if not s:
            return None
        i = bisect_right([d for d, _ in s], day) - 1
        return s[max(0, i)][1]

    def to_usd(self, amount: float, currency: str, day: date) -> Optional[float]:
        src, usd = self.try_of(currency, day), self.try_of("USD", day)
        return amount * src / usd if src and usd else None


def load_cases(folder: str | Path, horizon_days: int = 120, regions: Optional[Sequence[str]] = None,
               budget: int = 100_000, min_units: int = 1, usd_try: Optional[float] = None) -> List[BacktestCase]:
    """`usd_try`: doviz_kurlari.csv'de USD yoksa kullanılacak sabit kur (1 USD = ? TRY)."""
    folder = Path(folder)
    rates = _rows(folder, "doviz_kurlari", optional=True)
    has_usd = any(r["para_birimi"].upper() == "USD" for r in rates)
    if not has_usd and not usd_try:
        raise ValueError("doviz_kurlari.csv'de USD kuru yok; usd_try parametresiyle sabit kur ver")
    fx = _Fx(rates, None if has_usd else usd_try)
    stores = {m["magaza_kodu"]: m for m in _rows(folder, "magazalar")}
    sku_product = {s["sku_kodu"]: s["urun_kodu"] for s in _rows(folder, "skular")}
    products = {p["urun_kodu"]: p for p in _rows(folder, "urunler") if p.get("ilk_satis_tarihi")}
    start = {k: date.fromisoformat(p["ilk_satis_tarihi"]) for k, p in products.items()}

    units: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    full: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))  # usd, adet
    for s in _rows(folder, "satislar"):
        code = sku_product.get(s["sku_kodu"])
        store = stores.get(s["magaza_kodu"])
        if code not in start or store is None:
            continue
        day = date.fromisoformat(s["tarih"])
        if not start[code] <= day < start[code] + timedelta(days=horizon_days):
            continue
        region = COUNTRY_REGION.get((store.get("ulke") or "").upper())
        if region is None or (regions and region not in regions):
            continue
        qty = float(s["adet"] or 0)
        units[code][region] += qty
        if not (s.get("kampanya_kodu") or "").strip() and qty > 0:
            usd = fx.to_usd(float(s["net_tutar"] or 0), store.get("para_birimi") or "TRY", day)
            if usd is not None:
                full[code][region][0] += usd
                full[code][region][1] += qty

    cases: List[BacktestCase] = []
    for code, by_region in units.items():
        p = products[code]
        cost = fx.to_usd(float(p["birim_maliyet"]), p.get("maliyet_para_birimi") or "TRY", start[code])
        actual = {r: Actual(units=u, full_price=(full[code][r][0] / full[code][r][1]) if full[code][r][1] else None)
                  for r, u in by_region.items() if u >= min_units}
        if not actual or not cost or cost <= 0:
            continue
        specs = ", ".join(x for x in (p.get("kumas_karisimi"), p.get("kalip"), p.get("desen"), p.get("kategori")) if x)
        req = PredictionRequest(product_name=p["urun_adi"], image_base64="-", technical_specs=specs or p["urun_adi"],
                                unit_cost=round(cost, 2), total_production_budget=budget,
                                target_regions=sorted(actual))
        cases.append(BacktestCase(code, start[code], req, actual))
    return sorted(cases, key=lambda c: c.launch_date)
