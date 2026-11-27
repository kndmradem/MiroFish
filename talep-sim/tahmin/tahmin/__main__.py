"""Komut satırı.

python -m tahmin sozlesme                 # doküman alan listesi + CSV şablonları
python -m tahmin sentetik veri/           # sentetik veri üret
python -m tahmin dogrula veri/            # veri kalitesi raporu
python -m tahmin geriye-test veri/        # geriye dönük test + rapor
python -m tahmin benzer veri/ --kategori gomlek --renk BEJ --gorsel tasarim.jpg
python -m tahmin eritme veri/ --tarih 2025-11-09   # stok eritme önerisi (gölge mod)
python -m tahmin kampanya-etki veri/              # rakip kampanyası ve yanıt etkisi (1/2/4 hafta)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent


def _sozlesme(a) -> int:
    from .sozlesme import TABLOLAR, alan_dokumani, sablon_csv

    docs = Path(a.docs)
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "veri-sozlesmesi-alanlar.md").write_text(alan_dokumani(), encoding="utf-8")
    sab = Path(a.sablonlar)
    sab.mkdir(parents=True, exist_ok=True)
    for t in TABLOLAR:
        (sab / t.dosya_adi).write_text(sablon_csv(t), encoding="utf-8")
    print(f"Yazıldı: {docs / 'veri-sozlesmesi-alanlar.md'} ve {len(TABLOLAR)} şablon ({sab}/)")
    return 0


def _sentetik(a) -> int:
    from .sentetik import SentetikAyar, uret

    ayar = SentetikAyar(tohum=a.tohum, ilk_yil=a.ilk_yil, yil_sayisi=a.yil, model_sayisi=a.model_sayisi, gorsel=not a.gorselsiz)
    uret(a.klasor, ayar)
    print(f"SENTETİK veri yazıldı: {a.klasor} ({ayar.yil_sayisi * 2} sezon, sezon başına {ayar.model_sayisi} model)")
    return 0


def _dogrula(a) -> int:
    from .dogrulama import dogrula, hata_var, rapor_md
    from .yukleme import yukle

    bulgular = dogrula(yukle(a.klasor))
    md = rapor_md(bulgular)
    if a.rapor:
        Path(a.rapor).write_text(md, encoding="utf-8")
        print(f"Rapor: {a.rapor}")
    print(md)
    return 1 if hata_var(bulgular) else 0


def _geriye_test(a) -> int:
    from .dogrulama import dogrula, hata_var, rapor_md
    from .geriye_test import TestAyar, calistir
    from .modeller import YONTEMLER
    from .rapor import rapor_yaz
    from .yukleme import yukle

    bulgular = dogrula(yukle(a.klasor))
    cikti = Path(a.cikti)
    cikti.mkdir(parents=True, exist_ok=True)
    (cikti / "veri_kalitesi.md").write_text(rapor_md(bulgular), encoding="utf-8")
    if hata_var(bulgular) and not a.hatalara_ragmen:
        print(rapor_md(bulgular))
        print("Veri kalitesi hataları var; düzelt ya da --hatalara-ragmen ile çalıştır.", file=sys.stderr)
        return 1
    ayar = TestAyar(karar_oncesi_hafta=a.karar_oncesi_hafta, test_sezonlari=a.test_sezonu or None,
                    gorsel_modeli=a.gorsel_modeli, yontemler=a.yontem or list(YONTEMLER))
    sonuc = calistir(a.klasor, ayar)
    yol = rapor_yaz(sonuc, cikti, veri_adi=str(a.klasor))
    print(f"Rapor: {yol}")
    m = sonuc.metrikler
    print(m[(m["hedef"] == "talep") & (m["seviye"] == "urun")][["test_sezonu", "yontem", "wape", "bias", "kapsama_80"]].round(3).to_string(index=False))
    return 0


def _benzer(a) -> int:
    from .yeni_tasarim import benzer_bul

    ozellik = {k: v for k, v in dict(kategori=a.kategori, cinsiyet=a.cinsiyet, kumas=a.kumas, kalip=a.kalip, desen=a.desen,
                                      yaka=a.yaka, kol_boyu=a.kol_boyu, renk_kodu=a.renk, sezon_tipi=a.sezon_tipi,
                                      goreli_fiyat=a.goreli_fiyat).items() if v is not None}
    komsular, bolge = benzer_bul(a.klasor, ozellik, a.gorsel, k=a.k, gorsel_modeli=a.gorsel_modeli)
    print("En benzer geçmiş ürünler:")
    print(komsular[["sira", "komsu_ur", "komsu_sezon", "benzerlik", "kategori", "kalip", "desen", "renk_kodu", "magaza_basi_talep", "satis"]].round(2).to_string(index=False))
    print("\nBölge başına mağaza başı sezon talebi (komşu ortalaması, aralıksız):")
    print(bolge.round(2).to_string(index=False))
    return 0


def _eritme(a) -> int:
    from .eritme import EritmeAyar, eritme_onerisi, fiyat_oranlari
    from .eritme_rapor import eritme_raporu
    from .hazirlik import panel_kur
    from .yukleme import yukle

    vs = yukle(a.klasor)
    panel = panel_kur(vs)
    ayar = EritmeAyar(hedef_brut_marj=a.hedef_marj, kalan_deger_orani=a.kalan_deger, kdv_orani=a.kdv, oncelik=a.oncelik)
    g = fiyat_oranlari(vs, panel)
    r = eritme_onerisi(vs, panel, a.tarih, ayar, hedef_bitis=a.hedef_bitis, g=g)
    e_gercek = None
    if panel.gercek is not None:
        from .sentetik import BOLGE_KAMPANYA_ESNEKLIK as e_gercek
    yol = eritme_raporu(r, panel, g, vs, a.cikti, veri_adi=str(a.klasor), e_gercek=e_gercek)
    print(f"Rapor: {yol}")
    u = r.urunler
    print(f"{len(u)} model-renk, şişmiş {int(u['sisman'].sum()) if len(u) else 0}, ek indirim önerilen {int((u['onerilen_ek_indirim'] > 0).sum()) if len(u) else 0}")
    return 0


def _kampanya_etki(a) -> int:
    import pandas as pd

    from .hazirlik import panel_kur
    from .kampanya_etki import EtkiAyar, kampanya_etkisi
    from .kampanya_etki_rapor import etki_raporu
    from .yukleme import yukle

    vs = yukle(a.klasor)
    panel = panel_kur(vs)
    r = kampanya_etkisi(vs, panel, EtkiAyar(), tarih=a.tarih, defter=a.defter)
    gercek, e_gercek = None, None
    p = Path(a.klasor) / "_sentetik_rakip_etkisi.csv"
    if p.exists():
        from .sentetik import BOLGE_KAMPANYA_ESNEKLIK as e_gercek
        gercek = pd.read_csv(p)
    yol = etki_raporu(r, a.cikti, veri_adi=str(a.klasor), sentetik_gercek=gercek, e_gercek=e_gercek)
    print(f"Rapor: {yol}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m tahmin", description="ERP verisiyle talep tahmini ve geriye dönük test")
    alt = p.add_subparsers(dest="komut", required=True)

    s = alt.add_parser("sozlesme", help="veri sözleşmesi alan listesi ve CSV şablonlarını üret")
    s.add_argument("--docs", default=str(KOK / "docs"))
    s.add_argument("--sablonlar", default=str(KOK / "sablonlar"))
    s.set_defaults(f=_sozlesme)

    s = alt.add_parser("sentetik", help="SENTETİK veri üret")
    s.add_argument("klasor")
    s.add_argument("--tohum", type=int, default=7)
    s.add_argument("--ilk-yil", type=int, default=2023)
    s.add_argument("--yil", type=int, default=3)
    s.add_argument("--model-sayisi", type=int, default=45)
    s.add_argument("--gorselsiz", action="store_true")
    s.set_defaults(f=_sentetik)

    s = alt.add_parser("dogrula", help="veri kalitesi raporu")
    s.add_argument("klasor")
    s.add_argument("--rapor")
    s.set_defaults(f=_dogrula)

    s = alt.add_parser("geriye-test", help="geriye dönük test ve rapor")
    s.add_argument("klasor")
    s.add_argument("--cikti", default="rapor")
    s.add_argument("--test-sezonu", action="append", help="tekrar edilebilir; varsayılan son sezon")
    s.add_argument("--karar-oncesi-hafta", type=int, default=16)
    s.add_argument("--gorsel-modeli", default="renk_doku", choices=["renk_doku", "clip", "yok"])
    s.add_argument("--yontem", action="append")
    s.add_argument("--hatalara-ragmen", action="store_true")
    s.set_defaults(f=_geriye_test)

    s = alt.add_parser("benzer", help="yeni tasarım için en benzer geçmiş ürünler")
    s.add_argument("klasor")
    for o in ("kategori", "cinsiyet", "kumas", "kalip", "desen", "yaka", "kol-boyu", "renk", "sezon-tipi"):
        s.add_argument(f"--{o}")
    s.add_argument("--goreli-fiyat", type=float)
    s.add_argument("--gorsel")
    s.add_argument("--k", type=int, default=5)
    s.add_argument("--gorsel-modeli", default="renk_doku", choices=["renk_doku", "clip", "yok"])
    s.set_defaults(f=_benzer)

    s = alt.add_parser("eritme", help="stok eritme (indirim) önerisi, gölge mod")
    s.add_argument("klasor")
    s.add_argument("--tarih", required=True, help="öneri tarihi; yalnızca bu güne kadarki veri kullanılır")
    s.add_argument("--hedef-bitis", help="stoğun bitmesi hedeflenen tarih (varsayılan: ticari_hedefler, yoksa sezon sonu)")
    s.add_argument("--hedef-marj", type=float, default=0.35, help="korunacak en düşük brüt marj (ticari_hedefler yoksa)")
    s.add_argument("--kalan-deger", type=float, default=0.5, help="hedef tarihte kalan stoğun maliyete göre geri kazanımı")
    s.add_argument("--kdv", type=float, default=0.10)
    s.add_argument("--oncelik", default="kar", choices=["kar", "tarih"])
    s.add_argument("--cikti", default="rapor_eritme")
    s.set_defaults(f=_eritme)

    s = alt.add_parser("kampanya-etki", help="rakip kampanyası ve bizim yanıtımızın etkisi (gölge mod)")
    s.add_argument("klasor")
    s.add_argument("--tarih", help="rapor günü (varsayılan: son satış günü)")
    s.add_argument("--defter", default="karar_defteri", help="dondurulmuş temel tahminlerin tutulduğu klasör")
    s.add_argument("--cikti", default="rapor_kampanya")
    s.set_defaults(f=_kampanya_etki)

    a = p.parse_args(argv)
    return a.f(a)


if __name__ == "__main__":
    sys.exit(main())
