"""Simülasyon motoru arayüzü ve mock implementasyonu.

`SimulationEngine` gerçek implementasyonun (Claude Vision + MiroFish ajan
sürüsü) uyacağı sözleşmedir. `MockSimulationEngine` LLM çağrılarını
`asyncio.sleep` ile taklit eder; çıktılar ürün adı + bölgeye göre
deterministiktir, yani aynı girdi aynı sonucu verir.
"""
import asyncio
import hashlib
import random
import re
from dataclasses import dataclass, field
from typing import Awaitable, Callable, List, Optional, Protocol

from .. import brand as brandlib
from .. import economy
from ..models import BrandProfile, PredictionRequest
from ..pricing import AgentPriceAnswer
from .personas import PERSONAS


@dataclass
class RegionSimulation:
    region: str
    demand_score: int
    price_answers: List[AgentPriceAnswer]
    objections: List[str]
    # Açıklama üretimi için motorun hesap ayrıntıları (bkz. explain.py)
    meta: dict = field(default_factory=dict)


class SimulationEngine(Protocol):
    async def fuse_product_card(self, req: PredictionRequest) -> dict: ...

    async def simulate_region(self, card: dict, region: str, unit_cost: float,
                              brand: Optional[BrandProfile] = None,
                              fx_rates: Optional[dict] = None,
                              progress: Optional[Callable[[dict], Awaitable[None]]] = None) -> RegionSimulation: ...


_FEATURE_KEYWORDS = {
    "warmth": r"yün|wool|kaşmir|cashmere|polar|fleece|kaz tüyü|down|astar|kışlık|termal",
    "waterproof": r"su itici|su geçirmez|waterproof|water.?repellent|rüzgar",
    "sheen": r"saten|satin|ipek|silk|parlak|metalik|lame|kadife|velvet",
    "eco": r"organik|organic|geri dönüş|recycled|sürdürülebilir|sustainable|tencel|keten|linen",
    "synthetic": r"polyester|polyamid|naylon|nylon|akrilik|acrylic",
    "premium": r"kaşmir|cashmere|ipek|silk|deri|leather|el işi|premium|lüks",
    "oversize": r"oversize|bol kesim|relaxed|loose",
}

# (bölge, tetikleyici özellik, beklenen işaret) -> itiraz. İşaret +1: özellik
# varsa itiraz eder, -1: özellik yoksa itiraz eder.
_OBJECTIONS = [
    ("MENA", "heavy", 1, "Kumaş bu iklim için fazla kalın ve ağır"),
    ("MENA", "warmth", 1, "Yılın büyük kısmında giyilemeyecek kadar sıcak"),
    ("MENA", "sheen", -1, "Kumaş mat; lüks ve gösterişli bir duruşu yok"),
    ("MENA", "premium", -1, "Premium algısı zayıf, marka değeri hissettirmiyor"),
    ("EU", "synthetic", 1, "Sentetik oranı yüksek, sürdürülebilir değil"),
    ("EU", "eco", -1, "Sertifikalı/geri dönüştürülmüş içerik bilgisi yok"),
    ("EU", "sheen", 1, "Fazla gösterişli, minimalist gardıropla uyumsuz"),
    ("EU", "premium", 1, "İşlevine göre gereksiz pahalı görünüyor"),
    ("CIS", "warmth", -1, "Isı yalıtımı sert kış için yetersiz"),
    ("CIS", "waterproof", -1, "Rüzgar ve kar geçirmezliği belirtilmemiş"),
    ("CIS", "sheen", 1, "Parlak yüzey kirlenmeye ve aşınmaya dayanıksız görünüyor"),
    ("US", "oversize", -1, "Kalıp dar, rahat kesim beklentisini karşılamıyor"),
    ("US", "heavy", 1, "Günlük kullanım için fazla hantal"),
    ("US", "premium", -1, "Marka hikâyesi ve farklılaştırıcı detay eksik"),
]

_GENERIC_OBJECTIONS = [
    "Renk seçenekleri sınırlı",
    "Bakım talimatı zahmetli (kuru temizleme)",
    "Beden tablosu belirsiz, iade riski yüksek",
    "Benzer ürünler rakiplerde daha uygun fiyatlı",
]


def _seed(*parts: str) -> int:
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:12], 16)


class MockSimulationEngine:
    def __init__(self, agents_per_region: int = 40, latency_s: float = 0.4):
        self.agents_per_region = agents_per_region
        self.latency_s = latency_s

    async def fuse_product_card(self, req: PredictionRequest) -> dict:
        await asyncio.sleep(self.latency_s)  # Vision LLM çağrısı yerine
        text = f"{req.product_name} {req.technical_specs}".lower()
        features = {k: bool(re.search(p, text)) for k, p in _FEATURE_KEYWORDS.items()}
        gsm_match = re.search(r"gsm\s*:?\s*(\d+)|(\d+)\s*(?:g/m|gsm)", text)
        gsm = int(next(g for g in gsm_match.groups() if g)) if gsm_match else None
        features["heavy"] = bool(gsm and gsm >= 350)
        return {
            "product_name": req.product_name,
            "gsm": gsm,
            "features": features,
            "climate_fit": "soğuk" if features["warmth"] or features["heavy"] else "ılıman",
            "style_category": "oversize" if features["oversize"] else "standart",
            "has_image": bool(req.image_base64),
            "source": "mock",
        }

    async def simulate_region(self, card: dict, region: str, unit_cost: float,
                              brand: Optional[BrandProfile] = None,
                              fx_rates: Optional[dict] = None,
                              progress: Optional[Callable[[dict], Awaitable[None]]] = None) -> RegionSimulation:
        await asyncio.sleep(self.latency_s)  # MiroFish ajan turu yerine
        persona = PERSONAS[region]
        features = card["features"]
        rng = random.Random(_seed(card["product_name"], region, brand.name if brand else ""))
        brand = brand or brandlib.generic_profile(None, "")

        fit = sum(w for f, w in persona.likes.items() if features.get(f))
        fit = max(-1.5, min(1.5, fit))
        region_pts, pull_pts = brandlib.demand_points(brand, region)
        noise = rng.uniform(-6, 6)

        demand = 55 + fit * 22 + region_pts + pull_pts + noise
        demand_score = int(max(0, min(100, round(demand))))

        # Fiyat merkezi: maliyet x markanın tipik çarpanı x bölgenin alım gücü faktörü.
        # Uyum fiyat algısını da kaydırır: beğenilen ürüne daha fazla ödenir.
        region_factor = persona.price_multiplier / brandlib.NEUTRAL_MULTIPLE
        center = unit_cost * brand.price_multiple * region_factor * (1 + 0.15 * fit)
        sens_adj = economy.sensitivity_adj(region)  # örn. enflasyonlu pazarda fiyata duyarlılık artar
        spread, tol = brandlib.price_spread(brand, sens_adj), brandlib.upper_tolerance(brand, sens_adj)
        answers = []
        for _ in range(self.agents_per_region):
            mid = center * rng.lognormvariate(0, spread)
            answers.append(AgentPriceAnswer(
                too_cheap=mid * rng.uniform(0.40, 0.55),
                cheap=mid * rng.uniform(0.70, 0.85),
                expensive=mid * rng.uniform(1.10, 1.30) * tol,
                too_expensive=mid * rng.uniform(1.45, 1.75) * tol,
            ))
        meta = {
            "engine": "mock", "n_agents": self.agents_per_region, "fit_points": round(fit * 22, 1),
            "brand_region_points": round(region_pts, 1), "brand_pull_points": round(pull_pts, 1),
            "noise_points": round(noise, 1), "price_center": round(center, 2),
            "region_factor": round(region_factor, 2), "sensitivity_adj": sens_adj,
            "matched_features": [f for f, w in persona.likes.items() if features.get(f)],
        }

        triggered = [
            (abs(persona.likes.get(feat, 0.3)), text)
            for reg, feat, sign, text in _OBJECTIONS
            if reg == region and features.get(feat, False) == (sign > 0)
        ]
        triggered.sort(key=lambda t: -t[0])
        objections = [t for _, t in triggered][:3]
        pool = _GENERIC_OBJECTIONS[:]
        rng.shuffle(pool)
        objections += pool[: 3 - len(objections)]

        return RegionSimulation(region, demand_score, answers, objections, meta)
