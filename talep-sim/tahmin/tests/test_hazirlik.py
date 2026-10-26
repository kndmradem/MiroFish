import numpy as np
import pandas as pd

from tahmin.hazirlik import magaza_kumeleri, panel_kur
from tahmin.yukleme import yukle


def _yaz(klasor, ad, satirlar):
    pd.DataFrame(satirlar).to_csv(klasor / f"{ad}.csv", index=False)


def test_stok_bitisi_haftalari_talep_olarak_doldurulur(tmp_path):
    """10 hafta: ilk 5 hafta stokta, haftada 10 satış; sonra stok bitiyor, satış sıfır."""
    bas = pd.Timestamp("2024-02-05")
    _yaz(tmp_path, "urunler", [dict(urun_kodu="U1", sezon_kodu="2024-SS", kategori="tisort", cinsiyet="kadin", birim_maliyet=10,
                                    maliyet_para_birimi="TRY", ilk_satis_tarihi=bas.date())])
    _yaz(tmp_path, "skular", [dict(sku_kodu="U1-SYH-M", urun_kodu="U1", renk_kodu="SYH", beden="M")])
    _yaz(tmp_path, "magazalar", [dict(magaza_kodu="M1", kanal="magaza", ulke="TR", sehir="Istanbul", acilis_tarihi="2020-01-01", para_birimi="TRY")])
    satis, stok = [], []
    for k in range(10):
        pazartesi = bas + pd.Timedelta(weeks=k)
        if k < 5:
            satis.append(dict(tarih=pazartesi.date(), magaza_kodu="M1", sku_kodu="U1-SYH-M", adet=10, net_tutar=100))
        stok.append(dict(tarih=(pazartesi + pd.Timedelta(days=6)).date(), lokasyon_kodu="M1", sku_kodu="U1-SYH-M", eldeki_adet=5 if k < 4 else 0))
    _yaz(tmp_path, "satislar", satis)
    _yaz(tmp_path, "stok", stok)
    p = panel_kur(yukle(tmp_path), ufuk=10)
    hw = p.haftalik.sort_values("hafta_no")
    assert hw["satis"].sum() == 50
    # 4. hafta: stok bitti ama satış vardı -> kısmi; 5-9: tamamen stoksuz -> talep tahmin edilir
    assert (hw.loc[hw["hafta_no"] >= 5, "talep"] > 5).all()
    assert hw["talep"].sum() > 90
    assert hw.loc[hw["hafta_no"] >= 5, "sansurlu"].all()


def test_magaza_kumeleri():
    mag = pd.DataFrame(dict(
        magaza_kodu=["a", "b", "c", "d", "e", "f"], ulke=["TR", "TR", "TR", "TR", "TR", "DE"],
        kanal=["magaza"] * 4 + ["online", "magaza"], metrekare=[100, 200, 300, 400, np.nan, 300]))
    k = magaza_kumeleri(mag).set_index("magaza_kodu")["kume"]
    assert k["a"] == "TR-kucuk" and k["d"] == "TR-buyuk"
    assert k["e"] == "TR-online" and k["f"] == "EU-magaza"


def test_duzeltilmis_talep_gercege_satistan_yakin(sentetik_klasor):
    p = panel_kur(yukle(sentetik_klasor))
    m = p.haftalik.merge(p.gercek, on=["sezon_kodu", "ur_id", "magaza_kodu", "hafta_no"])
    t = m.groupby(["sezon_kodu", "ur_id"])[["satis", "talep", "gercek_talep"]].sum()
    hata_satis = (t["satis"] - t["gercek_talep"]).abs().sum()
    hata_talep = (t["talep"] - t["gercek_talep"]).abs().sum()
    assert hata_talep < 0.6 * hata_satis
    assert len(m) == len(p.haftalik)
