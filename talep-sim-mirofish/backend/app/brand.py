"""Marka profilinin fiyat ve talep üzerindeki etkisi (motordan bağımsız saf fonksiyonlar)."""
from typing import Dict, Optional, Tuple

from .models import BrandProfile

NEUTRAL_MULTIPLE = 2.7  # marka verilmediğinde perakende fiyat / maliyet

# Katmana göre makul fiyat çarpanı aralığı; LLM'in tutarsız cevabını sınırlar.
TIER_MULTIPLE_RANGE: Dict[str, Tuple[float, float]] = {
    "budget": (1.8, 2.8),
    "mass": (2.2, 3.6),
    "upper_mass": (3.0, 5.5),
    "premium": (4.0, 9.0),
    "luxury": (6.0, 25.0),
}
TIER_LABEL = {"budget": "ekonomik", "mass": "kitlesel", "upper_mass": "üst-kitlesel",
              "premium": "premium", "luxury": "lüks"}


def generic_profile(name: Optional[str], warning: str) -> BrandProfile:
    return BrandProfile(name=name or "Markasız", positioning="Marka bilgisi yok; nötr kitlesel varsayım.",
                        warning=warning)


def region_strength(brand: BrandProfile, region: str) -> int:
    return int(brand.regional_strength.get(region, 50))


def demand_points(brand: BrandProfile, region: str) -> Tuple[float, float]:
    """(bölgesel marka gücü etkisi, genel marka çekim gücü etkisi), endeks puanı."""
    return (region_strength(brand, region) - 50) * 0.35, (brand.brand_pull - 50) * 0.15


def effective_sensitivity(brand: BrandProfile, adj: float = 0.0) -> float:
    """Marka duyarlılığı + bölgesel ekonomik düzeltme (ör. enflasyon altındaki pazar), 0-1 arasında."""
    return max(0.0, min(1.0, brand.price_sensitivity + adj))


def price_spread(brand: BrandProfile, adj: float = 0.0) -> float:
    """Ajan fiyat algısının log-normal yayılımı: fiyata duyarlı kitle dar bir bantta toplanır."""
    return 0.35 - 0.15 * effective_sensitivity(brand, adj)


def upper_tolerance(brand: BrandProfile, adj: float = 0.0) -> float:
    """Fiyata duyarsız kitle 'pahalı' ve 'çok pahalı' eşiklerini daha yukarı koyar."""
    return 1 + 0.3 * (1 - effective_sensitivity(brand, adj))


def reference_price(brand: BrandProfile, unit_cost: float) -> float:
    return unit_cost * brand.price_multiple
