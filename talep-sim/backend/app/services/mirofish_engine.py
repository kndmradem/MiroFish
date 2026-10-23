"""MiroFish tabanlı simülasyon motoru.

Akış:
1. Dünya kurulumu (bir kez, diske kaydedilir): seed tüketici paneli ->
   Zep grafiği -> OASIS ajan profilleri -> kısa simülasyon -> ortam hazır.
   Ajanlar profil metnindeki isim/şehirden bölgelere eşlenir.
2. Her tahminde: ürün kartı, bölgedeki ajanlara röportaj sorusu olarak sorulur.
   Ajan JSON cevap verir: ilgi puanı, dört Van Westendorp eşiği, itirazı.
3. Cevaplar `RegionSimulation`a çevrilir; fiyat analizi ve bütçe dağıtımı
   motordan bağımsız çalışmaya devam eder.
"""
import asyncio
import json
import re
from collections import Counter
from pathlib import Path
from typing import Awaitable, Callable, Dict, List, Optional

from .. import brand as brandlib
from .. import economy
from ..models import BrandProfile, PredictionRequest
from ..pricing import AgentPriceAnswer
from .engine import RegionSimulation
from .mirofish_client import MiroFishClient, MiroFishError
from .personas import PERSONAS, SIMULATION_REQUIREMENT, build_seed_document, region_of, seed_hash

Fuser = Callable[[PredictionRequest], Awaitable[dict]]


def build_interview_prompt(card: dict, region: str, brand: Optional[BrandProfile] = None,
                           unit_cost: Optional[float] = None, fx_rates: Optional[dict] = None) -> str:
    persona = PERSONAS[region]
    features = ", ".join(k for k, v in card.get("features", {}).items() if v) or "belirtilmemiş"
    brand_block = ""
    if brand is not None:
        ref = f" Bu marka bu tür ürünleri genelde yaklaşık ${brandlib.reference_price(brand, unit_cost):.0f} civarında satar." if unit_cost else ""
        brand_block = (
            f"Marka: {brand.name} ({brandlib.TIER_LABEL[brand.price_tier]} segment). {brand.positioning} "
            f"Tipik müşteri: {brand.typical_customer or '-'}.{ref} "
            f"Markanın bu bölgedeki bilinirliği: {brandlib.region_strength(brand, region)}/100. "
            "Ürünü ve fiyat eşiklerini bu markanın müşterisi gibi değerlendir.\n"
        )
    eco = economy.REGION_ECONOMY.get(region)
    if eco is not None:
        rate = (fx_rates or {}).get(eco.currency)
        brand_block += f"Ekonomik bağlam: {eco.context}"
        if rate:
            brand_block += f" Kur: 1 USD = {rate:g} {eco.currency}; fiyatı kafanda {eco.currency} ile değerlendir, cevabını USD ver."
        brand_block += "\n"
    return (
        f"{persona.prompt}\n\n"
        "Aşağıdaki yeni ürünü bir tüketici olarak değerlendir. Fiyatlar ABD doları.\n"
        f"{brand_block}"
        f"Ürün: {card.get('product_name')}\n"
        f"Kumaş: {card.get('fabric_texture', '-')}; bileşim: {card.get('composition', '-')}; "
        f"gramaj: {card.get('gsm') or '-'}\n"
        f"İklim uyumu: {card.get('climate_fit', '-')}; stil: {card.get('style_category', '-')}\n"
        f"Görünüm: {card.get('visual_description', '-')}\n"
        f"Öne çıkan özellikler: {features}\n\n"
        "Sadece şu JSON ile cevap ver, başka metin yazma:\n"
        '{"interest": 0-100 arası satın alma ilgin, '
        '"too_cheap": bu fiyatın altında kaliteden şüphelenirim, '
        '"cheap": bu fiyat uygun ve kelepir, '
        '"expensive": bu fiyat pahalı ama düşünürüm, '
        '"too_expensive": bu fiyatın üstünde asla almam, '
        '"objection": ürüne en büyük itirazın, tek kısa cümle}\n'
        "Fiyat eşikleri artan sırada olmalı: too_cheap < cheap < expensive < too_expensive."
    )


def parse_agent_answer(text: str) -> Optional[dict]:
    """Ajan cevabından JSON çıkarır; tutarsız ya da eksik cevap None döner."""
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return None
    try:
        raw = json.loads(match.group(0))
        vals = [float(raw[k]) for k in ("too_cheap", "cheap", "expensive", "too_expensive")]
        interest = max(0.0, min(100.0, float(raw["interest"])))
    except (ValueError, KeyError, TypeError):
        return None
    if not all(0 < a < b for a, b in zip(vals, vals[1:])) or vals[0] <= 0:
        return None
    return {"interest": interest, "prices": vals, "objection": str(raw.get("objection", "")).strip()}


class MiroFishSimulationEngine:
    def __init__(self, client: MiroFishClient, fuser: Fuser, state_file: str,
                 max_rounds: int = 3, interview_timeout: int = 180,
                 poll_s: float = 5, env_wait_s: float = 600, retries: int = 1):
        self.client = client
        self.fuser = fuser
        self.state_path = Path(state_file)
        self.max_rounds = max_rounds
        self.interview_timeout = interview_timeout
        self.poll_s = poll_s
        self.env_wait_s = env_wait_s
        self.retries = retries
        self._world: Optional[dict] = None
        self._lock = asyncio.Lock()

    async def fuse_product_card(self, req: PredictionRequest) -> dict:
        return await self.fuser(req)

    # --- dünya kurulumu -------------------------------------------------
    async def _ensure_world(self) -> dict:
        async with self._lock:
            if self._world is None and self.state_path.exists():
                self._world = json.loads(self.state_path.read_text())
            # Seed (bölge/tüketici listesi) değiştiyse kayıtlı dünya eskidir, yeniden kurulur.
            if self._world is not None and self._world.get("seed_hash") == seed_hash() \
                    and await self._world_alive(self._world):
                return self._world
            self._world = await self._build_world()
            self.state_path.write_text(json.dumps(self._world))
            return self._world

    async def _world_alive(self, world: dict) -> bool:
        try:
            return await self.client.env_alive(world["simulation_id"])
        except MiroFishError:
            return False

    async def _build_world(self) -> dict:
        c = self.client
        project_id = await c.generate_ontology(
            "tuketici_panelleri.md", build_seed_document(), SIMULATION_REQUIREMENT, "talep-simulasyonu")
        await c.wait_graph_task(await c.build_graph(project_id), poll_s=self.poll_s)
        simulation_id = await c.create_simulation(project_id)
        await c.wait_prepared(simulation_id, await c.prepare(simulation_id), poll_s=self.poll_s)

        profiles = await c.profiles(simulation_id)
        agents: Dict[str, List[int]] = {r: [] for r in PERSONAS}
        for p in profiles:
            text = " ".join(str(p.get(k, "")) for k in ("name", "username", "bio", "persona"))
            region = region_of(text)
            if region:
                agents[region].append(int(p["user_id"]))
        if not any(agents.values()):
            raise MiroFishError("Hiçbir ajan bir bölgeye eşlenemedi; seed doküman ve profilleri kontrol et")

        await c.start(simulation_id, self.max_rounds)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.env_wait_s
        while not await c.env_alive(simulation_id):
            if loop.time() > deadline:
                raise MiroFishError("Simülasyon ortamı röportaja hazır hale gelmedi")
            await asyncio.sleep(self.poll_s)
        return {"project_id": project_id, "simulation_id": simulation_id, "agents": agents, "seed_hash": seed_hash()}

    # --- bölge simülasyonu ----------------------------------------------
    async def simulate_region(self, card: dict, region: str, unit_cost: float,
                              brand: Optional[BrandProfile] = None,
                              fx_rates: Optional[dict] = None) -> RegionSimulation:
        world = await self._ensure_world()
        agent_ids = world["agents"].get(region, [])
        if not agent_ids:
            raise MiroFishError(f"{region} bölgesi için ajan bulunamadı")

        prompt = build_interview_prompt(card, region, brand, unit_cost, fx_rates)
        parsed: Dict[int, dict] = {}
        pending = list(agent_ids)
        # Küçük/yerel modeller JSON'u bozabilir: geçersiz cevap veren ajanlara bir kez daha sor.
        for _ in range(1 + self.retries):
            if not pending:
                break
            responses = await self.client.interview_batch(
                world["simulation_id"], pending, prompt, self.interview_timeout)
            for agent_id, text in responses.items():
                answer = parse_agent_answer(text)
                if answer:
                    parsed[agent_id] = answer
            pending = [a for a in pending if a not in parsed]
        parsed = list(parsed.values())
        if len(parsed) < max(1, len(agent_ids) // 2):
            raise MiroFishError(
                f"{region}: {len(agent_ids)} ajandan yalnızca {len(parsed)} geçerli cevap geldi")

        answers = [AgentPriceAnswer(*a["prices"]) for a in parsed]
        demand = round(sum(a["interest"] for a in parsed) / len(parsed))
        counts = Counter(a["objection"] for a in parsed if a["objection"])
        objections = [o for o, _ in counts.most_common(3)]
        meta = {"engine": "mirofish", "n_agents": len(agent_ids), "n_valid": len(parsed),
                "mean_interest": demand, "objection_counts": counts.most_common(3)}
        return RegionSimulation(region, demand, answers, objections, meta)
