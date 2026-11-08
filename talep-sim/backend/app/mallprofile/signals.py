"""AVM kiracılarından sinyaller ve panel segment ağırlıklarına dönüşüm.

Sinyal → ağırlık kuralı (kural varsayımı, pilot verisiyle kalibre edilene kadar):
    d = AVM fiyat endeksi − şehrin AVM ortalaması   (ikisi de 0 ekonomik … 1 lüks)
    gelir puanı g: düşük 0, orta-alt 0.25, orta 0.5, orta-üst 0.75, yüksek 1
    çarpan = sınırla(1 + K · d · (g − 0.5), 0.5, 2)       K = 4
Örnek: şehir ortalaması 0.35, AVM 0.75 (d = 0.4) → yüksek gelir ×1.8, düşük gelir ×0.5 (alt sınır).
Bilinen marka sayısı MIN_KNOWN'dan azsa ya da şehir ortalaması yoksa çarpanlar 1'dir (bölge paneli aynen kalır).
"""
from statistics import mean
from typing import Iterable, List, Optional

from .models import CatalogSource, Mall, MallProfile, SegmentShift, Signal, Tenant
from .tiers import TIER_SCORE, TIER_TR, TierMap, known_scores, segment_label

MIN_KNOWN = 6
K = 4.0
CLAMP = (0.5, 2.0)
INCOME_SCORE = {"düşük": 0.0, "orta-alt": 0.25, "orta": 0.5, "orta-üst": 0.75, "yüksek": 1.0}


def price_index(tenants: Iterable[Tenant], tiers: TierMap) -> Optional[float]:
    known = known_scores(tenants, tiers)
    if len(known) < MIN_KNOWN:
        return None
    return round(mean(TIER_SCORE[t] for _, t in known), 3)


def city_index(malls: Iterable[Mall], tiers: TierMap) -> Optional[float]:
    """Şehirdeki AVM'lerin fiyat endeksi ortalaması (yoğun çarşı bölgeleri hariç)."""
    vals = [v for m in malls if not m.dense_area for v in [price_index(m.tenants, tiers)] if v is not None]
    return round(mean(vals), 3) if len(vals) >= 3 else None


def segment_shifts(lib, d: Optional[float]) -> List[SegmentShift]:
    if lib is None:
        return []
    base = [s.weight for s in lib.segments]
    mult = [1.0 if d is None else
            max(CLAMP[0], min(CLAMP[1], 1 + K * d * (INCOME_SCORE.get(s.income_band, 0.5) - 0.5)))
            for s in lib.segments]
    adj = [w * m for w, m in zip(base, mult)]
    tb, ta = sum(base), sum(adj)
    return [SegmentShift(id=s.id, label=s.label, income_band=s.income_band, base_weight=round(b / tb, 3),
                         mall_weight=round(a / ta, 3), multiplier=round(m, 2))
            for s, b, a, m in zip(lib.segments, base, adj, mult)]


def build_profile(*, name: str, ulke: str, sehir: str, region: Optional[str], tenants: List[Tenant],
                  tiers: TierMap, lib=None, city_idx: Optional[float] = None, mall: Optional[Mall] = None,
                  source: Optional[CatalogSource] = None, verified: bool = False, manual: bool = False,
                  brand_tier: Optional[str] = None, visitors: Optional[float] = None,
                  visitors_source: Optional[str] = None) -> MallProfile:
    tenant_basis = "kullanıcı girdisi" if manual else "dış veri"
    known = known_scores(tenants, tiers)
    known_names = {k for k, _ in known}
    unknown = sorted({(t.brand or t.name) for t in tenants
                      if not tiers.match(t.brand, t.name) and (t.brand or manual)})
    tier_counts = {TIER_TR[t]: sum(1 for _, x in known if x == t) for t in TIER_SCORE}
    idx = round(mean(TIER_SCORE[t] for _, t in known), 3) if len(known) >= MIN_KNOWN else None
    warnings: List[str] = []
    signals: List[Signal] = []

    src_note = "" if manual or source is None else f"{source.dataset} {source.release}, {source.retrieved_at}"
    radius = f", AVM noktasına {mall.radius_m} m içinde" if mall else ""
    signals.append(Signal(key="tenants", label="Giyim/ayakkabı/aksesuar mağazası", value=str(len(tenants)),
                          basis=tenant_basis, note=(src_note + radius).strip(", ")))
    signals.append(Signal(key="known", label="Fiyat katmanı bilinen marka", value=f"{len(known)}",
                          basis="kural varsayımı",
                          note="marka → katman eşlemesi marka_katmanlari.csv'den; ölçülmüş değil"))
    if idx is None:
        warnings.append(f"Fiyat katmanı bilinen marka {len(known)} tane (en az {MIN_KNOWN} gerekir): "
                        "AVM fiyat segmenti hesaplanmadı, panel bölge varsayılanıyla kalır.")
        signals.append(Signal(key="segment", label="AVM fiyat segmenti", basis="bilinmiyor",
                              note="yeterli bilinen marka yok"))
    else:
        signals.append(Signal(key="segment", label="AVM fiyat segmenti", value=segment_label(idx),
                              basis="kural varsayımı",
                              note=f"bilinen markaların ortalaması; endeks {idx:.2f} (0 ekonomik … 1 lüks)"))
    d = None
    if idx is not None and city_idx is not None:
        d = idx - city_idx
        word = "üstünde" if d > 0.05 else "altında" if d < -0.05 else "civarında"
        signals.append(Signal(key="vs_city", label="Şehir AVM ortalamasına göre", value=word,
                              basis="kural varsayımı", note=f"şehir ortalaması {city_idx:.2f}"))
    elif idx is not None:
        warnings.append("Bu şehirde karşılaştırılacak yeterli AVM yok: panel ağırlıkları değiştirilmedi.")

    rivals: List[str] = []
    if brand_tier in TIER_SCORE:
        rivals = [k for k, t in known if abs(TIER_SCORE[t] - TIER_SCORE[brand_tier]) <= 0.25]
        signals.append(Signal(key="rivals", label="Aynı/komşu fiyat katmanında rakip", value=str(len(rivals)),
                              basis="kural varsayımı",
                              note=f"markanın katmanı {TIER_TR[brand_tier]}; yalnızca katmanı bilinen markalar sayıldı"))
    if visitors:
        signals.append(Signal(key="visitors", label="Yıllık ziyaretçi", value=f"{visitors:,.0f}".replace(",", "."),
                              basis="kullanıcı girdisi" if manual else "dış veri", note=visitors_source or ""))
    else:
        signals.append(Signal(key="visitors", label="Yıllık ziyaretçi", basis="bilinmiyor",
                              note="kaynaklı beyan yok; tahmin edilmez"))
    signals.append(Signal(key="demography", label="Çevre demografisi", basis="bilinmiyor",
                          note="henüz bağlanmadı; şehir düzeyi persona ağırlıkları kullanılıyor"))

    if mall is not None and mall.dense_area:
        warnings.append(f"AVM çevresinde {mall.apparel_count} giyim mağazası var (çarşı/toptan bölgesi olabilir): "
                        "liste AVM dışındaki mağazaları da içerebilir.")
    if not manual and source is not None and not verified:
        warnings.append("AVM kataloğu henüz bir insan tarafından onaylanmadı (taslak).")
    if lib is None and region:
        warnings.append(f"{region} için persona kütüphanesi bulunamadı: panel etkisi gösterilemiyor.")
    elif region is None:
        warnings.append(f"{ulke} ülkesi bir bölgeye eşlenmemiş: panel etkisi gösterilemiyor.")

    return MallProfile(
        mall_id=mall.id if mall else None, name=name, ulke=ulke, sehir=sehir, region=region, source=source,
        verified=verified, manual=manual, tenant_count=len(tenants),
        known_brands=[{"name": k, "tier": TIER_TR[t]} for k, t in known],
        unknown_brands=[u for u in unknown if u not in known_names][:40], tier_counts=tier_counts,
        price_index=idx, city_price_index=city_idx, price_segment=segment_label(idx), rivals=rivals,
        signals=signals, segments=segment_shifts(lib, d), warnings=warnings)
