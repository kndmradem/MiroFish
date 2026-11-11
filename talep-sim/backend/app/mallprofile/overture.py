"""Overture Maps Places'ten şehir bazında AVM kataloğu üretir (yalnızca bizim sunucumuzda, internet gerekir).

Overture places verisi CDLA-Permissive-2.0 (Meta, Microsoft, Overture), Apache-2.0 (Foursquare) ve CC0
(AllThePlaces) lisanslı kaynaklardan derlenir: saklanabilir ve dağıtılabilir, atıf gerekir.

Yöntem (kural varsayımları, katalogda yazılı):
- AVM: `basic_category == "shopping_mall"`, kayıt güveni >= MIN_CONFIDENCE, kapalı olmayan.
- Kiracı: AVM noktasına RADIUS_M içindeki `fashion_and_apparel_store` mekânları. Overture'da AVM sınırı
  (poligon) yok; yarıçap büyük AVM'de bazı mağazaları kaçırır, sıkışık çarşıda AVM dışını da sayar.
- Adı bilinen bir marka olan "AVM" kayıtları (ör. "Tory Burch") mağazadır, AVM sayılmaz.
- Aynı AVM'nin birden çok kaydı (ör. "Zorlu Center" ve "Zorlu Center Meydan") birleştirilir: DEDUPE_M içinde ve
  adlarında ortak bir özel kelime varsa, ya da SAME_SPOT_M içindeyse. Yan yana iki ayrı AVM (Kanyon ve
  Özdilekpark) bu yüzden ayrı kalır. Temsilci kayıt: adında "AVM/mall/center" geçen, sonra güveni en yüksek olan.
- Yarıçap içinde DENSE_COUNT'tan fazla giyim mağazası varsa ve bunların DENSE_BRANDED'den azı markalıysa
  `dense_area` işaretlenir (çarşı/toptan bölgesi).

pyarrow gerekir (`pip install pyarrow`); müşteri kurulumunda gerekmez.
"""
import math
import os
from collections import defaultdict
from datetime import date
from typing import Dict, Iterable, List, Optional, Sequence

from .models import CatalogSource, Mall, MallCatalog, Tenant
from .tiers import norm_tokens

RELEASE = "2026-10-21.0"
BUCKET = "overturemaps-us-west-2"
MIN_CONFIDENCE = 0.6
RADIUS_M = 200
DEDUPE_M = 250
MIN_TENANTS = 5
DENSE_COUNT = 150
DENSE_BRANDED = 0.3
SAME_SPOT_M = 60
MALL_WORDS = {"avm", "mall", "center", "centre", "alisveris", "merkezi", "shopping", "plaza", "park",
              "galleria", "city", "outlet", "tc", "trts", "the", "of", "and"}
COLUMNS = ["id", "names", "brand", "basic_category", "confidence", "operating_status", "bbox"]

# Hazır şehir kutuları (xmin, ymin, xmax, ymax); başka şehir için --bbox verilir
BBOX = {
    ("TR", "istanbul"): (28.5, 40.8, 29.4, 41.25),
    ("TR", "ankara"): (32.55, 39.8, 33.05, 40.05),
    ("TR", "izmir"): (26.95, 38.3, 27.3, 38.55),
    ("SA", "riyadh"): (46.4, 24.4, 47.0, 25.0),
    ("SA", "jeddah"): (39.05, 21.35, 39.35, 21.8),
    ("AE", "dubai"): (55.05, 24.9, 55.6, 25.35),
    ("KZ", "almaty"): (76.75, 43.15, 77.1, 43.35),
    ("DE", "berlin"): (13.08, 52.33, 13.77, 52.68),
    ("GR", "athens"): (23.6, 37.85, 23.9, 38.1),
}


def read_places(bbox: Sequence[float], release: str = RELEASE, parquet: Optional[str] = None) -> List[dict]:
    import pyarrow.dataset as ds  # noqa: WPS433 (isteğe bağlı bağımlılık)
    import pyarrow.fs as fs

    xmin, ymin, xmax, ymax = bbox
    if parquet:
        d = ds.dataset(parquet, format="parquet")
    else:
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        s3 = fs.S3FileSystem(anonymous=True, region="us-west-2", **({"proxy_options": proxy} if proxy else {}))
        base = f"{BUCKET}/release/{release}/theme=places/type=place/"
        files = [f.path for f in s3.get_file_info(fs.FileSelector(base)) if f.path.endswith(".parquet")]
        d = ds.dataset(files, filesystem=s3, format="parquet")
    F = lambda k: ds.field("bbox", k)  # noqa: E731
    flt = (F("xmin") >= xmin) & (F("xmax") <= xmax) & (F("ymin") >= ymin) & (F("ymax") <= ymax)
    flt = flt & ds.field("basic_category").isin(["shopping_mall", "fashion_and_apparel_store"])
    return d.to_table(columns=COLUMNS, filter=flt).to_pylist()


def _center(r: dict):
    b = r["bbox"]
    return (b["xmin"] + b["xmax"]) / 2, (b["ymin"] + b["ymax"]) / 2


def _dist_m(a, b) -> float:
    dx = (a[0] - b[0]) * 111320 * math.cos(math.radians((a[1] + b[1]) / 2))
    dy = (a[1] - b[1]) * 110540
    return math.hypot(dx, dy)


def _name(r: dict) -> str:
    return ((r.get("names") or {}).get("primary") or "").strip()


def _brand(r: dict) -> Optional[str]:
    b = r.get("brand") or {}
    return ((b.get("names") or {}).get("primary") or "").strip() or None


def build_catalog(rows: Iterable[dict], ulke: str, sehir: str, bbox: Sequence[float], release: str = RELEASE,
                  radius_m: int = RADIUS_M, today: Optional[date] = None, tiers=None) -> MallCatalog:
    rows = list(rows)
    malls = [r for r in rows if r.get("basic_category") == "shopping_mall" and _name(r)
             and (r.get("confidence") or 0) >= MIN_CONFIDENCE and r.get("operating_status") != "permanently_closed"
             and not (tiers is not None and tiers.match(_brand(r), _name(r)))]
    apparel = [r for r in rows if r.get("basic_category") == "fashion_and_apparel_store" and _name(r)]

    cell = 0.005  # ~500 m ızgara
    grid: Dict[tuple, List[dict]] = defaultdict(list)
    for a in apparel:
        x, y = _center(a)
        grid[(int(x / cell), int(y / cell))].append(a)

    def near(c, radius):
        gx, gy = int(c[0] / cell), int(c[1] / cell)
        for i in (-1, 0, 1):
            for j in (-1, 0, 1):
                for a in grid.get((gx + i, gy + j), ()):
                    d = _dist_m(c, _center(a))
                    if d <= radius:
                        yield a, d

    def words(name: str) -> set:
        return {w for w in norm_tokens(name) if w not in MALL_WORDS and len(w) > 2}

    def mallish(r: dict) -> bool:
        return bool(set(norm_tokens(_name(r))) & {"avm", "mall", "center", "centre", "alisveris", "shopping"})

    kept: List[Mall] = []
    centers = []
    for m in sorted(malls, key=lambda r: (not mallish(r), -(r.get("confidence") or 0))):
        c = _center(m)
        dup = next((k for k, kc in zip(kept, centers)
                    if _dist_m(c, kc) <= SAME_SPOT_M
                    or (_dist_m(c, kc) <= DEDUPE_M and words(_name(m)) & set().union(*map(words, [k.name, *k.aliases])))),
                   None)
        if dup is not None:
            if _name(m) not in dup.aliases and _name(m) != dup.name:
                dup.aliases.append(_name(m))
            continue
        tenants = sorted((Tenant(name=_name(a), brand=_brand(a), wikidata=(a.get("brand") or {}).get("wikidata"),
                                 category=a.get("basic_category"), distance_m=int(d))
                          for a, d in near(c, radius_m)), key=lambda t: t.distance_m)
        kept.append(Mall(id=m["id"], name=_name(m), lat=round(c[1], 6), lon=round(c[0], 6),
                         confidence=round(m.get("confidence") or 0, 2), radius_m=radius_m,
                         apparel_count=len(tenants), tenants=tenants, dense_area=len(tenants) > DENSE_COUNT
                         and sum(1 for t in tenants if t.brand) < DENSE_BRANDED * len(tenants)))
        centers.append(c)

    out = [m for m in kept if m.apparel_count >= MIN_TENANTS]
    for m in out:
        if m.dense_area:  # çarşı bölgesinde yüzlerce kayıt: yalnızca markalı olanlar ve en yakın 60 mağaza tutulur
            m.tenants = [t for i, t in enumerate(m.tenants) if t.brand or i < 60]
    return MallCatalog(
        ulke=ulke.upper(), sehir=sehir, bbox=list(bbox),
        source=CatalogSource(dataset="Overture Maps Places", release=release,
                             license="CDLA-Permissive-2.0 / Apache-2.0 / CC0-1.0 (kaynak kaydına göre); atıf: © Overture Maps Foundation",
                             url="https://docs.overturemaps.org/guides/places/", retrieved_at=today or date.today()),
        malls=sorted(out, key=lambda m: -m.apparel_count))
