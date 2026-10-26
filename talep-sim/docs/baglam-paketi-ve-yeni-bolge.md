# Bağlam paketi hazırlama akışı ve yeni bölgede mağaza öngörüsü (tasarım)

## 1. Bağlam paketi hazırlama akışı

### Amaç

Panel motorunun yerel modeli yalnızca **onaylı** bağlam paketini görür. Paketi hazırlarken bulut modelin
web araması işi hızlandırır, ama her bilgi kaynak linki ve tarihiyle gelir, bir insan onaylar ve paket
imzalanıp müşteri kurulumlarına dağıtılır. Müşteri verisi bu akışta hiçbir aşamada buluta gitmez.

### Akış

```
 BİZİM SUNUCUMUZ (internet var)                               MÜŞTERİ SUNUCUSU (kapalı ağ olabilir)
 ───────────────────────────────                              ─────────────────────────────────────
 1. taslak  : bölge + tarih + genel kategori listesi
              -> bulut model (web aramalı) -> taslak paket
              (kaynaksız bilgi otomatik atılır, rapor edilir)
 2. inceleme: insan her bilgiyi linkinden kontrol eder,
              düzeltir/siler
 3. onay    : onaylayan + tarih yazılır, verified=true;
              kaynaksız tek bilgi kalırsa onay reddedilir
 4. paketle : onaylı paketler + manifest (sha256)            5. içe aktar: imza ve özetler doğrulanır,
              Ed25519 ile imzalanır -> .tar.gz  ─────────────>   onaysız ya da bozuk paket reddedilir,
                                                                 context/<BÖLGE>/ altına yazılır
                                                              6. yerel model: PANEL_REQUIRE_VERIFIED=true
                                                                 iken yalnızca onaylı paketleri görür
```

### Müşteri verisinin buluta gitmemesi nasıl sağlanır

- Taslak üretici kodu yalnızca şu girdileri kabul eder: bölge kodu, tarih, genel kategori adları
  (ör. "kadın dış giyim"). Ürün adı, maliyet, satış ya da müşteri bilgisi alan bir parametresi yoktur.
- Taslak üretici müşteri kurulumunda hiç çalışmaz. Müşteri tarafında yalnızca "içe aktar" komutu vardır
  ve bu komut ağa çıkmaz.
- Bulut model sağlayıcısının API anahtarı yalnızca bizim sunucumuzda bulunur.

### Paket biçimi (her bilgi kaynaklı)

Mevcut bağlam paketi şemasına şu alanlar eklenir:

- `sources`: her bilgi için `{url, title, published_at, retrieved_at}`
- makro alanlar için `macro_sources`: alan adı → kaynak
- `approved_by`, `approved_at`: onaylayan kişi ve tarih

### Doğrulayamadığım koşullar

- Bulut modellerin web araması özelliği sağlayıcıya göre farklı çalışır (Gemini'de "grounding with Google
  Search", OpenAI'da web arama aracı). Kod, sağlayıcıya bağlı olmayan bir arayüz kullanır. Hangi modelin,
  hangi fiyatla ve hangi kullanım koşuluyla arama yaptığını bu çalışmada doğrulamadım. Sahte sunucuyla test
  edildi.
- Bulut model link uydurabilir. Bu yüzden onay adımında linkin açılıp kontrol edilmesi zorunlu. Kod linkin
  biçimini kontrol eder, içeriğini kontrol etmez.
- Kaynak sitelerin (TÜİK, Eurostat vb.) içeriğinin pakete alıntılanıp müşterilere dağıtılmasının kullanım
  koşulları kontrol edilmeli. Resmi istatistikler genelde kaynak gösterilerek kullanılabilir, ama ücretli
  kaynaklar (WGSN vb.) dağıtılamaz.

## 2. Yeni bölgede mağaza öngörüsü

### Amaç

Müşteri, mağazası olmayan bir şehre (ör. ilk kez Riyad) mağaza açmayı düşünüyor. Sistem o şehrin dış
verisini, müşterinin benzer profildeki mevcut mağazalarıyla eşleştirir. Ekranda bir tahmin aralığı
gösterilir; belirsizlik ve "bu bölgede kendi veri yok" uyarısı açıkça yazılır.

### Veri

- **Lokasyon profili** (`lokasyon_profilleri.csv`, ülke + şehir bazında): nüfus, kişi başı gelir (USD),
  alım gücü endeksi, yıllık turist sayısı, AVM yıllık ziyaretçi sayısı. Her satırda `kaynak_url` ve `tarih`
  bulunur. Hem mevcut mağaza şehirleri hem aday şehir için doldurulur. Bağlam paketi gibi bizim sunucumuzda
  hazırlanıp onaylanabilir.
- **Mağaza satışları:** ERP veri sözleşmesindeki `magazalar.csv` (ülke, şehir, lokasyon tipi, metrekare,
  açılış tarihi) ve `satislar.csv`. Mağaza başına olgun dönem (açılıştan 6 ay sonrası) yıllık ciro ve
  m² başı ciro (USD) hesaplanır.

### Yöntem

1. Özellikler: log(nüfus), kişi başı gelir, alım gücü, log(turist), log(AVM ziyaretçisi), lokasyon tipi
   (AVM, cadde, outlet). Mevcut mağazalar üzerinden standartlaştırılır.
2. Aday ile her mevcut mağaza arasında ağırlıklı uzaklık hesaplanır. Eksik özellik karşılaştırmaya girmez,
   uyarı olarak yazılır. Aynı lokasyon tipine öncelik verilir.
3. En yakın k analog (varsayılan 5) seçilir. Tahmin, analogların m² başı cirosunun benzerlikle ağırlıklı
   medyanı × aday metrekaresidir.
4. Aralık, analogların ağırlıklı %10-%90 dilimleridir. Ayrıca genişletilir: aday, mevcut mağazaların
   özellik aralığının dışındaysa (dışa değerleme), analog sayısı azsa ya da en yakın analog bile uzaksa.
5. Uyarılar:
   - "Bu bölgede kendi veri yok": aday ülkede ya da bölgede müşterinin hiç mağazası yoksa.
   - Özellik aralığın dışında: ör. "turist sayısı mevcut mağazaların en yükseğinin 3 katı".
   - Eksik ya da kaynaksız dış veri.
   - Analog sayısı az.
6. Güven: düşük, orta ya da yüksek. Kendi bölge verisi yoksa en fazla "düşük-orta" gösterilir.

### Sınırlar

Bu yöntem bir benzerlik tahminidir, nedensel bir model değildir. Rakip yoğunluğu, mağazanın kesin konumu,
kira ve marka bilinirliği gibi etkenleri bilmez. Az mağazalı bir müşteride (10'dan az) aralık geniştir ve
geniş gösterilmelidir. İlk pilotta tahmin, açılan mağazanın gerçek ilk yılıyla karşılaştırılmalı.

### Dış veri kaynakları (doğrulanmadı)

Nüfus ve gelir: ulusal istatistik kurumları, Dünya Bankası, OECD. Turizm: ulusal turizm bakanlıkları,
UNWTO. AVM ziyaretçi sayısı: genelde AVM yönetimlerinin ya da sektör derneklerinin (TR'de AYD) yayınları,
ya da ücretli konum verisi sağlayıcıları. Şehir bazında ve güncel AVM trafiği kamuya açık olarak çoğu zaman
yoktur. Bu kaynakların erişimini ve kullanım koşullarını bu çalışmada kontrol etmedim.
