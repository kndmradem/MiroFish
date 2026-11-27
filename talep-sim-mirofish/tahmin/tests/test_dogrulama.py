import pandas as pd

from tahmin.dogrulama import HATA, UYARI, dogrula, hata_var
from tahmin.yukleme import yukle


def _yaz(klasor, ad, satirlar):
    pd.DataFrame(satirlar).to_csv(klasor / f"{ad}.csv", index=False)


def _kucuk_veri(klasor):
    _yaz(klasor, "urunler", [dict(urun_kodu="U1", sezon_kodu="2024-SS", kategori="tisort", cinsiyet="kadin", birim_maliyet=10, maliyet_para_birimi="TRY")])
    _yaz(klasor, "skular", [dict(sku_kodu="U1-SYH-M", urun_kodu="U1", renk_kodu="SYH", beden="M")])
    _yaz(klasor, "magazalar", [dict(magaza_kodu="M1", kanal="magaza", ulke="TR", sehir="Istanbul", acilis_tarihi="2020-01-01", para_birimi="TRY")])
    _yaz(klasor, "fiyat_gecmisi", [dict(urun_kodu="U1", kapsam_tipi="ulke", kapsam_kodu="TR", para_birimi="TRY", liste_fiyati=30, baslangic_tarihi="2024-02-05")])
    _yaz(klasor, "satin_alma_siparisleri", [dict(siparis_no="P1", sku_kodu="U1-SYH-M", siparis_tarihi="2023-11-01", teslim_tarihi="2024-01-20", siparis_adedi=100)])
    _yaz(klasor, "stok", [dict(tarih="2024-02-11", lokasyon_kodu="M1", sku_kodu="U1-SYH-M", eldeki_adet=5)])


def test_temiz_veride_hata_yok(tmp_path):
    _kucuk_veri(tmp_path)
    _yaz(tmp_path, "satislar", [dict(tarih="2024-02-06", magaza_kodu="M1", sku_kodu="U1-SYH-M", adet=2, net_tutar=60)])
    b = dogrula(yukle(tmp_path))
    hatalar = [x for x in b if x.seviye == HATA]
    # tek sezonluk veri geriye dönük test için yetersiz: tek beklenen hata bu
    assert [(x.tablo, x.kontrol) for x in hatalar] == [("urunler", "gecmis")]


def test_hatalar_yakalanir(tmp_path):
    _kucuk_veri(tmp_path)
    _yaz(tmp_path, "satislar", [
        dict(tarih="2024-02-06", magaza_kodu="M1", sku_kodu="U1-SYH-M", adet=2, net_tutar=60),
        dict(tarih="2024-02-06", magaza_kodu="M1", sku_kodu="U1-SYH-M", adet=1, net_tutar=30),  # tekrar eden anahtar
        dict(tarih="2024-02-07", magaza_kodu="M1", sku_kodu="YOK", adet=1, net_tutar=30),        # yetim SKU
        dict(tarih="2024-02-08", magaza_kodu="M1", sku_kodu="U1-SYH-M", adet=-1, net_tutar=30),  # negatif
        dict(tarih="bozuk", magaza_kodu="M1", sku_kodu="U1-SYH-M", adet=1, net_tutar=30),         # tarih okunamıyor
    ])
    (tmp_path / "magazalar.csv").unlink()
    b = dogrula(yukle(tmp_path))
    kontroller = {(x.tablo, x.kontrol) for x in b if x.seviye == HATA}
    assert ("magazalar", "tablo") in kontroller
    assert ("satislar", "anahtar") in kontroller
    assert ("satislar", "referans") in kontroller
    assert ("satislar", "aralik") in kontroller
    assert ("satislar", "tip") in kontroller
    assert any(x.tablo == "urunler" and x.kontrol == "gecmis" and x.seviye == HATA for x in b)


def test_sentetik_veri_temiz(sentetik_klasor):
    b = dogrula(yukle(sentetik_klasor))
    assert not hata_var(b), [x.mesaj for x in b if x.seviye == HATA]
    # küçük sentetik veride küçük bir mağazanın tek tük haftası satışsız geçebilir; diğer uyarılar olmamalı
    assert not [x for x in b if x.seviye == UYARI and x.kontrol != "bosluk"], [x.mesaj for x in b if x.seviye == UYARI]
