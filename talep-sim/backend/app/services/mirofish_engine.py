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
from typing import Awaitable, Callable, Dict, List, Optional, Sequence

from .. import brand as brandlib
from .. import economy
from ..models import BrandProfile, PredictionRequest
from ..pricing import AgentPriceAnswer
from .engine import RegionSimulation
from .mirofish_client import MiroFishClient, MiroFishError, MiroFishTimeout
from .personas import PERSONAS, build_seed_document, region_of, scope_of, seed_hash, simulation_requirement

Fuser = Callable[[PredictionRequest], Awaitable[dict]]
Progress = Callable[[dict], Awaitable[None]]


class RegionUnavailable(MiroFishError):
    """Bölge için yeterli ajan cevabı alınamadı (genellikle yavaş model); diğer bölgeler etkilenmez."""


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
                 poll_s: float = 5, env_wait_s: float = 3600, retries: int = 1,
                 batch_size: int = 3, timeout_retries: int = 1, max_concurrency: int = 1,
                 min_valid: int = 2):
        self.client = client
        self.fuser = fuser
        self.state_path = Path(state_file)
        self.max_rounds = max_rounds
        self.interview_timeout = interview_timeout
        self.poll_s = poll_s
        self.env_wait_s = env_wait_s
        self.retries = retries
        # Yerel/yavaş modeller için: küçük röportaj grupları, zaman aşımında yeniden deneme,
        # bölgeleri sırayla koşma (max_concurrency, main.py tarafından okunur).
        self.batch_size = max(1, batch_size)
        self.timeout_retries = max(0, timeout_retries)
        self.max_concurrency = max(1, max_concurrency)
        self.min_valid = max(1, min_valid)
        self._worlds: Optional[Dict[str, dict]] = None
        self._lock = asyncio.Lock()

    async def fuse_product_card(self, req: PredictionRequest) -> dict:
        return await self.fuser(req)

    # --- dünya kurulumu -------------------------------------------------
    async def _ensure_world(self, scope: Optional[Sequence[str]] = None,
                            progress: Optional[Progress] = None) -> dict:
        """Seçili bölgelere özel dünya: yalnızca o bölgelerin tüketicileri kurulur ve kaydedilir."""
        regions = scope_of(scope)
        key = seed_hash(regions)
        async with self._lock:
            if self._worlds is None:
                self._worlds = {}
                if self.state_path.exists():
                    saved = json.loads(self.state_path.read_text())
                    # Eski biçim: tek dünya {"seed_hash": ..., ...}
                    self._worlds = {saved["seed_hash"]: saved} if "seed_hash" in saved else saved
            world = self._worlds.get(key)
            if world is not None and await self._world_alive(world):
                return world
            world = await self._build_world(regions, progress)
            self._worlds[key] = world
            self.state_path.write_text(json.dumps(self._worlds))
            return world

    async def _world_alive(self, world: dict) -> bool:
        try:
            return await self.client.env_alive(world["simulation_id"])
        except MiroFishError:
            return False

    async def _build_world(self, regions: List[str], progress: Optional[Progress] = None) -> dict:
        c = self.client
        started = asyncio.get_running_loop().time()

        async def step(n: int, text: str) -> None:
            if progress:
                mins = int((asyncio.get_running_loop().time() - started) // 60)
                await progress({"stage": "world", "detail": (
                    f"Dünya kuruluyor ({', '.join(regions)}), adım {n}/6: {text}. "
                    f"İlk seferde yerel modelle 10-30 dk sürebilir (geçen: {mins} dk)")})

        await step(1, "ontoloji üretiliyor")
        project_id = await c.generate_ontology(
            "tuketici_panelleri.md", build_seed_document(regions), simulation_requirement(regions), "talep-simulasyonu")
        await step(2, "bilgi grafiği kuruluyor")
        await c.wait_graph_task(await c.build_graph(project_id), poll_s=self.poll_s, timeout_s=self.env_wait_s)
        await step(3, "simülasyon oluşturuluyor")
        simulation_id = await c.create_simulation(project_id)
        await step(4, "ajan profilleri üretiliyor")
        await c.wait_prepared(simulation_id, await c.prepare(simulation_id), poll_s=self.poll_s, timeout_s=self.env_wait_s)

        profiles = await c.profiles(simulation_id)
        agents: Dict[str, List[int]] = {r: [] for r in regions}
        for p in profiles:
            text = " ".join(str(p.get(k, "")) for k in ("name", "username", "bio", "persona"))
            region = region_of(text)
            if region in agents:
                agents[region].append(int(p["user_id"]))
        if not any(agents.values()):
            raise MiroFishError("Hiçbir ajan bir bölgeye eşlenemedi; seed doküman ve profilleri kontrol et")

        await step(5, "simülasyon turları çalışıyor")
        await c.start(simulation_id, self.max_rounds)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.env_wait_s
        await step(6, "ortamın röportaja hazır olması bekleniyor")
        while not await c.env_alive(simulation_id):
            if loop.time() > deadline:
                raise MiroFishError("Simülasyon ortamı röportaja hazır hale gelmedi")
            await asyncio.sleep(self.poll_s)
        return {"project_id": project_id, "simulation_id": simulation_id, "agents": agents, "seed_hash": seed_hash(regions), "regions": regions}

    # --- bölge simülasyonu ----------------------------------------------
    async def _interview_chunk(self, simulation_id: str, chunk: List[int], prompt: str) -> Dict[int, str]:
        """Bir grubu röportaj eder; zaman aşımında aynı grubu yeniden dener, hâlâ olmazsa MiroFishTimeout fırlatır."""
        for attempt in range(1 + self.timeout_retries):
            try:
                return await self.client.interview_batch(simulation_id, chunk, prompt, self.interview_timeout)
            except MiroFishTimeout:
                if attempt == self.timeout_retries:
                    raise
        return {}

    async def simulate_region(self, card: dict, region: str, unit_cost: float,
                              brand: Optional[BrandProfile] = None,
                              fx_rates: Optional[dict] = None,
                              progress: Optional[Progress] = None,
                              scope: Optional[Sequence[str]] = None) -> RegionSimulation:
        async def note(detail: str) -> None:
            if progress:
                await progress({"stage": "interview", "region": region, "detail": detail})

        await note("Simülasyon dünyası hazırlanıyor")
        world = await self._ensure_world(scope or [region], progress)
        agent_ids = world["agents"].get(region, [])
        if not agent_ids:
            raise RegionUnavailable(f"{region} bölgesi için ajan bulunamadı")

        prompt = build_interview_prompt(card, region, brand, unit_cost, fx_rates)
        parsed: Dict[int, dict] = {}
        timed_out = 0
        stuck = False
        # Küçük/yerel modeller JSON'u bozabilir: geçersiz cevap verenleri bir kez daha sor.
        # Zaman aşımına uğrayan gruplar aynı turda yeniden denenir, olmazsa atlanır (kısmi sonuç).
        for _ in range(1 + self.retries):
            pending = [a for a in agent_ids if a not in parsed]
            if not pending or stuck:
                break
            chunks = [pending[i:i + self.batch_size] for i in range(0, len(pending), self.batch_size)]
            consecutive_timeouts = 0
            for n, chunk in enumerate(chunks, 1):
                await note(f"Ajanlar röportaj ediliyor ({len(parsed)}/{len(agent_ids)} cevap, grup {n}/{len(chunks)})")
                try:
                    responses = await self._interview_chunk(world["simulation_id"], chunk, prompt)
                except MiroFishTimeout:
                    timed_out += len(chunk)
                    consecutive_timeouts += 1
                    if consecutive_timeouts >= 2:  # model takılmış görünüyor, bölgeyi boşuna bekletme
                        stuck = True
                        break
                    continue
                consecutive_timeouts = 0
                for agent_id, text in responses.items():
                    answer = parse_agent_answer(text)
                    if answer:
                        parsed[agent_id] = answer
        valid = list(parsed.values())
        need = min(self.min_valid, len(agent_ids))
        if len(valid) < need:
            reason = "model zaman aşımına uğradı" if timed_out else "ajan cevapları geçerli JSON değildi"
            raise RegionUnavailable(
                f"{region}: {len(agent_ids)} ajandan yalnızca {len(valid)} geçerli cevap alınabildi "
                f"({reason}; en az {need} gerekli)")

        answers = [AgentPriceAnswer(*a["prices"]) for a in valid]
        demand = round(sum(a["interest"] for a in valid) / len(valid))
        counts = Counter(a["objection"] for a in valid if a["objection"])
        objections = [o for o, _ in counts.most_common(3)]
        meta = {"engine": "mirofish", "n_agents": len(agent_ids), "n_valid": len(valid),
                "n_timed_out": timed_out, "mean_interest": demand,
                "objection_counts": counts.most_common(3)}
        return RegionSimulation(region, demand, answers, objections, meta)
