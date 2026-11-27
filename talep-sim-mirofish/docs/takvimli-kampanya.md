# Takvimli kampanya planı (yeni ürün)

Tekli ürün tahmininde her bölge için perakende takvimine göre kampanya planı üretir: hangi etkinlikte (Black Friday,
Ramazan Bayramı, Sevgililer Günü, sezon sonu...) hangi indirimle kampanya yapılırsa 120 günde değer en yüksek olur.
Tasarım: proje dosyalarında `talep-sim/kampanya-takvimi/kampanya-takvimi-tasarimi.md` (P2 adımı).

## Veri dosyaları (kodda sabit tarih yok)

Klasör `backend/panel_data/takvim/` (ya da `TAKVIM_DIR`):

| Dosya | İçerik |
|---|---|
| `perakende_takvimi.csv` | Etkinlik penceresi (yıl x bölge/ülke): tarih, ön pencere, tür, segment etiketleri, yasal not, kaynak, doğrulandı. Hicri bayramlar elle girilir. **Taslaktaki satırların hepsi doğrulanmadı.** |
| `etkinlik_turleri.csv` | Tür başına ajan sorusu, indirimsiz etki aralığı, indirim yapılırsa ek etki (%30 indirim için), bekleme/erteleme oranları. Hepsi kural varsayımı. |
| `ulke_bolge.csv` | Ülke kodu -> bölge (ör. FR -> EU). |
| `segment_esanlam.csv` | Segment etiketi -> ürün metninde aranacak kelimeler (kural uygunluğu için). |
| `kampanya_kaldiraclari.csv` | Eski `scenarios.CATALOG` (bölge x hedef kampanya kaldıraçları), aynı değerlerle veri dosyasına taşındı. |

Excel ile açılıp düzenlenir; dosya değişince yeniden yüklenir.

## Nasıl hesaplanır

1. **Takvim turu** (`app/takvim/fit.py`): panel kişilerine tek LLM çağrısıyla her etkinlik için 0-3 uygunluk ve
   penceredeki en büyük indirim etkinliği için "hemen al / bekle / almam" sorulur. Karma motorda panel tarafı kullanılır
   (MiroFish'te bu soru yok). Yalnız MiroFish motorunda ajan sorusu yapılmaz, segment eşleşmesi (kural varsayımı) kullanılır.
2. **Plan** (`app/takvim/plan.py`): en fazla N kampanya, iki kampanya arası en az G gün, izinli basamaklar, maliyet
   tabanı kısıtlarıyla bütün planlar denenir; her plan günlük stok simülasyonundan geçer. Değer = iade sonrası kâr +
   kalan stok x maliyet x geri kazanım oranı. Düşük/yüksek senaryo aralığı gösterilir.
3. Önerilen plan fiyat planına çevrilir (sabit 45/45/30 gün yerine takvim tarihleri).
4. Uyarılar: doğrulanmamış takvim satırı, ülkeye özel etkinlik, "indirim öncesi fiyat" (son 30 gün en düşük fiyat)
   kuralı ve ilan edilebilecek indirim (avukat sorusu H4), maliyet tabanını delen basamaklar.

## Ayarlar

- `TAKVIM_TURU=false`: ajan sorusu yapılmaz (ek LLM çağrısı yok), uygunluk kural varsayımıyla.
- `TAKVIM_DOGRULANMIS_ZORUNLU=true`: `dogrulandi=hayir` satırlar plana alınmaz.
- İstekte `assumptions.calendar_plan=false` takvim planını kapatır; koleksiyon modunda kapalıdır.
- Ekrandan: satışa çıkış tarihi, indirim basamakları, en fazla kampanya, kampanya arası gün, kalan stok geri kazanımı.

## Sınırlar

- Etkinlik etkisinin büyüklüğü kalibre edilmedi (kural varsayımı); satış geçmişi olan ürünlerde ERP'den öğrenilecek (P1).
- Ajan fiyat eğrisi yalnızca fiyat kabulünü ölçer; fiyat kabul bölgesindeyse indirimin etkisi yalnızca kural aralığından gelir.
- Rakiplerin aynı etkinlikte indirim yapması, kampanya sonrası düşüş ve koleksiyon içi yamyamlık modellenmedi.
