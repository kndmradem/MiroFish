"""SENTETİK veri üreteci. Gerçek bir markanın verisi DEĞİLDİR.

Veri sözleşmesindeki formatta çok sezonlu bir hazır giyim zinciri üretir:
mevsimsellik, kampanyalar, bayram/özel gün etkileri, bölge farkları (kategori,
renk, fiyat duyarlılığı, beden eğrisi), alıcı tahmin hatası yüzünden stok
bitişleri ve fazla stok, tekrar siparişleri, kalıcı indirimler, iadeler ve
TRY enflasyonu.

Ürünlerin "gerçek" talebi bilindiği için (_sentetik_gercek_talep.csv) stok
bitişi düzeltmesinin ne kadar işe yaradığı da ölçülebilir. Bu dosya gerçek
veride yoktur ve modellere verilmez.

Sınır: talebi biz formülle ürettik; modeller bu formülü ne kadar iyi geri
bulursa o kadar iyi görünür. Gerçek veride sonuçlar daha kötü olabilir.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .bolgeler import bolge

# --- Sabitler ----------------------------------------------------------------

BEDENLER = ("XS", "S", "M", "L", "XL")
JEAN_BEDENLER = ("34", "36", "38", "40", "42")

# kategori: (taban haftalık adet / ortalama mağaza, USD maliyet, iade oranı, sezonlar)
KATEGORILER: dict[str, tuple[float, float, float, str]] = {
    "tisort": (2.6, 6, 0.07, "SS AW"),
    "gomlek": (1.8, 11, 0.10, "SS AW"),
    "elbise": (1.5, 16, 0.22, "SS AW"),
    "etek": (1.2, 10, 0.14, "SS"),
    "sort": (1.6, 8, 0.09, "SS"),
    "pantolon": (1.6, 13, 0.14, "SS AW"),
    "jean": (1.8, 15, 0.18, "SS AW"),
    "ceket": (0.9, 26, 0.12, "SS AW"),
    "kazak": (1.7, 14, 0.09, "AW"),
    "mont": (1.0, 38, 0.10, "AW"),
}
SEZON_KATEGORI_AGIRLIK = {
    "SS": {"tisort": 4, "gomlek": 3, "elbise": 3, "etek": 2, "sort": 2, "pantolon": 2, "jean": 2, "ceket": 1},
    "AW": {"kazak": 4, "mont": 2, "ceket": 2, "pantolon": 2, "jean": 2, "gomlek": 2, "elbise": 2, "tisort": 1},
}
KUMASLAR = {
    "tisort": ("pamuk", "pamuk", "viskon", "polyester"),
    "gomlek": ("pamuk", "keten", "viskon"),
    "elbise": ("viskon", "pamuk", "keten", "polyester"),
    "etek": ("viskon", "pamuk", "polyester"),
    "sort": ("pamuk", "keten", "denim"),
    "pantolon": ("pamuk", "keten", "polyester", "yun"),
    "jean": ("denim",),
    "ceket": ("pamuk", "yun", "polyester", "keten"),
    "kazak": ("yun", "pamuk", "akrilik"),
    "mont": ("polyester", "yun", "pamuk"),
}
YAKALAR = {
    "tisort": ("bisiklet", "v"), "gomlek": ("gomlek_yaka",), "elbise": ("bisiklet", "v", "kare"),
    "etek": ("yok",), "sort": ("yok",), "pantolon": ("yok",), "jean": ("yok",),
    "ceket": ("klasik", "kapusonlu"), "kazak": ("bisiklet", "balikci", "v"), "mont": ("kapusonlu", "dik"),
}
DESENLER = ("duz", "cizgili", "cicekli", "ekose", "baskili")
DESEN_OLASILIK = (0.55, 0.15, 0.13, 0.09, 0.08)
DESEN_ETKI = {"duz": 0.0, "cizgili": -0.05, "cicekli": 0.05, "ekose": -0.15, "baskili": -0.1}
KALIPLAR = ("slim", "regular", "oversize")

# kod: (ad, RGB, taban etki, yıllık trend)
RENKLER = {
    "SYH": ("siyah", (25, 25, 25), 0.35, 0.0),
    "BYZ": ("beyaz", (240, 240, 236), 0.25, 0.0),
    "LCV": ("lacivert", (28, 38, 82), 0.15, 0.0),
    "BEJ": ("bej", (214, 194, 160), 0.05, 0.12),
    "GRI": ("gri", (130, 130, 130), 0.0, -0.05),
    "KRM": ("kirmizi", (188, 32, 42), -0.15, -0.08),
    "YSL": ("yesil", (52, 120, 64), -0.30, 0.22),
    "PMB": ("pembe", (232, 152, 170), -0.20, 0.0),
    "MAV": ("mavi", (72, 122, 200), 0.0, 0.0),
    "KHV": ("kahverengi", (112, 72, 42), -0.10, 0.08),
    "HAK": ("haki", (122, 120, 72), -0.20, 0.05),
    "SAR": ("sari", (230, 200, 64), -0.40, 0.0),
}
KALIP_TREND = {"slim": -0.10, "regular": 0.0, "oversize": 0.15}

BOLGE_KATEGORI = {
    "MENA": {"mont": -1.3, "kazak": -0.9, "elbise": 0.3, "sort": -0.7, "etek": 0.1},
    "CIS": {"mont": 0.4, "kazak": 0.3, "sort": -0.3},
    "EU": {"ceket": 0.2, "gomlek": 0.1},
    "US": {"tisort": 0.2, "jean": 0.25, "sort": 0.2},
    "TR": {},
}
BOLGE_RENK = {
    "MENA": {"BYZ": 0.35, "BEJ": 0.35, "SYH": 0.1, "KRM": -0.1, "SAR": 0.1},
    "CIS": {"SYH": 0.3, "KHV": 0.2, "PMB": -0.1},
    "EU": {"LCV": 0.2, "GRI": 0.15, "SAR": -0.2},
    "US": {"MAV": 0.2, "KRM": 0.1},
    "TR": {"SYH": 0.1},
}
# göreli fiyat esnekliği (log fiyat oranı başına) ve kampanya esnekliği
BOLGE_FIYAT_ESNEKLIK = {"TR": -1.4, "CIS": -1.2, "MENA": -0.6, "EU": -0.8, "US": -0.9}
BOLGE_KAMPANYA_ESNEKLIK = {"TR": 1.8, "CIS": 1.6, "MENA": 1.3, "EU": 1.5, "US": 1.7}
BOLGE_BEDEN = {
    "TR": (0.10, 0.25, 0.32, 0.22, 0.11),
    "EU": (0.07, 0.20, 0.32, 0.26, 0.15),
    "US": (0.05, 0.17, 0.30, 0.28, 0.20),
    "MENA": (0.06, 0.20, 0.33, 0.26, 0.15),
    "CIS": (0.12, 0.28, 0.32, 0.19, 0.09),
}

# kod, ad, ülke, şehir, kanal, lokasyon, m2, açılış, kapanış
MAGAZALAR = (
    ("M-IST-01", "Istanbul AVM 1", "TR", "Istanbul", "magaza", "avm", 620, "2018-04-01", None),
    ("M-IST-02", "Istanbul Cadde", "TR", "Istanbul", "magaza", "cadde", 350, "2016-09-01", None),
    ("M-IST-03", "Istanbul AVM 2", "TR", "Istanbul", "magaza", "avm", 450, "2020-02-01", None),
    ("M-ANK-01", "Ankara AVM", "TR", "Ankara", "magaza", "avm", 500, "2019-03-01", None),
    ("M-IZM-01", "Izmir AVM", "TR", "Izmir", "magaza", "avm", 400, "2019-10-01", None),
    ("M-ANT-01", "Antalya AVM", "TR", "Antalya", "magaza", "avm", 300, "2024-03-04", None),
    ("M-BUR-01", "Bursa Cadde", "TR", "Bursa", "magaza", "cadde", 250, "2017-05-01", None),
    ("O-TR", "Online TR", "TR", "Istanbul", "online", "online", None, "2017-01-01", None),
    ("M-BER-01", "Berlin", "DE", "Berlin", "magaza", "cadde", 380, "2021-04-01", None),
    ("M-MUC-01", "Munih", "DE", "Munich", "magaza", "avm", 300, "2022-03-01", None),
    ("M-AMS-01", "Amsterdam", "NL", "Amsterdam", "magaza", "cadde", 280, "2021-09-01", None),
    ("M-PAR-01", "Paris", "FR", "Paris", "magaza", "cadde", 260, "2021-06-01", "2025-01-31"),
    ("O-EU", "Online EU", "DE", "Berlin", "online", "online", None, "2021-01-01", None),
    ("M-DXB-01", "Dubai", "AE", "Dubai", "magaza", "avm", 520, "2020-11-01", None),
    ("M-RUH-01", "Riyad", "SA", "Riyadh", "magaza", "avm", 450, "2022-01-15", None),
    ("M-DOH-01", "Doha", "QA", "Doha", "magaza", "avm", 300, "2024-09-02", None),
    ("M-CAI-01", "Kahire", "EG", "Cairo", "franchise", "avm", 280, "2021-02-01", None),
    ("M-ALA-01", "Almati", "KZ", "Almaty", "magaza", "avm", 380, "2020-05-01", None),
    ("M-BAK-01", "Baku", "AZ", "Baku", "magaza", "avm", 300, "2019-08-01", None),
    ("M-TAS-01", "Taskent", "UZ", "Tashkent", "franchise", "avm", 250, "2022-10-01", None),
    ("M-NYC-01", "New York", "US", "New York", "magaza", "cadde", 300, "2022-05-01", None),
)
ONLINE_CARPAN = {"O-TR": 3.0, "O-EU": 2.2}
PARA_BIRIMI = {"TR": "TRY", "DE": "EUR", "NL": "EUR", "FR": "EUR"}  # diğerleri USD

# Ramazan Bayramı, Ramazan başlangıcı, Kurban Bayramı, Black Friday
OZEL_GUNLER = {
    2023: ("2023-04-21", "2023-03-23", "2023-06-28", "2023-11-24"),
    2024: ("2024-04-10", "2024-03-11", "2024-06-16", "2024-11-29"),
    2025: ("2025-03-30", "2025-03-01", "2025-06-06", "2025-11-28"),
    2026: ("2026-03-20", "2026-02-18", "2026-05-27", "2026-11-27"),
}
USDTRY = {2023: 18.8, 2024: 29.9, 2025: 35.5, 2026: 43.0, 2027: 50.0}

HAFTA = 26
PROFIL = {
    "SS": np.array([.55, .65, .75, .85, .95, 1.0, 1.05, 1.1, 1.15, 1.2, 1.2, 1.2, 1.15, 1.1, 1.05, 1.0, .95, .9, .85, .8, .75, .7, .65, .6, .55, .5]),
    "AW": np.array([.5, .6, .7, .8, .9, 1.0, 1.05, 1.1, 1.15, 1.2, 1.2, 1.25, 1.25, 1.2, 1.2, 1.15, 1.1, 1.0, .9, .8, .75, .7, .65, .6, .55, .5]),
}
GUN_AGIRLIK = np.array([0.11, 0.11, 0.12, 0.13, 0.16, 0.21, 0.16])


@dataclass
class SentetikAyar:
    tohum: int = 7
    ilk_yil: int = 2023
    yil_sayisi: int = 3
    model_sayisi: int = 45  # sezon başına yeni + devamlı model
    devamli_oran: float = 0.15
    gorsel: bool = True
    gorsel_boyut: int = 48


@dataclass
class Sezon:
    kod: str
    tip: str
    yil: int
    baslangic: pd.Timestamp

    def hafta_basi(self, k: int) -> pd.Timestamp:
        return self.baslangic + pd.Timedelta(days=7 * k)


def _sezonlar(ayar: SentetikAyar) -> list[Sezon]:
    out = []
    for y in range(ayar.ilk_yil, ayar.ilk_yil + ayar.yil_sayisi):
        for tip, hafta in (("SS", 6), ("AW", 32)):
            out.append(Sezon(f"{y}-{tip}", tip, y, pd.Timestamp.fromisocalendar(y, hafta, 1)))
    return out


def _yuvarla_fiyat(p: np.ndarray, para: str) -> np.ndarray:
    if para == "TRY":
        return np.floor(p / 10) * 10 + 9.90
    return np.floor(p) + 0.99


# --- Görsel ------------------------------------------------------------------

def _gorsel_ciz(path: Path, kategori: str, rgb: tuple[int, int, int], desen: str, rng: np.random.Generator, boyut: int) -> None:
    from PIL import Image, ImageDraw

    s = boyut
    img = Image.new("RGB", (s, s), (246, 246, 244))
    d = ImageDraw.Draw(img)
    renk = tuple(int(np.clip(c + rng.normal(0, 6), 0, 255)) for c in rgb)
    u = s / 48
    if kategori in ("tisort", "gomlek", "kazak", "ceket", "mont"):
        kol = 6 if kategori == "tisort" else 14
        poly = [(14, 8), (34, 8), (44, 8 + kol), (38, 8 + kol + 4), (34, 14), (34, 44), (14, 44), (14, 14), (10, 8 + kol + 4), (4, 8 + kol)]
        if kategori == "mont":
            poly = [(x + (2 if x > 24 else -2), y) for x, y in poly]
        d.polygon([(x * u, y * u) for x, y in poly], fill=renk)
    elif kategori == "elbise":
        d.polygon([(x * u, y * u) for x, y in [(18, 4), (30, 4), (32, 18), (40, 44), (8, 44), (16, 18)]], fill=renk)
    elif kategori == "etek":
        d.polygon([(x * u, y * u) for x, y in [(16, 10), (32, 10), (40, 40), (8, 40)]], fill=renk)
    else:  # pantolon, jean, sort
        boy = 24 if kategori == "sort" else 44
        d.polygon([(x * u, y * u) for x, y in [(14, 4), (34, 4), (36, boy), (26, boy), (24, 16), (22, boy), (12, boy)]], fill=renk)
    koyu = tuple(int(c * 0.55) for c in renk)
    acik = tuple(int(255 - (255 - c) * 0.3) for c in renk)
    maske = Image.new("L", (s, s), 0)
    ImageDraw.Draw(maske).bitmap((0, 0), img.convert("L").point(lambda v: 255 if v < 240 else 0))
    desenli = img.copy()
    dd = ImageDraw.Draw(desenli)
    if desen == "cizgili":
        for y in range(0, s, max(2, int(5 * u))):
            dd.line([(0, y), (s, y)], fill=koyu, width=max(1, int(1.5 * u)))
    elif desen == "ekose":
        for t in range(0, s, max(3, int(7 * u))):
            dd.line([(0, t), (s, t)], fill=koyu, width=max(1, int(u)))
            dd.line([(t, 0), (t, s)], fill=koyu, width=max(1, int(u)))
    elif desen == "cicekli":
        for _ in range(int(14 * u * u)):
            x, y = rng.uniform(0, s, 2)
            r = 1.6 * u
            dd.ellipse([x - r, y - r, x + r, y + r], fill=acik if sum(renk) < 300 else koyu)
    elif desen == "baskili":
        dd.rectangle([20 * u, 18 * u, 28 * u, 26 * u], fill=acik if sum(renk) < 300 else koyu)
    img = Image.composite(desenli, img, maske.point(lambda v: v))
    img.save(path, optimize=True)


# --- Ana üretici ---------------------------------------------------------------

def _magaza_df(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for kod, ad, ulke, sehir, kanal, lok, m2, ac, kap in MAGAZALAR:
        rows.append(dict(
            magaza_kodu=kod, magaza_adi=ad, kanal=kanal, ulke=ulke, sehir=sehir, lokasyon_tipi=lok,
            metrekare=m2, acilis_tarihi=ac, kapanis_tarihi=kap, para_birimi=PARA_BIRIMI.get(ulke, "USD"),
        ))
    df = pd.DataFrame(rows)
    df["bolge"] = df["ulke"].map(bolge)
    m2 = df["metrekare"].fillna(400).astype(float)
    carpan = (m2 / 400) ** 0.7 * np.where(df["lokasyon_tipi"] == "avm", 1.1, 1.0) * np.exp(rng.normal(0, 0.15, len(df)))
    for kod, c in ONLINE_CARPAN.items():
        carpan[df["magaza_kodu"] == kod] = c
    df["_carpan"] = carpan
    return df


def _takvim(yillar: range) -> pd.DataFrame:
    rows = []
    bayram_ulke = ["TR", "AE", "SA", "QA", "EG", "AZ", "KZ", "UZ"]
    for y in yillar:
        if y not in OZEL_GUNLER:
            continue
        rb, rbas, kb, bf = OZEL_GUNLER[y]
        for u in bayram_ulke:
            rows.append((rb, u, "dini_bayram", "Ramazan Bayramı"))
            rows.append((kb, u, "dini_bayram", "Kurban Bayramı"))
        for u in ["AE", "SA", "QA", "EG"]:
            rows.append((rbas, u, "ozel_gun", "Ramazan başlangıcı"))
        for u in ["TR", "DE", "NL", "FR", "AE", "SA", "QA", "EG", "KZ", "AZ", "UZ", "US"]:
            rows.append((bf, u, "ozel_gun", "Black Friday / Efsane Cuma"))
        for u in ["DE", "NL", "FR", "US"]:
            rows.append((f"{y}-12-25", u, "resmi_tatil", "Noel"))
        for u in ["TR", "DE", "NL", "FR", "AE", "SA", "QA", "EG", "KZ", "AZ", "UZ", "US"]:
            rows.append((f"{y}-01-01", u, "resmi_tatil", "Yılbaşı"))
        for u in ["KZ", "AZ", "UZ"]:
            rows.append((f"{y}-03-08", u, "resmi_tatil", "8 Mart"))
    return pd.DataFrame(rows, columns=["tarih", "ulke", "gun_tipi", "aciklama"])


def _ozel_gun_carpani(sz: Sezon, mag: pd.DataFrame) -> np.ndarray:
    """(mağaza, hafta) özel gün çarpanı."""
    S = len(mag)
    c = np.ones((S, HAFTA))
    bas = sz.baslangic
    hafta_no = lambda t: int((pd.Timestamp(t) - bas).days // 7)  # noqa: E731
    bolgeler = mag["bolge"].to_numpy()
    ulkeler = mag["ulke"].to_numpy()

    def uygula(tarih, maske, carpan, once=0):
        k = hafta_no(tarih) - once
        if 0 <= k < HAFTA:
            c[maske, k] *= carpan

    for y in (sz.yil, sz.yil + 1):
        if y not in OZEL_GUNLER:
            continue
        rb, rbas, kb, bf = OZEL_GUNLER[y]
        bayram = np.isin(ulkeler, ["TR", "AE", "SA", "QA", "EG", "AZ", "KZ", "UZ"])
        uygula(pd.Timestamp(rb) - pd.Timedelta(days=3), bayram, 1.5)
        uygula(pd.Timestamp(rb) - pd.Timedelta(days=10), bayram, 1.2)
        uygula(pd.Timestamp(kb) - pd.Timedelta(days=3), np.isin(bolgeler, ["TR", "MENA"]), 1.15)
        k0, k1 = hafta_no(rbas), hafta_no(pd.Timestamp(rb) - pd.Timedelta(days=7))
        for k in range(max(k0, 0), min(k1, HAFTA - 1) + 1):
            c[bolgeler == "MENA", k] *= 0.85
        uygula(bf, np.ones(S, bool), 1.3)
        for g in (11, 18):
            uygula(f"{y}-12-{g}", np.isin(bolgeler, ["EU", "US"]), 1.35)
        uygula(f"{y}-12-28", bolgeler == "CIS", 1.4)
        uygula(f"{y}-12-28", bolgeler == "TR", 1.2)
        uygula(f"{y}-03-06", bolgeler == "CIS", 1.2)
        uygula(f"{y}-09-08", np.ones(S, bool), 1.1)
    return c


def _kampanyalar(sz: Sezon, mag: pd.DataFrame) -> tuple[list[dict], list[dict], np.ndarray, np.ndarray]:
    """Kampanya kayıtları ve (mağaza, hafta) indirim oranı + kampanya indeksi."""
    S = len(mag)
    indirim = np.zeros((S, HAFTA))
    kod_idx = np.full((S, HAFTA), -1)
    kayit, kapsam = [], []
    bas = sz.baslangic

    def ekle(ad, mekanik, oran, k0, k1, maske=None, kanal=None, ulkeler=None):
        k0, k1 = max(k0, 0), min(k1, HAFTA - 1)
        if k0 > k1:
            return
        kod = f"K-{sz.kod}-{len(kayit) + 1:02d}"
        kayit.append(dict(
            kampanya_kodu=kod, kampanya_adi=ad, mekanik=mekanik, indirim_orani=oran,
            baslangic_tarihi=(bas + pd.Timedelta(days=7 * k0)).date(),
            bitis_tarihi=(bas + pd.Timedelta(days=7 * k1 + 6)).date(), kanal=kanal or "",
        ))
        if ulkeler:
            kapsam.extend(dict(kampanya_kodu=kod, ulke=u) for u in ulkeler)
        else:
            kapsam.append(dict(kampanya_kodu=kod))
        m = np.ones(S, bool) if maske is None else maske
        for k in range(k0, k1 + 1):
            yeni = m & (oran > indirim[:, k])
            indirim[yeni, k] = oran
            kod_idx[yeni, k] = len(kayit) - 1

    hafta_no = lambda t: int((pd.Timestamp(t) - bas).days // 7)  # noqa: E731
    online = (mag["kanal"] == "online").to_numpy()
    if sz.tip == "SS":
        ekle("Sezon ortası indirimi", "yuzde_indirim", 0.20, 9, 9)
        rb = OZEL_GUNLER.get(sz.yil, (None,))[0]
        if rb:
            ul = ["TR", "AE", "SA", "QA", "EG", "AZ", "KZ", "UZ"]
            k = hafta_no(pd.Timestamp(rb) - pd.Timedelta(days=3))
            ekle("Bayram indirimi", "yuzde_indirim", 0.20, k, k, mag["ulke"].isin(ul).to_numpy(), ulkeler=ul)
    else:
        ekle("Online özel", "kupon", 0.15, 11, 11, online, kanal="online")
        bf = OZEL_GUNLER.get(sz.yil, (None, None, None, None))[3]
        if bf:
            k = hafta_no(bf)
            ekle("Black Friday / Efsane Cuma", "yuzde_indirim", 0.30, k, k)
    ekle("Sezon sonu 1", "sezon_sonu", 0.30, 20, 22)
    ekle("Sezon sonu 2", "sezon_sonu", 0.40, 23, 25)
    return kayit, kapsam, indirim, kod_idx


def uret(klasor: str | Path, ayar: SentetikAyar | None = None) -> Path:
    ayar = ayar or SentetikAyar()
    klasor = Path(klasor)
    klasor.mkdir(parents=True, exist_ok=True)
    if ayar.gorsel:
        (klasor / "gorseller").mkdir(exist_ok=True)
    rng = np.random.default_rng(ayar.tohum)

    mag = _magaza_df(rng)
    S = len(mag)
    m_bolge = mag["bolge"].to_numpy()
    m_ulke = mag["ulke"].to_numpy()
    m_online = (mag["kanal"] == "online").to_numpy()
    m_acilis = pd.to_datetime(mag["acilis_tarihi"]).to_numpy()
    m_kapanis = pd.to_datetime(mag["kapanis_tarihi"]).to_numpy()
    ulke_listesi = sorted(set(m_ulke))

    out: dict[str, list] = {k: [] for k in (
        "urunler", "skular", "urun_gorselleri", "fiyat_gecmisi", "kampanyalar", "kampanya_kapsami",
        "satin_alma_siparisleri", "iadeler", "stok", "satislar", "gercek")}
    sku_goruldu: set[str] = set()
    gecmis_modeller: dict[str, list[dict]] = {"SS": [], "AW": []}
    sayac = 0

    for sz in _sezonlar(ayar):
        kur = USDTRY[sz.yil] * (1.0 if sz.tip == "SS" else 1.12)
        # ---- modeller
        agirlik = SEZON_KATEGORI_AGIRLIK[sz.tip]
        kat_ad = list(agirlik)
        kat_p = np.array([agirlik[k] for k in kat_ad], float)
        kat_p /= kat_p.sum()
        modeller: list[dict] = []
        adaylar = [m for m in gecmis_modeller[sz.tip] if m["kategori"] in ("tisort", "jean", "pantolon", "gomlek", "kazak") and m["desen"] == "duz"]
        n_devam = min(len(adaylar), int(round(ayar.model_sayisi * ayar.devamli_oran)))
        for m in (rng.choice(adaylar, n_devam, replace=False) if n_devam else []):
            m2 = dict(m)
            m2["stil_etki"] = m["stil_etki"] + rng.normal(0, 0.1)
            m2["devamli"] = True
            m2["maliyet_carpan"] = m["maliyet_carpan"]
            modeller.append(m2)
        for _ in range(ayar.model_sayisi - n_devam):
            sayac += 1
            kat = str(rng.choice(kat_ad, p=kat_p))
            cins = "kadin" if rng.random() < 0.7 else "erkek"
            if cins == "erkek" and kat in ("elbise", "etek"):
                kat = "gomlek"
            renk_sayisi = int(rng.choice([1, 2, 3], p=[0.35, 0.4, 0.25]))
            renk_kodlari = list(rng.choice(list(RENKLER), renk_sayisi, replace=False))
            modeller.append(dict(
                urun_kodu=f"{'K' if cins == 'kadin' else 'E'}{sz.yil % 100}{sz.tip[0]}-{sayac:04d}",
                kategori=kat, cinsiyet=cins,
                kumas=str(rng.choice(KUMASLAR[kat])), kalip=str(rng.choice(KALIPLAR, p=[0.3, 0.45, 0.25])),
                desen=str(rng.choice(DESENLER, p=DESEN_OLASILIK)), yaka=str(rng.choice(YAKALAR[kat])),
                kol_boyu=("kisa" if sz.tip == "SS" and kat in ("tisort", "gomlek", "elbise") and rng.random() < 0.6 else ("yok" if kat in ("etek", "sort", "pantolon", "jean") else "uzun")),
                stil_etki=rng.normal(0, 0.45), maliyet_carpan=float(np.exp(rng.normal(0, 0.2))),
                markup=float(rng.uniform(2.2, 3.4)), renkler=renk_kodlari,
                renk_etki={r: rng.normal(0, 0.2) for r in renk_kodlari}, devamli=False,
                tedarikci=f"TDR-{rng.integers(1, 15):03d}",
            ))
        for m in modeller:
            if not m["devamli"]:
                gecmis_modeller[sz.tip].append(m)
            maliyet_usd = KATEGORILER[m["kategori"]][1] * m["maliyet_carpan"]
            m["maliyet_try"] = round(maliyet_usd * kur, 2)
            m["maliyet_usd"] = maliyet_usd
            out["urunler"].append(dict(
                urun_kodu=m["urun_kodu"], sezon_kodu=sz.kod, urun_adi=f"{m['cinsiyet']} {m['kalip']} {m['kategori']}",
                kategori=m["kategori"], cinsiyet=m["cinsiyet"], koleksiyon="Ana", devamli_urun="evet" if m["devamli"] else "hayir",
                ilk_satis_tarihi=sz.baslangic.date(), birim_maliyet=m["maliyet_try"], maliyet_para_birimi="TRY",
                kumas=m["kumas"], kalip=m["kalip"], desen=m["desen"], yaka=m["yaka"], kol_boyu=m["kol_boyu"],
                tedarikci_kodu=m["tedarikci"], uretim_ulkesi="TR",
            ))

        # ---- model-renk dizileri
        ur = [(m, r) for m in modeller for r in m["renkler"]]
        U = len(ur)
        kat_u = np.array([m["kategori"] for m, _ in ur])
        yil_i = sz.yil - ayar.ilk_yil
        log_a = np.array([
            np.log(KATEGORILER[m["kategori"]][0]) + m["stil_etki"] + m["renk_etki"][r]
            + RENKLER[r][2] + RENKLER[r][3] * yil_i + KALIP_TREND[m["kalip"]] * yil_i + DESEN_ETKI[m["desen"]]
            for m, r in ur])
        fiyat_oran = np.array([m["maliyet_carpan"] * m["markup"] for m, _ in ur])
        goreli = np.empty(U)
        for k in set(kat_u):
            goreli[kat_u == k] = fiyat_oran[kat_u == k] / np.median(fiyat_oran[kat_u == k])
        bolge_etki = np.zeros((U, S))
        for s in range(S):
            b = m_bolge[s]
            for i, (m, r) in enumerate(ur):
                bolge_etki[i, s] = BOLGE_KATEGORI[b].get(m["kategori"], 0) + BOLGE_RENK[b].get(r, 0) + BOLGE_FIYAT_ESNEKLIK[b] * np.log(goreli[i])
        buyume = 1.05 ** yil_i
        ozel = _ozel_gun_carpani(sz, mag)
        prof = PROFIL[sz.tip]
        hafta_basi = np.array([sz.hafta_basi(k).to_datetime64() for k in range(HAFTA)])
        acik = (m_acilis[:, None] <= hafta_basi[None, :]) & (pd.isna(m_kapanis)[:, None] | (m_kapanis[:, None] > hafta_basi[None, :] + np.timedelta64(6, "D")))
        olgunluk = np.where((hafta_basi[None, :] - m_acilis[:, None]) < np.timedelta64(56, "D"), 0.7, 1.0)
        taban = np.exp(log_a[:, None] + bolge_etki) * mag["_carpan"].to_numpy()[None, :] * buyume  # (U,S)
        beklenen_np = taban[:, :, None] * (prof * 1.0)[None, None, :] * ozel[None] * (acik * olgunluk)[None]  # kampanyasız (U,S,K)

        kayit, kapsam, kamp_ind, kamp_idx = _kampanyalar(sz, mag)
        out["kampanyalar"].extend(kayit)
        out["kampanya_kapsami"].extend(kapsam)
        kamp_esn = np.array([BOLGE_KAMPANYA_ESNEKLIK[b] for b in m_bolge])

        # beden payları (ürün x bölge)
        beden = np.zeros((U, S, 5))
        for i in range(U):
            for b in sorted(set(m_bolge)):
                pay = rng.dirichlet(np.array(BOLGE_BEDEN[b]) * 80)
                beden[i, m_bolge == b] = pay
        plan_beden = np.array([BOLGE_BEDEN[b] for b in m_bolge])  # (S,5)

        # ---- alıcı planı, asortiman, ilk sipariş
        sezon_beklenen = beklenen_np.sum(2)  # (U,S)
        hata_u = np.exp(rng.normal(0, 0.5, U))
        plan = sezon_beklenen * hata_u[:, None] * np.exp(rng.normal(0, 0.2, (U, S)))
        plan_sira = plan.sum(1).argsort().argsort() / max(U - 1, 1)
        buyukluk = (mag["_carpan"].to_numpy() - mag["_carpan"].mean()) / mag["_carpan"].std()
        p_dagit = np.clip(0.4 + 0.45 * plan_sira[:, None] + 0.1 * buyukluk[None, :], 0.15, 1.0)
        bolge_kat = np.array([[np.exp(min(0.0, BOLGE_KATEGORI[m_bolge[s]].get(kat_u[i], 0))) for s in range(S)] for i in range(U)])
        dagit = (rng.random((U, S)) < p_dagit * bolge_kat) | m_online[None, :]
        dagit &= acik.any(1)[None, :]
        plan = plan * dagit
        plan_hafta = plan[:, :, None] * (prof / prof.sum())[None, None, :]
        ilk_stok = np.where(dagit[:, :, None], np.maximum(np.round(plan[:, :, None] * 0.4 * plan_beden[None]), 1), 0)
        alim = np.round((plan[:, :, None] * plan_beden[None]).sum(1) * 1.2)
        alim = np.maximum(alim, ilk_stok.sum(1))
        teslim_eksik = np.floor(alim * rng.uniform(0, 0.03, (U, 1)))
        depo = alim - teslim_eksik - ilk_stok.sum(1)
        depo = np.maximum(depo, 0)

        sku = np.empty((U, 5), dtype=object)
        for i, (m, r) in enumerate(ur):
            bed = JEAN_BEDENLER if m["kategori"] == "jean" else BEDENLER
            for z in range(5):
                sku[i, z] = f"{m['urun_kodu']}-{r}-{bed[z]}"
                if sku[i, z] not in sku_goruldu:
                    sku_goruldu.add(sku[i, z])
                    out["skular"].append(dict(sku_kodu=sku[i, z], urun_kodu=m["urun_kodu"], renk_kodu=r, renk_adi=RENKLER[r][0], beden=bed[z], beden_sirasi=z + 1))
            if ayar.gorsel:
                dosya = f"{m['urun_kodu']}-{r}.png"
                if not (klasor / "gorseller" / dosya).exists():
                    _gorsel_ciz(klasor / "gorseller" / dosya, m["kategori"], RENKLER[r][1], m["desen"], rng, ayar.gorsel_boyut)
                    out["urun_gorselleri"].append(dict(urun_kodu=m["urun_kodu"], renk_kodu=r, dosya_adi=dosya, gorsel_turu="flat", ana_gorsel="evet"))
            lead = int(rng.integers(14, 22))
            sip = sz.baslangic - pd.Timedelta(weeks=lead)
            plan_t = sz.baslangic - pd.Timedelta(days=14)
            gercek_t = plan_t + pd.Timedelta(days=int(rng.integers(-5, 12)))
            for z in range(5):
                if alim[i, z] > 0:
                    out["satin_alma_siparisleri"].append(dict(
                        siparis_no=f"PO-{sz.kod}-{i + 1:04d}", sku_kodu=sku[i, z], tedarikci_kodu=m["tedarikci"], siparis_tipi="ilk",
                        siparis_tarihi=sip.date(), planlanan_teslim_tarihi=plan_t.date(), teslim_tarihi=gercek_t.date(),
                        siparis_adedi=int(alim[i, z]), teslim_adedi=int(alim[i, z] - teslim_eksik[i, z]),
                        birim_maliyet=m["maliyet_try"], para_birimi="TRY", depo_kodu="D-MERKEZ"))

        # ---- hafta hafta simülasyon
        stok = ilk_stok.astype(float)
        yolda = np.zeros_like(stok)
        iade_bekleyen = np.zeros((U, S, 5, HAFTA + 4))
        depo_bekleyen = np.zeros((U, 5, HAFTA + 12))
        satis = np.zeros((U, S, 5, HAFTA))
        talep = np.zeros((U, S, HAFTA))
        stok_kayit = np.zeros((U, S, 5, HAFTA))
        depo_kayit = np.zeros((U, 5, HAFTA))
        iade_kayit = np.zeros((U, S, 5, HAFTA + 4))
        kalici_ind = np.zeros(U)
        ind_hafta = np.full(U, -1)
        iade_oran = np.array([KATEGORILER[k][2] for k in kat_u])[:, None] * np.where(m_online, 2.0, 1.0)[None, :]
        iade_oran *= np.array([0.85 if m["kalip"] == "oversize" else 1.0 for m, _ in ur])[:, None]
        tekrar_yapildi = np.zeros(U, bool)

        for k in range(HAFTA):
            stok += yolda + iade_bekleyen[:, :, :, k]
            yolda[:] = 0
            depo += depo_bekleyen[:, :, k]
            fiyat_carpan = (1 - kalici_ind)[:, None] * (1 - kamp_ind[None, :, k])
            lam = beklenen_np[:, :, k] * fiyat_carpan ** (-kamp_esn[None, :]) * dagit
            lam *= rng.gamma(4.0, 0.25, (U, S))
            d = rng.poisson(lam[:, :, None] * beden)
            s_ = np.minimum(d, stok)
            stok -= s_
            satis[:, :, :, k] = s_
            talep[:, :, k] = d.sum(2)
            # iadeler 1-3 hafta sonra aynı lokasyona döner, %85'i tekrar satılabilir
            ia = rng.binomial(s_.astype(int), np.broadcast_to(iade_oran[:, :, None], s_.shape))
            gecikme = rng.integers(1, 4)
            iade_kayit[:, :, :, k + gecikme] += ia
            iade_bekleyen[:, :, :, k + gecikme] += rng.binomial(ia, 0.85)
            stok_kayit[:, :, :, k] = stok
            # tekrar sipariş (6. hafta, satış planın %125'inden hızlıysa)
            if k == 5:
                gecen = satis[:, :, :, : k + 1].sum((1, 2, 3))
                plan_gecen = plan_hafta[:, :, : k + 1].sum((1, 2))
                oran = gecen / np.maximum(plan_gecen, 1)
                kalan_pay = prof[k + 1:].sum() / prof[: k + 1].sum()
                for i in np.where((oran > 1.25) & (plan_gecen > 0))[0]:
                    ihtiyac = gecen[i] * kalan_pay - stok[i].sum() - depo[i].sum()
                    if ihtiyac <= 5:
                        continue
                    lead = int(rng.integers(5, 9))
                    pay = satis[i, :, :, : k + 1].sum((0, 2)) + 1
                    adet = np.round(ihtiyac * 0.8 * pay / pay.sum())
                    depo_bekleyen[i, :, k + lead] += adet
                    tekrar_yapildi[i] = True
                    m, r = ur[i]
                    for z in range(5):
                        if adet[z] > 0:
                            out["satin_alma_siparisleri"].append(dict(
                                siparis_no=f"PO-{sz.kod}-{i + 1:04d}-T", sku_kodu=sku[i, z], tedarikci_kodu=m["tedarikci"], siparis_tipi="tekrar",
                                siparis_tarihi=sz.hafta_basi(k + 1).date(), planlanan_teslim_tarihi=sz.hafta_basi(k + lead - 1).date(),
                                teslim_tarihi=sz.hafta_basi(k + lead).date(), siparis_adedi=int(adet[z]), teslim_adedi=int(adet[z]),
                                birim_maliyet=round(m["maliyet_try"] * 1.08, 2), para_birimi="TRY", depo_kodu="D-MERKEZ"))
            # kalıcı indirim (14. hafta, satış hızı düşükse)
            if k == 13:
                st = satis.sum((1, 2, 3)) / np.maximum(alim.sum(1), 1)
                yavas = (st < 0.35) & (kalici_ind == 0)
                kalici_ind[yavas] = 0.25
                ind_hafta[yavas] = k + 1
            # haftalık ikmal: önümüzdeki 2 haftalık ihtiyaç (plan ya da son satış hızı) + 1
            if k < HAFTA - 1:
                son = satis[:, :, :, max(0, k - 1): k + 1].mean(3)
                planli = plan_hafta[:, :, k + 1: k + 3].sum(2)[:, :, None] * plan_beden[None]
                hedef = np.ceil(np.maximum(planli, 2 * son)) + dagit[:, :, None]
                ihtiyac = np.maximum(hedef - stok, 0) * dagit[:, :, None] * acik[None, :, min(k + 1, HAFTA - 1), None]
                toplam = ihtiyac.sum(1)
                oran = np.where(toplam > depo, depo / np.maximum(toplam, 1), 1.0)
                gonder = np.floor(ihtiyac * oran[:, None, :])
                depo -= gonder.sum(1)
                yolda = gonder
            depo_kayit[:, :, k] = depo

        # ---- kayıtlar
        gun0 = np.datetime64(sz.baslangic.date())
        magaza_kod = mag["magaza_kodu"].to_numpy()
        liste_arr = np.zeros((U, S, HAFTA))
        raf_arr = np.zeros((U, S, HAFTA))
        for i, (m, r) in enumerate(ur):
            for u in ulke_listesi:
                mu = m_ulke == u
                if not dagit[i, mu].any():
                    continue
                para = PARA_BIRIMI.get(u, "USD")
                if para == "TRY":
                    p0 = m["maliyet_try"] * m["markup"]
                elif para == "EUR":
                    p0 = m["maliyet_usd"] / 1.08 * m["markup"] * 1.3
                else:
                    p0 = m["maliyet_usd"] * m["markup"] * 1.25
                kirilim = sorted({0, HAFTA} | ({10} if para == "TRY" else set()) | ({int(ind_hafta[i])} if ind_hafta[i] > 0 else set()))
                for a, b in zip(kirilim[:-1], kirilim[1:]):
                    liste = float(_yuvarla_fiyat(np.array([p0 * (1.12 if para == "TRY" and a >= 10 else 1.0)]), para)[0])
                    raf = float(_yuvarla_fiyat(np.array([liste * (1 - kalici_ind[i])]), para)[0]) if ind_hafta[i] > 0 and a >= ind_hafta[i] else liste
                    liste_arr[i, mu, a:b] = liste
                    raf_arr[i, mu, a:b] = raf
                    out["fiyat_gecmisi"].append(dict(
                        urun_kodu=m["urun_kodu"], renk_kodu=r, kapsam_tipi="ulke", kapsam_kodu=u, para_birimi=para,
                        liste_fiyati=liste, raf_fiyati=raf, baslangic_tarihi=sz.hafta_basi(a).date(),
                        bitis_tarihi=(sz.hafta_basi(b) - pd.Timedelta(days=1)).date() if b < HAFTA else ""))

        # satışlar: hafta -> güne dağıt
        i_, s_, z_, k_ = np.nonzero(satis)
        gunluk = rng.multinomial(satis[i_, s_, z_, k_].astype(int), GUN_AGIRLIK)
        kamp_kod = np.array([x["kampanya_kodu"] for x in kayit] + [""], dtype=object)
        for j in range(7):
            nz = gunluk[:, j] > 0
            i, s, z, k, n = i_[nz], s_[nz], z_[nz], k_[nz], gunluk[nz, j]
            out["satislar"].append(pd.DataFrame(dict(
                tarih=gun0 + (7 * k + j).astype("timedelta64[D]"), magaza_kodu=magaza_kod[s], sku_kodu=sku[i, z], adet=n,
                brut_tutar=np.round(liste_arr[i, s, k] * n, 2), net_tutar=np.round(raf_arr[i, s, k] * (1 - kamp_ind[s, k]) * n, 2),
                kampanya_kodu=kamp_kod[kamp_idx[s, k]])))
        # iadeler (haftanın salı günü)
        i_, s_, z_, k_ = np.nonzero(iade_kayit)
        out["iadeler"].append(pd.DataFrame(dict(
            tarih=gun0 + (7 * k_ + 1).astype("timedelta64[D]"), magaza_kodu=magaza_kod[s_], sku_kodu=sku[i_, z_],
            adet=iade_kayit[i_, s_, z_, k_].astype(int),
            iade_nedeni=rng.choice(["beden", "begenmedim", "kalite", "diger"], len(i_), p=[0.45, 0.3, 0.15, 0.1]))))
        # stok: dağıtılan mağaza-ürünler için haftalık (pazar) anlık görüntü, sıfırlar dahil
        i_, s_ = np.nonzero(dagit)
        I, K, Z = np.meshgrid(i_, np.arange(HAFTA), np.arange(5), indexing="ij")
        Sg = np.broadcast_to(s_[:, None, None], I.shape)
        ac = acik[Sg, K]
        I, K, Z, Sg = I[ac], K[ac], Z[ac], Sg[ac]
        out["stok"].append(pd.DataFrame(dict(
            tarih=gun0 + (7 * K + 6).astype("timedelta64[D]"), lokasyon_kodu=magaza_kod[Sg], sku_kodu=sku[I, Z],
            eldeki_adet=stok_kayit[I, Sg, Z, K].astype(int))))
        I, K, Z = np.meshgrid(np.arange(U), np.arange(HAFTA), np.arange(5), indexing="ij")
        out["stok"].append(pd.DataFrame(dict(
            tarih=gun0 + (7 * K.ravel() + 6).astype("timedelta64[D]"), lokasyon_kodu="D-MERKEZ", sku_kodu=sku[I.ravel(), Z.ravel()],
            eldeki_adet=depo_kayit[I.ravel(), Z.ravel(), K.ravel()].astype(int))))
        # gerçek talep (yalnızca sentetik)
        I, K = np.meshgrid(i_, np.arange(HAFTA), indexing="ij")
        Sg = np.broadcast_to(s_[:, None], I.shape)
        ac = acik[Sg, K]
        I, K, Sg = I[ac], K[ac], Sg[ac]
        out["gercek"].append(pd.DataFrame(dict(
            sezon_kodu=sz.kod, urun_kodu=np.array([m["urun_kodu"] for m, _ in ur])[I], renk_kodu=np.array([r for _, r in ur])[I],
            magaza_kodu=magaza_kod[Sg], hafta_baslangic=gun0 + (7 * K).astype("timedelta64[D]"), gercek_talep=talep[I, Sg, K].astype(int))))

    _yaz(klasor, out, mag, ayar)
    return klasor


def _yaz(klasor: Path, out: dict, mag: pd.DataFrame, ayar: SentetikAyar) -> None:
    def csv(ad, df):
        df.to_csv(klasor / f"{ad}.csv", index=False)

    csv("magazalar", mag.drop(columns=["bolge", "_carpan"]))
    csv("depolar", pd.DataFrame([dict(depo_kodu="D-MERKEZ", depo_adi="Merkez depo", ulke="TR", depo_tipi="merkez")]))
    for ad in ("urunler", "skular", "urun_gorselleri", "fiyat_gecmisi", "kampanyalar", "kampanya_kapsami", "satin_alma_siparisleri"):
        if out[ad] or ad != "urun_gorselleri":
            csv(ad, pd.DataFrame(out[ad]))
    satis = pd.concat(out["satislar"], ignore_index=True).sort_values(["tarih", "magaza_kodu", "sku_kodu"])
    csv("satislar", satis)
    csv("iadeler", pd.concat(out["iadeler"]).groupby(["tarih", "magaza_kodu", "sku_kodu", "iade_nedeni"], as_index=False)["adet"].sum())
    csv("stok", pd.concat(out["stok"], ignore_index=True))
    csv("takvim", _takvim(range(ayar.ilk_yil, ayar.ilk_yil + ayar.yil_sayisi + 1)))
    pd.concat(out["gercek"], ignore_index=True).to_csv(
        klasor / "_sentetik_gercek_talep.csv", index=False)
    (klasor / "SENTETIK_VERI_BENIOKU.md").write_text(
        "# SENTETİK VERİ\n\n"
        "Bu klasördeki veriler `python -m tahmin sentetik` ile üretilmiştir. Gerçek bir markanın verisi değildir;\n"
        "satış, stok ve fiyatlar bir formülden üretilmiştir. Müşteriye gösterilirken mutlaka 'sentetik' olarak belirtilmelidir.\n\n"
        f"Tohum: {ayar.tohum}, yıl: {ayar.ilk_yil}-{ayar.ilk_yil + ayar.yil_sayisi - 1}, sezon başına model: {ayar.model_sayisi}.\n\n"
        "`_sentetik_gercek_talep.csv` stok bitişinden etkilenmemiş gerçek talebi içerir. Gerçek veride böyle bir dosya yoktur;\n"
        "yalnızca stok bitişi düzeltmesinin ve modellerin ne kadar isabetli olduğunu ölçmek için kullanılır, modellere verilmez.\n",
        encoding="utf-8")
