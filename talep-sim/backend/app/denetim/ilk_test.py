"""Kurulumda / ilk veri testinde müşteri verisiyle mantık denetimi.

Üç katman, tek rapor:
  1. Ürün listesi (Excel/CSV, koleksiyon şablonu): içe aktarıcının bulguları + veri kuralları (SKU, maliyet, kategori).
  2. ERP klasörü (varsa, tahmin paketinin veri sözleşmesi): mevcut veri kalitesi kontrolleri (tahmin.dogrulama), yeniden
     yazılmadı, yalnızca bu rapora bağlandı.
  3. Örnek koşu: listeden kategorilere yayılmış en fazla N ürünle gerçek koleksiyon hattı (ayarlı motor ya da mock)
     çalışır, çıkan sonuç koleksiyon kurallarıyla denetlenir.
"""
import asyncio
import io
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .model import Bulgu, DenetimRaporu
from . import denetle_urunler, rapor_olustur

PLACEHOLDER = "ilk-test-yer-tutucu.png"


def _yer_tutucu() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (600, 800), (200, 200, 200)).save(buf, "PNG")
    return buf.getvalue()


def _ornek_sec(items, n: int):
    """Kategorilere sırayla yayılarak en fazla n ürün; maliyeti olmayanlar alınmaz (zaten veri hatası olarak raporlanır)."""
    by: Dict[str, list] = {}
    for it in items:
        if it.unit_cost and it.unit_cost > 0:
            by.setdefault(it.category or "-", []).append(it)
    out, i = [], 0
    while len(out) < n and any(i < len(v) for v in by.values()):
        for v in by.values():
            if i < len(v) and len(out) < n:
                out.append(v[i])
        i += 1
    return out


def erp_denetimi(klasor: str) -> Optional[DenetimRaporu]:
    """tahmin paketinin veri kalitesi kontrollerini çalıştırır; bulguları bu raporun biçimine çevirir."""
    aday = Path(__file__).resolve().parents[3] / "tahmin"
    if aday.exists() and str(aday) not in sys.path:
        sys.path.insert(0, str(aday))
    try:
        from tahmin.dogrulama import dogrula
        from tahmin.yukleme import yukle
    except Exception as e:
        return rapor_olustur([Bulgu(seviye="uyarı", kural="veri_erp", baslik="ERP veri kalitesi",
                                    mesaj=f"ERP kontrolleri çalıştırılamadı (tahmin paketi yüklenemedi: {e}).")], ["veri_erp"], "veri")
    sev = {"HATA": "hata", "UYARI": "uyarı", "BİLGİ": "bilgi"}
    bul = [Bulgu(seviye=sev.get(b.seviye, "uyarı"), kural="veri_erp", baslik=f"ERP: {b.tablo} / {b.kontrol}", mesaj=b.mesaj,
                 dayanak="ERP") for b in dogrula(yukle(klasor))]
    return rapor_olustur(bul, ["veri_erp"], "veri")


def erp_urun_listesi(klasor: str) -> Optional[Tuple[bytes, str]]:
    """Excel verilmediyse ERP'nin urunler tablosunun son sezonu ürün listesi olarak kullanılır (içe aktarıcı başlıkları tanır)."""
    import csv
    p = Path(klasor) / "urunler.csv"
    if not p.exists():
        return None
    rows = list(csv.DictReader(p.read_text(encoding="utf-8-sig").splitlines()))
    if not rows:
        return None
    if "sezon_kodu" in rows[0]:
        son = max(r["sezon_kodu"] for r in rows if r.get("sezon_kodu"))
        rows = [r for r in rows if r.get("sezon_kodu") == son]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue().encode("utf-8"), "urunler.csv"


async def calistir(excel: Optional[bytes], dosya_adi: str, gorseller: List[Tuple[str, bytes]], engine, profiler, predict,
                   fx_rate: float, ornek: int = 6, erp_klasor: Optional[str] = None, kok: Optional[str] = None,
                   bolgeler: Optional[List[str]] = None) -> dict:
    from ..collection.importer import ImageInfo, build_preview, read_workbook
    from ..collection.models import Collection, RunOptions
    from ..collection.runner import CollectionRunner
    from ..collection.store import CollectionStore
    from ..collection.summary import summarize

    t0 = time.time()
    if not excel:
        kaynak = erp_urun_listesi(erp_klasor) if erp_klasor else None
        if kaynak is None:
            raise ValueError("Ürün listesi yok: Excel verin ya da ERP klasöründe urunler.csv olsun")
        excel, dosya_adi = kaynak
    store = CollectionStore(kok or tempfile.mkdtemp(prefix="ilk-test-"))
    cid = store.new_id()
    for rel, data in gorseller:
        store.save_image(cid, rel, data)
    infos = [ImageInfo(rel, None, None) for rel in store.list_images(cid)]
    prev = build_preview(cid, read_workbook(excel, dosya_adi), infos)
    issues = [i.model_copy(update={"level": "uyarı", "message": i.message + " (ilk testte gri yer tutucu görsel kullanıldı)"})
              if i.level == "hata" and "Görsel" in i.message else i for i in prev.issues]
    veri = denetle_urunler([p.item for p in prev.items], issues)
    erp = erp_denetimi(erp_klasor) if erp_klasor else None

    secilen = _ornek_sec([p.item for p in prev.items], ornek)
    sonuc, kosu_notu = None, ""
    if secilen:
        ph = store.save_image(cid, PLACEHOLDER, _yer_tutucu())
        gorselsiz = 0
        for it in secilen:
            if not it.images:
                it.images = [ph]
                gorselsiz += 1
        meta = prev.meta.model_copy(update={"name": f"İlk veri testi ({prev.meta.name})"})
        if bolgeler:
            meta.target_regions = bolgeler
        col = Collection(id=cid, meta=meta, items=secilen, created=time.time(), status="hazır")
        store.save(col)
        runner = CollectionRunner()
        runner.start(col, RunOptions(showcase=True), store, engine, profiler, predict, fx_rate)
        await runner.tasks[cid]
        sonuc = summarize(col, store.results(cid, [i.sku for i in col.items]), fx_rate, showcase=store.showcase(cid))
        kosu_notu = (f"{len(prev.items)} üründen {len(secilen)} tanesi ({', '.join(sorted({i.category or '-' for i in secilen}))}) "
                     f"{', '.join(col.meta.target_regions)} bölgelerinde koşturuldu"
                     + (f"; {gorselsiz} ürüne görsel olmadığı için gri yer tutucu verildi (ilgi puanı görseli içermez)" if gorselsiz else "")
                     + ".")
    else:
        kosu_notu = "Maliyeti olan ürün yok; örnek koşu yapılamadı."

    parcalar = [("Ürün listesi", veri)] + ([("ERP verisi", erp)] if erp else []) + ([("Örnek koşu sonucu", sonuc.denetim)] if sonuc else [])
    tum = [b for _, r in parcalar for b in r.bulgular]
    genel = rapor_olustur(tum, [k for _, r in parcalar for k in r.kurallar], "ilk-test")
    return {"genel": genel, "parcalar": parcalar, "kosu_notu": kosu_notu, "sure_s": round(time.time() - t0, 1),
            "sonuc": sonuc, "collection_id": cid, "n_urun": len(prev.items)}


def calistir_sync(*a, **kw) -> dict:
    return asyncio.run(calistir(*a, **kw))
