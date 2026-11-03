"""Koleksiyon koşusu: her ürün mevcut tek ürün hattından (run_prediction) geçer; bölge başına aynı panel kullanılır.

- Ürünler sırayla koşar (darboğaz yerel LLM); bölgeler motorun eşzamanlılık ayarına göre.
- Her ürünün sonucu bitince diske yazılır. Koşu kesilir ya da API yeniden başlarsa tekrar başlatıldığında
  sonucu olan ürünler atlanır (girdi değişmediyse).
- Marka profili bir kez çıkarılır; ürün başına LLM öneri çağrısı yapılmaz (kural önerileri yeterli, süre kazanır).
"""
import asyncio
import base64
import hashlib
import json
import logging
import time
from decimal import Decimal
from typing import Awaitable, Callable, Dict, Optional

from ..advisor import Advisor
from ..models import Assumptions, BrandProfile, PredictionRequest
from .models import Collection, CollectionItem, RunOptions, RunStatus
from .store import CollectionStore

log = logging.getLogger("talep-sim.collection")
COST_FALLBACK_MULTIPLE = 2.7   # maliyet yoksa planlanan fiyat / 2.7 (kural varsayımı, yalnızca fiyat analizi için)


class SeededEngine:
    """Motoru sarar: ürün kartına koleksiyonun panel tohumunu ekler ve kartı görsel başına önbelleğe alır."""

    def __init__(self, inner, seed: str, cache_dir):
        self.inner, self.seed, self.cache_dir = inner, seed, cache_dir

    def __getattr__(self, name):
        return getattr(self.inner, name)

    async def fuse_product_card(self, req: PredictionRequest) -> dict:
        key = hashlib.sha1(f"{req.product_name}|{req.technical_specs}|{req.image_base64}".encode()).hexdigest()[:16]
        path = self.cache_dir / f"{key}.json"
        if path.exists():
            card = json.loads(path.read_text(encoding="utf-8"))
        else:
            card = dict(await self.inner.fuse_product_card(req))
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")
        card["panel_seed"] = self.seed
        return card

    async def simulate_region(self, *a, **kw):
        return await self.inner.simulate_region(*a, **kw)


def item_specs(it: CollectionItem) -> str:
    parts = [it.technical_specs]
    if it.category:
        parts.append(f"Kategori: {it.category}" + (f" / {it.subcategory}" if it.subcategory else ""))
    if it.colors:
        parts.append(f"Renkler: {', '.join(it.colors)}")
    if it.attributes:
        parts.append("; ".join(f"{k}: {v}" for k, v in it.attributes.items()))
    return ". ".join(p for p in parts if p) or it.name


def input_hash(it: CollectionItem, regions, brand: Optional[str], image_digest: str) -> str:
    payload = json.dumps([it.model_dump(exclude={"planned_price", "planned_qty", "declared_role", "moq"}),
                          sorted(regions), brand or "", image_digest], sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(payload.encode()).hexdigest()[:16]


Predict = Callable[..., Awaitable]


class CollectionRunner:
    def __init__(self):
        self.status: Dict[str, RunStatus] = {}
        self.tasks: Dict[str, asyncio.Task] = {}

    def get(self, cid: str) -> RunStatus:
        return self.status.get(cid) or RunStatus(collection_id=cid, running=False)

    def running(self, cid: str) -> bool:
        t = self.tasks.get(cid)
        return bool(t and not t.done())

    def stop(self, cid: str) -> bool:
        t = self.tasks.get(cid)
        if t and not t.done():
            t.cancel()
            return True
        return False

    def start(self, col: Collection, opts: RunOptions, store: CollectionStore, engine, profiler,
              predict: Predict, fx_rate: float) -> RunStatus:
        if self.running(col.id):
            return self.get(col.id)
        st = RunStatus(collection_id=col.id, running=True, started=time.time())
        self.status[col.id] = st
        self.tasks[col.id] = asyncio.create_task(self._run(col, opts, store, engine, profiler, predict, fx_rate, st))
        return st

    @staticmethod
    async def _brand(col, store, profiler, say) -> Optional[BrandProfile]:
        """Ekrandaki profil önceliklidir; yoksa marka adı + notlarla bir kez çıkarılır ve saklanır."""
        if col.meta.brand_profile is not None:
            store.save_brand(col.id, {"profile": json.loads(col.meta.brand_profile.model_dump_json()), "notes": col.meta.brand_notes})
            return col.meta.brand_profile
        if not col.meta.brand:
            return None
        saved = store.load_brand(col.id) or {}
        prof = saved.get("profile")
        if prof and prof.get("name") == col.meta.brand and saved.get("notes", "") == col.meta.brand_notes:
            return BrandProfile(**prof)
        say(f"{col.meta.brand} marka profili çıkarılıyor")
        brand = await profiler.profile(col.meta.brand, col.meta.brand_notes or None)
        store.save_brand(col.id, {"profile": json.loads(brand.model_dump_json()), "notes": col.meta.brand_notes})
        return brand

    async def _run(self, col, opts, store, engine, profiler, predict, fx_rate, st: RunStatus):
        def say(msg: str):
            st.detail = msg
            st.log = (st.log + [time.strftime("%H:%M:%S ") + msg])[-200:]

        try:
            col.status = "koşuyor"
            store.save(col)
            regions = opts.regions or col.meta.target_regions
            items = [it for it in col.items if not opts.only or it.sku in opts.only]
            st.total = len(items)
            brand = await self._brand(col, store, profiler, say)
            seeded = SeededEngine(engine, f"koleksiyon:{col.id}", store.dir(col.id) / "cards")
            to_usd = (lambda v: v / fx_rate) if col.meta.currency == "TRY" else (lambda v: v)
            budget_usd = to_usd(col.meta.total_budget) if col.meta.total_budget else 100000.0
            per_item_budget = max(1000, int(budget_usd / max(1, len(items))))
            advisor = Advisor(None)

            for i, it in enumerate(items, 1):
                st.current = it.sku
                if not it.images:
                    st.failed.append(it.sku)
                    store.save_result(col.id, it.sku, {"error": "Görsel yok"})
                    st.done += 1
                    continue
                img = store.image_path(col.id, it.images[0]).read_bytes()
                digest = hashlib.sha1(img).hexdigest()[:16]
                h = input_hash(it, regions, brand.model_dump_json() if brand else "", digest)
                old = store.load_result(col.id, it.sku)
                if old and old.get("response") and old.get("input_hash") == h and not opts.rerun:
                    say(f"{i}/{len(items)} {it.name}: önceki sonuç kullanıldı")
                    st.done += 1
                    continue
                cost = it.unit_cost or (it.planned_price / COST_FALLBACK_MULTIPLE if it.planned_price else None)
                if not cost:
                    st.failed.append(it.sku)
                    store.save_result(col.id, it.sku, {"error": "Birim maliyet ve planlanan fiyat yok; fiyat analizi yapılamaz"})
                    st.done += 1
                    continue
                say(f"{i}/{len(items)} {it.name} değerlendiriliyor")
                req = PredictionRequest(
                    product_name=it.name, image_base64=base64.b64encode(img).decode(),
                    technical_specs=item_specs(it), unit_cost=Decimal(str(round(to_usd(cost), 2))),
                    total_production_budget=per_item_budget, target_regions=regions, brand=brand.name if brand else None,
                    brand_profile=brand,
                    assumptions=Assumptions(channel=col.meta.channel, launch_month=it.launch_month or col.meta.launch_month),
                    usd_try_rate=fx_rate, allocation_objective=opts.allocation_objective)

                async def emit(ev: dict, _i=i, _it=it):
                    if ev.get("detail"):
                        st.detail = f"{_i}/{len(items)} {_it.name}: " + (f"{ev['region']} " if ev.get("region") else "") + ev["detail"]

                try:
                    resp = await predict(req, seeded, profiler, advisor, emit)
                    store.save_result(col.id, it.sku, {"input_hash": h, "panel_seed": seeded.seed,
                                                       "cost_assumed": it.unit_cost is None, "finished": time.time(),
                                                       "response": json.loads(resp.model_dump_json())})
                    if resp.failed_regions:
                        say(f"{it.name}: hesaplanamayan bölge {', '.join(f.region for f in resp.failed_regions)}")
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # tek ürün hatası koleksiyonu düşürmez
                    detail = getattr(e, "detail", None) or f"{type(e).__name__}: {e}"
                    log.exception("Koleksiyon ürünü düştü: %s", it.sku)
                    st.failed.append(it.sku)
                    store.save_result(col.id, it.sku, {"error": str(detail)[:500], "input_hash": h})
                    say(f"{it.name}: hata ({str(detail)[:160]})")
                st.done += 1
            col.status = "bitti"
            say(f"Bitti: {st.done - len(st.failed)} ürün değerlendirildi" + (f", {len(st.failed)} hata" if st.failed else ""))
        except asyncio.CancelledError:
            col.status = "hazır"
            say("Durduruldu; yeniden başlatınca kaldığı yerden devam eder")
        except Exception as e:
            log.exception("Koleksiyon koşusu düştü")
            col.status = "hata"
            st.error = f"{type(e).__name__}: {e}"
            say(f"Koşu düştü: {st.error}")
        finally:
            st.running = False
            st.current = None
            st.finished = time.time()
            try:
                store.save(col)
            except Exception:
                log.exception("Koleksiyon durumu kaydedilemedi")
