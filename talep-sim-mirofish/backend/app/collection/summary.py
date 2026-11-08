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

from .. import brand as brandlib
from ..allocation import DEMAND_SCENARIOS, STOP_P, p_sells
from ..models import BrandProfile
from .importer import norm
from .models import (Action, Reason, BrandEffect, PairCount, PositionBias, ShowcaseItem, ShowcaseSummary, CannibalPair, CategorySummary, Collection, CollectionResult, CollectionSummary,
                     ItemRegion, ItemResult, Metric, ReachPoint, WhatIf)

ENTHUSIAST = 70          # ilgi puanı bu ve üstü: "hevesli" (prompttaki ölçek: hevesli 70-95)
CANNIBAL_OVERLAP = 0.6   # hevesli kişilerin örtüşmesi (küçük kümeye göre)
CANNIBAL_PRICE = 0.25    # fiyatlar birbirinin ±%25'i içinde
BOOTSTRAP = 200
REVERSE_LOGISTICS_PCT = 8.0

# Üretim kararı eşikleri (kural varsayımı; ERP ile kalibre edilene kadar sabit)
DEMAND_DROP = 35         # talep skoru (0-100) bunun altındaysa: üretme
DEMAND_REDUCE = 50       # bunun altındaysa: azalt
MARGIN_DROP = 15.0       # önerilen fiyatta iade sonrası net marj (%) bunun altındaysa: üretme
MARGIN_REDUCE = 30.0     # bunun altındaysa: azalt
REDUCE_FACTOR = 0.6      # "azalt" kararında bütçe dağıtımına giren talep oranı

Person = Tuple[str, int]  # (bölge, kişi no)


def _pct(x: float) -> float:
    return round(100 * x, 1)


def _net_margin(price: float, return_pct: float, cost: Optional[float]) -> Optional[float]:
    """İade (ve ters lojistik) düşüldükten sonra satış başına net marj yüzdesi. İade oranı kural varsayımıdır."""
    if not cost or not price:
        return None
    net = price * (1 - return_pct / 100 * (1 + REVERSE_LOGISTICS_PCT / 100))
    return round(100 * (net - cost) / price, 1)


def _item_regions(resp: dict, planned_usd: Optional[float], cost_usd: Optional[float] = None
                  ) -> Tuple[List[ItemRegion], Dict[Person, float], dict]:
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
        ret = rb.get("returns") or {}
        opt = float(rb["optimal_sale_price"])
        if planned_usd or ret.get("net_margin_pct") is None:
            nm = _net_margin(planned_usd or opt, float(ret.get("rate_pct") or 0), cost_usd)
        else:
            nm = float(ret["net_margin_pct"])
        zones = [{"key": z.get("key"), "label": z.get("label"), "low": float(z["low"]),
                  "high": float(z["high"]) if z.get("high") is not None else None} for z in vw.get("zones") or []]
        regions.append(ItemRegion(
            region=r, demand=int(rb["demand_score_100"]),
            enthusiast_pct=_pct(sum(v >= ENTHUSIAST for v in own.values()) / len(own)) if own else None,
            optimal_price=float(rb["optimal_sale_price"]), range_low=lo, range_high=hi,
            margin_pct=float(rb["estimated_margin_percentage"]), return_pct=float(rb["returns"]["rate_pct"]),
            demand_units=int(alloc.get("demand_units") or 0), price_fit=fit,
            ipp=float(vw["indifference_price_point"]) if vw.get("indifference_price_point") is not None else None,
            zones=zones, net_margin_pct=nm,
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


def brand_effect(used: Optional[dict], col: Collection, regions: List[str]) -> Optional[BrandEffect]:
    """Kullanılan marka profilinin hesaplara nasıl girdiği. Profil yoksa nötr varsayım olduğu söylenir."""
    if not used:
        return None
    b = BrandProfile(**used)
    neutral = brandlib.NEUTRAL_MULTIPLE
    level = round(100 * (b.price_multiple / neutral - 1), 1)
    dp = {r: round(sum(brandlib.demand_points(b, r)), 1) for r in regions}
    basis = "kullanıcı girdisi" if b.edited else "LLM tahmini" if b.source == "llm_knowledge" else \
        "kullanıcı girdisi" if b.source == "user_notes" else "kural varsayımı"
    lines = [
        f"Fiyat merdiveni ve panele söylenen 'bu marka genelde şu fiyata satar' bilgisi maliyet × {b.price_multiple:g} "
        f"üzerinden kuruldu. Marka yokken kullanılan × {neutral:g}'e göre fiyat seviyesi %{level:+g}.",
        f"Panel her üründe markayı '{brandlib.TIER_LABEL[b.price_tier]}' segment ve bölgedeki bilinirliğiyle "
        f"({', '.join(f'{r} {brandlib.region_strength(b, r)}/100' for r in regions)}) görerek cevap verdi; marka değeri "
        "kişilerin kabul ettiği fiyat aralığını doğrudan etkiler.",
        f"Fiyat duyarlılığı {b.price_sensitivity:.2f} ve çekim gücü {b.brand_pull}/100: fiyat aralığının genişliği ve "
        "panel yeterli fiyat cevabı vermezse kullanılan yedek eşikler bunlardan hesaplanır (kural varsayımı).",
    ]
    warn = b.warning
    cur = col.meta.brand_profile
    if (cur is not None and cur.model_dump() != b.model_dump()) or (cur is None and col.meta.brand and col.meta.brand != b.name):
        warn = ("Ekrandaki marka bilgisi bu sonuçlar üretildikten sonra değişti. Yeni marka profilinin etkisini görmek için "
                "paneli yeniden çalıştırın (değişen ürünler yeniden sorulur).")
    return BrandEffect(name=b.name, tier=brandlib.TIER_LABEL[b.price_tier], price_multiple=b.price_multiple,
                       neutral_multiple=neutral, price_level_pct=level, brand_pull=b.brand_pull,
                       price_sensitivity=b.price_sensitivity,
                       regional_strength={r: brandlib.region_strength(b, r) for r in regions}, demand_points=dp,
                       source=b.source, confidence=b.confidence, edited=b.edited, basis=basis, lines=lines, warning=warn)


def summarize_showcase(records: Dict[str, list], skus: List[str], single_ranks: Dict[str, int]
                       ) -> Tuple[Dict[str, ShowcaseItem], Optional[ShowcaseSummary]]:
    """Vitrin turu cevaplarından ürün seçilme skoru, kombin ve ikame çiftleri, sıra etkisi kontrolü (ajan)."""
    keep = set(skus)
    recs = [r for rs in records.values() for r in rs]
    ok = [r for r in recs if r.get("answer")]
    if not ok:
        return {}, None
    shown = {s: 0 for s in skus}
    best = {s: 0 for s in skus}
    worst = {s: 0 for s in skus}
    together: Dict[Tuple[str, str], int] = {}
    subs: Dict[Tuple[str, str], int] = {}
    co: Dict[Tuple[str, str], int] = {}
    pos_pick = {"ilk": 0.0, "orta": 0.0, "son": 0.0}
    pos_exp = {"ilk": 0.0, "orta": 0.0, "son": 0.0}
    n_buy, comments, block = [], [], 0
    for r in ok:
        order, letters, a = r["order"], r["letters"], r["answer"]
        block = max(block, len(order))
        for x in order:
            if x in keep:
                shown[x] += 1
        for i, x in enumerate(order):
            for y in order[i + 1:]:
                k = tuple(sorted((x, y)))
                co[k] = co.get(k, 0) + 1
        L = len(order)
        picks = [letters[c] for c in a["best"] if c in letters]
        for c in picks:
            if c in keep:
                best[c] += 1
            i = order.index(c)
            pos_pick["ilk" if i == 0 else "son" if i == L - 1 else "orta"] += 1
        if picks:
            pos_exp["ilk"] += len(picks) / L
            pos_exp["son"] += len(picks) / L
            pos_exp["orta"] += len(picks) * (L - 2) / L
        for c in a["worst"]:
            x = letters.get(c)
            if x in keep:
                worst[x] += 1
        for dst, key in ((together, "together"), (subs, "substitutes")):
            for p in a[key]:
                x, y = letters.get(p[0]), letters.get(p[1])
                if x in keep and y in keep:
                    k = tuple(sorted((x, y)))
                    dst[k] = dst.get(k, 0) + 1
        n_buy.append(a["n_buy"])
        if a.get("comment") and len(comments) < 6 and a["comment"] not in comments:
            comments.append(a["comment"])
    score = {s: ((best[s] - worst[s]) / shown[s]) if shown[s] else 0.0 for s in skus}
    order_s = sorted([s for s in skus if shown[s]], key=lambda s: (-score[s], s))
    rank = {s: i + 1 for i, s in enumerate(order_s)}
    tog_count = {s: sum(v for k, v in together.items() if s in k) for s in skus}
    items = {s: ShowcaseItem(shown=shown[s], best=best[s], worst=worst[s], score=round(score[s], 3),
                             best_pct=_pct(best[s] / shown[s]), worst_pct=_pct(worst[s] / shown[s]), rank=rank[s],
                             single_rank=single_ranks.get(s), together=tog_count[s])
             for s in order_s}

    def pairs(d):
        out = [PairCount(a=k[0], b=k[1], count=v, pct=_pct(v / co[k]) if co.get(k) else 0.0) for k, v in d.items() if v >= 2]
        return sorted(out, key=lambda p: (-p.count, -p.pct))[:10]

    total = sum(pos_pick.values())
    position = [PositionBias(position=k, pick_pct=_pct(pos_pick[k] / total) if total else 0.0,
                             expected_pct=_pct(pos_exp[k] / total) if total else 0.0) for k in ("ilk", "orta", "son")]
    warn = None
    if total >= 20:
        heavy = [p.position for p in position if p.position != "orta" and p.expected_pct and p.pick_pct > 1.5 * p.expected_pct]
        if heavy:
            warn = (f"Panel listenin {' ve '.join(heavy)} sırasındaki ürünleri beklenenden belirgin fazla seçti; vitrin "
                    "sonuçlarında sıra etkisi olabilir. Sıralar kişiden kişiye karıştırıldığı için etki ürünlere dağılır "
                    "ama küçük modelde güveni düşürür.")
    elif total:
        warn = "Sıra etkisini ölçmek için seçim sayısı az (20'nin altında); kontrol güvenilir değil."
    agree = None
    common = [s for s in order_s if s in single_ranks]
    if len(common) >= 4:
        a_r = {s: i for i, s in enumerate(sorted(common, key=lambda s: single_ranks[s]))}
        b_r = {s: i for i, s in enumerate(sorted(common, key=lambda s: rank[s]))}
        n = len(common)
        d2 = sum((a_r[s] - b_r[s]) ** 2 for s in common)
        agree = round(100 * (1 - 6 * d2 / (n * (n * n - 1))), 0)
    summ = ShowcaseSummary(
        n_answers=len(ok), n_failed=len(recs) - len(ok), n_persons=len({(r["region"], r["person"]) for r in ok}),
        block_size=block, by_region={reg: sum(1 for r in rs if r.get("answer")) for reg, rs in records.items()},
        together_pairs=pairs(together), substitute_pairs=pairs(subs), position=position, position_warning=warn,
        mean_n_buy=round(statistics.fmean(n_buy), 2) if n_buy else None, comments=comments, agreement_pct=agree)
    return items, summ


def summarize(col: Collection, results: Dict[str, dict], fx_rate: float, whatif: Optional[WhatIf] = None,
              objective: str = "balanced", showcase: Optional[Dict[str, list]] = None) -> CollectionResult:
    w = whatif or WhatIf()
    objective = w.allocation_objective or objective
    cur = col.meta.currency
    to_usd = (lambda v: v / fx_rate) if cur == "TRY" else (lambda v: v)
    excluded = set(w.exclude)
    indep = col.meta.kind == "bagimsiz"
    items = [it for it in col.items if it.sku not in excluded]
    evaluated = [it for it in items if it.sku in results and results[it.sku].get("response")]
    notes: List[str] = []

    per_item_regions: Dict[str, List[ItemRegion]] = {}
    per_item_int: Dict[str, Dict[Person, float]] = {}
    data_basis = None
    brand = None
    for it in evaluated:
        planned = w.planned_prices.get(it.sku, it.planned_price)
        regs, ints, b = _item_regions(results[it.sku]["response"], to_usd(planned) if planned else None,
                                      to_usd(it.unit_cost) if it.unit_cost else None)
        per_item_regions[it.sku], per_item_int[it.sku] = regs, ints
        data_basis = data_basis or b
        brand = brand or results[it.sku]["response"].get("brand_profile")

    persons: Set[Person] = {p for d in per_item_int.values() for p in d}
    shared = not indep and bool(persons) and all(r.get("panel_seed") for r in (results[i.sku] for i in evaluated))
    have_panel = not indep and len(persons) > 0 and len(evaluated) >= 2
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
        if indep:
            rel_how = "Talep skorunun liste ortalamasından farkı (yalnızca sıralama için; ürünler birbirine göre değerlendirilmedi)."
            notes.append("Bağımsız ürün listesi: her ürün kendi paneliyle ayrı değerlendirildi (tekli ekrandaki gibi). Koleksiyon "
                         "içi rol, erişim, kanibalizasyon ve vitrin turu hesaplanmaz; sıralama yalnızca talep skoruna göre listelemedir.")
        elif evaluated:
            notes.append("Kişi bazlı ilgi puanı yok (panel motoru kapalı); erişim ve kanibalizasyon hesaplanmadı, sıralama talep skorundan.")
    if have_panel and not shared:
        notes.append("Ürünler farklı kişi panelleriyle değerlendirilmiş görünüyor; kişi içi karşılaştırmalar zayıflar.")
    ranks = _ranks(rel)

    # hevesli kişi kümeleri
    ent: Dict[str, Set[Person]] = {s: {p for p, v in per_item_int.get(s, {}).items() if v >= ENTHUSIAST} for s in skus}
    ent_pct = {s: (len(ent[s]) / len(per_item_int[s]) if per_item_int.get(s) else None) for s in skus}
    disp = {s: (statistics.pstdev(per_item_int[s].values()) if len(per_item_int.get(s, {})) > 1 else None) for s in skus}

    sc_items, sc_summary = summarize_showcase({} if indep else (showcase or {}), skus, ranks)

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
        if indep:
            roles[s], why[s] = "belirsiz", "Bağımsız ürün: koleksiyon içi rol verilmez."
        elif n < 3:
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

    if sc_items:
        tog = sorted((v.together for v in sc_items.values()), reverse=True)
        cut = max(2, tog[max(0, len(tog) // 4 - 1)]) if tog else 2
        for s_, v in sc_items.items():
            if roles.get(s_) in ("destek", "riskli") and v.together >= cut:
                roles[s_], why[s_] = "tamamlayıcı", (f"Tek başına ilgi orta/düşük ama vitrinde {v.together} kez kombin "
                                                    "çiftinde seçildi: diğer ürünleri tamamlayan parça")

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
    if sc_summary:
        have = {tuple(sorted((p.a, p.b))) for p in pairs}
        cat = {i.sku: i.category for i in evaluated}
        for sp in sc_summary.substitute_pairs:
            if (sp.a, sp.b) not in have and sp.pct >= 20:
                pairs.append(CannibalPair(a=sp.a, b=sp.b, category=cat.get(sp.a, ""), overlap_pct=sp.pct,
                                          why=f"Vitrinde {sp.count} kişi 'ikisinden birini alırım' dedi"))

    # üretim kararı: üret / azalt / üretme. Sinyaller ajandan, eşikler kural varsayımı.
    in_curve = {p.sku for p in reach_curve}
    name_by = {i.sku: i.name for i in evaluated}
    decision: Dict[str, str] = {}
    source: Dict[str, str] = {}
    decisive: Dict[str, List[Reason]] = {}
    context: Dict[str, List[Reason]] = {}
    drop_regions: Dict[str, Set[str]] = {}
    net_margin: Dict[str, Optional[float]] = {}
    for it in evaluated:
        s = it.sku
        regs = per_item_regions[s]
        a = appeal[s]
        nms = [(r.net_margin_pct, max(1, r.demand_units)) for r in regs if r.net_margin_pct is not None]
        nm = round(sum(v * k for v, k in nms) / sum(k for _, k in nms), 1) if nms else None
        net_margin[s] = nm
        drop, red, ctx = [], [], []
        if a < DEMAND_DROP:
            drop.append(Reason(text=f"Talep skoru {a:.0f}/100, üretme eşiği {DEMAND_DROP}'in altında", basis="ajan"))
        elif a < DEMAND_REDUCE:
            red.append(Reason(text=f"Talep skoru {a:.0f}/100, temkinli üretim eşiği {DEMAND_REDUCE}'nin altında", basis="ajan"))
        else:
            ctx.append(Reason(text=f"Talep skoru {a:.0f}/100", basis="ajan"))
        price_word = "denenen fiyatta" if w.planned_prices.get(s, it.planned_price) else "önerilen fiyatta"
        if nm is None:
            ctx.append(Reason(text="Maliyet fiyatı yok: marj hesaplanamadı, karar yalnızca talebe dayanıyor", basis="kullanıcı girdisi"))
        elif nm < MARGIN_DROP:
            drop.append(Reason(text=f"{price_word.capitalize()} iade sonrası net marj %{nm:g}, üretme eşiği %{MARGIN_DROP:g}'in altında "
                                    "(maliyet bu fiyata göre yüksek)", basis="kural varsayımı"))
        elif nm < MARGIN_REDUCE:
            red.append(Reason(text=f"{price_word.capitalize()} iade sonrası net marj %{nm:g}, temkinli üretim eşiği %{MARGIN_REDUCE:g}'un altında",
                              basis="kural varsayımı"))
        else:
            ctx.append(Reason(text=f"{price_word.capitalize()} iade sonrası net marj %{nm:g}", basis="kural varsayımı"))
        weak = [r.region for r in regs if r.demand < DEMAND_DROP]
        if weak and len(weak) < len(regs):
            drop_regions[s] = set(weak)
            red.append(Reason(text=f"{', '.join(weak)} bölgesinde talep {DEMAND_DROP}'in altında: bu bölge için üretim önerilmez",
                              basis="ajan"))
        if not indep:
            better = sorted({(p.b if p.a == s else p.a) for p in pairs if s in (p.a, p.b)} - {s},
                            key=lambda x: ranks.get(x, 999))
            better = [x for x in better if ranks.get(x, 999) < ranks[s]]
            bn = ", ".join(name_by.get(x, x) for x in better[:2])
            if roles[s] == "riskli":
                if have_panel and s not in in_curve and better:
                    drop.append(Reason(text=f"Koleksiyonun alt diliminde; müşterisini daha güçlü {bn} ile paylaşıyor ve panelde "
                                            "ona özgü yeni bir kişiye ulaşmıyor", basis="ajan"))
                else:
                    red.append(Reason(text=f"Koleksiyon içinde zayıf: {why[s][0].lower() + why[s][1:]}", basis="ajan"))
            elif better:
                # zayıf ürün güçlü eşinin müşterisini paylaşıyorsa azalt; güçlü üründe yalnızca bilgi
                txt = f"Aynı müşteriyi daha güçlü {bn} ile paylaşıyor (kanibalizasyon)"
                (red if roles[s] in ("destek", "belirsiz") else ctx).append(Reason(text=txt, basis="ajan"))
            sci = sc_items.get(s)
            if sci and sci.single_rank and n >= 5 and sci.rank - sci.single_rank >= max(3, n // 4):
                txt = f"Vitrinde diğer ürünlerin yanında belirgin zayıflıyor (tek tek sıra {sci.single_rank}, vitrin sırası {sci.rank})"
                (red if roles[s] in ("destek", "belirsiz") else ctx).append(Reason(text=txt, basis="ajan"))
            if roles[s] == "hero":
                ctx.append(Reason(text="Koleksiyonun öne çıkan (hero) ürünü", basis="kural varsayımı"))
            elif roles[s] == "tamamlayıcı":
                ctx.append(Reason(text="Vitrinde kombin parçası olarak seçiliyor", basis="ajan"))
        sys_dec = "üretme" if drop else "azalt" if red else "üret"
        decisive[s] = drop or red or []
        context[s] = (red if drop else []) + ctx
        user = w.decisions.get(s)
        if user:
            decision[s], source[s] = user, "kullanıcı"
            if user != sys_dec:
                decisive[s] = [Reason(text=f"Elle verilen karar (sistem önerisi: {sys_dec})", basis="kullanıcı girdisi")] + decisive[s]
            drop_regions.pop(s, None)       # kullanıcı kararı bölge elemesini de geçersiz kılar
        else:
            decision[s], source[s] = sys_dec, "sistem"

    # bütçe dağıtımı (kural varsayımı)
    budget_total = w.total_budget if w.total_budget is not None else col.meta.total_budget
    budget_usd = to_usd(budget_total) if budget_total else None
    signals = []
    for it in evaluated:
        if not it.unit_cost or decision[it.sku] == "üretme":
            continue
        cost = to_usd(it.unit_cost)
        factor = REDUCE_FACTOR if decision[it.sku] == "azalt" else 1.0
        for r in per_item_regions[it.sku]:
            if r.region in drop_regions.get(it.sku, ()):
                continue
            price = to_usd(w.planned_prices.get(it.sku, it.planned_price)) if (w.planned_prices.get(it.sku, it.planned_price)) else r.optimal_price
            net = price * (1 - r.return_pct / 100 * (1 + REVERSE_LOGISTICS_PCT / 100))
            signals.append({"sku": it.sku, "region": r.region, "demand": r.demand_units * factor, "net": net, "cost": cost})
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
        if indep:
            pass
        elif any(s in (p.a, p.b) for p in pairs):
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
        sc = sc_items.get(s)
        if sc and sc.single_rank and n >= 5:
            if sc.single_rank - sc.rank >= max(3, n // 4):
                flags.append("vitrinde daha güçlü")
            elif sc.rank - sc.single_rank >= max(3, n // 4):
                flags.append("vitrinde daha zayıf")
        lo_hi = intervals.get(s)
        top = max(regs, key=lambda r: (r.demand_units, r.demand)) if regs else None
        rec_price = Metric(value=round(top.optimal_price, 2) if top else None, low=top.range_low if top else None,
                           high=top.range_high if top else None, basis="ajan",
                           how=(f"{top.region} bölgesinde (en çok talep beklenen bölge) panelin fiyat cevaplarından bulunan en kârlı "
                                "fiyat; aralık panelin kabul edilebilir fiyat aralığı (Van Westendorp). Diğer bölgeler ürün "
                                "ayrıntısında.") if top else "")
        nm_metric = Metric(value=net_margin.get(s), basis="kural varsayımı",
                           how=f"Fiyattan iade (ve %{REVERSE_LOGISTICS_PCT:g} ters lojistik) ile maliyet düşülerek; bölgelerin "
                               "beklenen satışına göre ağırlıklı. Fiyat panelden, iade oranı kural varsayımı.")
        if decision[s] == "üretme":
            qty_metric = Metric(value=0, basis="kural varsayımı", how="Üretme kararı: bütçe dağıtımına alınmadı.")
        else:
            qty_metric = Metric(value=tq if it.unit_cost and budget_usd else None, basis="kural varsayımı",
                                how="Bütçenin satış hızına göre dağıtımı: talep panelden, kitle ve dönüşüm varsayımdan."
                                    + (f" Azalt kararında talebin %{int(REDUCE_FACTOR * 100)}'ı esas alındı." if decision[s] == "azalt" else ""))
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
            role=roles[s], role_why=why[s], decision=decision[s], decision_source=source[s],
            decision_reasons=decisive[s] + context[s], recommended_price=rec_price, net_margin=nm_metric,
            recommended_qty=qty_metric,
            qty_by_region=qty_item.get(s, {}), planned_qty=it.planned_qty, flags=flags, failed_regions=failed,
            showcase=sc_items.get(s)))

    # kategori özeti
    cats: Dict[str, List[ItemResult]] = {}
    for r in out_items:
        if r.regions:
            cats.setdefault(r.category or "(kategorisiz)", []).append(r)
    categories = []
    for c, rs in sorted(cats.items()):
        prices = [r.planned_price_usd or r.recommended_price.value for r in rs if r.planned_price_usd or r.recommended_price.value]
        fits = [x.price_fit for r in rs for x in r.regions if x.price_fit]
        categories.append(CategorySummary(
            category=c, count=len(rs), roles={k: sum(r.role == k for r in rs) for k in ("hero", "çekirdek", "tamamlayıcı", "destek", "riskli")},
            price_min=min(prices) if prices else None, price_max=max(prices) if prices else None,
            mean_appeal=round(statistics.fmean(r.appeal.value or 0 for r in rs), 1),
            in_zone=sum(f == "içinde" for f in fits), out_zone=sum(f != "içinde" for f in fits)))

    # öneriler
    actions: List[Action] = []
    for r in out_items:
        if r.decision in ("üretme", "azalt") and r.sku in decisive:
            why_ = "; ".join(x.text for x in decisive[r.sku][:3])
            tail = (" Üretmeyin ya da tasarımı/maliyeti gözden geçirin." if r.decision == "üretme"
                    else f" Daha az adetle başlayın (talebin %{int(REDUCE_FACTOR * 100)}'ı esas alındı), satışa göre tekrar sipariş verin.")
            actions.append(Action(kind=r.decision, skus=[r.sku], basis=decisive[r.sku][0].basis if decisive[r.sku] else "kural varsayımı",
                                  text=f"{r.name}: {why_}.{tail}"))
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
    name_of = {r.sku: r.name for r in out_items}
    if sc_summary:
        for tp in sc_summary.together_pairs[:3]:
            actions.append(Action(kind="kombin", skus=[tp.a, tp.b], basis="ajan",
                                  text=f"{name_of.get(tp.a, tp.a)} ile {name_of.get(tp.b, tp.b)} vitrinde {tp.count} kez birlikte seçildi "
                                       f"(yan yana gösterildikleri grupların %{tp.pct:g}'si). Birlikte sergileyin, kombin/set önerisi düşünün."))
        for r in out_items:
            if "vitrinde daha güçlü" in r.flags:
                actions.append(Action(kind="vitrin", skus=[r.sku], basis="ajan",
                                      text=f"{r.name}: tek başına sıra {r.showcase.single_rank}, koleksiyonun içinde sıra {r.showcase.rank}. "
                                           "Diğer ürünlerin yanında daha çok seçiliyor; vitrinde ve kampanyada öne alın."))
            elif "vitrinde daha zayıf" in r.flags:
                actions.append(Action(kind="vitrin", skus=[r.sku], basis="ajan",
                                      text=f"{r.name}: tek başına sıra {r.showcase.single_rank}, koleksiyonun içinde sıra {r.showcase.rank}. "
                                           "Yanındaki ürünlere kaybediyor; benzer ürünle aynı yerde sergilemeyin."))
        if sc_summary.position_warning and sc_summary.n_answers >= 20:
            actions.append(Action(kind="veri", basis="ajan", text=sc_summary.position_warning))
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
    notes.append(f"Üretim kararı eşikleri kural varsayımıdır: talep skoru {DEMAND_DROP} altı ya da önerilen fiyatta iade sonrası net "
                 f"marj %{MARGIN_DROP:g} altı 'üretme'; talep {DEMAND_REDUCE} altı, marj %{MARGIN_REDUCE:g} altı"
                 + ("" if indep else ", koleksiyon içi zayıflık ya da kanibalizasyon") + f" ya da bir bölgede talep {DEMAND_DROP} altı "
                 f"'azalt' (bütçeye talebin %{int(REDUCE_FACTOR * 100)}'ı ile girer). Kararı ürün satırından elle değiştirebilirsiniz.")
    notes += [
        "Panel bir tüketici anketi değil, dil modelinin persona ve güncel bağlamla yaptığı tahmindir"
        + ("." if indep else "; en güvenilir kullanımı koleksiyon içi göreli karşılaştırmadır."),
    ]
    if not indep:
        notes.append("Roller, erişim ve kanibalizasyon eşikleri kural varsayımıdır (hevesli = 70+ ilgi; örtüşme %60+, fiyat farkı %25 içinde).")
    notes += [
        "Önerilen satış fiyatı panelin fiyat cevaplarından (Van Westendorp) gelir; Excel'den satış fiyatı okunmaz. Fiyat sekmesinde "
        "denenen fiyat yalnızca fiyat uyumunu, marjı ve kararı yeniden hesaplar, panel cevaplarını değiştirmez.",
        "Önerilen adetler ERP ile kalibre edilene kadar varsayımdır.",
    ]
    summary = CollectionSummary(
        n_items=len(items), n_evaluated=len(evaluated), n_failed=sum(1 for i in items if i.sku in results and not results[i.sku].get("response")),
        reach=reach, reach_by_region=reach_by_region, reach_curve=reach_curve,
        roles={k: sum(r.role == k for r in out_items if r.regions) for k in ("hero", "çekirdek", "tamamlayıcı", "destek", "riskli", "belirsiz")},
        decisions={k: sum(r.decision == k for r in out_items) for k in ("üret", "azalt", "üretme")},
        mean_appeal=Metric(value=round(statistics.fmean(appeal.values()), 1) if appeal else None, basis="ajan",
                           how="Ürünlerin talep skoru ortalaması."),
        categories=categories, cannibal_pairs=pairs, budget_total_usd=round(budget_usd, 2) if budget_usd else None,
        budget_used_usd=round(used, 2), total_qty=sum(alloc.values()),
        expected_units=Metric(value=round(exp_units), basis="kural varsayımı",
                              how="120 günde beklenen satış (orta senaryo), önerilen adetlerle sınırlı."),
        actions=actions)
    regions = sorted({r.region for rs in per_item_regions.values() for r in rs}) or list(col.meta.target_regions)
    return CollectionResult(collection_id=col.id, name=col.meta.name, kind=col.meta.kind, currency=cur, fx_rate=fx_rate, regions=regions,
                            items=out_items, summary=summary, notes=notes, data_basis=data_basis, panel_shared=shared,
                            brand_profile=brand, brand_effect=brand_effect(brand, col, regions), showcase=sc_summary)
