"""Ürünün hedef kitlesi (kadın / erkek / çocuk / unisex) ve panelin bu kitleye göre seçilmesi.

- Kullanıcı (ekran ya da Excel `hedef_kitle` sütunu) yazdıysa o kullanılır: dayanak "kullanıcı girdisi".
- Boşsa ürün adı, kategori, içerik ve beden aralığındaki ipucu kelimelerinden tahmin edilir: dayanak "tahmin".
  İpucu yoksa unisex (karışık panel) varsayılır ve bu da "tahmin" olarak etiketlenir. Marka listesi yoktur;
  ipucu kelimeleri veri dosyasıdır (panel_data/hedef_kitle/anahtar_kelimeler.json), müşteri kendi terimlerini ekler.
- Panelin cinsiyet ve yaş dağılımı bölge bazında veri dosyasından gelir (panel_data/hedef_kitle/dagilim.json):
  EU ve TR ayrı kalibre edilir, diğer bölgeler genel varsayımı kullanır ve bu sonuçta yazılır. Dosya doğrulanmamış
  bir kural varsayımıdır; müşterinin ERP/CRM alıcı verisiyle değiştirilmelidir.
- Persona panelinde kişiler bu dağılıma göre kota ile seçilir (12 kişide 0,85 kadın payı = 10 kadın, 2 erkek).
  MiroFish dünyasındaki kişiler sabit olduğu için orada cevaplar dağılıma göre ağırlıklandırılır (sonradan tabakalama).
"""
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, List, Literal, Optional, Sequence, Tuple

from pydantic import BaseModel, Field

AudienceValue = Literal["kadin", "erkek", "cocuk", "unisex"]
AudienceSource = Literal["kullanıcı girdisi", "tahmin"]
AUDIENCES: Tuple[str, ...] = ("kadin", "erkek", "cocuk", "unisex")
LABEL = {"kadin": "Kadın", "erkek": "Erkek", "cocuk": "Çocuk", "unisex": "Unisex"}
DATA_DIR = Path(__file__).resolve().parents[1] / "panel_data" / "hedef_kitle"
MAX_WEIGHT = 3.0          # ağırlıklandırmada tek kişinin etkisi ortalamanın en fazla 3 katı


class AudienceInfo(BaseModel):
    """Ürünün hedef kitlesi ve dayanağı."""
    value: AudienceValue
    label: str
    source: AudienceSource
    reason: str = ""
    child_gender: Optional[Literal["kız", "erkek"]] = None
    child_age_range: Optional[Tuple[int, int]] = None
    raw: str = Field("", description="Kullanıcının yazdığı değer (ör. 'kız çocuk')")


def fold(s: str) -> str:
    """Türkçe karakter ve büyük/küçük harf farkını kaldırır."""
    s = (s or "").replace("İ", "i").replace("I", "ı").lower()
    s = s.translate(str.maketrans("ıçğöşü", "icgosu"))
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


_CHILD_GIRL = ("kiz cocuk", "kiz", "girls", "girl")
_CHILD_BOY = ("erkek cocuk", "boys", "boy")
_BABY = ("bebek", "baby", "infant", "newborn")
_SYN = {
    "cocuk": ("cocuk", "kids", "kid", "child", "children", "junior", "genc"),
    "kadin": ("kadin", "bayan", "women", "woman", "womens", "ladies", "female", "k"),
    "erkek": ("erkek", "bay", "men", "man", "mens", "male", "e"),
    "unisex": ("unisex", "uniseks", "cinsiyetsiz", "genderless", "karma", "herkes", "ortak", "u"),
}


def normalize(text: Optional[str]) -> Optional[AudienceInfo]:
    """Kullanıcının yazdığı değeri dört kitleden birine çevirir; tanınmazsa None."""
    n = re.sub(r"[^a-z ]+", " ", fold(text or "")).strip()
    n = re.sub(r"\s+", " ", n)
    if not n:
        return None
    raw = (text or "").strip()
    if n in _BABY or n.startswith("bebek"):
        return AudienceInfo(value="cocuk", label="Çocuk (bebek)", source="kullanıcı girdisi", raw=raw,
                            child_age_range=(0, 2), reason="Kullanıcı girdisi")
    if n in _CHILD_GIRL or n.startswith("kiz cocu"):
        return AudienceInfo(value="cocuk", label="Çocuk (kız)", source="kullanıcı girdisi", raw=raw,
                            child_gender="kız", reason="Kullanıcı girdisi")
    if n in _CHILD_BOY or n.startswith("erkek cocu"):
        return AudienceInfo(value="cocuk", label="Çocuk (erkek)", source="kullanıcı girdisi", raw=raw,
                            child_gender="erkek", reason="Kullanıcı girdisi")
    for value, words in _SYN.items():
        if n in words or n.split(" ")[0] in words and len(n.split(" ")[0]) > 1:
            return AudienceInfo(value=value, label=LABEL[value], source="kullanıcı girdisi", raw=raw,
                                reason="Kullanıcı girdisi")
    return None


def _keywords(root: Optional[Path] = None) -> Dict[str, List[Tuple[str, str]]]:
    """Kitle -> [(yazıldığı hali, sadeleştirilmiş hali)], uzun ifadeler önce ("erkek çocuk" "erkek"ten önce)."""
    path = (root or DATA_DIR) / "anahtar_kelimeler.json"
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {k: [] for k in AUDIENCES}
    out = {}
    for k in AUDIENCES:
        seen, pairs = set(), []
        for w in sorted(d.get(k, []), key=lambda w: -len(w)):
            if fold(w) not in seen:
                seen.add(fold(w))
                pairs.append((w, fold(w)))
        out[k] = pairs
    return out


def _hit(text: str, word: str) -> bool:
    """Kelime eşleşmesi: kısa kelimeler tam kelime, 4+ harfliler kelime başından (elbise -> elbisesi)."""
    if " " in word:
        return re.search(rf"(?<![a-z]){re.escape(word)}", text) is not None
    tail = "" if len(word) < 4 else "[a-z]*"
    return re.search(rf"(?<![a-z]){re.escape(word)}{tail}(?![a-z])", text) is not None


_AGE_SIZE = re.compile(r"\b\d{1,2}\s*(?:-|/)\s*\d{1,2}\s*(?:yas|ay|y|m)\b")


def guess(name: str = "", category: str = "", subcategory: str = "", specs: str = "", sizes: str = "",
          root: Optional[Path] = None) -> AudienceInfo:
    """Boş hedef kitle için tahmin. Öncelik: açık kitle kelimesi > beden aralığı (yaş) > ürün tipi kelimesi > unisex."""
    kw = _keywords(root)
    fields = [("ürün adı", name), ("kategori", f"{category} {subcategory}"), ("içerik", specs)]
    # 1) çocuk her zaman önce: "erkek çocuk tişört" erkek değil çocuk ürünüdür
    for where, txt in fields:
        t = fold(txt)
        for orig, w in kw["cocuk"]:
            if _hit(t, w):
                info = normalize(w)
                if info is None or info.value != "cocuk":
                    info = AudienceInfo(value="cocuk", label="Çocuk", source="tahmin")
                return info.model_copy(update={"source": "tahmin", "raw": "",
                                               "reason": f"{where} içinde '{orig}' geçiyor"})
    if _AGE_SIZE.search(fold(sizes)):
        return AudienceInfo(value="cocuk", label="Çocuk", source="tahmin",
                            reason=f"beden aralığı yaş/ay ile yazılmış ({sizes})")
    for where, txt in fields:
        t = fold(txt)
        found = {v: next((o for o, w in kw[v] if _hit(t, w)), None) for v in ("unisex", "kadin", "erkek")}
        found = {v: w for v, w in found.items() if w}
        if "unisex" in found:
            return AudienceInfo(value="unisex", label="Unisex", source="tahmin",
                                reason=f"{where} içinde '{found['unisex']}' geçiyor")
        if len(found) == 1:
            v, w = next(iter(found.items()))
            return AudienceInfo(value=v, label=LABEL[v], source="tahmin", reason=f"{where} içinde '{w}' geçiyor")
        if len(found) == 2:
            return AudienceInfo(value="unisex", label="Unisex", source="tahmin",
                                reason=f"{where} hem kadın ('{found['kadin']}') hem erkek ('{found['erkek']}') ipucu içeriyor")
    return AudienceInfo(value="unisex", label="Unisex", source="tahmin",
                        reason="ad, kategori ve içerikte kitle ipucu yok; karışık panel varsayıldı")


def resolve(user_value: Optional[str], name: str = "", category: str = "", subcategory: str = "", specs: str = "",
            sizes: str = "", root: Optional[Path] = None) -> AudienceInfo:
    """Kullanıcı değeri tanınırsa o, değilse tahmin. Tanınmayan değer tahmine düşer ve gerekçede yazılır."""
    info = normalize(user_value)
    if info:
        return info
    g = guess(name, category, subcategory, specs, sizes, root)
    if user_value and user_value.strip():
        g = g.model_copy(update={"reason": f"'{user_value.strip()}' tanınmadı (kadın / erkek / çocuk / unisex); {g.reason}"})
    return g


# ---------------------------------------------------------------- bölge dağılımı (kalibrasyon)
class AudienceDist(BaseModel):
    female_share: float = Field(..., ge=0, le=1)
    age_bands: List[Tuple[int, int, float]] = Field(..., min_length=1)
    child_age_range: Optional[Tuple[int, int]] = None


class RegionDist(BaseModel):
    source: str = ""
    kadin: AudienceDist
    erkek: AudienceDist
    unisex: AudienceDist
    cocuk: AudienceDist


class DistFile(BaseModel):
    version: str
    as_of: date
    review_by: Optional[date] = None
    verified: bool = False
    owner: str = ""
    source: str = ""
    regions: Dict[str, RegionDist]


@dataclass
class AudiencePlan:
    """Bir bölgede panelin hangi dağılımla kurulacağı."""
    info: AudienceInfo
    region: str
    dist: AudienceDist
    region_specific: bool
    version: str
    as_of: str
    verified: bool
    source: str
    warnings: List[str] = field(default_factory=list)

    def calibration(self) -> dict:
        return {"version": self.version, "as_of": self.as_of, "verified": self.verified,
                "region_specific": self.region_specific, "source": self.source, "basis": "kural varsayımı"}


def load_dist(root: Optional[Path] = None) -> DistFile:
    path = (root or DATA_DIR) / "dagilim.json"
    return DistFile.model_validate(json.loads(path.read_text(encoding="utf-8")))


def plan_for(info: AudienceInfo, region: str, root: Optional[Path] = None) -> AudiencePlan:
    f = load_dist(root)
    rd = f.regions.get(region)
    specific = rd is not None
    rd = rd or f.regions["_varsayilan"]
    dist = getattr(rd, info.value)
    if info.value == "cocuk" and info.child_age_range:
        dist = dist.model_copy(update={"child_age_range": info.child_age_range})
    warn = []
    if not specific:
        warn.append(f"{region}: hedef kitle cinsiyet/yaş dağılımı bu bölge için ayrı kalibre edilmedi; genel varsayım kullanıldı.")
    if not f.verified:
        warn.append(f"{region}: hedef kitle dağılımı ({f.version}) doğrulanmamış kural varsayımı; ERP/CRM alıcı verisiyle güncellenmeli.")
    return AudiencePlan(info, region, dist, specific, f.version, f.as_of.isoformat(), f.verified,
                        rd.source or f.source, warn)


def band_label(lo: int, hi: int) -> str:
    return f"{lo}-{hi}"


def _allocate(weights: Sequence[float], n: int) -> List[int]:
    total = sum(weights) or 1.0
    raw = [w / total * n for w in weights]
    counts = [int(r) for r in raw]
    for i in sorted(range(len(raw)), key=lambda i: raw[i] - counts[i], reverse=True)[: n - sum(counts)]:
        counts[i] += 1
    return counts


def buyer_role(value: str, female: bool) -> str:
    """kendisi: ürünü kendisi için alır; hediye: karşı cins ürününü yakını için alır; ebeveyn: çocuğu için alır."""
    if value == "cocuk":
        return "ebeveyn"
    if value == "kadin" and not female or value == "erkek" and female:
        return "hediye"
    return "kendisi"


def composition(people: Sequence[Tuple[Optional[bool], Optional[int], float]], plan: AudiencePlan) -> dict:
    """Panelin gerçekleşen (ağırlıklı) cinsiyet ve yaş dağılımı ile hedefin karşılaştırması."""
    tot = sum(w for _, _, w in people) or 1.0
    fem = sum(w for f, _, w in people if f) / tot
    known_g = sum(w for f, _, w in people if f is not None) / tot
    bands = []
    wsum = sum(b[2] for b in plan.dist.age_bands) or 1.0
    for lo, hi, w in plan.dist.age_bands:
        got = sum(pw for _, a, pw in people if a is not None and lo <= a <= hi) / tot
        n = sum(1 for _, a, _ in people if a is not None and lo <= a <= hi)
        bands.append({"band": band_label(lo, hi), "target_pct": round(w / wsum * 100), "pct": round(got * 100), "n": n})
    roles: Dict[str, int] = {}
    for f, _, _ in people:
        if f is None:
            roles["bilinmiyor"] = roles.get("bilinmiyor", 0) + 1
        else:
            r = buyer_role(plan.info.value, f)
            roles[r] = roles.get(r, 0) + 1
    return {"n": len(people), "n_female": sum(1 for f, _, _ in people if f), "n_male": sum(1 for f, _, _ in people if f is False),
            "n_unknown": sum(1 for f, _, _ in people if f is None),
            "female_pct": round(fem * 100), "target_female_pct": round(plan.dist.female_share * 100),
            "gender_known_pct": round(known_g * 100), "age_bands": bands, "roles": roles}


def describe(plan: AudiencePlan, people: Sequence[Tuple[Optional[bool], Optional[int], float]], method: str,
             note: str = "", n_eff: Optional[float] = None) -> dict:
    """Sonuç ekranında 'kime soruldu' kutusu için meta."""
    d = plan.dist
    return {"value": plan.info.value, "label": plan.info.label, "source": plan.info.source, "reason": plan.info.reason,
            "child_gender": plan.info.child_gender,
            "child_age_range": list(d.child_age_range) if plan.info.value == "cocuk" and d.child_age_range else None,
            "method": method, "note": note, "n_eff": round(n_eff, 1) if n_eff is not None else None,
            "composition": composition(people, plan), "calibration": plan.calibration(), "warnings": plan.warnings}


def poststrat_weights(people: Sequence[Tuple[Optional[bool], Optional[int]]], dist: AudienceDist) -> List[float]:
    """Sabit kişi havuzunun cevaplarını hedef cinsiyet ve yaş dağılımına göre ağırlıklandırır.

    Cinsiyet ve yaş bandı ağırlıkları ayrı ayrı (marjinal) hesaplanıp çarpılır; bilinmeyen alan 1 sayılır.
    Havuzda hiç kişi olmayan hücrenin payı kaybolur (raporlanır). Tek kişinin ağırlığı ortalamanın MAX_WEIGHT katını aşmaz.
    """
    n = len(people)
    if n == 0:
        return []
    known = [f for f, _ in people if f is not None]
    w_g = {True: 1.0, False: 1.0}
    if known:
        pf = sum(known) / len(known)
        if 0 < pf < 1:
            w_g = {True: dist.female_share / pf, False: (1 - dist.female_share) / (1 - pf)}
    bands = dist.age_bands
    tw = sum(b[2] for b in bands) or 1.0
    in_band = lambda a: next((i for i, (lo, hi, _) in enumerate(bands) if lo <= a <= hi), None)
    ages = [in_band(a) if a is not None else None for _, a in people]
    cnt = {i: ages.count(i) for i in range(len(bands))}
    n_aged = sum(cnt.values())
    w_a = {i: (bands[i][2] / tw) / (cnt[i] / n_aged) if cnt[i] else 0.0 for i in cnt} if n_aged else {}
    out = []
    for (f, _), b in zip(people, ages):
        w = w_g[f] if f is not None else 1.0
        if b is not None:
            w *= w_a.get(b, 1.0) or 0.2      # hedef dışı yaş: tamamen silinmez, etkisi azaltılır
        elif n_aged:
            w *= 0.2                         # hedef yaş bantlarının dışında (ör. çocuk ürününde 22 yaşında öğrenci)
        out.append(w)
    mean = sum(out) / n or 1.0
    out = [min(MAX_WEIGHT, w / mean) for w in out]
    mean = sum(out) / n or 1.0
    return [w / mean for w in out]


def effective_n(weights: Sequence[float]) -> float:
    s, s2 = sum(weights), sum(w * w for w in weights)
    return s * s / s2 if s2 else 0.0


def replicate(items: Sequence, weights: Sequence[float], factor: int = 4) -> list:
    """Ağırlıklı listeyi tamsayı kopyalarla temsil eder (fiyat analizi ağırlık almadığı için)."""
    counts = _allocate(list(weights), max(len(items), len(items) * factor))
    return [x for x, c in zip(items, counts) for _ in range(c)]


def quota_people(plan: AudiencePlan, n: int) -> List[Tuple[bool, int, float]]:
    """Hedef dağılımın n kişilik kota karşılığı (kişi üretmeyen motorlarda gösterim için)."""
    n_f = round(n * plan.dist.female_share)
    counts = _allocate([w for _, _, w in plan.dist.age_bands], n)
    ages = [(lo + hi) // 2 for (lo, hi, _), c in zip(plan.dist.age_bands, counts) for _ in range(c)]
    return [(i < n_f, ages[i], 1.0) for i in range(n)]


def plan_from_card(card: dict, region: str, panel_root: Optional[Path] = None) -> Optional[AudiencePlan]:
    """Kartta hedef kitle varsa bölgenin kalibre dağılımıyla plan; yoksa None (eski davranış).

    `panel_root` müşterinin PANEL_DATA_DIR klasörü: içinde hedef_kitle/dagilim.json varsa o, yoksa varsayılan dosya."""
    info = card.get("target_audience")
    if not info:
        return None
    try:
        data = (Path(panel_root) / "hedef_kitle") if panel_root and (Path(panel_root) / "hedef_kitle" / "dagilim.json").exists() else None
        return plan_for(AudienceInfo.model_validate(info), region, data)
    except (OSError, ValueError):
        return None


def prompt_note(info: dict) -> str:
    """Herkese aynı soruyu soran motorlar (MiroFish) için: kişinin ürünü kimin için değerlendireceği."""
    v, label = info.get("value"), info.get("label") or LABEL.get(info.get("value"), "")
    if v == "kadin":
        return (f"Ürünün hedef kitlesi: {label}. Kadınsan kendin için; erkeksen hayatındaki bir kadın (eşin, annen, kız "
                "kardeşin) için alıp almayacağını değerlendir.")
    if v == "erkek":
        return (f"Ürünün hedef kitlesi: {label}. Erkeksen kendin için; kadınsan hayatındaki bir erkek (eşin, baban, erkek "
                "kardeşin) için alıp almayacağını değerlendir.")
    if v == "cocuk":
        lo, hi = info.get("child_age_range") or (2, 12)
        kid = {"kız": "kız çocuğu", "erkek": "erkek çocuğu"}.get(info.get("child_gender") or "", "çocuk")
        return (f"Ürünün hedef kitlesi: {label}. Bu bir {kid} ürünüdür ({lo}-{hi} yaş). Bir ebeveyn olarak (çocuğun yoksa "
                "yakınının çocuğu için) alıp almayacağını değerlendir: rahatlık, dayanıklılık, yıkanabilirlik ve fiyat.")
    if v == "unisex":
        return f"Ürünün hedef kitlesi: {label} (kadın ve erkek). Kendin için değerlendir."
    return ""
