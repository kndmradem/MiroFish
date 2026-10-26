"""Tahmin yöntemleri: basit kıyas yöntemleri ve özellik modeli.

Hepsi aynı soruyu cevaplar: karar anında (sezon başından `karar_oncesi_hafta` önce) bilinenlerle,
hedef sezondaki her model-renk için her mağaza kümesinde sezon boyu (ufuk) toplam talep ne olur?
Dağıtım planı (ürün kümede kaç mağazaya gidecek) karar anında bilinen bir girdi kabul edilir.

Tahmin = mağaza başı talep x mağaza sayısı.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .benzerlik import BenzerlikIndeksi, komsu_ortalamasi
from .hazirlik import OZELLIKLER, Panel, dagitim, kume_haftalik, sezon_toplam

KATEGORI_SEVIYELERI = (
    ["kategori", "sezon_tipi", "kume"],
    ["kategori", "sezon_tipi", "bolge"],
    ["kategori", "sezon_tipi"],
    ["kategori"],
)


@dataclass
class Baglam:
    panel: Panel
    indeks: BenzerlikIndeksi
    karar_oncesi_hafta: int = 16
    komsu_sayisi: int = 10
    _y: pd.DataFrame | None = field(default=None, repr=False)

    def gecmis_sezonlar(self, hedef: str) -> list[str]:
        """Karar anında tamamı gözlenmiş sezonlar."""
        s = self.panel.sezonlar
        kesim = s.set_index("sezon_kodu").at[hedef, "baslangic"] - pd.Timedelta(weeks=self.karar_oncesi_hafta)
        return s.loc[s["bitis"] <= kesim, "sezon_kodu"].tolist()

    @property
    def y(self) -> pd.DataFrame:
        """Sezon x model-renk x küme: talep, mağaza sayısı, mağaza başı talep + ürün özellikleri."""
        if self._y is None:
            y = sezon_toplam(self.panel).merge(dagitim(self.panel), on=["sezon_kodu", "ur_id", "kume", "bolge"])
            y["magaza_basi"] = y["deger"] / y["magaza_sayisi"]
            self._y = y.merge(self.urun_ozellik(), on=["sezon_kodu", "ur_id"])
        return self._y

    def urun_ozellik(self) -> pd.DataFrame:
        kol = ["sezon_kodu", "ur_id", "urun_kodu", "sezon_tipi", "devamli", "renk_sayisi", "goreli_fiyat", *OZELLIKLER]
        kol += [c for c in self.panel.urunler.columns if c.startswith("sinyal_")]
        return self.panel.urunler[kol]

    def hedef_satirlari(self, hedef: str) -> pd.DataFrame:
        return self.y[self.y["sezon_kodu"] == hedef].drop(columns=["deger", "magaza_basi"]).reset_index(drop=True)


def _hiyerarsik(gecmis: pd.DataFrame, hedef: pd.DataFrame, seviyeler=KATEGORI_SEVIYELERI, kolon: str = "magaza_basi") -> np.ndarray:
    sonuc = pd.Series(np.nan, index=hedef.index)
    for anahtar in seviyeler:
        if gecmis.empty:
            break
        ort = gecmis.groupby(list(anahtar))[kolon].mean().rename("_v").reset_index()
        v = hedef[list(anahtar)].merge(ort, on=list(anahtar), how="left")["_v"]
        v.index = hedef.index
        sonuc = sonuc.fillna(v)
    genel = gecmis[kolon].mean() if not gecmis.empty else 0.0
    return sonuc.fillna(genel).to_numpy()


def _son_ayni_tip(b: Baglam, hedef: str, gecmis: list[str]) -> list[str]:
    tip = b.panel.sezonlar.set_index("sezon_kodu").at[hedef, "sezon_tipi"]
    ayni = [s for s in gecmis if b.panel.sezonlar.set_index("sezon_kodu").at[s, "sezon_tipi"] == tip]
    return ayni[-1:] if ayni else gecmis[-1:]


class Tahminci:
    ad = "temel"
    aciklama = ""

    def egit(self, b: Baglam, hedef: str) -> None:  # noqa: B027 - kıyas yöntemleri eğitim istemez
        pass

    def magaza_basi(self, b: Baglam, hedef: str, satirlar: pd.DataFrame) -> np.ndarray:
        raise NotImplementedError

    def tahmin(self, b: Baglam, hedef: str) -> pd.DataFrame:
        self.egit(b, hedef)
        s = b.hedef_satirlari(hedef)
        s["tahmin"] = np.maximum(self.magaza_basi(b, hedef, s), 0) * s["magaza_sayisi"]
        return s


class KategoriOrtalamasi(Tahminci):
    ad = "kategori_ortalamasi"
    aciklama = "Benzer ürün ortalaması: geçmiş tüm sezonlarda aynı kategori ve sezon tipindeki ürünlerin kümedeki mağaza başı ortalaması"

    def magaza_basi(self, b, hedef, satirlar):
        g = b.y[b.y["sezon_kodu"].isin(b.gecmis_sezonlar(hedef))]
        return _hiyerarsik(g, satirlar)


class GecenYilKategori(Tahminci):
    ad = "gecen_yil_kategori"
    aciklama = "Geçen yıl aynı kategori: son aynı tip sezondaki kategori ortalaması"

    def magaza_basi(self, b, hedef, satirlar):
        gecmis = b.gecmis_sezonlar(hedef)
        g = b.y[b.y["sezon_kodu"].isin(_son_ayni_tip(b, hedef, gecmis))]
        return _hiyerarsik(g, satirlar)


class MevsimselNaif(Tahminci):
    ad = "mevsimsel_naif"
    aciklama = "Mevsimsel naif: devamlı ürün geçen yıl aynı sezonda ne sattıysa o; yeni üründe geçen yıl kategori ortalaması"

    def magaza_basi(self, b, hedef, satirlar):
        gecmis = b.gecmis_sezonlar(hedef)
        son = _son_ayni_tip(b, hedef, gecmis)
        g = b.y[b.y["sezon_kodu"].isin(son)]
        kendi = satirlar[["ur_id", "kume"]].merge(g[["ur_id", "kume", "magaza_basi"]], on=["ur_id", "kume"], how="left")["magaza_basi"].to_numpy()
        return np.where(np.isnan(kendi), _hiyerarsik(g, satirlar), kendi)


def _knn(b: Baglam, satirlar: pd.DataFrame, gecmis: list[str]) -> pd.DataFrame:
    """satirlar için komşu ortalaması (küme, yoksa bölge düzeyinde). Dönüş satirlar ile aynı sırada knn, knn_benzerlik."""
    out = pd.DataFrame({"knn": np.nan, "knn_benzerlik": np.nan}, index=satirlar.index)
    g = b.y[b.y["sezon_kodu"].isin(gecmis)]
    if g.empty:
        return out
    hedefler = satirlar[["sezon_kodu", "ur_id"]].drop_duplicates()
    adaylar = g[["sezon_kodu", "ur_id"]].drop_duplicates()
    komsu = b.indeks.komsular(hedefler, adaylar, k=b.komsu_sayisi)
    kume = komsu_ortalamasi(komsu, g[["sezon_kodu", "ur_id", "kume", "magaza_basi"]], "kume")
    gb = g.groupby(["sezon_kodu", "ur_id", "bolge"], as_index=False)[["deger", "magaza_sayisi"]].sum()
    gb["magaza_basi"] = gb["deger"] / gb["magaza_sayisi"]
    bol = komsu_ortalamasi(komsu, gb, "bolge")
    anahtar = satirlar[["sezon_kodu", "ur_id", "kume", "bolge"]].rename(columns={"sezon_kodu": "hedef_sezon", "ur_id": "hedef_ur"})
    m1 = anahtar.merge(kume, on=["hedef_sezon", "hedef_ur", "kume"], how="left")
    m2 = anahtar.merge(bol, on=["hedef_sezon", "hedef_ur", "bolge"], how="left")
    out["knn"] = m1["knn"].fillna(m2["knn"]).to_numpy()
    out["knn_benzerlik"] = m1["knn_benzerlik"].fillna(m2["knn_benzerlik"]).to_numpy()
    return out


class BenzerUrunKNN(Tahminci):
    ad = "benzer_urun_knn"
    aciklama = "En benzer 10 geçmiş ürünün (özellik + fiyat + görsel) kümedeki mağaza başı talebinin benzerlik ağırlıklı ortalaması"

    def magaza_basi(self, b, hedef, satirlar):
        gecmis = b.gecmis_sezonlar(hedef)
        k = _knn(b, satirlar, gecmis)["knn"].to_numpy()
        return np.where(np.isnan(k), _hiyerarsik(b.y[b.y["sezon_kodu"].isin(gecmis)], satirlar), k)


class OzellikModeli(Tahminci):
    """Gradyan artırmalı ağaçlar (Poisson kaybı). Girdiler: ürün özellikleri, göreli fiyat, küme,
    dağıtım genişliği, kategori geçmişi, devamlı ürünün kendi geçmişi, benzer ürün (kNN) sinyali
    ve varsa harici sinyaller (ör. ajan simülasyonu skoru)."""

    ad = "ozellik_modeli"
    aciklama = "Gradyan artırmalı ağaç (Poisson): özellikler + kategori geçmişi + benzer ürün sinyali"
    KATEGORIK = ("kume", "bolge", "sezon_tipi", *OZELLIKLER)

    def __init__(self, tohum: int = 0):
        self.tohum = tohum
        self.model = None
        self.kolonlar: list[str] = []
        self.sozluk: dict[str, dict] = {}

    def _ozellikler(self, b: Baglam, satirlar: pd.DataFrame) -> pd.DataFrame:
        parca = []
        for s, grup in satirlar.groupby("sezon_kodu", sort=False):
            gecmis = b.gecmis_sezonlar(s)
            g = b.y[b.y["sezon_kodu"].isin(gecmis)]
            x = grup.copy()
            x["kat_ort"] = _hiyerarsik(g, grup)
            son = g[g["sezon_kodu"].isin(_son_ayni_tip(b, s, gecmis))] if gecmis else g
            x["kat_gecen"] = _hiyerarsik(son, grup)
            kendi = grup[["ur_id", "kume"]].merge(son[["ur_id", "kume", "magaza_basi"]], on=["ur_id", "kume"], how="left")["magaza_basi"]
            x["onceki"] = kendi.to_numpy()
            x["kume_verim"] = _hiyerarsik(g, grup, seviyeler=(["kume"], ["bolge"]))
            x[["knn", "knn_benzerlik"]] = _knn(b, grup, gecmis).to_numpy()
            parca.append(x)
        x = pd.concat(parca).loc[satirlar.index]
        x["devamli"] = x["devamli"].astype(float)
        sayisal = ["magaza_sayisi", "goreli_fiyat", "renk_sayisi", "devamli", "kat_ort", "kat_gecen", "onceki", "kume_verim", "knn", "knn_benzerlik"]
        sayisal += [c for c in x.columns if c.startswith("sinyal_")]
        self.kolonlar = list(self.KATEGORIK) + sayisal
        return x[self.kolonlar]

    def _kodla(self, x: pd.DataFrame, ogren: bool) -> pd.DataFrame:
        x = x.copy()
        for c in self.KATEGORIK:
            if ogren:
                self.sozluk[c] = {v: i for i, v in enumerate(sorted(x[c].astype(str).unique()))}
            x[c] = x[c].astype(str).map(self.sozluk[c]).astype(float)
        return x.astype(float)

    def egit(self, b, hedef):
        from sklearn.ensemble import HistGradientBoostingRegressor

        gecmis = b.gecmis_sezonlar(hedef)
        tr = b.y[b.y["sezon_kodu"].isin(gecmis)].reset_index(drop=True)
        if tr.empty:
            raise ValueError(f"{hedef} için eğitim sezonu yok (karar anı kuralı çok katı ya da geçmiş kısa).")
        X = self._kodla(self._ozellikler(b, tr), ogren=True)
        bos = [c for c in X.columns if c not in self.KATEGORIK and X[c].isna().all()]
        self.kolonlar = [c for c in self.kolonlar if c not in bos]
        X = X[self.kolonlar]
        self.model = HistGradientBoostingRegressor(
            loss="poisson", learning_rate=0.05, max_iter=300, max_leaf_nodes=15, min_samples_leaf=20,
            l2_regularization=1.0, categorical_features=[X.columns.get_loc(c) for c in self.KATEGORIK],
            random_state=self.tohum)
        self.model.fit(X, tr["magaza_basi"], sample_weight=tr["magaza_sayisi"])

    def magaza_basi(self, b, hedef, satirlar):
        kolonlar = list(self.kolonlar)
        X = self._kodla(self._ozellikler(b, satirlar), ogren=False)
        self.kolonlar = kolonlar
        return self.model.predict(X[kolonlar])


YONTEMLER = {c.ad: c for c in (KategoriOrtalamasi, GecenYilKategori, MevsimselNaif, BenzerUrunKNN, OzellikModeli)}
KIYAS_YONTEMLERI = ("kategori_ortalamasi", "gecen_yil_kategori", "mevsimsel_naif")


def haftaya_dagit(b: Baglam, hedef: str, tahmin: pd.DataFrame) -> pd.DataFrame:
    """Sezon toplamını geçmiş sezonların haftalık payına (kategori x sezon tipi x bölge) göre haftalara böler."""
    gecmis = b.gecmis_sezonlar(hedef)
    kh = kume_haftalik(b.panel)
    kh = kh[kh["sezon_kodu"].isin(gecmis)].merge(b.panel.urunler[["sezon_kodu", "ur_id", "kategori", "sezon_tipi"]], on=["sezon_kodu", "ur_id"])
    ufuk = int(b.panel.haftalik["hafta_no"].max()) + 1

    def pay(anahtar):
        t = kh.groupby([*anahtar, "hafta_no"], as_index=False)["deger"].sum()
        t["pay"] = t["deger"] / t.groupby(anahtar)["deger"].transform("sum")
        return t.drop(columns="deger")

    izgara = tahmin.loc[tahmin.index.repeat(ufuk)].copy()
    izgara["hafta_no"] = np.tile(np.arange(ufuk), len(tahmin))
    p1 = izgara.merge(pay(["kategori", "sezon_tipi", "bolge"]), on=["kategori", "sezon_tipi", "bolge", "hafta_no"], how="left")["pay"]
    p2 = izgara.merge(pay(["sezon_tipi"]), on=["sezon_tipi", "hafta_no"], how="left")["pay"]
    izgara["pay"] = p1.fillna(p2).fillna(1 / ufuk).to_numpy()
    izgara["pay"] = izgara["pay"] / izgara.groupby(["ur_id", "kume"])["pay"].transform("sum")
    izgara["tahmin"] = izgara["tahmin"] * izgara["pay"]
    return izgara.drop(columns="pay")
