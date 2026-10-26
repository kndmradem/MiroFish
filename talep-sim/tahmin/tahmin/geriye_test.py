"""Geriye dönük test: eski sezonlarla eğit, saklanan sezonu tahmin et, basit yöntemlerle kıyasla.

Her test sezonu T için:
  1. Karar anı = T başlangıcı - karar_oncesi_hafta. Yalnızca o ana kadar tamamen bitmiş sezonlar görülür.
  2. Doğrulama sezonu V = görülen en son sezon. Her yöntem V'yi kendi karar anı kuralıyla tahmin eder;
     V'deki hatalardan aralıklar (konformal) öğrenilir.
  3. Her yöntem T'yi tahmin eder, aralıklar uygulanır.
  4. T'nin gerçekleşmesiyle (stok bitişi düzeltilmiş talep, ham satış, sentetikte gerçek talep) kıyaslanır.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .belirsizlik import SEVIYELER, KonformalAralik, kantil_degeri, q_kolon
from .benzerlik import BenzerlikIndeksi
from .gorsel import gomucu_sec, urun_gomuleri
from .hazirlik import Panel, kume_haftalik, panel_kur
from .metrikler import ozet
from .modeller import YONTEMLER, Baglam, haftaya_dagit
from .yukleme import yukle

SEVIYE_ANAHTAR = {
    "urun": ["ur_id"],
    "urun_bolge": ["ur_id", "bolge"],
    "urun_kume": ["ur_id", "kume"],
    "urun_kume_hafta": ["ur_id", "kume", "hafta_no"],
}
SEVIYE_AD = {
    "urun": "Model-renk toplamı (üretim kararı)",
    "urun_bolge": "Model-renk x bölge",
    "urun_kume": "Model-renk x mağaza kümesi",
    "urun_kume_hafta": "Model-renk x mağaza kümesi x hafta",
}
Q = [q_kolon(s) for s in SEVIYELER]


@dataclass
class TestAyar:
    __test__ = False
    karar_oncesi_hafta: int = 16
    test_sezonlari: list[str] | None = None  # None: son sezon
    komsu_sayisi: int = 10
    gorsel_modeli: str = "renk_doku"
    yontemler: list[str] = field(default_factory=lambda: list(YONTEMLER))
    # gazeteci (newsvendor) değer analizi varsayımları
    ortalama_indirim: float = 0.20     # etiket fiyatına göre ortalama tahsil edilen indirim
    hurda_orani: float = 0.30          # satılmayan stoğun maliyete göre geri kazanımı (outlet vb.)


@dataclass
class TestSonucu:
    __test__ = False
    ayar: TestAyar
    panel: Panel
    metrikler: pd.DataFrame
    tahminler: dict[str, pd.DataFrame]   # seviye -> tüm yöntemlerin tahminleri + gerçekleşme
    benzer: pd.DataFrame
    beden: pd.DataFrame
    deger: pd.DataFrame
    sentetik: bool
    egitim: dict[str, list[str]]
    dogrulama: dict[str, str]
    gorsel_var: bool


def _gercekler(panel: Panel, hedef: str) -> dict[str, pd.DataFrame]:
    """Test sezonunun gerçekleşmesi, küme x hafta düzeyinde: talep (düzeltilmiş), satis, gercek (sentetik)."""
    out = {}
    for kolon in ("talep", "satis"):
        kh = kume_haftalik(panel, kolon)
        out[kolon] = kh[kh["sezon_kodu"] == hedef].drop(columns=["sezon_kodu", "magaza"])
    if panel.gercek is not None:
        g = panel.gercek[panel.gercek["sezon_kodu"] == hedef]
        # yalnızca panelde dağıtılmış sayılan mağaza-haftalar (aynı kapsam)
        g = g.merge(panel.haftalik[panel.haftalik["sezon_kodu"] == hedef][["ur_id", "magaza_kodu", "hafta_no"]], on=["ur_id", "magaza_kodu", "hafta_no"])
        g = g.merge(panel.magazalar[["magaza_kodu", "kume", "bolge"]], on="magaza_kodu")
        out["gercek"] = g.groupby(["ur_id", "kume", "bolge", "hafta_no"], as_index=False).agg(deger=("gercek_talep", "sum"))
    return out


def _seviyeye(tahmin_hafta: pd.DataFrame, seviye: str) -> pd.DataFrame:
    return tahmin_hafta.groupby(SEVIYE_ANAHTAR[seviye], as_index=False)["tahmin"].sum()


def _gercek_seviye(gercek: pd.DataFrame, seviye: str) -> pd.DataFrame:
    return gercek.groupby(SEVIYE_ANAHTAR[seviye], as_index=False)["deger"].sum()


def _tahmin_hafta(b: Baglam, yontem: str, hedef: str) -> pd.DataFrame:
    t = YONTEMLER[yontem]().tahmin(b, hedef)
    return haftaya_dagit(b, hedef, t)


def calistir(veri: str | Path, ayar: TestAyar | None = None) -> TestSonucu:
    ayar = ayar or TestAyar()
    vs = yukle(veri)
    panel = panel_kur(vs)
    gomuler = urun_gomuleri(vs.get("urun_gorselleri"), vs.klasor, gomucu_sec(ayar.gorsel_modeli))
    indeks = BenzerlikIndeksi(panel.urunler, gomuler)
    b = Baglam(panel, indeks, ayar.karar_oncesi_hafta, ayar.komsu_sayisi)

    testler = ayar.test_sezonlari or [panel.sezonlar["sezon_kodu"].iloc[-1]]
    metrik_satir, tahmin_parca, benzer_parca, beden_parca, deger_parca = [], {s: [] for s in SEVIYE_ANAHTAR}, [], [], []
    egitim, dogrulama = {}, {}
    for T in testler:
        gecmis = b.gecmis_sezonlar(T)
        if not gecmis:
            raise ValueError(f"{T}: karar anından ({ayar.karar_oncesi_hafta} hafta önce) önce bitmiş sezon yok.")
        V = gecmis[-1]
        if not b.gecmis_sezonlar(V):
            raise ValueError(f"{T}: doğrulama sezonu {V} için eğitim sezonu yok; aralıklar öğrenilemez. En az 3 sezon gerekir.")
        egitim[T], dogrulama[T] = gecmis, V
        gercek_T = _gercekler(panel, T)
        gercek_V = _gercekler(panel, V)["talep"]

        for yontem in ayar.yontemler:
            th_V = _tahmin_hafta(b, yontem, V)
            th_T = _tahmin_hafta(b, yontem, T)
            for seviye in SEVIYE_ANAHTAR:
                anahtar = SEVIYE_ANAHTAR[seviye]
                v = _seviyeye(th_V, seviye).merge(_gercek_seviye(gercek_V, seviye), on=anahtar, how="left").fillna({"deger": 0})
                aralik = KonformalAralik().ogren(v["tahmin"].to_numpy(), v["deger"].to_numpy())
                t = _seviyeye(th_T, seviye)
                t = pd.concat([t.reset_index(drop=True), aralik.uygula(t["tahmin"].to_numpy())], axis=1)
                for hedef_ad, g in gercek_T.items():
                    t = t.merge(_gercek_seviye(g, seviye).rename(columns={"deger": hedef_ad}), on=anahtar, how="left").fillna({hedef_ad: 0})
                for hedef_ad in gercek_T:
                    metrik_satir.append(dict(test_sezonu=T, yontem=yontem, seviye=seviye, hedef=hedef_ad, **ozet(t, hedef_ad)))
                tahmin_parca[seviye].append(t.assign(test_sezonu=T, yontem=yontem))

        benzer_parca.append(_benzer_aciklama(b, T, gecmis))
        beden_parca.append(_beden_degerlendir(panel, T, gecmis))
        urun_t = [x for x in tahmin_parca["urun"] if x["test_sezonu"].iat[0] == T]
        deger_parca.append(_deger_analizi(panel, T, pd.concat(urun_t), ayar))

    return TestSonucu(
        ayar=ayar, panel=panel, metrikler=pd.DataFrame(metrik_satir),
        tahminler={s: pd.concat(p, ignore_index=True) for s, p in tahmin_parca.items()},
        benzer=pd.concat(benzer_parca, ignore_index=True), beden=pd.concat(beden_parca, ignore_index=True),
        deger=pd.concat(deger_parca, ignore_index=True), sentetik=panel.gercek is not None,
        egitim=egitim, dogrulama=dogrulama, gorsel_var=indeks.gorsel_var)


def _benzer_aciklama(b: Baglam, hedef: str, gecmis: list[str], k: int = 5) -> pd.DataFrame:
    """Her test ürünü için en benzer k geçmiş ürün ve gerçekleşen mağaza başı talebi / toplam satışı."""
    y = b.y
    hedefler = y[y["sezon_kodu"] == hedef][["sezon_kodu", "ur_id"]].drop_duplicates()
    adaylar = y[y["sezon_kodu"].isin(gecmis)][["sezon_kodu", "ur_id"]].drop_duplicates()
    komsu = b.indeks.komsular(hedefler, adaylar, k=k)
    ozet_k = y.groupby(["sezon_kodu", "ur_id"], as_index=False).agg(talep=("deger", "sum"), magaza=("magaza_sayisi", "sum"))
    ozet_k["magaza_basi"] = ozet_k["talep"] / ozet_k["magaza"]
    satis = b.panel.haftalik.groupby(["sezon_kodu", "ur_id"], as_index=False)["satis"].sum()
    ozet_k = ozet_k.merge(satis, on=["sezon_kodu", "ur_id"])
    u = b.panel.urunler[["sezon_kodu", "ur_id", "kategori", "kalip", "desen", "kumas", "renk_kodu", "goreli_fiyat"]]
    k_ = komsu.merge(ozet_k.rename(columns={"sezon_kodu": "komsu_sezon", "ur_id": "komsu_ur"}), on=["komsu_sezon", "komsu_ur"], how="left")
    k_ = k_.merge(u.rename(columns={"sezon_kodu": "komsu_sezon", "ur_id": "komsu_ur"}), on=["komsu_sezon", "komsu_ur"], how="left")
    return k_.assign(test_sezonu=hedef)


def _beden_degerlendir(panel: Panel, hedef: str, gecmis: list[str]) -> pd.DataFrame:
    """Beden eğrisi: geçmiş sezonların bölge x kategori beden payı, test sezonundaki gerçek payla kıyaslanır.

    Hata = 0.5 x sum|gerçek pay - önerilen pay| (model-renk x bölge başına, adetle ağırlıklı), yani
    "üretimin yüzde kaçı yanlış bedenlere gitmiş olurdu". Kıyas: tüm bedenlere eşit dağıtım.
    """
    bs = panel.beden_satis
    tr = bs[bs["sezon_kodu"].isin(gecmis)].groupby(["bolge", "kategori", "beden"], as_index=False)["adet"].sum()
    tr["egri"] = tr["adet"] / tr.groupby(["bolge", "kategori"])["adet"].transform("sum")
    te = bs[bs["sezon_kodu"] == hedef].copy()
    grup = ["ur_id", "bolge"]
    te["pay"] = te["adet"] / te.groupby(grup)["adet"].transform("sum")
    te = te.merge(tr[["bolge", "kategori", "beden", "egri"]], on=["bolge", "kategori", "beden"], how="left")
    te["egri"] = te["egri"].fillna(0)
    te["egri"] = (te["egri"] / te.groupby(grup)["egri"].transform("sum")).fillna(1 / te.groupby(grup)["beden"].transform("nunique"))
    te["esit"] = 1 / te.groupby(grup)["beden"].transform("nunique")
    te["h_egri"] = (te["pay"] - te["egri"]).abs()
    te["h_esit"] = (te["pay"] - te["esit"]).abs()
    u = te.groupby([*grup], as_index=False).agg(adet=("adet", "sum"), h_egri=("h_egri", "sum"), h_esit=("h_esit", "sum"))
    sonuc = []
    for b_, g in u.groupby("bolge"):
        w = g["adet"]
        sonuc.append(dict(test_sezonu=hedef, bolge=b_, adet=float(w.sum()),
                          gecmis_egri_hata=float(0.5 * (g["h_egri"] * w).sum() / w.sum()),
                          esit_dagilim_hata=float(0.5 * (g["h_esit"] * w).sum() / w.sum())))
    return pd.DataFrame(sonuc)


def _deger_analizi(panel: Panel, hedef: str, urun_tahmin: pd.DataFrame, ayar: TestAyar) -> pd.DataFrame:
    """Gazeteci (newsvendor) miktarı ile gerçekleşen alımı aynı talep karşısında kıyaslar.

    Kritik oran = (birim kâr) / (birim kâr + birim zarar). Birim kâr = etiket x (1 - ort. indirim) - maliyet;
    birim zarar = maliyet x (1 - hurda oranı). TRY etiket fiyatı ve maliyeti olan ürünler için.
    """
    if panel.satin_alma is None:
        return pd.DataFrame()
    u = panel.urunler[panel.urunler["sezon_kodu"] == hedef][["ur_id", "birim_maliyet", "maliyet_para_birimi", "liste_fiyati_try"]]
    u = u[(u["maliyet_para_birimi"] == "TRY") & u["liste_fiyati_try"].notna()]
    alim = panel.satin_alma[panel.satin_alma["sezon_kodu"] == hedef][["ur_id", "alim_adedi"]]
    satirlar = []
    for yontem, t in urun_tahmin.groupby("yontem"):
        m = t.merge(u, on="ur_id").merge(alim, on="ur_id")
        if m.empty:
            continue
        fiyat = m["liste_fiyati_try"] * (1 - ayar.ortalama_indirim)
        c = m["birim_maliyet"]
        cu, co = (fiyat - c).clip(lower=0), c * (1 - ayar.hurda_orani)
        oran = (cu / (cu + co)).fillna(0.5)
        m["oneri"] = [round(kantil_degeri(r, o)) for (_, r), o in zip(m.iterrows(), oran)]
        for hedef_ad in [h for h in ("talep", "gercek") if h in m]:
            for plan_ad, q in (("gerceklesen_alim", m["alim_adedi"]), ("model_onerisi", m["oneri"])):
                d = m[hedef_ad]
                satilan = np.minimum(d, q)
                artan = q - satilan
                kar = fiyat * satilan - c * q + c * ayar.hurda_orani * artan
                satirlar.append(dict(test_sezonu=hedef, yontem=yontem, hedef=hedef_ad, plan=plan_ad, urun=len(m),
                                     uretim=float(q.sum()), talep=float(d.sum()), satilan=float(satilan.sum()),
                                     kacan_satis=float((d - satilan).sum()), artan_stok=float(artan.sum()), brut_kar_try=float(kar.sum()),
                                     kritik_oran_medyan=float(oran.median())))
    return pd.DataFrame(satirlar)
