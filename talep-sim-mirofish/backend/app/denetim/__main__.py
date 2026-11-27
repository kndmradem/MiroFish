"""Mantık denetimi komutları (backend klasöründe çalıştırın).

  python -m app.denetim denetle --koleksiyon 20261112-9624f603      # kayıtlı koleksiyonu denetle
  python -m app.denetim denetle --dosya sonuc.json                  # API'den indirilmiş sonuç
  python -m app.denetim vaka-ekle --koleksiyon <id> --ad bralet-slip --aciklama "farklı kategori eşleşti"
  python -m app.denetim vakalar                                     # bütün regresyon vakalarını çalıştır
  python -m app.denetim ilk-test --excel urunler.xlsx [--gorseller klasor|zip] [--erp klasor] [--motor mock]
  python -m app.denetim kurallar

Çıkış kodu: hata seviyesinde bulgu varsa 1 (kurulum betikleri bunu kullanır).
"""
import argparse
import io
import json
import os
import sys
import zipfile
from pathlib import Path

from . import denetle_koleksiyon, kural_listesi
from .rapor import html_, md


def _store(a):
    from ..collection.store import CollectionStore
    return CollectionStore(a.kok or os.getenv("COLLECTIONS_DIR") or None)


def _fx(col):
    from ..config import settings
    return col.meta.usd_try_rate or settings.usd_try_rate


def _yaz(a, metin_md: str, metin_html: str, veri: dict) -> None:
    print(metin_md)
    if a.cikti:
        d = Path(a.cikti)
        d.mkdir(parents=True, exist_ok=True)
        (d / "denetim-raporu.md").write_text(metin_md, encoding="utf-8")
        (d / "denetim-raporu.html").write_text(metin_html, encoding="utf-8")
        (d / "denetim-raporu.json").write_text(json.dumps(veri, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"Rapor yazıldı: {d}/denetim-raporu.(md|html|json)")


def _denetle(a) -> int:
    if a.dosya:
        rapor = denetle_koleksiyon(json.loads(Path(a.dosya).read_text(encoding="utf-8")))
        ad = Path(a.dosya).name
    else:
        from ..collection.summary import summarize
        st = _store(a)
        col = st.load(a.koleksiyon)
        res = summarize(col, st.results(col.id, [i.sku for i in col.items]), _fx(col), showcase=st.showcase(col.id))
        rapor, ad = res.denetim, col.meta.name
    _yaz(a, md(rapor, f"Mantık denetimi: {ad}"), html_(rapor, f"Mantık denetimi: {ad}"), rapor.model_dump())
    return 1 if rapor.durum == "incelenmeli" else 0


def _vaka_ekle(a) -> int:
    from .vaka import VAKA_DIR, vaka_ekle
    st = _store(a)
    col = st.load(a.koleksiyon)
    bek = []
    for x in a.bekle or []:
        k, _, s = x.partition(":")
        bek.append({"kural": k, **({"seviye": s} if s else {})})
    yol, rapor, eksik = vaka_ekle(st, col.id, a.ad, a.aciklama, _fx(col), bek, anonim=not a.gercek_adlarla,
                                  klasor=Path(a.klasor) if a.klasor else VAKA_DIR)
    print(f"Vaka kaydedildi: {yol}")
    print(f"Bugünkü çıktıda denetim: {rapor.durum} ({rapor.sayilar})")
    for b in rapor.bulgular:
        print(f"  - {b.seviye} / {b.kural}: {b.mesaj}")
    if eksik:
        print("\nDİKKAT: denetim bu vakada beklenen bulguları vermiyor; yeni kural yazılana kadar test başarısız olur:")
        for k in eksik:
            print(f"  - {k}")
    elif not rapor.bulgular:
        print("\nDİKKAT: denetim bu çıktıda hiçbir şey bulmadı. Hatayı yakalayacak kural yazılmalı ve vakanın "
              "'sonuc_beklenen' listesine eklenmeli (ör. --bekle kural_kodu:hata ile yeniden ekleyin).")
    print("\nSonraki adım: dosyayı git'e ekleyin (git add tests/denetim_vakalari). Hata kodda düzelince vakadaki "
          "\"durum\": \"acik\" değerini \"kapali\" yapın; o andan sonra hata geri gelirse test kırılır.")
    return 0


def _vakalar(a) -> int:
    from .vaka import VAKA_DIR, vaka_calistir, vakalar
    kotu = 0
    for ad, v in vakalar(Path(a.klasor) if a.klasor else VAKA_DIR):
        sorun = vaka_calistir(v)
        acik = v.get("durum") == "acik"
        if acik:
            sorun_g = [s for s in sorun if s.startswith("[bugünkü kod]")]
            sorun = [s for s in sorun if not s.startswith("[bugünkü kod]")]
        print(f"{'GEÇTİ' if not sorun else 'KALDI'}  {ad}" + ("  (açık vaka: kod henüz düzeltilmedi)" if acik else ""))
        for s in sorun:
            print(f"    {s}")
        kotu += bool(sorun)
    return 1 if kotu else 0


def _ilk_test(a) -> int:
    from .ilk_test import calistir_sync
    from .. import main as m
    if a.motor == "mock":
        from ..services.engine import MockSimulationEngine
        engine = MockSimulationEngine(latency_s=0)
    else:
        engine = m.get_engine()
    gorseller = []
    if a.gorseller:
        p = Path(a.gorseller)
        if p.suffix.lower() == ".zip":
            with zipfile.ZipFile(p) as z:
                gorseller = [(i.filename, z.read(i)) for i in z.infolist() if not i.is_dir() and "__MACOSX" not in i.filename]
        else:
            gorseller = [(str(f.relative_to(p)), f.read_bytes()) for f in p.rglob("*") if f.is_file()]
    from ..config import settings
    if not a.excel and not a.erp:
        print("--excel ya da --erp gerekli", file=sys.stderr)
        return 2
    ex = Path(a.excel) if a.excel else None
    out = calistir_sync(ex.read_bytes() if ex else None, ex.name if ex else "", gorseller, engine, m.get_profiler(), m.run_prediction,
                        settings.usd_try_rate, ornek=a.ornek, erp_klasor=a.erp, kok=a.kok, bolgeler=a.bolge)
    g = out["genel"]
    not_ = f"{out['kosu_notu']} Süre {out['sure_s']} sn. Motor: {'mock (yalnızca mantık hattı)' if a.motor == 'mock' else settings.sim_engine}."
    _yaz(a, md(g, "İlk veri testi: mantık denetimi", out["parcalar"], not_), html_(g, "İlk veri testi: mantık denetimi", out["parcalar"], not_),
         {"genel": g.model_dump(), "parcalar": {ad: r.model_dump() for ad, r in out["parcalar"]}, "not": not_})
    return 1 if g.durum == "incelenmeli" else 0


def _kurallar(a) -> int:
    for k in kural_listesi():
        print(f"{k['kod']:24} [{', '.join(k['kapsam'])}] {k['baslik']}: {k['aciklama']}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.denetim", description="Mantık denetimi")
    p.add_argument("--kok", help="Koleksiyon klasörü (varsayılan: COLLECTIONS_DIR ya da backend/collections_data)")
    sub = p.add_subparsers(dest="komut", required=True)
    d = sub.add_parser("denetle", help="Kayıtlı koleksiyonu ya da sonuç dosyasını denetle")
    g = d.add_mutually_exclusive_group(required=True)
    g.add_argument("--koleksiyon")
    g.add_argument("--dosya")
    d.add_argument("--cikti", help="Raporların yazılacağı klasör")
    d.set_defaults(fn=_denetle)
    v = sub.add_parser("vaka-ekle", help="Bir koleksiyonu regresyon vakası olarak kaydet (anonim)")
    v.add_argument("--koleksiyon", required=True)
    v.add_argument("--ad", required=True)
    v.add_argument("--aciklama", required=True)
    v.add_argument("--bekle", action="append", help="kural_kodu[:seviye]; boşsa bugünkü hata/uyarılar beklenir")
    v.add_argument("--gercek-adlarla", action="store_true", help="Ürün/marka adlarını anonimleştirme (yalnızca özel depoda)")
    v.add_argument("--klasor")
    v.set_defaults(fn=_vaka_ekle)
    vs = sub.add_parser("vakalar", help="Bütün regresyon vakalarını çalıştır")
    vs.add_argument("--klasor")
    vs.set_defaults(fn=_vakalar)
    i = sub.add_parser("ilk-test", help="Müşteri verisiyle ilk veri testi")
    i.add_argument("--excel", help="Ürün listesi (koleksiyon şablonu, .xlsx ya da .csv); yoksa ERP urunler tablosunun son sezonu")
    i.add_argument("--gorseller", help="Görsel klasörü ya da zip")
    i.add_argument("--erp", help="ERP CSV klasörü (veri sözleşmesi tabloları)")
    i.add_argument("--ornek", type=int, default=6, help="Örnek koşuya alınacak en fazla ürün")
    i.add_argument("--bolge", action="append", help="Örnek koşu bölgeleri (varsayılan: listedeki hedef bölgeler)")
    i.add_argument("--motor", choices=["ayar", "mock"], default="ayar", help="ayar: .env'deki motor; mock: LLM'siz hızlı mantık testi")
    i.add_argument("--cikti")
    i.set_defaults(fn=_ilk_test)
    k = sub.add_parser("kurallar", help="Kural listesini yaz")
    k.set_defaults(fn=_kurallar)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
