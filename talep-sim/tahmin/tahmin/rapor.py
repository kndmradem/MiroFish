"""Geriye dönük test sonucunu Türkçe Markdown rapora ve CSV dosyalarına yazar."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from .geriye_test import SEVIYE_AD, TestSonucu
from .modeller import KIYAS_YONTEMLERI, YONTEMLER

YONTEM_AD = {
    "kategori_ortalamasi": "Benzer ürün ortalaması (kategori)",
    "gecen_yil_kategori": "Geçen yıl aynı kategori",
    "mevsimsel_naif": "Mevsimsel naif",
    "benzer_urun_knn": "Benzer ürün kNN (bizim, açıklanabilir)",
    "ozellik_modeli": "Özellik modeli (bizim)",
}
HEDEF_AD = {"talep": "stok bitişi düzeltilmiş talep", "satis": "ham satış", "gercek": "gerçek talep (yalnızca sentetik)"}


def yuzde(x: float, isaret: bool = False) -> str:
    if pd.isna(x):
        return "-"
    s = f"{100 * x:+.1f}" if isaret else f"{100 * x:.1f}"
    return "%" + s.replace(".", ",")


def sayi(x: float) -> str:
    return f"{x:,.0f}".replace(",", ".")


def _tablo(df: pd.DataFrame) -> str:
    kol = list(df.columns)
    satir = ["| " + " | ".join(kol) + " |", "|" + "---|" * len(kol)]
    satir += ["| " + " | ".join(str(v) for v in r) + " |" for r in df.itertuples(index=False)]
    return "\n".join(satir)


def _en_iyi_kiyas(m: pd.DataFrame) -> pd.Series:
    k = m[m["yontem"].isin(KIYAS_YONTEMLERI)]
    return k.loc[k["wape"].idxmin()]


def rapor_yaz(sonuc: TestSonucu, cikti: str | Path, veri_adi: str = "") -> Path:
    cikti = Path(cikti)
    cikti.mkdir(parents=True, exist_ok=True)
    m = sonuc.metrikler
    m.to_csv(cikti / "metrikler.csv", index=False)
    for seviye, t in sonuc.tahminler.items():
        t.to_csv(cikti / f"tahminler_{seviye}.csv", index=False)
    sonuc.benzer.to_csv(cikti / "benzer_urunler.csv", index=False)
    sonuc.beden.to_csv(cikti / "beden_egrisi.csv", index=False)
    sonuc.deger.to_csv(cikti / "uretim_adedi_kiyasi.csv", index=False)

    md = _rapor_md(sonuc, veri_adi)
    yol = cikti / "geriye_donuk_test_raporu.md"
    yol.write_text(md, encoding="utf-8")
    return yol


def _rapor_md(s: TestSonucu, veri_adi: str) -> str:
    m = s.metrikler
    testler = list(s.egitim)
    T = testler[-1]
    mt = m[(m["test_sezonu"] == T) & (m["hedef"] == "talep")]
    o = []
    o.append("# Geriye dönük test raporu\n")
    if s.sentetik:
        o.append("> **SENTETİK VERİ.** Bu rapordaki tüm sayılar formülle üretilmiş sentetik bir markanın verisinden gelir. "
                 "Yöntemin nasıl çalıştığını ve raporun neye benzeyeceğini gösterir; gerçek bir markada ulaşılacak isabeti kanıtlamaz.\n")
    o.append(f"Rapor tarihi: {date.today():%Y-%m-%d}. Veri: `{veri_adi}`. Test sezonu: {', '.join(testler)}.\n")

    # --- Özet
    urun = mt[mt["seviye"] == "urun"].set_index("yontem")
    hafta = mt[mt["seviye"] == "urun_kume_hafta"].set_index("yontem")
    biz = "ozellik_modeli" if "ozellik_modeli" in urun.index else urun["wape"].idxmin()
    kiyas = _en_iyi_kiyas(mt[mt["seviye"] == "urun"])
    kiyas_h = _en_iyi_kiyas(mt[mt["seviye"] == "urun_kume_hafta"])
    o.append("## Özet\n")
    o.append(f"- **Üretim kararı düzeyinde** (model-renk sezon toplamı) {YONTEM_AD[biz]} hata oranı (WAPE) **{yuzde(urun.at[biz, 'wape'])}**; "
             f"en iyi basit yöntem ({YONTEM_AD[kiyas['yontem']]}) {yuzde(kiyas['wape'])}. "
             f"Hata {yuzde(1 - urun.at[biz, 'wape'] / kiyas['wape'])} daha düşük.")
    o.append(f"- **Mağaza kümesi x hafta düzeyinde** WAPE {yuzde(hafta.at[biz, 'wape'])}; en iyi basit yöntem {yuzde(kiyas_h['wape'])}. "
             "Haftalık ve küme düzeyinde gürültü doğal olarak çok daha yüksektir.")
    kume = mt[(mt["seviye"] == "urun_kume") & (mt["yontem"] == biz)].iloc[0]
    o.append(f"- **Aralıklar:** %80 aralıklar test sezonunda gerçekleşmelerin {yuzde(kume['kapsama_80'])}'ini, "
             f"%50 aralıklar {yuzde(kume['kapsama_50'])}'ini, %90 aralıklar {yuzde(kume['kapsama_90'])}'ini kapsadı (model-renk x küme). "
             "Hedef, söylenen yüzdeye yakın olmaktır; çok üstü aralığın gereksiz geniş, çok altı fazla iddialı olduğunu gösterir.")
    o.append(f"- **Sapma (bias):** {YONTEM_AD[biz]} toplam talebi {yuzde(urun.at[biz, 'bias'], True)} tahmin etti "
             f"(basit yöntemler {yuzde(mt[(mt['seviye'] == 'urun') & mt['yontem'].isin(KIYAS_YONTEMLERI)]['bias'].min(), True)} ile "
             f"{yuzde(mt[(mt['seviye'] == 'urun') & mt['yontem'].isin(KIYAS_YONTEMLERI)]['bias'].max(), True)} arası). "
             "Negatif değer düşük tahmindir. Sezon geneli seviye kayması geçmişten öğrenilemediği sürece tüm yöntemlerde görülür; aralıklar bunu kısmen karşılar.")
    if s.sentetik:
        ms = m[(m["test_sezonu"] == T) & (m["seviye"] == "urun") & (m["yontem"] == biz)].set_index("hedef")
        o.append(f"- **Stok bitişi:** ham satış gerçek talebin {yuzde(ms.at['satis', 'gercek_toplam'] / ms.at['gercek', 'gercek_toplam'])}'i. "
                 f"Düzeltilmiş talep gerçek talebin {yuzde(ms.at['talep', 'gercek_toplam'] / ms.at['gercek', 'gercek_toplam'])}'i. "
                 "Satışı talep sanmak sistematik düşük üretime yol açar.")
    o.append("")

    # --- Kurulum
    o.append("## Nasıl test edildi\n")
    o.append(f"- **Karar anı:** her test sezonu, sezon başından **{s.ayar.karar_oncesi_hafta} hafta önce** (üretim siparişi zamanı) tahmin edildi. "
             "Bu ana kadar tamamen bitmemiş sezonlar kullanılmadı.")
    for t in testler:
        o.append(f"- **{t}:** eğitim {', '.join(s.egitim[t])}; aralıkların öğrenildiği doğrulama sezonu {s.dogrulama[t]}.")
    n_urun = s.panel.urunler[s.panel.urunler["sezon_kodu"] == T]["ur_id"].nunique()
    kumeler = s.panel.magazalar.groupby("kume")["magaza_kodu"].count()
    o.append(f"- **Tahmin birimi:** model-renk ({T} sezonunda {n_urun} adet) x mağaza kümesi x sezon haftası "
             f"(ufuk {int(s.panel.haftalik['hafta_no'].max()) + 1} hafta). Kümeler: " + ", ".join(f"{k} ({v})" for k, v in kumeler.items()) + ".")
    o.append("- **Gerçekleşme:** stok bitişi düzeltilmiş talep. Ürünün stokta olmadığı haftalarda satış sıfırdır ama talep vardır; "
             "bu haftaların talebi, ürünün stokta olduğu haftalardaki satış hızından ve kategorinin haftalık profilinden tahmin edilir.")
    o.append("- **Dağıtım planı** (ürünün hangi kümede kaç mağazaya gideceği) karar anında bilinen girdi kabul edildi.")
    o.append("- **Yöntemler:**")
    for y in s.ayar.yontemler:
        o.append(f"  - {YONTEM_AD[y]}: {YONTEMLER[y].aciklama}.")
    gorsel = "görsel gömme (renk, desen, siluet) dahil" if s.gorsel_var else "görsel kullanılmadan"
    o.append(f"- Benzer ürün araması {gorsel} yapıldı.")
    o.append("- **Metrikler:** WAPE = toplam mutlak hata / toplam gerçekleşme (düşük iyi). Sapma = (toplam tahmin - toplam gerçekleşme) / toplam gerçekleşme. "
             "Kapsama = gerçekleşmenin aralık içinde kaldığı satırların oranı.\n")

    # --- İsabet tabloları
    o.append(f"## İsabet ({T}, gerçekleşme: {HEDEF_AD['talep']})\n")
    for seviye in ("urun", "urun_bolge", "urun_kume", "urun_kume_hafta"):
        t = mt[mt["seviye"] == seviye].sort_values("wape")
        o.append(f"### {SEVIYE_AD[seviye]} ({sayi(t['n'].iloc[0])} satır)\n")
        o.append(_tablo(pd.DataFrame({
            "Yöntem": [YONTEM_AD[y] for y in t["yontem"]], "WAPE": [yuzde(v) for v in t["wape"]],
            "Sapma": [yuzde(v, True) for v in t["bias"]], "%50 kapsama": [yuzde(v) for v in t["kapsama_50"]],
            "%80 kapsama": [yuzde(v) for v in t["kapsama_80"]], "%90 kapsama": [yuzde(v) for v in t["kapsama_90"]],
            "%80 aralık genişliği": [f"{v:.2f}x".replace(".", ",") for v in t["genislik_80"]],
        })))
        o.append("")
    o.append("_%80 aralık genişliği: (üst - alt) / tahmin, medyan. 1,5x, aralığın tahminin 1,5 katı genişlikte olduğu anlamına gelir._\n")

    if len(testler) > 1:
        o.append("### Tüm test sezonları (model-renk toplamı)\n")
        tt = m[(m["seviye"] == "urun") & (m["hedef"] == "talep")]
        p = tt.pivot_table(index="yontem", columns="test_sezonu", values="wape")
        o.append(_tablo(pd.DataFrame({"Yöntem": [YONTEM_AD[y] for y in p.index], **{c: [yuzde(v) for v in p[c]] for c in p.columns}})))
        o.append("")

    # --- Hedefe göre
    o.append("## Neye karşı ölçtüğümüz önemli\n")
    hd = m[(m["test_sezonu"] == T) & (m["seviye"] == "urun") & (m["yontem"] == biz)]
    o.append(_tablo(pd.DataFrame({
        "Gerçekleşme": [HEDEF_AD[h] for h in hd["hedef"]], "Toplam": [sayi(v) for v in hd["gercek_toplam"]],
        "WAPE": [yuzde(v) for v in hd["wape"]], "Sapma": [yuzde(v, True) for v in hd["bias"]], "%80 kapsama": [yuzde(v) for v in hd["kapsama_80"]]})))
    o.append("\nModel talebi tahmin eder. Ham satışa göre ölçülürse stok bitişi yüzünden olduğundan fazla tahmin ediyormuş gibi görünür.\n")

    # --- Beden
    if not s.beden.empty:
        b = s.beden[s.beden["test_sezonu"] == T]
        o.append("## Beden dağılımı\n")
        o.append("Öneri: geçmiş sezonların bölge x kategori beden payı. Hata: üretimin yüzde kaçı yanlış bedenlere gitmiş olurdu (adetle ağırlıklı).\n")
        o.append(_tablo(pd.DataFrame({"Bölge": b["bolge"], "Satış adedi": [sayi(v) for v in b["adet"]],
                                      "Geçmiş beden eğrisi": [yuzde(v) for v in b["gecmis_egri_hata"]],
                                      "Eşit dağılım (kıyas)": [yuzde(v) for v in b["esit_dagilim_hata"]]})))
        o.append("")

    # --- Değer
    if not s.deger.empty:
        d = s.deger[(s.deger["test_sezonu"] == T) & (s.deger["yontem"] == biz)]
        hedef = "gercek" if s.sentetik else "talep"
        d = d[d["hedef"] == hedef].set_index("plan")
        if len(d) == 2:
            a, mo = d.loc["gerceklesen_alim"], d.loc["model_onerisi"]
            o.append("## Üretim adedi örneği (değer analizi)\n")
            o.append(f"Her model-renk için üretim adedi, tahmin dağılımının kritik orana karşılık gelen noktasından seçildi "
                     f"(gazeteci problemi; kritik oran medyanı {yuzde(mo['kritik_oran_medyan'])}: etiket fiyatı x (1 - {yuzde(s.ayar.ortalama_indirim)} ort. indirim), "
                     f"satılmayan stok maliyetin {yuzde(s.ayar.hurda_orani)}'i ile eritilir). Aynı talep karşısında gerçekleşen alımla kıyas "
                     f"({HEDEF_AD[hedef]}, TRY etiket fiyatıyla, mağazalar arası dağıtım kaybı yok sayılarak):\n")
            o.append(_tablo(pd.DataFrame({
                "": ["Üretim (adet)", "Satılan", "Kaçan satış", "Artan stok", "Brüt kâr (TRY, yaklaşık)"],
                "Gerçekleşen alım": [sayi(a[k]) for k in ("uretim", "satilan", "kacan_satis", "artan_stok", "brut_kar_try")],
                "Model önerisi": [sayi(mo[k]) for k in ("uretim", "satilan", "kacan_satis", "artan_stok", "brut_kar_try")]})))
            o.append("")
            if s.sentetik:
                o.append("> Sentetik veride 'gerçekleşen alım', gerçek beklenen talebi bilen ve sezon içinde tekrar sipariş verebilen bir alıcıya aittir. "
                         "Gerçek bir alıcı bu bilgiye sahip değildir; bu yüzden bu tablo değerin büyüklüğünü değil, ölçüm yöntemini gösterir. "
                         "Gerçek veride asıl kıyas budur: müşterinin kendi alım kararları ile modelin önerisi aynı talep karşısında.\n")

    # --- Benzer ürün
    if not s.benzer.empty:
        o.append("## Benzer ürün açıklaması (örnekler)\n")
        o.append("Test sezonundaki yeni (devamlı olmayan) ürünler için 'buna en çok benzeyen geçmiş ürünler ve gerçekte ne kadar sattıkları'. "
                 "Benzerlik 1'e yaklaştıkça ürünler daha çok benzer. Mağaza başı talep, ürünün gönderildiği mağaza başına stok bitişi düzeltilmiş sezon talebidir. "
                 "Tüm ürünler: `benzer_urunler.csv`.\n")
        bz = s.benzer[s.benzer["test_sezonu"] == T]
        u = s.panel.urunler.set_index(["sezon_kodu", "ur_id"])
        ornek = bz[["hedef_sezon", "hedef_ur"]].drop_duplicates("hedef_ur").merge(u.reset_index()[["sezon_kodu", "ur_id", "kategori"]], left_on=["hedef_sezon", "hedef_ur"], right_on=["sezon_kodu", "ur_id"])
        yeni = set(s.panel.urunler.loc[(s.panel.urunler["sezon_kodu"] == T) & ~s.panel.urunler["devamli"].astype(bool), "ur_id"])
        ornek = ornek[ornek["hedef_ur"].isin(yeni)].drop_duplicates("kategori").head(3)["hedef_ur"]
        for ur in ornek:
            h = u.loc[(T, ur)]
            o.append(f"**{ur}** ({h['kategori']}, {h['kalip']}, {h['desen']}, {h['kumas']}, renk {h['renk_kodu']}, göreli fiyat {str(round(float(h['goreli_fiyat']), 2)).replace('.', ',')})\n")
            k = bz[bz["hedef_ur"] == ur].sort_values("sira")
            o.append(_tablo(pd.DataFrame({
                "Benzer ürün": k["komsu_ur"], "Sezon": k["komsu_sezon"], "Benzerlik": [f"{v:.2f}".replace(".", ",") for v in k["benzerlik"]],
                "Özellikler": k["kategori"] + ", " + k["kalip"] + ", " + k["desen"] + ", " + k["renk_kodu"],
                "Mağaza başı talep": [f"{v:.0f}" for v in k["magaza_basi"]], "Toplam satış": [sayi(v) for v in k["satis"]]})))
            o.append("")

    # --- Notlar
    o.append("## Veri notları\n")
    o += [f"- {n}" for n in s.panel.notlar]
    o.append("")
    o.append("## Sınırlar\n")
    o.append("- Test tek (ya da birkaç) sezona dayanır; tek sezonun sonucu şansa açıktır. Gerçek pilotta en az 2 sezon ayrı ayrı test edilmelidir.")
    o.append("- Stok bitişi düzeltmesi bir tahmindir. Ürün bilerek raftan kaldırıldıysa talep fazla tahmin edilir; asortiman planı verisi bunu çözer.")
    o.append("- Sezon geneli seviye kaymaları (ekonomi, hava, marka ivmesi) geçmiş sezonlardan öğrenilemez; aralıklar bunu ancak geçmişte görülen ölçüde kapsar.")
    o.append("- Kampanya takvimi karar anında bilinmiyor kabul edildi; etkisi haftalık profilde ortalama olarak vardır.")
    if s.sentetik:
        o.append("- **Sentetik veri:** talep, bizim yazdığımız bir formülden üretildi. Modeller bu formülün yapısını (kategori, renk, fiyat, bölge etkileri) "
                 "geri bulabildiği için gerçek veriden daha iyi görünebilir. Görsellerdeki bilgi zaten özelliklerde olduğu için sentetik veride görselin "
                 "katkısı ölçülemez; gerçek fotoğraflarda stil bilgisi özelliklerde olmayan bir sinyal taşır.")
    o.append("")
    o.append("## Gerçek veriyle sonraki adım\n")
    o.append("1. Müşteriden veri talep listesindeki tablolar (en az 3 sezon, günlük ya da haftalık stok dahil).")
    o.append("2. `python -m tahmin dogrula <klasör>` ile veri kalitesi raporu, eksiklerin müşteriyle kapatılması.")
    o.append("3. `python -m tahmin geriye-test <klasör>` ile bu raporun gerçek veriyle üretilmesi; son 2 sezon ayrı ayrı test.")
    o.append("4. Müşterinin kendi alım kararlarıyla model önerisinin aynı talep karşısında kıyası (değer analizi).")
    return "\n".join(o) + "\n"
