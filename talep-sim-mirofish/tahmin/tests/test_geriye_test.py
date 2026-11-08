import pandas as pd

from tahmin.__main__ import main
from tahmin.benzerlik import BenzerlikIndeksi
from tahmin.geriye_test import SEVIYE_ANAHTAR, TestAyar, calistir
from tahmin.hazirlik import panel_kur
from tahmin.modeller import YONTEMLER, Baglam
from tahmin.rapor import rapor_yaz
from tahmin.yeni_tasarim import benzer_bul
from tahmin.yukleme import yukle


def test_karar_ani_kurali_gelecek_sezonu_gormez(sentetik_klasor):
    p = panel_kur(yukle(sentetik_klasor))
    b = Baglam(p, BenzerlikIndeksi(p.urunler), karar_oncesi_hafta=16)
    s = p.sezonlar.set_index("sezon_kodu")
    for hedef in s.index:
        kesim = s.at[hedef, "baslangic"] - pd.Timedelta(weeks=16)
        for g in b.gecmis_sezonlar(hedef):
            assert s.at[g, "bitis"] <= kesim
    assert b.gecmis_sezonlar("2025-AW")[-1] == "2024-AW"
    assert "2025-SS" not in b.gecmis_sezonlar("2025-AW")


def test_uctan_uca(sentetik_klasor, tmp_path):
    sonuc = calistir(sentetik_klasor, TestAyar())
    m = sonuc.metrikler
    assert set(m["yontem"]) == set(YONTEMLER)
    assert set(m["seviye"]) == set(SEVIYE_ANAHTAR)
    assert set(m["hedef"]) == {"talep", "satis", "gercek"}
    assert m["wape"].between(0, 5).all()
    assert m["kapsama_80"].between(0, 1).all()
    t = sonuc.tahminler["urun"]
    assert (t["q10"] <= t["q90"]).all()
    yol = rapor_yaz(sonuc, tmp_path / "rapor", "test")
    metin = yol.read_text(encoding="utf-8")
    assert "SENTETİK VERİ" in metin and "## İsabet" in metin
    assert (tmp_path / "rapor" / "benzer_urunler.csv").exists()


def test_yeni_tasarim_benzerleri(sentetik_klasor):
    komsular, bolge = benzer_bul(sentetik_klasor, dict(kategori="tisort", renk_kodu="SYH", sezon_tipi="SS"), k=3)
    assert len(komsular) == 3
    assert (komsular["kategori"] == "tisort").all()
    assert (bolge["magaza_basi_sezon_talebi"] > 0).all()


def test_komut_satiri(sentetik_klasor, tmp_path):
    assert main(["dogrula", str(sentetik_klasor)]) == 0
    assert main(["geriye-test", str(sentetik_klasor), "--cikti", str(tmp_path / "r"), "--yontem", "kategori_ortalamasi", "--yontem", "ozellik_modeli"]) == 0
    assert (tmp_path / "r" / "geriye_donuk_test_raporu.md").exists()
