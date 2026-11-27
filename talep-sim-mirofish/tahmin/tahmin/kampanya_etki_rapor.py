"""Kampanya ve rakip etkisi raporu (Türkçe Markdown + CSV)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from .kampanya_etki import EtkiSonucu
from .rapor import _tablo, sayi, yuzde

KARAR_AD = {"yapildi": "yaptık", "yapilmadi": "yapmadık", "kismen": "kısmen", "isaretlenmedi": "işaretlenmedi"}


def _ar(v, lo, hi) -> str:
    if pd.isna(v):
        return "ölçülemedi"
    if pd.isna(lo) or pd.isna(hi):
        return f"{yuzde(v, True)} (aralık yok)"
    return f"{yuzde(v, True)} ({yuzde(lo, True)} / {yuzde(hi, True)})"


def _adet(v, lo, hi) -> str:
    if pd.isna(v):
        return "-"
    if pd.isna(lo) or pd.isna(hi):
        return sayi(v)
    a, b = sorted((lo, hi))
    return f"{sayi(v)} ({sayi(a)} / {sayi(b)})"


def _guven(mde) -> str:
    """Ölçülebilir en küçük etkiye göre: bir rakip kampanyasının tipik etkisi (%15-30) ayırt edilebiliyor mu."""
    if pd.isna(mde):
        return "yok (geçmiş pencere yetersiz)"
    return "iyi" if mde <= 0.25 else ("orta" if mde <= 0.5 else "düşük")


def etki_raporu(r: EtkiSonucu, cikti: str | Path, veri_adi: str = "", sentetik_gercek: pd.DataFrame | None = None,
                e_gercek: dict | None = None) -> Path:
    cikti = Path(cikti)
    cikti.mkdir(parents=True, exist_ok=True)
    o = r.olaylar.copy()
    o.to_csv(cikti / "etki_olaylar.csv", index=False)
    r.gruplar.to_csv(cikti / "etki_gruplar.csv", index=False)
    r.havuz.to_csv(cikti / "etki_kutuphane.csv", index=False)
    sentetik = sentetik_gercek is not None
    if sentetik and len(o):
        o = o.merge(sentetik_gercek[["olay_kodu", "rakip_talep_carpani"]], on="olay_kodu", how="left")
        o["gercek_rakip"] = o["rakip_talep_carpani"] - 1
        if e_gercek:
            o["gercek_yanit"] = [
                ((1 - y) ** (-np.mean([e_gercek.get(b, 1.5) for b in str(bl).split(",") if b])) * min(su, H) / H + max(H - su, 0) / H - 1)
                if y > 0 else np.nan
                for y, bl, su, H in zip(o["yanit_indirimi"], o["bolgeler"], o["olay_suresi_hafta"], o["hafta"])]

    s: list[str] = []
    s.append("# Kampanya ve rakip etkisi")
    s.append("")
    s.append(f"Veri: `{veri_adi}` · Rapor tarihi: {date.today()} · **Gölge mod:** ölçüm yalnızca kaydedilir.")
    s.append("")
    if sentetik:
        s.append("> **SENTETİK VERİ.** Rakip kampanyaları, etkileri ve bizim kararlarımız formülle üretildi. Gerçek etki bilindiği için "
                 "yöntemin doğruluğu ölçülebiliyor; gerçek bir müşterinin sonucu değildir.")
        s.append("")
    s.append("Her rakip kampanyası için iki soru: (1) rakibin kampanyası maruz kalan ürünlerimizde satışımızı ne kadar değiştirdi, "
             "(2) yanıt verdiysek yanıtımız ne kazandırdı. Ölçüm, rakibin kampanyasının olmadığı ülke ya da kanaldaki aynı kategori "
             "ile karşılaştırarak yapılır (fark-içinde-fark). Aralık, aynı hesabın rakip kampanyası olmayan geçmiş haftalarda ne kadar "
             "oynadığından kurulur; yani \"şans eseri bu kadar fark çıkar mı\" sorusunun cevabıdır.")
    s.append("")
    if o.empty:
        s.append("Ölçülecek rakip olayı yok.")
        yol = cikti / "kampanya_etki_raporu.md"
        yol.write_text("\n".join(s + [f"- {n}" for n in r.notlar]), encoding="utf-8")
        return yol

    h1 = o[o["hafta"] == 1]
    olculen = h1[h1["rakip_alt"].notna()]
    s.append("## Özet")
    s.append("")
    s.append(f"- **{h1['olay_kodu'].nunique()}** rakip kampanyası kayıtlı; **{len(olculen)}** tanesinde etki aralığıyla ölçülebildi. "
             f"Kararlar: " + ", ".join(f"{KARAR_AD.get(k, k)} {v}" for k, v in h1["karar"].value_counts().items()) + ".")
    hv = r.havuz
    if len(hv) and (hv["hafta"] == 1).any():
        x = hv[hv["hafta"] == 1].iloc[0]
        s.append(f"- **Kampanya kütüphanesi (olaylar arası ortalama):** rakip kampanyası haftasında maruz kalan ürünlerimizin satışı ortalama "
                 f"**{_ar(x['ortalama_etki'], x['alt'], x['ust'])}** değişti ({int(x['olay'])} olay)."
                 + (f" Sentetik gerçek ortalama: {yuzde(h1.drop_duplicates('olay_kodu')['gercek_rakip'].mean(), True)}." if sentetik else ""))
    kap = olculen["kaptirilan"].dropna() if "kaptirilan" in olculen else pd.Series(dtype=float)
    if len(kap):
        kar = olculen["kaptirilan_kar"].dropna().sum() if "kaptirilan_kar" in olculen else np.nan
        s.append(f"- Ölçülen olayların ilk haftasında rakibe **kaptırılan tahmini satış** toplamı {sayi(kap.sum())} adet"
                 + (f", brüt kâr olarak yaklaşık {sayi(kar)} TL" if np.isfinite(kar) else "") + " (nokta tahminlerinin toplamı; tek tek aralıklar tabloda).")
    s.append("- Tek bir olayın tek haftası çok gürültülüdür: aşağıdaki \"ölçülebilir en küçük etki\" sütunu, o kapsamda şans eseri ne kadar "
             "fark çıkabileceğini gösterir. Bunun altındaki etkiler o olay için ayırt edilemez; kütüphane büyüdükçe ortalama netleşir.")
    s.append("")

    s.append("## Olay olay: ilk hafta")
    s.append("")
    tab = pd.DataFrame({
        "Olay": h1["olay_kodu"],
        "Kapsam": [f"{k} · {u} · {kn}" for k, u, kn in zip(h1["kategori"], h1["ulke"], h1["kanal"])],
        "Rakip indirimi": [f"%{round(100 * v)}" for v in h1["rakip_indirim"]],
        "Kararımız": [KARAR_AD.get(k, k) + (" (kontrol gruplu)" if kg else "") for k, kg in zip(h1["karar"], h1["kontrol_grubu"])],
        "Rakip etkisi (%80)": [_ar(v, lo, hi) for v, lo, hi in zip(h1["rakip_etki"], h1["rakip_alt"], h1["rakip_ust"])],
        "Ölçülebilir en küçük": [yuzde(v) if pd.notna(v) else "-" for v in h1["olculebilir_en_kucuk"]],
        "Güven": [_guven(m) for m in h1["olculebilir_en_kucuk"]],
        "Kaptırılan satış (adet)": [_adet(v, lo, hi) if pd.notna(lo) else "-" for v, lo, hi in zip(
            h1.get("kaptirilan", pd.Series(np.nan, index=h1.index)), h1.get("kaptirilan_alt", pd.Series(np.nan, index=h1.index)),
            h1.get("kaptirilan_ust", pd.Series(np.nan, index=h1.index)))],
        "Beklenenden sapma": [yuzde(v, True) for v in h1.get("sapma", pd.Series(np.nan, index=h1.index))],
    })
    if sentetik:
        tab["Sentetik gerçek"] = [yuzde(v, True) for v in h1["gercek_rakip"]]
    s.append(_tablo(tab))
    s.append("")
    s.append("Güven: o kapsamda şans eseri çıkabilecek fark %25'in altındaysa iyi, %50'nin altındaysa orta, üstündeyse düşük. "
             "\"Yok\" olan olaylarda aralık kurulacak kadar olaysız geçmiş hafta yok; nokta tahmini yalnızca bilgi içindir ve özete girmez.")
    s.append("")
    s.append("Yöntemler: " + "; ".join(f"{k}: {v} olay" for k, v in h1["rakip_yontem"].value_counts().items()) + ".")
    s.append("")
    s.append("\"Beklenenden sapma\", olay öncesi satış hızının kategori sezon eğrisiyle ileri taşınmasından (dondurulmuş temel tahmin) farktır. "
             "Rakip, hava, bizim kendi değişikliklerimiz ve şans karışımıdır; \"rakip etkisi\" diye okunmamalıdır.")
    s.append("")

    y = o[(o["hafta"] == 1) & (o["karar"] != "yapilmadi") & o["yanit_etki"].notna()]
    if len(y):
        s.append("## Yanıtımız ne kazandırdı?")
        s.append("")
        s.append("Kontrol grubu olan kararlarda yanıt verilen ürünler, maruz kalıp bilerek dışarıda bırakılan benzer ürünlerle karşılaştırılır. "
                 "Bu, bu rapordaki en güvenilir ölçümdür. Kontrol grubu yoksa yanıtın etkisi ölçülemez; indirim esnekliğinden hesaplanır.")
        s.append("")
        tab = pd.DataFrame({
            "Olay": y["olay_kodu"],
            "Yanıt indirimi": [f"%{round(100 * v)}" for v in y["yanit_indirimi"]],
            "Yanıtın satışa etkisi (%80)": [_ar(v, lo, hi) for v, lo, hi in zip(y["yanit_etki"], y["yanit_alt"], y["yanit_ust"])],
            "Yöntem": y["yanit_yontem"],
        })
        if sentetik and "gercek_yanit" in y:
            tab["Sentetik gerçek"] = [yuzde(v, True) for v in y["gercek_yanit"]]
        s.append(_tablo(tab))
        s.append("")
        s.append("Kontrol grubu önerisi: yanıt verilecek ürünlerin yaklaşık %20-30'u benzer çiftlerden rastgele seçilip kampanya dışında "
                 "bırakılırsa hem rakibin etkisi hem yanıtın getirisi ayrı ayrı ölçülür. Dışarıda bırakılan ürünlerdeki olası ek satış "
                 "kaybı bu ölçümün bedelidir.")
        s.append("")

    s.append("## 1, 2 ve 4 hafta sonra")
    s.append("")
    s.append("Pencere olayın başladığı haftadan başlar. Olay bittikten sonraki haftalar da pencereye girdikçe etki ya kapanır (müşteri geri döner) "
             "ya da sürer (müşteri kaybedildi). 4 haftalık ölçüm, yeterli geçmiş pencere olmadığında aralıksız kalabilir.")
    s.append("")
    pv = o.pivot_table(index="olay_kodu", columns="hafta", values="rakip_etki", aggfunc="first")
    pa = o.pivot_table(index="olay_kodu", columns="hafta", values="rakip_alt", aggfunc="first")
    pu = o.pivot_table(index="olay_kodu", columns="hafta", values="rakip_ust", aggfunc="first")
    tab = pd.DataFrame({"Olay": pv.index})
    for H in pv.columns:
        tab[f"{H}. hafta"] = [_ar(pv.loc[k, H], pa.loc[k, H] if k in pa.index and H in pa.columns else np.nan,
                                  pu.loc[k, H] if k in pu.index and H in pu.columns else np.nan) for k in pv.index]
    s.append(_tablo(tab))
    s.append("")
    if len(hv):
        s.append("Olaylar arası ortalama (kütüphane): " + "; ".join(
            f"{int(x.hafta)}. hafta {_ar(x.ortalama_etki, x.alt, x.ust)} ({int(x.olay)} olay)" for x in hv.itertuples()) + ".")
        s.append("")

    s.append("## \"Pazar payı\" hakkında")
    s.append("")
    s.append("Pazar payı (bizim satış ÷ pazarın toplamı) bu veriyle ölçülemez: pazarın toplamını ve rakibin satışını bilmiyoruz. Kaybedilen "
             "satışın hepsi rakibe gitmiş de olmayabilir (alışverişi erteleyen, başka markaya giden müşteri). Bu yüzden rapor "
             "\"kaptırılan tahmini satış\" verir: rakip kampanyası olmasaydı maruz kalan ürünlerde satacağımızı tahmin ettiğimiz ile gerçekleşen arasındaki fark.")
    s.append("")
    s.append("## Varsayımlar ve sınırlar")
    s.append("")
    for n in r.notlar:
        s.append(f"- {n}")
    s.append("- Satışlar stok bitişine göre düzeltilir (stokta olunmayan haftalar sayılmaz) ve bizim yanıt dışındaki kendi indirimlerimizden "
             "esneklikle arındırılır (ERP kalibrasyonu).")
    s.append("- Doğal kontrol varsayımı: rakip kampanyası olmasaydı maruz kalan grup ile kontrol grubu aynı yönde hareket ederdi. "
             "Bu varsayımın ne kadar tuttuğu, aralığın kurulduğu geçmiş haftalarda zaten ölçülür.")
    s.append("- Kaptırılan brüt kâr, maruz ürünlerin satış ağırlıklı birim brüt kârıyla hesaplanır (KDV %10 kural varsayımı).")
    s.append("- Rakip kampanyalarının tarihi ve kapsamı gözlem kaynağı kadar doğrudur (Boss Analyze ya da elle giriş).")
    s.append("")
    yol = cikti / "kampanya_etki_raporu.md"
    yol.write_text("\n".join(s), encoding="utf-8")
    return yol
