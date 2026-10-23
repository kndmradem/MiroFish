"""Bölgesel ajan personaları (teknik doküman §6).

`prompt` alanı gerçek LLM / MiroFish entegrasyonunda sistem promptu olarak
kullanılacak. Diğer alanlar mock simülasyonun parametreleri.
"""
from dataclasses import dataclass
from typing import Dict


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
}
