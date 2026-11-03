"""Koleksiyon sonuçlarının hesaplanması. LLM çağırmaz: kayıtlı ürün sonuçlarından (tek ürün akışının çıktısı ve
panel kişilerinin ham ilgi puanları) türetilir. Bu yüzden 'ürünü çıkarsak / fiyatı değiştirsek / bütçeyi
değiştirsek' soruları anında yeniden hesaplanır.

Panel motorunda (SIM_ENGINE=panel) bir bölgedeki bütün ürünlere aynı kişiler bakar. Kişi içi normalizasyon,
erişim (TURF) ve kanibalizasyon bu ortak panele dayanır. Mock/MiroFish motorunda kişi bazlı puan yoksa bu
göstergeler talep skorundan kaba olarak hesaplanır ya da boş bırakılır ve bu not edilir.
"""
import math
import random
import statistics
from typing import Dict, List, Optional, Set, Tuple

from ..allocation import DEMAND_SCENARIOS, STOP_P, p_sells
from .importer import norm
from .models import (Action, CannibalPair, CategorySummary, Collection, CollectionResult, CollectionSummary,
                     ItemRegion, ItemResult, Metric, ReachPoint, WhatIf)

ENTHUSIAST = 70          # ilgi puanı bu ve üstü: "hevesli" (prompttaki ölçek: hevesli 70-95)
CANNIBAL_OVERLAP = 0.6   # hevesli kişilerin örtüşmesi (küçük kümeye göre)
CANNIBAL_PRICE = 0.25    # fiyatlar birbirinin ±%25'i içinde
BOOTSTRAP = 200
REVERSE_LOGISTICS_PCT = 8.0

Person = Tuple[str, int]  # (bölge, kişi no)


def _pct(x: float) -> float:
    return round(100 * x, 1)


def _item_regions(resp: dict, planned_usd: Optional[float]) -> Tuple[List[ItemRegion], Dict[Person, float], dict]:
    regions, interests, basis = [], {}, None
    for rb in resp.get("regional_breakdown", []):
        r = rb["region"]
        vw = rb["van_westendorp"]
        lo, hi = float(vw["acceptable_range_low"]), float(vw["acceptable_range_high"])
        fit = None
        if planned_usd:
            fit = "altında" if planned_usd < lo else "üstünde" if planned_usd > hi else "içinde"
        own = {}
        for a in rb.get("raw_answers") or []:
            if a.get("interest") is not None:
                own[(r, int(a["agent"]))] = float(a["interest"])
        interests.update(own)
        alloc = rb.get("allocation") or {}
        regions.append(ItemRegion(
            region=r, demand=int(rb["demand_score_100"]),
            enthusiast_pct=_pct(sum(v >= ENTHUSIAST for v in own.values()) / len(own)) if own else None,
            optimal_price=float(rb["optimal_sale_price"]), range_low=lo, range_high=hi,
            margin_pct=float(rb["estimated_margin_percentage"]), return_pct=float(rb["returns"]["rate_pct"]),
            demand_units=int(alloc.get("demand_units") or 0), price_fit=fit,
            objections=list(rb.get("key_objections") or [])[:3],
            confidence=(rb.get("confidence") or {}).get("level", "")))
        basis = basis or rb.get("data_basis")
    return regions, interests, basis


def _relative(per_item: Dict[str, Dict[Person, float]]) -> Tuple[Dict[str, float], Dict[Person, Dict[str, float]]]:
    """Kişi içi normalizasyon: her kişinin puanı kendi ortalaması ve dağılımına göre z-puanına çevrilir."""
    by_person: Dict[Person, Dict[str, float]] = {}
    for sku, d in per_item.items():
        for p, v in d.items():
            by_person.setdefault(p, {})[sku] = v
    z: Dict[Person, Dict[str, float]] = {}
    for p, d in by_person.items():
        if len(d) < 2:
            continue
        m = statistics.fmean(d.values())
        sd = statistics.pstdev(d.values()) or 1.0
        z[p] = {s: (v - m) / sd for s, v in d.items()}
    rel = {}
    for sku in per_item:
        vals = [d[sku] for d in z.values() if sku in d]
        rel[sku] = statistics.fmean(vals) if vals else 0.0
    return rel, z


def _ranks(scores: Dict[str, float]) -> Dict[str, int]:
    order = sorted(scores, key=lambda s: (-scores[s], s))
    return {s: i + 1 for i, s in enumerate(order)}


def _bootstrap_ranks(z: Dict[Person, Dict[str, float]], skus: List[str]) -> Dict[str, Tuple[int, int]]:
    """Kişiler yeniden örneklenerek sıranın ne kadar oynadığı: %10-%90 aralığı."""
    persons = list(z)
    if len(persons) < 3:
        return {}
    rng = random.Random(7)
    samples: Dict[str, List[int]] = {s: [] for s in skus}
    for _ in range(BOOTSTRAP):
        pick = [persons[rng.randrange(len(persons))] for _ in persons]
        sc = {}
        for s in skus:
            vals = [z[p][s] for p in pick if s in z[p]]
            sc[s] = statistics.fmean(vals) if vals else 0.0
        for s, r in _ranks(sc).items():
            samples[s].append(r)
    out = {}
    for s, rs in samples.items():
        rs.sort()
        out[s] = (rs[int(0.1 * (len(rs) - 1))], rs[int(math.ceil(0.9 * (len(rs) - 1)))])
    return out


def _expected_sold(demand: float, q: int) -> float:
    return sum(w * min(demand * m, q) for m, w in DEMAND_SCENARIOS)


def allocate_items(signals: List[dict], budget: float, objective: str) -> Dict[Tuple[str, str], int]:
    """Bütçeyi ürün x bölgeye dağıtır (mevcut satış hızı algoritmasının ürün maliyeti farklı sürümü).

    Her adımda bir parti, bir sonraki birimi en olası satılacak (balanced) ya da birim maliyet başına en kârlı
    (profit) ürün x bölgeye verilir. Son birimin satılma olasılığı eşiğin altına düşünce o hücre durur; bütçe
    talebi aşıyorsa kalan bütçe harcanmaz. Kural varsayımıdır: talep senaryoları ve eşik sabittir.
    """
    q = {(s["sku"], s["region"]): 0 for s in signals}
    live = [s for s in signals if s["demand"] > 0 and s["net"] > s["cost"] > 0]
    if not live or budget <= 0:
        return q
    mean_cost = statistics.fmean(s["cost"] for s in live)
    step = max(1, int(budget / mean_cost) // 1500)
    stop = STOP_P[objective]
    max_net = max(s["net"] / s["cost"] for s in live)
    left = budget
    dead: Set[Tuple[str, str]] = set()

    def score(s):
        k = (s["sku"], s["region"])
        p = p_sells(s["demand"], q[k])
        profit = (p * s["net"] - s["cost"]) / s["cost"]
        if p <= 0 or p < stop or profit <= 0:
            return None
        if objective == "profit":
            return profit
        if objective == "balanced":
            return p - 1e-3 * q[k] / s["demand"] + 1e-9 * profit
        return 0.5 * p + 0.5 * profit / max_net - 1e-3 * q[k] / s["demand"]

    while True:
        best, bs = None, None
        for s in live:
            k = (s["sku"], s["region"])
            if k in dead:
                continue
            sc = score(s)
            if sc is None:
                dead.add(k)
                continue
            if bs is None or sc > bs:
                best, bs = s, sc
        if best is None:
            break
        n = min(step, int(left // best["cost"]))
        if n < 1:
            dead.add((best["sku"], best["region"]))
            continue
        q[(best["sku"], best["region"])] += n
        left -= n * best["cost"]
    return q


def summarize(col: Collection, results: Dict[str, dict], fx_rate: float, whatif: Optional[WhatIf] = None,
              objective: str = "balanced") -> CollectionResult:
    w = whatif or WhatIf()
    objective = w.allocation_objective or objective
    cur = col.meta.currency
    to_usd = (lambda v: v / fx_rate) if cur == "TRY" else (lambda v: v)
    excluded = set(w.exclude)
    items = [it for it in col.items if it.sku not in excluded]
    evaluated = [it for it in items if it.sku in results and results[it.sku].get("response")]
    notes: List[str] = []

    per_item_regions: Dict[str, List[ItemRegion]] = {}
    per_item_int: Dict[str, Dict[Person, float]] = {}
    data_basis = None
    brand = None
    for it in evaluated:
        planned = w.planned_prices.get(it.sku, it.planned_price)
        regs, ints, b = _item_regions(results[it.sku]["response"], to_usd(planned) if planned else None)
        per_item_regions[it.sku], per_item_int[it.sku] = regs, ints
        data_basis = data_basis or b
        brand = brand or results[it.sku]["response"].get("brand_profile")

    persons: Set[Person] = {p for d in per_item_int.values() for p in d}
    shared = bool(persons) and all(r.get("panel_seed") for r in (results[i.sku] for i in evaluated))
    have_panel = len(persons) > 0 and len(evaluated) >= 2
    skus = [it.sku for it in evaluated]

    appeal = {s: statistics.fmean(r.demand for r in per_item_regions[s]) if per_item_regions[s] else 0.0 for s in skus}
    if have_panel:
        rel, z = _relative(per_item_int)
        intervals = _bootstrap_ranks(z, skus)
        rel_basis, rel_how = "ajan", "Aynı kişilerin bu ürüne verdiği puanın, o kişinin bütün ürünlere verdiği puanların ortalamasından farkı (standart sapma cinsinden). Kişinin cömertliği ya da titizliği elenir."
    else:
        m = statistics.fmean(appeal.values()) if appeal else 0
        sd = statistics.pstdev(appeal.values()) if len(appeal) > 1 else 0
        rel = {s: (appeal[s] - m) / (sd or 1) for s in skus}
        intervals = {}
        rel_basis, rel_how = "ajan", "Talep skorunun koleksiyon ortalamasından farkı. Kişi bazında puan yok (panel motoru kullanılmadı); kişi içi normalizasyon yapılamadı."
        if evaluated:
            notes.append("Kişi bazlı ilgi puanı yok (panel motoru kapalı); erişim ve kanibalizasyon hesaplanmadı, sıralama talep skorundan.")
    if have_panel and not shared:
        notes.append("Ürünler farklı kişi panelleriyle değerlendirilmiş görünüyor; kişi içi karşılaştırmalar zayıflar.")
    ranks = _ranks(rel)

    # hevesli kişi kümeleri
    ent: Dict[str, Set[Person]] = {s: {p for p, v in per_item_int.get(s, {}).items() if v >= ENTHUSIAST} for s in skus}
    ent_pct = {s: (len(ent[s]) / len(per_item_int[s]) if per_item_int.get(s) else None) for s in skus}
    disp = {s: (statistics.pstdev(per_item_int[s].values()) if len(per_item_int.get(s, {})) > 1 else None) for s in skus}

    # roller (kural varsayımı)
    n = len(skus)
    # eşit puanlı ürünler aynı yüzdelik dilimi alır (sıralama sırası rolü belirlemesin)
    rounded = {s: round(rel[s], 3) for s in skus}
    asc = sorted(rounded.values())
    pctl = {s: ((asc.index(v) + (len(asc) - 1 - asc[::-1].index(v))) / 2 / (n - 1) if n > 1 else 0.5)
            for s, v in rounded.items()}
    flat = n >= 3 and (max(rel.values()) - min(rel.values())) < 0.1
    ent_vals = [v for v in ent_pct.values() if v is not None]
    ent_med = statistics.median(ent_vals) if ent_vals else None
    disp_vals = [v for v in disp.values() if v is not None]
    disp_med = statistics.median(disp_vals) if disp_vals else None
    # fiyat sorunu koleksiyonun çoğundaysa (genel fiyat seviyesi) ürünü tek başına riskli saymak için kullanılmaz
    over_items = [s for s in skus if (f := [r.price_fit for r in per_item_regions[s] if r.price_fit])
                  and sum(x == "üstünde" for x in f) > len(f) / 2]
    price_wide = len(over_items) > n / 2
    roles, why = {}, {}
    for s in skus:
        regs = per_item_regions[s]
        fits = [r.price_fit for r in regs if r.price_fit]
        over = fits and sum(f == "üstünde" for f in fits) > len(fits) / 2
        if n < 3:
            roles[s], why[s] = "belirsiz", "Rol için en az 3 değerlendirilmiş ürün gerekli."
        elif flat:
            roles[s], why[s] = "belirsiz", "Panel ürünleri birbirinden ayırt etmedi (puanlar neredeyse aynı); rol verilemez."
        elif pctl[s] <= 0.2 or appeal[s] < 40:
            roles[s], why[s] = "riskli", f"Koleksiyonun en alt %20'sinde (sıra {ranks[s]}/{n})" + (" ve talep skoru 40'ın altında" if appeal[s] < 40 else "")
        elif over and pctl[s] < 0.5 and not price_wide:
            roles[s], why[s] = "riskli", "Planlanan fiyat çoğu bölgede panelin kabul aralığının üstünde ve ilgi ortalamanın altında"
        elif pctl[s] >= 0.8 and (ent_med is None or (ent_pct[s] or 0) >= ent_med):
            roles[s], why[s] = "hero", f"Koleksiyonun en üst %20'sinde (sıra {ranks[s]}/{n})" + (f", hevesli kişi oranı %{_pct(ent_pct[s] or 0):g}" if ent_pct[s] is not None else "")
        elif pctl[s] >= 0.4 and (disp_med is None or (disp[s] or 0) <= disp_med):
            roles[s], why[s] = "çekirdek", "İlgi ortalamanın üstünde ve kişiler arasında görüş ayrılığı düşük: geniş kitleye güvenli"
        else:
            roles[s], why[s] = "destek", "İlgi orta seviyede; koleksiyonu tamamlayan ürün"

    # erişim (TURF): en az bir üründe hevesli olan kişi oranı
    reach_curve: List[ReachPoint] = []
    reach = Metric(value=None, basis="ajan", how="Panel kişi bazlı puan vermedi.")
    reach_by_region: Dict[str, float] = {}
    if have_panel and persons:
        covered: Set[Person] = set()
        left = set(skus)
        k = 0
        while left:
            best = max(sorted(left), key=lambda s: len(ent[s] - covered))
            add = len(ent[best] - covered)
            if add == 0:
                break
            covered |= ent[best]
            k += 1
            reach_curve.append(ReachPoint(k=k, sku=best, name=next(i.name for i in evaluated if i.sku == best),
                                          reach_pct=_pct(len(covered) / len(persons)), added_pct=_pct(add / len(persons))))
            left.discard(best)
        allent = set().union(*ent.values()) if ent else set()
        reach = Metric(value=_pct(len(allent) / len(persons)), basis="ajan",
                       how=f"Paneldeki {len(persons)} kişiden en az bir ürüne {ENTHUSIAST}+ ilgi puanı veren kişilerin oranı.")
        for r in sorted({p[0] for p in persons}):
            pr = {p for p in persons if p[0] == r}
            reach_by_region[r] = _pct(len(allent & pr) / len(pr)) if pr else 0.0

    # kanibalizasyon adayları
    price_of = {}
    for it in evaluated:
        planned = w.planned_prices.get(it.sku, it.planned_price)
        regs = per_item_regions[it.sku]
        price_of[it.sku] = to_usd(planned) if planned else (statistics.fmean(r.optimal_price for r in regs) if regs else 0)
    pairs: List[CannibalPair] = []
    if have_panel:
        for i, a in enumerate(evaluated):
            for b in evaluated[i + 1:]:
                if not a.category or norm(a.category) != norm(b.category):
                    continue
                ea, eb = ent[a.sku], ent[b.sku]
                if len(ea) < 2 or len(eb) < 2:
                    continue
                ov = len(ea & eb) / min(len(ea), len(eb))
                pa, pb = price_of[a.sku], price_of[b.sku]
                close = pa > 0 and pb > 0 and abs(pa - pb) / max(pa, pb) <= CANNIBAL_PRICE
                if ov >= CANNIBAL_OVERLAP and close:
                    pairs.append(CannibalPair(a=a.sku, b=b.sku, category=a.category, overlap_pct=_pct(ov),
                                              why=f"İkisini de beğenen kişilerin örtüşmesi %{_pct(ov):g}, aynı kategori ve fiyatlar birbirine yakın"))
        pairs.sort(key=lambda p: -p.overlap_pct)

    # bütçe dağıtımı (kural varsayımı)
    budget_total = w.total_budget if w.total_budget is not None else col.meta.total_budget
    budget_usd = to_usd(budget_total) if budget_total else None
    signals = []
    for it in evaluated:
        if not it.unit_cost:
            continue
        cost = to_usd(it.unit_cost)
        for r in per_item_regions[it.sku]:
            price = to_usd(w.planned_prices.get(it.sku, it.planned_price)) if (w.planned_prices.get(it.sku, it.planned_price)) else r.optimal_price
            net = price * (1 - r.return_pct / 100 * (1 + REVERSE_LOGISTICS_PCT / 100))
            signals.append({"sku": it.sku, "region": r.region, "demand": r.demand_units, "net": net, "cost": cost})
    alloc = allocate_items(signals, budget_usd or 0, objective) if budget_usd else {}
    if not budget_usd:
        notes.append("Toplam bütçe girilmedi; bütçe dağıtımı yapılmadı.")
    qty_item: Dict[str, Dict[str, int]] = {}
    for (s, r), qv in alloc.items():
        qty_item.setdefault(s, {})[r] = qv
    sig_by = {(s["sku"], s["region"]): s for s in signals}
    exp_units = sum(_expected_sold(sig_by[k]["demand"], qv) for k, qv in alloc.items())
    used = sum(qv * sig_by[k]["cost"] for k, qv in alloc.items())

    # ürün sonuçları
    out_items: List[ItemResult] = []
    for it in items:
        res = results.get(it.sku)
        failed = [f["region"] for f in ((res or {}).get("response") or {}).get("failed_regions", [])]
        planned = w.planned_prices.get(it.sku, it.planned_price)
        if it.sku not in per_item_regions:
            out_items.append(ItemResult(
                sku=it.sku, name=it.name, category=it.category, image=it.images[0] if it.images else None,
                unit_cost_usd=to_usd(it.unit_cost) if it.unit_cost else None, planned_price_usd=to_usd(planned) if planned else None,
                declared_role=it.declared_role, regions=[], appeal=Metric(value=None, basis="ajan"),
                relative=Metric(value=None, basis="ajan"), rank=Metric(value=None, basis="ajan"),
                enthusiast_pct=Metric(value=None, basis="ajan"), role="belirsiz",
                role_why=(res or {}).get("error") or "Henüz değerlendirilmedi",
                recommended_qty=Metric(value=None, basis="kural varsayımı"), planned_qty=it.planned_qty,
                flags=["değerlendirilmedi"] if not res else ["hata"], failed_regions=failed))
            continue
        s = it.sku
        regs = per_item_regions[s]
        flags = []
        fits = [r.price_fit for r in regs if r.price_fit]
        if fits and sum(f == "üstünde" for f in fits) > len(fits) / 2:
            flags.append("fiyat aralığın üstünde")
        elif fits and sum(f == "altında" for f in fits) > len(fits) / 2:
            flags.append("fiyat aralığın altında")
        if any(s in (p.a, p.b) for p in pairs):
            flags.append("kanibalizasyon adayı")
        if not it.unit_cost:
            flags.append("maliyet yok")
        tq = sum(qty_item.get(s, {}).values())
        if it.moq and 0 < tq < it.moq:
            flags.append(f"MOQ altı ({tq} < {it.moq})")
        if it.declared_role == "hero" and roles[s] in ("riskli", "destek"):
            flags.append("hedef rol tutmadı")
        if failed:
            flags.append("bazı bölgeler hesaplanamadı")
        lo_hi = intervals.get(s)
        out_items.append(ItemResult(
            sku=s, name=it.name, category=it.category, image=it.images[0] if it.images else None,
            unit_cost_usd=to_usd(it.unit_cost) if it.unit_cost else None,
            planned_price_usd=to_usd(planned) if planned else None, declared_role=it.declared_role, regions=regs,
            appeal=Metric(value=round(appeal[s], 1), basis="ajan", how="Bölgelerdeki talep skorlarının ortalaması (0-100)."),
            relative=Metric(value=round(rel[s], 2), basis=rel_basis, how=rel_how),
            rank=Metric(value=ranks[s], low=lo_hi[0] if lo_hi else None, high=lo_hi[1] if lo_hi else None, basis="ajan",
                        how="Koleksiyon içi sıra. Aralık, panel kişileri yeniden örneklenince sıranın %80 olasılıkla düştüğü bant." if lo_hi else "Koleksiyon içi sıra."),
            enthusiast_pct=Metric(value=_pct(ent_pct[s]) if ent_pct[s] is not None else None, basis="ajan",
                                  how=f"Ürüne {ENTHUSIAST}+ ilgi puanı veren kişi oranı."),
            role=roles[s], role_why=why[s],
            recommended_qty=Metric(value=tq if it.unit_cost and budget_usd else None, basis="kural varsayımı",
                                   how="Koleksiyon bütçesinin satış hızına göre dağıtımı: talep panelden, kitle ve dönüşüm varsayımdan."),
            qty_by_region=qty_item.get(s, {}), planned_qty=it.planned_qty, flags=flags, failed_regions=failed))

    # kategori özeti
    cats: Dict[str, List[ItemResult]] = {}
    for r in out_items:
        if r.regions:
            cats.setdefault(r.category or "(kategorisiz)", []).append(r)
    categories = []
    for c, rs in sorted(cats.items()):
        prices = [r.planned_price_usd for r in rs if r.planned_price_usd]
        fits = [x.price_fit for r in rs for x in r.regions if x.price_fit]
        categories.append(CategorySummary(
            category=c, count=len(rs), roles={k: sum(r.role == k for r in rs) for k in ("hero", "çekirdek", "destek", "riskli")},
            price_min=min(prices) if prices else None, price_max=max(prices) if prices else None,
            mean_appeal=round(statistics.fmean(r.appeal.value or 0 for r in rs), 1),
            in_zone=sum(f == "içinde" for f in fits), out_zone=sum(f != "içinde" for f in fits)))

    # öneriler
    actions: List[Action] = []
    in_curve = {p.sku for p in reach_curve}
    for r in out_items:
        if r.role == "riskli" and (not have_panel or r.sku not in in_curve):
            actions.append(Action(kind="çıkar", skus=[r.sku], basis="kural varsayımı",
                                  text=f"{r.name}: {r.role_why.lower()}" + ("; panelde ona özgü yeni bir kişiye ulaşmıyor" if have_panel else "") + ". Çıkarmayı ya da tasarımı gözden geçirmeyi düşünün."))
    for p in pairs[:5]:
        na = next(i.name for i in out_items if i.sku == p.a)
        nb = next(i.name for i in out_items if i.sku == p.b)
        actions.append(Action(kind="kanibalizasyon", skus=[p.a, p.b], basis="ajan",
                              text=f"{na} ile {nb} aynı müşteriyi paylaşıyor (örtüşme %{p.overlap_pct:g}). Birini çıkarmayı ya da fiyat/renkle ayrıştırmayı düşünün."))
    over_p = [r for r in out_items if "fiyat aralığın üstünde" in r.flags]
    under_p = [r for r in out_items if "fiyat aralığın altında" in r.flags]
    if len(over_p) > 3:
        actions.append(Action(kind="fiyat", skus=[r.sku for r in over_p], basis="ajan",
                              text=f"{len(over_p)} üründe planlanan fiyat çoğu bölgede panelin kabul aralığının üstünde "
                                   f"({', '.join(r.name for r in over_p[:6])}{'…' if len(over_p) > 6 else ''}). "
                                   "Koleksiyon geneli bir fiyat seviyesi sorunu olabilir; Fiyat sekmesinde ürün ürün bakın."))
    else:
        for r in over_p:
            bad = [x.region for x in r.regions if x.price_fit == "üstünde"]
            actions.append(Action(kind="fiyat", skus=[r.sku], basis="ajan",
                                  text=f"{r.name}: planlanan fiyat {', '.join(bad)} bölgesinde panelin kabul aralığının üstünde."))
    if under_p:
        actions.append(Action(kind="fiyat", skus=[r.sku for r in under_p], basis="ajan",
                              text=f"Planlanan fiyatı panelin kabul aralığının altında kalan ürünler: {', '.join(r.name for r in under_p[:6])}"
                                   f"{'…' if len(under_p) > 6 else ''}. Fiyat artırma alanı olabilir."))
    for r in out_items:
        if r.role == "hero" and r.planned_qty and r.recommended_qty.value and r.planned_qty < 0.8 * r.recommended_qty.value:
            actions.append(Action(kind="derinlik", skus=[r.sku], basis="kural varsayımı",
                                  text=f"{r.name}: hero ürün; planlanan adet ({r.planned_qty}) önerilenin ({int(r.recommended_qty.value)}) belirgin altında, stok erken bitebilir."))
    no_cost = [r.sku for r in out_items if "maliyet yok" in r.flags]
    if no_cost:
        actions.append(Action(kind="veri", skus=no_cost, basis="kullanıcı girdisi",
                              text=f"{len(no_cost)} üründe birim maliyet yok; bütçe dağıtımına girmediler."))
    for c in categories:
        if c.count >= 3 and c.roles.get("hero", 0) == 0 and c.mean_appeal < statistics.fmean(appeal.values() or [0]):
            actions.append(Action(kind="eksik", basis="kural varsayımı",
                                  text=f"{c.category} kategorisinde öne çıkan (hero) ürün yok ve ilgi koleksiyon ortalamasının altında."))

    if flat:
        notes.append("Panel ürünleri birbirinden ayırt etmedi: ürün puanları neredeyse aynı. Sahte LLM ya da çok küçük bir "
                     "model kullanıldıysa beklenir; sıralama ve roller bu koşuda anlamlı değildir.")
    notes += [
        "Panel bir tüketici anketi değil, dil modelinin persona ve güncel bağlamla yaptığı tahmindir; en güvenilir kullanımı koleksiyon içi göreli karşılaştırmadır.",
        "Roller, erişim ve kanibalizasyon eşikleri kural varsayımıdır (hevesli = 70+ ilgi; örtüşme %60+, fiyat farkı %25 içinde).",
        "Önerilen adetler ERP ile kalibre edilene kadar varsayımdır; planlanan fiyat değişikliği yalnızca fiyat uyumunu ve gelir hesabını değiştirir, panel cevaplarını değiştirmez.",
    ]
    summary = CollectionSummary(
        n_items=len(items), n_evaluated=len(evaluated), n_failed=sum(1 for i in items if i.sku in results and not results[i.sku].get("response")),
        reach=reach, reach_by_region=reach_by_region, reach_curve=reach_curve,
        roles={k: sum(r.role == k for r in out_items if r.regions) for k in ("hero", "çekirdek", "destek", "riskli", "belirsiz")},
        mean_appeal=Metric(value=round(statistics.fmean(appeal.values()), 1) if appeal else None, basis="ajan",
                           how="Ürünlerin talep skoru ortalaması."),
        categories=categories, cannibal_pairs=pairs, budget_total_usd=round(budget_usd, 2) if budget_usd else None,
        budget_used_usd=round(used, 2), total_qty=sum(alloc.values()),
        expected_units=Metric(value=round(exp_units), basis="kural varsayımı",
                              how="120 günde beklenen satış (orta senaryo), önerilen adetlerle sınırlı."),
        actions=actions)
    regions = sorted({r.region for rs in per_item_regions.values() for r in rs}) or list(col.meta.target_regions)
    return CollectionResult(collection_id=col.id, name=col.meta.name, currency=cur, fx_rate=fx_rate, regions=regions,
                            items=out_items, summary=summary, notes=notes, data_basis=data_basis, panel_shared=shared,
                            brand_profile=brand)
