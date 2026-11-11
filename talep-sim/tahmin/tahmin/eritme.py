"""Stok eritme: indirim esnekliği ve kampanya önerisi (gölge mod).

Üç parça:

1. ``fiyat_oranlari``: her ürün x mağaza x sezon haftası için ödenen fiyatın etiket fiyatına oranı
   (kalıcı indirim x kampanya, kampanyanın o haftadaki gün payıyla). Kaynak: fiyat_gecmisi, kampanyalar,
   kampanya_kapsami. Satış satırındaki net/brüt tutardan bağımsız hesaplanır; böylece satış olmayan haftalarda
   da fiyat bilinir.

2. ``esneklik_ogren``: "indirim satışı kaç kat artırıyor" sorusu, müşterinin kendi geçmişinden.
   Poisson modeli: satış ~ exp(ürün-mağaza etkisi + sezon-hafta-ülke-kategori etkisi - e x log(fiyat oranı)).
   Ürün-mağaza etkisi kötü satan ürüne indirim yapılmasının (seçim yanlılığı) düzey kısmını, hafta etkisi
   bütün zincirde aynı haftada olan kampanyaları ve özel günleri emer. Bu yüzden e yalnızca aynı haftada
   indirime giren ile girmeyen ürün/mağaza farkından öğrenilir (fark-içinde-fark mantığı). Zincir geneli
   kampanyalar (sezon sonu, Black Friday) bu tahmine katkı vermez; bu bir sınırdır ve raporda yazılır.
   Stokta bulunma oranı A >= 0,5 olan haftalar satış / A ile kullanılır. Aralık: ürün bazında küme bootstrap.

3. ``eritme_onerisi``: verilen tarihte (yalnızca o tarihe kadarki veriyle) her model-renk için eldeki stok,
   güncel satış hızı, hedef bitiş tarihine göre gereken hız ve indirim seçenekleri (satış, kalan stok,
   brüt marj, toplam katkı; esneklik aralığıyla). Öneri yalnızca kaydedilir, fiyat değiştirmez.

Etiketler: esneklik "ERP kalibrasyonu"; KDV oranı, kalan değer ve hedefler verilmezse "kural varsayımı".
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .hazirlik import Panel


@dataclass
class EritmeAyar:
    indirimler: tuple[float, ...] = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5)  # mevcut fiyata ek indirim seçenekleri
    hedef_brut_marj: float = 0.35      # kural varsayımı: ticari_hedefler yoksa
    kalan_deger_orani: float = 0.50    # kural varsayımı: hedef tarihte kalan stok maliyetin bu kadarıyla çıkar
    kdv_orani: float = 0.10            # kural varsayımı: etiket fiyatı KDV dahil
    oncelik: str = "kar"               # "kar" (marj tabanı içinde en yüksek katkı) ya da "tarih" (hedef tarihte bitir)
    hiz_hafta: int = 3                 # güncel satış hızı kaç haftadan
    sisman_esik: float = 1.2           # kapsama süresi kalan haftaların bu katından uzunsa "şişmiş"
    bootstrap: int = 30
    tohum: int = 0
    min_indirimli_gozlem: int = 200    # bir grup için ayrı esneklik ancak bu kadar indirimli gözlem varsa
    grup: str = "bolge"                # esneklik grubu: "bolge" ya da "kategori" ya da "tumu"
    min_A: float = 0.5                 # esneklik: stokta bulunma oranı en az bu kadar olan haftalar (satış / A ile düzeltilir)
    esneklik_tau: float = 0.25         # kural varsayımı: gruplar arası gerçek esneklik farkının tipik büyüklüğü (büzülme)


# ----------------------------------------------------------------------------- fiyat oranı

def _izgara(panel: Panel) -> pd.DataFrame:
    hw = panel.haftalik[["sezon_kodu", "ur_id", "magaza_kodu", "hafta_no", "satis", "A"]].copy()
    hw = hw.merge(panel.sezonlar[["sezon_kodu", "baslangic"]], on="sezon_kodu")
    hw["hafta_bas"] = hw["baslangic"] + pd.to_timedelta(hw["hafta_no"] * 7, unit="D")
    hw = hw.drop(columns="baslangic")
    u = panel.urunler[["sezon_kodu", "ur_id", "urun_kodu", "renk_kodu", "kategori"]]
    m = panel.magazalar[["magaza_kodu", "ulke", "kanal", "bolge"]]
    return hw.merge(u, on=["sezon_kodu", "ur_id"]).merge(m, on="magaza_kodu")


def _raf_orani(vs, g: pd.DataFrame) -> pd.Series:
    """Hafta ortasında geçerli raf fiyatı / liste fiyatı (kalıcı indirim). En özel kapsam (mağaza > kanal > ülke) kazanır."""
    f = vs.get("fiyat_gecmisi")
    out = pd.Series(1.0, index=g.index)
    if f is None or f.empty:
        return out
    f = f.copy()
    f["oran"] = (f["raf_fiyati"].fillna(f["liste_fiyati"]) / f["liste_fiyati"]).clip(0.05, 1.0)
    f["bitis_tarihi"] = f["bitis_tarihi"].fillna(pd.Timestamp("2200-01-01"))
    orta = g["hafta_bas"] + pd.Timedelta(days=3)
    g2 = g.assign(_i=g.index, orta=orta)
    for tip, anahtar in (("ulke", "ulke"), ("kanal", "kanal"), ("magaza", "magaza_kodu")):
        ff = f[f["kapsam_tipi"] == tip]
        if ff.empty:
            continue
        x = g2.merge(ff[["urun_kodu", "renk_kodu", "kapsam_kodu", "baslangic_tarihi", "bitis_tarihi", "oran"]].rename(columns={"renk_kodu": "_renk"}),
                     left_on=["urun_kodu", anahtar], right_on=["urun_kodu", "kapsam_kodu"])
        x = x[(x["_renk"].isna() | (x["_renk"] == x["renk_kodu"])) & (x["baslangic_tarihi"] <= x["orta"]) & (x["bitis_tarihi"] >= x["orta"])]
        x = x.sort_values("_renk", na_position="first").drop_duplicates("_i", keep="last")  # renge özel satır önce gelir
        out.loc[x["_i"].to_numpy()] = x["oran"].to_numpy()
    return out


def _kampanya_orani(vs, g: pd.DataFrame) -> pd.Series:
    """Haftada geçerli kampanya indirimi x kampanyanın o haftadaki gün payı (kampanyalar üst üste binmez, en büyüğü)."""
    k = vs.get("kampanyalar")
    out = pd.Series(0.0, index=g.index)
    if k is None or k.empty:
        return out
    k = k[k["indirim_orani"].notna()].copy()
    kap = vs.get("kampanya_kapsami")
    kap = pd.DataFrame({"kampanya_kodu": k["kampanya_kodu"]}) if kap is None or kap.empty else kap.copy()
    for c in ("magaza_kodu", "ulke", "urun_kodu", "kategori"):
        if c not in kap:
            kap[c] = np.nan
    haftalar = np.sort(g["hafta_bas"].unique())
    satir = []
    for r in k.itertuples(index=False):
        for hb in haftalar[(haftalar <= np.datetime64(r.bitis_tarihi)) & (haftalar + np.timedelta64(6, "D") >= np.datetime64(r.baslangic_tarihi))]:
            hb = pd.Timestamp(hb)
            gun = (min(pd.Timestamp(r.bitis_tarihi), hb + pd.Timedelta(days=6)) - max(pd.Timestamp(r.baslangic_tarihi), hb)).days + 1
            satir.append((r.kampanya_kodu, hb, float(r.indirim_orani) * gun / 7, r.kanal if isinstance(r.kanal, str) and r.kanal else None))
    if not satir:
        return out
    kh = pd.DataFrame(satir, columns=["kampanya_kodu", "hafta_bas", "etkin", "k_kanal"]).merge(kap, on="kampanya_kodu")
    x = g.assign(_i=g.index)[["_i", "hafta_bas", "magaza_kodu", "ulke", "urun_kodu", "kategori", "kanal"]].merge(kh, on="hafta_bas", suffixes=("", "_k"))
    uy = (x["k_kanal"].isna() | (x["k_kanal"] == x["kanal"]))
    for c in ("magaza_kodu", "ulke", "urun_kodu", "kategori"):
        uy &= x[f"{c}_k"].isna() | (x[f"{c}_k"] == x[c])
    x = x[uy].groupby("_i")["etkin"].max()
    out.loc[x.index] = x.to_numpy()
    return out


def _rakip_maruz(vs, g: pd.DataFrame) -> pd.Series:
    """Haftanın herhangi bir gününde rakip kampanyasına (rakip_kampanyalari: ülke x kanal x kategori) maruz kalan satırlar."""
    rk = vs.get("rakip_kampanyalari")
    out = pd.Series(False, index=g.index)
    if rk is None or rk.empty:
        return out
    hb = g["hafta_bas"]
    for r in rk.itertuples(index=False):
        m = (hb <= pd.Timestamp(r.bitis_tarihi)) & (hb + pd.Timedelta(days=6) >= pd.Timestamp(r.baslangic_tarihi))
        for c, v in (("ulke", r.ulke), ("kanal", r.kanal), ("kategori", r.kategori)):
            if isinstance(v, str) and v:
                m &= g[c] == v
        out |= m
    return out


def fiyat_oranlari(vs, panel: Panel) -> pd.DataFrame:
    """sezon_kodu, ur_id, magaza_kodu, hafta_no (+ satis, A, kategori, bolge, ...) ve raf_orani, kampanya_orani, oran, rakip_maruz."""
    g = _izgara(panel)
    g["raf_orani"] = _raf_orani(vs, g)
    g["kampanya_orani"] = _kampanya_orani(vs, g)
    g["oran"] = (g["raf_orani"] * (1 - g["kampanya_orani"])).clip(0.05, 1.0)
    g["rakip_maruz"] = _rakip_maruz(vs, g)
    return g


# ----------------------------------------------------------------------------- esneklik

MIN_BILGI = 1.0  # ölçülebilir esneklik için gereken en az artık fiyat farkı bilgisi (Fisher bilgisi, satış adedi x log fiyat farkı kare)

def _poisson_fe(y: np.ndarray, x: np.ndarray, a_id: np.ndarray, w_id: np.ndarray, b_id: np.ndarray, iter_: int = 50,
                bilgi: bool = False):
    """y ~ Poisson(exp(a[a_id] + w[w_id] + beta[b_id] * x)).

    Sabit etkiler kapalı formla güncellenir; beta için x'in sabit etkilerden arındırılmış hali (μ ağırlıklı
    ardışık izdüşüm) ile Newton adımı atılır. Arındırma yapılmazsa adım çok küçük kalır ve tahmin sıfıra
    doğru yanlı durur. Her sabit etki hücresi tek bir beta grubuna (bölge) ait olmalıdır.
    bilgi=True ise (beta, hess) döner: hess, sabit etkilerden arta kalan fiyat farkının ağırlıklı karesidir; sıfıra
    yakınsa fiyat farkı tamamen ürün ve hafta etkileriyle açıklanıyor demektir ve beta ölçülemez.
    """
    na, nw, nb = a_id.max() + 1, w_id.max() + 1, b_id.max() + 1
    a, w, beta = np.zeros(na), np.zeros(nw), np.zeros(nb)
    hess = np.zeros(nb)
    ya = np.bincount(a_id, y, minlength=na)
    yw = np.bincount(w_id, y, minlength=nw)
    for _ in range(iter_):
        for _ in range(3):
            e = np.exp(w[w_id] + beta[b_id] * x)
            a = np.log(np.maximum(ya, 1e-12) / np.maximum(np.bincount(a_id, e, minlength=na), 1e-300))
            e = np.exp(a[a_id] + beta[b_id] * x)
            w = np.log(np.maximum(yw, 1e-12) / np.maximum(np.bincount(w_id, e, minlength=nw), 1e-300))
        mu = np.exp(a[a_id] + w[w_id] + beta[b_id] * x)
        xt = x.copy()
        for _ in range(8):
            for ids, n in ((a_id, na), (w_id, nw)):
                xt -= (np.bincount(ids, mu * xt, minlength=n) / np.maximum(np.bincount(ids, mu, minlength=n), 1e-300))[ids]
        grad = np.bincount(b_id, xt * (y - mu), minlength=nb)
        hess = np.bincount(b_id, xt * xt * mu, minlength=nb)
        adim = np.where(hess > 0, grad / np.maximum(hess, 1e-12), 0.0)
        beta = beta + np.clip(adim, -1, 1)
        if np.abs(adim).max() < 1e-5:
            break
    return (beta, hess) if bilgi else beta


def esneklik_ogren(g: pd.DataFrame, sezonlar: list[str], ayar: EritmeAyar | None = None) -> pd.DataFrame:
    """g: fiyat_oranlari çıktısı. Sonuç: grup, e (satış ~ oran^-e), e_alt, e_ust (%80), indirimli_gozlem, gozlem, kaynak."""
    ayar = ayar or EritmeAyar()
    d = g[g["sezon_kodu"].isin(sezonlar) & (g["A"] >= ayar.min_A)].copy()
    if "rakip_maruz" in d:
        # rakip kampanyası haftalarında bizim indirimimiz çoğu zaman rakibe yanıttır; aynı anda rakip talebi düşürür.
        # Bu haftalar alınırsa esneklik olduğundan düşük çıkar.
        d = d[~d["rakip_maruz"]]
    d["x"] = np.log(d["oran"])
    # hafta etkisi ülke düzeyinde: ülkeye özel bayram/özel gün talep artışları kampanyayla aynı haftaya düşerse esnekliği şişirmesin
    d["_w"] = d["sezon_kodu"] + "|" + d["hafta_no"].astype(str) + "|" + d["ulke"] + "|" + d["kategori"]
    d["_a"] = d["sezon_kodu"] + "|" + d["ur_id"] + "|" + d["magaza_kodu"]
    # Not: fiyatı hiç değişmeyen ürün-mağazalar ve hücreler atılmaz; onlar hafta etkisini ve indirim öncesi düzeyi
    # belirleyen kontrol gözlemleridir. Yalnızca hiç satışı olmayan birimler (bilgi taşımaz) çıkarılır.
    d = d[d.groupby("_a")["satis"].transform("sum") > 0]
    d = d[d.groupby("_w")["satis"].transform("sum") > 0]
    if ayar.grup == "tumu" or d.empty:
        d["_g"] = "tümü"
    else:
        d["_g"] = d[ayar.grup]
        indirimli = d[d["x"] < np.log(0.97)].groupby("_g").size()
        az = indirimli[indirimli < ayar.min_indirimli_gozlem].index
        d.loc[d["_g"].isin(az), "_g"] = "diğer"
    if d.empty:
        return pd.DataFrame(columns=["grup", "e", "e_alt", "e_ust", "e_ham", "e_ham_alt", "e_ham_ust", "indirimli_gozlem", "gozlem", "kaynak"])
    gruplar = sorted(d["_g"].unique())
    b_id = d["_g"].map({k: i for i, k in enumerate(gruplar)}).to_numpy()
    a_id = pd.factorize(d["_a"])[0]
    w_id = pd.factorize(d["_w"])[0]
    y, x = (d["satis"] / d["A"]).to_numpy(float), d["x"].to_numpy(float)
    rng = np.random.default_rng(ayar.tohum)
    urunler = d["ur_id"].to_numpy()
    tekil = np.unique(urunler)
    konum = {u: np.where(urunler == u)[0] for u in tekil}
    ornekler = [rng.choice(tekil, len(tekil), replace=True) for _ in range(ayar.bootstrap)]

    def tahmin(bid):
        beta, hess = _poisson_fe(y, x, a_id, w_id, bid, bilgi=True)
        if ayar.bootstrap < 2:
            return -beta, -beta, -beta, hess
        boot = []
        for sec in ornekler:  # ürün bazında küme bootstrap
            idx = np.concatenate([konum[u] for u in sec])
            kopya = np.repeat(np.arange(len(sec)), [len(konum[u]) for u in sec])
            a_b = pd.factorize(pd.Series(a_id[idx]).astype(str) + "#" + pd.Series(kopya).astype(str))[0]
            boot.append(_poisson_fe(y[idx], x[idx], a_b, pd.factorize(w_id[idx])[0], bid[idx], iter_=25))
        boot = -np.array(boot)
        return -beta, np.quantile(boot, 0.1, axis=0), np.quantile(boot, 0.9, axis=0), hess

    e, alt, ust, hess = tahmin(b_id)
    olculemez = hess < MIN_BILGI  # fiyat farkı sabit etkilerle tamamen açıklanıyor
    satir = [dict(grup=k, e_ham=float(e[i]), e_ham_alt=float(alt[i]), e_ham_ust=float(ust[i]),
                  indirimli_gozlem=int((x[b_id == i] < np.log(0.97)).sum()), gozlem=int((b_id == i).sum()))
             for i, k in enumerate(gruplar)]
    df = pd.DataFrame(satir)
    df.loc[olculemez, ["e_ham", "e_ham_alt", "e_ham_ust"]] = np.nan
    if len(gruplar) > 1:
        # gruplar az veriyle oynak: tüm veriden ortak esnekliğe doğru büzülür (ampirik Bayes, gruplar arası fark ölçeği tau)
        ep, pa, pu, hp = (v[0] for v in tahmin(np.zeros_like(b_id)))
        if hp < MIN_BILGI:
            return pd.DataFrame(columns=df.columns.tolist() + ["e", "e_alt", "e_ust", "kaynak"])
        sig = ((df["e_ham_ust"] - df["e_ham_alt"]) / 2.563).clip(lower=0.02).fillna(np.inf)
        sig_p = max((pu - pa) / 2.563, 0.02)
        h = 1 / sig**2 + 1 / ayar.esneklik_tau**2
        df["e"] = (df["e_ham"].fillna(0) / sig**2 + ep / ayar.esneklik_tau**2) / h
        s_ = np.sqrt(1 / h + sig_p**2)
        df["e_alt"], df["e_ust"] = df["e"] - 1.2816 * s_, df["e"] + 1.2816 * s_
        df = pd.concat([df, pd.DataFrame([dict(grup="tümü", e_ham=ep, e_ham_alt=pa, e_ham_ust=pu, indirimli_gozlem=int((x < np.log(0.97)).sum()),
                                               gozlem=len(x), e=ep, e_alt=pa, e_ust=pu)])], ignore_index=True)
    else:
        if olculemez.all():
            return pd.DataFrame(columns=df.columns.tolist() + ["e", "e_alt", "e_ust", "kaynak"])
        df["e"], df["e_alt"], df["e_ust"] = df["e_ham"], df["e_ham_alt"], df["e_ham_ust"]
    df["kaynak"] = "ERP kalibrasyonu"
    return df[["grup", "e", "e_alt", "e_ust", "e_ham", "e_ham_alt", "e_ham_ust", "indirimli_gozlem", "gozlem", "kaynak"]]


# ----------------------------------------------------------------------------- öneri

@dataclass
class EritmeSonucu:
    tarih: pd.Timestamp
    esneklik: pd.DataFrame
    urunler: pd.DataFrame       # ürün başına durum + önerilen seçenek
    secenekler: pd.DataFrame    # ürün x indirim seçeneği
    bolge: pd.DataFrame         # ürün x bölge stok kapsaması
    projeksiyon: pd.DataFrame = field(default_factory=pd.DataFrame)  # ürün x kalan hafta: bugünkü fiyatla beklenen talep
    kalibrasyon: dict | None = None  # geçen sezon aynı haftada aynı yöntemin isabeti
    notlar: list[str] = field(default_factory=list)


def _profil(g: pd.DataFrame, sezonlar: list[str], esn: dict, varsayilan_e: float) -> pd.DataFrame:
    """Kategori x sezon tipi x hafta: indirimden arındırılmış (satış x oran^e) stokta-hafta ortalaması, ortalaması 1."""
    d = g[g["sezon_kodu"].isin(sezonlar) & (g["A"] >= 0.9)].copy()
    d["sezon_tipi"] = d["sezon_kodu"].str.split("-").str[-1]
    e = d["bolge"].map(esn).fillna(varsayilan_e)
    d["arinmis"] = d["satis"] * d["oran"] ** e
    p = d.groupby(["kategori", "sezon_tipi", "hafta_no"], as_index=False)["arinmis"].mean().rename(columns={"arinmis": "p"})
    p["p"] = p["p"] / p.groupby(["kategori", "sezon_tipi"])["p"].transform("mean")
    return p


def _iade_oranlari(vs, tarih: pd.Timestamp) -> tuple[dict, float]:
    """Kategori başına iade adedi / satış adedi, tarihe kadarki veriden. İade edilen ürün stoğa döner ve yeniden satılır."""
    sa, ia = vs.get("satislar"), vs.get("iadeler")
    if sa is None or ia is None or sa.empty or ia.empty:
        return {}, 0.0
    kat = vs["skular"][["sku_kodu", "urun_kodu"]].merge(vs["urunler"][["urun_kodu", "kategori"]].drop_duplicates("urun_kodu"), on="urun_kodu")
    kat = kat.set_index("sku_kodu")["kategori"]
    s_ = sa[sa["tarih"] <= tarih].groupby(sa["sku_kodu"].map(kat))["adet"].sum()
    i_ = ia[ia["tarih"] <= tarih].groupby(ia["sku_kodu"].map(kat))["adet"].sum()
    genel = float(i_.sum() / s_.sum()) if s_.sum() > 0 else 0.0
    oran = (i_.reindex(s_.index).fillna(0) / s_.where(s_ >= 200)).dropna().clip(0, 0.6)
    return oran.to_dict(), min(genel, 0.6)


def _hedef(hedefler, T: str, u) -> dict:
    """ticari_hedefler'den en özel satır (ürün > kategori > genel); boş alanlar None."""
    if hedefler is None or not len(hedefler):
        return {}
    h = hedefler[(hedefler["sezon_kodu"] == T) & (((hedefler["kapsam_tipi"] == "urun") & (hedefler["kapsam_kodu"] == u["urun_kodu"]))
                                                 | ((hedefler["kapsam_tipi"] == "kategori") & (hedefler["kapsam_kodu"] == u["kategori"]))
                                                 | (hedefler["kapsam_tipi"] == "genel"))]
    if not len(h):
        return {}
    h = h.assign(_o=h["kapsam_tipi"].map({"urun": 0, "kategori": 1, "genel": 2})).sort_values("_o")
    out = {}
    for c in ("hedef_brut_marj", "hedef_bitis_tarihi", "taban_fiyat", "kalan_deger_orani", "indirim_basamaklari"):
        if c in h:
            v = h[c].dropna()
            if len(v):
                out[c] = v.iloc[0]  # en özel kapsamda dolu olan değer
    return out


def _kalibrasyon(vs, panel: Panel, tarih: pd.Timestamp, ayar: EritmeAyar, g: pd.DataFrame, esn: pd.DataFrame, hedef_bitis) -> dict | None:
    """Aynı tipteki son bitmiş sezonda aynı haftada aynı yöntemi çalıştırır, sonraki gerçek satışla karşılaştırır.
    Döner: sezon, tarih, urun, wape, sapma, q10, q90 (log(gerçek/tahmin), stokla kısıtlanmamış ürünlerde)."""
    sz = panel.sezonlar
    aktif = sz[(sz["baslangic"] <= tarih) & (sz["bitis"] > tarih)].iloc[0]
    once = sz[(sz["sezon_tipi"] == aktif["sezon_tipi"]) & (sz["bitis"] <= tarih)].sort_values("bitis")
    for _, s0 in once.iloc[::-1].iterrows():
        t0 = s0["baslangic"] + (tarih - aktif["baslangic"])
        hb0 = None if hedef_bitis is None else s0["baslangic"] + (pd.Timestamp(hedef_bitis) - aktif["baslangic"])
        try:
            r0 = eritme_onerisi(vs, panel, t0, ayar, hedef_bitis=hb0, g=g, esneklik=esn, kalibrasyon=False)
        except ValueError:
            continue
        o = projeksiyon_testi(r0, g, vs)
        if o.empty:
            continue
        o = o[~o["sonradan_siparis"]]
        serbest = o[o["gercek"] < 0.9 * o["stok"]]  # stok bitmediyse gerçek satış talebi gösterir
        if len(serbest) < 10:
            continue
        lr = np.log((serbest["gercek"] + 1) / (serbest["tahmin"] + 1))
        return dict(sezon=s0["sezon_kodu"], tarih=t0, urun=len(o), serbest_urun=len(serbest),
                    wape=float((o["tahmin"] - o["gercek"]).abs().sum() / max(o["gercek"].sum(), 1)),
                    sapma=float(o["tahmin"].sum() / max(o["gercek"].sum(), 1) - 1),
                    q10=float(np.quantile(lr, 0.1)), q90=float(np.quantile(lr, 0.9)))
    return None


def eritme_onerisi(vs, panel: Panel, tarih, ayar: EritmeAyar | None = None, hedef_bitis=None, g: pd.DataFrame | None = None,
                   esneklik: pd.DataFrame | None = None, kalibrasyon: bool = True) -> EritmeSonucu:
    """``tarih`` gün sonunda, yalnızca o güne kadarki veriyle. Hedef bitiş: parametre > ticari_hedefler > sezon sonu."""
    ayar = ayar or EritmeAyar()
    tarih = pd.Timestamp(tarih)
    notlar: list[str] = []
    g = fiyat_oranlari(vs, panel) if g is None else g
    sz = panel.sezonlar
    biten = list(sz.loc[sz["bitis"] <= tarih, "sezon_kodu"])
    aktif = sz[(sz["baslangic"] <= tarih) & (sz["bitis"] > tarih)]
    if aktif.empty:
        raise ValueError(f"{tarih.date()}: bu tarihte süren sezon yok.")
    if not biten:
        raise ValueError(f"{tarih.date()}: esneklik için bu tarihten önce bitmiş sezon yok.")
    esn = esneklik_ogren(g, biten, ayar) if esneklik is None else esneklik
    if esn.empty:
        esn = pd.DataFrame([dict(grup="tümü", e=1.0, e_alt=0.5, e_ust=1.5, indirimli_gozlem=0, gozlem=0, kaynak="kural varsayımı (kalibre edilmedi)")])
        notlar.append("Geçmişte esneklik ölçülecek kadar indirim farkı yok; esneklik 1,0 (0,5-1,5) kural varsayımı.")
    e_harita = esn.set_index("grup")[["e", "e_alt", "e_ust"]]
    genel = e_harita.loc["tümü"] if "tümü" in e_harita.index else e_harita.mean()
    profil = _profil(g, biten, e_harita["e"].to_dict(), float(genel["e"]))
    kal = _kalibrasyon(vs, panel, tarih, ayar, g, esn, hedef_bitis) if kalibrasyon else None
    q10, q90 = (kal["q10"], kal["q90"]) if kal else (0.0, 0.0)
    if kalibrasyon and kal is None:
        notlar.append("Geriye dönük kalibrasyon için uygun geçmiş sezon yok; aralıklar yalnızca esneklik belirsizliğini içerir.")

    sonuc_u, sonuc_s, sonuc_b, sonuc_p = [], [], [], []
    iade, iade_genel = _iade_oranlari(vs, tarih)
    if iade_genel > 0:
        notlar.append(f"İadeler stoğa dönüp yeniden satılır varsayıldı; geçmiş iade oranı genelde %{100 * iade_genel:.0f} (ERP kalibrasyonu, kategori bazında).")
    hedefler = vs.get("ticari_hedefler")
    sku = vs["skular"][["sku_kodu", "urun_kodu", "renk_kodu"]].assign(ur_id=lambda d: d["urun_kodu"] + "|" + d["renk_kodu"])
    stok = vs["stok"]
    st_tum = stok[stok["tarih"] <= tarih]
    st_tum = st_tum[st_tum["tarih"] == st_tum.groupby(["lokasyon_kodu", "sku_kodu"])["tarih"].transform("max")]
    st_tum = st_tum.merge(sku[["sku_kodu", "ur_id"]], on="sku_kodu")
    magazalar = panel.magazalar.set_index("magaza_kodu")
    k_max = int(panel.haftalik["hafta_no"].max())
    for _, s in aktif.iterrows():
        T = s["sezon_kodu"]
        k_simdi = int((tarih - s["baslangic"]).days // 7)  # tarih bu haftanın içinde
        sezon_sonu = s["bitis"] - pd.Timedelta(days=1)
        gT = g[(g["sezon_kodu"] == T) & (g["hafta_no"] <= k_simdi)]
        urun_T = panel.urunler[panel.urunler["sezon_kodu"] == T]
        # eldeki stok: tarih itibarıyla son stok kaydı, mağaza + depo
        st = st_tum[st_tum["ur_id"].isin(urun_T["ur_id"])].copy()
        st["bolge"] = st["lokasyon_kodu"].map(magazalar["bolge"]).fillna("depo")
        # açık satın alma: tarihe kadar verilmiş, henüz teslim alınmamış ve sezon içinde gelmesi planlanan siparişler
        po = vs.get("satin_alma_siparisleri")
        if po is not None and len(po):
            ac = po[(po["siparis_tarihi"] <= tarih) & ~(po["teslim_tarihi"] <= tarih)]
            ac = ac[ac["planlanan_teslim_tarihi"].fillna(tarih) <= sezon_sonu].merge(sku[["sku_kodu", "ur_id"]], on="sku_kodu")
            acik_u = ac[ac["ur_id"].isin(urun_T["ur_id"])].groupby("ur_id")["siparis_adedi"].sum().astype(float)
        else:
            acik_u = pd.Series(dtype=float)
        st_u = st.groupby("ur_id")["eldeki_adet"].sum().add(acik_u, fill_value=0)
        # güncel hız: son hiz_hafta haftanın satışı / A (en az yarı stokta olunan haftalar), indirimden arındırılmış
        son = gT[(gT["hafta_no"] > k_simdi - ayar.hiz_hafta) & (gT["hafta_no"] <= k_simdi)]
        son = son[son["A"] >= 0.5]
        e_b = son["bolge"].map(e_harita["e"]).fillna(float(genel["e"]))
        son = son.assign(arinmis=son["satis"] / son["A"] * son["oran"] ** e_b)
        # mağaza başına geçerli haftaların ortalaması (stoksuz hafta sıfır sayılmaz), sonra bölgeye toplanır
        hiz_bolge = son.groupby(["ur_id", "bolge", "magaza_kodu"])["arinmis"].mean().groupby(level=[0, 1]).sum()
        # güncel fiyat oranı (kalıcı indirim; geçici kampanya hariç)
        oran_simdi = gT[gT["hafta_no"] == k_simdi].groupby("ur_id")["raf_orani"].mean()
        sezon_tipi = T.split("-")[-1]
        for _, u in urun_T.iterrows():
            ur = u["ur_id"]
            stok_u = float(st_u.get(ur, 0))
            if stok_u <= 0:
                continue
            h = _hedef(hedefler, T, u)
            hedef_marj = float(h.get("hedef_brut_marj", ayar.hedef_brut_marj))
            kalan_deger = float(h.get("kalan_deger_orani", ayar.kalan_deger_orani))
            taban = float(h["taban_fiyat"]) if "taban_fiyat" in h else np.nan
            basamak = ayar.indirimler
            if "indirim_basamaklari" in h:
                try:
                    basamak = tuple(sorted({0.0, *(float(v) for v in str(h["indirim_basamaklari"]).replace(";", ",").split(",") if v.strip())}))
                except ValueError:
                    pass
            bitis = pd.Timestamp(hedef_bitis) if hedef_bitis is not None else (pd.Timestamp(h["hedef_bitis_tarihi"]) if "hedef_bitis_tarihi" in h else sezon_sonu)
            k_son = min(int((bitis - s["baslangic"]).days // 7), k_max)
            kalan_hafta = list(range(k_simdi + 1, k_son + 1))
            ri = float(iade.get(u["kategori"], iade_genel))
            arz = stok_u / (1 - ri)  # brüt satılabilir adet: iade dönüşleriyle birlikte
            hb = hiz_bolge[ur] if ur in hiz_bolge.index.get_level_values(0) else pd.Series(dtype=float)
            hiz = float(hb.sum())
            w = hb / hiz if hiz > 0 else pd.Series({"tümü": 1.0})
            e = sum(float(e_harita["e"].get(b, genel["e"])) * v for b, v in w.items())
            e_alt = sum(float(e_harita["e_alt"].get(b, genel["e_alt"])) * v for b, v in w.items())
            e_ust = sum(float(e_harita["e_ust"].get(b, genel["e_ust"])) * v for b, v in w.items())
            p = profil[(profil["kategori"] == u["kategori"]) & (profil["sezon_tipi"] == sezon_tipi)].set_index("hafta_no")["p"]
            p_simdi = float(p.reindex(range(max(0, k_simdi - ayar.hiz_hafta + 1), k_simdi + 1)).mean()) if len(p) else 1.0
            p_simdi = p_simdi if np.isfinite(p_simdi) and p_simdi > 0 else 1.0
            p_ileri = p.reindex(kalan_hafta).fillna(p.mean() if len(p) else 1.0).to_numpy() if kalan_hafta else np.array([])
            ileri = hiz * p_ileri / p_simdi  # indirimsiz (bugünkü kalıcı fiyatla, kampanyasız) haftalık brüt talep
            o_simdi = float(oran_simdi.get(ur, 1.0))
            sonuc_p.append(pd.DataFrame(dict(sezon_kodu=T, ur_id=ur, hafta_no=kalan_hafta, talep=ileri, oran_simdi=o_simdi, esneklik=e,
                                             esneklik_alt=e_alt, esneklik_ust=e_ust, stok=arz)))
            liste = float(u["liste_fiyati_try"]) if pd.notna(u.get("liste_fiyati_try")) else np.nan
            maliyet = float(u["birim_maliyet"]) if u.get("maliyet_para_birimi") == "TRY" and pd.notna(u.get("birim_maliyet")) else np.nan
            hiz_net = hiz * (1 - ri)  # iade sonrası haftalık net satış hızı
            gerekli = stok_u / max(len(kalan_hafta), 1)
            kapsama = stok_u / hiz_net if hiz_net > 0 else np.inf
            secs = []
            for d_ in basamak:
                etiket = liste * o_simdi * (1 - d_) if np.isfinite(liste) else np.nan  # KDV dahil satış fiyatı
                net = etiket / (1 + ayar.kdv_orani)
                talepler = {ad: float((ileri * (1 - d_) ** (-ee)).sum()) for ad, ee in (("p50", e), ("e_dusuk", e_alt), ("e_yuksek", e_ust))}
                sat = {k: min(arz, v) * (1 - ri) for k, v in talepler.items()}  # net (iade sonrası) satış
                alt = min(arz, min(talepler["e_dusuk"], talepler["e_yuksek"]) * np.exp(q10)) * (1 - ri)
                ust = min(arz, max(talepler["e_dusuk"], talepler["e_yuksek"]) * np.exp(q90)) * (1 - ri)
                marj = (net - maliyet) / net if np.isfinite(net) and np.isfinite(maliyet) and net > 0 else np.nan
                kalan = stok_u - sat["p50"]
                katki = sat["p50"] * (net - maliyet) - kalan * maliyet * (1 - kalan_deger) if np.isfinite(marj) else np.nan
                uygun = bool(np.isfinite(marj) and marj >= hedef_marj and not (np.isfinite(taban) and etiket < taban))
                secs.append(dict(sezon_kodu=T, ur_id=ur, ek_indirim=d_, satis_fiyati=etiket, net_fiyat=net, brut_marj=marj,
                                 satis_p50=sat["p50"], satis_alt=min(alt, sat["p50"]), satis_ust=max(ust, sat["p50"]),
                                 kalan_p50=kalan, kalan_alt=stok_u - max(ust, sat["p50"]), kalan_ust=stok_u - min(alt, sat["p50"]),
                                 biter_mi=kalan <= 0.02 * stok_u, kurala_uygun=uygun, katki=katki))
            sdf = pd.DataFrame(secs)
            uygun = sdf[sdf["kurala_uygun"]]
            if ayar.oncelik == "tarih":
                aday = uygun[uygun["biter_mi"]]
                sec = aday.iloc[0] if len(aday) else (uygun.sort_values("kalan_p50").iloc[0] if len(uygun) else sdf.iloc[0])
            else:
                sec = uygun.loc[uygun["katki"].idxmax()] if len(uygun) and uygun["katki"].notna().any() else sdf.iloc[0]
            catisma = not sdf["biter_mi"].iloc[0] and not (sdf["biter_mi"] & sdf["kurala_uygun"]).any()
            sonuc_s.append(sdf)
            sonuc_u.append(dict(sezon_kodu=T, ur_id=ur, urun_kodu=u["urun_kodu"], renk_kodu=u["renk_kodu"], kategori=u["kategori"],
                                eldeki_stok=stok_u, acik_siparis=float(acik_u.get(ur, 0)), iade_orani=ri, guncel_hiz=hiz_net, gerekli_hiz=gerekli,
                                kapsama_hafta=kapsama, kalan_hafta=len(kalan_hafta), hedef_bitis=bitis,
                                sisman=bool(kapsama > ayar.sisman_esik * max(len(kalan_hafta), 1)),
                                guncel_kalici_indirim=1 - o_simdi, esneklik=e, esneklik_alt=e_alt, esneklik_ust=e_ust,
                                hedef_brut_marj=hedef_marj, kalan_deger_orani=kalan_deger, hedef_kaynagi="ticari_hedefler" if h else "kural varsayımı",
                                onerilen_ek_indirim=float(sec["ek_indirim"]), onerilen_kalan=float(sec["kalan_p50"]),
                                onerilen_katki=float(sec["katki"]) if pd.notna(sec["katki"]) else np.nan,
                                indirimsiz_kalan=float(sdf["kalan_p50"].iloc[0]), indirimsiz_katki=float(sdf["katki"].iloc[0]) if pd.notna(sdf["katki"].iloc[0]) else np.nan,
                                hedefler_celisiyor=bool(catisma), maliyet_bilinmiyor=not np.isfinite(maliyet) or not np.isfinite(liste)))
            for b, v in (hb * (1 - ri)).items():
                sb = float(st[(st["ur_id"] == ur) & (st["bolge"] == b)]["eldeki_adet"].sum())
                sonuc_b.append(dict(sezon_kodu=T, ur_id=ur, bolge=b, stok=sb, hiz=float(v), kapsama_hafta=sb / v if v > 0 else np.inf))
            depo = float(st[(st["ur_id"] == ur) & (st["bolge"] == "depo")]["eldeki_adet"].sum()) + float(acik_u.get(ur, 0))
            if depo:
                sonuc_b.append(dict(sezon_kodu=T, ur_id=ur, bolge="depo", stok=depo, hiz=0.0, kapsama_hafta=np.inf))
    urunler = pd.DataFrame(sonuc_u)
    if len(urunler):
        urunler = urunler.sort_values(["sisman", "kapsama_hafta"], ascending=False).reset_index(drop=True)
    if ayar.kdv_orani == EritmeAyar().kdv_orani:
        notlar.append(f"KDV oranı %{100 * ayar.kdv_orani:.0f} varsayıldı (kural varsayımı); etiket fiyatı KDV dahil kabul edildi.")
    return EritmeSonucu(tarih=tarih, esneklik=esn, urunler=urunler,
                        secenekler=pd.concat(sonuc_s, ignore_index=True) if sonuc_s else pd.DataFrame(), bolge=pd.DataFrame(sonuc_b),
                        projeksiyon=pd.concat(sonuc_p, ignore_index=True) if sonuc_p else pd.DataFrame(), kalibrasyon=kal, notlar=notlar)


def projeksiyon_testi(r: EritmeSonucu, g: pd.DataFrame, vs=None) -> pd.DataFrame:
    """Geriye dönük kontrol: tarihten sonra gerçekte uygulanan fiyat yolu (kalıcı indirim + kampanya) projeksiyona
    esneklikle uygulanır ve stokla kısılır; gerçekleşen satışla karşılaştırılır. Ürün başına: tahmin, alt, üst, gercek."""
    p = r.projeksiyon
    if p.empty:
        return pd.DataFrame()
    gg = g[g["sezon_kodu"].isin(p["sezon_kodu"].unique())]
    yol = gg.groupby(["sezon_kodu", "ur_id", "hafta_no"], as_index=False).agg(oran=("oran", "mean"), satis=("satis", "sum"))
    x = p.merge(yol, on=["sezon_kodu", "ur_id", "hafta_no"], how="left")
    x["oran"] = x["oran"].fillna(x["oran_simdi"])
    x["satis"] = x["satis"].fillna(0)
    goreli = (x["oran"] / x["oran_simdi"]).clip(0.05, 2)
    for ad, ec in (("tahmin", "esneklik"), ("a", "esneklik_alt"), ("b", "esneklik_ust")):
        x[ad] = x["talep"] * goreli ** (-x[ec])
    o = x.groupby(["sezon_kodu", "ur_id"]).agg(tahmin=("tahmin", "sum"), a=("a", "sum"), b=("b", "sum"), gercek=("satis", "sum"), stok=("stok", "first")).reset_index()
    q10, q90 = (r.kalibrasyon["q10"], r.kalibrasyon["q90"]) if r.kalibrasyon else (0.0, 0.0)
    o["a"], o["b"] = np.minimum(o["a"], o["b"]) * np.exp(q10), np.maximum(o["a"], o["b"]) * np.exp(q90)
    for c in ("tahmin", "a", "b"):
        o[c] = np.minimum(o[c], o["stok"])
    o["alt"], o["ust"] = np.minimum(o["a"], o["b"]), np.maximum(o["a"], o["b"])
    # tarihten sonra verilen tekrar siparişler o gün bilinemezdi: bu ürünlerde gerçek satış eldeki stoğu aşabilir
    o["sonradan_siparis"] = False
    po = vs.get("satin_alma_siparisleri") if vs is not None else None
    if po is not None and len(po):
        sku = vs["skular"].assign(ur_id=lambda d: d["urun_kodu"] + "|" + d["renk_kodu"])[["sku_kodu", "ur_id"]]
        sonra = set(po[po["siparis_tarihi"] > r.tarih].merge(sku, on="sku_kodu")["ur_id"])
        o["sonradan_siparis"] = o["ur_id"].isin(sonra) & (o["gercek"] > o["stok"])
    return o.drop(columns=["a", "b"])


def sentetik_karsi_olgu(r: EritmeSonucu, panel: Panel, g: pd.DataFrame, e_bolge: dict) -> pd.DataFrame:
    """Yalnızca sentetik veri: gerçek (kısıtsız) talep ve sentetiği üreten gerçek esneklikle, her sabit ek indirim
    seçeneğinin ve gerçekleşen fiyat yolunun (sezon sonu kampanyaları dahil) sonucu. Ürün düzeyinde, haftalık stok
    tükenmesiyle; mağaza/beden dağılımı yok sayılır (kaba kontrol). Döner: ur_id x politika: net_satis, kalan, katki."""
    if panel.gercek is None or r.projeksiyon.empty or r.secenekler.empty:
        return pd.DataFrame()
    p = r.projeksiyon[["sezon_kodu", "ur_id", "hafta_no", "oran_simdi"]]
    d = panel.gercek.merge(p, on=["sezon_kodu", "ur_id", "hafta_no"])
    d = d.merge(g[["sezon_kodu", "ur_id", "magaza_kodu", "hafta_no", "oran", "bolge"]], on=["sezon_kodu", "ur_id", "magaza_kodu", "hafta_no"], how="left")
    d["oran"] = d["oran"].fillna(d["oran_simdi"])
    d["e"] = d["bolge"].map(e_bolge).fillna(float(np.mean(list(e_bolge.values()))))
    u = r.urunler.set_index("ur_id")
    sec = r.secenekler
    satir = []
    for ur, x in d.groupby("ur_id"):
        if ur not in u.index:
            continue
        uu = u.loc[ur]
        ri, stok = float(uu["iade_orani"]), float(uu["eldeki_stok"])
        s_ur = sec[sec["ur_id"] == ur].set_index("ek_indirim")
        net0 = float(s_ur["net_fiyat"].iloc[0])
        maliyet = net0 * (1 - float(s_ur["brut_marj"].iloc[0])) if np.isfinite(s_ur["brut_marj"].iloc[0]) else np.nan
        kd = float(uu["kalan_deger_orani"])
        politikalar = {f"sabit_%{round(100 * k)}": (k, None) for k in s_ur.index}
        politikalar["gerceklesen"] = (None, None)
        for ad, (k, _) in politikalar.items():
            if k is None:
                carpan = np.ones(len(x))
                fiyat = x["oran"] / x["oran_simdi"]
            else:
                fiyat = pd.Series((1 - k), index=x.index) * 1.0
                carpan = ((x["oran_simdi"] * (1 - k)) / x["oran"]) ** (-x["e"])
            h = x.assign(talep=x["gercek_talep"] * carpan, fiyat=fiyat).groupby("hafta_no").apply(
                lambda z: pd.Series(dict(talep=z["talep"].sum(), gelir_birim=np.average(z["fiyat"], weights=z["talep"] + 1e-9))), include_groups=False)
            kalan_arz, net_adet, gelir = stok / (1 - ri), 0.0, 0.0
            for t in h.itertuples():
                s_ = min(kalan_arz, t.talep)
                kalan_arz -= s_
                net_adet += s_ * (1 - ri)
                gelir += s_ * (1 - ri) * net0 * t.gelir_birim
            kalan = stok - net_adet
            katki = gelir - net_adet * maliyet - kalan * maliyet * (1 - kd) if np.isfinite(maliyet) else np.nan
            satir.append(dict(ur_id=ur, politika=ad, ek_indirim=k, net_satis=net_adet, kalan=kalan, katki=katki,
                              onerilen=k is not None and np.isclose(k, uu["onerilen_ek_indirim"])))
    return pd.DataFrame(satir)
