# Veri sözleşmesi

Bu doküman, pilot müşterinin ERP'sinden hangi verileri hangi formatta alacağımızı tanımlar.
Alan alan liste: [`veri-sozlesmesi-alanlar.md`](veri-sozlesmesi-alanlar.md). Boş şablonlar: [`../sablonlar/`](../sablonlar/).
Müşteriye gönderilecek kısa liste: [`veri-talep-listesi.md`](veri-talep-listesi.md). KVKK notları: [`kvkk-anonimlestirme.md`](kvkk-anonimlestirme.md).

## Neden bu veriler

Amaç, yeni bir tasarım için sezon başlamadan (üretim siparişi anında) bölge, mağaza kümesi ve hafta
bazında talebi aralığıyla tahmin etmek ve bunun basit yöntemlerden daha iyi olduğunu geçmiş sezonlarla
kanıtlamaktır. Bunun için üç şey gerekir:

1. **Ne sattı:** satış, iade, fiyat ve kampanya geçmişi.
2. **Ne satabilirdi:** stok geçmişi. Stoğu biten mağazada satış sıfırdır ama talep vardı. Stok verisi olmadan
   çok satan ürünlerin talebi sistematik olarak düşük görünür ve model bunu öğrenir.
3. **Neye benziyordu:** ürün özellikleri ve fotoğrafları. Yeni tasarımın hiç satış geçmişi yoktur; tahmin, ona
   benzeyen geçmiş ürünlerin gerçek performansından gelir.

## Tablolar

| Tablo | Durum | Taneciklik | Ne için |
|---|---|---|---|
| `urunler` | zorunlu | model x sezon | Kategori, sezon, maliyet, özellikler |
| `skular` | zorunlu | model x renk x beden | Beden ve renk kırılımı |
| `magazalar` | zorunlu | mağaza (online dahil) | Bölge, küme, açılış/kapanış |
| `satislar` | zorunlu | gün x mağaza x SKU | Gerçekleşme |
| `stok` | zorunlu | gün (ya da hafta) x lokasyon x SKU | Stok bitişi düzeltmesi |
| `fiyat_gecmisi` | zorunlu | model x renk x ülke x geçerlilik aralığı | Göreli fiyat, indirim etkisi |
| `satin_alma_siparisleri` | zorunlu | sipariş satırı | Tedarik süresi, alım kararı kıyası |
| `urun_gorselleri` + `gorseller/` | önerilen | görsel | Görsel benzerlik, özellik çıkarımı |
| `kampanyalar`, `kampanya_kapsami` | önerilen | kampanya | Kampanya etkisini ayırmak |
| `iadeler` | önerilen | gün x mağaza x SKU | İade oranı (kanal ayrı) |
| `depolar` | önerilen | depo | Merkez depo stoğu |
| `sevkiyatlar` | opsiyonel | transfer | Mağaza ikmali analizi |
| `asortiman_plani` | opsiyonel | model x renk x mağaza | Bilerek kaldırılan ürünü stok bitişinden ayırmak |
| `takvim` | opsiyonel | gün x ülke | Ülkeye özel tatil/özel gün |
| `doviz_kurlari` | opsiyonel | gün x para birimi | Ciro raporlaması |

İlişkiler: `skular.urun_kodu → urunler`, `satislar/stok/iadeler.sku_kodu → skular`,
`satislar/iadeler.magaza_kodu → magazalar`, `stok.lokasyon_kodu → magazalar ya da depolar`,
`satislar.kampanya_kodu → kampanyalar`, `fiyat_gecmisi.urun_kodu → urunler`.

## Dosya kuralları

- **Format:** her tablo ayrı bir CSV, UTF-8, ilk satır başlık, ayırıcı virgül, ondalık ayırıcı nokta
  (virgülle gelen ondalıklar da okunur). Büyük tablolar `.csv.gz` olarak sıkıştırılabilir. Kolon adları
  şablondaki gibi; fazladan kolon sorun değildir, yok sayılır.
- **Tarih:** `YYYY-AA-GG` (ISO 8601). Saat gerekmez.
- **Para:** tutarlar KDV dahil, tüketicinin ödediği gibi. Para birimi her satırda ya da mağaza düzeyinde belirtilir.
  Model mutlak fiyat yerine aynı kategori, sezon ve para birimindeki ürünlere göre **göreli fiyat** kullanır;
  böylece kur ve enflasyon karşılaştırmayı bozmaz.
- **Kodlar:** kodlar tablolar arasında birebir aynı yazılmalı (baştaki sıfırlar, boşluklar). Kodların anlamlı olması
  gerekmez; müşteri isterse kodları kendi tarafında takma kodlara çevirebilir (KVKK notlarına bak).
- **Boş değer:** boş hücre. `0`, `-`, `NULL` gibi değerler boş anlamına gelmez.
- **Sıfır satırlar:** stok tablosunda sıfır stoklu satırlar da yazılır. Satış tablosunda sıfır satış satırı gerekmez.
- **Teslim:** tek bir zip (gorseller/ klasörü dahil), şifreli bağlantı ya da SFTP. E-posta eki kullanılmaz.

## Geçmiş uzunluğu

- **En az 3 sezon, tercihen 4-6** (2-3 yıl). Son sezon test için saklanır, ondan önceki sezon tahmin aralıklarını
  ayarlamak için kullanılır, gerisi eğitimdir.
- Devamlı (carry-over) ürünler: aynı `urun_kodu` her sezon `urunler` tablosunda ayrı satırla tekrar edilir.
  Satışlar tarihe göre ilgili sezona atanır.
- Sezon kodu `YYYY-SS` / `YYYY-AW` önerilir. Müşterinin kendi sezon yapısı farklıysa (ör. 4 drop) eşleme yapılır.

## Stok bitişi (sansürlü talep) nasıl ele alınır

1. Her mağaza x SKU x hafta için **stokta bulunma oranı** hesaplanır. Günlük stokta: stoğun sıfır olmadığı günlerin
   oranı. Haftalık stokta: hafta sonu stoğu > 0 ise 1; sıfırsa ve hafta içinde satış ya da hafta başında stok
   varsa 0,5; ikisi de yoksa 0.
2. Bedenler bölge x kategori beden payıyla ağırlıklanır (M bedeni bitince kaybedilen talep XS bitmesinden fazladır).
3. Ürünün stokta olduğu haftalardaki satış hızı, kategorinin haftalık profiliyle stoksuz haftalara taşınır.
   Kısmen stokta olunan haftada satış, stokta bulunma oranına bölünür.
4. Ürünün mağazaya hiç gönderilmediği haftalar (ilk stok girişinden önce) ve mağazanın kapalı olduğu haftalar
   talep sayılmaz.

Sınır: ürün bilerek raftan kaldırıldıysa (asortiman değişikliği) bu yöntem talebi fazla tahmin eder.
`asortiman_plani` tablosu bunu çözer. Sentetik veride bu düzeltme ham satışın gerçek talepten sapmasını
yaklaşık %8'den %2-3'e indiriyor; gerçek veride oran farklı olacaktır.

## Veri kalitesi kontrolleri

`python -m tahmin dogrula <klasör>` şu kontrolleri yapar ve HATA / UYARI / BİLGİ seviyeli rapor üretir:

- Zorunlu tablo ve alanların varlığı, tiplerin okunabilmesi (tarih, sayı), zorunlu alanların doluluğu
- İzinli değerler (kanal, cinsiyet, kampanya mekaniği), negatif adet ve fiyatlar
- Benzersiz anahtar tekrarları, tablolar arası referans bütünlüğü (yetim SKU, mağaza)
- Mağazanın açılış-kapanış aralığı dışındaki satışlar, mağaza-hafta boşlukları (eksik veri şüphesi)
- Net tutarın brüt tutarı aşması, raf fiyatının liste fiyatını aşması
- Stok sıklığı (günlük / haftalık), satışların ne kadarının stok kaydıyla eşleştiği, negatif stok
- Teslim tarihinin sipariş tarihinden önce olması, tedarik süresi dağılımı
- Genel iade oranı, görsel kapsaması ve eksik görsel dosyaları
- Sezon sayısı (2'den az: hata, 3'ten az: uyarı)
