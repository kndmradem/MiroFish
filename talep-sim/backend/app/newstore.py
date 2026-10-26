"""Yeni bölgede mağaza öngörüsü: aday lokasyonun dış verisini müşterinin benzer mevcut mağazalarıyla eşleştirir.

Yöntem (benzerlik tahmini, nedensel model değil):
1. Mevcut fiziksel mağazaların olgun dönem (açılıştan 180 gün sonrası) yıllık cirosu ve m² başı cirosu ERP
   CSV'lerinden (magazalar, satislar, doviz_kurlari) hesaplanır.
2. Her mağazanın şehrine lokasyon profili (nüfus, kişi başı gelir, alım gücü, turist, AVM ziyaretçisi) eşlenir;
   özellikler mevcut mağazalar üzerinden standartlaştırılır, aday ile uzaklık ölçülür (aynı lokasyon tipi öncelikli).
3. En yakın k analogun m² başı cirosunun benzerlik ağırlıklı medyanı × aday metrekare = tahmin; aralık ağırlıklı
   %10-%90 dilimleri. Dışa değerleme, az analog ve "bu bölgede kendi veri yok" durumunda aralık genişletilir.

Dış veri ve kaynakları lokasyon profili dosyasındadır; kaynaksız değerler uyarı olarak gösterilir.
"""
import csv
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field

from .panel.erp_cases import COUNTRY_REGION, _Fx, _rows

FEATURES = ("nufus", "kisi_basi_gelir_usd", "alim_gucu_endeksi", "turist_yillik", "avm_ziyaretci_yillik")
LOG_FEATURES = {"nufus", "turist_yillik", "avm_ziyaretci_yillik"}
FEATURE_TR = {"nufus": "nüfus", "kisi_basi_gelir_usd": "kişi başı gelir", "alim_gucu_endeksi": "alım gücü endeksi",
              "turist_yillik": "yıllık turist", "avm_ziyaretci_yillik": "AVM yıllık ziyaretçi"}
MATURE_AFTER_DAYS = 180
MIN_MATURE_DAYS = 120
TYPE_PENALTY = 0.75
REGION_PENALTY = 0.3   # aynı bölgedeki mağaza, eşit benzerlikte öne geçer (kültür, iklim, fiyat düzeyi)


class LocationProfile(BaseModel):
    ulke: str
    sehir: str
    nufus: Optional[float] = None
    kisi_basi_gelir_usd: Optional[float] = None
    alim_gucu_endeksi: Optional[float] = None
    turist_yillik: Optional[float] = None
    avm_ziyaretci_yillik: Optional[float] = None
    kaynak_url: str = ""
    tarih: Optional[date] = None

    @property
    def key(self) -> Tuple[str, str]:
        return self.ulke.upper(), _norm(self.sehir)


class Candidate(BaseModel):
    ulke: str = Field(..., examples=["SA"])
    sehir: str = Field(..., examples=["Jeddah"])
    lokasyon_tipi: Literal["avm", "cadde", "outlet"] = "avm"
    metrekare: float = Field(..., gt=20, lt=20000)
    profil: Optional[LocationProfile] = Field(None, description="Verilirse dosyadaki profil yerine kullanılır")


class Analog(BaseModel):
    magaza: str
    sehir: str
    ulke: str
    lokasyon_tipi: str
    metrekare: float
    yillik_ciro_usd: float
    m2_ciro_usd: float
    benzerlik: float = Field(..., description="0-1, ağırlık olarak kullanılır")
    kapandi: bool = False


class NewStoreEstimate(BaseModel):
    region: Optional[str]
    annual_revenue_usd: float
    low_usd: float
    high_usd: float
    per_sqm_usd: float
    confidence: Literal["düşük", "orta", "yüksek"]
    own_data: Literal["şehir", "ülke", "bölge", "yok"]
    warnings: List[str]
    analogs: List[Analog]
    features_used: List[str]
    profile_source: str = ""
    assumptions: List[str] = []
    basis: str = ("benzer mağaza eşleştirmesi: tahmin müşterinin mevcut mağazalarının cirosundan, dış veri lokasyon "
                  "profilinden; ölçülmüş satış değil")


@dataclass
class StoreStat:
    code: str
    ulke: str
    sehir: str
    tip: str
    sqm: float
    annual_usd: float
    closed: bool = False

    @property
    def per_sqm(self) -> float:
        return self.annual_usd / self.sqm


def _norm(s: str) -> str:
    return (s or "").strip().lower().translate(str.maketrans("ıİşŞğĞüÜöÖçÇ", "iissgguuoocc"))


def load_profiles(path: Path) -> Dict[Tuple[str, str], LocationProfile]:
    out = {}
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            clean = {k: (v if v not in ("", None) else None) for k, v in row.items() if k}
            p = LocationProfile.model_validate({**clean, "kaynak_url": clean.get("kaynak_url") or ""})
            out[p.key] = p
    return out


def store_stats(erp_dir: Path, fixed_rates: Optional[Dict[str, float]] = None) -> Tuple[List[StoreStat], List[str]]:
    """Fiziksel mağazaların olgun dönem yıllık cirosu (USD) ve hesaba katılamayan mağaza notları.

    `fixed_rates`: doviz_kurlari.csv'de olmayan para birimleri için sabit kur (1 birim = ? TRY), ör. {"USD": 42}.
    """
    erp_dir = Path(erp_dir)
    fx = _Fx(_rows(erp_dir, "doviz_kurlari", optional=True))
    for cur, rate in (fixed_rates or {}).items():
        fx.series.setdefault(cur.upper(), [(date.min, float(rate))])
    stores = {m["magaza_kodu"]: m for m in _rows(erp_dir, "magazalar")
              if (m.get("kanal") or "") != "online" and (m.get("lokasyon_tipi") or "") != "online"
              and m.get("metrekare")}  # kapanan mağazalar da girer: dışarıda bırakmak tahmini iyimser yapar
    revenue: Dict[str, float] = defaultdict(float)
    first: Dict[str, date] = {}
    last: Dict[str, date] = {}
    for s in _rows(erp_dir, "satislar"):
        m = stores.get(s["magaza_kodu"])
        if m is None:
            continue
        day = date.fromisoformat(s["tarih"])
        mature = date.fromisoformat(m["acilis_tarihi"]) + timedelta(days=MATURE_AFTER_DAYS)
        if day < mature:
            continue
        usd = fx.to_usd(float(s["net_tutar"] or 0), m.get("para_birimi") or "TRY", day)
        if usd is None:
            continue
        code = s["magaza_kodu"]
        revenue[code] += usd
        first[code] = min(first.get(code, day), day)
        last[code] = max(last.get(code, day), day)
    out, notes = [], []
    no_fx = sorted({f"{m['magaza_kodu']} ({m.get('para_birimi')})" for m in stores.values()
                    if fx.try_of(m.get("para_birimi") or "TRY", date.today()) is None or fx.try_of("USD", date.today()) is None})
    if no_fx:
        notes.append("Kur bilgisi olmadığı için hesaba katılamayan mağazalar: " + ", ".join(no_fx)
                     + ". doviz_kurlari.csv'yi doldur ya da sabit kur ver.")
    young = sorted(set(stores) - set(revenue) - {x.split(" ")[0] for x in no_fx})
    for code, rev in revenue.items():
        days = (last[code] - first[code]).days + 1
        if days < MIN_MATURE_DAYS or rev <= 0:
            young.append(code)
            continue
        m = stores[code]
        out.append(StoreStat(code, m["ulke"].upper(), m["sehir"], m.get("lokasyon_tipi") or "avm",
                             float(m["metrekare"]), rev / days * 365, bool(m.get("kapanis_tarihi"))))
    if young:
        notes.append("Olgun satış dönemi yetersiz olduğu için dışarıda kalan mağazalar: " + ", ".join(sorted(young)) + ".")
    return out, notes


def _value(p: Optional[LocationProfile], f: str) -> Optional[float]:
    v = getattr(p, f) if p else None
    if v is None or v < 0:
        return None
    return math.log1p(v) if f in LOG_FEATURES else float(v)


def _wquantile(values: List[float], weights: List[float], q: float) -> float:
    pairs = sorted(zip(values, weights))
    total = sum(w for _, w in pairs)
    acc = 0.0
    for v, w in pairs:
        acc += w
        if acc >= q * total:
            return v
    return pairs[-1][0]


def estimate(cand: Candidate, stats: List[StoreStat], profiles: Dict[Tuple[str, str], LocationProfile],
             k: int = 5, data_notes: Optional[List[str]] = None) -> NewStoreEstimate:
    if not stats:
        raise ValueError("Mevcut mağaza satışı bulunamadı (en az 120 günlük olgun dönem gerekli)")
    warnings: List[str] = list(data_notes or [])
    prof = cand.profil or profiles.get((cand.ulke.upper(), _norm(cand.sehir)))
    if prof is None:
        warnings.append(f"{cand.sehir} için lokasyon profili (dış veri) yok; eşleştirme yalnızca lokasyon tipine dayanıyor.")
    elif not prof.kaynak_url:
        warnings.append(f"{cand.sehir} lokasyon profilinin kaynağı belirtilmemiş; dış veri doğrulanmamış.")

    store_prof = {s.code: profiles.get((s.ulke, _norm(s.sehir))) for s in stats}
    unsourced = sorted({s.sehir for s in stats if store_prof[s.code] is None})
    if unsourced:
        warnings.append("Profili olmayan mağaza şehirleri: " + ", ".join(unsourced) + " (bu mağazalar yalnızca tiple eşleşti).")

    # standartlaştırma: mevcut mağazaların dağılımına göre
    scale: Dict[str, Tuple[float, float, float, float]] = {}
    for f in FEATURES:
        vals = [v for s in stats if (v := _value(store_prof[s.code], f)) is not None]
        if len(vals) >= 2:
            mu = sum(vals) / len(vals)
            sd = max(1e-6, math.sqrt(sum((v - mu) ** 2 for v in vals) / len(vals)))
            scale[f] = (mu, sd, min(vals), max(vals))
    cz = {f: (_value(prof, f) - mu) / sd for f, (mu, sd, _, _) in scale.items() if _value(prof, f) is not None}
    used = [f for f in FEATURES if f in cz]
    missing = [FEATURE_TR[f] for f in FEATURES if f not in cz]
    if missing and prof is not None:
        warnings.append("Karşılaştırmaya girmeyen dış veri: " + ", ".join(missing) + ".")

    # dışa değerleme: aday, mevcut mağazaların aralığının ne kadar dışında (standart sapma cinsinden)
    outside = 0.0
    for f in used:
        mu, sd, lo, hi = scale[f]
        v = _value(prof, f)
        gap = max(0.0, (lo - v) / sd, (v - hi) / sd)
        if gap > 0.25:
            warnings.append(f"Adayın {FEATURE_TR[f]} değeri mevcut mağazaların aralığının dışında; tahmin dışa değerleme içeriyor.")
        outside = max(outside, gap)

    region = COUNTRY_REGION.get(cand.ulke.upper())
    rows = []
    for s in stats:
        sp = store_prof[s.code]
        diffs = [(cz[f] - (_value(sp, f) - scale[f][0]) / scale[f][1]) ** 2
                 for f in used if _value(sp, f) is not None]
        d = math.sqrt(sum(diffs) / len(diffs)) if diffs else 1.5
        d += 0 if s.tip == cand.lokasyon_tipi else TYPE_PENALTY
        d += 0 if region and COUNTRY_REGION.get(s.ulke) == region else REGION_PENALTY
        rows.append((d, s))
    rows.sort(key=lambda r: r[0])
    near = rows[: max(1, k)]
    weights = [1 / (0.25 + d) for d, _ in near]
    per = [s.per_sqm for _, s in near]
    mid = _wquantile(per, weights, 0.5)
    p10, p90 = _wquantile(per, weights, 0.1), _wquantile(per, weights, 0.9)

    if any(s.ulke == cand.ulke.upper() and _norm(s.sehir) == _norm(cand.sehir) for s in stats):
        own = "şehir"
    elif any(s.ulke == cand.ulke.upper() for s in stats):
        own = "ülke"
    elif region and any(COUNTRY_REGION.get(s.ulke) == region for s in stats):
        own = "bölge"
    else:
        own = "yok"
    if own == "yok":
        warnings.insert(0, f"Bu bölgede ({region or cand.ulke}) kendi mağaza verin yok: tahmin tamamen başka bölgelerdeki "
                           "mağazalardan aktarılıyor, belirsizlik yüksek.")
    elif own == "bölge":
        warnings.insert(0, f"{cand.ulke} ülkesinde kendi mağaza verin yok; aynı bölgedeki ({region}) diğer ülkelerden aktarılıyor.")
    if len(stats) < 10:
        warnings.append(f"Yalnızca {len(stats)} mağazanın olgun satışı var; aralık geniş okunmalı.")
    dmin = near[0][0]
    closed = [s.code for _, s in near if s.closed]
    if closed:
        warnings.append("Benzer mağazalar arasında kapanmış olan var (" + ", ".join(closed) + "); bu lokasyon tipinin riskine işaret edebilir.")

    widen = (1 + 0.4 * min(outside, 3) + {"yok": 0.5, "bölge": 0.25, "ülke": 0.1, "şehir": 0.0}[own]
             + (0.3 if len(near) < 3 else 0) + 0.3 * max(0.0, dmin - 1))
    lo_ratio = min(p10 / mid, 0.8) ** widen
    hi_ratio = max(p90 / mid, 1.25) ** widen
    annual = mid * cand.metrekare

    score = 2
    if own in ("yok", "bölge"):
        score -= 1
    if outside > 0.25 or dmin > 1.2 or prof is None:
        score -= 1
    if len(stats) < 10 or (prof is not None and not prof.kaynak_url):
        score -= 1
    if own == "yok":
        score = min(score, 0)
    level = "düşük" if score <= 0 else "orta" if score == 1 else "yüksek"

    sim = [math.exp(-d) for d, _ in near]
    return NewStoreEstimate(
        region=region, annual_revenue_usd=round(annual), low_usd=round(annual * lo_ratio),
        high_usd=round(annual * hi_ratio), per_sqm_usd=round(mid, 1), confidence=level, own_data=own,
        warnings=warnings,
        analogs=[Analog(magaza=s.code, sehir=s.sehir, ulke=s.ulke, lokasyon_tipi=s.tip, metrekare=s.sqm,
                        yillik_ciro_usd=round(s.annual_usd), m2_ciro_usd=round(s.per_sqm, 1), benzerlik=round(w, 2),
                        kapandi=s.closed)
                 for (d, s), w in zip(near, sim)],
        features_used=[FEATURE_TR[f] for f in used],
        profile_source=(f"{prof.kaynak_url or 'kaynak yok'}" + (f" ({prof.tarih.isoformat()})" if prof and prof.tarih else ""))
        if prof else "profil yok",
        assumptions=[f"Olgun dönem: açılıştan {MATURE_AFTER_DAYS} gün sonrası; yıllık ciro bu dönemden yıllıklandırıldı.",
                     "Ciro m² ile doğrusal ölçeklenir varsayıldı; çok büyük/küçük mağazada geçerli olmayabilir.",
                     "Rakip yoğunluğu, kesin konum, kira ve marka bilinirliği modele girmedi.",
                     "Tutarlar doviz_kurlari ile USD'ye çevrildi; kur yoksa sabit kur varsayıldı."])
