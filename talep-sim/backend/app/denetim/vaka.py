"""Regresyon vakaları: bilinen mantık hatalarının kayıtlı örnekleri (tests/denetim_vakalari/*.json).

Bir vaka iki şeyi kilitler:
  1. sonuc + sonuc_beklenen: hatalı çıktı kaydedilir; denetim bu çıktıda beklenen bulguları MUTLAKA vermeli
     (denetim hatayı yakalamayı unutmasın).
  2. girdi + girdi_olmamali: aynı koşunun girdileri bugünkü kodla yeniden hesaplanır; listelenen bulgular ÇIKMAMALI
     (hata kodda düzeldiyse geri gelmesin). durum "acik" iken bu kısım beklenen başarısızlık sayılır.

Yeni vaka eklemek tek komut (Mac'te, backend klasöründe):
    python -m app.denetim vaka-ekle --koleksiyon <id> --ad kisa-ad --aciklama "ne yanlıştı"
Komut girdiyi ve bugünkü çıktıyı anonimleştirip kaydeder, denetimin bunu yakalayıp yakalamadığını yazar.
"""
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import denetle_koleksiyon, denetle_tahmin, denetle_urunler
from .model import DenetimRaporu

VAKA_DIR = Path(__file__).resolve().parents[2] / "tests" / "denetim_vakalari"

# sonuç hesabında kullanılmayan, kişisel ya da metin içeren alanlar (anonimleştirmede atılır)
_BOLGE_TUT = {"region", "demand_score_100", "optimal_sale_price", "estimated_margin_percentage", "van_westendorp", "allocation",
              "returns", "raw_answers", "confidence", "data_basis", "audience_panel", "recommended_production_qty"}


def _harita(col: dict) -> Dict[str, str]:
    """Gerçek ad / SKU / marka -> anonim karşılık. Uzun olan önce değiştirilir."""
    h: Dict[str, str] = {}
    sayac: Dict[str, int] = {}
    for n, it in enumerate(col["items"], 1):
        cat = (it.get("category") or "urun").strip()
        sayac[cat] = sayac.get(cat, 0) + 1
        h[it["sku"]] = f"U{n:02d}"
        if it.get("name"):
            h[it["name"]] = f"{cat.title()} {sayac[cat]}"
    meta = col.get("meta") or {}
    for k in ("brand", "name"):
        if meta.get(k):
            h[meta[k]] = "Marka" if k == "brand" else "Vaka koleksiyonu"
    bp = meta.get("brand_profile") or {}
    if bp.get("name"):
        h[bp["name"]] = "Marka"
    return dict(sorted(h.items(), key=lambda kv: -len(kv[0])))


def _degistir(o: Any, h: Dict[str, str]) -> Any:
    if isinstance(o, str):
        if o in h:
            return h[o]
        for a, b in h.items():
            if len(a) >= 3 and a in o:
                o = re.sub(r"(?<!\w)" + re.escape(a) + r"(?!\w)", b, o)
        return o
    if isinstance(o, list):
        return [_degistir(x, h) for x in o]
    if isinstance(o, dict):
        return {_degistir(k, h) if isinstance(k, str) else k: _degistir(v, h) for k, v in o.items()}
    return o


def _kirp_sonuc(r: dict) -> dict:
    """Ürün sonucu dosyasından yalnızca koleksiyon hesabının okuduğu alanlar; ajan metinleri atılır."""
    resp = r.get("response")
    if not resp:
        return {"error": r.get("error") or "sonuç yok"}
    regs = []
    for rb in resp.get("regional_breakdown") or []:
        x = {k: v for k, v in rb.items() if k in _BOLGE_TUT}
        x["key_objections"] = []
        vw = dict(x.get("van_westendorp") or {})
        vw.pop("curve", None)
        x["van_westendorp"] = vw
        x["raw_answers"] = [{k: v for k, v in a.items() if k != "text"} for a in rb.get("raw_answers") or []]
        db = x.get("data_basis") or {}
        x["data_basis"] = {k: db[k] for k in ("persona_version", "context_version") if k in db}
        regs.append(x)
    out = {"panel_seed": r.get("panel_seed"), "response": {
        "regional_breakdown": regs, "failed_regions": [{"region": f.get("region"), "reason": f.get("reason")} for f in resp.get("failed_regions") or []],
        "target_audience": resp.get("target_audience"), "brand_profile": resp.get("brand_profile")}}
    return out


def _kirp_vitrin(recs: Dict[str, list]) -> Dict[str, list]:
    out = {}
    for reg, rows in recs.items():
        rr = []
        for x in rows:
            y = {k: v for k, v in x.items() if k not in ("text",)}
            if isinstance(y.get("answer"), dict):
                y["answer"] = {k: v for k, v in y["answer"].items() if k != "comment"}
            rr.append(y)
        out[reg] = rr
    return out


def sonuc_temizle(sonuc: dict) -> dict:
    """Kayıtlı çıktıdan ajanların serbest metinleri (yorum, itiraz) atılır: ürün/marka adı geçebilir."""
    if sonuc.get("showcase"):
        sonuc["showcase"]["comments"] = []
    for it in sonuc.get("items") or []:
        it["image"] = None
        for r in it.get("regions") or []:
            r["objections"] = []
    return sonuc


def girdi_topla(store, cid: str, fx_rate: float, anonim: bool = True) -> Tuple[dict, Dict[str, str]]:
    col = store.load(cid)
    cd = json.loads(col.model_dump_json())
    for it in cd["items"]:
        it["images"] = [f"{i}.jpg" for i in range(len(it.get("images") or []))]
        it["color_images"] = {}
        it["technical_specs"] = ""
    cd["meta"]["brand_notes"] = ""
    cd["meta"]["notes"] = ""
    res = {s: _kirp_sonuc(r) for s, r in store.results(cid, [i.sku for i in col.items]).items()}
    g = {"collection": cd, "results": res, "showcase": _kirp_vitrin(store.showcase(cid)), "fx_rate": fx_rate}
    h = _harita(json.loads(col.model_dump_json())) if anonim else {}
    return (_degistir(g, h) if anonim else g), h


def girdiden_hesapla(girdi: dict):
    from ..collection.models import Collection
    from ..collection.summary import summarize
    col = Collection.model_validate(girdi["collection"])
    return summarize(col, girdi["results"], float(girdi.get("fx_rate") or 1.0), showcase=girdi.get("showcase") or {})


def _denetle(tur: str, veri: dict, ek: Optional[dict] = None) -> DenetimRaporu:
    if tur == "tekli":
        return denetle_tahmin(veri, **(ek or {}))
    if tur == "veri":
        return denetle_urunler(veri.get("items") or [], veri.get("issues"))
    return denetle_koleksiyon(veri)


def _eslesir(rapor: DenetimRaporu, kosul: dict) -> bool:
    return any(kosul.get("kural", "*") in ("*", b.kural) and (not kosul.get("seviye") or b.seviye == kosul["seviye"])
               and (not kosul.get("icerir") or kosul["icerir"] in b.mesaj) for b in rapor.bulgular)


def vaka_calistir(v: dict) -> List[str]:
    """Vakanın sağlanmayan koşullarını döner (boş liste = geçti). 'acik' vakada girdi kısmı ayrı raporlanır."""
    sorun: List[str] = []
    tur = v.get("tur", "koleksiyon")
    if "sonuc" in v:
        r = _denetle(tur, v["sonuc"], v.get("ek"))
        for k in v.get("sonuc_beklenen") or []:
            if not _eslesir(r, k):
                sorun.append(f"[kayıtlı çıktı] denetim şunu bulmalıydı ama bulmadı: {k}")
        for k in v.get("sonuc_olmamali") or []:
            if _eslesir(r, k):
                sorun.append(f"[kayıtlı çıktı] yanlış alarm: {k}")
    if "girdi" in v:
        r = girdiden_hesapla(v["girdi"]).denetim
        for k in v.get("girdi_olmamali") or []:
            if _eslesir(r, k):
                sorun.append(f"[bugünkü kod] hata geri geldi ya da düzelmedi: {k}")
        for k in v.get("girdi_beklenen") or []:
            if not _eslesir(r, k):
                sorun.append(f"[bugünkü kod] beklenen bulgu yok: {k}")
    return sorun


def vakalar(klasor: Path = VAKA_DIR) -> List[Tuple[str, dict]]:
    return [(p.stem, json.loads(p.read_text(encoding="utf-8"))) for p in sorted(klasor.glob("*.json"))]


def vaka_ekle(store, cid: str, ad: str, aciklama: str, fx_rate: float, beklenen: List[dict],
              anonim: bool = True, klasor: Path = VAKA_DIR) -> Tuple[Path, DenetimRaporu, List[str]]:
    """Koleksiyonun girdisini ve bugünkü çıktısını vaka olarak kaydeder.

    beklenen boşsa: bugünkü çıktıdaki hata ve uyarılar beklenen sayılır (denetim zaten yakalıyorsa).
    Denetim hiçbir şey bulmuyorsa vaka yine kaydedilir; test kural yazılana kadar başarısız olur (yapılacak işin işareti).
    """
    import time

    girdi, h = girdi_topla(store, cid, fx_rate, anonim)
    res = girdiden_hesapla(girdi)
    sonuc = sonuc_temizle(json.loads(res.model_dump_json(exclude={"denetim"})))
    rapor = res.denetim
    if not beklenen:
        beklenen = [{"kural": b.kural, "seviye": b.seviye} for b in rapor.bulgular if b.seviye in ("hata", "uyarı")]
        beklenen = [dict(t) for t in {tuple(sorted(x.items())) for x in beklenen}]
    hatalar = [k for k in beklenen if k.get("seviye") == "hata"]
    v = {
        "ad": ad, "tarih": time.strftime("%Y-%m-%d"), "aciklama": aciklama, "tur": "koleksiyon",
        "durum": "acik" if hatalar else "kapali",
        "anonim": anonim,
        "sonuc": sonuc, "sonuc_beklenen": beklenen,
        "girdi": girdi, "girdi_olmamali": hatalar,
    }
    klasor.mkdir(parents=True, exist_ok=True)
    yol = klasor / f"{re.sub(r'[^a-z0-9-]+', '-', ad.lower()).strip('-') or 'vaka'}.json"
    yol.write_text(json.dumps(v, ensure_ascii=False, indent=1), encoding="utf-8")
    eksik = [f"{k}" for k in beklenen if not _eslesir(rapor, k)]
    return yol, rapor, eksik
