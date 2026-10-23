"""Bölgesel ajan personaları (teknik doküman §6).

`prompt` alanı gerçek LLM / MiroFish entegrasyonunda sistem promptu olarak
kullanılacak. Diğer alanlar mock simülasyonun parametreleri.
"""
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence


@dataclass(frozen=True)
class RegionPersona:
    region: str
    city: str
    prompt: str
    # Mock parametreleri: ürün özelliklerine verilen ağırlıklar (-1..+1)
    likes: Dict[str, float]
    # Ajanın "makul" bulduğu fiyatın maliyete oranı (ortalama)
    price_multiplier: float


VISION_PROMPT = (
    "Sen kıdemli bir tekstil mühendisisin. Ekteki görseli ve sağlanan teknik metni incele. "
    "Bunları birleştirerek kumaş dokusunu, iklim uyumluluğunu ve stil kategorisini içeren "
    "standart bir JSON profili oluştur."
)

PERSONAS: Dict[str, RegionPersona] = {
    "MENA": RegionPersona(
        region="MENA",
        city="Dubai",
        prompt="Sen Dubai'de yaşayan bir tüketicisin. Lükse, kumaş parlaklığına ve gösterişe önem verirsin.",
        likes={"sheen": 0.9, "premium": 0.7, "warmth": -0.6, "heavy": -0.7, "eco": 0.1, "waterproof": -0.1, "oversize": 0.3},
        price_multiplier=3.2,
    ),
    "EU": RegionPersona(
        region="EU",
        city="Berlin",
        prompt=(
            "Sen Berlin'de yaşayan bir tüketicisin. Kumaşın çevreci (sürdürülebilir) olmasına ve "
            "minimalist işlevselliğe önem verirsin. Gereksiz pahalı ürünleri reddedersin."
        ),
        likes={"eco": 0.9, "synthetic": -0.5, "sheen": -0.4, "premium": -0.2, "warmth": 0.4, "waterproof": 0.5, "oversize": 0.4},
        price_multiplier=2.6,
    ),
    "CIS": RegionPersona(
        region="CIS",
        city="Almatı",
        prompt=(
            "Sen soğuk iklimde yaşayan birisin. Görsellikten ziyade ısı yalıtımı, dayanıklılık ve "
            "rüzgar/su geçirmezlik senin için en kritik karar faktörüdür."
        ),
        likes={"warmth": 1.0, "heavy": 0.6, "waterproof": 0.8, "sheen": -0.2, "eco": 0.0, "synthetic": 0.1, "oversize": 0.0},
        price_multiplier=2.2,
    ),
    "US": RegionPersona(
        region="US",
        city="New York",
        prompt=(
            "Sen New York'ta yaşayan bir tüketicisin. Rahatlık, marka hikâyesi ve fiyat/performans "
            "dengesine bakarsın; trend parçaları seversin."
        ),
        likes={"oversize": 0.7, "premium": 0.3, "warmth": 0.3, "waterproof": 0.4, "eco": 0.3, "sheen": 0.0, "heavy": -0.2},
        price_multiplier=2.8,
    ),
    "TR": RegionPersona(
        region="TR",
        city="İstanbul",
        prompt=(
            "Sen İstanbul'da yaşayan bir tüketicisin. Yüksek enflasyon ve kur dalgalanması yüzünden alım gücün "
            "düşük; fiyata çok duyarlısın, indirim dönemlerini ve kampanyaları beklersin, taksitle alışveriş "
            "yaparsın ve yerli markalarla fiyat karşılaştırırsın. Kalite ve dayanıklılık için ancak makul bir "
            "fark ödersin."
        ),
        likes={"warmth": 0.4, "waterproof": 0.3, "heavy": 0.1, "oversize": 0.3, "premium": 0.2, "sheen": 0.1,
               "eco": 0.1, "synthetic": -0.1},
        price_multiplier=1.9,
    ),
}


# MiroFish dünyasını kurmak için seed doküman. Her bölgeden adlandırılmış
# tüketiciler; MiroFish bunlardan Zep grafiği ve ajan profilleri üretir.
# İsimler ajan -> bölge eşlemesinde de kullanılır.
SEED_CONSUMERS: Dict[str, List[str]] = {
    "EU": [
        "Lena Hoffmann, 31, Berlin, UX tasarımcı; kapsül gardırop, ikinci el ve sertifikalı kumaş arar",
        "Jonas Weber, 27, Hamburg, bisikletle işe gider; işlevsellik ve dayanıklılık ister, logo sevmez",
        "Camille Laurent, 38, Lyon, öğretmen; doğal lif, sade kesim, makul fiyat",
        "Sofia Rossi, 24, Milano, moda öğrencisi; trendleri takip eder ama hızlı modaya karşıdır",
        "Pieter de Vries, 45, Amsterdam, mimar; minimalist, uzun ömürlü parçalar için fazla ödemeye hazır",
    ],
    "MENA": [
        "Fatima Al Mansoori, 29, Dubai, pazarlama yöneticisi; lüks markalar, parlak kumaşlar, gösterişli detay",
        "Omar Haddad, 35, Riyad, girişimci; statü gösteren premium parçalar, AVM alışverişi",
        "Layla Nasser, 26, Doha, influencer; fotoğrafta iyi duran, dikkat çeken ürünler",
        "Khalid Al Farsi, 42, Abu Dabi, banka müdürü; klimalı ortamlar için ince, kaliteli kumaş",
        "Noor Saleh, 33, Kuveyt, diş hekimi; muhafazakâr kesim, ipek ve saten sever",
    ],
    "CIS": [
        "Aigerim Seitkali, 30, Almatı, mühendis; -25°C kışlar, ısı yalıtımı her şeyden önce gelir",
        "Dmitri Volkov, 41, Novosibirsk, saha çalışanı; rüzgar ve kar geçirmezlik, dayanıklılık",
        "Nino Beridze, 28, Tiflis, grafik tasarımcı; sıcak tutan ama şık parçalar",
        "Rustam Aliyev, 36, Bakü, satış müdürü; rüzgarlı şehir, su itici dış giyim, fiyat/performans",
        "Olga Smirnova, 52, Yekaterinburg, muhasebeci; uzun yıllar giyilecek kalın, sağlam kumaş",
    ],
    "US": [
        "Emily Carter, 29, New York, ürün yöneticisi; rahat oversize kesim, marka hikâyesi önemli",
        "Marcus Johnson, 34, Chicago, öğretmen; soğuk rüzgar, fiyat/performans, kolay bakım",
        "Ashley Nguyen, 23, Los Angeles, üniversite öğrencisi; TikTok trendleri, uygun fiyat",
        "Daniel Brooks, 46, Seattle, yazılımcı; yağmura dayanıklı, sade ve teknik giyim",
        "Rachel Kim, 38, Austin, emlakçı; şık ama rahat, online alışveriş, kolay iade",
    ],
    "TR": [
        "Elif Demir, 29, Istanbul, pazarlama uzmanı; kira ve enflasyon baskısı altında, indirim dönemlerini bekler, taksitle alır",
        "Mehmet Yılmaz, 38, Ankara, kamu çalışanı; sabit maaş, dayanıklı ve uygun fiyatlı ürün arar",
        "Zeynep Kaya, 25, Izmir, üniversite öğrencisi; sosyal medya trendlerini izler ama bütçesi dar, uygun fiyat arar",
        "Burak Şahin, 34, Bursa, mühendis; kalite/fiyat dengesine bakar, yerli markalarla kıyaslar, kampanyaları takip eder",
        "Ayşe Çelik, 45, Antalya, esnaf; sezonluk alışveriş yapar, nakit ile taksit arasında hesap yapar, iade kolaylığı önemli",
    ],
}

def simulation_requirement(regions: Optional[Sequence[str]] = None) -> str:
    regions = list(regions or SEED_CONSUMERS)
    return (
        f"{len(regions)} bölgesel pazardaki ({', '.join(regions)}) tüketicilerin yeni moda/tekstil ürünlerini "
        "nasıl değerlendirdiğini simüle et. Her tüketici kendi şehrinin iklimini, kültürünü ve "
        "satın alma önceliklerini korumalı. Tüketiciler ürünler hakkında fikir paylaşır, fiyat "
        "algılarını ve itirazlarını tartışır."
    )


SIMULATION_REQUIREMENT = simulation_requirement()


def scope_of(regions: Optional[Sequence[str]] = None) -> List[str]:
    """Seçili bölgeler (sıra bağımsız, tekrarsız); boşsa hepsi."""
    return [r for r in SEED_CONSUMERS if not regions or r in regions]


def seed_hash(regions: Optional[Sequence[str]] = None) -> str:
    """Seed dokümanın özeti: seçili bölge/tüketici listesi değişince farklı bir MiroFish dünyası gerekir."""
    import hashlib
    return hashlib.sha256(build_seed_document(regions).encode()).hexdigest()[:12]


def build_seed_document(regions: Optional[Sequence[str]] = None) -> str:
    """Yalnızca seçili bölgelerin tüketici panellerini içerir; seçilmeyen bölge dünyaya hiç girmez."""
    lines = ["# Bölgesel Tüketici Panelleri", ""]
    for region in scope_of(regions):
        people = SEED_CONSUMERS[region]
        persona = PERSONAS[region]
        lines += [f"## {region} paneli ({persona.city} ve çevresi)", "", f"Bölge profili: {persona.prompt}", ""]
        lines += [f"- {p} ({region} bölgesi tüketicisi)" for p in people]
        lines.append("")
    return "\n".join(lines)


def region_of(profile_text: str) -> str | None:
    """Ajan profil metninden bölgeyi bulur: önce seed isimleri, sonra şehir/bölge kodu."""
    text = profile_text.lower()
    for region, people in SEED_CONSUMERS.items():
        if any(p.split(",")[0].lower() in text for p in people):
            return region
    for region, people in SEED_CONSUMERS.items():
        cities = {p.split(",")[2].strip().lower() for p in people}
        if any(c in text for c in cities) or re.search(rf"\b{region.lower()}\b", text):
            return region
    return None
