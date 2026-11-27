"""Stok eritme önerisini Türkçe Markdown rapora ve CSV dosyalarına yazar (gölge mod: fiyat değiştirmez)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from .eritme import EritmeSonucu, projeksiyon_testi, sentetik_karsi_olgu
from .hazirlik import Panel
from .rapor import _tablo, sayi, yuzde


def _ondalik(x: float, n: int = 1) -> str:
    return "-" if pd.isna(x) else (f"{x:.{n}f}".replace(".", ",") if np.isfinite(x) else "∞")


def _tl(x: float) -> str:
    return "-" if pd.isna(x) else f"{sayi(x)} TL"


def eritme_raporu(r: EritmeSonucu, panel: Panel, g: pd.DataFrame, vs, cikti: str | Path, veri_adi: str = "",
                  e_gercek: dict | None = None, ust_n: int = 20) -> Path:
    """e_gercek: yalnızca sentetik veri için sentetiği üreten bölge esneklikleri (karşı-olgu kontrolü)."""
    cikti = Path(cikti)
    cikti.mkdir(parents=True, exist_ok=True)
    sentetik = panel.gercek is not None
    u, sec, b, esn = r.urunler, r.secenekler, r.bolge, r.esneklik
    ad = panel.urunler.drop_duplicates("ur_id").set_index("ur_id")["urun_adi"] if "urun_adi" in panel.urunler else pd.Series(dtype=str)
    u.to_csv(cikti / "eritme_urunler.csv", index=False)
    sec.to_csv(cikti / "eritme_secenekler.csv", index=False)
    b.to_csv(cikti / "eritme_bolge.csv", index=False)
    esn.to_csv(cikti / "eritme_esneklik.csv", index=False)

    # tarihten sonrası veride varsa (geriye dönük çalıştırma) projeksiyon gerçekleşenle karşılaştırılır
    son_veri = g.loc[g["satis"] > 0, "hafta_bas"].max()
    geriye = pd.DataFrame()
    if pd.notna(son_veri) and son_veri > r.tarih + pd.Timedelta(days=28):
        geriye = projeksiyon_testi(r, g, vs)
        geriye.to_csv(cikti / "eritme_projeksiyon_testi.csv", index=False)
    karsi = pd.DataFrame()
    if sentetik and e_gercek:
        karsi = sentetik_karsi_olgu(r, panel, g, e_gercek)
        karsi.to_csv(cikti / "eritme_sentetik_karsi_olgu.csv", index=False)

    o: list[str] = []
    o.append(f"# Stok eritme önerisi: {r.tarih.date()}")
    o.append("")
    o.append(f"Veri: `{veri_adi}` · Rapor tarihi: {date.today()} · **Gölge mod:** öneri yalnızca kaydedilir, fiyat değiştirmez.")
    o.append("")
    if sentetik:
        o.append("> **SENTETİK VERİ.** Bu rapordaki tüm sayılar formülle üretilmiş sentetik bir markanın verisinden gelir. "
                 "Yöntemin çalıştığını gösterir; gerçek bir müşterinin sonucu değildir.")
        o.append("")
    o.append("Sorduğu soru: elde kalan stok, bugünkü satış hızıyla hedef tarihe kadar biter mi; bitmezse hangi ek indirim "
             "marj kuralını bozmadan en çok parayı geri getirir? Her sayının dayanağı yanında yazılıdır.")
    o.append("")

    # ---- özet
    if len(u):
        sis = u[u["sisman"]]
        oner = u[u["onerilen_ek_indirim"] > 0]
        o.append("## Özet")
        o.append("")
        o.append(f"- Sezonu süren ve elinde stok olan **{len(u)}** model-renk var; toplam **{sayi(u['eldeki_stok'].sum())}** adet "
                 f"(mağaza + depo + yoldaki satın alma; ERP).")
        o.append(f"- Bugünkü hızla hedef tarihe kadar bitmeyecek kadar fazla stoğu olan (\"şişmiş\", kapsama kalan sürenin "
                 f"{_ondalik(1.2)} katından uzun): **{len(sis)}** model-renk, **{sayi(sis['eldeki_stok'].sum())}** adet.")
        o.append(f"- Ek indirim önerilen: **{len(oner)}** model-renk. Dağılım: "
                 + ", ".join(f"%{round(100 * k)}: {v}" for k, v in u["onerilen_ek_indirim"].value_counts().sort_index().items()) + ".")
        fark = u["onerilen_katki"].sum() - u["indirimsiz_katki"].sum()
        o.append(f"- İndirimsiz devam etmeye göre beklenen katkı farkı: **{_tl(fark)}** (tahmin; ERP esnekliği x satış hızı, "
                 f"hedef tarihte kalan stok maliyetin %{round(100 * u['kalan_deger_orani'].iloc[0])}'siyle çıkar varsayımı).")
        cel = u[u["hedefler_celisiyor"]]
        if len(cel):
            o.append(f"- **{len(cel)}** model-renkte marj tabanı ile hedef bitiş tarihi birlikte tutmuyor: marjı koruyan hiçbir "
                     "indirim stoğu hedef tarihte bitirmiyor. Bunlar için karar ticari ekibin: tarih mi esner, marj mı, yoksa "
                     "kalan stok outlet/sonraki sezona mı gider?")
        o.append("")

    # ---- esneklik
    o.append("## İndirim satışı ne kadar artırıyor? (esneklik)")
    o.append("")
    o.append("Müşterinin kendi kampanya geçmişinden ölçülür: aynı hafta, aynı ülke ve kategoride indirime giren ürünler ile "
             "girmeyenlerin satış farkı. Ürünün kendi düzeyi (kötü satana indirim yapılması) ve bütün zincirde aynı anda olan "
             "kampanyalar hesaptan çıkarılır. Esneklik 1,5 demek: fiyat %10 düşünce satış yaklaşık %17 artar.")
    o.append("")
    t = esn.copy()
    tab = pd.DataFrame({
        "Grup": t["grup"],
        "Esneklik (%80 aralık)": [f"{_ondalik(a, 2)} ({_ondalik(lo, 2)}-{_ondalik(hi, 2)})" for a, lo, hi in zip(t["e"], t["e_alt"], t["e_ust"])],
        "Yalnız kendi verisi": [f"{_ondalik(a, 2)} ({_ondalik(lo, 2)}-{_ondalik(hi, 2)})" if "e_ham" in t and pd.notna(a) else "-"
                                for a, lo, hi in zip(t.get("e_ham", t["e"]), t.get("e_ham_alt", t["e_alt"]), t.get("e_ham_ust", t["e_ust"]))],
        "%10 indirimle satış artışı": [yuzde(0.9 ** (-a) - 1, True) for a in t["e"]],
        "İndirimli gözlem": [sayi(v) for v in t["indirimli_gozlem"]],
        "Dayanak": t["kaynak"],
    })
    if sentetik and e_gercek:
        tab["Sentetiği üreten değer"] = [_ondalik(e_gercek[k], 2) if k in e_gercek else "-" for k in t["grup"]]
    o.append(_tablo(tab))
    o.append("")
    if len(esn) > 1:
        o.append("- Az veriyle ölçülen gruplar tüm veriden çıkan ortak değere doğru çekilir (\"yalnız kendi verisi\" sütunu çekilmeden önceki halidir). "
             "Bu, bir bölgede birkaç kampanyadan çıkan oynak bir sayıyla karar verilmesini önler.")
    o.append("- Bütün zincirde aynı anda yapılan kampanyalar (sezon sonu, Black Friday) karşılaştırılacak indirimsiz ürün bırakmadığı için "
             "bu ölçüme katkı vermez. Bu kampanyaların trafik etkisi (mağazaya gelen kişi sayısı) fiyat etkisinden ayrı ölçülemez.")
    o.append("")

    # ---- kalibrasyon
    k = r.kalibrasyon
    if k:
        o.append("## Bu yöntem geçen sezon ne kadar isabetliydi?")
        o.append("")
        o.append(f"Aynı yöntem {k['sezon']} sezonunda aynı haftada ({pd.Timestamp(k['tarih']).date()}) çalıştırıldı ve sezon sonuna kadarki "
                 f"gerçek satışla karşılaştırıldı ({k['urun']} model-renk, gerçekte uygulanan fiyatlarla): ürün düzeyi hata (WAPE) "
                 f"**{yuzde(k['wape'])}**, toplam sapma **{yuzde(k['sapma'], True)}**. Aşağıdaki satış ve kalan stok aralıkları "
                 "bu geçmiş hatadan ve esneklik aralığından kurulur (%80 aralık).")
        o.append("")

    # ---- şişmiş ürünler
    if len(u):
        o.append(f"## Öncelikli ürünler (en uzun kapsama, ilk {min(ust_n, len(u))})")
        o.append("")
        o.append("Hız: son 3 haftanın indirimden arındırılmış, iade sonrası net haftalık satışı. Kapsama: eldeki stok bu hızla kaç haftada biter. Gereken hız: hedef tarihte bitmesi için haftada kaç adet satmalı. "
                 "Öneri, marj tabanını koruyan seçenekler içinde (indirim + kalan stoğun değer kaybı) toplam katkısı en yüksek olandır.")
        o.append("")
        s_on = sec.merge(u[["ur_id", "onerilen_ek_indirim"]], on="ur_id")
        s_on = s_on[np.isclose(s_on["ek_indirim"], s_on["onerilen_ek_indirim"])].set_index("ur_id")
        x = u.head(ust_n)
        tab = pd.DataFrame({
            "Ürün": [f"{ur.replace('|', ' ')}" + (f" {ad[ur]}" if ur in ad.index else "") for ur in x["ur_id"]],
            "Stok": [sayi(v) for v in x["eldeki_stok"]],
            "Hız/hafta": [_ondalik(v) for v in x["guncel_hiz"]],
            "Gereken/hafta": [_ondalik(v) for v in x["gerekli_hiz"]],
            "Kapsama (hafta)": [_ondalik(v) for v in x["kapsama_hafta"]],
            "Kalan hafta": x["kalan_hafta"].astype(int).astype(str),
            "Önerilen ek indirim": [f"%{round(100 * v)}" for v in x["onerilen_ek_indirim"]],
            "Satış fiyatı": [_tl(s_on.loc[ur, "satis_fiyati"]) for ur in x["ur_id"]],
            "Brüt marj": [yuzde(s_on.loc[ur, "brut_marj"]) for ur in x["ur_id"]],
            "Hedefte kalan (%80)": [f"{sayi(s_on.loc[ur, 'kalan_p50'])} ({sayi(max(0, s_on.loc[ur, 'kalan_alt']))}-{sayi(s_on.loc[ur, 'kalan_ust'])})" for ur in x["ur_id"]],
            "İndirimsiz kalan": [sayi(v) for v in x["indirimsiz_kalan"]],
            "Katkı farkı": [_tl(a - c) for a, c in zip(x["onerilen_katki"], x["indirimsiz_katki"])],
            "Not": ["marj ve tarih çelişiyor" if c else "" for c in x["hedefler_celisiyor"]],
        })
        o.append(_tablo(tab))
        o.append("")
        o.append(f"Dayanak: stok, hız ve fiyat ERP; esneklik {esn['kaynak'].iloc[0]}; marj tabanı, kalan değer ve KDV "
                 + ("ticari hedefler tablosu." if (u["hedef_kaynagi"] == "ticari_hedefler").all() else "kural varsayımı (ticari_hedefler tablosu gelince müşterinin kendi kuralı)."))
        o.append("")

        # ---- konum: önce transfer
        if len(b):
            bb = b.merge(u[["ur_id", "kalan_hafta", "sisman"]], on="ur_id")
            bb = bb[bb["sisman"] & (bb["bolge"] != "depo")]
            bb = bb[(bb["hiz"] > 0) & ((bb["stok"] >= 20) | (bb["kapsama_hafta"] < 0.5 * bb["kalan_hafta"]))]  # anlamlı miktar
            fazla = bb[bb["kapsama_hafta"] > 2 * bb["kalan_hafta"]]
            az = bb[bb["kapsama_hafta"] < 0.5 * bb["kalan_hafta"]]
            # az kalan bölgenin açığı depodan karşılanabiliyorsa transfer gerekmez: normal ikmal yeter
            depo_st = b[b["bolge"] == "depo"].groupby("ur_id")["stok"].sum()
            acik = (az["hiz"] * az["kalan_hafta"] - az["stok"]).groupby(az["ur_id"]).sum()
            az = az[az["ur_id"].map(lambda ur: depo_st.get(ur, 0) < acik.get(ur, 0))]
            ortak = sorted(set(fazla["ur_id"]) & set(az["ur_id"]))
            o.append("## Konum: önce transfer, sonra indirim")
            o.append("")
            if ortak:
                o.append(f"{len(ortak)} şişmiş model-renkte stok bir bölgede yığılmışken başka bir bölgede hızla tükeniyor. Bu ürünlerde indirimden "
                         "önce bölgeler arası transfer daha az para kaybettirir (transfer maliyeti ve gümrük bu sürümde hesaba katılmadı).")
                o.append("")
                satir = []
                for ur in ortak[:ust_n]:
                    f_ = fazla[fazla["ur_id"] == ur].sort_values("kapsama_hafta", ascending=False).iloc[0]
                    a_ = az[az["ur_id"] == ur].sort_values("kapsama_hafta").iloc[0]
                    satir.append(dict(Ürün=ur.replace("|", " "), Fazla=f"{f_['bolge']} ({sayi(f_['stok'])} adet, {_ondalik(f_['kapsama_hafta'])} hafta)",
                                      Az=f"{a_['bolge']} ({sayi(a_['stok'])} adet, {_ondalik(a_['kapsama_hafta'])} hafta)"))
                o.append(_tablo(pd.DataFrame(satir)))
            else:
                o.append("Şişmiş ürünlerde depodan ikmalle kapanmayacak bir bölge dengesizliği yok: hızlı satan bölgelerin açığı depodaki stokla "
                         "karşılanabiliyor, fazla stok her yerde fazla. Transfer yerine fiyat ya da sonraki sezona aktarım gerekiyor.")
            depo = b[(b["bolge"] == "depo")].merge(u[["ur_id", "sisman"]], on="ur_id")
            depo = depo[depo["sisman"]]
            if len(depo):
                o.append("")
                o.append(f"Şişmiş ürünlerin **{sayi(depo['stok'].sum())}** adedi henüz depoda (yoldaki satın alma dahil). Bu stok mağazaya "
                         "gönderilmeden önce indirim kararı verilirse etiket değişimi ve sevkiyat bir kez yapılır.")
            o.append("")

    # ---- geriye dönük kontrol
    if len(geriye):
        gg = geriye[~geriye["sonradan_siparis"]]
        icinde = ((gg["gercek"] >= gg["alt"]) & (gg["gercek"] <= gg["ust"])).mean()
        o.append("## Geriye dönük kontrol: bu tarihten sonra ne oldu?")
        o.append("")
        o.append(f"Bu rapor geçmiş bir tarih için çalıştırıldı. Gerçekte uygulanan fiyatlar (sezon sonu kampanyaları dahil) projeksiyona uygulandığında "
                 f"{len(gg)} model-renkte: ürün düzeyi hata **{yuzde((gg['tahmin'] - gg['gercek']).abs().sum() / gg['gercek'].sum())}**, "
                 f"toplam sapma **{yuzde(gg['tahmin'].sum() / gg['gercek'].sum() - 1, True)}**, gerçek satışın %80 aralığın içinde kaldığı ürün oranı "
                 f"**{yuzde(icinde)}**.")
        if geriye["sonradan_siparis"].any():
            o.append(f" Bu tarihten sonra verilen tekrar siparişle stoğu artan {int(geriye['sonradan_siparis'].sum())} ürün hesaba katılmadı.")
        o.append("")

    # ---- sentetik karşı-olgu
    if len(karsi):
        top = karsi.groupby("politika")[["net_satis", "kalan", "katki"]].sum()
        top.loc["oneri"] = karsi[karsi["onerilen"]][["net_satis", "kalan", "katki"]].sum()
        kahin = karsi[karsi["politika"] != "gerceklesen"]
        top.loc["kahin"] = kahin.loc[kahin.groupby("ur_id")["katki"].idxmax(), ["net_satis", "kalan", "katki"]].sum()
        ad_ = {"gerceklesen": "Gerçekleşen (sentetik markanın kendi indirimleri)", "sabit_%0": "Hiç ek indirim yok", "oneri": "**Bu öneri**",
               "kahin": "Gerçek esnekliği bilen en iyi sabit indirim (üst sınır)"}
        sira = ["gerceklesen", "sabit_%0", "oneri", "kahin"]
        tab = pd.DataFrame({"Politika": [ad_[k_] for k_ in sira],
                            "Net satış (adet)": [sayi(top.loc[k_, "net_satis"]) for k_ in sira],
                            "Hedefte kalan (adet)": [sayi(top.loc[k_, "kalan"]) for k_ in sira],
                            "Katkı": [_tl(top.loc[k_, "katki"]) for k_ in sira]})
        o.append("## Sentetik kontrol: öneri uygulansaydı?")
        o.append("")
        o.append("Yalnızca sentetik veride yapılabilir: gerçek talep ve onu üreten gerçek esneklik bilindiği için her seçenek ayrı ayrı oynatılır. "
                 "Ürün düzeyinde, haftalık stok tükenmesiyle; mağaza ve beden dağılımı yok sayılır.")
        o.append("")
        o.append(_tablo(tab))
        o.append("")
        g0, on, kh = top.loc["gerceklesen", "katki"], top.loc["oneri", "katki"], top.loc["kahin", "katki"]
        o.append(f"- Öneri, sentetik markanın kendi indirim kararlarına göre katkıyı **{yuzde(on / g0 - 1, True)}** değiştirdi; ulaşılabilecek üst sınırın "
                 f"**{yuzde(on / kh)}**'ini yakaladı. Üst sınır marj tabanını dikkate almaz, bu yüzden tam yakalanması beklenmez.")
        o.append("")

    # ---- notlar
    o.append("## Varsayımlar ve sınırlar")
    o.append("")
    for n in r.notlar:
        o.append(f"- {n}")
    o.append("- İndirim öneri haftasından hedef tarihe kadar sabit kabul edildi; kademeli indirim (önce %20, sonra %40) bu sürümde yok.")
    o.append("- Rakip kampanyaları bu sürümde hesaba girmiyor; Boss Analyze verisi gelince güncel hız rakip indirimine göre ayrıca okunacak.")
    o.append("- Stok model-renk toplamıdır; beden kırıklığı (yalnızca uç bedenlerin kalması) indirimin etkisini düşürebilir.")
    o.append("- Öneri yalnızca kaydedilir (gölge mod). Ticari ekip kararını işaretledikten sonra gerçekleşen satış, önerinin isabetini ölçmek için kullanılır.")
    o.append("")
    yol = cikti / "eritme_raporu.md"
    yol.write_text("\n".join(o), encoding="utf-8")
    return yol
