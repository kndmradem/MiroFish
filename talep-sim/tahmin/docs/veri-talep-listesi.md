# Pilot çalışma için veri talep listesi

Merhaba,

Pilot çalışmanın ilk çıktısı bir **geriye dönük test raporu** olacak: geçmiş sezonlarınızla modeli
eğitip en son sezonu, o sezonun verisini görmeden tahmin edeceğiz. Sonucu, sizin bugün kullandığınız
yönteme ve basit yöntemlere (benzer ürün ortalaması, geçen yıl aynı kategori) göre kıyaslayacağız.
Tahminlerin yanında verdiğimiz "%80 aralık" gibi aralıkların gerçekten o oranda tutup tutmadığını da ölçeceğiz.

Bunun için aşağıdaki verilere ihtiyacımız var. **Son 3 yıl (en az 4-6 sezon)** yeterli.
Her tablonun alan listesi ve boş şablonu ekte. Alan adlarını birebir tutturmanız gerekmiyor;
ERP'nizin çıktısını olduğu gibi gönderirseniz eşlemeyi biz yaparız.

## Olmazsa olmaz

1. **Ürün kartları:** model kodu, sezon, kategori, cinsiyet, birim maliyet. Varsa kumaş, kalıp, desen, yaka, koleksiyon.
2. **SKU listesi:** model, renk, beden kırılımı.
3. **Mağaza listesi:** kod, ülke, şehir, kanal (mağaza / online / outlet / franchise), açılış ve kapanış tarihi.
   Varsa metrekare ve AVM / cadde bilgisi. Online satışlar ülke başına ayrı bir "mağaza" olarak.
4. **Satışlar:** gün x mağaza x SKU bazında adet ve tahsil edilen tutar (fiş düzeyi gerekmez; müşteri bilgisi istemiyoruz).
5. **Stok geçmişi:** gün sonu (yoksa hafta sonu) mağaza ve depo stoğu, SKU bazında, **sıfır stoklu satırlar dahil**.
   En önemli tablo budur: stoğu biten üründe satış durur ama talep devam eder; stok verisi olmadan bunu ayıramayız.
   ERP'niz geçmiş stoğu saklamıyorsa stok hareketlerini (giriş, çıkış, transfer) göndermeniz yeterli, geriye doğru hesaplarız.
6. **Fiyat geçmişi:** etiket fiyatı ve kalıcı indirimli fiyat değişiklikleri, ülke ya da mağaza bazında, geçerlilik tarihleriyle.
7. **Satın alma siparişleri:** sipariş tarihi, planlanan ve gerçekleşen teslim tarihi, sipariş ve teslim adedi (ilk ve tekrar siparişler).

## Çok faydalı

8. **Ürün fotoğrafları:** model-renk başına bir katalog fotoğrafı (düz fon ya da hayalet manken tercih edilir).
9. **Kampanya takvimi:** kampanya adı, mekaniği (yüzde indirim, x al y öde, sepette indirim...), oranı, tarihleri, hangi mağaza ve ürünlerde geçerli olduğu.
10. **İadeler:** gün x mağaza x SKU bazında iade adedi; online ve mağaza ayrı. Varsa iade nedeni.

## Varsa

11. Depodan mağazaya sevkiyatlar, asortiman planı (hangi ürün hangi mağazada satılacaktı), mağaza tadilat / geçici kapanma dönemleri, ülkeye özel kampanya ve tatil takvimi.

## Gizlilik

- Müşteri adı, telefon, e-posta, kart ya da sadakat numarası **istemiyoruz**. Bu alanları çıkarıp gönderin.
- Personel, kasiyer ve tedarikçi isimleri gerekmez; kod yeterli.
- İsterseniz ürün, mağaza ve tedarikçi kodlarını kendi tarafınızda takma kodlara çevirebilirsiniz; tablolar arasında tutarlı olması yeterli.
- Veriyi şifreli bağlantı ya da SFTP ile alıyoruz, e-posta eki kullanmıyoruz. Gizlilik sözleşmesi ve veri işleme sözleşmesi veriden önce imzalanır.
- Çalışma bitince veri sizin talimatınıza göre silinir ve silindiği yazılı olarak bildirilir.

## Takvim

Veri geldikten sonra:
1. Hafta: veri kalitesi raporu (eksikler, tutarsızlıklar) ve sizinle kısa bir kontrol görüşmesi.
2.-3. Hafta: geriye dönük test raporu.

Sorularınız için bana yazabilirsiniz.
