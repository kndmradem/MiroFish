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
from . import showcase
from .store import CollectionStore

log = logging.getLogger("talep-sim.collection")
COST_FALLBACK_MULTIPLE = 2.7   # maliyet yoksa planlanan fiyat / 2.7 (kural varsayımı, yalnızca fiyat analizi için)


class SeededEngine:
    """Motoru sarar: ürün kartına koleksiyonun panel tohumunu ekler ve kartı görsel başına önbelleğe alır."""

    def __init__(self, inner, seed: Optional[str], cache_dir):
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
        if self.seed:       # bağımsız üründe tohum yok: panel motoru tekli ekrandaki gibi ürün adına göre kişi seçer
            card["panel_seed"] = self.seed
        else:
            card.pop("panel_seed", None)
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


def input_hash(it: CollectionItem, regions, brand: Optional[str], image_digest: str, kind: str = "koleksiyon") -> str:
    parts = [it.model_dump(exclude={"planned_price", "planned_qty", "declared_role", "moq", "color_images"}), sorted(regions), brand or "", image_digest]
    if kind != "koleksiyon":    # tür değişirse panel değişir (ortak panel / ürün başına panel), ürün yeniden sorulur
        parts.append(kind)
    payload = json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str)
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

    @staticmethod
    async def _showcase(col, opts, store, engine, brand, regions, fx_rate, say, st):
        """Tek tek turdan sonra vitrin turu. Yalnızca panel motorunda (kişi ve LLM erişimi gerekir)."""
        if not (hasattr(engine, "llm") and hasattr(engine, "store") and hasattr(engine.llm, "ask_json")):
            say("Vitrin turu atlandı: yalnızca panel motorunda (SIM_ENGINE=panel) çalışır")
            return
        res = store.results(col.id, [i.sku for i in col.items])
        ok = {s: r for s, r in res.items() if r.get("response")}
        if len(ok) < 3:
            say("Vitrin turu atlandı: en az 3 değerlendirilmiş ürün gerekli")
            return
        to_usd = (lambda v: v / fx_rate) if col.meta.currency == "TRY" else (lambda v: v)
        items = {i.sku: i for i in col.items}
        cards = {s: r["response"].get("product_card") or {"product_name": items[s].name} for s, r in ok.items()}
        sig = hashlib.sha1(json.dumps([sorted((s, r.get("input_hash")) for s, r in ok.items()),
                                       brand.model_dump_json() if brand else "", opts.block_size,
                                       {s: items[s].planned_price for s in ok}],
                                      sort_keys=True, default=str).encode()).hexdigest()[:16]
        base = store.dir(col.id) / "showcase"
        base.mkdir(parents=True, exist_ok=True)
        for region in regions:
            path = base / f"{region}.jsonl"
            meta = base / f"{region}.sig"
            if opts.rerun or not meta.exists() or meta.read_text() != sig:
                path.unlink(missing_ok=True)
                meta.write_text(sig)
            prices = {}
            for s, r in ok.items():
                pp = items[s].planned_price
                reg = next((x for x in r["response"]["regional_breakdown"] if x["region"] == region), None)
                prices[s] = to_usd(pp) if pp else (float(reg["optimal_sale_price"]) if reg else None)
            done = showcase.load_jsonl(path)

            def save(rec, _p=path):
                with _p.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")

            def note(msg):
                st.detail = msg

            say(f"{region} vitrin turu başlıyor ({len(ok)} ürün, en fazla {opts.block_size} ürünlük gruplar)")
            try:
                await showcase.run_region(engine, region, f"koleksiyon:{col.id}", brand, cards, prices,
                                          fx_rate if region == "TR" else None, opts.block_size, done, save, note)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.exception("Vitrin turu düştü: %s", region)
                say(f"{region} vitrin turu hata verdi: {type(e).__name__}: {e}")

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
            independent = col.meta.kind == "bagimsiz"
            seeded = SeededEngine(engine, None if independent else f"koleksiyon:{col.id}", store.dir(col.id) / "cards")
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
                h = input_hash(it, regions, brand.model_dump_json() if brand else "", digest, col.meta.kind)
                old = store.load_result(col.id, it.sku)
                if old and old.get("response") and old.get("input_hash") == h and not opts.rerun:
                    say(f"{i}/{len(items)} {it.name}: önceki sonuç kullanıldı")
                    st.done += 1
                    continue
                cost = it.unit_cost or (it.planned_price / COST_FALLBACK_MULTIPLE if it.planned_price else None)
                if not cost:
                    st.failed.append(it.sku)
                    store.save_result(col.id, it.sku, {"error": "Maliyet fiyatı yok; marj, fiyat önerisi ve üretim kararı hesaplanamaz"})
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
            if opts.showcase and not independent:
                await self._showcase(col, opts, store, engine, brand, regions, fx_rate, say, st)
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
