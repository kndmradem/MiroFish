from pathlib import Path

import pytest
from pydantic import ValidationError

from tahmin.sozlesme import TABLO, TABLOLAR, alan_dokumani, sablon_csv, satir_dogrula

KOK = Path(__file__).resolve().parent.parent


def test_alan_adlari_benzersiz_ve_anahtarlar_tanimli():
    for t in TABLOLAR:
        adlar = [a.ad for a in t.alanlar]
        assert len(adlar) == len(set(adlar)), t.ad
        for k in t.anahtar:
            assert k in adlar, (t.ad, k)


def test_referanslar_var_olan_alanlari_gosteriyor():
    for t in TABLOLAR:
        for a in t.alanlar:
            if a.referans:
                tablo, alan = a.referans.split(".")
                assert alan in [x.ad for x in TABLO[tablo].alanlar], a.referans


@pytest.mark.parametrize("tablo", [t.ad for t in TABLOLAR])
def test_ornek_satirlar_kendi_modelini_gecer(tablo):
    t = TABLO[tablo]
    satir_dogrula(tablo, {a.ad: a.ornek for a in t.alanlar})


def test_zorunlu_alan_eksikse_hata():
    with pytest.raises(ValidationError):
        satir_dogrula("satislar", {"tarih": "2025-01-01", "magaza_kodu": "M1", "sku_kodu": "S1"})


def test_izinli_deger_disi_hata():
    satir = {a.ad: a.ornek for a in TABLO["magazalar"].alanlar}
    satir["kanal"] = "tv"
    with pytest.raises(ValidationError):
        satir_dogrula("magazalar", satir)


def test_dokuman_ve_sablonlar_guncel():
    """docs/ ve sablonlar/ sozlesme.py'den üretilir; değişiklikten sonra `python -m tahmin sozlesme` çalıştırılmalı."""
    assert (KOK / "docs" / "veri-sozlesmesi-alanlar.md").read_text(encoding="utf-8") == alan_dokumani()
    for t in TABLOLAR:
        assert (KOK / "sablonlar" / t.dosya_adi).read_text(encoding="utf-8") == sablon_csv(t)
