# KVKK ve anonimleştirme kontrol listesi

> Bu liste pratik bir çalışma notudur, hukuki görüş değildir. Pilot başlamadan bir KVKK avukatına
> (ve AB'deki müşteriler için GDPR açısından) kontrol ettirilmelidir.

## İlke: kişisel veri almamak

Talep tahmini için **kişisel veriye ihtiyacımız yok**. Satış, stok, fiyat ve ürün verisi gün x mağaza x SKU
toplamı olarak geldiğinde bir kişiyle ilişkilendirilemez. En güvenli yol, kişisel verinin müşterinin
sisteminden hiç çıkmamasıdır.

| Veri | Durum | Not |
|---|---|---|
| Müşteri adı, TC kimlik, telefon, e-posta, adres | **istenmez** | Export'tan çıkarılmalı |
| Kart no, sadakat kartı no, müşteri id | **istenmez** | Gerekirse ileride, tek yönlü hash ile ve ayrı onayla |
| Fiş / sipariş no | istenmez | Fiş düzeyi gerekirse rastgele takma koda çevrilir |
| Kasiyer, satış danışmanı, personel adı | **istenmez** | |
| Mağaza adresi | alınabilir | İşyeri adresi; kişisel veri değildir |
| Online sipariş teslimat adresi | **istenmez** | Gerekirse yalnızca il / ilçe düzeyinde toplam |
| Ürün fotoğrafı (manken üzerinde, yüz görünür) | dikkat | Yüz bir kişiye aittir (manken/model). Flat ya da hayalet manken tercih edilir; yoksa yüz kırpılır |
| Tedarikçi adı | gerekmez | Kod yeterli; ticari sır olabilir |

## Sözleşmeler (veri gelmeden önce)

- [ ] Karşılıklı gizlilik sözleşmesi (NDA): ticari sırlar (maliyet, marj, tedarikçi) dahil.
- [ ] Veri işleme sözleşmesi: biz "veri işleyen", müşteri "veri sorumlusu". Amaç: yalnızca talep tahmini ve geriye
      dönük test. Başka amaçla kullanım, üçüncü kişiye aktarım ve başka müşterinin modeliyle birleştirme yok.
- [ ] Saklama süresi ve silme: pilot bitişi + X gün; silme yazılı teyit edilir.
- [ ] Yurt dışına aktarım: veri hangi ülkede, hangi bulut sağlayıcıda tutulacak? Yurt dışındaysa KVKK m.9
      kapsamında değerlendirilmeli. Bulut LLM servislerine (ör. ürün görseli analizi için) gönderilecekse ayrıca yazılmalı;
      yerel model (Qwen-VL) kullanımı bu riski azaltır.
- [ ] Alt işleyenler listesi (bulut sağlayıcı, depolama).

## Teknik önlemler

- [ ] Veri şifreli kanalla gelir (SFTP ya da süreli, şifreli bağlantı). E-posta eki yok.
- [ ] Veri şifreli diskte, erişim yalnızca projede çalışan kişilerde, erişim kaydı tutulur.
- [ ] Ham veri git deposuna **asla** girmez (`.gitignore`), raporlarda tekil müşteri ya da personel bilgisi olmaz.
- [ ] Müşteri isterse kodları kendi tarafında takma kodlara çevirir (ör. mağaza `M-IST-014` → `S017`).
      Eşleme tablosu müşteride kalır. Tutarlılık şart: aynı kod her tabloda aynı takma koda dönüşmeli.
- [ ] Gelen veride kişisel veri taraması: kolon adlarında ve örnek değerlerde ad, telefon, e-posta, TC kimlik deseni
      aranır; bulunursa kolon silinir ve müşteriye bildirilir.
- [ ] Küçük hücre riski: çok küçük mağaza x gün x SKU toplamları bir kişiye işaret etmez (müşteri kimliği yok), ama
      raporlarda tek bir işlemin görülebildiği tablolar paylaşılmaz.
- [ ] Pilot bitince ham veri, türetilmiş tablolar ve yedekler silinir; model ağırlıkları da müşteriye özeldir ve silinir.

## Raporlama

- Müşteriye verilen raporlar müşterinin kendi verisidir. Başka bir müşteriye örnek olarak gösterilmez;
  satış sunumlarında yalnızca **sentetik veri** raporu kullanılır ve sentetik olduğu yazılır.
