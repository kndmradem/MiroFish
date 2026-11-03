# Koleksiyon modu (toplu ürün değerlendirme)

Arayüzün üstünde üç sekme var: **Tekli ürün** (eski ekran, değişmedi), **Koleksiyon (çoklu)** ve **Yeni mağaza**.
Koleksiyon modunda bütün ürünler Excel + görsellerle yüklenir, her bölgede **aynı panel kişileri bütün ürünlere bakar**,
ürün bazlı ve koleksiyon bazlı sonuç çıkar.

## Akış

1. **Yükle:** ürün listesi (.xlsx ya da .csv) + görseller (dosyalar, klasör ya da zip). Şablon:
   `GET /api/collections/template.xlsx` (ekranda "Örnek Excel şablonu").
2. **Kontrol et:** önizleme ekranı. Onaysız hiçbir şey kaydedilmez. Eşleşmeyen satır, sahipsiz görsel, eksik maliyet,
   tekrarlı SKU burada görünür ve düzeltilir (görsel seç, sahipsiz görseli ürüne bağla, satırı dahil etme).
3. **Çalıştır:** koşu sunucuda arka planda sürer; sayfa kapansa da devam eder. Her ürünün sonucu diske yazılır;
   durdurulur ya da API yeniden başlarsa tekrar başlatınca biten ürünler atlanır.
4. **Sonuç:** Özet (erişim, roller, öneriler, erişim eğrisi, kanibalizasyon, kategoriler), Ürünler, Bölgeler (ısı
   haritası), Fiyat (panel kabul aralığı ve planlanan fiyat), Bütçe (ürün × bölge adet). Ürün çıkarma, fiyat ve bütçe
   değişikliği LLM çağırmadan anında yeniden hesaplanır. Excel olarak indirilebilir. Bir ürün "Tekli ürün ekranında
   ayrıntı" bağlantısıyla tekli ekranın bütün grafikleriyle açılır.

## Görsel eşleştirme

Sırasıyla: (1) Excel'deki `gorsel_dosyalari` sütunu, (2) dosya adı SKU ile başlıyor (`SW27-014.jpg`,
`SW27-014_2.jpg`, `SW27-014-arka.jpg`), (3) SKU adlı klasör (`SW27-014/on.jpg`). Büyük/küçük harf, uzantı ve
Türkçe karakter önemsiz. Bir SKU başka SKU'nun başıysa en uzun eşleşme kazanır. HEIC desteklenmez (JPG/PNG/WEBP).
Excel başlıkları esnek okunur (`SKU`, `Model Kodu`, `Ürün Kodu` aynı alan).

Zorunlu: SKU, ürün adı, görsel. Önerilen: kategori ve birim maliyet (maliyetsiz ürün değerlendirilir ama bütçeye
girmez). Koleksiyon bilgisi (ad, sezon, bütçe, para birimi TRY/USD, bölgeler, kanal) ayrı "Koleksiyon" sayfasından
ya da ekrandan.

## Sayıların dayanağı

| Gösterge | Dayanak |
|---|---|
| Talep skoru, koleksiyon içi sıra ve aralığı, hevesli oranı, erişim, kabul edilebilir fiyat aralığı | ajan |
| Kanibalizasyon çiftleri | ajan (hevesli kişi örtüşmesi) + kural varsayımı (eşikler) |
| Roller (hero / çekirdek / destek / riskli), önerilen adet, beklenen satış | kural varsayımı |
| Planlanan fiyat, hedef rol, maliyet | kullanıcı girdisi |

- **Kişi içi normalizasyon:** her kişinin puanı kendi ortalamasına göre ölçeklenir; "her şeye 60 veren" kişi ile
  "her şeye 40 veren" kişi aynı ölçeğe gelir.
- **Sıra aralığı:** panel kişileri 200 kez yeniden örneklenir; aralık sıranın %80 olasılıkla düştüğü bant.
- **Hevesli:** ilgi puanı 70+. **Erişim:** en az bir ürüne hevesli kişilerin oranı; erişim eğrisi en çok yeni kişi
  getiren ürünü sırayla ekler (TURF).
- Panel ürünleri ayırt etmezse (puanlar neredeyse aynı) rol verilmez ve uyarı çıkar.
- Fiyat sorunu koleksiyonun çoğundaysa tek bir ürün sırf fiyat yüzünden "riskli" sayılmaz; genel fiyat seviyesi uyarısı
  çıkar.
- Sahte LLM (`app.panel.mock_llm`) yalnızca akışı sınar, sayıları anlamsızdır.

## Kurulum notu

Yeni bağımlılıklar: `openpyxl`, `python-multipart` (`requirements.txt`). Koleksiyonlar `backend/collections_data/`
altında saklanır (`COLLECTIONS_DIR` ile değiştirilebilir, git'e girmez).

## Marka

Marka tekli ekrandaki gibi ekranda girilir: ad, notlar, "Profil çıkar", sonra segment, fiyat çarpanı, fiyat
duyarlılığı, çekim gücü ve bölge bilinirliği elle düzeltilebilir. Ekrandaki profil Excel'deki marka alanından önce
gelir. Marka yoksa nötr varsayılan (× 2.7) kullanılır. Marka değişirse ürünler yeniden sorulur (girdi özeti markayı da
içerir). Özet sekmesindeki "Marka etkisi" kartı fiyat seviyesine etkiyi (çarpan ÷ 2.7 − 1) ve her bölgede talep
puanına etkisini dayanak etiketleriyle gösterir. Hiçbir marka adı kodda sabit değildir.

## Vitrin turu (panel motoru)

Tek tek değerlendirmeden sonra aynı kişiler ürünleri gruplar halinde bir arada görür (varsayılan en fazla 8 ürün;
7B model için daha büyüğü önerilmez). Koleksiyon tek gruba sığıyorsa sıra kişiden kişiye döndürülür; sığmıyorsa
her kişi için ürünler iki kez karıştırılıp eşit gruplara bölünür. Ürünler A, B, C harfleriyle verilir, SKU prompta
girmez. Sorular: en çok almak istediği (en fazla 3), kesinlikle almayacağı (en fazla 2), birlikte alacağı çiftler,
birbirinin yerine geçen çiftler, kaç parça alacağı, tek cümle yorum. Cevaplar `showcase/<bölge>.jsonl` dosyasına
yazılır; koşu kesilirse kalan gruplar sorulur.

Sonuç "Vitrin" sekmesinde: vitrin sırası (en çok seçilen − almam denen), kombin ve ikame çiftleri, tek tek sıralama ile
uyum (sıra korelasyonu), **sıra etkisi kontrolü** (seçimlerin listede ilk/orta/son konuma dağılımı beklenene göre;
beklenenin 1.5 katını aşarsa ve en az 20 seçim varsa uyarı). Kombin ve vitrinde belirgin güçlü/zayıf ürünler öneri
olarak Özet'e de düşer. Ek süre: kişi başı grup sayısı × bölge kadar ek LLM sorusu.

## Henüz yok (sonraki adım)

ERP'den beden/renk kırılımı, vitrin sonucunun bütçe dağılımına katılması. Tasarım: proje dosyalarında
`talep-sim/koleksiyon/koleksiyon-degerlendirme-tasarimi.md`.
