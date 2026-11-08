"""AVM profili: aday mağazanın hangi AVM'de olduğu bilgisini tahmine kontrollü biçimde katar.

Akış:
- Bizim sunucumuzda (internet var) `python -m app.mallprofile cek ...` açık veriden (Overture Maps Places)
  şehir bazında AVM kataloğu üretir: AVM adı, konumu, çevresindeki giyim mağazaları ve markaları. Her katalog
  kaynak, sürüm, lisans ve tarih taşır; bir insan kontrol edip onaylar (`onayla`).
- Müşteri kurulumunda katalog yalnızca okunur (ağa çıkılmaz): AVM arama, AVM kartı, persona ağırlık ayarı.
- AVM bulunamazsa kullanıcı kiracı listesini elle girer; hiçbir şey girilmezse şehir bazlı hesap aynen çalışır.

Her sinyal bir dayanak etiketi taşır: "dış veri", "kural varsayımı", "kullanıcı girdisi" ya da "bilinmiyor".
Ziyaretçi sayısı gibi kaynaklı olmayan bir bilgi tahmin edilmez, boş bırakılır.
"""
