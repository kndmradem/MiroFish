# tahmin: ERP verisiyle talep tahmini ve geriye dönük test

Müşterinin ERP verisinden (ürün, SKU, mağaza, satış, stok, fiyat, kampanya, iade, satın alma, görsel)
yeni bir tasarımın sezon talebini **karar anında** (sezon başından ~16 hafta önce) model-renk x mağaza
kümesi x hafta düzeyinde, **aralıklarıyla** tahmin eder ve bunun basit yöntemlerden iyi olup olmadığını
geçmiş sezonlarla ölçer. talep-sim'deki ajan simülasyonundan bağımsızdır; ajan skoru istenirse ek sinyal
olarak eklenebilir (aşağıda).

## Çalıştırma

```bash
cd talep-sim/tahmin
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

.venv/bin/python -m tahmin sentetik veri-sentetik/           # SENTETİK veri (6 sezon, ~5 sn)
.venv/bin/python -m tahmin dogrula veri-sentetik/            # veri kalitesi raporu
.venv/bin/python -m tahmin geriye-test veri-sentetik/ --cikti rapor/ --test-sezonu 2025-SS --test-sezonu 2025-AW
.venv/bin/python -m tahmin benzer veri-sentetik/ --kategori gomlek --renk YSL --kalip oversize --sezon-tipi SS --gorsel tasarim.png
.venv/bin/python -m pytest -q                                # testler (~30 sn)
```

Gerçek müşteri verisi için klasöre şablondaki adlarla CSV'leri (ve `gorseller/`) koyup aynı komutları çalıştır.
`rapor/geriye_donuk_test_raporu.md` pilot müşteriye verilecek ilk çıktının taslağıdır; yanında tüm tahminler
(`tahminler_*.csv`, q05-q95 kantilleriyle), `metrikler.csv`, `benzer_urunler.csv`, `beden_egrisi.csv`,
`uretim_adedi_kiyasi.csv` ve `veri_kalitesi.md` yazılır.

## Dokümanlar

| Dosya | İçerik |
|---|---|
| [`docs/veri-sozlesmesi.md`](docs/veri-sozlesmesi.md) | Tablolar, dosya kuralları, stok bitişi yöntemi, kalite kontrolleri |
| [`docs/veri-sozlesmesi-alanlar.md`](docs/veri-sozlesmesi-alanlar.md) | Alan alan liste (koddan üretilir) |
| [`docs/veri-talep-listesi.md`](docs/veri-talep-listesi.md) | Pilot müşteriye gönderilecek kısa liste |
| [`docs/kvkk-anonimlestirme.md`](docs/kvkk-anonimlestirme.md) | KVKK / anonimleştirme kontrol listesi (hukuki görüş değildir) |
| [`sablonlar/`](sablonlar/) | Her tablo için başlık + örnek satırlı CSV |

## Yapı

| Modül | Görev |
|---|---|
| `sozlesme.py` | Tek doğruluk kaynağı: tablolar, alanlar, tipler, anahtarlar. Pydantic satır modelleri, doküman ve şablon üretimi |
| `yukleme.py`, `dogrulama.py` | CSV klasörünü tiplerle yükleme; HATA/UYARI/BİLGİ seviyeli kalite raporu |
| `sentetik.py` | Sentetik zincir: 21 mağaza, 5 bölge, mevsimsellik, bayram/Black Friday, kampanyalar, alıcı hatası, ikmal, tekrar sipariş, kalıcı indirim, iade, TRY enflasyonu, ürün görselleri. Gerçek talep `_sentetik_gercek_talep.csv`'de (yalnızca ölçüm için) |
| `hazirlik.py` | Sezon pencereleri, satış/stoğun sezon haftasına eşlenmesi, stokta bulunma oranı, stok bitişi düzeltmesi, mağaza kümeleri |
| `gorsel.py` | Değiştirilebilir görsel gömücü: `renk_doku` (model indirmez), `clip` (open_clip kuruluysa), `yok` |
| `benzerlik.py` | Özellik + göreli fiyat + görsel ile en benzer geçmiş ürünler (kNN) |
| `modeller.py` | Kıyas yöntemleri (kategori ortalaması, geçen yıl kategori, mevsimsel naif), benzer ürün kNN, özellik modeli (gradyan artırmalı ağaç, Poisson); haftalara dağıtım |
| `belirsizlik.py` | Doğrulama sezonundan öğrenilen konformal aralıklar (q05-q95) |
| `geriye_test.py`, `metrikler.py`, `rapor.py` | Test akışı, WAPE / sapma / kapsama, beden eğrisi, gazeteci (newsvendor) üretim adedi kıyası, Türkçe rapor |
| `yeni_tasarim.py` | Henüz satılmamış tasarım için benzer ürünler ve bölge başına mağaza başı talep |

## Önemli tasarım kararları

- **Karar anı kuralı:** test sezonu, başlangıcından `--karar-oncesi-hafta` (16) önce tamamen bitmiş sezonlarla tahmin edilir.
  Böylece test, gerçekte sipariş verilirken elde olan bilgiyle yapılır.
- **Aralıklar:** her yöntem önce bir doğrulama sezonunu (aynı kuralla) tahmin eder; oradaki hata dağılımı tahmin
  büyüklüğüne göre kovalanıp test sezonuna uygulanır. Raporda %50/%80/%90 kapsama ayrıca ölçülür.
- **Göreli fiyat:** fiyat, aynı kategori-sezon-para birimindeki medyana oranlanır; kur ve enflasyon karşılaştırmayı bozmaz.
- **Dağıtım planı:** ürünün kümede kaç mağazaya gideceği karar anında bilinen girdi sayılır; tahmin mağaza başı talep x mağaza sayısıdır.
- **Ajan simülasyonu (opsiyonel sinyal):** `urunler` tablosuna `sinyal_` ile başlayan kolon (ör. `sinyal_ajan_skoru`)
  eklenirse özellik modeli onu girdi olarak kullanır. Geriye dönük testte anlamlı olması için skorun geçmiş ürünler için de
  üretilmiş olması gerekir.

## Sınırlar

- Sentetik veride talebi biz ürettiğimiz için modeller gerçekte olacağından iyi görünebilir; görselin katkısı sentetikte ölçülemez.
- Sezon geneli seviye kaymaları geçmişten öğrenilemez; sentetik testte tüm yöntemler toplamı %15-22 düşük tahmin etti.
  Gerçek veride, karar anında devam eden sezonun geçen yıla göre trendi (like-for-like) bir sonraki iyileştirme adayıdır.
- Kampanya takvimi karar anında bilinmiyor kabul edildi; promosyon planı girdisi sonraki adımdır.
- ERP bağlantısı (connector) yok; veri CSV olarak gelir.
