"""MiroFish için hedef kitleye göre sıfırdan kurulan kişiler (Zep yok).

Her (bölgeler, hedef kitle) için ayrı bir MiroFish dünyası kurulur. Kişiler burada üretilir ve MiroFish'e
/api/graph/local ile doğrudan verilir; Zep bilgi grafiği kullanılmaz. Bölge başına n kişi
(n = MIROFISH_AGENTS_PER_REGION):

- kadin/erkek/unisex: kadın payı ve yaş bantları o kitlenin bölge dağılımından (panel_data/hedef_kitle/dagilim.json);
- cocuk: hepsi ebeveyn (anne payı ve ebeveyn yaşı çocuk dağılımından), her birinin çocuğunun yaşı ve cinsiyetiyle;
  ürün kız ya da erkek çocuk içinse hepsinin çocuğu o cinsiyettendir.

Her kişiye bölgenin persona kütüphanesinden yaşına uyan segment (şehir, gelir, tarz, alışveriş) verilir. Adlar
uydurmadır (panel_data/hedef_kitle/isimler.json). Liste deterministiktir: aynı veri aynı dünyayı verir; dağılım ya da
persona seti değişirse liste değişir ve dünya yeniden kurulur.
"""
import hashlib
import json
import random
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .. import audience as audlib

DATA = Path(__file__).resolve().parents[2] / "panel_data"
_INCOME = {"düşük": "düşük gelirli", "orta-alt": "orta-alt gelirli", "orta": "orta gelirli",
           "orta-üst": "orta-üst gelirli", "yüksek": "yüksek gelirli"}


def _h(*parts) -> int:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:12], 16)


def _segments(region: str) -> List[dict]:
    try:
        from ..panel.library import PanelStore
        lib = PanelStore(DATA).personas(region)
        return [s.model_dump() for s in lib.segments]
    except Exception:       # persona seti yoksa bölge adıyla nötr segment
        return [{"label": "tüketici", "city": region, "weight": 1, "age_range": (18, 70), "income_band": "orta",
                 "style_affinity": [], "channel_habits": []}]


def _names(region: str) -> dict:
    d = json.loads((DATA / "hedef_kitle" / "isimler.json").read_text(encoding="utf-8"))
    return d.get(region) or d["EU"]


def _ages(bands, k: int, rng: random.Random) -> List[int]:
    counts = audlib._allocate([w for _, _, w in bands], k)
    out = [rng.randint(lo, hi) for (lo, hi, _), c in zip(bands, counts) for _ in range(c)]
    rng.shuffle(out)
    return out


def _segment_for(age: int, segs: List[dict], rng: random.Random) -> dict:
    fit = [s for s in segs if s["age_range"][0] <= age <= s["age_range"][1]] or segs
    return rng.choices(fit, weights=[s["weight"] for s in fit])[0]


COUNTRY = {"TR": "Türkiye", "EU": "Avrupa", "MENA": "Körfez ülkeleri", "CIS": "BDT ülkeleri", "US": "ABD"}


@lru_cache(maxsize=64)
def build_people(region: str, n: int, audience: str = "unisex", child: Optional[str] = None) -> Tuple[dict, ...]:
    """Bölgede bu hedef kitle için n kişi: cinsiyet kotası ve yaş bantları bölgenin kalibre dağılımından.

    kadin/erkek/unisex: kadın payı ve yaş bantları o kitlenin dağılımından. cocuk: kişilerin hepsi ebeveyn
    (anne payı ve ebeveyn yaşı çocuk dağılımından), her birinin çocuğunun yaşı ve cinsiyetiyle.
    Deterministik: aynı veri aynı listeyi (ve aynı MiroFish dünyasını) verir.
    """
    rng = random.Random(_h("dunya", region, n, audience, child or ""))
    dist = audlib.load_dist()
    rd = dist.regions.get(region) or dist.regions["_varsayilan"]
    d = getattr(rd, audience)
    segs = _segments(region)
    names = _names(region)
    used = set()

    def name(female: bool) -> str:
        pool = names["kadin" if female else "erkek"]
        for _ in range(500):
            nm = f"{rng.choice(pool)} {rng.choice(names['soyad'])}"
            if nm not in used:
                used.add(nm)
                return nm
        raise ValueError(f"{region}: isimler.json yeterli benzersiz ad üretmiyor")

    n_f = round(n * d.female_share)
    lo_c, hi_c = d.child_age_range or (2, 12)
    people: List[dict] = []
    for female, k in ((True, n_f), (False, n - n_f)):
        for age in _ages(d.age_bands, k, rng):
            parent = audience == "cocuk"
            people.append({"female": female, "age": age, "parent": parent,
                           "child_age": rng.randint(lo_c, hi_c) if parent else None,
                           "child_female": ((child == "kız") if child in ("kız", "erkek") else rng.random() < 0.5)
                                           if parent else None})
    rng.shuffle(people)
    for p in people:
        s = _segment_for(p["age"], segs, rng)
        p.update({"name": name(p["female"]), "region": region, "city": s["city"], "segment": s["label"],
                  "income": _INCOME.get(s.get("income_band", "orta"), ""), "style": list(s.get("style_affinity") or [])[:3],
                  "habits": list(s.get("channel_habits") or [])[:3]})
    return tuple(people)


def seed_line(p: dict) -> str:
    """'Ad Soyad, 34, Şehir, kadın; ...' (personas.seed_person bu biçimi okur)."""
    g = "kadın" if p["female"] else "erkek"
    parts = [f"{p['name']}, {p['age']}, {p['city']}, {g}", f"{p['segment']}, {p['income']}"]
    if p["style"]:
        parts.append("tarzı: " + ", ".join(p["style"]))
    if p["habits"]:
        parts.append("alışveriş: " + ", ".join(p["habits"]))
    if p["parent"]:
        kid = "kızı" if p["child_female"] else "oğlu"
        parts.append(f"{'anne' if p['female'] else 'baba'}, {p['child_age']} yaşında {kid} var")
    return "; ".join(parts)


def entity(p: dict) -> dict:
    """MiroFish /api/graph/local kişi kaydı: yaş/cinsiyet/ülke/meslek profil üretiminde LLM'in önüne geçer."""
    return {"name": p["name"], "type": "Person",
            "summary": f"{seed_line(p)} ({p['region']} bölgesi tüketicisi)",
            "attributes": {"age": p["age"], "gender": "female" if p["female"] else "male",
                           "country": COUNTRY.get(p["region"], p["region"]), "profession": p["segment"],
                           "region": p["region"]}}


def person_meta(p: dict) -> dict:
    return {"name": p["name"], "age": p["age"], "female": p["female"], "parent": p["parent"],
            "child_age": p["child_age"], "child_female": p["child_female"], "region": p["region"]}


def audience_key(card: dict) -> Tuple[str, Optional[str]]:
    """Karttaki hedef kitle -> dünya anahtarı (kitle, çocuk cinsiyeti). Kitle yoksa karışık (unisex) dünya."""
    info = card.get("target_audience") or {}
    value = info.get("value") if info.get("value") in audlib.LABEL else "unisex"
    child = info.get("child_gender") if value == "cocuk" and info.get("child_gender") in ("kız", "erkek") else None
    return value, child


def world_people(regions: Sequence[str], n: int, audience: str, child: Optional[str] = None) -> List[dict]:
    return [p for r in regions for p in build_people(r, n, audience, child)]


def label(audience: str, child: Optional[str] = None) -> str:
    base = audlib.LABEL.get(audience, audience)
    return f"{base} ({child})" if child else base


def requirement(regions: Sequence[str], audience: str, child: Optional[str] = None) -> str:
    return (
        f"{len(regions)} bölgesel pazardaki ({', '.join(regions)}) tüketicilerin yeni moda/tekstil ürünlerini nasıl "
        f"değerlendirdiğini simüle et. Panel bu ürünlerin hedef kitlesi ({label(audience, child)}) için kuruldu. Her kişi "
        "kendi şehrinin iklimini, kültürünü ve satın alma önceliklerini korur; ürünler hakkında fikir paylaşır, fiyat "
        "algısını ve itirazlarını tartışır. Kişilerin adı, yaşı, cinsiyeti, şehri, ülkesi ve ebeveynliği verildiği gibi "
        "kullanılır, değiştirilmez. Profil metinleri Türkçe ya da İngilizce yazılır, Çince yazılmaz."
    )


def document(regions: Sequence[str], n: int, audience: str, child: Optional[str] = None) -> str:
    """Bağlam metni (MiroFish simülasyon ayarı üretirken okur); içeriği dünya önbellek anahtarına da girer."""
    lines = [f"# Bölgesel tüketici paneli (hedef kitle: {label(audience, child)})", ""]
    for r in regions:
        lines += [f"## {r} bölgesinde yaşayan bireysel tüketiciler", ""]
        lines += [f"- {seed_line(p)}" for p in build_people(r, n, audience, child)]
        lines.append("")
    return "\n".join(lines)
