"""AVM kataloğu komutları.

    # bizim sunucumuzda (internet + pyarrow)
    python -m app.mallprofile cek TR İstanbul                       # hazır kutu
    python -m app.mallprofile cek SA Riyadh --bbox 46.4,24.4,47.0,25.0
    python -m app.mallprofile onayla panel_data/malls/TR/istanbul.json --onaylayan "Adem"
    python -m app.mallprofile listele
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

from .catalog import DEFAULT_DIR, MallStore, catalog_path, city_slug
from .models import MallCatalog
from . import overture
from .tiers import TierMap


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.mallprofile")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cek", help="Overture'dan şehir AVM kataloğu üret (taslak)")
    c.add_argument("ulke")
    c.add_argument("sehir")
    c.add_argument("--bbox", help="xmin,ymin,xmax,ymax (hazır kutu yoksa zorunlu)")
    c.add_argument("--release", default=overture.RELEASE)
    c.add_argument("--parquet", help="önceden indirilmiş yerel parquet (ağa çıkmadan)")
    c.add_argument("--yaricap", type=int, default=overture.RADIUS_M)
    c.add_argument("--klasor", default=str(DEFAULT_DIR))
    o = sub.add_parser("onayla", help="kontrol edilmiş kataloğu onaylı işaretle")
    o.add_argument("dosya")
    o.add_argument("--onaylayan", required=True)
    sub.add_parser("listele")
    a = p.parse_args(argv)

    if a.cmd == "cek":
        key = (a.ulke.upper(), city_slug(a.sehir))
        bbox = tuple(float(x) for x in a.bbox.split(",")) if a.bbox else overture.BBOX.get(key)
        if not bbox or len(bbox) != 4:
            print(f"{a.sehir} için hazır kutu yok; --bbox xmin,ymin,xmax,ymax ver.", file=sys.stderr)
            return 2
        rows = overture.read_places(bbox, a.release, a.parquet)
        tiers = TierMap.load(Path(__file__).resolve().parents[2] / "panel_data" / "marka_katmanlari.csv")
        cat = overture.build_catalog(rows, a.ulke, a.sehir, bbox, a.release, a.yaricap, tiers=tiers)
        path = catalog_path(Path(a.klasor), a.ulke, a.sehir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(cat.model_dump_json(exclude_none=True), encoding="utf-8")
        dense = sum(m.dense_area for m in cat.malls)
        print(f"{path}: {len(cat.malls)} AVM ({dense} tanesi yoğun çarşı bölgesinde), taslak. "
              "Kontrol et, sonra: python -m app.mallprofile onayla ...")
        return 0
    if a.cmd == "onayla":
        path = Path(a.dosya)
        cat = MallCatalog.model_validate(json.loads(path.read_text(encoding="utf-8")))
        cat.verified, cat.approved_by, cat.approved_at = True, a.onaylayan, date.today()
        path.write_text(cat.model_dump_json(exclude_none=True), encoding="utf-8")
        print(f"{path}: onaylandı ({a.onaylayan}).")
        return 0
    for row in MallStore().cities():
        print(f"{row['ulke']} {row['sehir']}: {row['mall_count']} AVM, {'onaylı' if row['verified'] else 'taslak'}, "
              f"{row['source']['dataset']} {row['source']['release']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
