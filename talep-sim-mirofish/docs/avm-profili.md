# AVM profili (yeni mağaza ekranı)

Yeni mağaza ekranında lokasyon tipi "AVM" seçilince bir AVM kartı açılır. Bu kartta AVM ya katalogdan aranır
ya da elle girilir. Seçilen AVM'nin kiracı markalarından üç şey çıkarılır: fiyat segmenti, rakipler ve panel
segment ağırlıklarının nasıl kayacağı. AVM seçilmezse ya da AVM'nin verisi yoksa tahmin şehir verisiyle aynen
çalışır.

Kod: `backend/app/mallprofile/`. Ekran: `frontend/src/components/mall-card.tsx`.

## Veri

- **AVM kataloğu** `panel_data/malls/<ÜLKE>/<şehir>.json`. Bizim sunucumuzda Overture Maps Places verisinden
  üretilir. Kaynak verinin lisansı CDLA-Permissive-2.0, Apache-2.0 ya da CC0'dır: saklanabilir ve
  dağıtılabilir, atıf gerekir. Hazır taslaklar: İstanbul, Ankara, İzmir, Riyad, Cidde, Dubai, Almatı, Berlin,
  Atina (Overture sürümü 2026-10-21.0).
- **Marka katmanları** `panel_data/marka_katmanlari.csv`. Bu bir kural varsayımıdır: markaların genel bilinen
  fiyat konumunu yazar, ölçülmüş veri değildir. Müşteri kendi pazarına göre düzeltmelidir.

```bash
cd talep-sim/backend
.venv/bin/pip install pyarrow                       # yalnızca katalog üretilecek makinede
.venv/bin/python -m app.mallprofile cek TR Istanbul  # hazır kutu; başka şehir için --bbox xmin,ymin,xmax,ymax
.venv/bin/python -m app.mallprofile onayla panel_data/malls/TR/istanbul.json --onaylayan "Adem"
.venv/bin/python -m app.mallprofile listele
```

Müşteri kurulumunda katalog yalnızca okunur, kurulum ağa çıkmaz. `MALL_DATA_DIR` başka bir klasörü,
`BRAND_TIERS_FILE` başka bir katman dosyasını gösterir.

## Yöntem (kural varsayımları)

- **AVM kaydı:** kategorisi `shopping_mall` ve kayıt güveni 0,6 ya da üstü olan kayıtlar alınır. Adı bilinen bir
  marka olan kayıt (ör. "Tory Burch") AVM değil mağaza sayılır ve atlanır. Aynı AVM'nin birden çok kaydı
  birleştirilir: ya 60 m içindeyse, ya da 250 m içinde ve adlarında ortak özel kelime varsa.
- **Kiracılar:** AVM noktasına 200 m içindeki giyim, ayakkabı ve aksesuar mağazaları. Overture'da AVM sınırı
  yok, bu yüzden çok büyük AVM'lerde bazı mağazalar kaçar, sıkışık çarşılarda ise AVM dışındaki mağazalar da
  sayılır. 150'den fazla mağaza varsa ve bunların %30'undan azı markalıysa kayıt "çarşı bölgesi" olarak
  işaretlenir.
- **Fiyat endeksi:** katmanı bilinen markaların ortalamasıdır (ekonomik 0 … lüks 1). En az 6 bilinen marka
  gerekir; daha azsa segment hesaplanmaz.
- **Panel ağırlığı:** çarpan şöyle hesaplanır: `1 + 4 · (AVM endeksi − şehir AVM ortalaması) · (gelir puanı − 0,5)`.
  Çarpan 0,5 ile 2 arasında sınırlanır. Şehir ortalaması yoksa ya da bilinen marka azsa çarpan 1'dir.
- **Rakipler:** markanın seçilen katmanı ile aynı ya da komşu katmandaki bilinen markalardır.
- **Ziyaretçi sayısı** yalnızca kaynaklı beyandan alınır, yoksa "bilinmiyor" yazılır. **Çevre demografisi**
  henüz bağlanmadı.

Ekrandaki her satır bir dayanak etiketi taşır: dış veri, kural varsayımı, kullanıcı girdisi ya da bilinmiyor.

## Sınırlar ve sonraki adımlar

- AVM kartı şimdilik **ciro tahminini değiştirmez**. AVM özelliklerinin ciro tahminine girmesi için önce
  müşterinin mevcut mağazalarının AVM'leri eşlenmeli. Ardından her mevcut mağaza sırayla "yeni açılıyormuş"
  gibi tahmin edilerek geriye dönük test yapılmalı. AVM bilgisi bu testte hatayı düşürmüyorsa tahmine
  katılmaz.
- Panel çarpanları henüz panel koşusuna (`sample_panel`) bağlı değildir, ekranda önizleme olarak gösterilir.
- Kataloglar taslaktır. Bazı AVM'ler bir mağaza kaydının adıyla görünür (ör. "forum istanbul mavi jeans");
  bazıları hiç yoktur (ör. Capacity). Katalog onaylanmadan önce bir insan ad ve kayıtları kontrol etmelidir.
- OpenStreetMap (Overpass) sağlayıcısı henüz yazılmadı.
