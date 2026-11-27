"""Veri kalitesi kontrolleri. Her bulgu seviye (HATA / UYARI / BİLGİ) taşır.

HATA: düzeltilmeden geriye dönük test anlamsız olur.
UYARI: test çalışır ama sonuçlar bu konuda yanlı olabilir.
BİLGİ: verinin şekli hakkında not.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .sozlesme import TABLO, TABLOLAR, Zorunluluk
from .yukleme import VeriSeti

HATA, UYARI, BILGI = "HATA", "UYARI", "BİLGİ"


@dataclass
class Bulgu:
    seviye: str
    tablo: str
    kontrol: str
    mesaj: str
    adet: int = 0


def _oran(n: int, toplam: int) -> str:
    return f"%{100 * n / toplam:.1f}" if toplam else "-"


def _sema_kontrolleri(vs: VeriSeti) -> list[Bulgu]:
    b: list[Bulgu] = []
    for t in TABLOLAR:
        if t.ad not in vs:
            if t.zorunluluk == Zorunluluk.ZORUNLU:
                b.append(Bulgu(HATA, t.ad, "tablo", f"Zorunlu tablo yok: {t.dosya_adi}"))
            elif t.zorunluluk == Zorunluluk.ONERILEN:
                b.append(Bulgu(UYARI, t.ad, "tablo", f"Önerilen tablo yok: {t.dosya_adi}"))
            continue
        df = vs[t.ad]
        n = len(df)
        for eksik in vs.eksik_alanlar.get(t.ad, []):
            b.append(Bulgu(HATA, t.ad, "alan", f"Zorunlu alan yok: {eksik}"))
        for alan, sayi in vs.cevrim_hatalari.get(t.ad, {}).items():
            sev = HATA if sayi > 0.01 * n else UYARI
            b.append(Bulgu(sev, t.ad, "tip", f"{alan}: {sayi} değer ({_oran(sayi, n)}) {t.alan(alan).tip.value} olarak okunamadı", sayi))
        for a in t.alanlar:
            if a.ad not in df.columns:
                continue
            kol = df[a.ad]
            if a.zorunlu:
                bos = int(kol.isna().sum())
                if bos:
                    b.append(Bulgu(HATA, t.ad, "bos", f"{a.ad}: {bos} satırda boş ({_oran(bos, n)})", bos))
            if a.izinli:
                gecersiz = int((kol.notna() & ~kol.isin(a.izinli)).sum())
                if gecersiz:
                    ornek = ", ".join(map(str, kol[kol.notna() & ~kol.isin(a.izinli)].unique()[:5]))
                    b.append(Bulgu(UYARI, t.ad, "izinli", f"{a.ad}: {gecersiz} satır izinli değerlerin dışında (ör. {ornek})", gecersiz))
            if a.min_deger is not None and pd.api.types.is_numeric_dtype(kol):
                alt = int((kol < a.min_deger).sum())
                if alt:
                    b.append(Bulgu(HATA, t.ad, "aralik", f"{a.ad}: {alt} satır {a.min_deger} altında", alt))
        if t.anahtar and all(k in df.columns for k in t.anahtar):
            tekrar = int(df.duplicated(list(t.anahtar)).sum())
            if tekrar:
                b.append(Bulgu(HATA, t.ad, "anahtar", f"{', '.join(t.anahtar)} için {tekrar} tekrar eden satır", tekrar))
        elif not t.anahtar:
            tekrar = int(df.duplicated().sum())
            if tekrar:
                b.append(Bulgu(UYARI, t.ad, "anahtar", f"{tekrar} birebir aynı satır", tekrar))
    return b


def _referans_kontrolleri(vs: VeriSeti) -> list[Bulgu]:
    b: list[Bulgu] = []
    for t in TABLOLAR:
        if t.ad not in vs:
            continue
        df = vs[t.ad]
        for a in t.alanlar:
            if not a.referans or a.ad not in df.columns:
                continue
            hedef_tablo, hedef_alan = a.referans.split(".")
            if hedef_tablo not in vs:
                continue
            gecerli = set(vs[hedef_tablo][hedef_alan].dropna())
            kol = df[a.ad].dropna()
            yetim = int((~kol.isin(gecerli)).sum())
            if yetim:
                sev = HATA if yetim > 0.01 * len(df) else UYARI
                b.append(Bulgu(sev, t.ad, "referans", f"{a.ad}: {yetim} satır {a.referans} içinde yok ({_oran(yetim, len(df))})", yetim))
    if "stok" in vs and "magazalar" in vs:
        lok = set(vs["magazalar"]["magaza_kodu"].dropna())
        if "depolar" in vs:
            lok |= set(vs["depolar"]["depo_kodu"].dropna())
        yetim = int((~vs["stok"]["lokasyon_kodu"].isin(lok)).sum())
        if yetim:
            b.append(Bulgu(UYARI, "stok", "referans", f"lokasyon_kodu: {yetim} satır mağaza ya da depo listesinde yok", yetim))
    return b


def _is_kurallari(vs: VeriSeti) -> list[Bulgu]:
    b: list[Bulgu] = []
    satis = vs.get("satislar")
    stok = vs.get("stok")
    mag = vs.get("magazalar")

    if satis is not None and {"brut_tutar", "net_tutar"} <= set(satis.columns):
        fazla = int((satis["net_tutar"] > satis["brut_tutar"] * 1.01).sum())
        if fazla:
            b.append(Bulgu(UYARI, "satislar", "tutar", f"{fazla} satırda net tutar brüt tutardan büyük", fazla))

    if satis is not None and mag is not None and "acilis_tarihi" in mag.columns:
        m = satis[["tarih", "magaza_kodu"]].merge(mag[["magaza_kodu", "acilis_tarihi", "kapanis_tarihi"]], on="magaza_kodu", how="left")
        disarida = (m["tarih"] < m["acilis_tarihi"]) | (m["kapanis_tarihi"].notna() & (m["tarih"] > m["kapanis_tarihi"]))
        n = int(disarida.sum())
        if n:
            b.append(Bulgu(UYARI, "satislar", "magaza_tarihi", f"{n} satış satırı mağazanın açılış-kapanış aralığı dışında", n))

    if satis is not None and "tarih" in satis.columns and satis["tarih"].notna().any():
        hafta = satis.assign(h=satis["tarih"].dt.to_period("W-SUN")).groupby(["magaza_kodu", "h"])["adet"].sum()
        bosluk = 0
        for kod, seri in hafta.groupby(level=0):
            donemler = seri.index.get_level_values(1)
            beklenen = pd.period_range(donemler.min(), donemler.max(), freq="W-SUN")
            bosluk += len(beklenen) - len(donemler)
        if bosluk:
            b.append(Bulgu(UYARI, "satislar", "bosluk", f"Mağazaların açık olduğu dönemde toplam {bosluk} mağaza-hafta hiç satış yok (eksik veri ya da kapanma?)", bosluk))
        if "urunler" in vs:
            sezonlar = vs["urunler"]["sezon_kodu"].nunique()
            sev = HATA if sezonlar < 2 else (UYARI if sezonlar < 3 else BILGI)
            b.append(Bulgu(sev, "urunler", "gecmis", f"{sezonlar} sezon var (en az 3 önerilir: 2+ eğitim, 1 test)", sezonlar))
        b.append(Bulgu(BILGI, "satislar", "aralik", f"Satış tarihleri {satis['tarih'].min():%Y-%m-%d} - {satis['tarih'].max():%Y-%m-%d}, {len(satis):,} satır"))

    if stok is not None and "eldeki_adet" in stok.columns:
        neg = int((stok["eldeki_adet"] < 0).sum())
        if neg:
            b.append(Bulgu(UYARI, "stok", "negatif", f"{neg} satırda negatif stok (sıfır kabul edilecek)", neg))
        tarihler = stok["tarih"].dropna().drop_duplicates().sort_values()
        if len(tarihler) > 1:
            aralik = tarihler.diff().dt.days.median()
            tur = "günlük" if aralik <= 1 else ("haftalık" if aralik <= 7 else f"{aralik:.0f} günlük")
            sev = BILGI if aralik <= 7 else UYARI
            b.append(Bulgu(sev, "stok", "siklik", f"Stok anlık görüntüleri {tur} (medyan {aralik:.0f} gün)"))
        if satis is not None:
            s = satis.assign(h=satis["tarih"].dt.to_period("W-SUN"))[["magaza_kodu", "sku_kodu", "h"]].drop_duplicates()
            st = stok.assign(h=stok["tarih"].dt.to_period("W-SUN")).rename(columns={"lokasyon_kodu": "magaza_kodu"})[["magaza_kodu", "sku_kodu", "h"]].drop_duplicates()
            kapsanan = len(s.merge(st, on=["magaza_kodu", "sku_kodu", "h"]))
            oran = kapsanan / len(s) if len(s) else 1
            sev = BILGI if oran >= 0.9 else UYARI
            b.append(Bulgu(sev, "stok", "kapsama", f"Satış olan mağaza-SKU-haftaların {_oran(kapsanan, len(s))}'inde stok kaydı var (stok bitişi düzeltmesi bunlara dayanır)"))

    po = vs.get("satin_alma_siparisleri")
    if po is not None and {"siparis_tarihi", "teslim_tarihi"} <= set(po.columns):
        sure = (po["teslim_tarihi"] - po["siparis_tarihi"]).dt.days
        ters = int((sure < 0).sum())
        if ters:
            b.append(Bulgu(HATA, "satin_alma_siparisleri", "tarih", f"{ters} satırda teslim tarihi sipariş tarihinden önce", ters))
        if sure.notna().any():
            b.append(Bulgu(BILGI, "satin_alma_siparisleri", "tedarik_suresi", f"Tedarik süresi medyan {sure.median():.0f} gün (%10-%90: {sure.quantile(.1):.0f}-{sure.quantile(.9):.0f})"))

    fiyat = vs.get("fiyat_gecmisi")
    if fiyat is not None and "raf_fiyati" in fiyat.columns:
        ters = int((fiyat["raf_fiyati"] > fiyat["liste_fiyati"] * 1.001).sum())
        if ters:
            b.append(Bulgu(UYARI, "fiyat_gecmisi", "fiyat", f"{ters} satırda raf fiyatı liste fiyatından yüksek", ters))

    iade = vs.get("iadeler")
    if iade is not None and satis is not None and len(satis):
        oran = iade["adet"].sum() / max(satis["adet"].sum(), 1)
        sev = UYARI if oran > 0.5 else BILGI
        b.append(Bulgu(sev, "iadeler", "oran", f"Genel iade oranı %{100 * oran:.1f}"))

    gorsel = vs.get("urun_gorselleri")
    if gorsel is not None and "urunler" in vs:
        urun = set(vs["urunler"]["urun_kodu"].dropna())
        var = set(gorsel["urun_kodu"].dropna()) & urun
        b.append(Bulgu(BILGI if len(var) >= 0.9 * len(urun) else UYARI, "urun_gorselleri", "kapsama", f"Modellerin {_oran(len(var), len(urun))}'inin görseli var"))
        eksik_dosya = [d for d in gorsel["dosya_adi"].dropna() if not (vs.klasor / "gorseller" / d).exists()]
        if eksik_dosya:
            b.append(Bulgu(UYARI, "urun_gorselleri", "dosya", f"{len(eksik_dosya)} görsel dosyası gorseller/ klasöründe bulunamadı (ör. {eksik_dosya[0]})", len(eksik_dosya)))
    return b


def dogrula(vs: VeriSeti) -> list[Bulgu]:
    bulgular = _sema_kontrolleri(vs) + _referans_kontrolleri(vs) + _is_kurallari(vs)
    sira = {HATA: 0, UYARI: 1, BILGI: 2}
    return sorted(bulgular, key=lambda x: (sira[x.seviye], x.tablo))


def rapor_md(bulgular: list[Bulgu], baslik: str = "Veri kalitesi raporu") -> str:
    say = {s: sum(1 for x in bulgular if x.seviye == s) for s in (HATA, UYARI, BILGI)}
    satir = [f"# {baslik}", "", f"{say[HATA]} hata, {say[UYARI]} uyarı, {say[BILGI]} bilgi.", ""]
    if say[HATA]:
        satir += ["Hatalar düzeltilmeden geriye dönük test sonuçları güvenilir değildir.", ""]
    satir += ["| Seviye | Tablo | Kontrol | Bulgu |", "|---|---|---|---|"]
    satir += [f"| {x.seviye} | {x.tablo} | {x.kontrol} | {x.mesaj} |" for x in bulgular]
    return "\n".join(satir) + "\n"


def hata_var(bulgular: list[Bulgu]) -> bool:
    return any(x.seviye == HATA for x in bulgular)


__all__ = ["Bulgu", "dogrula", "rapor_md", "hata_var", "HATA", "UYARI", "BILGI", "TABLO"]
