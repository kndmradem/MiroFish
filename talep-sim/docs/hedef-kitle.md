# Hedef kitleye göre panel (kadın / erkek / çocuk / unisex)

Her ürünün bir hedef kitlesi vardır ve panel (ajan topluluğu) buna göre seçilir.

| Kitle | Panel |
|---|---|
| Kadın | Ağırlıklı kadın; erkekler ürünü hayatlarındaki bir kadın için değerlendirir |
| Erkek | Ağırlıklı erkek; kadınlar ürünü eş/baba/kardeş için değerlendirir |
| Çocuk | Ebeveynler (anne/baba), çocuğun yaşı ve (varsa) cinsiyetiyle |
| Unisex | Karışık |

## Hedef kitle nereden gelir

- Tekli ekran: "Hedef kitle" seçimi. Toplu yükleme Excel'i: `hedef_kitle` sütunu (kadın, erkek, çocuk, unisex; kız çocuk, erkek çocuk, bebek de olur).
- Boşsa ürün adı, kategori, içerik ve beden aralığından (ör. "2-3 yaş") tahmin edilir. Sonuçta **tahmin** diye etiketlenir ve gerekçesi yazılır
  (ör. "ürün adı içinde 'elbise' geçiyor"). İpucu yoksa unisex varsayılır, o da "tahmin".
- İpucu kelimeleri veri dosyasıdır: `backend/panel_data/hedef_kitle/anahtar_kelimeler.json`. Marka listesi yoktur.

## Bölge bazında kalibrasyon

`backend/panel_data/hedef_kitle/dagilim.json`: her bölge ve kitle için kadın payı (çocukta anne payı) ve yaş bantları
(çocukta ebeveyn yaşı + çocuk yaş aralığı). EU ve TR ayrı kalibre edilir; diğer bölgeler `_varsayilan` kullanır ve sonuçta
"genel varsayım" yazar. Dosya `verified: false` bir **kural varsayımıdır**; müşterinin ERP/CRM alıcı verisiyle (alıcı cinsiyeti, yaşı)
değiştirilmelidir. Müşteri kendi `PANEL_DATA_DIR` klasörüne `hedef_kitle/dagilim.json` koyarsa o kullanılır.

## Motorlara göre

- **Persona paneli (SIM_ENGINE=panel):** kişiler kota ile seçilir (12 kişide %85 kadın = 10 kadın, 2 erkek). Yaş bantları en büyük
  kalan yöntemiyle dağıtılır; her kişiye segmentinin yaş aralığıyla en çok örtüşen bant verilir. Aynı kitledeki ürünlere aynı kişiler
  bakar (koleksiyon içi karşılaştırma kitle içinde yapılır). Vitrin turu koleksiyonun çoğunluk kitlesiyle koşar.
- **MiroFish (SIM_ENGINE=mirofish / hybrid), varsayılan:** her hedef kitle için **ayrı bir dünya, sıfırdan oluşturulan ajanlarla**
  kurulur; **Zep kullanılmaz**. `services/world_people.py` bölge başına `MIROFISH_AGENTS_PER_REGION` kişi üretir: kadın payı ve yaş
  bantları kitlenin bölge dağılımından (kota), çocukta hepsi ebeveyn (ürün kız/erkek çocuk içinse çocukları o cinsiyetten), şehir/gelir/
  tarz persona kütüphanesinden, adlar `panel_data/hedef_kitle/isimler.json`dan. Kişiler MiroFish'e `POST /api/graph/local` ile verilir;
  MiroFish bunları Zep grafiği yerine proje klasöründen okur, profil üretir (verilen yaş/cinsiyet/ülke/meslek LLM'in tahmininin önüne
  geçer), kısa simülasyonu koşar. Dünyalar (bölgeler, kitle) başına önbelleğe alınır: bir kitle için ilk koşu yerel modelde 10-30 dk,
  sonrakiler hazır dünyayı kullanır. Ağırlık yok (yöntem: kota). "Dünyayı sıfırla" seçili bölgelerin tüm kitle dünyalarını siler.
- **MiroFish eski yol (`MIROFISH_ZEP=1`):** sabit seed dünyası (bölge başına 10 kişi, Zep grafiği). Hepsi sorulur, cevaplar hedef
  cinsiyet/yaş dağılımına göre **ağırlıklandırılır** (talep ve fiyat; tek kişinin ağırlığı ortalamanın en fazla 3 katı; etkili kişi
  sayısı ve ağırlıksız talep gösterilir). Seed kişilerin cinsiyeti `services/personas.py` içinde `SEED_GENDER`.
- Her iki MiroFish yolunda soruya hedef kitle notu eklenir ("Kadınsan kendin için, erkeksen hayatındaki bir kadın için…").
- **Mock motor:** kişi üretmez, hedef dağılım yalnızca gösterilir.

## Sonuç ekranı

"Kime soruldu" kutusu: hedef kitle ve dayanağı (kullanıcı girdisi / tahmin), bölge bölge kaç kadın/erkek/ebeveyn, yaş bantlarında
hedef ve gerçekleşen pay, yöntem (kota / ağırlık), dağılımın dayanağı (kural varsayımı, sürüm, tarih, bölgeye özel mi, doğrulandı mı).
Koleksiyon ekranında her ürünün altında kitle etiketi, başlıkta kitle dağılımı; Excel çıktısında "Hedef kitle (dayanak)" sütunu.
