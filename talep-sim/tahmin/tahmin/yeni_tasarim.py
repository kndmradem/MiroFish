"""Henüz satılmamış yeni bir tasarım için: en benzer geçmiş ürünler ve onların bölge başına satışından
basit bir mağaza başı talep tahmini. Özellikler elle girilir ya da görsel modelden (ör. talep-sim
backend'indeki Qwen-VL ürün kartı) gelir.

Bu, geriye dönük testteki `benzer_urun_knn` yöntemidir; aralık içermez. Üretim kararı için
geriye dönük testi geçmiş özellik modelini ve aralıkları kullan.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .benzerlik import BenzerlikIndeksi, komsu_ortalamasi
from .gorsel import gomucu_sec, urun_gomuleri
from .hazirlik import OZELLIKLER, panel_kur
from .modeller import Baglam
from .yukleme import yukle

YENI_SEZON = "YENI"


def benzer_bul(veri: str | Path, ozellik: dict, gorsel: str | Path | None = None, k: int = 5,
               gorsel_modeli: str = "renk_doku") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Dönüş: (komşular, bölge başına mağaza başı talep tahmini)."""
    vs = yukle(veri)
    panel = panel_kur(vs)
    gomucu = gomucu_sec(gorsel_modeli)
    gomuler = urun_gomuleri(vs.get("urun_gorselleri"), vs.klasor, gomucu)
    renk = str(ozellik.get("renk_kodu", "bilinmiyor"))
    ur_id = f"YENI|{renk}"
    satir = {o: str(ozellik.get(o, "bilinmiyor")) for o in OZELLIKLER}
    satir.update(sezon_kodu=YENI_SEZON, ur_id=ur_id, urun_kodu="YENI", goreli_fiyat=float(ozellik.get("goreli_fiyat", 1.0)),
                 sezon_tipi=str(ozellik.get("sezon_tipi", "")).upper())
    urunler = pd.concat([panel.urunler, pd.DataFrame([satir])], ignore_index=True)
    if gorsel is not None and gomuler:
        v = gomucu.gom(Path(gorsel))
        gomuler[ur_id] = v / max(np.linalg.norm(v), 1e-9)
    indeks = BenzerlikIndeksi(urunler, gomuler)
    b = Baglam(panel, indeks)
    y = b.y
    adaylar = y[["sezon_kodu", "ur_id"]].drop_duplicates()
    if satir["sezon_tipi"] in ("SS", "AW"):
        adaylar = adaylar[adaylar["sezon_kodu"].str.endswith(satir["sezon_tipi"])]
    komsu = indeks.komsular(pd.DataFrame([{"sezon_kodu": YENI_SEZON, "ur_id": ur_id}]), adaylar, k=k)

    toplam = y.groupby(["sezon_kodu", "ur_id"], as_index=False).agg(talep=("deger", "sum"), magaza=("magaza_sayisi", "sum"))
    toplam["magaza_basi_talep"] = toplam["talep"] / toplam["magaza"]
    satis = panel.haftalik.groupby(["sezon_kodu", "ur_id"], as_index=False)["satis"].sum()
    bilgi = panel.urunler[["sezon_kodu", "ur_id", *OZELLIKLER, "goreli_fiyat"]]
    komsular = (komsu.merge(toplam.rename(columns={"sezon_kodu": "komsu_sezon", "ur_id": "komsu_ur"}), on=["komsu_sezon", "komsu_ur"])
                .merge(satis.rename(columns={"sezon_kodu": "komsu_sezon", "ur_id": "komsu_ur"}), on=["komsu_sezon", "komsu_ur"])
                .merge(bilgi.rename(columns={"sezon_kodu": "komsu_sezon", "ur_id": "komsu_ur"}), on=["komsu_sezon", "komsu_ur"]))

    gb = y.groupby(["sezon_kodu", "ur_id", "bolge"], as_index=False)[["deger", "magaza_sayisi"]].sum()
    gb["magaza_basi"] = gb["deger"] / gb["magaza_sayisi"]
    bolge = komsu_ortalamasi(komsu, gb, "bolge").drop(columns=["hedef_sezon", "hedef_ur"])
    bolge = bolge.rename(columns={"knn": "magaza_basi_sezon_talebi", "knn_benzerlik": "ortalama_benzerlik"})
    return komsular.drop(columns=["hedef_sezon", "hedef_ur"]), bolge
