"""Kampanya kaydı ve rakip etkisi (gölge mod).

Bir rakip kampanyası (rakip_kampanyalari) ve ona karşı bizim kararımız (kampanya_kararlari: yapıldı / yapılmadı,
kontrol grubu var / yok) için olaydan 1, 2 ve 4 hafta sonra şunları ölçer:

- **Rakip etkisi:** rakip kampanyasına maruz kalan ve bizim kampanyamıza girmeyen ürün-mağazaların satışı, maruz
  kalmayan benzer gruba (aynı kategori, rakip kampanyasının olmadığı ülke/kanal) göre ne kadar değişti
  (fark-içinde-fark, satış oranlarının oranı). Varsayım: rakip kampanyası olmasaydı iki grup aynı yönde hareket ederdi.
  Bu varsayım olay öncesi haftalarda aynı hesapla (plasebo) kontrol edilir.
- **Bizim yanıtımızın etkisi:** kontrol grubu varsa yanıt verilen ürünler ile bilerek dışarıda bırakılan benzer
  ürünlerin farkı (en güvenilir ölçüm). Kontrol grubu yoksa yanıt ve rakip etkisi ayrılamaz; yanıtın etkisi
  esneklikten (model varsayımı) alınır.
- **Beklenenden sapma:** olay öncesi hızın kategori sezon profiliyle ileri taşınmasıyla kurulan temel tahmine göre fark
  (model karşı-olgusalı; rakip, hava ve şans karışımıdır, "rakip etkisi" diye sunulmaz).

Bütün satışlar stok bitişine göre düzeltilir (satış / A, A >= 0,5) ve bizim yanıt kampanyamız dışındaki kendi
indirimlerimizden arındırılır (satış x oran^e). Aralıklar ürün bazında küme bootstrap ile %80.
"Pazar payı" ölçülmez: pazarın toplamını ve rakibin satışını bilmiyoruz; yerine "kaptırılan tahmini satış" verilir.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .eritme import EritmeAyar, _profil, esneklik_ogren, fiyat_oranlari
from .hazirlik import Panel


@dataclass
class EtkiAyar:
    haftalar: tuple[int, ...] = (1, 2, 4)   # olay başlangıcından itibaren ölçüm pencereleri
    once_hafta: int = 4                     # olay öncesi taban dönemi
    bootstrap: int = 300
    tohum: int = 0
    kdv_orani: float = 0.10                 # kural varsayımı
    min_birim: int = 5                      # bir grupta en az bu kadar ürün-mağaza olmalı
    min_urun: int = 3                       # ve en az bu kadar farklı ürün


@dataclass
class EtkiSonucu:
    olaylar: pd.DataFrame          # olay x hafta penceresi: ölçümler
    gruplar: pd.DataFrame          # olay x grup x dönem: düzeltilmiş satış
    havuz: pd.DataFrame = field(default_factory=pd.DataFrame)  # olaylar arası ortalama (kampanya kütüphanesi)
    esneklik: dict = field(default_factory=dict)
    notlar: list[str] = field(default_factory=list)


def _yanit_kodlari(vs) -> set[str]:
    kr = vs.get("kampanya_kararlari")
    if kr is None or kr.empty:
        return set()
    return set(kr["kampanya_kodu"].dropna().astype(str)) - {""}


def _yanitsiz_oran(vs, panel: Panel) -> pd.DataFrame:
    """Fiyat oranı ızgarası; bizim rakip yanıtı kampanyalarımız hariç (onların etkisini ayrıca ölçmek için)."""
    kodlar = _yanit_kodlari(vs)
    if not kodlar:
        return fiyat_oranlari(vs, panel)
    vs2 = copy.copy(vs)
    vs2.tablolar = dict(vs.tablolar)
    vs2.tablolar["kampanyalar"] = vs["kampanyalar"][~vs["kampanyalar"]["kampanya_kodu"].isin(kodlar)]
    if vs.get("kampanya_kapsami") is not None:
        vs2.tablolar["kampanya_kapsami"] = vs["kampanya_kapsami"][~vs["kampanya_kapsami"]["kampanya_kodu"].isin(kodlar)]
    return fiyat_oranlari(vs2, panel)


def _yanit_kapsami(vs, kod: str, g: pd.DataFrame) -> pd.Series:
    """g satırları içinde bizim yanıt kampanyamızın kapsamına giren satırlar (tarih hariç; kapsam = ürün/mağaza/ülke/kanal)."""
    k = vs["kampanyalar"]
    kamp = k[k["kampanya_kodu"] == kod]
    if kamp.empty:
        return pd.Series(False, index=g.index)
    kanal = kamp["kanal"].iloc[0] if "kanal" in kamp and isinstance(kamp["kanal"].iloc[0], str) and kamp["kanal"].iloc[0] else None
    kap = vs.get("kampanya_kapsami")
    kap = pd.DataFrame({"kampanya_kodu": [kod]}) if kap is None else kap[kap["kampanya_kodu"] == kod]
    if kap.empty:
        kap = pd.DataFrame({"kampanya_kodu": [kod]})
    icinde = pd.Series(False, index=g.index)
    for r in kap.itertuples(index=False):
        m = pd.Series(True, index=g.index)
        for c in ("magaza_kodu", "ulke", "urun_kodu", "kategori"):
            v = getattr(r, c, None)
            if isinstance(v, str) and v:
                m &= g[c] == v
        icinde |= m
    if kanal:
        icinde &= g["kanal"] == kanal
    return icinde


def _oran_orani(post: np.ndarray, pre: np.ndarray, post_k: np.ndarray, pre_k: np.ndarray) -> float:
    a, b, c, d = post.sum(), pre.sum(), post_k.sum(), pre_k.sum()
    if min(b, c, d) <= 0:
        return np.nan
    return (a / b) / (c / d) - 1


def _boot(df_a: pd.DataFrame, df_b: pd.DataFrame, rng, n: int) -> tuple[float, float, float]:
    """df_*: birim (ürün-mağaza) satırları: ur_id, pre, post. Ürün bazında yeniden örnekleme ile (a/b) fark-içinde-fark."""
    nokta = _oran_orani(df_a["post"].to_numpy(), df_a["pre"].to_numpy(), df_b["post"].to_numpy(), df_b["pre"].to_numpy())
    if not np.isfinite(nokta) or n < 2:
        return nokta, np.nan, np.nan
    ga = df_a.groupby("ur_id")[["pre", "post"]].sum()
    gb = df_b.groupby("ur_id")[["pre", "post"]].sum()
    pa, qa, pb, qb = ga["pre"].to_numpy(), ga["post"].to_numpy(), gb["pre"].to_numpy(), gb["post"].to_numpy()
    sonuc = []
    for _ in range(n):
        ia = rng.integers(0, len(ga), len(ga))
        ib = rng.integers(0, len(gb), len(gb))
        sonuc.append(_oran_orani(qa[ia], pa[ia], qb[ib], pb[ib]))
    sonuc = np.array(sonuc)
    sonuc = sonuc[np.isfinite(sonuc)]
    if len(sonuc) < n // 2:
        return nokta, np.nan, np.nan
    return nokta, float(np.quantile(sonuc, 0.1)), float(np.quantile(sonuc, 0.9))


def _birimler(d: pd.DataFrame, pre_h: list[int], post_h: list[int]) -> pd.DataFrame:
    """Ürün-mağaza başına pre/post haftalık ortalama düzeltilmiş satış; iki dönemde de gözlenen (A >= 0,5) birimler."""
    x = d[d["A"] >= 0.5]
    pre = x[x["hafta_no"].isin(pre_h)].groupby(["ur_id", "magaza_kodu"]).agg(pre=("y", "mean"), n_pre=("y", "size"))
    post = x[x["hafta_no"].isin(post_h)].groupby(["ur_id", "magaza_kodu"]).agg(post=("y", "mean"), n_post=("y", "size"))
    b = pre.join(post, how="inner")
    b = b[(b["n_pre"] >= max(1, len(pre_h) // 2)) & (b["n_post"] >= max(1, len(post_h) // 2))]
    return b.reset_index()


class _Matris:
    """Birim (ürün-mağaza) x hafta düzeltilmiş satış matrisi; stoksuz hafta (A < 0,5) boş. Pencere hesapları hızlı olsun diye."""

    def __init__(self, d: pd.DataFrame, n_hafta: int):
        x = d[d["A"] >= 0.5]
        birim = pd.factorize(x["ur_id"] + "#" + x["magaza_kodu"])
        self.M = np.full((len(birim[1]), n_hafta), np.nan)
        self.M[birim[0], x["hafta_no"].to_numpy()] = x["y"].to_numpy()
        self.ur = np.array([k.split("#")[0] for k in birim[1]])

    def pencere(self, pre_h, post_h):
        with np.errstate(invalid="ignore"), __import__("warnings").catch_warnings():
            __import__("warnings").simplefilter("ignore", RuntimeWarning)
            pre, post = np.nanmean(self.M[:, pre_h], 1), np.nanmean(self.M[:, post_h], 1)
        n_pre, n_post = np.isfinite(self.M[:, pre_h]).sum(1), np.isfinite(self.M[:, post_h]).sum(1)
        ok = (n_pre >= max(1, len(pre_h) // 2)) & (n_post >= max(1, len(post_h) // 2))
        return pre[ok], post[ok], self.ur[ok]


def _did_log(ma: _Matris, mb: _Matris, pre_h, post_h, min_birim: int, min_urun: int) -> float:
    pa, qa, ua = ma.pencere(pre_h, post_h)
    pb, qb, ub = mb.pencere(pre_h, post_h)
    if len(pa) < min_birim or len(pb) < min_birim or len(set(ua)) < min_urun or len(set(ub)) < min_urun:
        return np.nan
    v = _oran_orani(qa, pa, qb, pb)
    return float(np.log1p(v)) if np.isfinite(v) and v > -1 else np.nan


def _maske(d: pd.DataFrame, o: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Rakip olayına maruz kalan satırlar ve doğal kontrol (aynı kategori, olayın hiç dokunmadığı mağazalar)."""
    maruz = pd.Series(False, index=d.index)
    for r in o.itertuples(index=False):
        m = pd.Series(True, index=d.index)
        if isinstance(r.ulke, str) and r.ulke:
            m &= d["ulke"] == r.ulke
        if isinstance(r.kanal, str) and r.kanal:
            m &= d["kanal"] == r.kanal
        if isinstance(r.kategori, str) and r.kategori:
            m &= d["kategori"] == r.kategori
        maruz |= m
    kategoriler = set(o["kategori"].dropna()) - {""}
    kontrol = ~maruz & (d["kategori"].isin(kategoriler) if kategoriler else True) & ~d["magaza_kodu"].isin(set(d.loc[maruz, "magaza_kodu"]))
    return maruz, kontrol


def _aralik(nokta_log: float, plasebo: list[float]) -> tuple[float, float, float, float]:
    """Plasebo (olay olmayan pencerelerdeki aynı hesap) dağılımıyla %80 aralık ve ölçülebilir en küçük etki."""
    p = np.array([v for v in plasebo if np.isfinite(v)])
    if not np.isfinite(nokta_log) or len(p) < 6:
        return (np.expm1(nokta_log) if np.isfinite(nokta_log) else np.nan), np.nan, np.nan, np.nan
    p = p - np.median(p)  # yalnızca yayılım alınır; plasebo ortancası küçük örnekte oynak olduğundan nokta kaydırılmaz
    q10, q90 = np.quantile(p, 0.1), np.quantile(p, 0.9)
    return float(np.expm1(nokta_log)), float(np.expm1(nokta_log - q90)), float(np.expm1(nokta_log - q10)), float(np.expm1((q90 - q10) / 2))


def havuz(olaylar: pd.DataFrame) -> pd.DataFrame:
    """Olaylar arası ağırlıklı ortalama rakip etkisi (log ölçekte, ters varyans ağırlıklı; varyans %80 aralıktan).
    Tek olay gürültülüdür; kütüphane büyüdükçe ortalama daraltılır. Yalnızca aralığı olan olaylar."""
    if olaylar.empty:
        return pd.DataFrame()
    satir = []
    for H, x in olaylar[olaylar["rakip_alt"].notna() & olaylar["rakip_ust"].notna()].groupby("hafta"):
        lg = np.log1p(x["rakip_etki"])
        se = ((np.log1p(x["rakip_ust"]) - np.log1p(x["rakip_alt"])) / 2.563).clip(lower=0.02)
        w = 1 / se**2
        m = float((w * lg).sum() / w.sum())
        sm = float(np.sqrt(1 / w.sum()))
        # olaylar arası gerçek farklılık (rakip, indirim, kategori farklı): DerSimonian-Laird
        q = float((w * (lg - m) ** 2).sum())
        tau2 = max(0.0, (q - (len(x) - 1)) / max(w.sum() - (w**2).sum() / w.sum(), 1e-9))
        w2 = 1 / (se**2 + tau2)
        m2 = float((w2 * lg).sum() / w2.sum())
        s2 = float(np.sqrt(1 / w2.sum()))
        satir.append(dict(hafta=H, olay=len(x), ortalama_etki=np.expm1(m2), alt=np.expm1(m2 - 1.2816 * s2), ust=np.expm1(m2 + 1.2816 * s2),
                          olaylar_arasi_sd=float(np.sqrt(tau2))))
    return pd.DataFrame(satir)


def kampanya_etkisi(vs, panel: Panel, ayar: EtkiAyar | None = None, tarih=None, defter: str | Path | None = None,
                    g: pd.DataFrame | None = None) -> EtkiSonucu:
    """tarih: rapor günü (varsayılan son satış günü); yalnızca penceresi bu güne kadar tamamlanan ölçümler yapılır.
    defter: verilirse her olayın temel tahmini ilk hesaplandığı anda buraya dondurulur ve sonra değiştirilmez."""
    ayar = ayar or EtkiAyar()
    notlar: list[str] = []
    rk = vs.get("rakip_kampanyalari")
    if rk is None or rk.empty:
        return EtkiSonucu(pd.DataFrame(), pd.DataFrame(), notlar=["rakip_kampanyalari tablosu yok: rakip etkisi ölçülemez."])
    kr = vs.get("kampanya_kararlari")
    g = _yanitsiz_oran(vs, panel) if g is None else g
    tarih = pd.Timestamp(tarih) if tarih is not None else vs["satislar"]["tarih"].max()
    sz = panel.sezonlar
    rng = np.random.default_rng(ayar.tohum)
    satirlar, grup_satir = [], []
    esn_onbellek: dict = {}
    defter = Path(defter) if defter else None
    if defter:
        defter.mkdir(parents=True, exist_ok=True)
    fiyat = panel.urunler.drop_duplicates("ur_id").set_index("ur_id")[["liste_fiyati_try", "birim_maliyet", "maliyet_para_birimi"]]

    for olay, o in rk.groupby("olay_kodu", sort=False):
        bas, bit = pd.Timestamp(o["baslangic_tarihi"].min()), pd.Timestamp(o["bitis_tarihi"].max())
        s = sz[(sz["baslangic"] <= bas) & (sz["bitis"] > bas)]
        if s.empty:
            notlar.append(f"{olay}: hiçbir sezona düşmüyor, atlandı.")
            continue
        s = s.iloc[0]
        T = s["sezon_kodu"]
        k0 = int((bas - s["baslangic"]).days // 7)
        k1 = int((bit - s["baslangic"]).days // 7)
        if k0 < ayar.once_hafta:
            notlar.append(f"{olay}: sezonun ilk {ayar.once_hafta} haftasında; olay öncesi taban yok, atlandı.")
            continue
        # esneklik: olaydan önce bitmiş sezonlardan (kendi indirimlerimizden arındırmak için)
        biten = tuple(sz.loc[sz["bitis"] <= bas, "sezon_kodu"])
        if biten not in esn_onbellek:
            e = esneklik_ogren(g, list(biten), EritmeAyar(bootstrap=10)) if biten else pd.DataFrame()
            esn_onbellek[biten] = e.set_index("grup")["e"].to_dict() if len(e) else {}
        e_h = esn_onbellek[biten]
        e_genel = e_h.get("tümü", 1.0)
        d = g[g["sezon_kodu"] == T].copy()
        d["y"] = d["satis"] / d["A"].clip(lower=0.5) * d["oran"] ** d["bolge"].map(e_h).fillna(e_genel)
        # maruz kalan: ülke x kanal x kategori
        maruz, kontrol = _maske(d, o)
        kategoriler = set(o["kategori"].dropna()) - {""}
        # karar
        k_satir = kr[kr["olay_kodu"] == olay] if kr is not None and len(kr) else pd.DataFrame()
        karar = str(k_satir["karar"].iloc[0]) if len(k_satir) else "isaretlenmedi"
        kamp_kod = str(k_satir["kampanya_kodu"].iloc[0]) if len(k_satir) and pd.notna(k_satir["kampanya_kodu"].iloc[0]) else ""
        kontrol_grubu = bool(len(k_satir) and k_satir["kontrol_grubu"].iloc[0] == "evet")
        yanitli = _yanit_kapsami(vs, kamp_kod, d) & maruz if kamp_kod and karar != "yapilmadi" else pd.Series(False, index=d.index)
        yanit_ind = 0.0
        if kamp_kod and kamp_kod in set(vs["kampanyalar"]["kampanya_kodu"]):
            yanit_ind = float(vs["kampanyalar"].set_index("kampanya_kodu").loc[kamp_kod, "indirim_orani"] or 0)
        d["grup"] = np.select([maruz & yanitli, maruz & ~yanitli, kontrol], ["maruz_yanitli", "maruz_yanitsiz", "kontrol"], "disarida")
        d = d[d["grup"] != "disarida"]
        pre_h = list(range(k0 - ayar.once_hafta, k0))
        profil = _profil(g, list(biten), e_h, e_genel) if biten else pd.DataFrame(columns=["kategori", "sezon_tipi", "hafta_no", "p"])
        sezon_tipi = T.split("-")[-1]

        # temel tahmin (dondurulmuş): olay öncesi hız x kategori profili; yalnızca olay öncesi veriyle
        temel_yol = defter / f"temel_{olay}.csv" if defter else None
        if temel_yol is not None and temel_yol.exists():
            temel = pd.read_csv(temel_yol)
            temel_durum = f"dondurulmuş ({temel['olusturma'].iloc[0]})"
        else:
            pre_rows = d[d["hafta_no"].isin(pre_h) & (d["A"] >= 0.5)]
            hiz = pre_rows.groupby("grup")["y"].sum() / ayar.once_hafta
            temel = []
            for grp, v in hiz.items():
                kats = d.loc[d["grup"] == grp, "kategori"].unique()
                p = profil[(profil["kategori"].isin(kats)) & (profil["sezon_tipi"] == sezon_tipi)].groupby("hafta_no")["p"].mean()
                p_pre = float(p.reindex(pre_h).mean()) if len(p) else 1.0
                for h in range(k0, k0 + max(ayar.haftalar)):
                    temel.append(dict(olay_kodu=olay, grup=grp, hafta_no=h, temel=v * float(p.get(h, p_pre) if len(p) else 1.0) / max(p_pre, 1e-9),
                                      olusturma=datetime.now().strftime("%Y-%m-%d %H:%M")))
            temel = pd.DataFrame(temel)
            temel_durum = "olay öncesi veriyle yeniden hesaplandı"
            if temel_yol is not None and len(temel):
                temel.to_csv(temel_yol, index=False)
                temel_durum = f"dondurulmuş ({temel['olusturma'].iloc[0]})"

        n_hafta = int(g["hafta_no"].max()) + 1
        mat = {grp: _Matris(d[d["grup"] == grp], n_hafta) for grp in ("maruz_yanitli", "maruz_yanitsiz", "kontrol")}
        # önceki aynı tip sezonlarda aynı kapsam (olay öncesi esneklikle düzeltilmiş); olay haftaları plasebodan çıkarılır
        onceki = []
        for _, s0 in sz[(sz["sezon_tipi"] == s["sezon_tipi"]) & (sz["bitis"] <= bas)].iterrows():
            d0 = g[g["sezon_kodu"] == s0["sezon_kodu"]].copy()
            d0["y"] = d0["satis"] / d0["A"].clip(lower=0.5) * d0["oran"] ** d0["bolge"].map(e_h).fillna(e_genel)
            m0, k0_ = _maske(d0, o)
            dolu = set()
            for r0 in rk.itertuples(index=False):
                b0, e0 = pd.Timestamp(r0.baslangic_tarihi), pd.Timestamp(r0.bitis_tarihi)
                if s0["baslangic"] <= b0 < s0["bitis"]:
                    dolu |= set(range(int((b0 - s0["baslangic"]).days // 7), int((e0 - s0["baslangic"]).days // 7) + 1))
            onceki.append((_Matris(d0[m0], n_hafta), _Matris(d0[k0_], n_hafta), dolu))
        ob = ayar.once_hafta

        dolu_T = set()  # bu sezondaki diğer rakip olaylarının haftaları plasebo olamaz
        for r0 in rk[rk["olay_kodu"] != olay].itertuples(index=False):
            b0, e0 = pd.Timestamp(r0.baslangic_tarihi), pd.Timestamp(r0.bitis_tarihi)
            if s["baslangic"] <= b0 < s["bitis"]:
                dolu_T |= set(range(int((b0 - s["baslangic"]).days // 7), int((e0 - s["baslangic"]).days // 7) + 1))

        def plasebo(ma, mb, H, onceki_de=True):
            out = [_did_log(ma, mb, list(range(ks - ob, ks)), list(range(ks, ks + H)), ayar.min_birim, ayar.min_urun)
                   for ks in range(ob, k0 - H + 1) if not (set(range(ks - ob, ks + H)) & dolu_T)]
            if onceki_de:
                for ma0, mb0, dolu in onceki:
                    out += [_did_log(ma0, mb0, list(range(ks - ob, ks)), list(range(ks, ks + H)), ayar.min_birim, ayar.min_urun)
                            for ks in range(ob, n_hafta - H + 1) if not (set(range(ks - ob, ks + H)) & dolu)]
            return out

        for H in ayar.haftalar:
            post_h = list(range(k0, k0 + H))
            bitis_H = s["baslangic"] + pd.Timedelta(days=7 * (k0 + H) - 1)
            if bitis_H > tarih or k0 + H > n_hafta:
                continue
            b = {grp: _birimler(d[d["grup"] == grp], pre_h, post_h) for grp in ("maruz_yanitli", "maruz_yanitsiz", "kontrol")}
            for grp, x in b.items():
                grup_satir.append(dict(olay_kodu=olay, hafta=H, grup=grp, birim=len(x), urun=x["ur_id"].nunique() if len(x) else 0,
                                       once_haftalik=x["pre"].sum() if len(x) else 0.0, sonra_haftalik=x["post"].sum() if len(x) else 0.0))
            r = dict(olay_kodu=olay, sezon_kodu=T, hafta=H, baslangic=bas.date(), bitis=bit.date(),
                     kategori=",".join(sorted(kategoriler)) or "tümü", ulke=",".join(sorted(set(o["ulke"].dropna()) - {""})) or "tümü",
                     kanal=",".join(sorted(set(o["kanal"].dropna()) - {""})) or "tümü", rakip_indirim=float(o["indirim_orani"].max()),
                     karar=karar, kontrol_grubu=kontrol_grubu, yanit_indirimi=yanit_ind, temel_durum=temel_durum,
                     olay_suresi_hafta=k1 - k0 + 1, bolgeler=",".join(sorted(set(d.loc[d["grup"] != "kontrol", "bolge"]))))
            # rakip etkisi: maruz kalıp yanıt vermediğimiz grup vs maruz kalmayan grup; aralık plasebo pencerelerinden
            nokta = _did_log(mat["maruz_yanitsiz"], mat["kontrol"], pre_h, post_h, ayar.min_birim, ayar.min_urun)
            if np.isfinite(nokta):
                pl = plasebo(mat["maruz_yanitsiz"], mat["kontrol"], H)
                r["rakip_etki"], r["rakip_alt"], r["rakip_ust"], r["olculebilir_en_kucuk"] = _aralik(nokta, pl)
                r["plasebo_pencere"] = int(np.isfinite(pl).sum())
                r["rakip_yontem"] = ("rastgele kontrol grubu + doğal kontrol (fark-içinde-fark)" if kontrol_grubu
                                     else "doğal kontrol (fark-içinde-fark)")
            else:
                net = _did_log(mat["maruz_yanitli"], mat["kontrol"], pre_h, post_h, ayar.min_birim, ayar.min_urun)
                if np.isfinite(net):
                    # yanıt herkese uygulandı: yanıt ve rakip birlikte; yanıtın payı esneklikten çıkarılır (model varsayımı)
                    pl = plasebo(mat["maruz_yanitli"], mat["kontrol"], H, onceki_de=False) + [v for ma0, mb0, dolu in onceki for v in
                         (_did_log(ma0, mb0, list(range(ks - ob, ks)), list(range(ks, ks + H)), ayar.min_birim, ayar.min_urun)
                          for ks in range(ob, n_hafta - H + 1) if not (set(range(ks - ob, ks + H)) & dolu))]
                    e_m = float(d.loc[d["grup"] == "maruz_yanitli", "bolge"].map(e_h).fillna(e_genel).mean())
                    sure = k1 - k0 + 1
                    lift = (1 - yanit_ind) ** (-e_m) * min(sure, H) / H + max(H - sure, 0) / H
                    v, lo, hi, mde = _aralik(net, pl)
                    r["rakip_etki"], r["rakip_alt"], r["rakip_ust"] = ((1 + x) / lift - 1 if np.isfinite(x) else np.nan for x in (v, lo, hi))
                    r["olculebilir_en_kucuk"], r["plasebo_pencere"] = mde, int(np.isfinite(pl).sum())
                    r["rakip_yontem"] = "yanıtla karışık; yanıtın payı esneklikten çıkarıldı (model varsayımı)"
                else:
                    r["rakip_etki"] = r["rakip_alt"] = r["rakip_ust"] = np.nan
                    r["rakip_yontem"] = "ölçülemedi (maruz kalan ya da kontrol grubu çok küçük)"
            # yanıt etkisi: kontrol grubu varsa doğrudan (yanıtlı vs bilerek dışarıda bırakılan maruz ürünler)
            if karar != "yapilmadi" and kamp_kod:
                nokta_y = _did_log(mat["maruz_yanitli"], mat["maruz_yanitsiz"], pre_h, post_h, ayar.min_birim, ayar.min_urun) if kontrol_grubu else np.nan
                if np.isfinite(nokta_y):
                    ply = plasebo(mat["maruz_yanitli"], mat["maruz_yanitsiz"], H, onceki_de=False)
                    r["yanit_etki"], r["yanit_alt"], r["yanit_ust"], r["yanit_olculebilir"] = _aralik(nokta_y, ply)
                    r["yanit_yontem"] = "kontrol grubu ölçümü"
                else:
                    e_m = float(d.loc[d["grup"] == "maruz_yanitli", "bolge"].map(e_h).fillna(e_genel).mean()) if (d["grup"] == "maruz_yanitli").any() else e_genel
                    sure = k1 - k0 + 1
                    r["yanit_etki"] = (1 - yanit_ind) ** (-e_m) * min(sure, H) / H + max(H - sure, 0) / H - 1
                    r["yanit_alt"] = r["yanit_ust"] = np.nan
                    r["yanit_yontem"] = "esneklikten (model varsayımı, ölçülmedi)"
            # adetler: maruz kalan toplam (yanıtlı + yanıtsız), gerçek satış (düzeltilmemiş) ve kaptırılan tahmini satış
            maruz_d = d[d["grup"].isin(["maruz_yanitli", "maruz_yanitsiz"]) & d["hafta_no"].isin(post_h)]
            r["maruz_satis"] = float(maruz_d["satis"].sum())
            r["maruz_urun"] = int(maruz_d["ur_id"].nunique())
            ef = r.get("rakip_etki", np.nan)
            if np.isfinite(ef) and ef > -0.95:
                adj = maruz_d["y"].sum()
                # düzeltilmiş satış, rakip olmasaydı adj / (1 + etki) olurdu
                for ad, v in (("kaptirilan", ef), ("kaptirilan_alt", r.get("rakip_ust", np.nan)), ("kaptirilan_ust", r.get("rakip_alt", np.nan))):
                    r[ad] = float(adj / (1 + v) - adj) if np.isfinite(v) and v > -0.95 else np.nan
                pr = maruz_d.merge(fiyat, left_on="ur_id", right_index=True)
                marj = (pr["liste_fiyati_try"] * pr["oran"] / (1 + ayar.kdv_orani) - pr["birim_maliyet"].where(pr["maliyet_para_birimi"] == "TRY"))
                birim_kar = float(np.average(marj.fillna(marj.mean()), weights=pr["satis"] + 1e-9)) if len(pr) else np.nan
                r["birim_brut_kar"] = birim_kar
                for ad in ("kaptirilan", "kaptirilan_alt", "kaptirilan_ust"):
                    r[ad + "_kar"] = r[ad] * birim_kar if np.isfinite(r.get(ad, np.nan)) else np.nan
            # beklenenden sapma (model karşı-olgusalı): maruz kalan gruplar, dondurulmuş temel tahmine göre
            if len(temel):
                tm = temel[temel["grup"].isin(["maruz_yanitli", "maruz_yanitsiz"]) & temel["hafta_no"].isin(post_h)]["temel"].sum()
                gz = d[d["grup"].isin(["maruz_yanitli", "maruz_yanitsiz"]) & d["hafta_no"].isin(post_h) & (d["A"] >= 0.5)]["y"].sum()
                r["temel"] = float(tm)
                r["sapma"] = float(gz / tm - 1) if tm > 0 else np.nan
            satirlar.append(r)
    olaylar = pd.DataFrame(satirlar)
    if len(olaylar):
        for c in ("rakip_etki", "rakip_alt", "rakip_ust", "yanit_etki", "yanit_alt", "yanit_ust", "olculebilir_en_kucuk", "plasebo_pencere"):
            if c not in olaylar:
                olaylar[c] = np.nan
    if len(olaylar) and olaylar["rakip_etki"].isna().any():
        notlar.append("Bazı olaylarda maruz kalan ya da kontrol grubu çok küçük olduğu için rakip etkisi ölçülemedi.")
    return EtkiSonucu(olaylar=olaylar, havuz=havuz(olaylar), gruplar=pd.DataFrame(grup_satir), esneklik=esn_onbellek, notlar=notlar)
