"""Karma motor (SIM_ENGINE=hybrid): MiroFish yapabildiği yerde, kalan yerde bizim persona panelimiz.

- Ürün kartı, dünya kurma/sıfırlama ve bölge simülasyonu önce MiroFish ajan sürüsüyle denenir.
- MiroFish bir bölgeyi hesaplayamazsa (servis kapalı, zaman aşımı, yeterli geçerli cevap yok) o bölge
  persona paneliyle hesaplanır. Bölgenin sonucu "panel" olarak etiketlenir ve nedeni not edilir; sessizce
  karıştırılmaz.
- MiroFish'te karşılığı olmayan işler (koleksiyondaki vitrin turu, persona/bağlam sürüm bilgisi) panel
  motoruna bırakılır: `self.panel` bu iş için dışarıya açıktır.
"""
import logging
import time
from typing import Optional, Sequence

import httpx

from ..models import BrandProfile, PredictionRequest
from .engine import RegionSimulation
from .mirofish_engine import Progress
from .llm import LLMError
from .mirofish_client import MiroFishError

log = logging.getLogger(__name__)

# MiroFish'e hiç bağlanılamazsa bu süre boyunca tekrar denenmez (her bölgede bağlantı zaman aşımı beklenmesin)
DOWN_COOLDOWN_S = 60.0


class HybridEngine:
    def __init__(self, mirofish, panel, fallback_on_error: bool = True, mirofish_url: str = ""):
        self.mirofish_url = mirofish_url
        self.mirofish = mirofish
        self.panel = panel
        self.fallback_on_error = fallback_on_error
        self.max_concurrency = getattr(mirofish, "max_concurrency", 1)
        self._down_until = 0.0
        self._down_reason = ""

    async def fuse_product_card(self, req: PredictionRequest) -> dict:
        return await self.mirofish.fuse_product_card(req)

    async def reset_world(self, scope: Optional[Sequence[str]] = None, progress: Optional[Progress] = None):
        self._down_until = 0.0
        return await self.mirofish.reset_world(scope, progress)

    async def _via_panel(self, reason: str, card: dict, region: str, unit_cost: float, brand, fx_rates, progress,
                         scope) -> RegionSimulation:
        if progress:
            await progress({"stage": "interview", "region": region,
                            "detail": f"MiroFish {region} için sonuç veremedi, persona paneliyle devam ediliyor ({reason})"})
        sim = await self.panel.simulate_region(card, region, unit_cost, brand, fx_rates, progress=progress, scope=scope)
        sim.meta["fallback_from"] = "mirofish"
        sim.meta["fallback_reason"] = reason
        return sim

    async def simulate_region(self, card: dict, region: str, unit_cost: float,
                              brand: Optional[BrandProfile] = None,
                              fx_rates: Optional[dict] = None,
                              progress: Optional[Progress] = None,
                              scope: Optional[Sequence[str]] = None) -> RegionSimulation:
        if self.fallback_on_error and time.monotonic() < self._down_until:
            return await self._via_panel(f"MiroFish'e ulaşılamıyor: {self._down_reason}", card, region, unit_cost,
                                         brand, fx_rates, progress, scope)
        try:
            return await self.mirofish.simulate_region(card, region, unit_cost, brand, fx_rates,
                                                       progress=progress, scope=scope)
        except (MiroFishError, LLMError, httpx.HTTPError, OSError) as e:
            if not self.fallback_on_error:
                raise
            reason = f"{type(e).__name__}: {e}"[:300]
            if isinstance(e, (httpx.ConnectError, ConnectionError)) or isinstance(e.__cause__, (httpx.ConnectError, ConnectionError)):
                url = self.mirofish_url or "MiroFish adresi"
                reason = (f"MiroFish servisi kapalı ya da ulaşılamıyor ({url}). MiroFish penceresinin (1-mirofish.sh) "
                          f"açık ve hatasız çalıştığını kontrol edin. Teknik ayrıntı: {reason}")[:400]
                self._down_until = time.monotonic() + DOWN_COOLDOWN_S
                self._down_reason = reason
            log.warning("MiroFish %s bölgesinde düştü, panele geçiliyor: %s", region, reason)
            return await self._via_panel(reason, card, region, unit_cost, brand, fx_rates, progress, scope)
