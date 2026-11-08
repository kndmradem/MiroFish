import numpy as np
import pandas as pd
import pytest

from tahmin.dogrulama import dogrula, hata_var
from tahmin.hazirlik import panel_kur
from tahmin.kampanya_etki import EtkiAyar, _aralik, _did_log, _Matris, havuz, kampanya_etkisi
from tahmin.kampanya_etki_rapor import etki_raporu
from tahmin.yukleme import yukle


def _tablo(etki: float, rng, n_ur=30, n_mag=4, n_hafta=26, k0=12):
    satir = []
    for grp, carpan in (("a", etki), ("b", 1.0)):
        for u in range(n_ur):
            seviye = rng.gamma(4, 2)
            for m in range(n_mag):
                for h in range(n_hafta):
                    lam = seviye * (1 + 0.02 * h) * (carpan if (grp == "a" and k0 <= h < k0 + 1) else 1.0)
                    satir.append(dict(grp=grp, ur_id=f"{grp}{u}", magaza_kodu=f"M{m}", hafta_no=h, A=1.0, y=float(rng.poisson(lam))))
    return pd.DataFrame(satir)


def test_fark_icinde_fark_bilinen_etkiyi_bulur():
    rng = np.random.default_rng(0)
    d = _tablo(0.75, rng)
    ma, mb = _Matris(d[d["grp"] == "a"], 26), _Matris(d[d["grp"] == "b"], 26)
    nokta = _did_log(ma, mb, list(range(8, 12)), [12], 5, 3)
    assert abs(np.expm1(nokta) - (-0.25)) < 0.06
    plasebo = [_did_log(ma, mb, list(range(k - 4, k)), [k], 5, 3) for k in range(4, 12)]
    v, lo, hi, mde = _aralik(nokta, plasebo)
    assert lo < v < hi and 0 < mde < 0.2
    # olay olmayan haftada etki yok
    assert abs(np.expm1(_did_log(ma, mb, list(range(4, 8)), [8], 5, 3))) < 0.1


def test_havuz_ters_varyans_ortalama():
    o = pd.DataFrame(dict(hafta=[1, 1, 1], rakip_etki=[-0.2, -0.3, -0.1], rakip_alt=[-0.35, -0.4, -0.3], rakip_ust=[-0.05, -0.2, 0.1]))
    h = havuz(o)
    x = h.iloc[0]
    assert x["olay"] == 3 and x["alt"] < x["ortalama_etki"] < x["ust"] and -0.3 < x["ortalama_etki"] < -0.1


def test_sentetik_rakip_tablolari_sozlesmeye_uyar(sentetik_klasor):
    vs = yukle(sentetik_klasor)
    assert len(vs["rakip_kampanyalari"]) and len(vs["kampanya_kararlari"])
    assert set(vs["kampanya_kararlari"]["karar"]) <= {"yapildi", "yapilmadi", "kismen"}
    assert (sentetik_klasor / "_sentetik_rakip_etkisi.csv").exists()
    assert not hata_var(dogrula(vs))
    # yanıt kampanyaları kampanyalar tablosunda ve satışlarda görünüyor
    yanit = set(vs["kampanya_kararlari"]["kampanya_kodu"].dropna()) - {""}
    assert yanit <= set(vs["kampanyalar"]["kampanya_kodu"])
    assert set(vs["satislar"]["kampanya_kodu"].dropna()) & yanit


def test_etki_uctan_uca_ve_temel_dondurulur(sentetik_klasor, tmp_path):
    vs = yukle(sentetik_klasor)
    panel = panel_kur(vs)
    defter = tmp_path / "defter"
    r = kampanya_etkisi(vs, panel, EtkiAyar(bootstrap=20), defter=defter)
    o = r.olaylar
    assert len(o) and set(o["hafta"]) <= {1, 2, 4}
    assert set(o["karar"]) <= {"yapildi", "yapilmadi", "kismen", "isaretlenmedi"}
    ok = o["rakip_alt"].notna()
    assert (o.loc[ok, "rakip_alt"] <= o.loc[ok, "rakip_ust"]).all()
    dosyalar = sorted(defter.glob("temel_*.csv"))
    assert dosyalar
    once = {p.name: p.read_text() for p in dosyalar}
    r2 = kampanya_etkisi(vs, panel, EtkiAyar(bootstrap=20), defter=defter)
    assert {p.name: p.read_text() for p in sorted(defter.glob("temel_*.csv"))} == once
    assert r2.olaylar["temel_durum"].str.startswith("dondurulmuş").all()
    yol = etki_raporu(r, tmp_path / "r", "test", sentetik_gercek=pd.read_csv(sentetik_klasor / "_sentetik_rakip_etkisi.csv"))
    md = yol.read_text(encoding="utf-8")
    assert "## Olay olay: ilk hafta" in md and "Pazar payı" in md and "SENTETİK" in md


def test_rapor_tarihinden_sonrasi_olculmez(sentetik_klasor):
    vs = yukle(sentetik_klasor)
    panel = panel_kur(vs)
    ilk = pd.to_datetime(vs["rakip_kampanyalari"]["baslangic_tarihi"]).min()
    r = kampanya_etkisi(vs, panel, EtkiAyar(bootstrap=5), tarih=ilk + pd.Timedelta(days=3))
    assert r.olaylar.empty


def test_rakip_tablosu_yoksa_bos(sentetik_klasor):
    import copy
    vs = yukle(sentetik_klasor)
    vs2 = copy.copy(vs)
    vs2.tablolar = {k: v for k, v in vs.tablolar.items() if k != "rakip_kampanyalari"}
    r = kampanya_etkisi(vs2, panel_kur(vs2))
    assert r.olaylar.empty and r.notlar
