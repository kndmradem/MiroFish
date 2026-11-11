"""Excel (koleksiyon listesi) + görsel klasörü içe aktarma.

Eşleştirme sırası (ilk tutan kazanır):
1. Excel'deki `gorsel_dosyalari` sütunu: dosya adları birebir (büyük/küçük harf, uzantı, Türkçe karakter önemsiz).
2. Dosya adı SKU ile başlıyor: SW27-014.jpg, SW27-014_2.jpg, SW27-014-arka.jpg, "SW27-014 (1).png".
3. Görsel SKU adlı klasörde: SW27-014/on.jpg.
Bir SKU başka bir SKU'nun başlangıcıysa en uzun eşleşme kazanır; yine belirsizse otomatik bağlanmaz.
Hiçbir şey onaysız kaydedilmez: bu modül yalnızca önizleme üretir.
"""
import base64
import difflib
import io
import zipfile
import re
import unicodedata
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .models import CollectionItem, CollectionMeta, ImportPreview, Issue, ItemPreview, OrphanImage

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
UNSUPPORTED_IMAGE_EXT = {".heic", ".heif", ".tif", ".tiff", ".bmp", ".gif"}
MIN_IMAGE_PX = 400

_TR = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")


def norm(s: str) -> str:
    """Karşılaştırma anahtarı: küçük harf, Türkçe karaktersiz, aksansız, kenar boşluksuz."""
    s = unicodedata.normalize("NFKD", str(s).translate(_TR))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.strip().lower()


def stem(filename: str) -> str:
    base = filename.replace("\\", "/").rsplit("/", 1)[-1]
    return base.rsplit(".", 1)[0] if "." in base else base


def ext(filename: str) -> str:
    base = filename.rsplit("/", 1)[-1]
    return "." + base.rsplit(".", 1)[-1].lower() if "." in base else ""


# ---------- Excel başlıkları ----------
# Aynı alana giden farklı yazımlar. Anahtarlar norm() + boşluk/altçizgi temizliğiyle karşılaştırılır.
ITEM_ALIASES: Dict[str, List[str]] = {
    "sku": ["sku", "sku kodu", "sku_kodu", "model kodu", "model_kodu", "urun kodu", "ürün kodu", "stok kodu", "kod", "style", "style code", "article"],
    "name": ["urun adi", "ürün adı", "urun_adi", "ad", "ürün", "urun", "model adi", "model adı", "name", "product name", "aciklama", "açıklama"],
    "category": ["kategori", "category", "ana kategori", "urun grubu", "ürün grubu", "urun cinsi", "ürün cinsi"],
    "subcategory": ["alt kategori", "alt_kategori", "subcategory", "alt grup", "model cinsi", "model tipi"],
    "technical_specs": ["urun icerigi", "ürün içeriği", "urun_icerigi", "icerik", "içerik", "kompozisyon", "composition",
                        "kumas icerigi", "kumaş içeriği",
                        "kumas", "kumaş", "bilesim", "bileşim", "teknik ozellikler", "teknik özellikler", "teknik_ozellikler", "specs"],
    "unit_cost": ["maliyet fiyati", "maliyet fiyatı", "maliyet_fiyati", "birim maliyet", "birim_maliyet", "maliyet", "cost",
                  "unit cost", "alis fiyati", "alış fiyatı"],
    "images": ["gorsel dosyalari", "görsel dosyaları", "gorsel_dosyalari", "gorsel", "görsel", "foto", "fotograf", "fotoğraf", "resim", "image", "images", "dosya adi", "dosya adı",
               "photo", "colorphoto", "colorphoto data uri", "photo data uri", "data uri", "urun gorseli", "ürün görseli"],
    "colors": ["renkler", "renk", "color", "colors", "colour", "renk adi", "renk adı"],
    "sizes": ["beden araligi", "beden aralığı", "beden_araligi", "beden", "bedenler", "size", "sizes"],
    "planned_qty": ["planlanan adet", "planlanan_adet", "adet", "siparis adedi", "sipariş adedi", "qty", "quantity"],
    "declared_role": ["hedef rol", "hedef_rol", "rol", "role"],
    "outfit_group": ["kombin grubu", "kombin_grubu", "kombin", "hikaye", "tema", "story"],
    "launch_month": ["lansman ayi", "lansman ayı", "lansman_ayi", "ay", "launch month"],
    "moq": ["min siparis adedi", "min sipariş adedi", "min_siparis_adedi", "moq", "minimum siparis"],
    "attributes": ["ek ozellikler", "ek özellikler", "ek_ozellikler", "ozellikler", "özellikler"],
    # Ürün detayı sütunları: panele ürün kartının parçası olarak gider (ek özelliklere yazılır)
    "attr:Hedef kitle": ["hedef kitle", "hedef_kitle", "cinsiyet", "gender", "kitle"],
    "attr:Kalıp": ["kalip", "kalıp", "fit", "kesim"],
    "attr:Desen": ["desen", "pattern", "baski", "baskı"],
    "attr:Gramaj": ["gramaj", "gsm", "kumas gramaji", "kumaş gramajı"],
    "attr:Menşei": ["mensei", "menşei", "uretim yeri", "üretim yeri", "origin"],
    "attr:Renk kodu": ["renk kodu", "renk_kodu", "color code"],
    "attr:Kumaş tipi": ["kumas tipi", "kumaş tipi", "fabric type"],
    "attr:Sezon": ["sezon", "season"],
    "attr:Yıl": ["yil", "yıl", "year"],
    # Satış fiyatı okunmaz: önerilen fiyatı sistem hesaplar. Sütun varsa önizlemede not düşülür.
    "ignored_price": ["satis fiyati", "satış fiyatı", "satis_fiyati", "planlanan fiyat", "planlanan_fiyat", "fiyat", "price",
                      "retail price", "psf", "etiket fiyati", "etiket fiyatı"],
}
META_ALIASES: Dict[str, List[str]] = {
    "name": ["koleksiyon adi", "koleksiyon adı", "koleksiyon_adi", "koleksiyon", "collection"],
    "brand": ["marka", "brand"],
    "brand_notes": ["marka notlari", "marka notları", "marka_notlari", "brand notes"],
    "season": ["sezon", "season"],
    "total_budget": ["toplam butce", "toplam bütçe", "toplam_butce", "butce", "bütçe", "budget"],
    "currency": ["para birimi", "para_birimi", "doviz", "döviz", "currency"],
    "target_regions": ["hedef bolgeler", "hedef bölgeler", "hedef_bolgeler", "bolgeler", "bölgeler", "regions"],
    "channel": ["kanal", "channel"],
    "launch_month": ["lansman ayi", "lansman ayı", "lansman_ayi"],
    "usd_try_rate": ["usd try kuru", "kur", "usd_try", "usd/try"],
    "notes": ["notlar", "not", "notes"],
    "color_min_qty": ["renk min adet", "renk_min_adet", "renk basina minimum adet", "renk başına minimum adet", "renk minimum adet"],
}
ROLE_MAP = {"hero": "hero", "cekirdek": "çekirdek", "core": "çekirdek", "temel": "çekirdek",
            "tamamlayici": "tamamlayıcı", "complement": "tamamlayıcı", "destek": "tamamlayıcı",
            "deneme": "deneme", "test": "deneme"}
CHANNEL_MAP = {"online": "online", "e-ticaret": "online", "eticaret": "online", "magaza": "store", "store": "store"}
REGION_SET = {"EU", "MENA", "CIS", "US", "TR"}


def _key(s: str) -> str:
    return re.sub(r"[\s_\-/]+", " ", norm(s)).strip()


def _key_loose(s: str) -> str:
    """ERP dışa aktarımlarındaki ekleri atar: 'Renk Açıklaması' -> 'renk', 'Birim Cinsi (1)' -> 'birim cinsi'."""
    k = re.sub(r"\(\d+\)", " ", _key(s))
    k = re.sub(r"\b(aciklamasi|aciklmasi|aciklama|adi)$", "", k.strip()).strip()
    return re.sub(r"\s+", " ", k)


def map_headers(headers: List[str], aliases: Dict[str, List[str]]) -> Tuple[Dict[int, str], List[str]]:
    lookup = {_key(a): f for f, al in aliases.items() for a in al + [f]}
    out, ignored = {}, []
    for i, h in enumerate(headers):
        if h is None or not str(h).strip():
            continue
        f = lookup.get(_key(str(h))) or lookup.get(_key_loose(str(h)))
        if f and f not in out.values():
            out[i] = f
        elif f and aliases is ITEM_ALIASES and not f.startswith(("attr:", "ignored")) and f not in ("sku", "images"):
            label = re.sub(r"\s*(açıklaması|açıklması|açıklama)$", "", str(h).strip(), flags=re.I) or str(h).strip()
            out[i] = f"attr:{label}"      # aynı alana ikinci sütun: bilgi kaybolmasın, ürün kartına ek özellik
        else:
            ignored.append(str(h))
    return out, ignored


def _num(v) -> Optional[float]:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[^\d,.\-]", "", str(v))
    if "," in s and "." in s:   # 1.499,90 ya da 1,499.90
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".") if len(s.split(",")[-1]) != 3 else s.replace(",", "")
    elif s.count(".") > 1 or ("." in s and len(s.split(".")[-1]) == 3):   # Türkçe binlik ayracı: 1.799
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        raise ValueError(f"sayı değil: {v!r}")


def _split(v) -> List[str]:
    if v is None:
        return []
    return [p.strip() for p in re.split(r"[;,\n]", str(v)) if p.strip()]


def _str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


@dataclass
class Sheet:
    headers: List[str]
    rows: List[Tuple[int, list]]   # (excel satır no, değerler)
    title: str = ""


def embedded_images(data: bytes) -> Dict[str, Dict[int, List[Tuple[bytes, str]]]]:
    """Excel'e gömülü (hücre üstüne yerleştirilmiş) görseller: sayfa adı -> excel satır no -> [(bayt, uzantı)].
    Görsel, sol üst köşesinin düştüğü satıra aittir. Excel'in yeni 'hücreye yerleştir' (IMAGE/richData) biçimi okunmaz."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if not any(n.startswith("xl/media/") for n in z.namelist()):
                return {}
    except zipfile.BadZipFile:
        return {}
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(data), data_only=True)
    out: Dict[str, Dict[int, List[Tuple[bytes, str]]]] = {}
    for ws in wb.worksheets:
        for im in getattr(ws, "_images", []):
            frm = getattr(im.anchor, "_from", None)
            if frm is None:
                continue
            try:
                raw = im._data()
            except Exception:
                continue
            fmt = (getattr(im, "format", "") or "png").lower().replace("jpeg", "jpg")
            out.setdefault(ws.title, {}).setdefault(frm.row + 1, []).append((raw, fmt))
    return out


def data_uri_image(v) -> Optional[Tuple[bytes, str]]:
    """Hücrede 'data:image/png;base64,...' yazıyorsa görseli çözer."""
    if not isinstance(v, str) or not v.strip().lower().startswith("data:image/"):
        return None
    m = re.match(r"data:image/([a-zA-Z+]+);base64,(.*)$", v.strip(), re.S)
    if not m:
        return None
    try:
        return base64.b64decode(m.group(2)), m.group(1).lower().replace("jpeg", "jpg")
    except Exception:
        return None


def read_workbook(data: bytes, filename: str = "liste.xlsx") -> Dict[str, Sheet]:
    """xlsx ya da csv okur; sayfa adı -> Sheet. Boş satırlar atlanır."""
    if filename.lower().endswith(".csv"):
        import csv
        text = data.decode("utf-8-sig", errors="replace")
        dialect = csv.Sniffer().sniff(text[:2048], delimiters=",;\t") if text.strip() else csv.excel
        rows = list(csv.reader(io.StringIO(text), dialect))
        if not rows:
            return {}
        return {"Ürünler": Sheet(rows[0], [(i + 2, r) for i, r in enumerate(rows[1:]) if any(str(c).strip() for c in r)], "Ürünler")}
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    out = {}
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue
        out[ws.title] = Sheet([_str(h) for h in rows[0]],
                              [(i + 2, list(r)) for i, r in enumerate(rows[1:]) if any(c not in (None, "") for c in r)], ws.title)
    return out


def _pick_sheets(book: Dict[str, Sheet]) -> Tuple[Optional[Sheet], Optional[Sheet]]:
    """Ürün sayfası: SKU başlığı olan ve en çok satırı olan sayfa. Genel bilgi sayfası: SKU'su olmayan ve en az iki
    genel bilgi başlığı (koleksiyon adı, marka, sezon, bütçe, para birimi, bölgeler...) taşıyan sayfa."""
    items, meta = None, None
    for title, sh in book.items():
        hm, _ = map_headers(sh.headers, ITEM_ALIASES)
        mm, _ = map_headers(sh.headers, META_ALIASES)
        if "sku" in hm.values() and (items is None or len(sh.rows) > len(items.rows)):
            items = sh
        elif "sku" not in hm.values() and len(set(mm.values())) >= 2 and meta is None:
            meta = sh
    return items, meta


def parse_meta(sheet: Optional[Sheet], issues: List[Issue]) -> CollectionMeta:
    meta = CollectionMeta()
    if sheet is None or not sheet.rows:
        issues.append(Issue(level="bilgi", message="Excel'de genel bilgi (koleksiyon) sayfası bulunamadı; marka, bütçe ve bölgeleri ekrandan girin."))
        return meta
    cols, _ = map_headers(sheet.headers, META_ALIASES)
    _, row = sheet.rows[0]
    vals = {f: row[i] if i < len(row) else None for i, f in cols.items()}
    d: dict = {}
    if _str(vals.get("name")):
        d["name"] = _str(vals["name"])
    for f in ("brand", "brand_notes", "season", "notes"):
        if _str(vals.get(f)):
            d[f] = _str(vals[f])
    try:
        n = _num(vals.get("color_min_qty"))
        if n is not None and n >= 1:
            d["color_min_qty"] = int(n)
    except ValueError:
        issues.append(Issue(level="uyarı", message=f"Koleksiyon sayfası: renk_min_adet sayı değil ({vals.get('color_min_qty')!r})"))
    for f in ("total_budget", "usd_try_rate"):
        try:
            n = _num(vals.get(f))
            if n is not None and n > 0:
                d[f] = n
        except ValueError:
            issues.append(Issue(level="uyarı", message=f"Koleksiyon sayfası: {f} sayı değil ({vals.get(f)!r})"))
    cur = _str(vals.get("currency")).upper().replace("TL", "TRY")
    if cur:
        if cur in ("TRY", "USD"):
            d["currency"] = cur
        else:
            issues.append(Issue(level="uyarı", message=f"Para birimi {cur} desteklenmiyor; TRY ya da USD yazın. TRY varsayıldı."))
    regs = [r.upper() for r in _split(vals.get("target_regions"))]
    if regs:
        bad = [r for r in regs if r not in REGION_SET]
        if bad:
            issues.append(Issue(level="uyarı", message=f"Tanınmayan bölge: {', '.join(bad)} (geçerli: EU, MENA, CIS, US, TR)"))
        good = [r for r in regs if r in REGION_SET]
        if good:
            d["target_regions"] = list(dict.fromkeys(good))
    ch = CHANNEL_MAP.get(norm(_str(vals.get("channel"))).replace(" ", ""))
    if ch:
        d["channel"] = ch
    m = _num_safe(vals.get("launch_month"))
    if m and 1 <= m <= 12:
        d["launch_month"] = int(m)
    return meta.model_copy(update=d)


def _num_safe(v) -> Optional[float]:
    try:
        return _num(v)
    except ValueError:
        return None


def parse_items(sheet: Sheet, issues: List[Issue]) -> Tuple[List[Tuple[int, CollectionItem, List[str]]], Dict[str, str], List[str]]:
    """(satır, ürün, satır sorunları) listesi + başlık eşlemesi + yok sayılan sütunlar."""
    cols, ignored = map_headers(sheet.headers, ITEM_ALIASES)
    out = []
    for rowno, row in sheet.rows:
        vals = {f: row[i] if i < len(row) else None for i, f in cols.items()}
        probs: List[str] = []
        d: dict = {"sku": _str(vals.get("sku")), "name": _str(vals.get("name"))}
        for f in ("category", "subcategory", "technical_specs", "outfit_group", "sizes"):
            d[f] = _str(vals.get(f))
        try:
            n = _num(vals.get("unit_cost"))
            d["unit_cost"] = n if n is None or n > 0 else None
        except ValueError as e:
            d["unit_cost"] = None
            probs.append(f"Maliyet fiyatı {e}")
        for f in ("planned_qty", "moq"):
            n = _num_safe(vals.get(f))
            d[f] = int(n) if n and n > 0 else None
        m = _num_safe(vals.get("launch_month"))
        d["launch_month"] = int(m) if m and 1 <= m <= 12 else None
        iv = vals.get("images")
        d["images"] = [] if data_uri_image(iv) else _split(iv)     # gömülü/data URI görseller ayrıca okunur
        d["colors"] = _split(vals.get("colors"))
        role = _str(vals.get("declared_role"))
        if role:
            d["declared_role"] = ROLE_MAP.get(norm(role).replace(" ", ""))
            if d["declared_role"] is None:
                probs.append(f"Hedef rol tanınmadı ({role}); hero / çekirdek / tamamlayıcı / deneme yazın")
        attrs = {}
        for part in re.split(r"[;\n]", _str(vals.get("attributes"))):
            if "=" in part:
                k, v = part.split("=", 1)
                attrs[k.strip()] = v.strip()
        for f, v in vals.items():
            if f.startswith("attr:") and _str(v):
                attrs.setdefault(f[5:], _str(v))
        d["attributes"] = attrs
        out.append((rowno, CollectionItem(**d), probs))
    colmap = {sheet.headers[i]: f for i, f in cols.items()}
    return out, colmap, ignored


@dataclass
class ImageInfo:
    path: str                  # yüklenen göreli yol (klasör/dosya)
    width: Optional[int] = None
    height: Optional[int] = None


def _sku_prefix_match(sku_n: str, file_stem_n: str) -> bool:
    """Dosya adı SKU ile başlıyor ve ardından ayraç ya da hiçbir şey geliyor mu."""
    if not file_stem_n.startswith(sku_n):
        return False
    rest = file_stem_n[len(sku_n):]
    return rest == "" or rest[0] in "_- .("


def match_images(items: List[CollectionItem], images: List[ImageInfo]) -> Tuple[Dict[str, List[str]], Dict[str, str], Dict[str, List[str]], List[OrphanImage]]:
    """SKU -> görsel yolları, SKU -> eşleşme kuralı, SKU -> belirsiz aday görseller, sahipsiz görseller."""
    by_full = {norm(i.path): i.path for i in images}
    by_name = {}
    for i in images:
        by_name.setdefault(norm(i.path.rsplit("/", 1)[-1]), []).append(i.path)
        by_name.setdefault(norm(stem(i.path)), []).append(i.path)
    skus = [it.sku for it in items if it.sku]
    sku_n = {s: norm(s) for s in skus}
    used: set = set()
    matched: Dict[str, List[str]] = {}
    rule: Dict[str, str] = {}

    # 1) Excel'de dosya adı yazılı
    for it in items:
        if not it.sku or not it.images:
            continue
        found = []
        for name in it.images:
            n = norm(name)
            hit = by_full.get(n) or (by_name.get(n) or by_name.get(norm(stem(name))) or [None])[0]
            if hit:
                found.append(hit)
        if found:
            matched[it.sku] = list(dict.fromkeys(found))
            rule[it.sku] = "Excel görsel sütunu"
            used.update(found)

    # 2) dosya adı SKU ile başlıyor, 3) SKU adlı klasör. En uzun SKU kazanır.
    ambiguous: Dict[str, List[str]] = {}
    for img in images:
        if img.path in used:
            continue
        parts = img.path.replace("\\", "/").split("/")
        folder_n = [norm(p) for p in parts[:-1]]
        st = norm(stem(img.path))
        cands = [(len(sku_n[s]), s, "dosya adı = SKU") for s in skus if s not in rule or rule[s] != "Excel görsel sütunu"
                 if _sku_prefix_match(sku_n[s], st)]
        cands += [(len(sku_n[s]), s, "SKU klasörü") for s in skus if s not in rule or rule[s] != "Excel görsel sütunu"
                  if sku_n[s] in folder_n]
        if not cands:
            continue
        cands.sort(reverse=True)
        top = [c for c in cands if c[0] == cands[0][0]]
        if len({c[1] for c in top}) > 1:
            for c in top:
                ambiguous.setdefault(c[1], []).append(img.path)
            used.add(img.path)
            continue
        _, s, r = top[0]
        matched.setdefault(s, []).append(img.path)
        rule.setdefault(s, r)
        used.add(img.path)

    for s, files in matched.items():
        if rule.get(s) != "Excel görsel sütunu":
            matched[s] = sorted(files, key=_image_order)

    orphans = []
    norm_skus = list(sku_n.values())
    back = {v: k for k, v in sku_n.items()}
    for img in images:
        if img.path in used:
            continue
        st = norm(stem(img.path))
        close = difflib.get_close_matches(st.split("_")[0].split(" ")[0], norm_skus, n=1, cutoff=0.75)
        orphans.append(OrphanImage(file=img.path, suggestion=back[close[0]] if close else None))
    return matched, rule, ambiguous, orphans


def _image_order(path: str):
    """Ana görsel önce: eki olmayan (SW27-014.jpg) ya da _1, sonra diğerleri ada göre."""
    st = norm(stem(path))
    m = re.search(r"[_\- (](\d+)\)?$", st)
    return (0 if not re.search(r"[_\- (]", st) else 1 if m and m.group(1) == "1" else 2, int(m.group(1)) if m else 0, st)


def group_variants(parsed, mode: str, issues: List[Issue]):
    """Aynı SKU'nun renk satırları. mode=model: tek ürüne birleştir (renkler ve satır görselleri birikir);
    mode=renk: her renk ayrı ürün (SKU-renk kodu). Dönüş: [(ilk satır, ürün, sorunlar, satırlar)]."""
    groups: Dict[str, list] = {}
    order: List[str] = []
    for rowno, it, probs in parsed:
        k = norm(it.sku) if it.sku else f"__satir{rowno}"
        if k not in groups:
            order.append(k)
        groups.setdefault(k, []).append((rowno, it, probs))
    out = []
    for k in order:
        g = groups[k]
        if len(g) == 1 or not g[0][1].sku:
            out += [(r, it, p, [r]) for r, it, p in g]
            continue
        color = lambda it: (it.colors[0] if it.colors else "") or it.attributes.get("Renk kodu", "")
        labels = [color(it) for _, it, _ in g]
        if len(set(labels)) < len(labels):          # renk farkı yok: gerçek tekrar, birleştirme
            out += [(r, it, p, [r]) for r, it, p in g]
            continue
        if mode == "renk":
            for r, it, p in g:
                code = it.attributes.get("Renk kodu") or color(it)
                out.append((r, it.model_copy(update={"sku": f"{it.sku}-{code}", "name": f"{it.name} ({color(it)})" if color(it) else it.name}), p, [r]))
            issues.append(Issue(level="bilgi", sku=g[0][1].sku, message=f"{g[0][1].sku}: {len(g)} renk ayrı ürün olarak alındı"))
            continue
        first = g[0][1]
        costs = {it.unit_cost for _, it, _ in g if it.unit_cost}
        probs = [x for _, _, p in g for x in p]
        if len(costs) > 1:
            probs.append(f"Renklerde farklı maliyet var ({', '.join(f'{c:g}' for c in sorted(costs))}); en yüksek kullanıldı")
        attrs = dict(first.attributes)
        codes = [it.attributes.get("Renk kodu") for _, it, _ in g if it.attributes.get("Renk kodu")]
        if codes:
            attrs["Renk kodu"] = ", ".join(dict.fromkeys(codes))
        qty = [it.planned_qty for _, it, _ in g if it.planned_qty]
        merged = first.model_copy(update={
            "colors": list(dict.fromkeys(c for _, it, _ in g for c in it.colors)),
            "images": list(dict.fromkeys(x for _, it, _ in g for x in it.images)),
            "unit_cost": max(costs) if costs else None, "planned_qty": sum(qty) if qty else None, "attributes": attrs})
        out.append((g[0][0], merged, probs, [r for r, _, _ in g]))
        issues.append(Issue(level="bilgi", sku=first.sku, message=f"{first.sku}: {len(g)} renk satırı tek üründe birleştirildi ({', '.join(labels)})"))
    return out


def build_preview(collection_id: str, book: Dict[str, Sheet], images: List[ImageInfo], kind: str = "koleksiyon",
                  embedded: Optional[Dict[str, Dict[int, List[str]]]] = None, variants: str = "model") -> ImportPreview:
    """Aynı şablon iki ekranda da çalışır: kind=koleksiyon ya da bagimsiz (koleksiyonu olmayan ürünler)."""
    issues: List[Issue] = []
    items_sheet, meta_sheet = _pick_sheets(book)
    meta = parse_meta(meta_sheet, issues)
    upd = {"kind": kind}
    if kind == "bagimsiz" and meta.name == CollectionMeta().name:
        upd["name"] = "Toplu ürün listesi"
    meta = meta.model_copy(update=upd)
    if items_sheet is None:
        issues.append(Issue(level="hata", message="Ürün sayfası bulunamadı: SKU / Model kodu başlıklı bir sütun gerekli."))
        return ImportPreview(collection_id=collection_id, meta=meta, items=[], orphans=[OrphanImage(file=i.path) for i in images],
                             issues=issues, counts={"rows": 0, "images": len(images)})
    parsed, colmap, ignored = parse_items(items_sheet, issues)
    row_imgs = (embedded or {}).get(items_sheet.title, {})
    row_color = {r: ((it.colors[0] if it.colors else "") or it.attributes.get("Renk kodu", "")) for r, it, _ in parsed}
    grouped = group_variants(parsed, variants, issues)
    parsed = [(r, it, p) for r, it, p, _ in grouped]
    rows_of = {id(it): rows for _, it, _, rows in grouped}
    if row_imgs:
        issues.append(Issue(level="bilgi", message=f"Excel'e gömülü {sum(len(v) for v in row_imgs.values())} görsel okundu; "
                                                   "aynı SKU ile ayrıca yüklenen görsel varsa o kullanılır."))
    if not meta.season:
        seas = {" ".join(x for x in (it.attributes.get("Sezon", ""), it.attributes.get("Yıl", "")) if x) for _, it, _ in parsed}
        if len(seas) == 1 and next(iter(seas)):
            meta = meta.model_copy(update={"season": next(iter(seas))})
    for need, label, lvl in (("name", "Ürün adı", "uyarı"), ("category", "Kategori", "uyarı"), ("unit_cost", "Maliyet fiyatı", "hata"),
                             ("technical_specs", "Ürün içeriği", "uyarı")):
        if need not in colmap.values():
            issues.append(Issue(level=lvl, message=f"'{label}' sütunu bulunamadı."))
    price_cols = [h for h, f in colmap.items() if f == "ignored_price"]
    if price_cols:
        issues.append(Issue(level="bilgi", message=f"Satış fiyatı sütunu ({', '.join(price_cols)}) okunmadı: önerilen satış "
                                                   "fiyatını sistem panelin fiyat cevaplarından hesaplar."))
    if kind == "bagimsiz":
        coll_cols = [h for h, f in colmap.items() if f in ("declared_role", "outfit_group")]
        if coll_cols:
            issues.append(Issue(level="bilgi", message=f"Koleksiyona özel sütunlar ({', '.join(coll_cols)}) bağımsız "
                                                       "ürün değerlendirmesinde kullanılmaz."))
    if ignored:
        issues.append(Issue(level="bilgi", message=f"Tanınmayan sütunlar yok sayıldı: {', '.join(ignored)}"))

    items = [it for _, it, _ in parsed]
    emb_paths = {p for rows in (embedded or {}).values() for ps in rows.values() for p in ps}
    dims = {i.path: i for i in images}
    images = [i for i in images if i.path not in emb_paths]     # gömülü görseller satırına bağlı; dosya eşleştirmesine girmez
    matched, rule, ambiguous, orphans = match_images(items, images)
    seen: Dict[str, int] = {}
    previews: List[ItemPreview] = []
    img_owner: Dict[str, List[str]] = {}
    for rowno, it, probs in parsed:
        errs, warns = [], list(probs)
        if not it.sku:
            errs.append("SKU boş")
        elif norm(it.sku) in seen:
            errs.append(f"Aynı SKU {seen[norm(it.sku)]}. satırda da var")
        else:
            seen[norm(it.sku)] = rowno
        if not it.name:
            errs.append("Ürün adı boş")
        imgs = matched.get(it.sku, []) if it.sku else []
        rule_it = rule.get(it.sku, "")
        emb = [p for r in rows_of.get(id(it), [rowno]) for p in row_imgs.get(r, [])]
        cimg: Dict[str, str] = {}
        if emb and not imgs:
            imgs, rule_it = emb, "Excel'e gömülü"
            for r in rows_of.get(id(it), [rowno]):
                if row_color.get(r) and row_imgs.get(r):
                    cimg.setdefault(row_color[r], row_imgs[r][0])
        if it.images and rule.get(it.sku) != "Excel görsel sütunu":
            warns.append("Excel'de yazılı görsel adları yüklenen dosyalarda bulunamadı")
        cands = ambiguous.get(it.sku, []) if it.sku else []
        if not imgs and not cands and it.sku:
            errs.append("Görsel bulunamadı")
        if it.unit_cost is None:
            errs.append("Maliyet fiyatı boş ya da geçersiz: marj ve üretim kararı için gerekli")
            warns = [w for w in warns if not w.startswith("Maliyet fiyatı")]
        if not it.technical_specs:
            warns.append("Ürün içeriği (kumaş/kompozisyon) boş: panel ürünü yalnızca görsel ve addan değerlendirir")
        if not it.category:
            warns.append("Kategori boş: fiyat mimarisi ve kanibalizasyon analizine girmez")
        small = []
        for p in imgs:
            d = dims.get(p)
            if d and d.width and d.height and min(d.width, d.height) < MIN_IMAGE_PX:
                small.append((p, d))
            img_owner.setdefault(p, []).append(it.sku)
        if len(small) == 1:
            p, d = small[0]
            warns.append(f"Görsel küçük ({d.width}x{d.height}px): {p}")
        elif small:
            d = small[0][1]
            warns.append(f"{len(small)} görsel küçük (ör. {d.width}x{d.height}px); görsel model ayrıntıyı zor seçer, "
                         "büyük görsel aynı SKU adıyla yüklenirse o kullanılır")
        item = it.model_copy(update={"images": imgs, "color_images": cimg} if cimg else {"images": imgs})
        status = "hata" if errs else "belirsiz" if (cands and not imgs) else "uyarı" if warns else "ok"
        for e in errs:
            issues.append(Issue(level="hata", sku=it.sku or None, row=rowno, message=e))
        for w in warns:
            issues.append(Issue(level="uyarı", sku=it.sku or None, row=rowno, message=w))
        if cands and not imgs:
            issues.append(Issue(level="uyarı", sku=it.sku, row=rowno,
                                message=f"Görsel belirsiz: {', '.join(cands)} birden fazla SKU'ya uyuyor, elle seçin"))
        previews.append(ItemPreview(row=rowno, item=item, status=status, match_rule=rule_it, candidates=cands))
    for p, owners in img_owner.items():
        if len(owners) > 1:
            issues.append(Issue(level="uyarı", message=f"Aynı görsel birden fazla üründe: {p} ({', '.join(owners)})"))
    cat_n: Dict[str, set] = {}
    for it in items:
        if it.category:
            cat_n.setdefault(norm(it.category).replace(" ", ""), set()).add(it.category)
    for variants in cat_n.values():
        if len(variants) > 1:
            issues.append(Issue(level="bilgi", message=f"Kategori farklı yazılmış olabilir: {' / '.join(sorted(variants))}"))
    for o in orphans:
        issues.append(Issue(level="bilgi", message=f"Sahipsiz görsel: {o.file}" + (f" (benzer SKU: {o.suggestion}?)" if o.suggestion else "")))

    counts = {"rows": len(previews), "ok": sum(p.status == "ok" for p in previews),
              "warn": sum(p.status == "uyarı" for p in previews), "error": sum(p.status == "hata" for p in previews),
              "ambiguous": sum(p.status == "belirsiz" for p in previews), "images": len(dims),
              "images_linked": len(dims) - len(orphans) - len({x for v in ambiguous.values() for x in v}),
              "orphans": len(orphans)}
    return ImportPreview(collection_id=collection_id, meta=meta, items=previews, orphans=orphans, issues=issues,
                         column_map=colmap, ignored_columns=ignored, counts=counts)


TEMPLATE_ITEM_COLS = ["sku", "urun_adi", "kategori", "alt_kategori", "urun_icerigi", "maliyet_fiyati", "gorsel_dosyalari",
                      "renkler", "beden_araligi", "hedef_kitle", "kalip", "desen", "gramaj", "planlanan_adet",
                      "min_siparis_adedi", "lansman_ayi", "hedef_rol", "kombin_grubu", "ek_ozellikler"]
TEMPLATE_REQUIRED = {"sku", "urun_adi", "kategori", "urun_icerigi", "maliyet_fiyati"}
TEMPLATE_EXAMPLES = [
    ["URN-001", "Keten gömlek", "Üst giyim", "Gömlek", "%100 keten, 160 gsm, sedef düğme", 420, "", "ekru, mavi", "S-XL",
     "kadın", "rahat", "düz", "160 gsm", 800, 300, 3, "çekirdek", "Sahil", "yaka=klasik"],
    ["URN-002", "Geniş paça pantolon", "Alt giyim", "Pantolon", "%55 keten %45 viskon, 220 gsm", 510,
     "URN-002_on.jpg; URN-002_arka.jpg", "ekru", "34-44", "kadın", "geniş paça", "düz", "220 gsm", 600, 300, 3,
     "tamamlayıcı", "Sahil", ""],
    ["URN-003", "Çiçek desenli midi elbise", "Elbise", "Midi", "%100 viskon, 120 gsm, astarlı", 640, "", "", "XS-L",
     "kadın", "A kesim", "çiçek", "120 gsm", None, 200, 4, "hero", "", ""],
]


def template_bytes() -> bytes:
    """Ortak toplu yükleme şablonu (koleksiyon ve bağımsız ürünler aynı dosyayı kullanır).
    Sayfalar: Okuma rehberi, Genel bilgi, Ürünler (3 örnek satır). Satış fiyatı sütunu yoktur: fiyatı sistem önerir."""
    from openpyxl import Workbook
    from openpyxl.comments import Comment
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation

    wb = Workbook()
    bold_w = Font(bold=True, color="FFFFFF")
    req, opt, coll = PatternFill("solid", fgColor="1F4E78"), PatternFill("solid", fgColor="7F7F7F"), PatternFill("solid", fgColor="8E7CC3")

    def header(ws, cols, required, collection_only=()):
        for i, c in enumerate(cols, 1):
            x = ws.cell(1, i, c)
            x.font = bold_w
            x.fill = req if c in required else coll if c in collection_only else opt
            x.alignment = Alignment(wrap_text=True)
            ws.column_dimensions[x.column_letter].width = max(14, len(c) + 4)
        ws.freeze_panes = "A2"

    guide = wb.active
    guide.title = "Okuma rehberi"
    for line in [
        "Toplu ürün yükleme şablonu. Koleksiyon ekranında da, bağımsız ürünler ekranında da aynı dosya kullanılır.",
        "Örnek satırlar uydurmadır; silip kendi verinizi yazın.",
        "Koyu mavi başlık zorunlu, gri başlık isteğe bağlı, mor başlık yalnızca koleksiyon değerlendirmesinde kullanılır.",
        "Satış fiyatı yazmayın: önerilen satış fiyatını ve fiyat bölgelerini sistem panelin fiyat cevaplarından hesaplar.",
        "1) 'Genel bilgi' sayfasına tek satır yazın (marka, bütçe, para birimi, bölgeler). Ekrandan da düzeltilebilir.",
        "   Koleksiyon yüklüyorsanız koleksiyon_adi yazın; bağımsız ürünlerde boş bırakabilirsiniz.",
        "2) 'Ürünler' sayfasına her ürün için bir satır yazın. SKU benzersiz olmalı.",
        "   urun_icerigi: kumaş ve kompozisyon (ör. %100 pamuk, 180 gsm, süprem). Panel ürünü bu bilgiyle ve görselle değerlendirir.",
        "   maliyet_fiyati: birim maliyet, Genel bilgi sayfasındaki para biriminde. Marj ve üret/azalt/üretme kararı buna dayanır.",
        "3) Görselleri klasör, çoklu dosya ya da zip olarak yükleyin. Eşleştirme sırası:",
        "   a. gorsel_dosyalari sütunundaki adlar (birden fazlaysa ; ile ayırın, ilk yazılan ana görsel)",
        "   b. Dosya adı SKU ile başlıyorsa otomatik: URN-001.jpg, URN-001_2.jpg, URN-001-arka.jpg",
        "   c. Görseller SKU adlı klasördeyse: URN-001/on.jpg",
        "4) Büyük/küçük harf, uzantı ve Türkçe karakter farkı önemsizdir. Başlıklar esnek okunur (ör. 'Model kodu' = sku).",
        "5) Yüklemeden sonra önizleme ekranı eşleşmeyen satırları ve görselleri gösterir; onaysız hiçbir şey kaydedilmez.",
        "Para birimi TRY ya da USD.",
        "renk_min_adet (isteğe bağlı): renk başına en az üretim adedi (boya partisi). Boşsa 300 varsayılır (kural varsayımı).",
        "renkler: modelin renkleri virgülle (ör. siyah, pembe) ya da ERP çıktısındaki gibi her renk ayrı satırda aynı SKU ile.",
        "hedef_rol (koleksiyon): hero / çekirdek / tamamlayıcı / deneme. Tasarımcının niyetidir; panel sonucuyla karşılaştırılır.",
        "kombin_grubu (koleksiyon): birlikte satılması düşünülen ürünler için aynı ad.",
        "ek_ozellikler: anahtar=değer; ile ayırarak (ör. yaka=klasik; kol=uzun).",
    ]:
        guide.append([line])
    guide.column_dimensions["A"].width = 120
    guide["A1"].font = Font(bold=True, size=13)

    meta = wb.create_sheet("Genel bilgi")
    header(meta, ["koleksiyon_adi", "marka", "sezon", "toplam_butce", "para_birimi", "hedef_bolgeler", "kanal",
                  "lansman_ayi", "notlar", "renk_min_adet"],
           {"para_birimi", "hedef_bolgeler"}, {"koleksiyon_adi"})
    meta.append(["SS27 Ana Koleksiyon", "Örnek Marka", "İlkbahar-Yaz 2027", 2500000, "TRY", "TR, EU", "online", 3, "örnek satır"])
    dv = DataValidation(type="list", formula1='"online,mağaza"')
    meta.add_data_validation(dv)
    dv.add("G2")
    dvc = DataValidation(type="list", formula1='"TRY,USD"')
    meta.add_data_validation(dvc)
    dvc.add("E2")

    items = wb.create_sheet("Ürünler")
    header(items, TEMPLATE_ITEM_COLS, TEMPLATE_REQUIRED, {"hedef_rol", "kombin_grubu"})
    items["E1"].comment = Comment("Kumaş ve kompozisyon: ör. %100 pamuk, 180 gsm, süprem", "şablon")
    items["F1"].comment = Comment("Birim maliyet (Genel bilgi sayfasındaki para biriminde). Satış fiyatı yazılmaz.", "şablon")
    for r in TEMPLATE_EXAMPLES:
        items.append(r)
    col_of = {c: items.cell(1, i + 1).column_letter for i, c in enumerate(TEMPLATE_ITEM_COLS)}
    dv2 = DataValidation(type="list", formula1='"hero,çekirdek,tamamlayıcı,deneme"')
    items.add_data_validation(dv2)
    dv2.add(f"{col_of['hedef_rol']}2:{col_of['hedef_rol']}2000")
    dv3 = DataValidation(type="list", formula1='"kadın,erkek,unisex,kız çocuk,erkek çocuk,bebek"', allow_blank=True)
    items.add_data_validation(dv3)
    dv3.add(f"{col_of['hedef_kitle']}2:{col_of['hedef_kitle']}2000")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
