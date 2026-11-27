import copy
import shutil

import numpy as np
import pandas as pd
import pytest

from tahmin.eritme import EritmeAyar, _poisson_fe, eritme_onerisi, fiyat_oranlari, projeksiyon_testi
from tahmin.eritme_rapor import eritme_raporu
from tahmin.hazirlik import panel_kur
from tahmin.sentetik import BOLGE_KAMPANYA_ESNEKLIK
from tahmin.yukleme import yukle

AYAR = EritmeAyar(bootstrap=4)


@pytest.fixture(scope="module")
def veri(sentetik_klasor):
    vs = yukle(sentetik_klasor)
    panel = panel_kur(vs)
    g = fiyat_oranlari(vs, panel)
    sz = panel.sezonlar.sort_values("baslangic")
    tarih = sz.iloc[-1]["baslangic"] + pd.Timedelta(weeks=14) - pd.Timedelta(days=1)  # son sezonun 14. haftası sonu
    return vs, panel, g, tarih


def test_poisson_sabit_etkili_esneklik_geri_bulunur():
    rng = np.random.default_rng(1)
    n_a, n_w = 300, 20
    a_id = np.repeat(np.arange(n_a), n_w)
    w_id = np.tile(np.arange(n_w), n_a)
    a = rng.normal(1, 0.7, n_a)
    w = rng.normal(0, 0.3, n_w)
    # kötü satan ürüne daha çok indirim (seçim yanlılığı): FE olmadan esneklik yanlı çıkar
    indirim = (rng.random(n_a * n_w) < 0.2 + 0.3 * (a[a_id] < 1)) * rng.choice([0.2, 0.3, 0.5], n_a * n_w)
    x = np.log(1 - indirim)
    y = rng.poisson(np.exp(a[a_id] + w[w_id] - 1.6 * x))
    beta = _poisson_fe(y.astype(float), x, a_id, w_id, np.zeros_like(a_id))
    assert abs(-beta[0] - 1.6) < 0.1


def test_fiyat_orani_kampanya_haftalarini_gorur(veri):
    vs, panel, g, _ = veri
    assert g["oran"].between(0.05, 1.0).all()
    assert (g["kampanya_orani"] > 0).any() and (g["raf_orani"] <= 1).all()
    # satış satırındaki net/brüt ile hesaplanan oran aynı yöne gider
    s = vs["satislar"]
    sat = s[s["brut_tutar"] > 0]
    assert (sat["net_tutar"] <= sat["brut_tutar"] + 1e-6).all()
    assert g.loc[g["kampanya_orani"] > 0, "oran"].mean() < g.loc[g["kampanya_orani"] == 0, "oran"].mean()


def test_oneri_tutarli_ve_kurala_uygun(veri):
    vs, panel, g, tarih = veri
    r = eritme_onerisi(vs, panel, tarih, AYAR, g=g)
    u, sec = r.urunler, r.secenekler
    assert len(u) > 0 and len(sec) == len(u) * len(AYAR.indirimler)
    assert set(r.esneklik["kaynak"]) == {"ERP kalibrasyonu"}
    for _, x in sec.groupby("ur_id"):
        x = x.sort_values("ek_indirim")
        assert (np.diff(x["satis_p50"]) >= -1e-9).all()       # indirim arttıkça satış azalmaz
        assert (np.diff(x["brut_marj"].dropna()) <= 1e-9).all()  # marj azalır
        assert (x["satis_alt"] <= x["satis_p50"] + 1e-9).all() and (x["satis_p50"] <= x["satis_ust"] + 1e-9).all()
    st = sec.merge(u[["ur_id", "eldeki_stok", "onerilen_ek_indirim"]], on="ur_id")
    assert np.allclose(st["kalan_p50"], st["eldeki_stok"] - st["satis_p50"])
    assert (st["satis_p50"] <= st["eldeki_stok"] + 1e-6).all()
    on = st[np.isclose(st["ek_indirim"], st["onerilen_ek_indirim"])]
    # önerilen indirim ya marj kuralına uyar ya da hiç ek indirim değildir
    assert (on["kurala_uygun"] | (on["ek_indirim"] == 0)).all()


def test_gelecek_veri_kullanilmaz(veri, sentetik_klasor, tmp_path):
    vs, panel, g, tarih = veri
    r = eritme_onerisi(vs, panel, tarih, AYAR, g=g, kalibrasyon=False)
    klasor = tmp_path / "kesik"
    shutil.copytree(sentetik_klasor, klasor, ignore=shutil.ignore_patterns("_sentetik*", "gorseller"))
    for ad, kol in (("satislar", "tarih"), ("stok", "tarih"), ("iadeler", "tarih"), ("sevkiyatlar", "tarih")):
        p = klasor / f"{ad}.csv"
        d = pd.read_csv(p, dtype=str)
        d[pd.to_datetime(d[kol]) <= tarih].to_csv(p, index=False)
    vs2 = yukle(klasor)
    r2 = eritme_onerisi(vs2, panel_kur(vs2), tarih, AYAR, kalibrasyon=False)
    a = r.urunler.set_index("ur_id").sort_index()
    b = r2.urunler.set_index("ur_id").sort_index()
    assert list(a.index) == list(b.index)
    assert np.allclose(a["eldeki_stok"], b["eldeki_stok"])
    # panelin beden payları (stok bitişi düzeltmesinde ağırlık) tüm satış geçmişinden kurulur; bu küçük fark dışında aynı.
    # Gölge modda veri zaten bugünle biter, bu fark yalnızca geriye dönük çalıştırmada oluşur.
    assert np.allclose(a["guncel_hiz"], b["guncel_hiz"], rtol=0.02)
    assert (a["onerilen_ek_indirim"] == b["onerilen_ek_indirim"]).mean() >= 0.9


def test_ticari_hedefler_uygulanir(veri):
    vs, panel, g, tarih = veri
    T = panel.sezonlar.sort_values("baslangic").iloc[-1]["sezon_kodu"]
    hedef = pd.DataFrame([dict(sezon_kodu=T, kapsam_tipi="genel", kapsam_kodu=None, hedef_brut_marj=0.95, hedef_bitis_tarihi=None,
                               taban_fiyat=None, kalan_deger_orani=0.2, indirim_basamaklari="0.25,0.5")])
    vs2 = copy.copy(vs)
    vs2.tablolar = {**vs.tablolar, "ticari_hedefler": hedef}
    r = eritme_onerisi(vs2, panel, tarih, AYAR, g=g, kalibrasyon=False)
    u = r.urunler
    assert (u["hedef_brut_marj"] == 0.95).all() and (u["kalan_deger_orani"] == 0.2).all()
    assert (u["onerilen_ek_indirim"] == 0).all()  # %95 marjı tutan indirim yok
    assert set(r.secenekler["ek_indirim"]) == {0.0, 0.25, 0.5}


def test_rapor_ve_geriye_kontrol(veri, tmp_path):
    vs, panel, g, tarih = veri
    r = eritme_onerisi(vs, panel, tarih, AYAR, g=g)
    o = projeksiyon_testi(r, g, vs)
    assert len(o) and (o["alt"] <= o["tahmin"] + 1e-9).all() and (o["tahmin"] <= o["ust"] + 1e-9).all()
    yol = eritme_raporu(r, panel, g, vs, tmp_path / "e", "test", e_gercek=BOLGE_KAMPANYA_ESNEKLIK)
    md = yol.read_text(encoding="utf-8")
    for baslik in ("## İndirim satışı ne kadar artırıyor?", "## Öncelikli ürünler", "## Geriye dönük kontrol", "## Sentetik kontrol", "SENTETİK VERİ"):
        assert baslik in md
    for f in ("eritme_urunler.csv", "eritme_secenekler.csv", "eritme_esneklik.csv", "eritme_sentetik_karsi_olgu.csv"):
        assert (tmp_path / "e" / f).exists()


def test_fiyat_farki_sabit_etkilerle_aciklaniyorsa_olculmez():
    # fiyat yalnızca haftaya bağlı (bütün ürünlerde aynı anda indirim): esneklik ölçülemez, sıfır dönmemeli
    from tahmin.eritme import esneklik_ogren

    rng = np.random.default_rng(2)
    satir = []
    for u in range(40):
        for m in range(3):
            for h in range(20):
                satir.append(dict(sezon_kodu="2023-SS", ur_id=f"U{u}", magaza_kodu=f"M{m}", hafta_no=h, A=1.0, ulke="TR", bolge="TR",
                                  kategori="gomlek", oran=0.7 if h >= 15 else 1.0, satis=rng.poisson(3)))
    e = esneklik_ogren(pd.DataFrame(satir), ["2023-SS"], EritmeAyar(bootstrap=2))
    assert e.empty
