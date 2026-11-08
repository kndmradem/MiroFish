import numpy as np

from tahmin.dagitim_test import DagitimAyar, _politika_model, _politika_tek_sefer, _simule
from tahmin.geriye_test import TestAyar, calistir
from tahmin.rapor import rapor_yaz
from tahmin.yukleme import yukle


def test_simulasyon_stok_dengesi():
    rng = np.random.default_rng(0)
    D = rng.poisson(3, (4, 10)).astype(float)
    arz = np.zeros(10)
    arz[0], arz[5] = 60, 20
    for karar in (_politika_tek_sefer(np.ones(4)), _politika_model(np.full((4, 10), 3.0), DagitimAyar())):
        r = _simule(D, arz, karar)
        # arz = satılan + mağazada kalan + depoda kalan; talep = satılan + kaçan
        assert np.isclose(arz.sum(), r["satilan"] + r["magazada_kalan"] + r["depoda_kalan"])
        assert np.isclose(D.sum(), r["satilan"] + r["kacan_satis"])
        assert r["depoda_kalan"] >= 0 and r["kacan_satis"] >= 0


def test_depo_yetmezse_sevk_kisilir():
    D = np.full((3, 4), 10.0)
    arz = np.array([5.0, 0, 0, 0])
    r = _simule(D, arz, lambda k, d: np.full(3, 100.0))
    assert r["satilan"] <= 5 and r["depoda_kalan"] >= 0


def test_sentetik_sevkiyatlar_yaziliyor(sentetik_klasor):
    sv = yukle(sentetik_klasor).get("sevkiyatlar")
    assert sv is not None and len(sv) > 0
    assert (sv["adet"] > 0).all()


def test_dagitim_testi_uctan_uca(sentetik_klasor, tmp_path):
    sonuc = calistir(sentetik_klasor, TestAyar(yontemler=["kategori_ortalamasi", "ozellik_modeli"]))
    oz = sonuc.dagitim["ozet"]
    assert {"gerceklesen", "model", "tek_sefer_esit", "tek_sefer_pay"} <= set(oz["politika"])
    # aynı ürünler, aynı arz ve talep üzerinde kıyas
    assert oz["arz"].nunique() == 1 and oz["talep"].nunique() == 1
    assert np.allclose(oz["arz"], oz["satilan"] + oz["magazada_kalan"] + oz["depoda_kalan"])
    assert (oz.loc[oz["politika"].str.startswith("tek_sefer"), "depoda_kalan"] == 0).all()
    assert oz["karsilanan_talep"].between(0, 1).all()
    yol = rapor_yaz(sonuc, tmp_path / "r", "test")
    assert "## Mağaza dağıtımı ve ikmal" in yol.read_text(encoding="utf-8")
    assert (tmp_path / "r" / "dagitim_ozet.csv").exists()


def test_dagitim_kapatilabilir(sentetik_klasor):
    sonuc = calistir(sentetik_klasor, TestAyar(yontemler=["kategori_ortalamasi"], dagitim=None))
    assert sonuc.dagitim == {}
