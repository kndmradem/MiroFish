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
import logging
import math
from collections import Counter
from pathlib import Path
from typing import Awaitable, Callable, Dict, List, Optional, Sequence

from .. import brand as brandlib
from .. import economy
from ..models import BrandProfile, PredictionRequest
from ..pricing import AgentPriceAnswer
from .answer_extractor import (AnswerExtractor, example_ladder, ladder_text, make_ladder,
                               parse_agent_answer)
from .engine import RegionSimulation
from .mirofish_client import MiroFishClient, MiroFishError, MiroFishTimeout
from .personas import PERSONAS, build_seed_document, region_of, scope_of, seed_hash, simulation_requirement

Fuser = Callable[[PredictionRequest], Awaitable[dict]]
Progress = Callable[[dict], Awaitable[None]]
log = logging.getLogger(__name__)
RAW_CHARS = 1500


class RegionUnavailable(MiroFishError):
    """Bölge için yeterli ajan cevabı alınamadı (genellikle yavaş model); diğer bölgeler etkilenmez."""

    def __init__(self, message: str, raw_answers: Optional[List[dict]] = None):
        super().__init__(message)
        self.raw_answers = raw_answers or []


def build_interview_prompt(card: dict, region: str, brand: Optional[BrandProfile] = None,
                           unit_cost: Optional[float] = None, fx_rates: Optional[dict] = None,
                           ladder: Optional[List[float]] = None) -> str:
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
        f"{_answer_format(ladder, (fx_rates or {}).get(eco.currency) if eco else None)}"
    )


def _answer_format(ladder: Optional[List[float]], try_rate: Optional[float]) -> str:
    if not ladder:
        return ("Sadece şu JSON ile cevap ver: "
                '{"interest": 0-100 arası SAYI, "too_cheap": USD sayı, "cheap": USD sayı, '
                '"expensive": USD sayı, "too_expensive": USD sayı, "objection": "tek kısa cümle"}')
    return (
        "Ürün şu fiyatlardan biriyle satılsa ne düşünürsün? Her fiyat için TEK etiket seç:\n"
        f"{ladder_text(ladder, try_rate if try_rate and (try_rate > 0) else None)}\n"
        'Etiketler: "supheli" (bu kadar ucuzsa kaliteden şüphelenirim), "uygun" (makul, alırım), '
        '"pahali" (pahalı ama düşünürüm), "cok_pahali" (asla almam).\n'
        "Sadece şu JSON ile cevap ver, başka metin yazma. interest 0-100 arası TEK BİR SAYI olmalı, cümle yazma:\n"
        f'{{"interest": 65, "ladder": {example_ladder(len(ladder))}, "objection": "tek kısa cümle"}}'
    )


class MiroFishSimulationEngine:
    def __init__(self, client: MiroFishClient, fuser: Fuser, state_file: str,
                 max_rounds: int = 3, interview_timeout: int = 180,
                 poll_s: float = 5, env_wait_s: float = 3600, retries: int = 1,
                 batch_size: int = 3, timeout_retries: int = 1, max_concurrency: int = 1,
                 min_valid: int = 2, extractor: Optional[AnswerExtractor] = None,
                 agents_per_region: int = 10):
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
        self.extractor = extractor
        self.agents_per_region = max(1, agents_per_region)
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
            self._load_state()
            world = self._worlds.get(key)
            if world is not None and await self._world_alive(world):
                return world
            world = await self._build_world(regions, progress)
            self._worlds[key] = world
            self.state_path.write_text(json.dumps(self._worlds))
            return world

    async def reset_world(self, scope: Optional[Sequence[str]] = None,
                          progress: Optional[Progress] = None) -> List[str]:
        """Seçili bölgelerin önbellekteki dünyasını unutur ve MiroFish/Zep tarafında silmeyi dener.

        Silme en iyi çabayla yapılır: başarısız olsa bile bir sonraki çağrı yeni proje ve yeni Zep grafiğiyle
        sıfırdan kurar (eski kayıt yalnızca Zep Cloud'da artık kalır). Dönüş: kullanıcıya gösterilecek notlar.
        """
        regions = scope_of(scope)
        key = seed_hash(regions)
        notes: List[str] = []
        async with self._lock:
            self._load_state()
            world = self._worlds.pop(key, None)
            self.state_path.write_text(json.dumps(self._worlds))
            # Eski sürümden kalan, artık kullanılmayan kayıtlar da bu bölge kapsamı için temizlenir.
            stale = [k for k, w in self._worlds.items() if sorted(w.get("regions", [])) == sorted(regions)]
            olds = ([world] if world else []) + [self._worlds.pop(k) for k in stale]
            if stale:
                self.state_path.write_text(json.dumps(self._worlds))
        if not olds:
            return ["Önbellekte bu bölgeler için dünya yoktu; sıfırdan kurulacak."]
        for w in olds:
            if progress:
                await progress({"stage": "world", "detail": f"Eski dünya siliniyor ({', '.join(regions)})"})
            for label, call in (("ortam kapatıldı", lambda: self.client.close_env(w["simulation_id"])),
                                ("simülasyon durduruldu", lambda: self.client.stop(w["simulation_id"]))):
                try:
                    await call()
                except MiroFishError as e:
                    log.info("Dünya sıfırlama: %s atlandı: %s", label, e)
            try:
                await self.client.delete_project(w["project_id"])
                notes.append(f"Eski proje ve Zep grafiği silindi ({w['project_id']}).")
            except MiroFishError as e:
                log.warning("Eski proje silinemedi: %s", e)
                notes.append(f"Eski proje silinemedi ({w['project_id']}): Zep Cloud panelinden 'mirofish_' grafiklerini elle silebilirsin. Yeni dünya yine de sıfırdan kuruldu.")
        return notes

    @staticmethod
    def _valid_world(w) -> bool:
        return (isinstance(w, dict) and isinstance(w.get("project_id"), str) and isinstance(w.get("simulation_id"), str)
                and isinstance(w.get("agents"), dict))

    def _load_state(self) -> None:
        """Önbelleği okur; eski/bozuk biçimli kayıtlar (ya da dosya) geçersiz sayılır ve dünya yeniden kurulur."""
        if self._worlds is not None:
            return
        self._worlds = {}
        if not self.state_path.exists():
            return
        try:
            saved = json.loads(self.state_path.read_text())
        except (OSError, ValueError):
            log.warning("Dünya önbelleği okunamadı (%s); yeniden kurulacak", self.state_path)
            return
        if not isinstance(saved, dict):
            return
        # Eski biçim: tek dünya {"seed_hash": ..., ...} ya da seed_hash'siz düz dünya
        if self._valid_world(saved):
            saved = {str(saved.get("seed_hash") or "legacy"): saved}
        self._worlds = {k: w for k, w in saved.items() if self._valid_world(w)}
        if len(self._worlds) != len(saved):
            log.warning("Önbellekte geçersiz dünya kayıtları atıldı")

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
    async def _understand(self, text: str, currency_note: str, ladder: Optional[List[float]] = None,
                          try_rate: Optional[float] = None):
        """(cevap, durum): önce hoşgörülü ayrıştırma, fiyat çıkmazsa LLM ile çıkarım, o da olmazsa kısmi cevap."""
        if not (text or "").strip():
            return None, "empty"
        answer = parse_agent_answer(text, ladder)
        if answer is not None and answer["prices"] is not None:
            return answer, "json"
        if self.extractor is not None and ladder:
            extracted = await self.extractor.extract(text, ladder, currency_note, try_rate)
            if extracted is not None and (extracted["prices"] is not None or answer is None):
                return extracted, "extracted"
        if answer is not None:
            return answer, "partial"  # yalnızca ilgi puanı: talep skoruna katılır, fiyat eşiği yok
        return None, "failed"

    @staticmethod
    def _fallback_prices(reference: float, brand: Optional[BrandProfile], region: str, n: int) -> List[AgentPriceAnswer]:
        """Ajanlardan fiyat gelmediğinde referans fiyat etrafında deterministik bir panel."""
        sens = economy.sensitivity_adj(region)
        b = brand or brandlib.generic_profile(None, "")
        spread, tol = brandlib.price_spread(b, sens), brandlib.upper_tolerance(b, sens)
        out = []
        for i in range(n):
            z = (i - (n - 1) / 2) / max(1, n - 1) * 2  # -1..1
            mid = reference * math.exp(spread * z)
            out.append(AgentPriceAnswer(too_cheap=mid * 0.5, cheap=mid * 0.78, expensive=mid * 1.2 * tol,
                                        too_expensive=mid * 1.6 * tol))
        return out

    def _persist(self, region: str, raw_answers: List[dict]) -> None:
        """Hata ayıklama için ham cevapları (kısaltılmış) diske ve loga yazar."""
        path = self.state_path.with_name(self.state_path.name + ".answers.jsonl")
        try:
            with path.open("a", encoding="utf-8") as f:
                for r in raw_answers:
                    f.write(json.dumps({"region": region, **r}, ensure_ascii=False) + "\n")
        except OSError as e:
            log.warning("Ham cevaplar yazılamadı: %s", e)
        for r in raw_answers:
            log.info("%s ajan %s [%s]: %s", region, r["agent"], r["status"], r["text"][:200].replace("\n", " "))

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
        async def note(detail: str, **counts) -> None:
            if progress:
                await progress({"stage": "interview", "region": region, "detail": detail, **counts})

        await note("Simülasyon dünyası hazırlanıyor")
        world = await self._ensure_world(scope or [region], progress)
        agent_ids = world["agents"].get(region, [])[: self.agents_per_region]
        if not agent_ids:
            raise RegionUnavailable(f"{region} bölgesi için ajan bulunamadı")

        persona = PERSONAS[region]
        reference = ((brandlib.reference_price(brand, unit_cost) if brand else unit_cost * brandlib.NEUTRAL_MULTIPLE)
                     * persona.price_multiplier / brandlib.NEUTRAL_MULTIPLE)
        ladder = make_ladder(reference)
        prompt = build_interview_prompt(card, region, brand, unit_cost, fx_rates, ladder)
        parsed: Dict[int, dict] = {}
        raw: Dict[int, dict] = {}
        eco = economy.REGION_ECONOMY.get(region)
        rate = (fx_rates or {}).get(eco.currency) if eco else None
        try_rate = rate if eco and eco.currency == "TRY" else None
        currency_note = (f"Cevaptaki fiyatlar {eco.currency} ise USD'ye çevir (1 USD = {rate:g} {eco.currency})."
                         if eco and rate else "")
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
                await note(f"Ajanlar röportaj ediliyor ({len(parsed)}/{len(agent_ids)} cevap, grup {n}/{len(chunks)})",
                           answered=len(parsed), agents=len(agent_ids), chunk=n, chunks=len(chunks), phase="interview")
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
                    await note(f"Ajan {agent_id} cevabı çözümleniyor", answered=len(parsed), agents=len(agent_ids),
                               chunk=n, chunks=len(chunks), phase="parse")
                    answer, how = await self._understand(text, currency_note, ladder, try_rate)
                    raw[agent_id] = {"agent": agent_id, "status": how, "text": (text or "")[:RAW_CHARS]}
                    if answer:
                        parsed[agent_id] = answer
                        raw[agent_id]["interest"] = answer["interest"]
                        await note(f"{len(parsed)}/{len(agent_ids)} ajan cevapladı", answered=len(parsed),
                                   agents=len(agent_ids), chunk=n, chunks=len(chunks), phase="answered")
        valid = list(parsed.values())
        raw_answers = list(raw.values())
        self._persist(region, raw_answers)
        need = min(self.min_valid, len(agent_ids))
        if len(valid) < need:
            reason = "model zaman aşımına uğradı" if timed_out else "ajan cevaplarından fiyat/ilgi bilgisi çıkarılamadı"
            snippet = next((r["text"] for r in raw_answers if r["text"]), "")[:200].replace("\n", " ")
            hint = f" Örnek ham cevap: «{snippet}»" if snippet else ""
            raise RegionUnavailable(
                f"{region}: {len(agent_ids)} ajandan yalnızca {len(valid)} geçerli cevap alınabildi "
                f"({reason}; en az {need} gerekli).{hint}", raw_answers)

        priced = [a for a in valid if a["prices"] is not None]
        if len(priced) >= max(2, min(self.min_valid, len(valid))):
            answers = [AgentPriceAnswer(*a["prices"]) for a in priced]
            price_source = "agents"
        else:  # fiyat bilgisi yetersiz: eşikler ajanlardan değil, marka/maliyet referansından üretilir
            answers = self._fallback_prices(reference, brand, region, max(len(valid), 5))
            price_source = "brand_fallback"
        votes = [a["ranks"] for a in priced if a.get("ranks")]
        demand = round(sum(a["interest"] for a in valid) / len(valid))
        counts = Counter(a["objection"] for a in valid if a["objection"])
        objections = [o for o, _ in counts.most_common(3)]
        meta = {"engine": "mirofish", "n_agents": len(agent_ids), "n_valid": len(valid),
                "n_timed_out": timed_out, "n_priced": len(priced), "price_source": price_source,
                "n_extracted": sum(r["status"] == "extracted" for r in raw_answers),
                "n_estimated": sum(1 for a in valid if a.get("estimated")), "raw_answers": raw_answers,
                "mean_interest": demand, "ladder": ladder, "ladder_votes": votes if price_source == "agents" else [],
                "objection_counts": counts.most_common(3)}
        return RegionSimulation(region, demand, answers, objections, meta)
