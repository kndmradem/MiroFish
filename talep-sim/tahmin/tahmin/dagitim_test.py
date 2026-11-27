"""Mağaza dağıtımı ve ikmal: geriye dönük test (D1).

Soru: aynı toplam adet (gerçekte depoya giren alım) ve aynı talep karşısında, ürünü mağazalara farklı
politikalarla dağıtsaydık ne kadar satardık, ne kadar satış kaçardı, sezon sonunda nerede ne kalırdı?

Her test sezonu ve model-renk için, mağaza x beden x hafta düzeyinde basit bir stok simülasyonu çalışır
(depo stoğu beden başına ayrı):

    hafta başı: yoldaki sevk rafa girer, tedarikçiden gelen depoya girer
    hafta içi:  satış = min(talep, raf stoğu); kalan talep kaçan satıştır
    hafta sonu: politika depodan sevk kararı verir, sevk ertesi hafta rafta

Politikalar:
  - gerceklesen:   müşterinin gerçek sevkiyatları (sevkiyatlar tablosu) olduğu gibi tekrar oynatılır.
  - tek_sefer_esit: depoya giren her şey hemen, ürünün gittiği mağazalara eşit bölünür (kıyas).
  - tek_sefer_pay:  depoya giren her şey hemen, karar anındaki tahmini mağaza payına göre bölünür (kıyas).
  - model:          ilk N haftanın tahmini talebi (mağaza payı x geçmiş beden eğrisi) + güvenlik payı kadar ilk sevk,
                    kalanı depoda rezerv; her hafta sonu ilk satışlarla (ürün, mağaza ve beden düzeyinde) güncellenen
                    tahmine göre "hedef stoğa tamamla" ikmali.
  - model_esit_beden: aynı model, beden eğrisi yerine bedenlere eşit pay (beden eğrisinin katkısını gösterir).

Talep: sentetik veride stok bitişinden etkilenmemiş gerçek talep; gerçek veride stok bitişi düzeltilmiş
talep (bir tahmindir, raporda yazılır). Gerçek veride beden talebi = mağaza talebi x ürünün o bölgedeki
sezon beden payı (bölge x kategori eğrisine büzülmüş); stoğu biten bedenin payı düşük görünebilir, bu bir sınırdır.
İadeler ve mağazalar arası transferler bu sürümde yok sayılır; bütün politikalara aynı şekilde uygulanır.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from .hazirlik import Panel

POLITIKALAR = ("gerceklesen", "tek_sefer_esit", "tek_sefer_pay", "model", "model_esit_beden")
POLITIKA_AD = {
    "gerceklesen": "Gerçekleşen sevkiyat (müşterinin kendi kararları)",
    "tek_sefer_esit": "Hepsi baştan, eşit (kıyas)",
    "tek_sefer_pay": "Hepsi baştan, tahmini paya göre (kıyas)",
    "model": "Model: ilk sevk + depoda rezerv + haftalık ikmal",
    "model_esit_beden": "Model, beden eğrisi yerine eşit beden (kıyas)",
}


def politika_adi(kod: str) -> str:
    if kod.startswith("model_kapsama_"):
        return f"Model, ikmal {kod.rsplit('_', 1)[-1]} haftalık talebi kapsar (duyarlılık)"
    return POLITIKA_AD.get(kod, kod)


@dataclass
class DagitimAyar:
    ilk_hafta: int = 4            # ilk sevk kaç haftalık tahmini talebi kapsar
    guvenlik_z: float = 1.0       # hedef stok = beklenen + z * sqrt(beklenen) (Poisson yaklaşımı)
    sunum_minimumu: int = 1       # ürünün gittiği her mağazaya ilk sevkte en az bu kadar
    kapsama_hafta: int = 2        # ikmal hedefi: önümüzdeki kaç haftanın talebi (teslim 1 hafta + gözden geçirme 1 hafta)
    magaza_buzulme: float = 3.0   # mağaza payı: geçmiş ortalamaya eklenen küme ortalaması sayısı (az geçmişte kümeye doğru)
    okuma_buzulme_urun: float = 10.0   # ilk satış okumasında ürün düzeyi çarpanın önsel ağırlığı (adet)
    okuma_buzulme_magaza: float = 4.0  # mağaza çarpanının ürün çarpanına doğru büzülmesi (adet)
    kapsama_alternatif: tuple[int, ...] = (3,)  # duyarlılık: aynı model, farklı ikmal kapsaması (hizmet düzeyi ayarı)
    beden_buzulme: float = 20.0       # gerçek veride ürün-bölge beden payının bölge x kategori eğrisine büzülmesi (adet)
    okuma_buzulme_beden: float = 15.0  # ilk satış okumasında beden çarpanının 1'e büzülmesi (adet)


# ----------------------------------------------------------------------------- girdiler

def _hafta(tarih: pd.Series, baslangic: pd.Timestamp) -> np.ndarray:
    return ((pd.to_datetime(tarih) - baslangic).dt.days // 7).to_numpy()


def _sku_bilgi(vs) -> pd.DataFrame:
    sku = vs["skular"][["sku_kodu", "urun_kodu", "renk_kodu", "beden"] + (["beden_sirasi"] if "beden_sirasi" in vs["skular"] else [])].copy()
    sku["ur_id"] = sku["urun_kodu"] + "|" + sku["renk_kodu"]
    return sku


def _bedenler(sku: pd.DataFrame) -> dict[str, list[str]]:
    """ur_id -> sıralı beden listesi."""
    s = sku.sort_values(["ur_id", "beden_sirasi"] if "beden_sirasi" in sku else ["ur_id", "beden"])
    return {u: list(dict.fromkeys(g["beden"])) for u, g in s.groupby("ur_id", sort=False)}


def _arz(vs, panel: Panel, T: str, H: int, sku: pd.DataFrame) -> pd.DataFrame:
    """Tedarikçiden depoya giriş: ur_id, beden, hafta, adet (sezon başından önce gelenler 0. haftada)."""
    po = vs.get("satin_alma_siparisleri")
    if po is None or po.empty:
        return pd.DataFrame(columns=["ur_id", "beden", "hafta", "adet"])
    bas = panel.sezon(T)["baslangic"]
    urun_T = set(panel.urunler.loc[panel.urunler["sezon_kodu"] == T, "ur_id"])
    po = po.merge(sku[["sku_kodu", "ur_id", "beden"]], on="sku_kodu")
    po = po[po["ur_id"].isin(urun_T)]
    po = po[(po["siparis_tarihi"] < bas + pd.Timedelta(weeks=H)) & (po["siparis_tarihi"] >= bas - pd.Timedelta(weeks=40))]
    if po.empty:
        return pd.DataFrame(columns=["ur_id", "beden", "hafta", "adet"])
    tarih = po["teslim_tarihi"] if "teslim_tarihi" in po else po["siparis_tarihi"]
    if "planlanan_teslim_tarihi" in po:
        tarih = tarih.fillna(po["planlanan_teslim_tarihi"])
    tarih = tarih.fillna(po["siparis_tarihi"])
    adet = po["teslim_adedi"].fillna(po["siparis_adedi"]) if "teslim_adedi" in po else po["siparis_adedi"]
    po = po.assign(hafta=np.clip(_hafta(tarih, bas), 0, None), adet=adet)
    return po[po["hafta"] < H].groupby(["ur_id", "beden", "hafta"], as_index=False)["adet"].sum()


def _gercek_sevk(vs, panel: Panel, T: str, H: int, sku: pd.DataFrame) -> pd.DataFrame | None:
    """Depodan mağazaya gerçek sevkler: ur_id, magaza_kodu, beden, varis_hafta, adet.

    Hafta k içinde yapılan sevk k+1 başında rafta sayılır; sezon başından önceki sevkler 0. haftada rafta.
    Mağazadan mağazaya transferler bu sürümde dışarıda bırakılır.
    """
    sv = vs.get("sevkiyatlar")
    if sv is None or sv.empty:
        return None
    bas = panel.sezon(T)["baslangic"]
    magazalar = set(panel.magazalar["magaza_kodu"])
    sv = sv[~sv["kaynak_lokasyon"].isin(magazalar) & sv["hedef_lokasyon"].isin(magazalar)]
    sv = sv.merge(sku[["sku_kodu", "ur_id", "beden"]], on="sku_kodu")
    urun_T = set(panel.urunler.loc[panel.urunler["sezon_kodu"] == T, "ur_id"])
    sv = sv[sv["ur_id"].isin(urun_T)]
    h = _hafta(sv["tarih"], bas)
    sv = sv.assign(varis_hafta=np.where(h < 0, 0, h + 1))
    sv = sv[(sv["varis_hafta"] < H) & (h >= -20)]
    return sv.groupby(["ur_id", "hedef_lokasyon", "beden", "varis_hafta"], as_index=False)["adet"].sum().rename(columns={"hedef_lokasyon": "magaza_kodu"})


def _gecmis_beden_egrisi(panel: Panel, gecmis: list[str]) -> pd.DataFrame:
    """Bölge x kategori x beden payı, yalnızca karar anında bitmiş sezonlardan."""
    bs = panel.beden_satis[panel.beden_satis["sezon_kodu"].isin(gecmis)]
    t = bs.groupby(["bolge", "kategori", "beden"], as_index=False)["adet"].sum()
    t["pay"] = t["adet"] / t.groupby(["bolge", "kategori"])["adet"].transform("sum")
    return t[["bolge", "kategori", "beden", "pay"]]


def _talep(vs, panel: Panel, T: str, sku: pd.DataFrame, gecmis: list[str], ayar: DagitimAyar) -> tuple[pd.DataFrame, str]:
    """Test sezonu talebi: ur_id, magaza_kodu, beden, hafta_no, deger."""
    hw = panel.haftalik[panel.haftalik["sezon_kodu"] == T][["ur_id", "magaza_kodu", "hafta_no", "talep"]]
    bas = panel.sezon(T)["baslangic"]
    p = vs.klasor / "_sentetik_gercek_talep_beden.csv"
    if panel.gercek is not None and p.exists():
        g = pd.read_csv(p, parse_dates=["hafta_baslangic"])
        g = g[g["sezon_kodu"] == T].merge(sku[["sku_kodu", "ur_id", "beden"]], on="sku_kodu")
        g["hafta_no"] = (g["hafta_baslangic"] - bas).dt.days // 7
        g = g.merge(hw[["ur_id", "magaza_kodu", "hafta_no"]], on=["ur_id", "magaza_kodu", "hafta_no"])
        return g.rename(columns={"gercek_talep": "deger"})[["ur_id", "magaza_kodu", "beden", "hafta_no", "deger"]], "gercek"
    # gerçek veri: stok bitişi düzeltilmiş mağaza talebi x ürünün o bölgedeki sezon beden payı (eğriye büzülmüş)
    egri = _gecmis_beden_egrisi(panel, gecmis)
    bs = panel.beden_satis[panel.beden_satis["sezon_kodu"] == T]
    bs = bs.merge(egri, on=["bolge", "kategori", "beden"], how="outer" if False else "left")
    bs["pay"] = bs["pay"].fillna(0)
    top = bs.groupby(["ur_id", "bolge"])["adet"].transform("sum")
    bs["pay_t"] = (bs["adet"] + ayar.beden_buzulme * bs["pay"]) / (top + ayar.beden_buzulme * bs.groupby(["ur_id", "bolge"])["pay"].transform("sum").clip(lower=1e-9))
    hw = hw.merge(panel.magazalar[["magaza_kodu", "bolge"]], on="magaza_kodu")
    d = hw.merge(bs[["ur_id", "bolge", "beden", "pay_t"]], on=["ur_id", "bolge"])
    d["deger"] = d["talep"] * d["pay_t"]
    return d[["ur_id", "magaza_kodu", "beden", "hafta_no", "deger"]], "talep"


def magaza_paylari(panel: Panel, gecmis: list[str], ayar: DagitimAyar) -> pd.DataFrame:
    """Kategori x mağaza: ürün başına ortalama sezon talebi, küme ortalamasına doğru büzülmüş (karar anında bilinen)."""
    hw = panel.haftalik[panel.haftalik["sezon_kodu"].isin(gecmis)]
    hw = hw.merge(panel.urunler[["sezon_kodu", "ur_id", "kategori"]], on=["sezon_kodu", "ur_id"])
    t = hw.groupby(["kategori", "magaza_kodu"], as_index=False).agg(talep=("talep", "sum"), n=("ur_id", lambda x: x.nunique()))
    t = t.merge(panel.magazalar[["magaza_kodu", "kume"]], on="magaza_kodu")
    t["ort"] = t["talep"] / t["n"]
    kume_ort = t.groupby(["kategori", "kume"])["ort"].transform("mean")
    t["agirlik"] = (t["talep"] + ayar.magaza_buzulme * kume_ort) / (t["n"] + ayar.magaza_buzulme)
    return t[["kategori", "magaza_kodu", "agirlik"]]


def _beklenen(tahmin_kh: pd.DataFrame, magazalar: list[str], mag_kume: dict, agirlik: dict, H: int) -> np.ndarray:
    """Küme x hafta tahminini kümedeki mağazalara geçmiş paylarına göre böler: (S, H)."""
    E = np.zeros((len(magazalar), H))
    kumeler = {}
    for i, m in enumerate(magazalar):
        kumeler.setdefault(mag_kume[m], []).append(i)
    tk = {k: g.set_index("hafta_no")["tahmin"].reindex(range(H), fill_value=0).to_numpy() for k, g in tahmin_kh.groupby("kume")}
    ort_profil = np.mean(list(tk.values()), axis=0) if tk else np.full(H, 1.0 / H)
    for k, idx in kumeler.items():
        w = np.array([agirlik.get(magazalar[i], np.nan) for i in idx])
        w = np.where(np.isnan(w), np.nanmean(w) if np.isfinite(w).any() else 1.0, w)
        w = w / w.sum() if w.sum() > 0 else np.full(len(idx), 1 / len(idx))
        prof = tk.get(k)
        if prof is None:  # bu küme için tahmin yoksa diğer kümelerin mağaza başı ortalaması
            prof = ort_profil
            w = np.ones(len(idx))
        E[idx] = w[:, None] * prof[None, :]
    return E


def _beden_paylari(egri: pd.DataFrame, magazalar: list[str], mag_bolge: dict, kategori: str, bedenler: list[str], esit: bool = False) -> np.ndarray:
    """(S, Z) beden payı: mağazanın bölgesindeki geçmiş kategori eğrisi; bilinmeyen beden ortalama pay alır."""
    Z = len(bedenler)
    if esit:
        return np.full((len(magazalar), Z), 1 / Z)
    e = egri[egri["kategori"] == kategori].set_index(["bolge", "beden"])["pay"]
    P = np.zeros((len(magazalar), Z))
    for i, m in enumerate(magazalar):
        p = np.array([e.get((mag_bolge[m], b), np.nan) for b in bedenler], dtype=float)
        if np.isnan(p).all():
            p = np.full(Z, 1 / Z)
        p = np.where(np.isnan(p), np.nanmean(p), p)
        P[i] = p / p.sum()
    return P


# ----------------------------------------------------------------------------- simülasyon

def _simule(D: np.ndarray, arz: np.ndarray, karar, grup: np.ndarray | None = None, magaza: np.ndarray | None = None) -> dict:
    """Satır = mağaza (x beden) konumu. D: (R,H) talep; arz: (G,H) ya da (H,) depoya giriş, G = depo grubu (beden);
    grup: (R,) satırın depo grubu; magaza: (R,) satırın mağaza indeksi (beden kaynaklı kaybı ölçmek için).
    karar(k, durum) -> (R,) sevk (k sonunda, k+1'de rafta). k = -1 çağrısı ilk sevktir (0. hafta rafta).
    """
    R, H = D.shape
    arz = np.atleast_2d(arz)
    G = arz.shape[0]
    grup = np.zeros(R, int) if grup is None else grup
    magaza = np.arange(R) if magaza is None else magaza
    depo = arz[:, 0].astype(float).copy()
    raf = np.zeros(R)
    satis = np.zeros((R, H))
    sevk_sayisi = 0
    kirik_kayip = 0.0
    durum = dict(depo=depo, raf=raf, satis=satis, D=D, grup=grup)

    def gonder(k):
        nonlocal sevk_sayisi
        durum["depo"] = depo
        s = np.maximum(np.floor(karar(k, durum)), 0)
        talep_g = np.bincount(grup, s, minlength=G)
        oran = np.where(talep_g > depo, depo / np.maximum(talep_g, 1e-9), 1.0)  # depo yetmiyorsa ihtiyaçla orantılı kıs
        s = np.floor(s * oran[grup])
        depo[:] = depo - np.bincount(grup, s, minlength=G)
        sevk_sayisi += int(np.unique(magaza[s > 0]).size)  # mağaza başına bir sevk satırı (koli)
        return s

    yolda = gonder(-1)
    for k in range(H):
        if k > 0:
            depo += arz[:, k]
        raf += yolda
        s = np.minimum(D[:, k], raf)
        raf -= s
        satis[:, k] = s
        # beden kaynaklı kayıp: mağazada üründen stok varken istenen beden yoktu
        stoklu = np.bincount(magaza, raf, minlength=magaza.max() + 1) > 0
        kirik_kayip += float(((D[:, k] - s) * stoklu[magaza]).sum())
        yolda = gonder(k) if k < H - 1 else np.zeros(R)
    talep = D.sum()
    return dict(talep=talep, satilan=satis.sum(), kacan_satis=talep - satis.sum(), stok_varken_kacan=kirik_kayip,
                magazada_kalan=raf.sum() + yolda.sum(), depoda_kalan=float(depo.sum()), sevk_satiri=sevk_sayisi,
                satis_satir=satis.sum(1), kacan_satir=D.sum(1) - satis.sum(1), kalan_satir=raf + yolda)


def _politika_tek_sefer(w: np.ndarray, grup: np.ndarray | None = None):
    grup = np.zeros(len(w), int) if grup is None else grup
    G = grup.max() + 1
    toplam = np.bincount(grup, w, minlength=G)
    adet_g = np.bincount(grup, minlength=G)
    w = np.where(toplam[grup] > 0, w / np.where(toplam[grup] > 0, toplam[grup], 1), 1 / adet_g[grup])

    def karar(k, d):
        # depodaki her şey hemen gider (ilk sevkte ve tedarikçiden her yeni girişte)
        dagit = np.floor(d["depo"][grup] * w)
        for g in range(G):
            kalan = int(d["depo"][g] - dagit[grup == g].sum())
            if kalan > 0:  # yuvarlama artığını en büyük paylara
                idx = np.where(grup == g)[0]
                dagit[idx[np.argsort(-w[idx])[:kalan]]] += 1
        return dagit
    return karar


def _politika_model(E: np.ndarray, ayar: DagitimAyar, grup: np.ndarray | None = None, magaza: np.ndarray | None = None):
    R, H = E.shape
    grup = np.zeros(R, int) if grup is None else grup
    magaza = np.arange(R) if magaza is None else magaza
    G, S = grup.max() + 1, magaza.max() + 1

    def hedef(beklenen):
        return np.ceil(beklenen + ayar.guvenlik_z * np.sqrt(beklenen))

    def karar(k, d):
        if k == -1:
            b = E[:, : ayar.ilk_hafta].sum(1)
            return np.maximum(hedef(b), ayar.sunum_minimumu)
        # ilk satış okuması: stok bitmeyen haftalarda gerçekleşen / beklenen; ürün, mağaza ve beden düzeyinde büzülmüş.
        # stok bitmeyen hafta = talep tamamen karşılandı (gerçekte: hafta sonu raf stoğu > 0). Biten haftalar sansürlüdür, okunmaz.
        sat = d["satis"][:, : k + 1]
        tam = sat >= d["D"][:, : k + 1]
        st, et = (sat * tam).sum(1), (E[:, : k + 1] * tam).sum(1)
        M = (ayar.okuma_buzulme_urun + st.sum()) / (ayar.okuma_buzulme_urun + et.sum())
        ms = (ayar.okuma_buzulme_magaza * M + np.bincount(magaza, st, minlength=S)) / (ayar.okuma_buzulme_magaza + np.bincount(magaza, et, minlength=S))
        mz = (ayar.okuma_buzulme_beden * M + np.bincount(grup, st, minlength=G)) / (ayar.okuma_buzulme_beden + np.bincount(grup, et, minlength=G))
        m = ms[magaza] * (mz[grup] / M)
        ileri = E[:, k + 1: k + 1 + ayar.kapsama_hafta].sum(1) * m
        return np.maximum(hedef(ileri) - d["raf"], 0)
    return karar


# ----------------------------------------------------------------------------- ana akış

def dagitim_testi(vs, panel: Panel, T: str, gecmis: list[str], tahmin_kh: pd.DataFrame, ayar: DagitimAyar | None = None) -> dict[str, pd.DataFrame]:
    """tahmin_kh: test sezonu için tek yöntemin ur_id x kume x hafta_no x tahmin tablosu (karar anı tahmini)."""
    ayar = ayar or DagitimAyar()
    H = int(panel.haftalik["hafta_no"].max()) + 1
    sku = _sku_bilgi(vs)
    bedenler = _bedenler(sku)
    talep, hedef_ad = _talep(vs, panel, T, sku, gecmis, ayar)
    arz = _arz(vs, panel, T, H, sku)
    sevk = _gercek_sevk(vs, panel, T, H, sku)
    paylar = magaza_paylari(panel, gecmis, ayar)
    egri = _gecmis_beden_egrisi(panel, gecmis)
    mag = panel.magazalar.set_index("magaza_kodu")
    mag_kume, mag_bolge = mag["kume"].to_dict(), mag["bolge"].to_dict()
    kat = panel.urunler[panel.urunler["sezon_kodu"] == T].set_index("ur_id")["kategori"].to_dict()
    arz_g = dict(tuple(arz.groupby("ur_id")))
    sevk_g = dict(tuple(sevk.groupby("ur_id"))) if sevk is not None else {}

    satir, magaza_satir, beden_satir, atlanan = [], [], [], 0
    for ur, g in talep.groupby("ur_id"):
        a_ur = arz_g.get(ur)
        if a_ur is None or a_ur["adet"].sum() <= 0 or ur not in bedenler:
            atlanan += 1
            continue
        magazalar = sorted(g["magaza_kodu"].unique())
        bed = bedenler[ur]
        S, Z = len(magazalar), len(bed)
        mi, zi = {m: i for i, m in enumerate(magazalar)}, {b: j for j, b in enumerate(bed)}
        satir_mag, satir_bed = np.repeat(np.arange(S), Z), np.tile(np.arange(Z), S)  # satır r = i * Z + j
        D = np.zeros((S * Z, H))
        g = g[g["beden"].isin(zi)]
        np.add.at(D, (g["magaza_kodu"].map(mi).to_numpy() * Z + g["beden"].map(zi).to_numpy(), g["hafta_no"].to_numpy()), g["deger"].to_numpy(float))
        A = np.zeros((Z, H))
        a_ur = a_ur[a_ur["beden"].isin(zi)]
        np.add.at(A, (a_ur["beden"].map(zi).to_numpy(), a_ur["hafta"].to_numpy()), a_ur["adet"].to_numpy(float))
        w = paylar[paylar["kategori"] == kat.get(ur)].set_index("magaza_kodu")["agirlik"].to_dict()
        Es = _beklenen(tahmin_kh[tahmin_kh["ur_id"] == ur], magazalar, mag_kume, w, H)
        P = _beden_paylari(egri, magazalar, mag_bolge, kat.get(ur), bed)
        E = (Es[:, None, :] * P[:, :, None]).reshape(S * Z, H)
        Pe = _beden_paylari(egri, magazalar, mag_bolge, kat.get(ur), bed, esit=True)
        Ee = (Es[:, None, :] * Pe[:, :, None]).reshape(S * Z, H)
        politikalar = {
            "tek_sefer_esit": _politika_tek_sefer(np.ones(S * Z), satir_bed),
            "tek_sefer_pay": _politika_tek_sefer(E.sum(1), satir_bed),
            "model": _politika_model(E, ayar, satir_bed, satir_mag),
            "model_esit_beden": _politika_model(Ee, ayar, satir_bed, satir_mag),
            **{f"model_kapsama_{n}": _politika_model(E, replace(ayar, kapsama_hafta=n), satir_bed, satir_mag) for n in ayar.kapsama_alternatif},
        }
        gs = sevk_g.get(ur)
        if gs is not None:
            gs = gs[gs["magaza_kodu"].isin(mi) & gs["beden"].isin(zi)]
            if len(gs):
                Sv = np.zeros((S * Z, H))
                np.add.at(Sv, (gs["magaza_kodu"].map(mi).to_numpy() * Z + gs["beden"].map(zi).to_numpy(), gs["varis_hafta"].to_numpy()), gs["adet"].to_numpy(float))

                def karar(k, d, Sv=Sv):
                    return Sv[:, 0] if k == -1 else (Sv[:, k + 1] if k + 1 < H else np.zeros(len(Sv)))
                politikalar["gerceklesen"] = karar
        for ad, karar in politikalar.items():
            r = _simule(D, A, karar, satir_bed, satir_mag)
            satir.append(dict(test_sezonu=T, ur_id=ur, politika=ad, arz=float(A.sum()),
                              **{k: float(v) for k, v in r.items() if np.isscalar(v)}))
            ks, kk, kl = (r[x].reshape(S, Z) for x in ("satis_satir", "kacan_satir", "kalan_satir"))
            Dm = D.sum(1).reshape(S, Z)
            for m, i in mi.items():
                magaza_satir.append(dict(test_sezonu=T, ur_id=ur, politika=ad, magaza_kodu=m, bolge=mag_bolge[m],
                                         talep=float(Dm[i].sum()), satilan=float(ks[i].sum()), kacan_satis=float(kk[i].sum()), kalan=float(kl[i].sum())))
            for b, j in zi.items():
                beden_satir.append(dict(test_sezonu=T, ur_id=ur, politika=ad, beden=b, beden_sirasi=j, talep=float(Dm[:, j].sum()),
                                        satilan=float(ks[:, j].sum()), kacan_satis=float(kk[:, j].sum()), magazada_kalan=float(kl[:, j].sum())))
    urun = pd.DataFrame(satir)
    if urun.empty:
        return dict(urun=urun, ozet=pd.DataFrame(), bolge=pd.DataFrame(), beden=pd.DataFrame(),
                    notlar=pd.DataFrame([dict(test_sezonu=T, not_="Dağıtım testi için arz (satın alma) verisi bulunamadı.")]))
    # karşılaştırma yalnızca bütün politikaların koştuğu ürünlerde (gerçek sevki olmayan ürün varsa diğerleri de dışarıda)
    n_pol = urun.groupby("ur_id")["politika"].nunique()
    ortak = n_pol[n_pol == n_pol.max()].index
    urun_o = urun[urun["ur_id"].isin(ortak)]
    ozet = urun_o.groupby(["test_sezonu", "politika"], as_index=False)[
        ["arz", "talep", "satilan", "kacan_satis", "stok_varken_kacan", "magazada_kalan", "depoda_kalan", "sevk_satiri"]].sum()
    ozet["urun"] = len(ortak)
    ozet["karsilanan_talep"] = ozet["satilan"] / ozet["talep"]
    ozet["satis_orani"] = ozet["satilan"] / ozet["arz"]
    ozet["hedef"] = hedef_ad
    ms = pd.DataFrame(magaza_satir)
    bolge = ms[ms["ur_id"].isin(ortak)].groupby(["test_sezonu", "politika", "bolge"], as_index=False)[["talep", "satilan", "kacan_satis", "kalan"]].sum()
    bs = pd.DataFrame(beden_satir)
    beden = bs[bs["ur_id"].isin(ortak)].groupby(["test_sezonu", "politika", "beden_sirasi"], as_index=False).agg(
        beden=("beden", lambda x: "/".join(sorted(set(map(str, x))))), talep=("talep", "sum"), satilan=("satilan", "sum"),
        kacan_satis=("kacan_satis", "sum"), magazada_kalan=("magazada_kalan", "sum"))
    notlar = pd.DataFrame([dict(test_sezonu=T, urun_toplam=talep["ur_id"].nunique(), urun_karsilastirilan=len(ortak), arzsiz_atlanan=atlanan,
                                gercek_sevk_var=sevk is not None)])
    return dict(urun=urun, ozet=ozet, bolge=bolge, beden=beden, notlar=notlar)
