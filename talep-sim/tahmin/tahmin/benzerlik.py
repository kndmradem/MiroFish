"""Yeni tasarım için "en çok benzeyen geçmiş ürünler" (k en yakın komşu).

Ürün vektörü = ağırlıklı one-hot özellikler + log göreli fiyat + görsel gömme. Benzerlik kosinüs.
Hem modele özellik (komşuların mağaza başı talebi) hem müşteriye açıklama ("buna en çok benzeyen
5 ürün ve gerçekte ne kadar sattıkları") olarak kullanılır.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .hazirlik import OZELLIKLER

AGIRLIK = {"kategori": 3.0, "cinsiyet": 1.5, "renk_kodu": 1.5, "kalip": 1.0, "desen": 1.0, "kumas": 1.0, "yaka": 0.7, "kol_boyu": 0.7}
FIYAT_AGIRLIK = 1.0
GORSEL_AGIRLIK = 1.5


class BenzerlikIndeksi:
    def __init__(self, urunler: pd.DataFrame, gomuler: dict[str, np.ndarray] | None = None,
                 gorsel_agirlik: float = GORSEL_AGIRLIK):
        self.urunler = urunler.reset_index(drop=True)
        self._anahtar = {(r.sezon_kodu, r.ur_id): i for i, r in enumerate(self.urunler[["sezon_kodu", "ur_id"]].itertuples())}
        bloklar = []
        for o in OZELLIKLER:
            d = pd.get_dummies(self.urunler[o].astype(str)).to_numpy(float)
            bloklar.append(d * AGIRLIK.get(o, 1.0))
        fiyat = np.log(self.urunler["goreli_fiyat"].astype(float).fillna(1.0).clip(0.2, 5)).to_numpy()[:, None]
        bloklar.append(fiyat * FIYAT_AGIRLIK * 2)
        gomuler = gomuler or {}
        if gomuler:
            boyut = len(next(iter(gomuler.values())))
            g = np.zeros((len(self.urunler), boyut))
            for i, r in enumerate(self.urunler.itertuples()):
                v = gomuler.get(r.ur_id, gomuler.get(r.urun_kodu))
                if v is not None and len(v) == boyut:
                    g[i] = v
            bloklar.append(g * gorsel_agirlik)
        X = np.hstack(bloklar)
        self.X = X / np.maximum(np.linalg.norm(X, axis=1, keepdims=True), 1e-9)
        self.gorsel_var = bool(gomuler)

    def indeks(self, sezon: str, ur_id: str) -> int:
        return self._anahtar[(sezon, ur_id)]

    def komsular(self, hedefler: pd.DataFrame, adaylar: pd.DataFrame, k: int = 10, ayni_kategori: bool = True) -> pd.DataFrame:
        """hedefler, adaylar: sezon_kodu + ur_id kolonları. Her hedef için en benzer k aday."""
        hi = np.array([self.indeks(s, u) for s, u in zip(hedefler["sezon_kodu"], hedefler["ur_id"])])
        ai = np.array([self.indeks(s, u) for s, u in zip(adaylar["sezon_kodu"], adaylar["ur_id"])])
        if len(hi) == 0 or len(ai) == 0:
            return pd.DataFrame(columns=["hedef_sezon", "hedef_ur", "komsu_sezon", "komsu_ur", "benzerlik", "sira"])
        S = self.X[hi] @ self.X[ai].T
        if ayni_kategori:
            hk = self.urunler["kategori"].to_numpy()[hi]
            ak = self.urunler["kategori"].to_numpy()[ai]
            ayni = hk[:, None] == ak[None, :]
            yeterli = ayni.sum(1) >= min(k, 3)
            S = np.where(ayni | ~yeterli[:, None], S, S - 2.0)
        k = min(k, len(ai))
        en = np.argsort(-S, axis=1)[:, :k]
        rows = []
        for r, h in enumerate(hi):
            for j, a in enumerate(en[r]):
                rows.append((self.urunler.at[h, "sezon_kodu"], self.urunler.at[h, "ur_id"], self.urunler.at[ai[a], "sezon_kodu"],
                             self.urunler.at[ai[a], "ur_id"], float(np.clip(S[r, a], -1, 1)), j + 1))
        return pd.DataFrame(rows, columns=["hedef_sezon", "hedef_ur", "komsu_sezon", "komsu_ur", "benzerlik", "sira"])


def komsu_ortalamasi(komsu: pd.DataFrame, magaza_basi: pd.DataFrame, anahtar: str = "kume") -> pd.DataFrame:
    """Komşuların aynı küme (ya da bölge) içindeki mağaza başı talebinin benzerlik ağırlıklı ortalaması.

    magaza_basi: sezon_kodu, ur_id, <anahtar>, magaza_basi
    Dönüş: hedef_sezon, hedef_ur, <anahtar>, knn, knn_benzerlik
    """
    m = komsu.merge(magaza_basi.rename(columns={"sezon_kodu": "komsu_sezon", "ur_id": "komsu_ur"}), on=["komsu_sezon", "komsu_ur"])
    m["w"] = m["benzerlik"].clip(lower=0.01) ** 2
    m["wy"] = m["w"] * m["magaza_basi"]
    g = m.groupby(["hedef_sezon", "hedef_ur", anahtar], as_index=False).agg(wy=("wy", "sum"), w=("w", "sum"), knn_benzerlik=("benzerlik", "mean"))
    g["knn"] = g["wy"] / g["w"]
    return g.drop(columns=["wy", "w"])
