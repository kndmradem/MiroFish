"""Fiyat planı (lansman -> kampanya -> stok eritme) ve bölgeye göre kampanya senaryoları.

Fiyatın talebe etkisi ajanların fiyat eşiklerinden (satın alma olasılığı eğrisi) gelir. Kampanya
kaldıraçlarının (taksit, ücretsiz kargo, paket vb.) etkisi, bölge alışkanlıklarına dair KURAL
VARSAYIMIDIR; aralık olarak gösterilir. Sonuçlar ölçüm değil modeldir.
"""
from decimal import Decimal
from typing import List, Optional, Sequence

from .forecast import HORIZON, DemandModel
from .models import (Assumptions, CampaignLever, CampaignScenario, PricePhase, PricePlan,
                     SalesForecast, VanWestendorpResult)
from .pricing import AgentPriceAnswer, purchase_probability
from .returns import net_margin_pct, net_profit_per_sale


def _d(x: float) -> Decimal:
    return Decimal(str(round(x, 2)))


def _zone_of(price: float, vw: VanWestendorpResult) -> str:
    for z in vw.zones:
        if price >= float(z.low) and (z.high is None or price < float(z.high)):
            return z.label
    return ""


def build_price_plan(model: DemandModel, answers: Sequence[AgentPriceAnswer], vw: VanWestendorpResult, launch: float,
                     unit_cost: float, qty: int, rate_pct: float, a: Assumptions) -> PricePlan:
    ideal = next(z for z in vw.zones if z.key == "ideal")
    cheap_lo = float(vw.acceptable_range_low)
    floor = unit_cost * 1.05
    mid = (float(ideal.low) * float(ideal.high)) ** 0.5
    campaign = max(floor * 1.1, min(launch * 0.9, mid))
    if campaign >= launch:
        campaign = launch * 0.88
    clearance = max(floor, min(campaign * 0.85, (cheap_lo + float(ideal.low)) / 2))
    if clearance >= campaign:
        clearance = campaign * 0.85
    plan = [("Lansman", 0, 45, launch, "Tam fiyatla ilk satış"),
            ("İlk kampanya sonrası", 45, 90, campaign, "İlk kampanya ve fiyat düzeltmesi sonrası standart fiyat"),
            ("Stok eritme", 90, HORIZON, clearance, "Kalan stoğu bitirmek için son fiyat")]
    remaining, phases = qty, []
    for name, t0, t1, price, note in plan:
        prob = purchase_probability(answers, price)
        units = int(min(remaining, model.demand(t0, t1, prob)))
        remaining -= units
        profit = net_profit_per_sale(price, unit_cost, rate_pct, a) * units
        phases.append(PricePhase(
            name=name, day_from=t0, day_to=t1, price=_d(price), discount_pct=round((1 - price / launch) * 100, 1),
            zone=_zone_of(price, vw), purchase_prob_pct=round(prob * 100, 1), units=units, revenue=_d(units * price),
            net_profit=_d(profit), net_margin_pct=round(net_margin_pct(price, unit_cost, rate_pct, a), 1), note=note))

    prob_l = purchase_probability(answers, launch)
    flat_units = int(min(qty, model.demand(0, HORIZON, prob_l)))
    flat_profit = net_profit_per_sale(launch, unit_cost, rate_pct, a) * flat_units
    notes = [
        "Her aşamada satın alma olasılığı ajanların fiyat eşiklerinden hesaplanır (ajan kaynaklı).",
        "Aşama süreleri (45/45/30 gün) ve satış hızı varsayımdır; kampanya fiyatı ideal bölge ortası, stok eritme fiyatı ucuz bölge ortasıdır.",
        f"Fiyatlar maliyetin altına inmez (taban ${floor:.2f}).",
        "İndirim beklentisinin sonraki alımları ertelemesi (bekleyen müşteri) modele dahil değildir; gerçekte erken indirim lansman satışını düşürebilir.",
        "Kâr, iade oranı ve iade maliyeti düşüldükten sonradır.",
    ]
    total_profit = sum(float(p.net_profit) for p in phases)
    leftover = remaining
    if flat_units >= qty * 0.95 and total_profit < flat_profit:
        verdict = (f"Bu senaryoda stok tek fiyatla da (%{flat_units / qty * 100:.0f}) bitiyor; kademeli indirim kârı "
                   f"${flat_profit - total_profit:,.0f} azaltır. İndirim planına gerek yok, lansman fiyatını koru.")
    elif total_profit >= flat_profit:
        verdict = (f"Kademeli plan kârı ${total_profit - flat_profit:,.0f} artırır ve kalan stoğu "
                   f"{qty - flat_units - leftover:,} adet azaltır.")
    else:
        verdict = (f"Kademeli plan kalan stoğu {qty - flat_units - leftover:,} adet azaltır ama kâr "
                   f"${flat_profit - total_profit:,.0f} düşer; stok riski kâr kaybından büyükse tercih edilir.")
    return PricePlan(
        verdict=verdict, phases=phases, total_units=sum(p.units for p in phases), total_revenue=_d(sum(float(p.revenue) for p in phases)),
        total_net_profit=_d(sum(float(p.net_profit) for p in phases)), leftover_units=remaining,
        flat_units=flat_units, flat_revenue=_d(flat_units * launch), flat_net_profit=_d(flat_profit),
        flat_leftover_units=qty - flat_units, assumptions=notes)


# Bölge x hedef için kampanya kataloğu. Kaldıraç: (etiket, talep artışı alt %, üst %, ciro maliyeti %).
# Tüm yüzdeler kural varsayımıdır; bölge alışkanlığına dair genel eğilimlere dayanır.
CATALOG = {
    "TR": {
        "clear_stock": ("Taksitli büyük indirim + Efsane Cuma", 25,
                        [("Taksit (3-6 ay) seçeneği", 12, 25, 1.5), ("Efsane Cuma / sezon sonu etkinliği", 15, 30, 0.5)],
                        "Kasım Efsane Cuma ya da sezon sonu", "Türkiye'de taksit ve indirim etkinlikleri satın alma kararını belirgin hızlandırır."),
        "boost_sales": ("Taksit + ücretsiz kargo", 10,
                        [("Taksit (3-6 ay) seçeneği", 10, 22, 1.5), ("Ücretsiz kargo", 5, 12, 2.0)],
                        "Yeni sezon girişi, bayram öncesi", "Fiyata duyarlı ve enflasyon altında ezilen müşteri için taksit, indirimden daha az marj yer."),
        "defend_competition": ("Fiyat eşleştirme + taksit", 5,
                               [("Taksit (3-6 ay) seçeneği", 6, 14, 1.5), ("Sadakat/ilk alışveriş kodu", 3, 8, 1.0)],
                               "Rakip kampanya haftaları", "Rakip fiyata yakın kal, indirimi taksit ve sadakatle destekle."),
    },
    "MENA": {
        "clear_stock": ("Beyaz Cuma + paket (2'li set)", 25,
                        [("White Friday etkinliği", 15, 30, 0.5), ("2'li paket / aile seti", 10, 20, 1.0)],
                        "White Friday, sezon sonu", "Körfez'de büyük etkinlik dönemleri ve paket teklifleri yüksek hacim getirir."),
        "boost_sales": ("Kapıda ödeme + ücretsiz kargo + Ramazan/Bayram koleksiyonu", 8,
                        [("Kapıda ödeme ve ücretsiz teslimat", 8, 18, 3.0), ("Ramazan / Bayram sezon teması", 12, 28, 1.0)],
                        "Ramazan öncesi 3-4 hafta, Bayram öncesi", "Güven (kapıda ödeme) ve dini takvim bu pazarda en güçlü kaldıraçlar."),
        "defend_competition": ("Değer katan hediye + influencer", 5,
                               [("Hediye / ek ürün (indirim yerine)", 4, 10, 2.0), ("Yerel influencer iş birliği", 4, 12, 3.0)],
                               "Rakip lansmanlarında", "Fiyat savaşı yerine algılanan değeri artır."),
    },
    "EU": {
        "clear_stock": ("Sezon sonu satışı + ücretsiz iade", 25,
                        [("Sezon sonu (SALE) etkinliği", 15, 30, 0.5), ("Ücretsiz iade", 3, 8, 3.0)],
                        "Sezon sonu, Black Friday", "AB'de sezon sonu indirimi alışılmış; ücretsiz iade güveni korur ama iade maliyetini artırır."),
        "boost_sales": ("Ücretsiz kargo eşiği + bülten kodu", 8,
                        [("Ücretsiz kargo (sepet eşiği)", 5, 12, 2.0), ("Bülten/ilk alışveriş kodu", 4, 10, 1.0)],
                        "Yeni sezon girişi", "Sepet eşiği ortalama sipariş tutarını da yükseltir."),
        "defend_competition": ("Sürdürülebilirlik/kalite vurgusu + sadakat", 4,
                               [("Sadakat puanı", 3, 8, 1.0), ("Sürdürülebilirlik/kalite mesajı", 2, 6, 0.5)],
                               "Sürekli", "AB müşterisi fiyat dışında kalite ve sürdürülebilirliğe de bakar."),
    },
    "US": {
        "clear_stock": ("Black Friday / Cyber Monday + BOGO", 30,
                        [("Black Friday/Cyber Monday", 20, 40, 0.5), ("Al-1-Öde-1-yarı fiyat (BOGO)", 10, 20, 1.0)],
                        "Kasım sonu, yıl sonu", "ABD'de Black Friday hacmi diğer dönemlerin çok üzerindedir."),
        "boost_sales": ("Ücretsiz kargo + Şimdi al sonra öde", 8,
                        [("Ücretsiz kargo", 6, 14, 2.0), ("Şimdi al, sonra öde (BNPL)", 6, 15, 2.5)],
                        "Yeni sezon, hafta sonu", "Kargo ve ödeme esnekliği dönüşümü artırır."),
        "defend_competition": ("Fiyat eşleştirme garantisi + sadakat", 5,
                               [("Fiyat eşleştirme garantisi", 4, 10, 1.5), ("Sadakat/üyelik", 3, 8, 1.0)],
                               "Rakip kampanya haftaları", "Rekabetçi pazarda güven ve fiyat garantisi."),
    },
    "CIS": {
        "clear_stock": ("Yılbaşı / 8 Mart indirimi + taksit", 25,
                        [("Yılbaşı / 8 Mart / 11.11 etkinlikleri", 15, 30, 0.5), ("Taksit (рассрочка)", 8, 18, 1.5)],
                        "Aralık-Ocak, Mart başı", "Bölgede takvim temelli hediye dönemleri ve taksit güçlü etki yapar."),
        "boost_sales": ("Ücretsiz teslimat + hediye dönemi", 8,
                        [("Ücretsiz teslimat", 6, 14, 2.5), ("Hediye dönemi teması (8 Mart, Yılbaşı)", 10, 24, 1.0)],
                        "Aralık, Mart başı", "Hediye alışverişi tekil dönemlerde yoğunlaşır."),
        "defend_competition": ("Fiyat eşleştirme + taksit", 5,
                               [("Taksit (рассрочка)", 5, 12, 1.5), ("Yerel pazaryeri görünürlüğü", 3, 9, 2.0)],
                               "Rakip dönemleri", "Fiyat ve ödeme kolaylığıyla rakibe yakın kal."),
    },
}
GOAL_LABEL = {"clear_stock": "Stok eritme", "boost_sales": "Satışı artırma", "defend_competition": "Rakibe karşı konum koruma"}
WINDOW = {"clear_stock": (75, 21), "boost_sales": (30, 21), "defend_competition": (45, 21)}


def build_campaigns(region: str, model: DemandModel, answers: Sequence[AgentPriceAnswer], base_price: float,
                    unit_cost: float, qty: int, rate_pct: float, a: Assumptions, forecast: SalesForecast) -> List[CampaignScenario]:
    prob_base = max(1e-6, purchase_probability(answers, base_price))
    comp_price = a.competitor_price_usd.get(region)
    out: List[CampaignScenario] = []
    sold_at = {p.day: p.sold for p in forecast.curve}
    for goal, (name, disc, lever_rows, timing, rationale) in CATALOG[region].items():
        notes: List[str] = []
        if goal == "defend_competition":
            if comp_price:
                gap = (base_price / comp_price - 1) * 100
                disc = max(0, min(20, round(gap, 1))) if gap > 0 else 0
                rationale += f" Rakip fiyatı ${comp_price:g}; bizim fiyatımız %{gap:+.1f} fark gösteriyor (senin girdin)."
            else:
                notes.append("Rakip fiyatı girilmedi; indirim derinliği genel varsayımdır. Rakip fiyatını 'Varsayımlar'a girersen gerçek farka göre hesaplanır.")
        start, window = WINDOW[goal]
        end = start + window
        price = max(unit_cost * 1.05, base_price * (1 - disc / 100))
        disc_real = (1 - price / base_price) * 100
        prob_c = purchase_probability(answers, price)
        price_uplift = max(0.0, prob_c / prob_base - 1)

        def total_uplift(which: str) -> float:
            f = 1 + price_uplift
            for _, lo, hi, _ in lever_rows:
                f *= 1 + (lo if which == "low" else hi) / 100
            return f - 1

        mid_up = (total_uplift("low") + total_uplift("high")) / 2
        stock_at_start = qty - sold_at.get(start - start % 10, 0)
        base_demand = model.demand(start, end, prob_base)
        baseline = int(min(stock_at_start, base_demand))

        def units(u: float) -> int:
            return int(min(stock_at_start, base_demand * (1 + u)))

        u_low, u_mid, u_high = units(total_uplift("low")), units(mid_up), units(total_uplift("high"))
        cost_pct = sum(c for *_, c in lever_rows) / 100
        profit_c = net_profit_per_sale(price, unit_cost, rate_pct, a) * u_mid - price * u_mid * cost_pct
        profit_b = net_profit_per_sale(base_price, unit_cost, rate_pct, a) * baseline
        margin_c = net_margin_pct(price, unit_cost, rate_pct, a) - cost_pct * 100
        margin_b = net_margin_pct(base_price, unit_cost, rate_pct, a)
        notes += [
            f"Fiyat etkisi ajan eğrisinden: %{disc_real:.0f} indirimle satın alma olasılığı %{prob_base * 100:.0f} → %{prob_c * 100:.0f}.",
            "Taksit/kargo/paket gibi kaldıraçların etkisi kural varsayımıdır (aralık olarak verildi).",
            f"Kampanya penceresi {window} gün (gün {start}-{end}); stok yetmezse artış sınırlanır.",
        ]
        out.append(CampaignScenario(
            goal=goal, goal_label=GOAL_LABEL[goal], name=name, start_day=start, window_days=window,
            discount_pct=round(disc_real, 1), campaign_price=_d(price),
            levers=[CampaignLever(label=l, uplift_low_pct=lo, uplift_high_pct=hi, cost_pct=c) for l, lo, hi, c in lever_rows],
            baseline_units=baseline, units_low=u_low, units=u_mid, units_high=u_high, extra_units=u_mid - baseline,
            extra_revenue=_d(u_mid * price - baseline * base_price), profit_delta=_d(profit_c - profit_b),
            margin_impact_pts=round(margin_c - margin_b, 1), timing=timing, rationale=rationale, assumptions=notes))

    # Hedefe göre öneri: stok kalıyorsa eritme, erken bitiyorsa kampanya gereksiz, aksi halde satışı artırma
    left_share = forecast.leftover_units / qty if qty else 0
    if left_share > 0.10:
        pick, why = "clear_stock", f"120. günde stokun %{left_share * 100:.0f}'i kalıyor; öncelik stok eritme."
    elif forecast.stockout_day and forecast.stockout_day <= 75:
        pick, why = "defend_competition", (f"Stok {forecast.stockout_day}. günde bitiyor; satışı artırmaya gerek yok. "
                                           "İndirimden kaçın, fiyatı ve konumu koru.")
    else:
        pick, why = "boost_sales", "Stok kalmıyor ama satış hızı artırılabilir; indirimsiz kaldıraçlarla satış hızlandırılabilir."
    for c in out:
        if c.goal == pick:
            c.recommended, c.why = True, why
    return out
