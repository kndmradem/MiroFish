"""Perakende takvimine bağlı kampanya planı (yeni ürün, satış geçmişi yok).

Plan = 120 günlük ufukta takvim etkinliklerine yerleştirilmiş kampanyalar (etkinlik, indirim basamağı, pencere).
Her plan günlük stok simülasyonundan geçer:

    günlük talep = temel talep eğrisi (forecast.DemandModel) x fiyatta satın alma olasılığı (ajan eğrisi)
                   x etkinlik etkisi (uygunluk x tür aralığı) x bekleme düzeltmesi
    satış = stokla sınırlı;  değer = iade sonrası kâr + kalan stok x maliyet x geri kazanım oranı

Dayanaklar: satın alma olasılığı ajan; etkinlik uygunluğu ajan (yoksa kural varsayımı); etkinlik etkisinin
büyüklüğü, erteleme ve geri dönüş oranları kural varsayımı (etkinlik_turleri.csv); düşük/yüksek senaryo talep
x0,65 / x1,4 ve etki aralığının alt/üst ucu (olasılık aralığı değil, senaryo aralığı).
"""
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from itertools import combinations, product
from typing import Dict, List, Optional, Sequence, Tuple

from ..forecast import HIGH_MULT, HORIZON, LOW_MULT, DemandModel
from ..models import (Assumptions, CalendarCampaign, CalendarEvent, CalendarPlan, CalendarPlanOption, PricePhase,
                      PricePlan, VanWestendorpResult)
from ..pricing import AgentPriceAnswer, purchase_probability
from ..returns import net_margin_pct, net_profit_per_sale
from .data import Event, Takvim
from .fit import FitResult

MIN_WINDOW, MAX_WINDOW, GIFT_LEAD_CAP, WAIT_LEAD_DEFAULT, REF_DAYS, PROMO_REF_DISC = 3, 30, 7, 14, 30, 30.0
SCEN = {"low": (LOW_MULT, 0), "mid": (1.0, 1), "high": (HIGH_MULT, 2)}


def _d(x: float) -> Decimal:
    return Decimal(str(round(x, 2)))


@dataclass
class _Ev:
    e: Event
    d0: int            # etkinlik başlangıcı (gün)
    d1: int            # etkinlik bitişi (gün, dahil)
    w0: int            # etkinin başladığı gün (ön pencere dahil)
    fit: float
    lifts: Tuple[float, float, float]   # alt / orta / üst etkinlik çarpanı - 1 (indirimsiz)
    promo: Tuple[float, float, float]   # etkinlikte indirim yapılırsa ek çarpan - 1
    c0: int            # kampanya penceresi
    c1: int


def _events(takvim: Takvim, events: Sequence[Event], fits: FitResult, start: date) -> List[_Ev]:
    out = []
    for e in events:
        if e.code not in fits.fits:
            continue
        t = takvim.types[e.kind]
        d0, d1 = (e.start - start).days, (e.end - start).days
        w0 = d0 - (e.lead_days if t.use_lead else 0)
        f = fits.fits[e.code].fit
        lo, hi = f * t.lift_low_pct / 100, f * t.lift_high_pct / 100
        c0 = max(0, d0 - (min(e.lead_days, GIFT_LEAD_CAP) if t.use_lead else 0))
        c1 = min(HORIZON - 1, max(d1, c0 + MIN_WINDOW - 1))
        c1 = min(c1, c0 + MAX_WINDOW - 1)
        if c0 > HORIZON - 1 or d1 < 0:
            continue
        g = 0.5 + f                         # indirim ek etkisi: uygunluk 0,5 iken dosyadaki aralık, 0 iken yarısı, 1 iken 1,5 katı
        plo, phi = g * t.promo_low_pct / 100, g * t.promo_high_pct / 100
        out.append(_Ev(e, d0, d1, w0, f, (lo, (lo + hi) / 2, hi), (plo, (plo + phi) / 2, phi), c0, c1))
    return out


class _Sim:
    def __init__(self, dm: DemandModel, answers: Sequence[AgentPriceAnswer], launch: float, unit_cost: float, qty: int,
                 rate_pct: float, a: Assumptions, evs: List[_Ev], takvim: Takvim, fits: FitResult):
        self.dm, self.answers, self.launch, self.cost, self.qty, self.rate, self.a = dm, answers, launch, unit_cost, qty, rate_pct, a
        self.evs = evs
        self.base = [dm.demand(t, t + 1, 1.0) for t in range(HORIZON)]
        self.lift = {k: [1.0] * HORIZON for k in ("low", "mid", "high")}
        for ev in evs:
            for t in range(max(0, ev.w0), min(HORIZON, ev.d1 + 1)):
                for k, (_, i) in SCEN.items():
                    self.lift[k][t] *= 1 + ev.lifts[i]
        self.prob_cache: Dict[float, float] = {}
        # Bekleme: penceredeki ilk büyük indirim etkinliği öncesinde tam fiyat talebinin bir kısmı ertelenir.
        self.wait = None
        if fits.wait_event and fits.wait_share:
            ev = next((x for x in evs if x.e.code == fits.wait_event), None)
            if ev is not None:
                t = takvim.types[ev.e.kind]
                lead = ev.e.lead_days or WAIT_LEAD_DEFAULT
                self.wait = (ev, max(0, ev.d0 - lead), max(0, ev.d0), fits.wait_share * t.defer_share, t.return_share)

    def prob(self, price: float) -> float:
        p = self.prob_cache.get(price)
        if p is None:
            p = self.prob_cache[price] = purchase_probability(self.answers, price)
        return p

    def prices(self, plan: Sequence[Tuple[_Ev, float]]) -> List[float]:
        pr = [self.launch] * HORIZON
        for ev, disc in plan:
            p = max(self.cost * 1.05, self.launch * (1 - disc / 100))
            for t in range(ev.c0, ev.c1 + 1):
                pr[t] = p
        return pr

    def run(self, plan: Sequence[Tuple[_Ev, float]], scen: str = "mid") -> dict:
        mult = SCEN[scen][0]
        pr = self.prices(plan)
        dem = [self.base[t] * self.prob(pr[t]) * self.lift[scen][t] * mult for t in range(HORIZON)]
        i = SCEN[scen][1]
        for ev, disc in plan:                      # etkinlikte indirim: fırsat arayanlar ve görünürlük (kural varsayımı),
            k = disc / PROMO_REF_DISC              # %30 indirim referansına göre derinlikle orantılı
            for t in range(ev.c0, ev.c1 + 1):
                dem[t] *= 1 + ev.promo[i] * k
        if self.wait is not None:
            ev, a0, a1, share, back = self.wait
            moved = 0.0
            for t in range(a0, min(a1, HORIZON)):
                if pr[t] >= self.launch:          # yalnızca tam fiyat günlerinde ertelenir
                    x = dem[t] * share
                    dem[t] -= x
                    moved += x
            ours = any(e is ev for e, _ in plan)
            if ours:                              # etkinlikte indirim varsa erteleyenler o pencerede alır
                span = range(ev.c0, ev.c1 + 1)
            else:                                 # yoksa bir kısmı etkinlikten sonraki 14 günde tam fiyatla döner
                moved *= back
                span = range(min(HORIZON, ev.d1 + 1), min(HORIZON, ev.d1 + 15))
            if len(span):
                for t in span:
                    dem[t] += moved / len(span)
        left, units, rev, prof = self.qty, [0] * HORIZON, 0.0, 0.0
        carry = 0.0
        for t in range(HORIZON):
            carry += dem[t]
            u = int(min(left, carry))
            carry -= u
            left -= u
            units[t] = u
            rev += u * pr[t]
            prof += u * net_profit_per_sale(pr[t], self.cost, self.rate, self.a)
            if left <= 0:
                carry = 0
        resid = left * self.cost * self.a.residual_value_pct / 100
        return {"prices": pr, "units": units, "sold": self.qty - left, "left": left, "revenue": rev, "profit": prof,
                "residual": resid, "value": prof + resid}


def _valid(plan: Sequence[Tuple[_Ev, float]], gap: int) -> bool:
    w = sorted((ev.c0, ev.c1) for ev, _ in plan)
    return all(b0 - a1 - 1 >= gap for (_, a1), (b0, _) in zip(w, w[1:]))


def _sig(plan) -> tuple:
    return tuple(sorted((ev.e.code, d) for ev, d in plan))


def build_calendar_plan(region: str, dm: DemandModel, answers: Sequence[AgentPriceAnswer], launch: float,
                        unit_cost: float, qty: int, rate_pct: float, a: Assumptions, takvim: Takvim,
                        events: Sequence[Event], fits: FitResult, start: date,
                        verified_only: bool = False) -> CalendarPlan:
    evs = _events(takvim, events, fits, start)
    sim = _Sim(dm, answers, launch, unit_cost, qty, rate_pct, a, evs, takvim, fits)
    floor = unit_cost * 1.05
    steps = sorted({float(s) for s in a.discount_steps if 0 < s < 90 and launch * (1 - s / 100) >= floor})
    skipped_steps = sorted({float(s) for s in a.discount_steps if 0 < s < 90} - set(steps))

    plans: List[tuple] = [()]
    for k in range(1, max(0, a.max_campaigns) + 1):
        for evset in combinations(evs, k):
            for ds in product(steps, repeat=k):
                p = tuple(zip(evset, ds))
                if _valid(p, a.min_campaign_gap_days):
                    plans.append(p)
    scored = [(p, sim.run(p)) for p in plans]

    def pick(cands):
        return max(cands, key=lambda x: (round(x[1]["value"], 2), -len(x[0]))) if cands else None

    none = scored[0]
    best = pick(scored)
    single = pick([x for x in scored if len(x[0]) == 1])
    top_v = best[1]["value"]
    sell = max((x for x in scored if x[1]["value"] >= 0.9 * top_v), key=lambda x: (x[1]["sold"], x[1]["value"]))
    chosen, seen = [], set()
    if not best[0]:
        cands = (("none", "Kampanya yok (tam fiyat): en yüksek değer", none),
                 ("sell", "Stoğu en çok eriten (değerin %90'ı içinde)", sell), ("single", "Tek kampanyalı en iyi", single))
    else:
        cands = (("best", "En yüksek değer", best), ("sell", "Stoğu en çok eriten (değerin %90'ı içinde)", sell),
                 ("single", "Tek kampanyalı en iyi", single), ("none", "Kampanya yok (tam fiyat)", none))
    for key, label, x in cands:
        if x is None or _sig(x[0]) in seen:
            continue
        seen.add(_sig(x[0]))
        chosen.append((key, label, x))

    def campaigns(p, r) -> List[CalendarCampaign]:
        out = []
        for ev, disc in sorted(p, key=lambda z: z[0].c0):
            price = r["prices"][ev.c0]
            hist = [r["prices"][t] for t in range(max(0, ev.c0 - REF_DAYS), ev.c0)]
            ref = min(hist) if hist else launch
            out.append(CalendarCampaign(
                event_code=ev.e.code, event_name=ev.e.name, day_from=ev.c0, day_to=ev.c1,
                date_from=start + timedelta(days=ev.c0), date_to=start + timedelta(days=ev.c1),
                discount_pct=round((1 - price / launch) * 100, 1), price=_d(price),
                purchase_prob_pct=round(sim.prob(price) * 100, 1), units=sum(r["units"][ev.c0:ev.c1 + 1]),
                ref_price=_d(ref), advertised_discount_pct=round(max(0.0, (1 - price / ref) * 100), 1),
                price_history_days=ev.c0))
        return out

    options = []
    for key, label, (p, r) in chosen:
        lo, hi = sim.run(p, "low"), sim.run(p, "high")
        options.append(CalendarPlanOption(
            key=key, label=label, campaigns=campaigns(p, r), units=r["sold"], units_low=lo["sold"], units_high=hi["sold"],
            leftover_units=r["left"], sell_through_pct=round(r["sold"] / qty * 100, 1) if qty else 0.0,
            revenue=_d(r["revenue"]), net_profit=_d(r["profit"]), residual_value=_d(r["residual"]),
            total_value=_d(r["value"]), total_value_low=_d(lo["value"]), total_value_high=_d(hi["value"]),
            recommended=_sig(p) == _sig(best[0])))

    # --- yorum ---
    b, n0 = best[1], none[1]
    if not best[0]:
        verdict = (f"Bu ürün ve takvimde kampanyasız plan en yüksek değeri veriyor: {qty:,} adetten {n0['sold']:,} "
                   f"satılır, {n0['left']:,} kalır. İndirim kârı artırmıyor.")
    else:
        names = " + ".join(f"{c.event_name} %{c.discount_pct:g}" for c in options[0].campaigns)
        verdict = (f"Önerilen plan: {names}. Kampanyasıza göre değer {_signed(b['value'] - n0['value'])}, "
                   f"satış {b['sold'] - n0['sold']:+,} adet, kalan stok {n0['left']:,} → {b['left']:,}.")
        gap = (b["value"] - n0["value"]) / abs(n0["value"]) if n0["value"] else 1.0
        if gap < 0.03:
            verdict += (f" Fark küçük (değerin %{gap * 100:.1f}'i) ve senaryo aralıklarının içinde: kampanyasız plan da "
                        "makul, karar marka politikasına göre verilebilir.")
        if sell[0] and _sig(sell[0]) != _sig(best[0]):
            verdict += (f" Stoğu daha çok eritmek isterseniz '{_plan_name(sell[0])}' {sell[1]['left']:,} adet bırakır, "
                        f"değeri {_signed(sell[1]['value'] - b['value'])} farklıdır.")

    # --- etkinlik listesi ---
    ev_rows = []
    for ev in evs:
        f = fits.fits[ev.e.code]
        t = takvim.types[ev.e.kind]
        ev_rows.append(CalendarEvent(
            code=ev.e.code, name=ev.e.name, scope=ev.e.scope, country_only=ev.e.country_only, kind=ev.e.kind,
            kind_label=t.label, date_from=ev.e.start, date_to=ev.e.end, day_from=ev.d0, day_to=ev.d1, window_from_day=ev.w0,
            fit_pct=round(f.fit * 100), fit_basis=f.basis, fit_n=f.n, rule_fit_pct=round(f.rule_fit * 100),
            lift_low_pct=round(ev.lifts[0] * 100, 1), lift_high_pct=round(ev.lifts[2] * 100, 1), verified=ev.e.verified,
            source=ev.e.source, legal_note=ev.e.legal_note, comments=f.comments))

    warnings = []
    unver = [e.name for e in evs_events(evs) if not e.verified]
    if unver:
        warnings.append(f"Doğrulanmamış takvim satırı ({len(unver)}): {', '.join(unver)}. Tarihleri perakende_takvimi.csv'de "
                        "resmi kaynaktan kontrol edip dogrulandi=evet yapın.")
    if any(ev.e.country_only for ev in evs):
        warnings.append("Bazı etkinlikler yalnızca bir ülkede (ör. FR, AE): bölge planında o ülkenin payı ayrıca düşünülmeli; "
                        "simülasyon tüm bölgeye uygulanmış gibi hesaplar.")
    for c in options[0].campaigns if options else []:
        if c.price_history_days < REF_DAYS:
            warnings.append(f"{c.event_name} kampanyası ürün satışa çıktıktan {c.price_history_days} gün sonra başlıyor. "
                            "İndirim duyurusunda gösterilecek 'indirim öncesi fiyat' kuralı (son 30 gün en düşük fiyat; TR ve AB) "
                            "avukatla doğrulanmalı (soru H4).")
        if c.advertised_discount_pct + 0.5 < c.discount_pct:
            warnings.append(f"{c.event_name}: önceki indirim yüzünden ilan edilebilecek indirim %{c.advertised_discount_pct:g} "
                            f"(gerçek %{c.discount_pct:g}). Kural doğrulanmalı (H4).")
    for ev in evs:
        if ev.e.legal_note and ev.e.kind in ("sezon_sonu",):
            warnings.append(f"{ev.e.name}: {ev.e.legal_note}")
    if skipped_steps:
        warnings.append(f"İndirim basamağı %{', %'.join(f'{s:g}' for s in skipped_steps)} maliyet tabanının "
                        f"(maliyet x1,05 = ${floor:.2f}) altına indiği için denenmedi.")
    if fits.note:
        warnings.append(fits.note)
    if not evs:
        warnings.append("Bu bölge ve tarih aralığında takvimde etkinlik yok; plan yalnızca kampanyasız seçeneği gösterir. "
                        "perakende_takvimi.csv'ye bu dönemin etkinliklerini ekleyin.")

    wt = takvim.types[next(ev.e.kind for ev in evs if ev.e.code == fits.wait_event)] if fits.wait_event and evs else None
    assumptions = [
        "İndirimli fiyatta satın alma olasılığı ajanların fiyat eşiklerinden gelir (ajan).",
        "Etkinlik uygunluğu " + ("panel kişilerine soruldu (ajan)." if fits.engine == "panel" else
                                 "mock motorun sahte cevaplarından." if fits.engine == "mock" else
                                 "ürün metninin etkinlik segment etiketleriyle eşleşmesinden (kural varsayımı)."),
        "Etkinlik etkisinin büyüklüğü = uygunluk x etkinlik türü aralığı (etkinlik_turleri.csv, kural varsayımı, kalibre edilmedi): "
        "indirimsiz etki her planda, 'indirim yapılırsa ek etki' yalnızca o etkinlikte kampanya varsa (dosyadaki aralık %30 "
        "indirim içindir, indirim derinliğiyle orantılı ve uygunlukla (0,5 + uygunluk katı) ölçeklenir). "
        "Satış geçmişi olan ürünlerde bu sayılar ERP'den öğrenilecek (P1).",
        "Ajan fiyat eğrisi yalnızca fiyatı kabul edip etmemeyi ölçer; fiyat zaten kabul bölgesindeyse indirim ajan "
        "tarafında satışı artırmaz, artış yalnızca kural varsayımı olan 'indirim ek etkisi'nden gelir. Fiyat kabul bölgesinin "
        "üstündeyse iki etki birlikte çalışır ve artış biraz fazla sayılmış olabilir.",
        f"Kampanya penceresi etkinlik günleri (hediye/dini günlerde en fazla {GIFT_LEAD_CAP} gün önceden), en az {MIN_WINDOW}, "
        f"en fazla {MAX_WINDOW} gün; kampanya bitince fiyat lansman fiyatına döner.",
        f"En fazla {a.max_campaigns} kampanya, iki kampanya arası en az {a.min_campaign_gap_days} gün, basamaklar "
        f"%{', %'.join(f'{s:g}' for s in steps) or '-'}; fiyat maliyet x1,05'in altına inmez.",
        f"120. günde kalan stok maliyetin %{a.residual_value_pct:g}'i ile geri kazanılır (kural varsayımı; outlet/stok satışı).",
        "Düşük/yüksek: talep x" + f"{LOW_MULT:g}/x{HIGH_MULT:g} ve etkinlik etkisi aralığının alt/üst ucu (senaryo aralığı, istatistiksel güven aralığı değil).",
        "Rakiplerin aynı etkinlikte indirim yapması ve kampanya sonrası talep düşüşü modellenmedi.",
    ]
    if fits.wait_event and fits.wait_share is not None and wt is not None:
        assumptions.append(
            f"Bekleme: kişilerin %{fits.wait_share * 100:.0f}'i ({fits.wait_basis}, {fits.wait_n} cevap) bu ürün için "
            f"{_ev_name(evs, fits.wait_event)} indirimini beklerim dedi; bunların %{wt.defer_share * 100:.0f}'inin gerçekten "
            f"ertelediği, indirim yapılmazsa %{wt.return_share * 100:.0f}'inin sonra tam fiyata döndüğü varsayıldı (kural varsayımı).")
    return CalendarPlan(
        start_date=start, horizon_days=HORIZON, events=ev_rows, options=options, verdict=verdict,
        wait_event=fits.wait_event, wait_share_pct=round(fits.wait_share * 100, 1) if fits.wait_share is not None else None,
        wait_basis=fits.wait_basis, wait_n=fits.wait_n, engine=fits.engine, engine_note=fits.note,
        n_plans_evaluated=len(plans), assumptions=assumptions, warnings=list(dict.fromkeys(warnings)))


def evs_events(evs: List[_Ev]) -> List[Event]:
    return [ev.e for ev in evs]


def _ev_name(evs: List[_Ev], code: str) -> str:
    return next((ev.e.name for ev in evs if ev.e.code == code), code)


def _plan_name(p) -> str:
    return " + ".join(f"{ev.e.name} %{d:g}" for ev, d in sorted(p, key=lambda z: z[0].c0))


def _signed(x: float) -> str:
    return f"{'+' if x >= 0 else '-'}${abs(x):,.0f}"


def to_price_plan(cp: CalendarPlan, dm: DemandModel, answers: Sequence[AgentPriceAnswer], vw: VanWestendorpResult,
                  launch: float, unit_cost: float, qty: int, rate_pct: float, a: Assumptions,
                  zone_of) -> Optional[PricePlan]:
    """Önerilen takvim planını fiyat aşamalarına çevirir (sabit 45/45/30 gün yerine etkinlik tarihleri)."""
    best = next((o for o in cp.options if o.recommended), None)
    flat = next((o for o in cp.options if o.key == "none"), None)
    if best is None:
        return None
    bounds, t = [], 0
    for c in best.campaigns:
        if c.day_from > t:
            bounds.append(("Lansman" if t == 0 else "Kampanya sonrası tam fiyat", t, c.day_from, launch, "Tam fiyat"))
        bounds.append((f"{c.event_name} kampanyası", c.day_from, c.day_to + 1, float(c.price),
                       f"{c.date_from.strftime('%d.%m')} - {c.date_to.strftime('%d.%m')}, takvimden"))
        t = c.day_to + 1
    if t < HORIZON:
        bounds.append(("Kampanya sonrası tam fiyat" if t else "Tam fiyat (kampanya yok)", t, HORIZON, launch,
                       "Tam fiyat" if t else "Takvim planı indirimin değer artırmadığını gösteriyor"))
    # Aşama adetleri takvim simülasyonundan (etkinlik etkisi ve bekleme dahil) değil, plan toplamıyla tutarlı olsun diye
    # orantılı dağıtılır: aşamanın temel talep payı x satın alma olasılığı.
    weights = [dm.demand(d0, d1, purchase_probability(answers, p)) for _, d0, d1, p, _ in bounds]
    tot = sum(weights) or 1
    phases, left = [], best.units
    for i, (name, d0, d1, p, note) in enumerate(bounds):
        u = left if i == len(bounds) - 1 else int(round(best.units * weights[i] / tot))
        u = max(0, min(u, left))
        left -= u
        phases.append(PricePhase(
            name=name, day_from=d0, day_to=d1, price=_d(p), discount_pct=round((1 - p / launch) * 100, 1), zone=zone_of(p, vw),
            purchase_prob_pct=round(purchase_probability(answers, p) * 100, 1), units=u, revenue=_d(u * p),
            net_profit=_d(net_profit_per_sale(p, unit_cost, rate_pct, a) * u),
            net_margin_pct=round(net_margin_pct(p, unit_cost, rate_pct, a), 1), note=note))
    return PricePlan(
        verdict=cp.verdict, phases=phases, total_units=best.units, total_revenue=best.revenue,
        total_net_profit=best.net_profit, leftover_units=best.leftover_units,
        flat_units=flat.units if flat else 0, flat_revenue=flat.revenue if flat else _d(0),
        flat_net_profit=flat.net_profit if flat else _d(0), flat_leftover_units=flat.leftover_units if flat else qty,
        assumptions=["Aşamalar perakende takviminden: kampanyalar etkinlik tarihlerine oturur (sabit 45/45/30 gün yerine).",
                     "Toplamlar takvim planından (etkinlik etkisi ve bekleme dahil); aşama adetleri bu toplamın talep payına göre dağıtımıdır.",
                     *cp.assumptions[:1]],
        basis="fiyat kabulü ajan eğrisinden; kampanya tarihleri takvim dosyasından; etkinlik etkisi kural varsayımı")
