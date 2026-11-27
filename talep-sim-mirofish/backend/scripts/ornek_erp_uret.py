"""SENTETİK örnek ERP CSV'leri üretir (yeni mağaza öngörüsünü gerçek veri gelmeden denemek için).

Çıktı: backend/panel_data/ornek_erp/{magazalar,satislar,doviz_kurlari}.csv
Değerler uydurmadır (sabit tohumlu rastgele); hiçbir gerçek markanın satışı değildir.
Gerçek veri gelince NEWSTORE_ERP_DIR ile kendi klasörünü ver; bu klasör kullanılmaz.

Çalıştırma (backend klasöründe):  python scripts/ornek_erp_uret.py
"""
import csv
import random
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "panel_data" / "ornek_erp"
START, END = date(2024, 1, 1), date(2025, 12, 28)

# kod, ülke, şehir, tip, m², para birimi, açılış, kapanış, m² başı yıllık ciro (USD, varsayım)
STORES = [
    ("ORNEK-IST-01", "TR", "Istanbul", "avm", 520, "TRY", "2021-03-01", "", 2300),
    ("ORNEK-IST-02", "TR", "Istanbul", "cadde", 300, "TRY", "2022-05-01", "", 2600),
    ("ORNEK-IST-03", "TR", "Istanbul", "outlet", 700, "TRY", "2020-09-01", "", 1100),
    ("ORNEK-ANK-01", "TR", "Ankara", "avm", 450, "TRY", "2021-10-01", "", 1800),
    ("ORNEK-IZM-01", "TR", "Izmir", "avm", 400, "TRY", "2022-02-01", "", 1750),
    ("ORNEK-IZM-02", "TR", "Izmir", "cadde", 250, "TRY", "2023-04-01", "", 1900),
    ("ORNEK-ANT-01", "TR", "Antalya", "avm", 380, "TRY", "2022-06-01", "", 2000),
    ("ORNEK-BUR-01", "TR", "Bursa", "avm", 350, "TRY", "2023-01-15", "2025-09-30", 1250),
    ("ORNEK-BER-01", "DE", "Berlin", "cadde", 280, "EUR", "2022-09-01", "", 3600),
    ("ORNEK-AMS-01", "NL", "Amsterdam", "cadde", 220, "EUR", "2023-03-01", "", 4100),
    ("ORNEK-DXB-01", "AE", "Dubai", "avm", 500, "USD", "2021-11-01", "", 3900),
    ("ORNEK-RUH-01", "SA", "Riyadh", "avm", 450, "USD", "2022-10-01", "", 3000),
    ("ORNEK-ALA-01", "KZ", "Almaty", "avm", 360, "USD", "2023-02-01", "", 1600),
    ("ORNEK-BAK-01", "AZ", "Baku", "avm", 320, "USD", "2023-05-01", "", 1400),
]


def usd_try(d: date) -> float:  # yıllık ~%30 artan kur (yaklaşık, varsayım)
    return 29.5 * 1.30 ** ((d - date(2024, 1, 1)).days / 365)


def season(d: date) -> float:  # kasım-aralık ve yaz zirvesi, şubat dibi
    return {1: 0.9, 2: 0.75, 3: 0.9, 4: 0.95, 5: 1.0, 6: 1.1, 7: 1.15, 8: 1.05, 9: 0.95, 10: 1.0, 11: 1.2, 12: 1.3}[d.month]


def main() -> None:
    rnd = random.Random(20261108)
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "magazalar.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["magaza_kodu", "kanal", "ulke", "sehir", "lokasyon_tipi", "metrekare", "acilis_tarihi",
                    "kapanis_tarihi", "para_birimi"])
        for c, u, s, t, m2, cur, op, cl, _ in STORES:
            w.writerow([c, "magaza", u, s, t, m2, op, cl, cur])
        w.writerow(["ORNEK-WEB-TR", "online", "TR", "Istanbul", "online", "", "2020-01-01", "", "TRY"])

    with (OUT / "doviz_kurlari.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["tarih", "para_birimi", "try_karsiligi"])
        d = date(2023, 12, 1)
        while d <= END:
            u = usd_try(d)
            w.writerow([d.isoformat(), "USD", round(u, 2)])
            w.writerow([d.isoformat(), "EUR", round(u * 1.08, 2)])
            d = (d.replace(day=1) + timedelta(days=32)).replace(day=1)

    with (OUT / "satislar.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["tarih", "magaza_kodu", "sku_kodu", "adet", "net_tutar"])
        for c, u, s, t, m2, cur, op, cl, per_sqm in STORES:
            opened, closed = date.fromisoformat(op), date.fromisoformat(cl) if cl else None
            store_noise = rnd.uniform(0.85, 1.15)
            d = max(START, opened)
            while d <= END and (closed is None or d <= closed):
                week_usd = per_sqm * m2 / 52 * season(d) * store_noise * rnd.uniform(0.8, 1.2)
                rate = {"TRY": usd_try(d), "EUR": 1 / 1.08, "USD": 1.0}[cur]
                local = week_usd * rate
                w.writerow([d.isoformat(), c, "ORNEK-SKU", max(1, round(week_usd / 35)), round(local, 2)])
                d += timedelta(days=7)
    print(f"Sentetik örnek ERP verisi yazıldı: {OUT}")


if __name__ == "__main__":
    main()
