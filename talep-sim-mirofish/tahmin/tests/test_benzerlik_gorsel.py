import numpy as np
import pandas as pd
from PIL import Image

from tahmin.benzerlik import BenzerlikIndeksi
from tahmin.gorsel import RenkDokuGomucu, gomucu_sec
from tahmin.hazirlik import OZELLIKLER


def _urun(sezon, ur, **oz):
    d = {o: "x" for o in OZELLIKLER}
    d.update(sezon_kodu=sezon, ur_id=ur, urun_kodu=ur.split("|")[0], goreli_fiyat=1.0)
    d.update(oz)
    return d


def test_en_benzer_ayni_ozellikli_urun():
    u = pd.DataFrame([
        _urun("Y", "Y1|SYH", kategori="gomlek", renk_kodu="SYH", kalip="oversize"),
        _urun("G", "A|SYH", kategori="gomlek", renk_kodu="SYH", kalip="oversize"),
        _urun("G", "B|BYZ", kategori="gomlek", renk_kodu="BYZ", kalip="slim"),
        _urun("G", "C|SYH", kategori="mont", renk_kodu="SYH", kalip="oversize"),
    ])
    ix = BenzerlikIndeksi(u)
    k = ix.komsular(u.iloc[[0]], u.iloc[1:], k=3)
    assert list(k["komsu_ur"]) [0] == "A|SYH"
    assert k["benzerlik"].iloc[0] > 0.99
    assert list(k["komsu_ur"])[-1] == "C|SYH"  # kategori farklı -> en sonda


def test_gorsel_gomme_rengi_ayirir(tmp_path):
    def ciz(ad, renk):
        img = Image.new("RGB", (48, 48), (246, 246, 244))
        img.paste(renk, (12, 8, 36, 44))
        img.save(tmp_path / ad)
        return tmp_path / ad
    g = RenkDokuGomucu()
    kirmizi1, kirmizi2, mavi = g.gom(ciz("k1.png", (190, 30, 40))), g.gom(ciz("k2.png", (200, 35, 45))), g.gom(ciz("m.png", (40, 60, 200)))
    assert np.dot(kirmizi1, kirmizi2) > np.dot(kirmizi1, mavi)


def test_gomucu_secimi():
    assert gomucu_sec("yok").ad == "yok"
    try:
        gomucu_sec("bilinmeyen")
    except ValueError:
        pass
    else:
        raise AssertionError
