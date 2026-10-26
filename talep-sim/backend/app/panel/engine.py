"""MiroFish'siz doğrudan panel motoru (`SIM_ENGINE=panel`).

MiroFish dünya kurar (ontoloji, Zep grafiği, profil üretimi, simülasyon turları) ve sonra ajanlara röportaj
yapar. Bizim çıktılarımız için gereken yalnızca röportaj cevaplarıdır. Bu motor aynı cevapları doğrudan üretir:

1. Bölgenin persona kütüphanesinden (veri dosyası) segment ağırlıklarına göre N kişilik panel örneklenir.
2. Her kişiye, bölgenin tarihli bağlam paketi + ürün kartı + fiyat merdiveni tek bir LLM çağrısıyla sorulur
   (JSON şeması, hoşgörülü ayrıştırma, onarım denemesi; bkz. questioner.py).
3. İsteğe bağlı akran turu: kişiler diğerlerinin yorum özetini görüp yeniden cevaplar (varsayılan kapalı).
4. Kalibrasyon katsayıları uygulanır, cevaplar `RegionSimulation`a çevrilir; fiyat bölgeleri, iade, satış
   tahmini, senaryolar ve dağıtım değişmeden çalışır.

Zep, dünya kurma ve dış bulut bağımlılığı yoktur; yerel LLM (Ollama/vLLM) yeterlidir.
"""
import asyncio
import hashlib
import math
import time
from collections import Counter
from datetime import date
from typing import Awaitable, Callable, Dict, List, Optional, Sequence

from .. import brand as brandlib
from .. import economy
from ..models import BrandProfile, PredictionRequest
from ..pricing import AgentPriceAnswer
from ..services.answer_extractor import make_ladder
from ..services.engine import RegionSimulation
from ..services.llm import LLMError
from . import prompts
from .calibration import Calibration
from .library import PanelStore, freshness_warnings, sample_panel
from .questioner import PanelLLM, PanelReply

Fuser = Callable[[PredictionRequest], Awaitable[dict]]
Progress = Callable[[dict], Awaitable[None]]
RAW_CHARS = 1500


class PanelUnavailable(LLMError):
    """Bölge için yeterli geçerli cevap alınamadı; diğer bölgeler etkilenmez."""

    def __init__(self, message: str, raw_answers: Optional[List[dict]] = None):
        super().__init__(message)
        self.raw_answers = raw_answers or []


def _seed_int(*parts: str) -> int:
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:8], 16)


class DirectPanelEngine:
    def __init__(self, store: PanelStore, llm: PanelLLM, fuser: Fuser, panel_size: int = 12,
                 min_valid: int = 4, peer_round: bool = False, calibration: Optional[Calibration] = None,
                 persona_version: Optional[str] = None, as_of: Optional[date] = None):
        self.store = store
        self.llm = llm
        self.fuser = fuser
        self.panel_size = max(1, panel_size)
        self.min_valid = max(1, min_valid)
        self.peer_round = peer_round
        self.calibration = calibration or Calibration()
        self.persona_version = persona_version   # None = active.json'daki sürüm
        self.as_of = as_of                       # None = bugün; backtest'te lansman tarihi

    async def fuse_product_card(self, req: PredictionRequest) -> dict:
        return await self.fuser(req)

    async def _ask_all(self, members, card, ctx, ladder, brand, region, unit_cost, try_rate, seed,
                       note, peer: Optional[str] = None) -> Dict[int, PanelReply]:
        replies: Dict[int, PanelReply] = {}
        phase = "peer" if peer else "interview"

        async def one(m):
            r = await self.llm.ask(prompts.system_prompt(m),
                                   prompts.user_prompt(card, ctx, ladder, brand, region, unit_cost, try_rate, peer),
                                   ladder, seed=_seed_int(seed, str(m.index), phase))
            replies[m.index] = r
            ok = sum(1 for x in replies.values() if x.answer)
            await note(f"{'Akran turu: ' if peer else ''}{len(replies)}/{len(members)} kişi cevapladı ({ok} geçerli)",
                       answered=ok, agents=len(members), phase="answered")
            return r

        await asyncio.gather(*(one(m) for m in members))
        return replies

    @staticmethod
    def _fallback_prices(reference: float, brand: Optional[BrandProfile], region: str, n: int) -> List[AgentPriceAnswer]:
        """Panelden yeterli fiyat kararı gelmezse referans fiyat etrafında deterministik eşikler (varsayım)."""
        b = brand or brandlib.generic_profile(None, "")
        sens = economy.sensitivity_adj(region)
        spread, tol = brandlib.price_spread(b, sens), brandlib.upper_tolerance(b, sens)
        out = []
        for i in range(n):
            mid = reference * math.exp(spread * ((i - (n - 1) / 2) / max(1, n - 1) * 2))
            out.append(AgentPriceAnswer(mid * 0.5, mid * 0.78, mid * 1.2 * tol, mid * 1.6 * tol))
        return out

    async def simulate_region(self, card: dict, region: str, unit_cost: float,
                              brand: Optional[BrandProfile] = None,
                              fx_rates: Optional[dict] = None,
                              progress: Optional[Progress] = None,
                              scope: Optional[Sequence[str]] = None) -> RegionSimulation:
        async def note(detail: str, **counts) -> None:
            if progress:
                await progress({"stage": "interview", "region": region, "detail": detail, **counts})

        started = time.monotonic()
        lib = self.store.personas(region, self.persona_version)
        ctx = self.store.context(region, self.as_of)
        cal = self.calibration.for_region(region)
        warnings = freshness_warnings(lib, ctx, self.as_of)

        reference = ((brandlib.reference_price(brand, unit_cost) if brand else unit_cost * brandlib.NEUTRAL_MULTIPLE)
                     * lib.price_level / brandlib.NEUTRAL_MULTIPLE)
        ladder = make_ladder(reference)
        currency = economy.currency_of(region)
        rate = (fx_rates or {}).get(currency) if currency else None
        try_rate = rate if currency == "TRY" and rate else None
        seed = f"{card.get('product_name')}|{brand.name if brand else ''}|{region}"
        members = sample_panel(lib, self.panel_size, seed, cal.sensitivity_scale, cal.trend_scale)
        await note(f"{len(members)} kişilik panel ({lib.version}, {len(lib.segments)} segment) sorgulanıyor",
                   answered=0, agents=len(members), phase="interview")

        replies = await self._ask_all(members, card, ctx, ladder, brand, region, unit_cost, try_rate, seed, note)
        peer_used = False
        if self.peer_round:
            first = [r.answer for r in replies.values() if r.answer]
            if len(first) >= 2:
                objs = [o for o, _ in Counter(a["objection"] for a in first if a["objection"]).most_common(4)]
                summary = prompts.peer_summary(objs, sum(a["interest"] for a in first) / len(first), len(first))
                second = await self._ask_all(members, card, ctx, ladder, brand, region, unit_cost, try_rate, seed,
                                             note, peer=summary)
                replies = {i: (second[i] if second[i].answer else replies[i]) for i in replies}
                peer_used = True

        by_index = {m.index: m for m in members}
        raw_answers = [{"agent": i, "status": r.status, "segment": by_index[i].segment.label,
                        "text": (r.text or r.error)[:RAW_CHARS],
                        **({"interest": r.answer["interest"]} if r.answer else {})}
                       for i, r in sorted(replies.items())]
        valid = [r.answer for r in replies.values() if r.answer]
        need = min(self.min_valid, len(members))
        if len(valid) < need:
            errors = [r.error for r in replies.values() if r.error]
            why = f" İlk hata: {errors[0]}" if errors else ""
            raise PanelUnavailable(f"{region}: {len(members)} kişiden yalnızca {len(valid)} geçerli cevap alındı "
                                   f"(en az {need} gerekli).{why}", raw_answers)

        ps = cal.price_scale
        priced = [a for a in valid if a["prices"] is not None]
        if len(priced) >= max(2, min(self.min_valid, len(valid))):
            answers = [AgentPriceAnswer(*(p * ps for p in a["prices"])) for a in priced]
            price_source = "agents"
        else:
            answers = self._fallback_prices(reference * ps, brand, region, max(len(valid), 5))
            price_source = "brand_fallback"
        mean_interest = sum(a["interest"] for a in valid) / len(valid)
        demand = int(max(0, min(100, round(mean_interest * cal.demand_scale))))
        counts = Counter(a["objection"] for a in valid if a["objection"])
        seg_mix = Counter(m.segment.label for m in members)
        meta = {
            "engine": "panel", "n_agents": len(members), "n_valid": len(valid), "n_priced": len(priced),
            "n_timed_out": sum(r.status == "error" for r in replies.values()),
            "n_extracted": sum(r.status == "repaired" for r in replies.values()),
            "n_estimated": sum(1 for a in valid if a.get("estimated")), "price_source": price_source,
            "raw_answers": raw_answers, "mean_interest": round(mean_interest),
            "ladder": [p * ps for p in ladder],
            "ladder_votes": [a["ranks"] for a in priced if a.get("ranks")] if price_source == "agents" else [],
            "objection_counts": counts.most_common(3),
            "persona_version": lib.version, "persona_as_of": lib.as_of.isoformat(),
            "context_version": ctx.version if ctx else None, "context_as_of": ctx.as_of.isoformat() if ctx else None,
            "freshness_warnings": warnings, "segments": dict(seg_mix), "peer_round": peer_used,
            "calibration": {"demand_scale": cal.demand_scale, "price_scale": ps,
                            "sensitivity_scale": cal.sensitivity_scale, "trend_scale": cal.trend_scale,
                            "n_obs": cal.n_obs},
            "elapsed_s": round(time.monotonic() - started, 1),
        }
        return RegionSimulation(region, demand, answers, [o for o, _ in counts.most_common(3)], meta)
