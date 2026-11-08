"""Mağaza dağıtımı ve ikmal: geriye dönük test (D1).

Soru: aynı toplam adet (gerçekte depoya giren alım) ve aynı talep karşısında, ürünü mağazalara farklı
politikalarla dağıtsaydık ne kadar satardık, ne kadar satış kaçardı, sezon sonunda nerede ne kalırdı?

Her test sezonu ve model-renk için, mağaza x hafta düzeyinde basit bir stok simülasyonu çalışır:

    hafta başı: yoldaki sevk rafa girer, tedarikçiden gelen depoya girer
    hafta içi:  satış = min(talep, raf stoğu); kalan talep kaçan satıştır
    hafta sonu: politika depodan sevk kararı verir, sevk ertesi hafta rafta

Politikalar:
  - gerceklesen:   müşterinin gerçek sevkiyatları (sevkiyatlar tablosu) olduğu gibi tekrar oynatılır.
  - tek_sefer_esit: depoya giren her şey hemen, ürünün gittiği mağazalara eşit bölünür (kıyas).
  - tek_sefer_pay:  depoya giren her şey hemen, karar anındaki tahmini mağaza payına göre bölünür (kıyas).
  - model:          ilk N haftanın tahmini talebi + güvenlik payı kadar ilk sevk, kalanı depoda rezerv;
                    her hafta sonu ilk satışlarla güncellenen tahmine göre "hedef stoğa tamamla" ikmali.

Talep: sentetik veride stok bitişinden etkilenmemiş gerçek talep; gerçek veride stok bitişi düzeltilmiş
talep (bir tahmindir, raporda yazılır). İadeler ve mağazalar arası transferler bu sürümde yok sayılır;
bütün politikalara aynı şekilde uygulanır. Beden kırılımı yok (model-renk x mağaza düzeyi); beden eğrisi
ayrıca test edilir.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from .hazirlik import Panel

POLITIKALAR = ("gerceklesen", "tek_sefer_esit", "tek_sefer_pay", "model")
POLITIKA_AD = {
    "gerceklesen": "Gerçekleşen sevkiyat (müşterinin kendi kararları)",
    "tek_sefer_esit": "Hepsi baştan, eşit (kıyas)",
    "tek_sefer_pay": "Hepsi baştan, tahmini paya göre (kıyas)",
    "model": "Model: ilk sevk + depoda rezerv + haftalık ikmal",
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


# ----------------------------------------------------------------------------- girdiler

def _hafta(tarih: pd.Series, baslangic: pd.Timestamp) -> np.ndarray:
    return ((pd.to_datetime(tarih) - baslangic).dt.days // 7).to_numpy()


def _arz(vs, panel: Panel, T: str, H: int) -> dict[str, np.ndarray]:
    """Tedarikçiden depoya giriş: ur_id -> haftalık adet (sezon başından önce gelenler 0. haftada)."""
    po = vs.get("satin_alma_siparisleri")
    if po is None or po.empty:
        return {}
    bas = panel.sezon(T)["baslangic"]
    sku = vs["skular"][["sku_kodu", "urun_kodu", "renk_kodu"]]
    urun_T = panel.urunler.loc[panel.urunler["sezon_kodu"] == T, ["urun_kodu", "ur_id"]].drop_duplicates()
    po = po.merge(sku, on="sku_kodu").assign(ur_id=lambda d: d["urun_kodu"] + "|" + d["renk_kodu"])
    po = po[po["ur_id"].isin(urun_T["ur_id"])]
    po = po[(po["siparis_tarihi"] < bas + pd.Timedelta(weeks=H)) & (po["siparis_tarihi"] >= bas - pd.Timedelta(weeks=40))]
    if po.empty:
        return {}
    tarih = po["teslim_tarihi"] if "teslim_tarihi" in po else po["siparis_tarihi"]
    if "planlanan_teslim_tarihi" in po:
        tarih = tarih.fillna(po["planlanan_teslim_tarihi"])
    tarih = tarih.fillna(po["siparis_tarihi"])
    adet = po["teslim_adedi"].fillna(po["siparis_adedi"]) if "teslim_adedi" in po else po["siparis_adedi"]
    po = po.assign(hafta=np.clip(_hafta(tarih, bas), 0, None), adet=adet)
    po = po[po["hafta"] < H]
    out = {}
    for ur, g in po.groupby("ur_id"):
        a = np.zeros(H)
        np.add.at(a, g["hafta"].to_numpy(), g["adet"].to_numpy(float))
        out[ur] = a
    return out


def _gercek_sevk(vs, panel: Panel, T: str, H: int) -> pd.DataFrame | None:
    """Depodan mağazaya gerçek sevkler: ur_id, magaza_kodu, varis_hafta, adet.

    Hafta k içinde yapılan sevk k+1 başında rafta sayılır; sezon başından önceki sevkler 0. haftada rafta.
    Mağazadan mağazaya transferler bu sürümde dışarıda bırakılır.
    """
    sv = vs.get("sevkiyatlar")
    if sv is None or sv.empty:
        return None
    bas = panel.sezon(T)["baslangic"]
    magazalar = set(panel.magazalar["magaza_kodu"])
    sv = sv[~sv["kaynak_lokasyon"].isin(magazalar) & sv["hedef_lokasyon"].isin(magazalar)]
    sku = vs["skular"][["sku_kodu", "urun_kodu", "renk_kodu"]]
    sv = sv.merge(sku, on="sku_kodu").assign(ur_id=lambda d: d["urun_kodu"] + "|" + d["renk_kodu"])
    urun_T = set(panel.urunler.loc[panel.urunler["sezon_kodu"] == T, "ur_id"])
    sv = sv[sv["ur_id"].isin(urun_T)]
    h = _hafta(sv["tarih"], bas)
    sv = sv.assign(varis_hafta=np.where(h < 0, 0, h + 1))
    sv = sv[(sv["varis_hafta"] < H) & (h >= -20)]
    return sv.groupby(["ur_id", "hedef_lokasyon", "varis_hafta"], as_index=False)["adet"].sum().rename(columns={"hedef_lokasyon": "magaza_kodu"})


def _talep(panel: Panel, T: str) -> tuple[pd.DataFrame, str]:
    """Test sezonu talebi: ur_id, magaza_kodu, hafta_no, deger. Sentetikte gerçek talep."""
    hw = panel.haftalik[panel.haftalik["sezon_kodu"] == T]
    if panel.gercek is not None:
        g = panel.gercek[panel.gercek["sezon_kodu"] == T].merge(hw[["ur_id", "magaza_kodu", "hafta_no"]], on=["ur_id", "magaza_kodu", "hafta_no"])
        return g.rename(columns={"gercek_talep": "deger"})[["ur_id", "magaza_kodu", "hafta_no", "deger"]], "gercek"
    return hw.rename(columns={"talep": "deger"})[["ur_id", "magaza_kodu", "hafta_no", "deger"]], "talep"


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


# ----------------------------------------------------------------------------- simülasyon

def _simule(D: np.ndarray, arz: np.ndarray, karar) -> dict:
    """D: (S,H) talep; arz: (H,) depoya giriş; karar(k, durum) -> (S,) sevk (k sonunda, k+1'de rafta).

    k = -1 çağrısı ilk sevktir (0. hafta rafta).
    """
    S, H = D.shape
    depo = arz[0]
    raf = np.zeros(S)
    satis = np.zeros((S, H))
    sevk_sayisi = 0
    durum = dict(depo=depo, raf=raf, satis=satis, D=D)

    def gonder(k):
        nonlocal depo, sevk_sayisi
        durum["depo"] = depo
        s = np.maximum(np.floor(karar(k, durum)), 0)
        if s.sum() > depo:  # depo yetmiyorsa ihtiyaçla orantılı kıs
            s = np.floor(s * depo / s.sum())
        depo -= s.sum()
        sevk_sayisi += int((s > 0).sum())
        return s

    yolda = gonder(-1)
    for k in range(H):
        if k > 0:
            depo += arz[k]
        raf += yolda
        s = np.minimum(D[:, k], raf)
        raf -= s
        satis[:, k] = s
        yolda = gonder(k) if k < H - 1 else np.zeros(S)
    talep = D.sum()
    return dict(talep=talep, satilan=satis.sum(), kacan_satis=talep - satis.sum(), magazada_kalan=raf.sum() + yolda.sum(),
                depoda_kalan=depo, sevk_satiri=sevk_sayisi, satis_magaza=satis.sum(1), kacan_magaza=D.sum(1) - satis.sum(1),
                kalan_magaza=raf + yolda)


def _politika_tek_sefer(w: np.ndarray):
    w = w / w.sum() if w.sum() > 0 else np.full(len(w), 1 / len(w))

    def karar(k, d):
        # depodaki her şey hemen gider (ilk sevkte ve tedarikçiden her yeni girişte)
        dagit = np.floor(d["depo"] * w)
        kalan = int(d["depo"] - dagit.sum())
        if kalan > 0:  # yuvarlama artığını en büyük paylara
            dagit[np.argsort(-w)[:kalan]] += 1
        return dagit
    return karar


def _politika_model(E: np.ndarray, ayar: DagitimAyar):
    S, H = E.shape

    def hedef(beklenen):
        return np.ceil(beklenen + ayar.guvenlik_z * np.sqrt(beklenen))

    def karar(k, d):
        if k == -1:
            b = E[:, : ayar.ilk_hafta].sum(1)
            return np.maximum(hedef(b), ayar.sunum_minimumu)
        # ilk satış okuması: stok bitmeyen haftalarda gerçekleşen / beklenen, ürün ve mağaza düzeyinde büzülmüş
        # stok bitmeyen hafta = talep tamamen karşılandı (gerçekte: hafta sonu raf stoğu > 0). Biten haftalar sansürlüdür, okunmaz.
        sat = d["satis"][:, : k + 1]
        tam = sat >= d["D"][:, : k + 1]
        e = E[:, : k + 1]
        M = (ayar.okuma_buzulme_urun + (sat * tam).sum()) / (ayar.okuma_buzulme_urun + (e * tam).sum())
        m = (ayar.okuma_buzulme_magaza * M + (sat * tam).sum(1)) / (ayar.okuma_buzulme_magaza + (e * tam).sum(1))
        ileri = E[:, k + 1: k + 1 + ayar.kapsama_hafta].sum(1) * m
        return np.maximum(hedef(ileri) - d["raf"], 0)
    return karar


# ----------------------------------------------------------------------------- ana akış

def dagitim_testi(vs, panel: Panel, T: str, gecmis: list[str], tahmin_kh: pd.DataFrame, ayar: DagitimAyar | None = None) -> dict[str, pd.DataFrame]:
    """tahmin_kh: test sezonu için tek yöntemin ur_id x kume x hafta_no x tahmin tablosu (karar anı tahmini)."""
    ayar = ayar or DagitimAyar()
    H = int(panel.haftalik["hafta_no"].max()) + 1
    talep, hedef_ad = _talep(panel, T)
    arz = _arz(vs, panel, T, H)
    sevk = _gercek_sevk(vs, panel, T, H)
    paylar = magaza_paylari(panel, gecmis, ayar)
    mag = panel.magazalar.set_index("magaza_kodu")
    mag_kume, mag_bolge = mag["kume"].to_dict(), mag["bolge"].to_dict()
    kat = panel.urunler[panel.urunler["sezon_kodu"] == T].set_index("ur_id")["kategori"].to_dict()

    satir, magaza_satir, atlanan = [], [], 0
    for ur, g in talep.groupby("ur_id"):
        if ur not in arz or arz[ur].sum() <= 0:
            atlanan += 1
            continue
        magazalar = sorted(g["magaza_kodu"].unique())
        idx = {m: i for i, m in enumerate(magazalar)}
        D = np.zeros((len(magazalar), H))
        D[g["magaza_kodu"].map(idx).to_numpy(), g["hafta_no"].to_numpy()] = g["deger"].to_numpy()
        a = paylar[paylar["kategori"] == kat.get(ur)].set_index("magaza_kodu")["agirlik"].to_dict()
        E = _beklenen(tahmin_kh[tahmin_kh["ur_id"] == ur], magazalar, mag_kume, a, H)
        politikalar = {
            "tek_sefer_esit": _politika_tek_sefer(np.ones(len(magazalar))),
            "tek_sefer_pay": _politika_tek_sefer(E.sum(1)),
            "model": _politika_model(E, ayar),
            **{f"model_kapsama_{n}": _politika_model(E, replace(ayar, kapsama_hafta=n)) for n in ayar.kapsama_alternatif},
        }
        if sevk is not None:
            gs = sevk[(sevk["ur_id"] == ur) & sevk["magaza_kodu"].isin(idx)]
            if len(gs):
                Sv = np.zeros((len(magazalar), H))
                np.add.at(Sv, (gs["magaza_kodu"].map(idx).to_numpy(), gs["varis_hafta"].to_numpy()), gs["adet"].to_numpy(float))
                ilk = Sv[:, 0].copy()

                def karar(k, d, Sv=Sv, ilk=ilk):
                    return ilk if k == -1 else (Sv[:, k + 1] if k + 1 < H else np.zeros(len(ilk)))
                politikalar["gerceklesen"] = karar
        for ad, karar in politikalar.items():
            r = _simule(D, arz[ur], karar)
            satir.append(dict(test_sezonu=T, ur_id=ur, politika=ad, arz=float(arz[ur].sum()),
                              **{k: float(v) for k, v in r.items() if np.isscalar(v)}))
            for m, i in idx.items():
                magaza_satir.append(dict(test_sezonu=T, ur_id=ur, politika=ad, magaza_kodu=m, bolge=mag_bolge[m],
                                         talep=float(D[i].sum()), satilan=float(r["satis_magaza"][i]),
                                         kacan_satis=float(r["kacan_magaza"][i]), kalan=float(r["kalan_magaza"][i])))
    urun = pd.DataFrame(satir)
    if urun.empty:
        return dict(urun=urun, ozet=pd.DataFrame(), bolge=pd.DataFrame(), notlar=pd.DataFrame([dict(test_sezonu=T, not_="Dağıtım testi için arz (satın alma) verisi bulunamadı.")]))
    # karşılaştırma yalnızca bütün politikaların koştuğu ürünlerde (gerçek sevki olmayan ürün varsa diğerleri de dışarıda)
    n_pol = urun.groupby("ur_id")["politika"].nunique()
    ortak = n_pol[n_pol == n_pol.max()].index
    urun_o = urun[urun["ur_id"].isin(ortak)]
    ozet = urun_o.groupby(["test_sezonu", "politika"], as_index=False)[["arz", "talep", "satilan", "kacan_satis", "magazada_kalan", "depoda_kalan", "sevk_satiri"]].sum()
    ozet["urun"] = len(ortak)
    ozet["karsilanan_talep"] = ozet["satilan"] / ozet["talep"]
    ozet["satis_orani"] = ozet["satilan"] / ozet["arz"]
    ozet["hedef"] = hedef_ad
    ms = pd.DataFrame(magaza_satir)
    bolge = ms[ms["ur_id"].isin(ortak)].groupby(["test_sezonu", "politika", "bolge"], as_index=False)[["talep", "satilan", "kacan_satis", "kalan"]].sum()
    notlar = pd.DataFrame([dict(test_sezonu=T, urun_toplam=talep["ur_id"].nunique(), urun_karsilastirilan=len(ortak), arzsiz_atlanan=atlanan,
                                gercek_sevk_var=sevk is not None)])
    return dict(urun=urun, ozet=ozet, bolge=bolge, notlar=notlar)
