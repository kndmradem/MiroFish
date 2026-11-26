# Mantık denetimi

Her koleksiyon ve tekli koşunun sonunda (ve her "ne olur" denemesinde) sonuç, marka/ürün listesi içermeyen genel
kurallarla denetlenir. Bulgular sonuç ekranının üstünde **Denetim uyarıları** kutusunda, Excel raporunda **Denetim**
sayfasında ve `/api/denetim/koleksiyon/<id>?bicim=html` raporunda görünür.

| Seviye | Anlamı |
|---|---|
| hata | Sonuç kendi içinde imkânsız ya da yanlış. Ekranda kırmızı **İNCELENMELİ** damgası çıkar; müşteriye gösterilmeden incelenmeli. |
| uyarı | Sonuç tutarlı, ama bir sayı az veriye dayanıyor ya da kurulumdan türemiş. Sunarken açıklanmalı. |
| bilgi | Bağlam notu (ör. bütçenin bir kısmı kullanılmadı). |

## Kurallar

`python -m app.denetim kurallar` güncel listeyi verir. Eşikler `app/denetim/kurallar.py` başında, kural varsayımıdır.

| Kod | Yakaladığı |
|---|---|
| `kategori_disi_eslesme` | Farklı kategorideki ürünlerin "aynı müşteriyi paylaşıyor"/kanibalizasyon çifti (hata); vitrinde farklı kategori "ikisinden biri" cevabı (uyarı). Kategori yazım farkı (büyük/küçük harf, Türkçe karakter, boşluk) aynı sayılır. |
| `kucuk_orneklem` | Yüzdenin paydası 10 kişiden az (uyarı), 3 kişiden az (hata), kişi sayısı yazmayan yüzde (uyarı), panel bölge başına 10 kişiden az. |
| `fiyat_maliyet` | Önerilen fiyat < maliyet, "üret" kararında negatif net marj, ters kabul aralığı, aralık dışı fiyat, sırasız fiyat bölgeleri, fiyat maliyetin 15 katından fazla. |
| `toplam_tutarlilik` | Bölge adetleri ≠ ürün adedi, ürün toplamı ≠ koleksiyon toplamı, bütçe aşımı, adet × maliyet ≠ kullanılan bütçe, "üretme" kararına adet, beklenen satış > üretim, renk adetleri/payları. Tekli: bölge toplamı ≠ genel, satış eğrisi azalıyor ya da üretimi aşıyor. |
| `siralama` | Sıra ile koleksiyon içi puan çelişiyor (hata); aynı kategoride daha pahalı ve daha az ilgi gören ürüne daha çok adet; daha çok ilgi gören ve daha ucuz ürüne daha az talep; gerekçesiz "üretme/azalt"; hero ama "üretme". |
| `panel_ayirt_etmedi` | Talep puanları neredeyse aynı; mevcut güven kontrolü (fiyat maliyetten, adet kitle varsayımından türemiş) burada uyarı olarak görünür (kod yeniden yazılmadı). |
| `eksik_sonuc` | Hiç ürün değerlendirilmedi, ürünlerin %30'undan fazlası hesaplanamadı (hata), bölge eksik (uyarı). |
| `bos_uc_deger` | NaN/sonsuz, negatif adet/fiyat/maliyet, 0-100 dışında yüzde ya da talep puanı, boş ana metrik, %60 üstü iade. |
| `etiketsiz_sayi` | Dayanağı (ajan / kural varsayımı / LLM tahmini / ERP / kullanıcı girdisi) yazılmamış metrik, öneri ya da gerekçe. |
| `veri_urun` | Müşteri ürün listesi: tekrarlayan SKU, boş/sıfır maliyet, boş kategori, aynı kategorinin farklı yazımları, kategorisine göre 5 kat uç maliyet. |

## Bilinen hatalar: regresyon vakaları

`tests/denetim_vakalari/*.json`. Her vaka iki şeyi kilitler:

1. Kayıtlı hatalı çıktıda denetim beklenen bulguyu **vermeli** (denetim hatayı yakalamayı unutmasın).
2. Aynı koşunun girdisi bugünkü kodla yeniden hesaplanınca hata **çıkmamalı** (düzelen hata geri gelmesin).

İlk vaka `bralet-slip-farkli-kategori`: Suwen koşusunun anonimleştirilmiş hali. Eski kodla girdi kısmı kırılır, bugünkü
kodla geçer.

Yeni hata bulununca (Mac, backend klasörü):

```bash
python -m app.denetim vaka-ekle --koleksiyon <id> --ad kisa-ad --aciklama "ne yanlıştı"
python -m app.denetim vakalar
```

Komut ürün/marka adlarını, SKU'ları ve ajan metinlerini anonimleştirir. Denetim hatayı zaten yakalıyorsa vaka
kendiliğinden geçer. Yakalamıyorsa komut bunu söyler ve test, kural yazılana kadar başarısız olur. Kod düzelince vakada
`"durum": "acik"` → `"kapali"`.

## Müşteri verisiyle ilk test

```bash
python -m app.denetim ilk-test --excel urunler.xlsx [--gorseller klasor|zip] [--erp ERP_klasoru] [--motor mock] --cikti rapor/
```

Ürün listesi kuralları + ERP veri kalitesi (tahmin paketindeki mevcut kontroller) + birkaç ürünlük örnek koşu, tek
rapor. Excel yoksa ERP `urunler` tablosunun son sezonu kullanılır. Kurulum sihirbazı aynı şeyi `/api/denetim/ilk-test`
ile "Mantık denetimi" adımında çalıştırır; sunucuda `sudo talepsim denetim`. Çıkış kodu hata varsa 1.

## Denetimin yetmediği yerler: insan gözü gerekir

Denetim sonucun **kendi içinde tutarlı** olup olmadığını ölçer, **doğru** olup olmadığını ölçmez.

1. **Ajanların ham cevapları.** Persona cevabının ürüne gerçekten baktığı mı, şablon cümle mi tekrarlandığı
   ("Fiyat, kalite ve trendi değerlendirerek…"), kişinin kendi persona bilgisiyle çeliştiği mi (öğrenci ama lüks fiyatı
   "uygun" bulması) kurallarla yakalanamaz. Her koşuda bir bölgeden 5-6 ham cevap okunmalı.
2. **Görsel-ürün eşleşmesi ve görselden çıkan ürün kartı.** Yanlış görsel yanlış ürüne bağlandıysa ya da görsel model
   kumaşı/kesimi yanlış okuduysa sonuç tutarlı ama yanlış olur. Önizleme ekranında görseller tek tek bakılmalı.
3. **Kategorinin kendisi yanlışsa.** Denetim ERP kategorisine güvenir. Bralet "KULOT" girildiyse kategori kuralı
   çalışmaz. Kategori listesi kurulumda müşteriyle bir kez gözden geçirilmeli.
4. **Kategoriler arası gerçek ilişkiler.** Aynı kategori içinde de ikame olmayan ürünler (push-up ile spor sütyeni)
   ya da farklı kategoride gerçekten tamamlayıcı olanlar (takım) kuralla ayrılamaz.
5. **Mutlak büyüklükler.** Fiyat ve adetlerin piyasa gerçeğine uygunluğu (ör. 609 adet makul mü) ancak ERP satışı ya
   da rakip fiyatıyla karşılaştırılarak bilinir; denetim yalnızca "maliyetten türemiş" desenini yakalar.
6. **Metinlerin anlamı.** Öneri ve gerekçe cümlelerinin müşteriye doğru tonu, yanlış anlaşılabilecek ifadeler
   ("aynı müşteriyi paylaşıyor" gibi) dil olarak denetlenmez.
7. **Bağlam paketlerinin güncelliği.** Trend/sezon bilgisinin eskimesi sürüm etiketiyle görünür, ama içeriğin doğruluğu
   okunarak kontrol edilmeli.

Önerilen düzen: kurulumda ve her müşteri koşusundan önce denetim "temiz" ya da "uyarılı" olmalı; buna ek olarak ilk
iki koşuda yukarıdaki 1-3 numaralı kontroller için 15 dakikalık bir göz kontrolü yapılmalı. Göz kontrolünde bulunan her
hata `vaka-ekle` ile vakaya dönüştürülür; gerekirse yeni kural yazılır.
