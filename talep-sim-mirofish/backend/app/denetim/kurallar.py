"""Mantık denetimi kuralları.

Her kural bir sonucun (koleksiyon sonucu, tekli tahmin ya da müşteri ürün listesi) kendi içindeki tutarlılığını ölçer.
Hiçbir kural marka, ürün ya da kategori adı listesi içermez: yalnızca sonucun alanlarına bakar (kategori eşitliği,
kişi sayısı, fiyat-maliyet, toplamlar, sıralar, sayının dayanağı).

Yeni kural eklemek:
    @kural("kod", "koleksiyon", "Kısa ad", "Neyi yakalar")
    def _kod(s: Sonuc) -> Iterable[Bulgu]:
        ...
Kod regresyon vakalarında 'beklenen' listesinde kullanılır (tests/denetim_vakalari/).

Eşikler kural varsayımıdır; değiştirilirse regresyon testleri ne kaybedildiğini gösterir.
"""
import math
import re
import statistics
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Tuple

from .model import Bulgu

# ---------- eşikler (kural varsayımı) ----------
MIN_KISI = 10            # bir yüzdenin paydası bundan az kişiyse "az kişiye dayanıyor"
MIN_KISI_HATA = 3        # bundan az kişiyle gösterilen eşleşme/yüzde: hata (kanibalizasyon kuralı en az 3 kişi ister)
YUKSEK_YUZDE = 50.0      # az kişiden bu ve üstü yüzde: uyarı
MIN_GOSTERIM = 5         # vitrinde bir ürünün en az bu kadar gösterilmesi beklenir
FIYAT_ARALIK_PAYI = 0.05  # önerilen fiyat kabul aralığının en fazla bu kadar dışına taşabilir
UC_FIYAT_KATI = 15.0     # fiyat / maliyet bunun üstündeyse aşırı uç
UC_IADE = 60.0           # iade oranı (%) bunun üstündeyse aşırı uç
BUTCE_PAYI = 0.005       # bütçe aşımı toleransı
TOPLAM_PAYI = 0.03       # adet x maliyet ile kullanılan bütçe arasındaki fark toleransı
SIRA_ILGI_FARKI = 10.0   # sıralama kuralında "belirgin daha az ilgi" (talep puanı)
SIRA_FIYAT_FARKI = 0.15  # "belirgin daha pahalı" (%)
SIRA_ADET_KATI = 1.25    # "belirgin daha çok adet"
DUZ_ILGI = 2.0           # ürünlerin talep puanları arasındaki fark bundan küçükse panel ayırt etmedi
BASARISIZ_HATA = 0.3     # ürünlerin bu oranından fazlası hesaplanamadıysa hata

DAYANAKLAR = {"ajan", "kural varsayımı", "LLM tahmini", "ERP", "kullanıcı girdisi"}


@dataclass
class Sonuc:
    """Kurallara verilen bağlam. veri: sonucun sözlük hali (model_dump)."""
    kapsam: str
    veri: Dict[str, Any]
    ek: Dict[str, Any] = field(default_factory=dict)   # tekli: unit_cost, budget; veri: import issues

    def urunler(self) -> List[dict]:
        return self.veri.get("items") or []

    def urun(self, sku: str) -> Optional[dict]:
        return next((i for i in self.urunler() if i.get("sku") == sku), None)

    def ad(self, sku: str) -> str:
        u = self.urun(sku)
        return (u or {}).get("name") or sku


@dataclass
class Kural:
    kod: str
    kapsam: Tuple[str, ...]
    baslik: str
    aciklama: str
    fn: Callable[[Sonuc], Iterable[Bulgu]]


KURALLAR: List[Kural] = []


def kural(kod: str, kapsam: str, baslik: str, aciklama: str):
    def deco(fn):
        KURALLAR.append(Kural(kod, tuple(kapsam.split(",")), baslik, aciklama, fn))
        return fn
    return deco


def _b(seviye: str, kod: str, mesaj: str, **kw) -> Bulgu:
    k = next(k for k in KURALLAR if k.kod == kod)
    return Bulgu(seviye=seviye, kural=kod, baslik=k.baslik, mesaj=mesaj, **kw)


# ---------- yardımcılar ----------

def kategori_anahtari(c: Optional[str]) -> str:
    """Kategori karşılaştırması: büyük/küçük harf, Türkçe karakter, boşluk ve noktalama farkı yok sayılır."""
    if not c:
        return ""
    c = c.replace("ı", "i").replace("İ", "i")
    c = unicodedata.normalize("NFKD", c)
    c = "".join(ch for ch in c if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "", c.casefold())


def _sayi(x) -> Optional[float]:
    if x is None or isinstance(x, bool):
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _fmt(x: float, nd: int = 0) -> str:
    s = f"{x:,.{nd}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _gez(o: Any, yol: str = "") -> Iterator[Tuple[str, str, Any, Any]]:
    """(yol, anahtar, değer, üst sözlük) üretir; bütün iç içe sözlük/listeleri gezer."""
    if isinstance(o, dict):
        for k, v in o.items():
            p = f"{yol}.{k}" if yol else str(k)
            yield p, str(k), v, o
            yield from _gez(v, p)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            p = f"{yol}[{i}]"
            if isinstance(v, (dict, list)):
                yield from _gez(v, p)
            else:
                yield p, "", v, o


# =====================================================================
# Koleksiyon sonucu kuralları
# =====================================================================

@kural("kategori_disi_eslesme", "koleksiyon", "Farklı kategoride müşteri paylaşımı",
       "Kanibalizasyon / 'aynı müşteriyi paylaşıyor' çifti farklı kategorideki ürünlerden oluşuyorsa ya da çiftin "
       "kategori etiketi ürünlerin kategorisiyle uyuşmuyorsa")
def _kategori_disi(s: Sonuc):
    pairs = (s.veri.get("summary") or {}).get("cannibal_pairs") or []
    seen = set()
    for i, p in enumerate(pairs):
        a, b = s.urun(p.get("a")), s.urun(p.get("b"))
        if not a or not b:
            yield _b("hata", "kategori_disi_eslesme", f"Müşteri paylaşımı çiftindeki ürün sonuçta yok ({p.get('a')} / {p.get('b')}).",
                     skus=[p.get("a"), p.get("b")], alan=f"summary.cannibal_pairs[{i}]")
            continue
        ka, kb = kategori_anahtari(a.get("category")), kategori_anahtari(b.get("category"))
        seen.add(frozenset((p["a"], p["b"])))
        if ka and kb and ka != kb:
            yield _b("hata", "kategori_disi_eslesme",
                     f"{a['name']} ({a.get('category')}) ile {b['name']} ({b.get('category')}) farklı kategoride, ama "
                     f"'aynı müşteriyi paylaşıyor' (örtüşme %{p.get('overlap_pct')}) olarak gösteriliyor. Farklı kategorideki "
                     "ürünler birbirinin yerine geçmez; bu çift gösterilmemeli.",
                     skus=[p["a"], p["b"]], alan=f"summary.cannibal_pairs[{i}]", dayanak=p.get("basis") or "ajan")
        elif ka and p.get("category") and kategori_anahtari(p.get("category")) != ka:
            yield _b("hata", "kategori_disi_eslesme",
                     f"{a['name']} ile {b['name']} çiftinin kategori etiketi '{p.get('category')}', ürünlerin kategorisi "
                     f"'{a.get('category')}'.", skus=[p["a"], p["b"]], alan=f"summary.cannibal_pairs[{i}]")
    for i, act in enumerate((s.veri.get("summary") or {}).get("actions") or []):
        if act.get("kind") != "kanibalizasyon" or len(act.get("skus") or []) != 2:
            continue
        a, b = (s.urun(x) for x in act["skus"])
        if a and b and frozenset(act["skus"]) not in seen:
            ka, kb = kategori_anahtari(a.get("category")), kategori_anahtari(b.get("category"))
            if ka and kb and ka != kb:
                yield _b("hata", "kategori_disi_eslesme",
                         f"Öneri listesinde {a['name']} ({a.get('category')}) ile {b['name']} ({b.get('category')}) için "
                         "kanibalizasyon önerisi var; ürünler farklı kategoride.", skus=act["skus"], alan=f"summary.actions[{i}]")
    sc = s.veri.get("showcase") or {}
    for i, p in enumerate(sc.get("substitute_pairs") or []):
        a, b = s.urun(p.get("a")), s.urun(p.get("b"))
        if a and b:
            ka, kb = kategori_anahtari(a.get("category")), kategori_anahtari(b.get("category"))
            if ka and kb and ka != kb:
                yield _b("uyarı", "kategori_disi_eslesme",
                         f"Vitrin sekmesi: {p.get('count')} kişi {a['name']} ({a.get('category')}) ile {b['name']} "
                         f"({b.get('category')}) için 'ikisinden birini alırım' dedi. Bu ajanın sözüdür; farklı kategoride "
                         "olduğu için kanibalizasyon sayılmadı. Müşteriye gösterirken açıklayın ya da gizleyin.",
                         skus=[p["a"], p["b"]], alan=f"showcase.substitute_pairs[{i}]", dayanak="ajan")


@kural("kucuk_orneklem", "koleksiyon,tekli", "Az kişiden yüksek yüzde",
       "Bir yüzde ya da eşleşme 10 kişiden azına dayanıyorsa (%100 = 3 kişinin 3'ü gibi)")
def _kucuk_orneklem(s: Sonuc):
    if s.kapsam == "tekli":
        for r in s.veri.get("regional_breakdown") or []:
            ans = r.get("raw_answers") or []
            ok = [a for a in ans if a.get("status") not in ("failed", "empty", "error")]
            if ans and len(ok) < MIN_KISI_HATA:
                yield _b("hata", "kucuk_orneklem", f"{r['region']}: talep ve fiyat yalnızca {len(ok)} geçerli ajan cevabına dayanıyor.",
                         bolge=r["region"], dayanak="ajan")
            elif ans and len(ok) < MIN_KISI:
                yield _b("uyarı", "kucuk_orneklem", f"{r['region']}: {len(ok)} geçerli ajan cevabı var ({MIN_KISI} altı); "
                         "yüzdeler ve fiyat eşikleri kaba.", bolge=r["region"], dayanak="ajan")
        return
    summ = s.veri.get("summary") or {}
    for i, p in enumerate(summ.get("cannibal_pairs") or []):
        base, shared, pct = p.get("base") or 0, p.get("shared") or 0, _sayi(p.get("overlap_pct")) or 0
        nm = f"{s.ad(p['a'])} ile {s.ad(p['b'])}"
        if not base:
            yield _b("uyarı", "kucuk_orneklem", f"{nm}: örtüşme %{pct:g} gösteriliyor ama kaç kişiye dayandığı yok.",
                     skus=[p["a"], p["b"]], alan=f"summary.cannibal_pairs[{i}]", dayanak="ajan")
        elif shared < MIN_KISI_HATA:
            yield _b("hata", "kucuk_orneklem", f"{nm}: örtüşme %{pct:g} yalnızca {shared} kişiye dayanıyor ({shared}/{base}).",
                     skus=[p["a"], p["b"]], alan=f"summary.cannibal_pairs[{i}]", dayanak="ajan")
        elif base < MIN_KISI and pct >= YUKSEK_YUZDE:
            yield _b("uyarı", "kucuk_orneklem",
                     f"{nm}: örtüşme %{pct:g} = {shared}/{base} kişi. Yüzde yüksek görünüyor ama {MIN_KISI} kişiden azına dayanıyor; "
                     "ekranda kişi sayısıyla birlikte gösterilmeli, karar olarak sunulmamalı.",
                     skus=[p["a"], p["b"]], alan=f"summary.cannibal_pairs[{i}]", dayanak="ajan")
    sc = s.veri.get("showcase") or {}
    for key in ("together_pairs", "substitute_pairs"):
        for i, p in enumerate(sc.get(key) or []):
            cnt, pct = p.get("count") or 0, _sayi(p.get("pct")) or 0
            if cnt < MIN_KISI_HATA and pct >= YUKSEK_YUZDE:
                yield _b("uyarı", "kucuk_orneklem", f"Vitrin: {s.ad(p['a'])} ile {s.ad(p['b'])} için %{pct:g}, yalnızca {cnt} seçim.",
                         skus=[p["a"], p["b"]], alan=f"showcase.{key}[{i}]", dayanak="ajan")
    for it in s.urunler():
        v = it.get("showcase")
        if v and (v.get("shown") or 0) < MIN_GOSTERIM and max(v.get("best_pct") or 0, v.get("worst_pct") or 0) >= YUKSEK_YUZDE:
            yield _b("uyarı", "kucuk_orneklem", f"Vitrin: {it['name']} yalnızca {v.get('shown')} kez gösterildi; "
                     f"en iyi %{v.get('best_pct')} / en kötü %{v.get('worst_pct')} kaba.", skus=[it["sku"]], dayanak="ajan")
    n = _panel_n(s)
    if n is not None and n < MIN_KISI:
        yield _b("uyarı", "kucuk_orneklem", f"Panel bölge başına {n} kişi ({MIN_KISI} altı). Hevesli oranı, erişim ve örtüşme "
                 "yüzdeleri birkaç kişiyle değişir.", dayanak="ajan")


def _panel_n(s: Sonuc) -> Optional[int]:
    ns = [p.get("panel_n") for p in (s.veri.get("summary") or {}).get("cannibal_pairs") or [] if p.get("panel_n")]
    if ns:
        return min(ns)
    sc = s.veri.get("showcase") or {}
    by = sc.get("by_region") or {}
    if sc.get("n_persons") and by:
        return int(sc["n_persons"] / max(len(by), 1))
    return s.ek.get("panel_n")


@kural("fiyat_maliyet", "koleksiyon,tekli", "Fiyat-maliyet imkânsızlığı",
       "Önerilen fiyat maliyetin altında, üretilen üründe negatif marj, kabul aralığı ters ya da önerilen fiyat aralığın dışında")
def _fiyat_maliyet(s: Sonuc):
    if s.kapsam == "tekli":
        cost = _sayi(s.ek.get("unit_cost"))
        for r in s.veri.get("regional_breakdown") or []:
            reg, price, qty = r["region"], _sayi(r.get("optimal_sale_price")), r.get("recommended_production_qty") or 0
            if cost and price is not None and price < cost:
                yield _b("hata" if qty > 0 else "uyarı", "fiyat_maliyet",
                         f"{reg}: önerilen fiyat ({_fmt(price, 2)} USD) birim maliyetin ({_fmt(cost, 2)} USD) altında"
                         + (f", yine de {qty} adet üretim öneriliyor." if qty > 0 else "."), bolge=reg, dayanak="ajan")
            m = _sayi(r.get("estimated_margin_percentage"))
            if m is not None and m < 0 and qty > 0:
                yield _b("hata", "fiyat_maliyet", f"{reg}: brüt marj %{m:g} negatif ama {qty} adet üretim öneriliyor.", bolge=reg)
            yield from _vw_kontrol(r.get("van_westendorp") or {}, price, reg, None)
        return
    for it in s.urunler():
        if not it.get("regions"):
            continue
        cost, dec, nm = _sayi(it.get("unit_cost_usd")), it.get("decision"), it["name"]
        rp = _sayi((it.get("recommended_price") or {}).get("value"))
        if cost and rp is not None and rp < cost:
            yield _b("hata" if dec != "üretme" else "bilgi", "fiyat_maliyet",
                     f"{nm}: önerilen fiyat ({_fmt(rp, 2)} USD) birim maliyetin ({_fmt(cost, 2)} USD) altında; karar '{dec}'.",
                     skus=[it["sku"]], dayanak="ajan")
        nmv = _sayi((it.get("net_margin") or {}).get("value"))
        if nmv is not None and nmv < 0 and dec == "üret":
            yield _b("hata", "fiyat_maliyet", f"{nm}: iade sonrası net marj %{nmv:g} negatif ama karar 'üret'.",
                     skus=[it["sku"]], dayanak="kural varsayımı")
        pp = _sayi(it.get("planned_price_usd"))
        if cost and pp is not None and pp < cost:
            yield _b("uyarı", "fiyat_maliyet", f"{nm}: denenen/planlanan fiyat ({_fmt(pp, 2)} USD) maliyetin altında.",
                     skus=[it["sku"]], dayanak="kullanıcı girdisi")
        for r in it["regions"]:
            price = _sayi(r.get("optimal_price"))
            if cost and price and price / cost > UC_FIYAT_KATI:
                yield _b("uyarı", "fiyat_maliyet", f"{nm} {r['region']}: önerilen fiyat maliyetin {price / cost:.1f} katı "
                         f"({UC_FIYAT_KATI:g} kat üstü aşırı uç). Maliyet ya da para birimi yanlış girilmiş olabilir.",
                         skus=[it["sku"]], bolge=r["region"], dayanak="ajan")
            q = (it.get("qty_by_region") or {}).get(r["region"]) or 0
            m = _sayi(r.get("net_margin_pct"))
            if m is not None and m < 0 and q > 0:
                yield _b("uyarı", "fiyat_maliyet", f"{nm} {r['region']}: net marj %{m:g} negatif ama bu bölgeye {q} adet ayrıldı.",
                         skus=[it["sku"]], bolge=r["region"], dayanak="kural varsayımı")
            yield from _vw_kontrol({"acceptable_range_low": r.get("range_low"), "acceptable_range_high": r.get("range_high"),
                                    "zones": r.get("zones")}, price, r["region"], it["sku"], nm)


def _vw_kontrol(vw: dict, price: Optional[float], reg: str, sku: Optional[str], nm: str = ""):
    lo, hi = _sayi(vw.get("acceptable_range_low")), _sayi(vw.get("acceptable_range_high"))
    pre = f"{nm} {reg}" if nm else reg
    skus = [sku] if sku else []
    if lo is not None and hi is not None:
        if lo > hi:
            yield _b("hata", "fiyat_maliyet", f"{pre}: kabul edilebilir fiyat aralığı ters ({_fmt(lo, 2)} > {_fmt(hi, 2)}).",
                     skus=skus, bolge=reg, dayanak="ajan")
        elif price is not None and (price < lo * (1 - FIYAT_ARALIK_PAYI) or price > hi * (1 + FIYAT_ARALIK_PAYI)):
            yield _b("uyarı", "fiyat_maliyet", f"{pre}: önerilen fiyat {_fmt(price, 2)} panelin kabul aralığının "
                     f"({_fmt(lo, 2)}-{_fmt(hi, 2)}) dışında.", skus=skus, bolge=reg, dayanak="ajan")
    lows = [_sayi(z.get("low")) for z in vw.get("zones") or []]
    lows = [x for x in lows if x is not None]
    if any(b < a - 1e-9 for a, b in zip(lows, lows[1:])):
        yield _b("hata", "fiyat_maliyet", f"{pre}: fiyat bölgeleri sırasız (alt sınırlar artmıyor).", skus=skus, bolge=reg, dayanak="ajan")


@kural("toplam_tutarlilik", "koleksiyon,tekli", "Toplam / bütçe tutarsızlığı",
       "Bölge adetleri toplamı ≠ ürün adedi, ürün toplamı ≠ koleksiyon toplamı, bütçe aşımı, 'üretme' kararına adet, "
       "beklenen satış > üretim, renk adetleri ≠ model adedi")
def _toplam(s: Sonuc):
    if s.kapsam == "tekli":
        regs = s.veri.get("regional_breakdown") or []
        tot = sum(r.get("recommended_production_qty") or 0 for r in regs)
        if regs and tot != (s.veri.get("total_produced_qty") or 0):
            yield _b("hata", "toplam_tutarlilik", f"Bölge üretim adetleri toplamı {tot}, genel toplam {s.veri.get('total_produced_qty')}.")
        cost, budget = _sayi(s.ek.get("unit_cost")), _sayi(s.ek.get("budget"))
        if cost and budget and tot * cost > budget * (1 + BUTCE_PAYI):
            yield _b("hata", "toplam_tutarlilik", f"Üretim maliyeti ({_fmt(tot * cost)}) bütçeyi ({_fmt(budget)}) aşıyor.",
                     dayanak="kullanıcı girdisi")
        un = _sayi(s.veri.get("unallocated_budget"))
        if cost and budget and un is not None and abs(budget - tot * cost - un) > max(1.0, budget * BUTCE_PAYI):
            yield _b("hata", "toplam_tutarlilik", f"Harcanmayan bütçe ({_fmt(un)}) = bütçe − adet × maliyet "
                     f"({_fmt(budget - tot * cost)}) değil.")
        for r in regs:
            reg, q = r["region"], r.get("recommended_production_qty") or 0
            f = r.get("forecast") or {}
            prev = -1
            for m in f.get("milestones") or []:
                lo, mid, hi = m.get("units_low"), m.get("units"), m.get("units_high")
                if None not in (lo, mid, hi) and not (lo <= mid <= hi):
                    yield _b("hata", "toplam_tutarlilik", f"{reg} {m.get('day')}. gün: alt/orta/üst satış sırasız ({lo}/{mid}/{hi}).", bolge=reg)
                if mid is not None and mid < prev:
                    yield _b("hata", "toplam_tutarlilik", f"{reg}: kümülatif satış {m.get('day')}. günde azalıyor ({prev} → {mid}).", bolge=reg)
                if mid is not None and q and mid > q:
                    yield _b("hata", "toplam_tutarlilik", f"{reg} {m.get('day')}. gün: satış ({mid}) üretimi ({q}) aşıyor.", bolge=reg)
                prev = mid if mid is not None else prev
            st = _sayi(f.get("sell_through_pct"))
            if st is not None and not (0 <= st <= 100.5):
                yield _b("hata", "toplam_tutarlilik", f"{reg}: satış oranı %{st:g} (0-100 dışında).", bolge=reg)
        return

    summ = s.veri.get("summary") or {}
    items = s.urunler()
    tot = 0
    for it in items:
        q = _sayi((it.get("recommended_qty") or {}).get("value"))
        byr = it.get("qty_by_region") or {}
        if q is not None:
            tot += q
            if byr and abs(sum(byr.values()) - q) > max(1, len(byr)):
                yield _b("hata", "toplam_tutarlilik", f"{it['name']}: bölge adetleri toplamı {sum(byr.values())}, ürün adedi {int(q)}.",
                         skus=[it["sku"]], dayanak="kural varsayımı")
            if it.get("decision") == "üretme" and q > 0:
                yield _b("hata", "toplam_tutarlilik", f"{it['name']}: karar 'üretme' ama {int(q)} adet önerilmiş.", skus=[it["sku"]])
        cols = [c for c in it.get("colors") or [] if c.get("qty") is not None]
        if cols and q is not None and it.get("decision") != "üretme":
            cq = sum(c["qty"] for c in cols)
            if abs(cq - q) > max(1, len(cols)):
                yield _b("uyarı", "toplam_tutarlilik", f"{it['name']}: renk adetleri toplamı {cq}, model adedi {int(q)}.", skus=[it["sku"]])
        shares = [_sayi((c.get("share") or {}).get("value")) for c in it.get("colors") or []]
        shares = [x for x in shares if x is not None]
        if len(shares) > 1 and abs(sum(shares) - 100) > 1.5:
            yield _b("uyarı", "toplam_tutarlilik", f"{it['name']}: renk payları toplamı %{sum(shares):.1f} (100 olmalı).", skus=[it["sku"]])
    if items and summ.get("total_qty") is not None and abs(summ["total_qty"] - tot) > 1:
        yield _b("hata", "toplam_tutarlilik", f"Koleksiyon toplam adedi {summ['total_qty']}, ürün adetlerinin toplamı {int(tot)}.",
                 alan="summary.total_qty")
    bt, bu = _sayi(summ.get("budget_total_usd")), _sayi(summ.get("budget_used_usd"))
    if bt and bu is not None and bu > bt * (1 + BUTCE_PAYI):
        yield _b("hata", "toplam_tutarlilik", f"Kullanılan bütçe ({_fmt(bu)} USD) toplam bütçeyi ({_fmt(bt)} USD) aşıyor.",
                 alan="summary.budget_used_usd", dayanak="kullanıcı girdisi")
    spent = sum((_sayi((i.get("recommended_qty") or {}).get("value")) or 0) * (_sayi(i.get("unit_cost_usd")) or 0) for i in items)
    if bu and spent and abs(spent - bu) > max(1.0, bu * TOPLAM_PAYI):
        yield _b("hata", "toplam_tutarlilik", f"Kullanılan bütçe {_fmt(bu)} USD, ama ürün adetleri × maliyet {_fmt(spent)} USD.",
                 alan="summary.budget_used_usd")
    if bt and bu is not None and bu < 0.5 * bt and any(i.get("decision") == "üret" for i in items):
        yield _b("bilgi", "toplam_tutarlilik", f"Bütçenin yalnızca yüzde {100 * bu / bt:.0f} kadarı kullanıldı: adetler talep tavanına takıldı "
                 "(talep, kitle ve dönüşüm varsayımından). Bütçe kalan kısmı için karar değil.", alan="summary.budget_used_usd")
    eu = _sayi((summ.get("expected_units") or {}).get("value"))
    if eu is not None and summ.get("total_qty") is not None and eu > summ["total_qty"] + 1:
        yield _b("hata", "toplam_tutarlilik", f"Beklenen satış ({int(eu)}) üretilen toplam adedi ({summ['total_qty']}) aşıyor.",
                 alan="summary.expected_units")
    dec = summ.get("decisions") or {}
    n_dec = sum(1 for i in items if i.get("decision"))
    if dec and sum(dec.values()) != n_dec:
        yield _b("hata", "toplam_tutarlilik", f"Karar sayıları ({sum(dec.values())}) kararlı ürün sayısını ({n_dec}) tutmuyor.",
                 alan="summary.decisions")
    ne = summ.get("n_evaluated")
    if ne is not None and ne != sum(1 for i in items if i.get("regions")):
        yield _b("hata", "toplam_tutarlilik", f"Değerlendirilen ürün sayısı {ne}, sonuçlu ürün {sum(1 for i in items if i.get('regions'))}.",
                 alan="summary.n_evaluated")


@kural("siralama", "koleksiyon", "Şüpheli sıralama",
       "Sıra ile koleksiyon içi puan çelişiyor; aynı kategoride daha pahalı ve daha az ilgi gören ürüne daha çok adet; "
       "daha çok ilgi gören ve daha ucuz ürüne daha az talep adedi; gerekçesiz 'üretme/azalt'; hero ama 'üretme'")
def _siralama(s: Sonuc):
    items = [i for i in s.urunler() if i.get("regions")]
    rel = [(i, _sayi((i.get("relative") or {}).get("value")), _sayi((i.get("rank") or {}).get("value"))) for i in items]
    rel = [(i, r, k) for i, r, k in rel if r is not None and k is not None]
    for (a, ra, ka) in rel:
        for (b, rb, kb) in rel:
            if ra > rb + 0.05 and ka > kb:
                yield _b("hata", "siralama", f"{a['name']} koleksiyon içi puanı ({ra:g}) {b['name']} ürününden ({rb:g}) yüksek, ama sırası "
                         f"daha geride ({int(ka)} > {int(kb)}).", skus=[a["sku"], b["sku"]], dayanak="ajan")
    for it in items:
        if it.get("decision") in ("üretme", "azalt") and not it.get("decision_reasons") and it.get("decision_source") != "kullanıcı":
            yield _b("uyarı", "siralama", f"{it['name']}: karar '{it['decision']}' ama gerekçe yazılmamış.", skus=[it["sku"]])
        if it.get("role") == "hero" and it.get("decision") == "üretme":
            yield _b("uyarı", "siralama", f"{it['name']}: rolü 'hero' (öne çıkan) ama kararı 'üretme'.", skus=[it["sku"]])
    by_cat: Dict[str, List[dict]] = {}
    for it in items:
        by_cat.setdefault(kategori_anahtari(it.get("category")) or "-", []).append(it)
    for grp in by_cat.values():
        for a in grp:
            for b in grp:
                if a is b:
                    continue
                pa, pb = _sayi((a.get("recommended_price") or {}).get("value")), _sayi((b.get("recommended_price") or {}).get("value"))
                aa, ab = _sayi((a.get("appeal") or {}).get("value")), _sayi((b.get("appeal") or {}).get("value"))
                qa, qb = _sayi((a.get("recommended_qty") or {}).get("value")), _sayi((b.get("recommended_qty") or {}).get("value"))
                if None in (pa, pb, aa, ab, qa, qb) or not pb or not qb:
                    continue
                if pa >= pb * (1 + SIRA_FIYAT_FARKI) and aa <= ab - SIRA_ILGI_FARKI and qa >= qb * SIRA_ADET_KATI:
                    yield _b("uyarı", "siralama",
                             f"{a['name']} {b['name']} ürününden daha pahalı ({_fmt(pa, 2)} > {_fmt(pb, 2)} USD) ve daha az ilgi görüyor "
                             f"({aa:g} < {ab:g}), ama daha çok adet önerilmiş ({int(qa)} > {int(qb)}). Maliyet, renk karışımı ya da "
                             "bölge payı kontrol edilmeli.", skus=[a["sku"], b["sku"]], dayanak="kural varsayımı")
        # bölge içinde: daha çok ilgi + daha ucuz ama daha az talep adedi
        regs = sorted({r["region"] for it in grp for r in it["regions"]})
        for reg in regs:
            rows = [(it, next((r for r in it["regions"] if r["region"] == reg), None)) for it in grp]
            rows = [(it, r) for it, r in rows if r]
            for a, ra in rows:
                for b, rb in rows:
                    if a is b:
                        continue
                    if (ra["demand"] >= rb["demand"] + SIRA_ILGI_FARKI and ra["optimal_price"] <= rb["optimal_price"]
                            and rb["demand_units"] and ra["demand_units"] < rb["demand_units"] / SIRA_ADET_KATI):
                        yield _b("uyarı", "siralama",
                                 f"{reg}: {a['name']} daha çok ilgi görüyor ({ra['demand']} > {rb['demand']}) ve daha ucuz, ama talep adedi "
                                 f"daha az ({ra['demand_units']} < {rb['demand_units']}).", skus=[a["sku"], b["sku"]], bolge=reg,
                                 dayanak="kural varsayımı")


@kural("panel_ayirt_etmedi", "koleksiyon", "Panel ürünleri ayırt etmedi",
       "Ürünlerin talep puanları neredeyse aynı (sıra ve roller anlamsız) ya da mevcut güven kontrolü (fiyat maliyetten, "
       "adet kitle varsayımından türemiş) uyarı verdi")
def _ayirt(s: Sonuc):
    ap = [_sayi((i.get("appeal") or {}).get("value")) for i in s.urunler() if i.get("regions")]
    ap = [x for x in ap if x is not None]
    if len(ap) >= 3 and max(ap) - min(ap) < DUZ_ILGI:
        yield _b("uyarı", "panel_ayirt_etmedi", f"{len(ap)} ürünün talep puanları {min(ap):g}-{max(ap):g} arasında; panel ürünleri "
                 "ayırt etmedi. Sıra, rol ve karar bu koşuda ürün farkını yansıtmaz.", dayanak="ajan")
    for i, a in enumerate((s.veri.get("summary") or {}).get("actions") or []):
        if (a.get("text") or "").startswith("Güven kontrolü:"):
            yield _b("uyarı", "panel_ayirt_etmedi", a["text"][len("Güven kontrolü:"):].strip(), alan=f"summary.actions[{i}]",
                     dayanak=a.get("basis") or "kural varsayımı")


@kural("erisim_egrisi", "koleksiyon", "Erişim eğrisi az ürüne / az kişiye dayanıyor",
       "Erişim eğrisi kendi içinde tutarsızsa (azalan erişim, toplamı tutmayan katkılar), tek ürünle doyuyorsa ya da "
       "eğrideki erişim 10 kişiden azına dayanıyorsa")
def _erisim(s: Sonuc):
    summ = s.veri.get("summary") or {}
    curve = summ.get("reach_curve") or []
    if not curve:
        return
    alan = "summary.reach_curve"
    adds = [p for p in curve if (p.get("added") or 0) > 0 or (_sayi(p.get("added_pct")) or 0) > 0]
    # tutarlılık: erişim azalmaz, katkılar toplamı son erişime eşit, son erişim kutudaki erişimle aynı
    prev = 0.0
    for i, p in enumerate(curve):
        r = _sayi(p.get("reach_pct")) or 0.0
        if r + 0.05 < prev:
            yield _b("hata", "erisim_egrisi", f"Erişim eğrisi {p.get('name')} ürününde azalıyor (%{prev:g} -> %{r:g}); "
                     "ürün eklemek erişimi düşüremez.", skus=[p.get("sku")], alan=f"{alan}[{i}]", dayanak="ajan")
        prev = max(prev, r)
    son = _sayi(curve[-1].get("reach_pct")) or 0.0
    top = sum(_sayi(p.get("added_pct")) or 0.0 for p in curve)
    if abs(top - son) > 0.15 * max(1, len(adds)):
        yield _b("hata", "erisim_egrisi", f"Erişim eğrisinde ürünlerin eklediği kişilerin toplamı %{top:.1f}, son erişim %{son:g}.",
                 alan=alan, dayanak="ajan")
    kutu = _sayi((summ.get("reach") or {}).get("value"))
    if kutu is not None and abs(kutu - son) > 0.15:
        yield _b("hata", "erisim_egrisi", f"Koleksiyon erişimi kutusu %{kutu:g}, erişim eğrisinin sonu %{son:g}; ikisi aynı olmalı.",
                 alan=alan, dayanak="ajan")
    n_panel = max((int(p.get("panel_n") or 0) for p in curve), default=0)
    ulasilan = sum(int(p.get("added") or 0) for p in curve)
    n_urun = summ.get("n_evaluated") or len([i for i in s.urunler() if i.get("regions")])
    if len(adds) == 1 and n_urun >= 3:
        ilk = adds[0]
        bos = [p for p in curve if p is not ilk and (p.get("added") or 0) == 0 and "enthusiasts" in p and not p.get("enthusiasts")]
        ort = [p for p in curve if p is not ilk and (p.get("enthusiasts") or 0) > 0]
        ayr = []
        if ort:
            ayr.append(f"{len(ort)} ürünün hevesli kişilerinin hepsi {ilk.get('name')} ürününü de seviyor")
        if bos:
            ayr.append(f"{len(bos)} ürüne kimse 70+ ilgi vermedi")
        kisi = f" ({n_panel} kişilik panelden {ulasilan} kişi)" if n_panel else ""
        yield _b("uyarı", "erisim_egrisi",
                 f"Erişim eğrisi tek ürünle doyuyor: {ilk.get('name')} panelin %{ilk.get('reach_pct')}'ine ulaşıyor{kisi}, "
                 f"diğer {n_urun - 1} ürün yeni kişi eklemiyor" + (f" ({'; '.join(ayr)})" if ayr else "") + ". "
                 "Bu çoğunlukla aynı birkaç kişinin her ürüne yüksek puan vermesinden ya da panelin küçük olmasından gelir; "
                 "'diğer ürünler gereksiz' diye okunmamalı.", skus=[ilk.get("sku")], alan=alan, dayanak="ajan")
    if n_panel and ulasilan and ulasilan < MIN_KISI:
        yield _b("uyarı", "erisim_egrisi", f"Erişim (%{son:g}) yalnızca {ulasilan} kişiye dayanıyor ({n_panel} kişilik panel, "
                 f"{MIN_KISI} altı): eğrinin şekli ve sıralaması kaba.", alan=alan, dayanak="ajan")


@kural("eksik_sonuc", "koleksiyon,tekli", "Eksik / başarısız sonuç",
       "Hiç ürün değerlendirilmedi, ürünlerin ya da bölgelerin bir kısmı hesaplanamadı")
def _eksik(s: Sonuc):
    if s.kapsam == "tekli":
        if not s.veri.get("regional_breakdown"):
            yield _b("hata", "eksik_sonuc", "Hiçbir bölge hesaplanamadı.")
        for f in s.veri.get("failed_regions") or []:
            yield _b("uyarı", "eksik_sonuc", f"{f.get('region')} hesaplanamadı: {f.get('reason')}", bolge=f.get("region"))
        return
    summ = s.veri.get("summary") or {}
    n, ne, nf = summ.get("n_items") or 0, summ.get("n_evaluated") or 0, summ.get("n_failed") or 0
    if n and ne == 0:
        yield _b("hata", "eksik_sonuc", f"{n} üründen hiçbiri değerlendirilemedi.")
    elif nf:
        yield _b("hata" if nf / n > BASARISIZ_HATA else "uyarı", "eksik_sonuc",
                 f"{n} üründen {nf} tanesi hesaplanamadı; koleksiyon içi sıra, erişim ve bütçe bunlar olmadan hesaplandı.")
    for it in s.urunler():
        if it.get("failed_regions"):
            yield _b("uyarı", "eksik_sonuc", f"{it['name']}: {', '.join(it['failed_regions'])} bölgesi hesaplanamadı.", skus=[it["sku"]])


@kural("bos_uc_deger", "koleksiyon,tekli", "Boş / NaN / aşırı uç değer",
       "NaN ya da sonsuz sayı, negatif adet/fiyat/maliyet, 0-100 dışında yüzde ya da talep puanı, değerlendirilmiş üründe boş "
       "ana metrik, aşırı yüksek iade oranı")
def _bos_uc(s: Sonuc):
    nan, neg, pct = [], [], []
    for yol, k, v, ust in _gez(s.veri):
        x = _sayi(v) if isinstance(v, (int, float)) else None
        if x is None:
            continue
        if math.isnan(x) or math.isinf(x):
            nan.append(yol)
            continue
        kl = k.lower()
        if x < 0 and re.search(r"(qty|units|price|cost|budget|count|shown|demand$|^demand_|fiyat|adet|maliyet)", kl) \
                and "pct" not in kl and "margin" not in kl and "delta" not in kl and "vs_" not in kl and "impact" not in kl \
                and "extra" not in kl and "change" not in kl and "unallocated" not in kl:
            neg.append(f"{yol}={x:g}")
        puan = kl == "demand_score_100" or (kl == "demand" and isinstance(ust, dict) and "optimal_price" in ust)
        if (kl.endswith("_pct") or kl == "pct" or puan) and "margin" not in kl and "vs_" not in kl \
                and "uplift" not in kl and "level" not in kl and "impact" not in kl and "discount" not in kl and "change" not in kl \
                and "_pts" not in kl and "delta" not in kl:
            if x < -0.01 or x > 100.5:
                pct.append(f"{yol}={x:g}")
        if "margin" in kl and kl.endswith(("_pct", "percentage")) and x > 100.5:
            pct.append(f"{yol}={x:g}")
    if nan:
        yield _b("hata", "bos_uc_deger", f"{len(nan)} alanda NaN/sonsuz değer: {', '.join(nan[:5])}{'…' if len(nan) > 5 else ''}.")
    if neg:
        yield _b("hata", "bos_uc_deger", f"{len(neg)} alanda negatif adet/fiyat/maliyet: {', '.join(neg[:5])}{'…' if len(neg) > 5 else ''}.")
    if pct:
        yield _b("hata", "bos_uc_deger", f"{len(pct)} alanda 0-100 dışında yüzde/puan: {', '.join(pct[:5])}{'…' if len(pct) > 5 else ''}.")
    if s.kapsam == "koleksiyon":
        for it in s.urunler():
            if not it.get("regions"):
                continue
            bos = [k for k in ("appeal", "recommended_price") if (it.get(k) or {}).get("value") is None]
            if bos:
                yield _b("uyarı", "bos_uc_deger", f"{it['name']}: değerlendirildi ama {', '.join(bos)} boş.", skus=[it["sku"]])
            for r in it["regions"]:
                if (_sayi(r.get("return_pct")) or 0) > UC_IADE:
                    yield _b("uyarı", "bos_uc_deger", f"{it['name']} {r['region']}: iade oranı %{r['return_pct']:g} (aşırı uç).",
                             skus=[it["sku"]], bolge=r["region"], dayanak="kural varsayımı")
                if r.get("demand", 0) >= 50 and r.get("demand_units") == 0:
                    yield _b("uyarı", "bos_uc_deger", f"{it['name']} {r['region']}: talep puanı {r['demand']} ama talep adedi 0.",
                             skus=[it["sku"]], bolge=r["region"])
    else:
        for r in s.veri.get("regional_breakdown") or []:
            ret = (r.get("returns") or {}).get("rate_pct")
            if ret is not None and ret > UC_IADE:
                yield _b("uyarı", "bos_uc_deger", f"{r['region']}: iade oranı %{ret:g} (aşırı uç).", bolge=r["region"])


@kural("etiketsiz_sayi", "koleksiyon,tekli", "Dayanağı yazılmamış sayı",
       "Ekranda gösterilen bir metrik, öneri ya da gerekçe dayanak (ajan / kural varsayımı / LLM tahmini / ERP / kullanıcı "
       "girdisi) taşımıyor")
def _etiket(s: Sonuc):
    yok, gecersiz, nasil = [], [], 0
    for yol, k, v, ust in _gez(s.veri):
        if not isinstance(v, dict):
            continue
        is_metric = "value" in v and isinstance(v.get("value"), (int, float))
        is_text = "text" in v and ("kind" in v or yol.endswith(("decision_reasons", "reasons")) or re.search(r"(reasons|actions)\[\d+\]$", yol))
        if not (is_metric or is_text):
            continue
        b = v.get("basis")
        if not b:
            yok.append(yol)
        elif s.kapsam == "koleksiyon" and b not in DAYANAKLAR:
            gecersiz.append(f"{yol}='{b}'")
        elif is_metric and v.get("value") is not None and "how" in v and not v.get("how"):
            nasil += 1
    if s.kapsam == "tekli":
        for r in s.veri.get("regional_breakdown") or []:
            for blok in ("returns", "forecast", "price_plan", "seasonality"):
                if r.get(blok) and not r[blok].get("basis"):
                    yok.append(f"{r['region']}.{blok}")
            for i, c in enumerate(r.get("campaigns") or []):
                if not c.get("basis"):
                    yok.append(f"{r['region']}.campaigns[{i}]")
    if yok:
        yield _b("hata", "etiketsiz_sayi", f"{len(yok)} sayının dayanağı yazılmamış: {', '.join(yok[:5])}{'…' if len(yok) > 5 else ''}.")
    if gecersiz:
        yield _b("uyarı", "etiketsiz_sayi", f"{len(gecersiz)} sayının dayanağı tanımlı listede değil: {', '.join(gecersiz[:5])}.")
    if nasil:
        yield _b("bilgi", "etiketsiz_sayi", f"{nasil} metrikte 'nasıl hesaplandı' açıklaması boş.")


# =====================================================================
# Müşteri verisi (ürün listesi) kuralları: ilk veri testi
# =====================================================================

@kural("veri_urun", "veri", "Ürün listesi tutarlılığı",
       "Tekrarlayan SKU, maliyeti boş/sıfır/negatif ürün, boş kategori, aynı kategorinin farklı yazımları, kategorisine göre "
       "aşırı uç maliyet")
def _veri_urun(s: Sonuc):
    items = s.urunler()
    seen: Dict[str, int] = {}
    for it in items:
        seen[it.get("sku") or ""] = seen.get(it.get("sku") or "", 0) + 1
    dup = [k for k, n in seen.items() if n > 1 and k]
    if dup:
        yield _b("hata", "veri_urun", f"{len(dup)} SKU birden fazla satırda: {', '.join(dup[:5])}.", skus=dup[:20], dayanak="kullanıcı girdisi")
    nocost = [i["sku"] for i in items if (_sayi(i.get("unit_cost")) or 0) <= 0]
    if nocost:
        yield _b("hata", "veri_urun", f"{len(nocost)} üründe maliyet boş, sıfır ya da negatif: {', '.join(nocost[:5])}"
                 f"{'…' if len(nocost) > 5 else ''}. Fiyat ve bütçe hesabı yapılamaz.", skus=nocost[:20], dayanak="kullanıcı girdisi")
    nocat = [i["sku"] for i in items if not kategori_anahtari(i.get("category"))]
    if nocat:
        yield _b("uyarı", "veri_urun", f"{len(nocat)} üründe kategori boş; kategori kuralları (müşteri paylaşımı, sıralama) bu ürünlere "
                 "uygulanamaz.", skus=nocat[:20], dayanak="kullanıcı girdisi")
    yazim: Dict[str, set] = {}
    for i in items:
        if i.get("category"):
            yazim.setdefault(kategori_anahtari(i["category"]), set()).add(i["category"].strip())
    for k, v in yazim.items():
        if len(v) > 1:
            yield _b("uyarı", "veri_urun", f"Aynı kategori farklı yazılmış: {', '.join(sorted(v))}. Sistem bunları aynı sayar; "
                     "ERP'de tek yazıma indirin.", dayanak="kullanıcı girdisi")
    by: Dict[str, List[Tuple[str, float]]] = {}
    for i in items:
        c = _sayi(i.get("unit_cost"))
        if c and c > 0:
            by.setdefault(kategori_anahtari(i.get("category")) or "-", []).append((i["sku"], c))
    for k, rows in by.items():
        if len(rows) < 3:
            continue
        med = statistics.median(c for _, c in rows)
        uc = [sku for sku, c in rows if c > 5 * med or c < med / 5]
        if uc:
            yield _b("uyarı", "veri_urun", f"{len(uc)} ürünün maliyeti kategorisinin medyanının 5 katından fazla ya da 5'te birinden az "
                     f"(medyan {_fmt(med, 2)}): {', '.join(uc[:5])}. Birim/para birimi hatası olabilir.", skus=uc[:20],
                     dayanak="kullanıcı girdisi")
    for iss in s.ek.get("issues") or []:
        yield _b(iss.get("level", "uyarı"), "veri_urun", iss.get("message", ""), skus=[iss["sku"]] if iss.get("sku") else [],
                 dayanak="kullanıcı girdisi")
