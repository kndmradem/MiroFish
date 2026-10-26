"""Veri sözleşmesi: müşteri ERP'sinden beklenen tablolar ve alanlar.

Tek doğruluk kaynağı burasıdır. Doküman tablosu (docs/veri-sozlesmesi-alanlar.md),
CSV şablonları (sablonlar/), Pydantic satır modelleri ve veri kalitesi kontrolleri
bu tanımlardan üretilir; bir alan eklenecekse yalnızca burası değişir.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, create_model


class Tip(str, Enum):
    METIN = "metin"
    TAMSAYI = "tamsayı"
    ONDALIK = "ondalık"
    TARIH = "tarih"
    EVET_HAYIR = "evet/hayır"


class Zorunluluk(str, Enum):
    ZORUNLU = "zorunlu"
    ONERILEN = "önerilen"
    OPSIYONEL = "opsiyonel"


@dataclass(frozen=True)
class Alan:
    ad: str
    tip: Tip
    zorunlu: bool
    aciklama: str
    ornek: str = ""
    izinli: tuple[str, ...] = ()
    min_deger: Optional[float] = None
    referans: Optional[str] = None  # "tablo.alan" yabancı anahtar
    kisisel_veri: bool = False


@dataclass(frozen=True)
class Tablo:
    ad: str
    zorunluluk: Zorunluluk
    aciklama: str
    taneciklik: str
    anahtar: tuple[str, ...]
    alanlar: tuple[Alan, ...]
    notlar: tuple[str, ...] = field(default=())

    def alan(self, ad: str) -> Alan:
        for a in self.alanlar:
            if a.ad == ad:
                return a
        raise KeyError(f"{self.ad}.{ad}")

    @property
    def zorunlu_alanlar(self) -> list[str]:
        return [a.ad for a in self.alanlar if a.zorunlu]

    @property
    def dosya_adi(self) -> str:
        return f"{self.ad}.csv"


SEZON_ORNEK = "2025-AW"
KANALLAR = ("magaza", "online", "outlet", "franchise", "toptan")
LOKASYON_TIPLERI = ("avm", "cadde", "outlet", "havalimani", "online", "diger")
CINSIYETLER = ("kadin", "erkek", "unisex", "cocuk")
MEKANIKLER = ("yuzde_indirim", "tutar_indirim", "x_al_y_ode", "sepette_indirim", "kupon", "sezon_sonu", "diger")


TABLOLAR: tuple[Tablo, ...] = (
    Tablo(
        ad="urunler",
        zorunluluk=Zorunluluk.ZORUNLU,
        aciklama="Model (stil) kartı. Aynı model birden fazla sezonda satılıyorsa her sezon için bir satır.",
        taneciklik="model x sezon",
        anahtar=("urun_kodu", "sezon_kodu"),
        alanlar=(
            Alan("urun_kodu", Tip.METIN, True, "Model kodu (renk ve beden içermez).", "KD25A-0412"),
            Alan("sezon_kodu", Tip.METIN, True, "YYYY-SS (ilkbahar/yaz) ya da YYYY-AW (sonbahar/kış).", SEZON_ORNEK),
            Alan("urun_adi", Tip.METIN, False, "Ürün adı.", "Kadın oversize keten gömlek"),
            Alan("kategori", Tip.METIN, True, "Ana kategori (müşterinin kendi kategori ağacı).", "gomlek"),
            Alan("alt_kategori", Tip.METIN, False, "Alt kategori.", "keten gomlek"),
            Alan("cinsiyet", Tip.METIN, True, "Hedef cinsiyet.", "kadin", izinli=CINSIYETLER),
            Alan("koleksiyon", Tip.METIN, False, "Koleksiyon / kapsül adı.", "Resort"),
            Alan("devamli_urun", Tip.EVET_HAYIR, False, "Her sezon tekrar eden temel ürün (carry-over) mu?", "hayir"),
            Alan("ilk_satis_tarihi", Tip.TARIH, False, "Mağazaya ilk çıkış tarihi (planlanan ya da gerçekleşen).", "2025-08-04"),
            Alan("birim_maliyet", Tip.ONDALIK, True, "Standart birim maliyet (KDV hariç, tedarik + navlun).", "182.50", min_deger=0),
            Alan("maliyet_para_birimi", Tip.METIN, True, "ISO 4217 para birimi.", "TRY"),
            Alan("kumas", Tip.METIN, False, "Ana kumaş.", "keten"),
            Alan("kumas_karisimi", Tip.METIN, False, "Kompozisyon.", "%55 keten %45 pamuk"),
            Alan("kalip", Tip.METIN, False, "Kalıp / fit.", "oversize"),
            Alan("desen", Tip.METIN, False, "Desen.", "duz"),
            Alan("yaka", Tip.METIN, False, "Yaka tipi.", "gomlek_yaka"),
            Alan("kol_boyu", Tip.METIN, False, "Kol boyu.", "uzun"),
            Alan("tedarikci_kodu", Tip.METIN, False, "Tedarikçi kodu (isim gerekmez).", "TDR-018"),
            Alan("uretim_ulkesi", Tip.METIN, False, "ISO2 ülke kodu.", "TR"),
        ),
        notlar=(
            "Özellik alanları (kumaş, kalıp, desen, yaka) ERP'de boşsa sorun değil: görsellerden görsel model ile çıkarılır.",
            "Kategori isimleri müşteriye özeldir; eşleme tablosu ilk görüşmede birlikte çıkarılır.",
        ),
    ),
    Tablo(
        ad="skular",
        zorunluluk=Zorunluluk.ZORUNLU,
        aciklama="Satılabilir en küçük birim: model x renk x beden.",
        taneciklik="SKU",
        anahtar=("sku_kodu",),
        alanlar=(
            Alan("sku_kodu", Tip.METIN, True, "SKU kodu.", "KD25A-0412-BEJ-M"),
            Alan("urun_kodu", Tip.METIN, True, "Model kodu.", "KD25A-0412", referans="urunler.urun_kodu"),
            Alan("renk_kodu", Tip.METIN, True, "Renk kodu.", "BEJ"),
            Alan("renk_adi", Tip.METIN, False, "Renk adı.", "bej"),
            Alan("beden", Tip.METIN, True, "Beden etiketi.", "M"),
            Alan("beden_sirasi", Tip.TAMSAYI, False, "Beden sıralaması (XS=1, S=2 ...).", "3", min_deger=0),
            Alan("barkod", Tip.METIN, False, "EAN/UPC barkod.", "8690000000000"),
        ),
    ),
    Tablo(
        ad="urun_gorselleri",
        zorunluluk=Zorunluluk.ONERILEN,
        aciklama="Ürün fotoğrafları. Dosyalar gorseller/ klasöründe, bu tabloda adlarıyla listelenir.",
        taneciklik="model x renk x görsel",
        anahtar=("dosya_adi",),
        alanlar=(
            Alan("urun_kodu", Tip.METIN, True, "Model kodu.", "KD25A-0412", referans="urunler.urun_kodu"),
            Alan("renk_kodu", Tip.METIN, False, "Renk kodu (boşsa tüm renkler).", "BEJ"),
            Alan("dosya_adi", Tip.METIN, True, "gorseller/ altındaki göreli dosya yolu (jpg/png/webp).", "KD25A-0412-BEJ-on.jpg"),
            Alan("gorsel_turu", Tip.METIN, False, "on / arka / detay / manken / flat.", "on"),
            Alan("ana_gorsel", Tip.EVET_HAYIR, False, "Ürünün ana (katalog) görseli mi?", "evet"),
        ),
        notlar=(
            "Tercihen düz fonda ürün fotoğrafı (flat ya da hayalet manken). Manken üzerinde yüzü görünen model fotoğrafları kişisel veri içerir; KVKK notlarına bak.",
        ),
    ),
    Tablo(
        ad="magazalar",
        zorunluluk=Zorunluluk.ZORUNLU,
        aciklama="Satış noktaları. Online kanal da (ülke başına) bir 'mağaza' satırı olarak yazılır.",
        taneciklik="mağaza",
        anahtar=("magaza_kodu",),
        alanlar=(
            Alan("magaza_kodu", Tip.METIN, True, "Mağaza kodu.", "M-IST-014"),
            Alan("magaza_adi", Tip.METIN, False, "Mağaza adı.", "İstinyePark"),
            Alan("kanal", Tip.METIN, True, "Satış kanalı.", "magaza", izinli=KANALLAR),
            Alan("ulke", Tip.METIN, True, "ISO2 ülke kodu.", "TR"),
            Alan("sehir", Tip.METIN, True, "Şehir.", "Istanbul"),
            Alan("ilce", Tip.METIN, False, "İlçe / semt.", "Sariyer"),
            Alan("adres", Tip.METIN, False, "Açık adres (işyeri adresi; kişisel veri değildir).", "..."),
            Alan("enlem", Tip.ONDALIK, False, "Enlem.", "41.110"),
            Alan("boylam", Tip.ONDALIK, False, "Boylam.", "29.032"),
            Alan("lokasyon_tipi", Tip.METIN, False, "AVM / cadde / outlet / havalimanı / online.", "avm", izinli=LOKASYON_TIPLERI),
            Alan("metrekare", Tip.ONDALIK, False, "Satış alanı (m2).", "420", min_deger=0),
            Alan("acilis_tarihi", Tip.TARIH, True, "Açılış tarihi.", "2019-03-15"),
            Alan("kapanis_tarihi", Tip.TARIH, False, "Kapanış tarihi (açıksa boş).", ""),
            Alan("para_birimi", Tip.METIN, True, "Mağazanın satış para birimi.", "TRY"),
            Alan("musteri_bolgesi", Tip.METIN, False, "Müşterinin kendi bölge gruplaması.", "Marmara"),
        ),
        notlar=(
            "Yenileme / tadilat / geçici kapanma dönemleri varsa ayrıca liste olarak istenir (satışta boşluk = talep yok sanılmasın).",
        ),
    ),
    Tablo(
        ad="depolar",
        zorunluluk=Zorunluluk.ONERILEN,
        aciklama="Merkez / bölge / e-ticaret depoları.",
        taneciklik="depo",
        anahtar=("depo_kodu",),
        alanlar=(
            Alan("depo_kodu", Tip.METIN, True, "Depo kodu.", "D-MERKEZ"),
            Alan("depo_adi", Tip.METIN, False, "Depo adı.", "Merkez depo"),
            Alan("ulke", Tip.METIN, True, "ISO2 ülke kodu.", "TR"),
            Alan("depo_tipi", Tip.METIN, False, "merkez / bolge / eticaret.", "merkez", izinli=("merkez", "bolge", "eticaret")),
        ),
    ),
    Tablo(
        ad="fiyat_gecmisi",
        zorunluluk=Zorunluluk.ZORUNLU,
        aciklama="Etiket fiyatı değişiklikleri (kalıcı indirimler dahil). Her fiyat değişikliği bir satır.",
        taneciklik="model x (renk) x kapsam x geçerlilik aralığı",
        anahtar=("urun_kodu", "renk_kodu", "kapsam_kodu", "baslangic_tarihi"),
        alanlar=(
            Alan("urun_kodu", Tip.METIN, True, "Model kodu.", "KD25A-0412", referans="urunler.urun_kodu"),
            Alan("renk_kodu", Tip.METIN, False, "Renk kodu (boşsa tüm renkler).", ""),
            Alan("kapsam_tipi", Tip.METIN, True, "Fiyat hangi düzeyde: ulke / kanal / magaza.", "ulke", izinli=("ulke", "kanal", "magaza")),
            Alan("kapsam_kodu", Tip.METIN, True, "Ülke kodu, kanal adı ya da mağaza kodu.", "TR"),
            Alan("para_birimi", Tip.METIN, True, "ISO 4217.", "TRY"),
            Alan("liste_fiyati", Tip.ONDALIK, True, "İlk etiket fiyatı (KDV dahil, tüketicinin gördüğü).", "1299.90", min_deger=0),
            Alan("raf_fiyati", Tip.ONDALIK, False, "Kalıcı indirimli etiket fiyatı (yoksa liste fiyatı).", "999.90", min_deger=0),
            Alan("baslangic_tarihi", Tip.TARIH, True, "Geçerlilik başlangıcı.", "2025-08-04"),
            Alan("bitis_tarihi", Tip.TARIH, False, "Geçerlilik sonu (hâlâ geçerliyse boş).", ""),
        ),
        notlar=(
            "Sepette / kampanyalı indirimler buraya değil kampanyalar tablosuna yazılır; ödenen gerçek tutar satislar.net_tutar'dadır.",
            "Yüksek enflasyonlu para birimlerinde (TRY) sezon içi fiyat artışları mutlaka bu tabloda olmalı.",
        ),
    ),
    Tablo(
        ad="kampanyalar",
        zorunluluk=Zorunluluk.ONERILEN,
        aciklama="Kampanya takvimi ve mekaniği.",
        taneciklik="kampanya",
        anahtar=("kampanya_kodu",),
        alanlar=(
            Alan("kampanya_kodu", Tip.METIN, True, "Kampanya kodu.", "K-2025-BF"),
            Alan("kampanya_adi", Tip.METIN, False, "Kampanya adı.", "Efsane Cuma"),
            Alan("mekanik", Tip.METIN, True, "Kampanya mekaniği.", "yuzde_indirim", izinli=MEKANIKLER),
            Alan("indirim_orani", Tip.ONDALIK, False, "Ortalama indirim oranı 0-1 (x al y öde için eşdeğeri).", "0.30", min_deger=0),
            Alan("baslangic_tarihi", Tip.TARIH, True, "Başlangıç.", "2025-11-24"),
            Alan("bitis_tarihi", Tip.TARIH, True, "Bitiş (dahil).", "2025-11-30"),
            Alan("kanal", Tip.METIN, False, "Yalnızca bir kanalda geçerliyse kanal adı.", "", izinli=KANALLAR),
            Alan("aciklama", Tip.METIN, False, "Serbest açıklama.", ""),
        ),
    ),
    Tablo(
        ad="kampanya_kapsami",
        zorunluluk=Zorunluluk.ONERILEN,
        aciklama="Hangi kampanya hangi mağaza ve ürünlerde geçerli. Boş alan = tümü.",
        taneciklik="kampanya x mağaza x ürün",
        anahtar=(),
        alanlar=(
            Alan("kampanya_kodu", Tip.METIN, True, "Kampanya kodu.", "K-2025-BF", referans="kampanyalar.kampanya_kodu"),
            Alan("magaza_kodu", Tip.METIN, False, "Mağaza kodu (boşsa tüm mağazalar).", ""),
            Alan("ulke", Tip.METIN, False, "Ülke kodu (boşsa tüm ülkeler).", "TR"),
            Alan("urun_kodu", Tip.METIN, False, "Model kodu (boşsa tüm ürünler).", ""),
            Alan("kategori", Tip.METIN, False, "Kategori (boşsa tüm kategoriler).", ""),
        ),
    ),
    Tablo(
        ad="satislar",
        zorunluluk=Zorunluluk.ZORUNLU,
        aciklama="Günlük mağaza x SKU satış toplamları (fiş düzeyi gerekmez). İadeler ayrı tabloda.",
        taneciklik="gün x mağaza x SKU (x kampanya)",
        anahtar=("tarih", "magaza_kodu", "sku_kodu", "kampanya_kodu"),
        alanlar=(
            Alan("tarih", Tip.TARIH, True, "Satış günü.", "2025-08-09"),
            Alan("magaza_kodu", Tip.METIN, True, "Mağaza kodu.", "M-IST-014", referans="magazalar.magaza_kodu"),
            Alan("sku_kodu", Tip.METIN, True, "SKU kodu.", "KD25A-0412-BEJ-M", referans="skular.sku_kodu"),
            Alan("adet", Tip.TAMSAYI, True, "Satılan adet (iade düşülmeden, brüt).", "3", min_deger=0),
            Alan("brut_tutar", Tip.ONDALIK, False, "Etiket fiyatı x adet (KDV dahil).", "3899.70", min_deger=0),
            Alan("net_tutar", Tip.ONDALIK, True, "Tahsil edilen tutar, tüm indirimler sonrası (KDV dahil).", "3119.76", min_deger=0),
            Alan("kampanya_kodu", Tip.METIN, False, "Satışa uygulanan kampanya (yoksa boş).", "", referans="kampanyalar.kampanya_kodu"),
        ),
        notlar=(
            "Haftalık toplam kabul edilir ama günlük tercih edilir (kampanya ve stok bitişi etkisi gün düzeyinde ayrışır).",
            "Müşteri / kart / sadakat numarası istemiyoruz. Fiş düzeyi veri gerekirse fiş no anonimleştirilir.",
        ),
    ),
    Tablo(
        ad="iadeler",
        zorunluluk=Zorunluluk.ONERILEN,
        aciklama="Günlük mağaza x SKU iade toplamları. Online iadeler online 'mağaza' koduyla.",
        taneciklik="gün x mağaza x SKU",
        anahtar=("tarih", "magaza_kodu", "sku_kodu", "iade_nedeni"),
        alanlar=(
            Alan("tarih", Tip.TARIH, True, "İade günü.", "2025-08-20"),
            Alan("magaza_kodu", Tip.METIN, True, "İadenin alındığı mağaza.", "M-IST-014", referans="magazalar.magaza_kodu"),
            Alan("sku_kodu", Tip.METIN, True, "SKU kodu.", "KD25A-0412-BEJ-M", referans="skular.sku_kodu"),
            Alan("adet", Tip.TAMSAYI, True, "İade adedi.", "1", min_deger=0),
            Alan("net_tutar", Tip.ONDALIK, False, "İade edilen tutar.", "1039.92", min_deger=0),
            Alan("iade_nedeni", Tip.METIN, False, "beden / kalite / begenmedim / diger.", "beden"),
            Alan("satis_magaza_kodu", Tip.METIN, False, "Ürünün satıldığı mağaza (farklıysa).", ""),
        ),
    ),
    Tablo(
        ad="stok",
        zorunluluk=Zorunluluk.ZORUNLU,
        aciklama="Gün sonu stok anlık görüntüsü; mağazalar ve depolar aynı tabloda.",
        taneciklik="gün x lokasyon x SKU",
        anahtar=("tarih", "lokasyon_kodu", "sku_kodu"),
        alanlar=(
            Alan("tarih", Tip.TARIH, True, "Stok tarihi (gün sonu).", "2025-08-10"),
            Alan("lokasyon_kodu", Tip.METIN, True, "Mağaza ya da depo kodu.", "M-IST-014"),
            Alan("sku_kodu", Tip.METIN, True, "SKU kodu.", "KD25A-0412-BEJ-M", referans="skular.sku_kodu"),
            Alan("eldeki_adet", Tip.TAMSAYI, True, "Satılabilir eldeki adet (negatif olmamalı).", "4"),
            Alan("yoldaki_adet", Tip.TAMSAYI, False, "Lokasyona sevk edilmiş, henüz girmemiş adet.", "0", min_deger=0),
        ),
        notlar=(
            "Satış talep değildir: stoğu biten mağazada satış sıfırdır ama talep vardı. Bu tablo olmadan tahminler sistematik düşük çıkar.",
            "Günlük tercih edilir; haftalık (pazar gün sonu) kabul edilir. Sıfır stoklu satırlar da yazılmalıdır (eksik satır = bilinmiyor sayılır).",
            "Geçmiş stok çoğu ERP'de saklanmaz; saklanmıyorsa stok hareketlerinden (giriş/çıkış/transfer) geriye doğru hesaplanabilir.",
        ),
    ),
    Tablo(
        ad="satin_alma_siparisleri",
        zorunluluk=Zorunluluk.ZORUNLU,
        aciklama="Tedarikçiye verilen siparişler ve teslimatlar (ilk sipariş ve tekrar siparişler).",
        taneciklik="sipariş satırı (SKU)",
        anahtar=("siparis_no", "sku_kodu"),
        alanlar=(
            Alan("siparis_no", Tip.METIN, True, "Sipariş numarası.", "PO-25-1182"),
            Alan("sku_kodu", Tip.METIN, True, "SKU kodu.", "KD25A-0412-BEJ-M", referans="skular.sku_kodu"),
            Alan("tedarikci_kodu", Tip.METIN, False, "Tedarikçi kodu.", "TDR-018"),
            Alan("siparis_tipi", Tip.METIN, False, "ilk / tekrar.", "ilk", izinli=("ilk", "tekrar")),
            Alan("siparis_tarihi", Tip.TARIH, True, "Siparişin verildiği gün.", "2025-04-02"),
            Alan("planlanan_teslim_tarihi", Tip.TARIH, False, "Sözleşmedeki teslim günü.", "2025-07-15"),
            Alan("teslim_tarihi", Tip.TARIH, False, "Depoya gerçek giriş günü (teslim edilmediyse boş).", "2025-07-22"),
            Alan("siparis_adedi", Tip.TAMSAYI, True, "Sipariş adedi.", "240", min_deger=0),
            Alan("teslim_adedi", Tip.TAMSAYI, False, "Teslim alınan adet.", "236", min_deger=0),
            Alan("birim_maliyet", Tip.ONDALIK, False, "Sipariş birim maliyeti.", "182.50", min_deger=0),
            Alan("para_birimi", Tip.METIN, False, "ISO 4217.", "USD"),
            Alan("depo_kodu", Tip.METIN, False, "Teslim deposu.", "D-MERKEZ"),
        ),
        notlar=(
            "Tedarik süresi = teslim_tarihi - siparis_tarihi. 'Ne zaman üretmeli' sorusu bu tarihler olmadan cevaplanamaz.",
        ),
    ),
    Tablo(
        ad="sevkiyatlar",
        zorunluluk=Zorunluluk.OPSIYONEL,
        aciklama="Depodan mağazaya ve mağazalar arası transferler.",
        taneciklik="gün x kaynak x hedef x SKU",
        anahtar=(),
        alanlar=(
            Alan("tarih", Tip.TARIH, True, "Sevk günü.", "2025-08-01"),
            Alan("kaynak_lokasyon", Tip.METIN, True, "Çıkış lokasyonu.", "D-MERKEZ"),
            Alan("hedef_lokasyon", Tip.METIN, True, "Varış lokasyonu.", "M-IST-014"),
            Alan("sku_kodu", Tip.METIN, True, "SKU kodu.", "KD25A-0412-BEJ-M", referans="skular.sku_kodu"),
            Alan("adet", Tip.TAMSAYI, True, "Adet.", "12", min_deger=0),
        ),
    ),
    Tablo(
        ad="asortiman_plani",
        zorunluluk=Zorunluluk.OPSIYONEL,
        aciklama="Hangi ürün hangi mağazada hangi tarihler arasında satılacaktı. Bilerek kaldırılan ürünü stok bitişinden ayırır.",
        taneciklik="model x renk x mağaza",
        anahtar=("urun_kodu", "renk_kodu", "magaza_kodu"),
        alanlar=(
            Alan("urun_kodu", Tip.METIN, True, "Model kodu.", "KD25A-0412", referans="urunler.urun_kodu"),
            Alan("renk_kodu", Tip.METIN, True, "Renk kodu.", "BEJ"),
            Alan("magaza_kodu", Tip.METIN, True, "Mağaza kodu.", "M-IST-014", referans="magazalar.magaza_kodu"),
            Alan("baslangic_tarihi", Tip.TARIH, True, "Satışa başlama.", "2025-08-04"),
            Alan("bitis_tarihi", Tip.TARIH, False, "Plana göre satıştan kalkış.", "2026-01-25"),
        ),
    ),
    Tablo(
        ad="takvim",
        zorunluluk=Zorunluluk.OPSIYONEL,
        aciklama="Ülkeye özel tatil ve özel günler. Verilmezse genel takvim kullanılır.",
        taneciklik="gün x ülke",
        anahtar=("tarih", "ulke", "aciklama"),
        alanlar=(
            Alan("tarih", Tip.TARIH, True, "Gün.", "2025-03-30"),
            Alan("ulke", Tip.METIN, True, "ISO2 ülke kodu.", "TR"),
            Alan("gun_tipi", Tip.METIN, True, "resmi_tatil / dini_bayram / ozel_gun / okul_tatili.", "dini_bayram"),
            Alan("aciklama", Tip.METIN, False, "Açıklama.", "Ramazan Bayramı 1. gün"),
        ),
    ),
    Tablo(
        ad="doviz_kurlari",
        zorunluluk=Zorunluluk.OPSIYONEL,
        aciklama="Ciro raporlaması için günlük ya da aylık kur. Tahmin modeli kur kullanmaz (göreli fiyatla çalışır).",
        taneciklik="gün x para birimi",
        anahtar=("tarih", "para_birimi"),
        alanlar=(
            Alan("tarih", Tip.TARIH, True, "Gün (aylık ise ayın ilk günü).", "2025-08-01"),
            Alan("para_birimi", Tip.METIN, True, "ISO 4217.", "EUR"),
            Alan("try_karsiligi", Tip.ONDALIK, True, "1 birimin TRY karşılığı.", "47.20", min_deger=0),
        ),
    ),
)

TABLO = {t.ad: t for t in TABLOLAR}


# --- Pydantic satır modelleri ------------------------------------------------

_PY_TIP = {
    Tip.METIN: str,
    Tip.TAMSAYI: int,
    Tip.ONDALIK: float,
    Tip.TARIH: date,
    Tip.EVET_HAYIR: bool,
}


def _model_adi(tablo: str) -> str:
    return "".join(p.capitalize() for p in tablo.split("_")) + "Satiri"


def _pydantic_model(t: Tablo) -> type[BaseModel]:
    alanlar = {}
    for a in t.alanlar:
        tip = _PY_TIP[a.tip]
        if a.izinli:
            tip = Literal[a.izinli]  # type: ignore[valid-type]
        kisit = {}
        if a.min_deger is not None:
            kisit["ge"] = a.min_deger
        if a.zorunlu:
            alanlar[a.ad] = (tip, Field(..., description=a.aciklama, **kisit))
        else:
            alanlar[a.ad] = (Optional[tip], Field(None, description=a.aciklama, **kisit))
    return create_model(  # type: ignore[call-overload]
        _model_adi(t.ad),
        __config__=ConfigDict(str_strip_whitespace=True, extra="allow"),
        **alanlar,
    )


SATIR_MODELLERI: dict[str, type[BaseModel]] = {t.ad: _pydantic_model(t) for t in TABLOLAR}


def satir_dogrula(tablo: str, satir: dict) -> BaseModel:
    """Tek bir satırı (ör. API'den gelen) doğrular. Boş metinler None sayılır."""
    temiz = {k: (None if v == "" else v) for k, v in satir.items()}
    for a in TABLO[tablo].alanlar:
        if a.tip == Tip.EVET_HAYIR and isinstance(temiz.get(a.ad), str):
            temiz[a.ad] = temiz[a.ad].strip().lower() in ("evet", "e", "1", "true", "yes")
    return SATIR_MODELLERI[tablo].model_validate(temiz)


# --- Doküman ve şablon üretimi -----------------------------------------------

def alan_dokumani() -> str:
    satirlar = [
        "# Veri sözleşmesi: alan listesi",
        "",
        "Bu dosya `tahmin/sozlesme.py` içinden otomatik üretilir (`python -m tahmin sozlesme`). Elle düzenleme.",
        "Genel kurallar ve stok bitişi (sansürlü talep) notları için `veri-sozlesmesi.md`.",
        "",
    ]
    for t in TABLOLAR:
        satirlar += [
            f"## `{t.dosya_adi}` ({t.zorunluluk.value})",
            "",
            t.aciklama,
            "",
            f"- Taneciklik: {t.taneciklik}",
            f"- Benzersiz anahtar: {', '.join(f'`{k}`' for k in t.anahtar) if t.anahtar else 'yok (tekrar eden satırlar kontrol edilir)'}",
            "",
            "| Alan | Tip | Zorunlu | Açıklama | Örnek |",
            "|---|---|---|---|---|",
        ]
        for a in t.alanlar:
            ek = []
            if a.izinli:
                ek.append("İzinli: " + ", ".join(f"`{v}`" for v in a.izinli))
            if a.referans:
                ek.append(f"Bağlantı: `{a.referans}`")
            aciklama = a.aciklama + (" " + ". ".join(ek) + "." if ek else "")
            satirlar.append(
                f"| `{a.ad}` | {a.tip.value} | {'evet' if a.zorunlu else 'hayır'} | {aciklama} | {a.ornek or '-'} |"
            )
        if t.notlar:
            satirlar.append("")
            satirlar += [f"> {n}" for n in t.notlar]
        satirlar.append("")
    return "\n".join(satirlar)


def sablon_csv(t: Tablo) -> str:
    """Başlık satırı + bir örnek satır."""
    import csv
    import io

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow([a.ad for a in t.alanlar])
    w.writerow([a.ornek for a in t.alanlar])
    return buf.getvalue()
