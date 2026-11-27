"""Ham tablolardan modelleme panelini kurar.

Adımlar:
1. Sezon pencereleri: her sezonun başlangıç haftası ve ufku (varsayılan 26 hafta).
2. Satış ve stok, SKU -> model-renk -> sezon haftasına eşlenir (devamlı ürünler tarihe göre ayrılır).
3. Stokta bulunma oranı (A): her mağaza-SKU-hafta için 0-1; model-renk düzeyinde beden payıyla ağırlıklanır.
4. Stok bitişi düzeltmesi (sansürlü talep): stokta olunan haftaların satış hızı, kategori haftalık
   profiline göre stoksuz haftalara taşınır. Sonuç `talep` kolonudur; satış (`satis`) ayrıca tutulur.
5. Mağaza kümeleri: bölge x büyüklük (metrekare) x kanal. Basit, açıklanabilir ve sızıntısız.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import numpy as np
import pandas as pd

from .bolgeler import bolge
from .yukleme import VeriSeti

UFUK_HAFTA = 26
OZELLIKLER = ("kategori", "cinsiyet", "kumas", "kalip", "desen", "yaka", "kol_boyu", "renk_kodu")


@dataclass
class Panel:
    sezonlar: pd.DataFrame          # sezon_kodu, sezon_tipi, baslangic, bitis
    magazalar: pd.DataFrame         # magaza_kodu, bolge, kume, ...
    urunler: pd.DataFrame           # sezon_kodu, ur_id, urun_kodu, renk_kodu, özellikler, goreli_fiyat, devamli
    haftalik: pd.DataFrame          # sezon_kodu, ur_id, magaza_kodu, hafta_no, satis, A, talep, sansurlu
    beden_paylari: pd.DataFrame     # bolge, kategori, beden, pay
    profil: pd.DataFrame            # kategori, sezon_tipi, hafta_no, p
    beden_satis: pd.DataFrame       # sezon_kodu, ur_id, bolge, kategori, beden, adet
    gercek: pd.DataFrame | None = None   # yalnızca sentetik: sezon_kodu, ur_id, magaza_kodu, hafta_no, gercek_talep
    satin_alma: pd.DataFrame | None = None  # sezon_kodu, ur_id, alim_adedi
    notlar: list[str] = field(default_factory=list)

    def sezon(self, kod: str) -> pd.Series:
        return self.sezonlar.set_index("sezon_kodu").loc[kod]


def _sezon_baslangic_tahmini(kod: str) -> pd.Timestamp:
    yil, tip = kod.split("-")[0], kod.split("-")[-1].upper()
    return pd.Timestamp.fromisocalendar(int(yil), 6 if tip == "SS" else 32, 1)


def sezonlari_kur(urunler: pd.DataFrame, ufuk: int = UFUK_HAFTA) -> pd.DataFrame:
    rows = []
    for kod, g in urunler.groupby("sezon_kodu"):
        bas = g["ilk_satis_tarihi"].min() if "ilk_satis_tarihi" in g and g["ilk_satis_tarihi"].notna().any() else _sezon_baslangic_tahmini(kod)
        bas = (pd.Timestamp(bas) - pd.Timedelta(days=pd.Timestamp(bas).weekday())).normalize()
        rows.append(dict(sezon_kodu=kod, sezon_tipi=str(kod).split("-")[-1].upper(), baslangic=bas, bitis=bas + pd.Timedelta(weeks=ufuk)))
    return pd.DataFrame(rows).sort_values("baslangic").reset_index(drop=True)


def magaza_kumeleri(mag: pd.DataFrame) -> pd.DataFrame:
    """Bölge x kanal x büyüklük. 4+ fiziksel mağazası olan bölgede medyan metrekareye göre büyük/küçük."""
    mag = mag.copy()
    mag["bolge"] = mag["ulke"].map(bolge)
    online = mag["kanal"].eq("online")
    mag["kume"] = mag["bolge"] + "-" + np.where(online, "online", "magaza")
    for b, g in mag[~online].groupby("bolge"):
        if len(g) >= 4 and "metrekare" in g and g["metrekare"].notna().sum() >= 4:
            med = g["metrekare"].median()
            buyuk = g["metrekare"].fillna(med) > med
            mag.loc[g.index, "kume"] = b + "-" + np.where(buyuk, "buyuk", "kucuk")
    return mag


def _sezona_esle(df: pd.DataFrame, sku: pd.DataFrame, urun_sezon: pd.DataFrame, sezonlar: pd.DataFrame) -> pd.DataFrame:
    df = df.merge(sku[["sku_kodu", "urun_kodu", "renk_kodu", "beden"]], on="sku_kodu", how="inner")
    df = df.merge(urun_sezon, on="urun_kodu", how="inner").merge(sezonlar[["sezon_kodu", "baslangic"]], on="sezon_kodu")
    hafta_basi = df["tarih"] - pd.to_timedelta(df["tarih"].dt.weekday, unit="D")
    df["hafta_no"] = ((hafta_basi.dt.normalize() - df["baslangic"]).dt.days // 7).astype(int)
    return df[(df["hafta_no"] >= 0) & (df["hafta_no"] < UFUK_HAFTA)].drop(columns="baslangic")


def _goreli_fiyat(vs: VeriSeti, urunler: pd.DataFrame, sezonlar: pd.DataFrame) -> pd.DataFrame:
    """Sezon başındaki etiket fiyatı / aynı kategori-sezon-para birimi medyanı. Kur ve enflasyondan bağımsız."""
    f = vs.get("fiyat_gecmisi")
    if f is None or f.empty:
        return pd.DataFrame(columns=["sezon_kodu", "ur_id", "goreli_fiyat", "liste_fiyati_try"])
    f = f.merge(urunler[["sezon_kodu", "urun_kodu", "renk_kodu", "ur_id", "kategori"]].rename(columns={"renk_kodu": "_renk"}), on="urun_kodu")
    f = f[f["renk_kodu"].isna() | (f["renk_kodu"] == f["_renk"])]
    f = f.merge(sezonlar[["sezon_kodu", "baslangic", "bitis"]], on="sezon_kodu")
    f = f[(f["baslangic_tarihi"] >= f["baslangic"] - pd.Timedelta(days=60)) & (f["baslangic_tarihi"] < f["bitis"])]
    f = f.sort_values("baslangic_tarihi").groupby(["sezon_kodu", "ur_id", "kapsam_kodu"], as_index=False).first()
    med = f.groupby(["sezon_kodu", "kategori", "para_birimi"])["liste_fiyati"].transform("median")
    f["oran"] = f["liste_fiyati"] / med
    out = f.groupby(["sezon_kodu", "ur_id"], as_index=False).agg(goreli_fiyat=("oran", "mean"))
    tr = f[f["para_birimi"] == "TRY"].groupby(["sezon_kodu", "ur_id"], as_index=False).agg(liste_fiyati_try=("liste_fiyati", "first"))
    return out.merge(tr, on=["sezon_kodu", "ur_id"], how="left")


def panel_kur(vs: VeriSeti, ufuk: int = UFUK_HAFTA) -> Panel:
    notlar: list[str] = []
    urun = vs["urunler"].copy()
    sku = vs["skular"].copy()
    mag = magaza_kumeleri(vs["magazalar"])
    sezonlar = sezonlari_kur(urun, ufuk)

    # model-renk x sezon tablosu
    renkler = sku[["urun_kodu", "renk_kodu"]].drop_duplicates()
    ur = urun.merge(renkler, on="urun_kodu")
    ur["ur_id"] = ur["urun_kodu"] + "|" + ur["renk_kodu"]
    ur["sezon_tipi"] = ur["sezon_kodu"].str.split("-").str[-1].str.upper()
    ur["devamli"] = ur["devamli_urun"].fillna(False).astype(bool) if "devamli_urun" in ur else False
    ur["renk_sayisi"] = ur.groupby(["sezon_kodu", "urun_kodu"])["renk_kodu"].transform("nunique")
    for o in OZELLIKLER:
        if o not in ur:
            ur[o] = pd.NA
        ur[o] = ur[o].astype("string").fillna("bilinmiyor")
    ur = ur.merge(_goreli_fiyat(vs, ur, sezonlar), on=["sezon_kodu", "ur_id"], how="left")
    if ur["goreli_fiyat"].isna().all():
        notlar.append("Fiyat geçmişi yok ya da eşleşmedi: göreli fiyat özelliği kullanılamıyor.")
    urun_sezon = ur[["urun_kodu", "sezon_kodu"]].drop_duplicates()

    # satışlar -> SKU x mağaza x sezon haftası
    satis = _sezona_esle(vs["satislar"][["tarih", "magaza_kodu", "sku_kodu", "adet"]], sku, urun_sezon, sezonlar)
    sh = satis.groupby(["sezon_kodu", "urun_kodu", "renk_kodu", "beden", "magaza_kodu", "hafta_no"], as_index=False)["adet"].sum()

    # beden payları (bölge x kategori)
    sh_b = sh.merge(mag[["magaza_kodu", "bolge"]], on="magaza_kodu").merge(urun[["urun_kodu", "kategori"]].drop_duplicates("urun_kodu"), on="urun_kodu")
    bp = sh_b.groupby(["bolge", "kategori", "beden"], as_index=False)["adet"].sum()
    bp["pay"] = bp["adet"] / bp.groupby(["bolge", "kategori"])["adet"].transform("sum")
    beden_paylari = bp.drop(columns="adet")
    beden_satis = sh_b.assign(ur_id=sh_b["urun_kodu"] + "|" + sh_b["renk_kodu"]).groupby(
        ["sezon_kodu", "ur_id", "bolge", "kategori", "beden"], as_index=False)["adet"].sum()

    # stok -> SKU x mağaza x sezon haftası, stokta bulunma oranı
    stok = vs.get("stok")
    magaza_kodlari = set(mag["magaza_kodu"])
    if stok is not None and len(stok):
        st = stok[stok["lokasyon_kodu"].isin(magaza_kodlari)].rename(columns={"lokasyon_kodu": "magaza_kodu"})
        st = _sezona_esle(st[["tarih", "magaza_kodu", "sku_kodu", "eldeki_adet"]], sku, urun_sezon, sezonlar)
        st["eldeki_adet"] = st["eldeki_adet"].clip(lower=0)
        st = st.sort_values("tarih")
        st["sifir"] = (st["eldeki_adet"] == 0).astype(int)
        anahtar = ["sezon_kodu", "urun_kodu", "renk_kodu", "beden", "magaza_kodu", "hafta_no"]
        sw = st.groupby(anahtar, as_index=False).agg(son=("eldeki_adet", "last"), sifir=("sifir", "sum"), n=("sifir", "size"))
        gunluk = sw["n"].median() >= 5
        notlar.append(f"Stok verisi {'günlük' if gunluk else 'haftalık'} işlendi.")
        sw = sw.merge(sh, on=anahtar, how="outer")
        sw["adet"] = sw["adet"].fillna(0)
        sw = sw.sort_values(anahtar)
        sw["bas"] = sw.groupby(anahtar[:-1])["son"].shift(1)
        if gunluk:
            a = 1 - sw["sifir"] / sw["n"]
        else:
            a = np.where(sw["son"] > 0, 1.0, np.where((sw["adet"] > 0) | (sw["bas"].fillna(0) > 0), 0.5, 0.0))
        sw["a"] = np.where(sw["n"].isna(), np.nan, a)
        sw["var"] = (sw["son"].fillna(0) > 0) | (sw["adet"] > 0)
    else:
        notlar.append("Stok verisi yok: stok bitişi düzeltmesi yapılamadı, talep = satış kabul edildi (sistematik düşük tahmin riski).")
        sw = sh.assign(a=np.nan, var=sh["adet"] > 0)

    # model-renk x mağaza x hafta: beden payıyla ağırlıklı A
    sw = sw.merge(mag[["magaza_kodu", "bolge"]], on="magaza_kodu").merge(urun[["urun_kodu", "kategori"]].drop_duplicates("urun_kodu"), on="urun_kodu")
    sw = sw.merge(beden_paylari, on=["bolge", "kategori", "beden"], how="left")
    sw["pay"] = sw["pay"].fillna(sw.groupby(["sezon_kodu", "urun_kodu", "renk_kodu", "magaza_kodu", "hafta_no"])["pay"].transform("mean")).fillna(0.2)
    sw["a_bilinmiyor"] = sw["a"].isna()
    sw["a_pay"] = sw["a"].fillna(1.0) * sw["pay"]
    sw["ur_id"] = sw["urun_kodu"] + "|" + sw["renk_kodu"]
    hw = sw.groupby(["sezon_kodu", "ur_id", "magaza_kodu", "hafta_no"], as_index=False).agg(
        satis=("adet", "sum"), a_pay=("a_pay", "sum"), pay=("pay", "sum"), var=("var", "max"), bilinmiyor=("a_bilinmiyor", "mean"))
    hw["A"] = (hw["a_pay"] / hw["pay"].where(hw["pay"] > 0)).fillna(1.0).clip(0, 1)
    hw = hw.drop(columns=["a_pay", "pay"])

    # asortiman penceresi: ilk stok/satış haftasından ufuk sonuna (mağaza açıkken)
    ilk = hw[hw["var"]].groupby(["sezon_kodu", "ur_id", "magaza_kodu"], as_index=False)["hafta_no"].min().rename(columns={"hafta_no": "ilk_hafta"})
    izgara = ilk.loc[ilk.index.repeat(ufuk - ilk["ilk_hafta"])].copy()
    izgara["hafta_no"] = izgara["ilk_hafta"] + izgara.groupby(level=0).cumcount()
    hw = izgara.drop(columns="ilk_hafta").merge(hw, on=["sezon_kodu", "ur_id", "magaza_kodu", "hafta_no"], how="left")
    hw["satis"] = hw["satis"].fillna(0)
    hw["A"] = hw["A"].fillna(0.0 if stok is not None else 1.0)
    hw = hw.merge(sezonlar[["sezon_kodu", "baslangic"]], on="sezon_kodu").merge(mag[["magaza_kodu", "acilis_tarihi", "kapanis_tarihi"]], on="magaza_kodu")
    hafta_basi = hw["baslangic"] + pd.to_timedelta(hw["hafta_no"] * 7, unit="D")
    acik = (hw["acilis_tarihi"] <= hafta_basi) & (hw["kapanis_tarihi"].isna() | (hw["kapanis_tarihi"] > hafta_basi + pd.Timedelta(days=6)))
    hw = hw[acik].drop(columns=["baslangic", "acilis_tarihi", "kapanis_tarihi", "var"])

    # kategori haftalık profili (stokta olunan haftalardan)
    hw = hw.merge(ur[["sezon_kodu", "ur_id", "kategori", "sezon_tipi"]], on=["sezon_kodu", "ur_id"])
    tam = hw[hw["A"] >= 0.9]
    profil = tam.groupby(["kategori", "sezon_tipi", "hafta_no"], as_index=False)["satis"].mean().rename(columns={"satis": "p"})
    profil["p"] = profil["p"] / profil.groupby(["kategori", "sezon_tipi"])["p"].transform("mean")
    hw = hw.merge(profil, on=["kategori", "sezon_tipi", "hafta_no"], how="left")
    hw["p"] = hw["p"].fillna(1.0).clip(lower=0.05)

    # stok bitişi düzeltmesi
    gozlem = hw["A"] >= 0.5
    hw["d_gozlem"] = np.where(gozlem, hw["satis"] / hw["A"].clip(lower=0.5), 0.0)
    g = ["sezon_kodu", "ur_id", "magaza_kodu"]
    oran = hw.assign(pg=np.where(gozlem, hw["p"], 0.0)).groupby(g)[["d_gozlem", "pg"]].transform("sum")
    hiz = (oran["d_gozlem"] / oran["pg"]).where(oran["pg"] > 0)
    hw["talep"] = np.where(gozlem, hw["d_gozlem"], np.maximum(hw["satis"], (hiz * hw["p"]).fillna(hw["satis"])))
    hw["sansurlu"] = ~gozlem | (hw["A"] < 0.999)
    hw = hw.drop(columns=["d_gozlem", "p", "kategori", "sezon_tipi"])
    oran_sansur = (~gozlem).mean()
    notlar.append(f"Mağaza-ürün-haftaların %{100 * oran_sansur:.1f} kadarında ürün çoğunlukla stokta yok; bu haftaların talebi tahmin edildi.".replace(".", ",", 1))
    notlar.append(f"Stok bitişi düzeltmesi toplam talebi satışın {hw['talep'].sum() / max(hw['satis'].sum(), 1):.2f} katı olarak verdi.".replace(".", ",", 1))

    # sentetik gerçek talep
    gercek = None
    p = vs.klasor / "_sentetik_gercek_talep.csv"
    if p.exists():
        gt = pd.read_csv(p, parse_dates=["hafta_baslangic"])
        gt["ur_id"] = gt["urun_kodu"] + "|" + gt["renk_kodu"]
        gt = gt.merge(sezonlar[["sezon_kodu", "baslangic"]], on="sezon_kodu")
        gt["hafta_no"] = (gt["hafta_baslangic"] - gt["baslangic"]).dt.days // 7
        gercek = gt[["sezon_kodu", "ur_id", "magaza_kodu", "hafta_no", "gercek_talep"]]

    # satın alma (değer analizi için)
    satin_alma = None
    po = vs.get("satin_alma_siparisleri")
    if po is not None and len(po):
        po = po.merge(sku[["sku_kodu", "urun_kodu", "renk_kodu"]], on="sku_kodu")
        po["ur_id"] = po["urun_kodu"] + "|" + po["renk_kodu"]
        po = po.merge(urun_sezon, on="urun_kodu").merge(sezonlar[["sezon_kodu", "baslangic", "bitis"]], on="sezon_kodu")
        po = po[(po["siparis_tarihi"] < po["bitis"]) & (po["siparis_tarihi"] >= po["baslangic"] - pd.Timedelta(weeks=40))]
        adet = po["teslim_adedi"].fillna(po["siparis_adedi"]) if "teslim_adedi" in po else po["siparis_adedi"]
        satin_alma = po.assign(adet=adet).groupby(["sezon_kodu", "ur_id"], as_index=False).agg(alim_adedi=("adet", "sum"))

    return Panel(sezonlar=sezonlar, magazalar=mag, urunler=ur, haftalik=hw, beden_paylari=beden_paylari, profil=profil, beden_satis=beden_satis,
                 gercek=gercek, satin_alma=satin_alma, notlar=notlar)


def kume_haftalik(panel: Panel, kolon: str = "talep") -> pd.DataFrame:
    """Model-renk x küme x hafta toplamları + kümede dağıtılan mağaza sayısı."""
    hw = panel.haftalik.merge(panel.magazalar[["magaza_kodu", "kume", "bolge"]], on="magaza_kodu")
    return hw.groupby(["sezon_kodu", "ur_id", "kume", "bolge", "hafta_no"], as_index=False).agg(
        deger=(kolon, "sum"), magaza=("magaza_kodu", "nunique"))


def dagitim(panel: Panel) -> pd.DataFrame:
    """Sezon x model-renk x küme: ürünün gönderildiği mağaza sayısı (karar anında planlanan dağıtım)."""
    hw = panel.haftalik.merge(panel.magazalar[["magaza_kodu", "kume", "bolge"]], on="magaza_kodu")
    return hw.groupby(["sezon_kodu", "ur_id", "kume", "bolge"], as_index=False).agg(magaza_sayisi=("magaza_kodu", "nunique"))


def sezon_toplam(panel: Panel, kolon: str = "talep", tablo: pd.DataFrame | None = None) -> pd.DataFrame:
    """Sezon x model-renk x küme sezon toplamı."""
    hw = (panel.haftalik if tablo is None else tablo).merge(panel.magazalar[["magaza_kodu", "kume", "bolge"]], on="magaza_kodu")
    return hw.groupby(["sezon_kodu", "ur_id", "kume", "bolge"], as_index=False).agg(deger=(kolon, "sum"))

