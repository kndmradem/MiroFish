# Güncel personalar: veriler nereden gelir, nasıl güncel kalır

## Kısa cevap

MiroFish personaları kendisi uydurmuyordu. Ona bizim yazdığımız 50 kişilik bir tanıtım metnini veriyorduk, o da bunu dil modeline genişletiyordu. Yani MiroFish'te de personaların kaynağı model hafızası ve bizim taslağımızdı. Yeni yapıda persona ve bağlam doğrudan veriden kurulur. Dil modeli yalnızca "bu kişi bu bağlamda bu ürüne ne der" sorusunu canlandırır. Kimin var olduğuna ve dünyanın bugün nasıl olduğuna veri karar verir.

Üç katman var:

1. **Persona segmentleri:** müşteride kimler var, hangi oranda, nasıl alışveriş yapıyorlar. Ana kaynak müşterinin kendi ERP'si (Nebim).
2. **Bağlam paketi:** bu ay ekonomi, sezon, trend ve rakip fiyatı nasıl. Kaynağı resmi istatistik, hava verisi, trend ve rakip takibi.
3. **Doğrulama:** tahminler gerçek satışla karşılaştırılır. Sapma çıkarsa güncelleme tetiklenir, yeni persona sürümü ancak ölçülerek daha iyi çıkarsa devreye girer.

## 1. Persona segmentleri: müşterinin kendi verisinden

En değerli ve en güncel kaynak, müşterinin gerçek müşterileridir. Model hafızası ya da genel pazar bilgisi bunun yerini tutmaz.

| Persona alanı | Nebim / ERP'den nasıl çıkar | Sıklık | Otomatik mi |
|---|---|---|---|
| Segmentler ve ağırlıkları | Sadakat kartlı müşteriler şehir, yaş bandı, cinsiyet, kanal ve sepet tutarına göre gruplanır. Her grubun ciro payı ağırlık olur | 3 ayda bir | Otomatik (betik), insan onayı |
| Şehir / bölge | Mağaza ve e-ticaret teslimat adresi | 3 ayda bir | Otomatik |
| Fiyat duyarlılığı | İndirimli alınan ürün payı, ortalama indirim oranı, raf fiyatından alma oranı | 3 ayda bir | Otomatik |
| Trend ilgisi | Yeni sezon ürünlerinin ilk 2-3 haftada alınma payı, yeni kalıp/renk denemesi | 3 ayda bir | Otomatik |
| Kanal alışkanlıkları | Mağaza / online / pazaryeri payı, taksit kullanımı | 3 ayda bir | Otomatik |
| Tarz eğilimi | Kategori, kalıp (oversize, slim), kumaş ve renk karması | 3 ayda bir | Otomatik, etiketleri insan yazar |
| İade davranışı | Segment bazında iade oranı ve nedenleri | 3 ayda bir | Otomatik |
| Yaş, gelir bandı | Sadakat kartı yaşı; gelir doğrudan yok, sepet tutarı ve mağaza konumundan tahmin edilir | 3 ayda bir | Yarı otomatik (tahmin olduğu işaretlenir) |
| İklim, giyim normları | Bölgenin iklim normalleri ve yerel bilgi | Yılda bir | Elle |

Kişisel veri (KVKK/GDPR): betik müşteri bazında değil, en az birkaç yüz kişilik grup özetleri üretir. Persona dosyasına isim ya da kişi bilgisi girmez. Ayrıntılar ERP thread'indeki anonimleştirme dokümanında.

Müşterinin hiç satmadığı bir bölge (ör. yeni açılacak MENA) için ERP'de veri olmaz. Orada başlangıç personası pazar araştırmasından ya da benzer bölgeden kurulur, "doğrulanmamış" işaretli kalır ve güven seviyesi düşük gösterilir.

## 2. Bağlam paketi: dünyanın bu ayki hâli

| Bilgi | Önerilen kaynak | Sıklık | Otomatik mi |
|---|---|---|---|
| Enflasyon | TR: TÜİK TÜFE. EU: Eurostat HICP. US: BLS CPI. MENA/CIS: ülke istatistik kurumları, IMF | Aylık | Otomatik çekilebilir |
| Kur | TR: TCMB kurları. Diğerleri: merkez bankaları | Günlük / aylık | Otomatik çekilebilir |
| Tüketici güveni | TR: TÜİK-TCMB tüketici güven endeksi. EU: Avrupa Komisyonu anketi. US: Michigan / Conference Board | Aylık | Otomatik çekilebilir |
| Sezon ve hava | İklim normalleri ve mevsimlik tahmin (ör. Open-Meteo, ulusal meteoroloji) | Aylık | Otomatik çekilebilir |
| Alışveriş takvimi | Black Friday / Efsane Cuma, Ramazan, bayramlar, okul dönemi | Yılda bir | Elle (takvim tablosu) |
| Trendler, en güvenilir hâli | Müşterinin kendi satışında hızla büyüyen renk, kalıp ve kumaşlar (ERP'den, geçen yılın aynı dönemine göre) | Aylık | Otomatik |
| Trendler, dış kaynak | Google Trends kategori aramaları, pazaryeri çok satanları, sektör yayınları (ör. ücretli WGSN, Business of Fashion), sosyal medya | Aylık | Yarı otomatik, insan özetler |
| Rakip fiyatları | Rakip sitelerinden benzer ürün fiyatları, mağaza gezisi | Aylık | Elle ya da izinli otomatik takip |

Kural: her not kaynağı ve tarihiyle girer, insan kontrol edince `verified: true` yapılır. Dil modeli bir kaynağı özetleyebilir ama kaynaksız trend notu yazmaz.

## 3. Güncel kalma döngüsü

1. **Her ay:** makro, kur ve hava verisi otomatik çekilir, trend ve rakip notları eklenir. Biri kontrol eder ve yeni tarihli bağlam paketi oluşur. 45 günü geçen paket arayüzde uyarı verir.
2. **Her 3 ayda:** ERP özetlerinden persona segmentleri yeniden hesaplanır ve yeni sürüm (v2, v3...) olarak kaydedilir. Eski sürüm silinmez.
3. **Yeni sürüm testi:** geçmiş ürünler eski ve yeni personayla yeniden tahmin edilip gerçek satışla karşılaştırılır. Yeni sürüm yalnızca belirgin daha isabetliyse aktif olur (bu adım kodda hazır: `python -m app.panel geriye-test`).
4. **Sürekli:** her ürünün gerçek 120 günlük satışı geldikçe kaydedilir. Bir bölgede hata büyümeye başlarsa ya da tahminler hep aynı yöne kayıyorsa sapma uyarısı çıkar ve o bölgenin güncellemesi 3 ayı beklemeden yapılır.
5. **Yılda bir ya da büyük bir değişimde** (yeni bölge, kriz, kur şoku): küçük bir gerçek müşteri anketiyle personalar ayrıca sağlama yapılır.

## Şu an ne hazır, ne değil

- **Hazır (kodda):** persona ve bağlam dosya biçimi, sürüm ve tarih alanları, eskime uyarıları, kalibrasyon, sapma izleme, sürüm karşılaştırma ve ERP CSV'lerinden geçmiş ürün okuma.
- **Henüz yok:** ERP özetinden persona segmentlerini otomatik üreten betik ve makro/kur/hava verisini otomatik çeken betik. İkisi de yapılabilir, sıradaki iş olarak öneriyorum.
- **Doğrulamadığım kaynaklar:** Yukarıdaki dış kaynakların bugünkü erişim yollarını, API koşullarını ve lisanslarını bu çalışmada kontrol etmedim; liste bilinen resmi ve yaygın kaynaklara dayanıyor. Google Trends'in resmi ve kararlı bir API'si yok. WGSN gibi sektör kaynakları ücretli. Rakip sitelerinden otomatik fiyat toplamak sitenin kullanım koşullarına takılabilir, hukuken kontrol edilmeli. MENA ve CIS'te resmi istatistiklerin sıklığı ve güvenilirliği ülkeden ülkeye değişir.
