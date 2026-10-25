"""Her sayının nasıl türetildiğini sade Türkçe ile açıklar.

Metinler sabit şablon değil: motorun hesap ayrıntılarından (meta), fiyat analizinden,
dağıtım ağırlıklarından ve marka profilinden gelen gerçek sayılarla doldurulur.
"""
from decimal import Decimal
from typing import List, Optional

from . import brand as brandlib
from . import economy
from .allocation import RegionAllocation
from .models import AllocationView, BrandProfile, Explanation, VanWestendorpResult
from .services.engine import RegionSimulation

_FEATURE_TR = {"warmth": "ısı tutma", "waterproof": "su/rüzgar geçirmezlik", "sheen": "parlak yüzey",
               "eco": "sürdürülebilirlik", "synthetic": "sentetik içerik", "premium": "premium algı",
               "oversize": "bol kesim", "heavy": "ağır kumaş"}


def _signed(x: float) -> str:
    return f"{x:+.1f}"


def _usd(x) -> str:
    return f"${float(x):,.2f}"


def _demand(sim: RegionSimulation, region: str, brand: Optional[BrandProfile]) -> Explanation:
    m = sim.meta
    if m.get("engine") == "mirofish":
        how = (f"{m['n_agents']} ajan ürün kartını ve {region} personasını değerlendirdi; {m['n_valid']} ajandan geçerli "
               f"cevap geldi. Talep endeksi bu ajanların 0-100 arası ilgi puanlarının ortalamasıdır ({m['mean_interest']}).")
        assumptions = ["Ajanlar bir dil modelinin canlandırdığı sentetik tüketicilerdir, gerçek satış verisi değildir.",
                       "Sonuç modelin kalitesine bağlıdır; küçük yerel modeller tutarsız puan verebilir."]
        if m.get("n_extracted"):
            assumptions.append(
                f"{m['n_extracted']} ajan serbest metinle cevap verdi; ilgi ve fiyat eşikleri ayrı bir dil modeli çağrısıyla "
                "bu metinlerden çıkarıldı (ham cevaplar 'Ham ajan cevapları' bölümünde).")
        if m.get("price_source") == "brand_fallback":
            assumptions.append(
                "Ajanlardan kullanılabilir fiyat eşiği gelmedi (yalnızca ilgi puanı); fiyat eğrisi marka profili ve maliyetten "
                "üretilen referans fiyat etrafında kuruldu. Önerilen fiyatı ajan görüşü değil varsayım olarak değerlendir.")
        elif m.get("n_priced") is not None and m["n_priced"] < m["n_valid"]:
            assumptions.append(f"{m['n_valid'] - m['n_priced']} ajanın yalnızca ilgi puanı alındı; fiyat eğrisi {m['n_priced']} ajana dayanıyor.")
        if m.get("n_estimated"):
            assumptions.append(f"{m['n_estimated']} cevapta bazı fiyat eşikleri açıkça yazmıyordu, metnin tonundan tahmin edildi.")
        if m["n_valid"] < m["n_agents"]:
            assumptions.append(
                f"{m['n_agents'] - m['n_valid']} ajan zaman aşımı ya da bozuk cevap yüzünden hesaba katılmadı; "
                "sonuç kısmi örneklemle üretildi, güven düşüktür.")
    else:
        feats = ", ".join(_FEATURE_TR.get(f, f) for f in m.get("matched_features", [])) or "eşleşen özellik yok"
        parts = [f"taban 55", f"ürün-bölge uyumu {_signed(m['fit_points'])} ({feats})"]
        if brand is not None:
            parts += [f"markanın {region} gücü {_signed(m['brand_region_points'])}",
                      f"marka çekim gücü {_signed(m['brand_pull_points'])}"]
        parts.append(f"deterministik rastgelelik {_signed(m['noise_points'])}")
        how = "Mock simülasyon: " + " + ".join(parts) + f" = {sim.demand_score} (0-100 arasına sıkıştırılır)."
        assumptions = ["Bu bir mock modeldir: ürün özellikleri anahtar kelimeyle çıkarılır, ajanlar gerçek LLM değildir.",
                       "Gerçek ajan sürüsü için SIM_ENGINE=mirofish kullanılmalı."]
    if brand is not None and m.get("engine") == "mirofish":
        assumptions.append(f"Ajanlara {brand.name} markasının profili ve {region} bilinirliği "
                           f"({brandlib.region_strength(brand, region)}/100) verildi.")
    return Explanation(key="demand", label="Talep endeksi", value=f"{sim.demand_score}/100", how=how, assumptions=assumptions)


def _price(sim: RegionSimulation, vw: VanWestendorpResult, best: Decimal, unit_cost: float,
           brand: Optional[BrandProfile], region: str, fx_rate: Optional[float] = None) -> Explanation:
    how = (f"{len(sim.price_answers)} ajana dört fiyat sorusu soruldu (çok ucuz, ucuz, pahalı, çok pahalı). "
           f"Eğrilerin kesişimiyle kabul edilebilir aralık {_usd(vw.acceptable_range_low)} – {_usd(vw.acceptable_range_high)}, "
           f"optimal fiyat noktası (OPP) {_usd(vw.optimal_price_point)} bulundu. Önerilen {_usd(best)}, bu aralıkta "
           f"(fiyat − maliyet) × satın alma olasılığı en yüksek olan fiyattır; maliyetin {float(best) / unit_cost:.1f} katı.")
    assumptions = ["Ajanların söylediği eşikler gerçek satın alma davranışı değildir.",
                   "'Pahalı' bulan ajanın yarı olasılıkla aldığı varsayıldı.",
                   f"Fiyatlar ABD doları; birim maliyet {_usd(unit_cost)}."]
    if brand is not None:
        ref = brandlib.reference_price(brand, unit_cost)
        how += (f" Marka etkisi: {brand.name} ({brandlib.TIER_LABEL[brand.price_tier]}) tipik olarak maliyetinin "
                f"{brand.price_multiple:.1f} katına satar; bu, referans fiyatı {_usd(ref)} yapar.")
        if sim.meta.get("engine") == "mock":
            how += (f" Ajanların fiyat merkezi {_usd(sim.meta['price_center'])} = maliyet × {brand.price_multiple:.1f} × "
                    f"{region} alım gücü faktörü {sim.meta['region_factor']}; fiyata duyarlılık {brand.price_sensitivity:.2f} "
                    "olduğundan kabul bandı " + ("dar" if brand.price_sensitivity >= 0.6 else "geniş" if brand.price_sensitivity <= 0.35 else "orta") + ".")
        assumptions.append(f"Marka profili ({brand.source}"
                           + (", kullanıcı düzenledi" if brand.edited else "") + f", güven: {brand.confidence}) doğruluğu kadar geçerlidir.")
    else:
        assumptions.append("Marka girilmediği için nötr kitlesel fiyat varsayımı (maliyetin ~2.7 katı) kullanıldı.")
    eco = economy.REGION_ECONOMY.get(region)
    if eco is not None:
        assumptions.extend(eco.assumptions)
        if eco.currency and fx_rate:
            local = economy.local_price(best, fx_rate)
            lo = economy.local_price(vw.acceptable_range_low, fx_rate)
            hi = economy.local_price(vw.acceptable_range_high, fx_rate)
            how += (f" Yerel para: kur 1 USD = {fx_rate:g} {eco.currency} varsayımıyla önerilen fiyat ₺{int(local):,} "
                    f"(kabul aralığı ₺{int(lo):,} – ₺{int(hi):,}).")
            shocked = economy.margin_after_fx_shock(float(best), unit_cost)
            how += (f" Kur riski: {eco.currency} %{economy.FX_SHOCK_PCT:.0f} değer kaybeder ve TL fiyatı sabit kalırsa "
                    f"USD marjı %{(float(best) - unit_cost) / float(best) * 100:.1f}'den %{shocked:.1f}'e düşer.")
            assumptions.append(f"Kur 1 USD = {fx_rate:g} {eco.currency} alındı; bu varsayılan/girilen bir değerdir, canlı kur değildir.")
    return Explanation(key="price", label="Optimal satış fiyatı", value=_usd(best), how=how, assumptions=assumptions)


def _margin(best: Decimal, unit_cost: float, brand: Optional[BrandProfile]) -> Explanation:
    margin = float((best - Decimal(str(unit_cost))) / best * 100)
    how = f"(satış fiyatı {_usd(best)} − birim maliyet {_usd(unit_cost)}) ÷ satış fiyatı = %{margin:.1f}."
    if brand is not None:
        diff = margin - brand.margin_norm_pct
        how += (f" {brand.name} için tipik brüt marj %{brand.margin_norm_pct:.0f}; bu ürün "
                + ("normun yaklaşık aynısında." if abs(diff) < 5 else f"normdan %{abs(diff):.0f} puan {'yüksek' if diff > 0 else 'düşük'}."))
    return Explanation(key="margin", label="Brüt marj", value=f"%{margin:.1f}", how=how,
                       assumptions=["Yalnızca üretim maliyeti dikkate alındı; lojistik, gümrük, pazarlama ve iade maliyeti dahil değil.",
                                    "Marka marj normu modelin genel bilgisinden gelir ve doğrulanmamıştır." if brand else
                                    "Marka girilmediği için marj normu ile karşılaştırma yapılmadı."])


def _quantity(alloc: RegionAllocation, total_weight: Decimal, total_budget: int, unit_cost: float,
              sim: RegionSimulation, best: Decimal) -> Explanation:
    if alloc.weight <= 0:
        how = (f"Ağırlık = talep {sim.demand_score} × (fiyat {_usd(best)} − maliyet {_usd(unit_cost)}) kârsız ya da sıfır çıktığı için "
               "bu bölgeye üretim ayrılmadı.")
    else:
        share = float(alloc.weight / total_weight * 100)
        how = (f"Ağırlık = talep {sim.demand_score} × (fiyat {_usd(best)} − maliyet {_usd(unit_cost)}) = {float(alloc.weight):,.0f}. "
               f"Tüm bölgelerin toplam ağırlığındaki payı %{share:.1f}; bu pay {_usd(total_budget)} bütçenin {_usd(alloc.budget)} kadarını "
               f"getirir. {_usd(alloc.budget)} ÷ {_usd(unit_cost)} = {float(alloc.budget) / unit_cost:.1f} adet, aşağı yuvarlanır.")
    return Explanation(key="quantity", label="Önerilen üretim adedi", value=f"{alloc.quantity:,}", how=how,
                       assumptions=["Bütçe tamamen üretime gider; talep ve fiyat, ajan simülasyonu sonucuna göre sabit varsayıldı.",
                                    "Stok riski, minimum sipariş adedi ve sezon sonu indirimi hesaba katılmadı."])


def explain_region(sim: RegionSimulation, vw: VanWestendorpResult, best: Decimal, unit_cost: float,
                   alloc: RegionAllocation, total_weight: Decimal, total_budget: int,
                   brand: Optional[BrandProfile], fx_rate: Optional[float] = None) -> List[Explanation]:
    return [_demand(sim, sim.region, brand), _price(sim, vw, best, unit_cost, brand, sim.region, fx_rate),
            _margin(best, unit_cost, brand), _quantity(alloc, total_weight, total_budget, unit_cost, sim, best)]


def methodology_notes(engine: str, brand: Optional[BrandProfile]) -> List[str]:
    notes = ["Sonuçlar sentetik ajan simülasyonundan gelir; gerçek satış verisiyle doğrulanmadı. Karar için tek başına kullanılmamalı."]
    notes.append("Bu çalıştırma MOCK simülasyon kullandı (gerçek LLM ajanları yok)." if engine == "mock"
                 else "Bu çalıştırma MiroFish ajan sürüsü kullandı.")
    if brand is None:
        notes.append("Marka girilmedi: fiyatlama nötr kitlesel varsayımla yapıldı.")
    return notes


def allocation_view(region: str, objective: str, demand: float, ret_pct: float, restock: float,
                    units_before: int, units: int, unit_cost: float, price: float) -> AllocationView:
    """Eski (kâr ağırlıklı) ve yeni dağıtımı orta senaryoda (tahmin bölümüyle aynı) karşılaştırır ve nedenini yazar."""
    def outcome(q: int):
        sold = min(q, int(demand))
        return sold, q - sold, max(0, int(demand) - q), round(sold / q * 100, 1) if q else 0.0

    sb, lb, ub, stb = outcome(units_before)
    sn, ln, un, stn = outcome(units)
    net = int(demand * (1 - ret_pct / 100 * (1 - restock)))
    names = {"balanced": "dengeli (satış hızı)", "profit": "kâr ağırlıklı", "blended": "karışık"}
    if units <= 0:
        why = (f"{region} için üretim ayrılmadı: iade ve iade lojistiği düşülünce net fiyat birim maliyetin altında kalıyor "
               "ya da beklenen talep sıfır.")
    elif units >= int(demand):
        why = (f"{region} için beklenen 120 günlük talep yaklaşık {int(demand):,} adet (iade sonrası kalıcı satış ~{net:,}). "
               f"Talebi karşılayacak kadar {units:,} adet ayrıldı; fazlası stok riski yaratırdı.")
    else:
        why = (f"Bütçe tüm bölgelerin talebini karşılamaya yetmedi. {region} beklenen talebi ~{int(demand):,} adet; "
               f"bölgelerin satış oranı dengelenerek {units:,} adet ayrıldı (beklenen satış {sn:,}, karşılanamayan talep ~{un:,}).")
    if units_before != units:
        why += (f" Eski kâr ağırlıklı dağıtım {units_before:,} adet verirdi: "
                + (f"~{lb:,} adet stok kalırdı." if lb > 0 else f"~{ub:,} adetlik talep karşılanamazdı."))
    return AllocationView(
        objective=objective, demand_units=int(demand), net_demand_units=net, units_before=units_before, units=units,
        sold_before=sb, sold=sn, leftover_before=lb, leftover=ln, unmet_before=ub, unmet=un,
        sell_through_before_pct=stb, sell_through_pct=stn, why=why + f" Hedef: {names.get(objective, objective)}.")


def allocation_note(objective: str, unspent: Decimal, unit_cost: Decimal, total_demand: float, produced: int) -> str:
    if objective == "profit":
        return "Kâr ağırlıklı mod: bütçe, talep × (fiyat − maliyet) ağırlığıyla dağıtıldı; bölgelerde stok kalması ya da talebin karşılanamaması olabilir."
    if unspent > unit_cost * 10:
        return (f"Toplam bütçe, beklenen 120 günlük talebi (~{int(total_demand):,} adet) karşılamak için gerekenden fazla. "
                f"{int(unspent / unit_cost):,} adetlik ({unspent:,.0f} $) bütçe stok riski yaratacağı için üretime ayrılmadı; "
                f"önerilen toplam üretim {produced:,} adet. Daha fazla üretmek istersen 'Kâr ağırlıklı' modu ya da kitle varsayımlarını değiştir.")
    return "Bütçe, beklenen talebin altında kaldı; üretim bölgeler arasında satış oranları dengelenecek biçimde dağıtıldı."
