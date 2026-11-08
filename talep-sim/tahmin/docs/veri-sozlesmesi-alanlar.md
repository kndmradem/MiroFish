# Veri sözleşmesi: alan listesi

Bu dosya `tahmin/sozlesme.py` içinden otomatik üretilir (`python -m tahmin sozlesme`). Elle düzenleme.
Genel kurallar ve stok bitişi (sansürlü talep) notları için `veri-sozlesmesi.md`.

## `urunler.csv` (zorunlu)

Model (stil) kartı. Aynı model birden fazla sezonda satılıyorsa her sezon için bir satır.

- Taneciklik: model x sezon
- Benzersiz anahtar: `urun_kodu`, `sezon_kodu`

| Alan | Tip | Zorunlu | Açıklama | Örnek |
|---|---|---|---|---|
| `urun_kodu` | metin | evet | Model kodu (renk ve beden içermez). | KD25A-0412 |
| `sezon_kodu` | metin | evet | YYYY-SS (ilkbahar/yaz) ya da YYYY-AW (sonbahar/kış). | 2025-AW |
| `urun_adi` | metin | hayır | Ürün adı. | Kadın oversize keten gömlek |
| `kategori` | metin | evet | Ana kategori (müşterinin kendi kategori ağacı). | gomlek |
| `alt_kategori` | metin | hayır | Alt kategori. | keten gomlek |
| `cinsiyet` | metin | evet | Hedef cinsiyet. İzinli: `kadin`, `erkek`, `unisex`, `cocuk`. | kadin |
| `koleksiyon` | metin | hayır | Koleksiyon / kapsül adı. | Resort |
| `devamli_urun` | evet/hayır | hayır | Her sezon tekrar eden temel ürün (carry-over) mu? | hayir |
| `ilk_satis_tarihi` | tarih | hayır | Mağazaya ilk çıkış tarihi (planlanan ya da gerçekleşen). | 2025-08-04 |
| `birim_maliyet` | ondalık | evet | Standart birim maliyet (KDV hariç, tedarik + navlun). | 182.50 |
| `maliyet_para_birimi` | metin | evet | ISO 4217 para birimi. | TRY |
| `kumas` | metin | hayır | Ana kumaş. | keten |
| `kumas_karisimi` | metin | hayır | Kompozisyon. | %55 keten %45 pamuk |
| `kalip` | metin | hayır | Kalıp / fit. | oversize |
| `desen` | metin | hayır | Desen. | duz |
| `yaka` | metin | hayır | Yaka tipi. | gomlek_yaka |
| `kol_boyu` | metin | hayır | Kol boyu. | uzun |
| `tedarikci_kodu` | metin | hayır | Tedarikçi kodu (isim gerekmez). | TDR-018 |
| `uretim_ulkesi` | metin | hayır | ISO2 ülke kodu. | TR |

> Özellik alanları (kumaş, kalıp, desen, yaka) ERP'de boşsa sorun değil: görsellerden görsel model ile çıkarılır.
> Kategori isimleri müşteriye özeldir; eşleme tablosu ilk görüşmede birlikte çıkarılır.

## `skular.csv` (zorunlu)

Satılabilir en küçük birim: model x renk x beden.

- Taneciklik: SKU
- Benzersiz anahtar: `sku_kodu`

| Alan | Tip | Zorunlu | Açıklama | Örnek |
|---|---|---|---|---|
| `sku_kodu` | metin | evet | SKU kodu. | KD25A-0412-BEJ-M |
| `urun_kodu` | metin | evet | Model kodu. Bağlantı: `urunler.urun_kodu`. | KD25A-0412 |
| `renk_kodu` | metin | evet | Renk kodu. | BEJ |
| `renk_adi` | metin | hayır | Renk adı. | bej |
| `beden` | metin | evet | Beden etiketi. | M |
| `beden_sirasi` | tamsayı | hayır | Beden sıralaması (XS=1, S=2 ...). | 3 |
| `barkod` | metin | hayır | EAN/UPC barkod. | 8690000000000 |

## `urun_gorselleri.csv` (önerilen)

Ürün fotoğrafları. Dosyalar gorseller/ klasöründe, bu tabloda adlarıyla listelenir.

- Taneciklik: model x renk x görsel
- Benzersiz anahtar: `dosya_adi`

| Alan | Tip | Zorunlu | Açıklama | Örnek |
|---|---|---|---|---|
| `urun_kodu` | metin | evet | Model kodu. Bağlantı: `urunler.urun_kodu`. | KD25A-0412 |
| `renk_kodu` | metin | hayır | Renk kodu (boşsa tüm renkler). | BEJ |
| `dosya_adi` | metin | evet | gorseller/ altındaki göreli dosya yolu (jpg/png/webp). | KD25A-0412-BEJ-on.jpg |
| `gorsel_turu` | metin | hayır | on / arka / detay / manken / flat. | on |
| `ana_gorsel` | evet/hayır | hayır | Ürünün ana (katalog) görseli mi? | evet |

> Tercihen düz fonda ürün fotoğrafı (flat ya da hayalet manken). Manken üzerinde yüzü görünen model fotoğrafları kişisel veri içerir; KVKK notlarına bak.

## `magazalar.csv` (zorunlu)

Satış noktaları. Online kanal da (ülke başına) bir 'mağaza' satırı olarak yazılır.

- Taneciklik: mağaza
- Benzersiz anahtar: `magaza_kodu`

| Alan | Tip | Zorunlu | Açıklama | Örnek |
|---|---|---|---|---|
| `magaza_kodu` | metin | evet | Mağaza kodu. | M-IST-014 |
| `magaza_adi` | metin | hayır | Mağaza adı. | İstinyePark |
| `kanal` | metin | evet | Satış kanalı. İzinli: `magaza`, `online`, `outlet`, `franchise`, `toptan`. | magaza |
| `ulke` | metin | evet | ISO2 ülke kodu. | TR |
| `sehir` | metin | evet | Şehir. | Istanbul |
| `ilce` | metin | hayır | İlçe / semt. | Sariyer |
| `adres` | metin | hayır | Açık adres (işyeri adresi; kişisel veri değildir). | ... |
| `enlem` | ondalık | hayır | Enlem. | 41.110 |
| `boylam` | ondalık | hayır | Boylam. | 29.032 |
| `lokasyon_tipi` | metin | hayır | AVM / cadde / outlet / havalimanı / online. İzinli: `avm`, `cadde`, `outlet`, `havalimani`, `online`, `diger`. | avm |
| `metrekare` | ondalık | hayır | Satış alanı (m2). | 420 |
| `acilis_tarihi` | tarih | evet | Açılış tarihi. | 2019-03-15 |
| `kapanis_tarihi` | tarih | hayır | Kapanış tarihi (açıksa boş). | - |
| `para_birimi` | metin | evet | Mağazanın satış para birimi. | TRY |
| `musteri_bolgesi` | metin | hayır | Müşterinin kendi bölge gruplaması. | Marmara |
| `magaza_sinifi` | metin | hayır | Müşterinin kendi mağaza sınıfı (dağıtım kuralları genellikle buna dayanır). | A |
| `kapasite_adet` | tamsayı | hayır | Satış alanı + mağaza deposunun yaklaşık ürün kapasitesi (adet). | 6000 |
| `iklim_bolgesi` | metin | hayır | Müşterinin iklim / sezon gruplaması (boşsa geçmiş satıştan ve koordinattan türetilir). | soguk |
| `depo_teslim_suresi_gun` | tamsayı | hayır | Merkez depodan sevkin rafa ulaşma süresi (gün). | 3 |
| `sevk_gunleri` | metin | hayır | Sevk alınan günler, virgülle (pzt,sal,car,per,cum,cmt,paz). | pzt,per |

> Yenileme / tadilat / geçici kapanma dönemleri varsa ayrıca liste olarak istenir (satışta boşluk = talep yok sanılmasın).

## `depolar.csv` (önerilen)

Merkez / bölge / e-ticaret depoları.

- Taneciklik: depo
- Benzersiz anahtar: `depo_kodu`

| Alan | Tip | Zorunlu | Açıklama | Örnek |
|---|---|---|---|---|
| `depo_kodu` | metin | evet | Depo kodu. | D-MERKEZ |
| `depo_adi` | metin | hayır | Depo adı. | Merkez depo |
| `ulke` | metin | evet | ISO2 ülke kodu. | TR |
| `depo_tipi` | metin | hayır | merkez / bolge / eticaret. İzinli: `merkez`, `bolge`, `eticaret`. | merkez |

## `fiyat_gecmisi.csv` (zorunlu)

Etiket fiyatı değişiklikleri (kalıcı indirimler dahil). Her fiyat değişikliği bir satır.

- Taneciklik: model x (renk) x kapsam x geçerlilik aralığı
- Benzersiz anahtar: `urun_kodu`, `renk_kodu`, `kapsam_kodu`, `baslangic_tarihi`

| Alan | Tip | Zorunlu | Açıklama | Örnek |
|---|---|---|---|---|
| `urun_kodu` | metin | evet | Model kodu. Bağlantı: `urunler.urun_kodu`. | KD25A-0412 |
| `renk_kodu` | metin | hayır | Renk kodu (boşsa tüm renkler). | - |
| `kapsam_tipi` | metin | evet | Fiyat hangi düzeyde: ulke / kanal / magaza. İzinli: `ulke`, `kanal`, `magaza`. | ulke |
| `kapsam_kodu` | metin | evet | Ülke kodu, kanal adı ya da mağaza kodu. | TR |
| `para_birimi` | metin | evet | ISO 4217. | TRY |
| `liste_fiyati` | ondalık | evet | İlk etiket fiyatı (KDV dahil, tüketicinin gördüğü). | 1299.90 |
| `raf_fiyati` | ondalık | hayır | Kalıcı indirimli etiket fiyatı (yoksa liste fiyatı). | 999.90 |
| `baslangic_tarihi` | tarih | evet | Geçerlilik başlangıcı. | 2025-08-04 |
| `bitis_tarihi` | tarih | hayır | Geçerlilik sonu (hâlâ geçerliyse boş). | - |

> Sepette / kampanyalı indirimler buraya değil kampanyalar tablosuna yazılır; ödenen gerçek tutar satislar.net_tutar'dadır.
> Yüksek enflasyonlu para birimlerinde (TRY) sezon içi fiyat artışları mutlaka bu tabloda olmalı.

## `kampanyalar.csv` (önerilen)

Kampanya takvimi ve mekaniği.

- Taneciklik: kampanya
- Benzersiz anahtar: `kampanya_kodu`

| Alan | Tip | Zorunlu | Açıklama | Örnek |
|---|---|---|---|---|
| `kampanya_kodu` | metin | evet | Kampanya kodu. | K-2025-BF |
| `kampanya_adi` | metin | hayır | Kampanya adı. | Efsane Cuma |
| `mekanik` | metin | evet | Kampanya mekaniği. İzinli: `yuzde_indirim`, `tutar_indirim`, `x_al_y_ode`, `sepette_indirim`, `kupon`, `sezon_sonu`, `diger`. | yuzde_indirim |
| `indirim_orani` | ondalık | hayır | Ortalama indirim oranı 0-1 (x al y öde için eşdeğeri). | 0.30 |
| `baslangic_tarihi` | tarih | evet | Başlangıç. | 2025-11-24 |
| `bitis_tarihi` | tarih | evet | Bitiş (dahil). | 2025-11-30 |
| `kanal` | metin | hayır | Yalnızca bir kanalda geçerliyse kanal adı. İzinli: `magaza`, `online`, `outlet`, `franchise`, `toptan`. | - |
| `aciklama` | metin | hayır | Serbest açıklama. | - |

## `kampanya_kapsami.csv` (önerilen)

Hangi kampanya hangi mağaza ve ürünlerde geçerli. Boş alan = tümü.

- Taneciklik: kampanya x mağaza x ürün
- Benzersiz anahtar: yok (tekrar eden satırlar kontrol edilir)

| Alan | Tip | Zorunlu | Açıklama | Örnek |
|---|---|---|---|---|
| `kampanya_kodu` | metin | evet | Kampanya kodu. Bağlantı: `kampanyalar.kampanya_kodu`. | K-2025-BF |
| `magaza_kodu` | metin | hayır | Mağaza kodu (boşsa tüm mağazalar). | - |
| `ulke` | metin | hayır | Ülke kodu (boşsa tüm ülkeler). | TR |
| `urun_kodu` | metin | hayır | Model kodu (boşsa tüm ürünler). | - |
| `kategori` | metin | hayır | Kategori (boşsa tüm kategoriler). | - |

## `satislar.csv` (zorunlu)

Günlük mağaza x SKU satış toplamları (fiş düzeyi gerekmez). İadeler ayrı tabloda.

- Taneciklik: gün x mağaza x SKU (x kampanya)
- Benzersiz anahtar: `tarih`, `magaza_kodu`, `sku_kodu`, `kampanya_kodu`

| Alan | Tip | Zorunlu | Açıklama | Örnek |
|---|---|---|---|---|
| `tarih` | tarih | evet | Satış günü. | 2025-08-09 |
| `magaza_kodu` | metin | evet | Mağaza kodu. Bağlantı: `magazalar.magaza_kodu`. | M-IST-014 |
| `sku_kodu` | metin | evet | SKU kodu. Bağlantı: `skular.sku_kodu`. | KD25A-0412-BEJ-M |
| `adet` | tamsayı | evet | Satılan adet (iade düşülmeden, brüt). | 3 |
| `brut_tutar` | ondalık | hayır | Etiket fiyatı x adet (KDV dahil). | 3899.70 |
| `net_tutar` | ondalık | evet | Tahsil edilen tutar, tüm indirimler sonrası (KDV dahil). | 3119.76 |
| `kampanya_kodu` | metin | hayır | Satışa uygulanan kampanya (yoksa boş). Bağlantı: `kampanyalar.kampanya_kodu`. | - |

> Haftalık toplam kabul edilir ama günlük tercih edilir (kampanya ve stok bitişi etkisi gün düzeyinde ayrışır).
> Müşteri / kart / sadakat numarası istemiyoruz. Fiş düzeyi veri gerekirse fiş no anonimleştirilir.

## `iadeler.csv` (önerilen)

Günlük mağaza x SKU iade toplamları. Online iadeler online 'mağaza' koduyla.

- Taneciklik: gün x mağaza x SKU
- Benzersiz anahtar: `tarih`, `magaza_kodu`, `sku_kodu`, `iade_nedeni`

| Alan | Tip | Zorunlu | Açıklama | Örnek |
|---|---|---|---|---|
| `tarih` | tarih | evet | İade günü. | 2025-08-20 |
| `magaza_kodu` | metin | evet | İadenin alındığı mağaza. Bağlantı: `magazalar.magaza_kodu`. | M-IST-014 |
| `sku_kodu` | metin | evet | SKU kodu. Bağlantı: `skular.sku_kodu`. | KD25A-0412-BEJ-M |
| `adet` | tamsayı | evet | İade adedi. | 1 |
| `net_tutar` | ondalık | hayır | İade edilen tutar. | 1039.92 |
| `iade_nedeni` | metin | hayır | beden / kalite / begenmedim / diger. | beden |
| `satis_magaza_kodu` | metin | hayır | Ürünün satıldığı mağaza (farklıysa). | - |

## `stok.csv` (zorunlu)

Gün sonu stok anlık görüntüsü; mağazalar ve depolar aynı tabloda.

- Taneciklik: gün x lokasyon x SKU
- Benzersiz anahtar: `tarih`, `lokasyon_kodu`, `sku_kodu`

| Alan | Tip | Zorunlu | Açıklama | Örnek |
|---|---|---|---|---|
| `tarih` | tarih | evet | Stok tarihi (gün sonu). | 2025-08-10 |
| `lokasyon_kodu` | metin | evet | Mağaza ya da depo kodu. | M-IST-014 |
| `sku_kodu` | metin | evet | SKU kodu. Bağlantı: `skular.sku_kodu`. | KD25A-0412-BEJ-M |
| `eldeki_adet` | tamsayı | evet | Satılabilir eldeki adet (negatif olmamalı). | 4 |
| `yoldaki_adet` | tamsayı | hayır | Lokasyona sevk edilmiş, henüz girmemiş adet. | 0 |

> Satış talep değildir: stoğu biten mağazada satış sıfırdır ama talep vardı. Bu tablo olmadan tahminler sistematik düşük çıkar.
> Günlük tercih edilir; haftalık (pazar gün sonu) kabul edilir. Sıfır stoklu satırlar da yazılmalıdır (eksik satır = bilinmiyor sayılır).
> Geçmiş stok çoğu ERP'de saklanmaz; saklanmıyorsa stok hareketlerinden (giriş/çıkış/transfer) geriye doğru hesaplanabilir.

## `satin_alma_siparisleri.csv` (zorunlu)

Tedarikçiye verilen siparişler ve teslimatlar (ilk sipariş ve tekrar siparişler).

- Taneciklik: sipariş satırı (SKU)
- Benzersiz anahtar: `siparis_no`, `sku_kodu`

| Alan | Tip | Zorunlu | Açıklama | Örnek |
|---|---|---|---|---|
| `siparis_no` | metin | evet | Sipariş numarası. | PO-25-1182 |
| `sku_kodu` | metin | evet | SKU kodu. Bağlantı: `skular.sku_kodu`. | KD25A-0412-BEJ-M |
| `tedarikci_kodu` | metin | hayır | Tedarikçi kodu. | TDR-018 |
| `siparis_tipi` | metin | hayır | ilk / tekrar. İzinli: `ilk`, `tekrar`. | ilk |
| `siparis_tarihi` | tarih | evet | Siparişin verildiği gün. | 2025-04-02 |
| `planlanan_teslim_tarihi` | tarih | hayır | Sözleşmedeki teslim günü. | 2025-07-15 |
| `teslim_tarihi` | tarih | hayır | Depoya gerçek giriş günü (teslim edilmediyse boş). | 2025-07-22 |
| `siparis_adedi` | tamsayı | evet | Sipariş adedi. | 240 |
| `teslim_adedi` | tamsayı | hayır | Teslim alınan adet. | 236 |
| `birim_maliyet` | ondalık | hayır | Sipariş birim maliyeti. | 182.50 |
| `para_birimi` | metin | hayır | ISO 4217. | USD |
| `depo_kodu` | metin | hayır | Teslim deposu. | D-MERKEZ |

> Tedarik süresi = teslim_tarihi - siparis_tarihi. 'Ne zaman üretmeli' sorusu bu tarihler olmadan cevaplanamaz.

## `sevkiyatlar.csv` (önerilen)

Depodan mağazaya ve mağazalar arası transferler. Mağaza dağıtımı geriye dönük testi için gerekli.

- Taneciklik: gün x kaynak x hedef x SKU
- Benzersiz anahtar: yok (tekrar eden satırlar kontrol edilir)

| Alan | Tip | Zorunlu | Açıklama | Örnek |
|---|---|---|---|---|
| `tarih` | tarih | evet | Sevk günü. | 2025-08-01 |
| `kaynak_lokasyon` | metin | evet | Çıkış lokasyonu. | D-MERKEZ |
| `hedef_lokasyon` | metin | evet | Varış lokasyonu. | M-IST-014 |
| `sku_kodu` | metin | evet | SKU kodu. Bağlantı: `skular.sku_kodu`. | KD25A-0412-BEJ-M |
| `adet` | tamsayı | evet | Adet. | 12 |

## `asortiman_plani.csv` (opsiyonel)

Hangi ürün hangi mağazada hangi tarihler arasında satılacaktı. Bilerek kaldırılan ürünü stok bitişinden ayırır.

- Taneciklik: model x renk x mağaza
- Benzersiz anahtar: `urun_kodu`, `renk_kodu`, `magaza_kodu`

| Alan | Tip | Zorunlu | Açıklama | Örnek |
|---|---|---|---|---|
| `urun_kodu` | metin | evet | Model kodu. Bağlantı: `urunler.urun_kodu`. | KD25A-0412 |
| `renk_kodu` | metin | evet | Renk kodu. | BEJ |
| `magaza_kodu` | metin | evet | Mağaza kodu. Bağlantı: `magazalar.magaza_kodu`. | M-IST-014 |
| `baslangic_tarihi` | tarih | evet | Satışa başlama. | 2025-08-04 |
| `bitis_tarihi` | tarih | hayır | Plana göre satıştan kalkış. | 2026-01-25 |

## `takvim.csv` (opsiyonel)

Ülkeye özel tatil ve özel günler. Verilmezse genel takvim kullanılır.

- Taneciklik: gün x ülke
- Benzersiz anahtar: `tarih`, `ulke`, `aciklama`

| Alan | Tip | Zorunlu | Açıklama | Örnek |
|---|---|---|---|---|
| `tarih` | tarih | evet | Gün. | 2025-03-30 |
| `ulke` | metin | evet | ISO2 ülke kodu. | TR |
| `gun_tipi` | metin | evet | resmi_tatil / dini_bayram / ozel_gun / okul_tatili. | dini_bayram |
| `aciklama` | metin | hayır | Açıklama. | Ramazan Bayramı 1. gün |

## `eticaret_siparisleri.csv` (opsiyonel)

Online talebin coğrafyası: online satışların teslimat iline ve siparişi karşılayan lokasyona göre toplamı.

- Taneciklik: gün x teslimat ili x karşılayan lokasyon x SKU
- Benzersiz anahtar: `tarih`, `ulke`, `teslimat_ili`, `karsilayan_lokasyon`, `sku_kodu`, `teslim_tipi`

| Alan | Tip | Zorunlu | Açıklama | Örnek |
|---|---|---|---|---|
| `tarih` | tarih | evet | Sipariş günü. | 2025-08-09 |
| `ulke` | metin | evet | Teslimat ülkesi (ISO2). | TR |
| `teslimat_ili` | metin | evet | Teslimat ili / bölgesi. Adres, posta kodu ya da kişi bilgisi istenmez. | Izmir |
| `karsilayan_lokasyon` | metin | evet | Siparişi gönderen depo ya da mağaza kodu. | D-ETICARET |
| `sku_kodu` | metin | evet | SKU kodu. Bağlantı: `skular.sku_kodu`. | KD25A-0412-BEJ-M |
| `teslim_tipi` | metin | hayır | Adrese teslim ya da mağazadan teslim. İzinli: `adrese`, `magazadan`. | adrese |
| `adet` | tamsayı | evet | Sipariş adedi. | 2 |
| `iade_adet` | tamsayı | hayır | Bu siparişlerden sonradan iade edilen adet (biliniyorsa). | 0 |

> KVKK: yalnızca il düzeyinde toplam. Müşteri, adres, telefon ya da sipariş numarası istenmez.
> Mağazadan gönderim ya da mağazadan teslim yapan müşteride mağaza talebi = mağaza satışı + çevresindeki online sipariş.

## `paket_tanimlari.csv` (opsiyonel)

Asorti / seri koliler: depodan mağazaya hangi beden karışımıyla kolilenerek gidiyor.

- Taneciklik: paket x beden
- Benzersiz anahtar: `paket_kodu`, `beden`

| Alan | Tip | Zorunlu | Açıklama | Örnek |
|---|---|---|---|---|
| `paket_kodu` | metin | evet | Paket / seri kodu. | SERI-1221 |
| `urun_kodu` | metin | hayır | Yalnızca bir model için geçerliyse model kodu (boşsa kategoride geçerli). Bağlantı: `urunler.urun_kodu`. | - |
| `kategori` | metin | hayır | Kategoride geçerliyse kategori. | gomlek |
| `beden` | metin | evet | Beden etiketi. | M |
| `adet` | tamsayı | evet | Pakette bu bedenden kaç adet. | 2 |

## `dagitim_kurallari.csv` (opsiyonel)

Müşterinin dağıtım kuralları. Boş bırakılırsa varsayılanlar kullanılır ve raporda 'kural varsayımı' olarak etiketlenir.

- Taneciklik: kural x kapsam
- Benzersiz anahtar: `kural`, `kapsam_tipi`, `kapsam_kodu`

| Alan | Tip | Zorunlu | Açıklama | Örnek |
|---|---|---|---|---|
| `kural` | metin | evet | Kural tipi. İzinli: `sunum_minimumu`, `ilk_dagitim_orani`, `ilk_dagitim_hafta`, `maks_kapsama_hafta`, `ikmal_kapsama_hafta`, `transfer_yok`, `dagitim_disi`. | sunum_minimumu |
| `kapsam_tipi` | metin | evet | Kuralın geçerli olduğu düzey. İzinli: `genel`, `magaza`, `magaza_sinifi`, `kategori`, `urun`. | magaza_sinifi |
| `kapsam_kodu` | metin | hayır | Mağaza kodu, sınıf, kategori ya da model kodu (genel ise boş). | C |
| `deger` | ondalık | hayır | Kuralın sayısal değeri (adet, oran ya da hafta). | 1 |
| `aciklama` | metin | hayır | Serbest açıklama. | C sınıfı mağazalara her bedenden en az 1 |

## `ticari_hedefler.csv` (opsiyonel)

Stok eritme önerileri için hedefler: marj tabanı, stok bitirme tarihi, sezon sonu kalan değer.

- Taneciklik: sezon x kapsam (kategori ya da model)
- Benzersiz anahtar: `sezon_kodu`, `kapsam_tipi`, `kapsam_kodu`

| Alan | Tip | Zorunlu | Açıklama | Örnek |
|---|---|---|---|---|
| `sezon_kodu` | metin | evet | Sezon. | 2025-AW |
| `kapsam_tipi` | metin | evet | Hedefin düzeyi. İzinli: `genel`, `kategori`, `urun`. | kategori |
| `kapsam_kodu` | metin | hayır | Kategori ya da model kodu (genel ise boş). | mont |
| `hedef_brut_marj` | ondalık | hayır | İndirimli satışta korunacak en düşük brüt marj, 0-1 (KDV hariç net fiyata göre). | 0.35 |
| `hedef_bitis_tarihi` | tarih | hayır | Stoğun bitirilmesi hedeflenen tarih. | 2026-01-31 |
| `taban_fiyat` | ondalık | hayır | Altına inilmeyecek satış fiyatı (KDV dahil). | 1499.90 |
| `kalan_deger_orani` | ondalık | hayır | Hedef tarihte kalan stoğun maliyete göre geri kazanımı, 0-1 (outlet, stok satışı). | 0.50 |
| `indirim_basamaklari` | metin | hayır | Markanın kullandığı indirim oranları, virgülle. | 0.2,0.3,0.4,0.5 |

## `doviz_kurlari.csv` (opsiyonel)

Ciro raporlaması için günlük ya da aylık kur. Tahmin modeli kur kullanmaz (göreli fiyatla çalışır).

- Taneciklik: gün x para birimi
- Benzersiz anahtar: `tarih`, `para_birimi`

| Alan | Tip | Zorunlu | Açıklama | Örnek |
|---|---|---|---|---|
| `tarih` | tarih | evet | Gün (aylık ise ayın ilk günü). | 2025-08-01 |
| `para_birimi` | metin | evet | ISO 4217. | EUR |
| `try_karsiligi` | ondalık | evet | 1 birimin TRY karşılığı. | 47.20 |
