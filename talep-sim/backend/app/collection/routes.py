"""Koleksiyon modu uç noktaları (/api/collections/...). Tek ürün uç noktaları değişmez."""
import io
import os
import time
import zipfile
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

from ..config import settings
from .importer import (IMAGE_EXT, UNSUPPORTED_IMAGE_EXT, ImageInfo, build_preview, data_uri_image, embedded_images, ext,
                       read_workbook, template_bytes)
from .models import (Collection, CollectionResult, ConfirmRequest, ImportPreview, Issue, MetaUpdate, RunOptions, RunStatus,
                     WhatIf)
from .runner import CollectionRunner
from .store import CollectionStore, safe_rel
from .summary import summarize

router = APIRouter(prefix="/api/collections", tags=["koleksiyon"])
_store = CollectionStore(os.getenv("COLLECTIONS_DIR") or None)
runner = CollectionRunner()
MAX_ZIP_FILES = 2000
MAX_IMAGE_BYTES = 15 * 1024 * 1024


def get_store() -> CollectionStore:
    return _store


def _deps():
    # main.py bu modülü en sonda içe aktarır; döngüsel içe aktarmayı önlemek için geç bağlanır
    from .. import main
    return main


def _fx(col: Collection) -> float:
    return col.meta.usd_try_rate or settings.usd_try_rate


def _load(store: CollectionStore, cid: str) -> Collection:
    try:
        return store.load(cid)
    except KeyError:
        raise HTTPException(404, "Koleksiyon bulunamadı")


def _dims(data: bytes):
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            return im.size
    except Exception:
        return None


@router.get("")
async def list_collections(kind: Optional[str] = None, store: CollectionStore = Depends(get_store)) -> list:
    return [{"id": c.id, "name": c.meta.name, "kind": c.meta.kind, "season": c.meta.season, "status": c.status,
             "items": len(c.items), "created": c.created, "running": runner.running(c.id)}
            for c in store.list() if not kind or c.meta.kind == kind]


@router.delete("/{cid}")
async def delete_collection(cid: str, store: CollectionStore = Depends(get_store)) -> dict:
    """Koleksiyonu ve ona ait her şeyi (sonuçlar, ajan cevapları, görseller) kalıcı olarak siler."""
    if runner.running(cid):
        raise HTTPException(409, "Koleksiyon şu an çalışıyor; önce durdurun, sonra silin.")
    try:
        store.delete(cid)
    except KeyError:
        raise HTTPException(404, "Koleksiyon bulunamadı")
    runner.tasks.pop(cid, None)
    return {"deleted": cid}


@router.get("/template.xlsx")
async def template() -> Response:
    return Response(template_bytes(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="urun-yukleme-sablonu.xlsx"'})


@router.post("/import", response_model=ImportPreview)
async def import_collection(sheet: UploadFile = File(..., description="Excel (.xlsx) ya da CSV"),
                            images: List[UploadFile] = File(default_factory=list, description="Görseller ya da zip"),
                            collection_id: Optional[str] = Form(None),
                            kind: str = Form("koleksiyon", description="koleksiyon ya da bagimsiz (aynı şablon)"),
                            variants: str = Form("model", description="Aynı SKU'nun renk satırları: model (birleştir) ya da renk (ayrı ürün)"),
                            store: CollectionStore = Depends(get_store)) -> ImportPreview:
    """Excel + görselleri alır, eşleştirir ve önizleme döner. Koleksiyon onaylanana kadar kaydedilmez
    (görseller taslak klasörüne yazılır). collection_id verilirse aynı taslağa yeni dosyalar eklenir."""
    if kind not in ("koleksiyon", "bagimsiz"):
        raise HTTPException(422, "kind koleksiyon ya da bagimsiz olmalı")
    if variants not in ("model", "renk"):
        raise HTTPException(422, "variants model ya da renk olmalı")
    name = sheet.filename or "liste.xlsx"
    if not name.lower().endswith((".xlsx", ".xlsm", ".csv")):
        raise HTTPException(422, "Ürün listesi .xlsx ya da .csv olmalı (eski .xls biçimini Excel'de .xlsx olarak kaydedin)")
    raw = await sheet.read()
    try:
        book = read_workbook(raw, name)
        found = embedded_images(raw) if not name.lower().endswith(".csv") else {}
    except Exception as e:
        raise HTTPException(422, f"Excel okunamadı: {type(e).__name__}: {e}")
    cid = collection_id or store.new_id()
    try:
        store.dir(cid)
    except KeyError:
        raise HTTPException(422, "Geçersiz koleksiyon kimliği")
    skipped: List[Issue] = []

    def add(rel: str, data: bytes):
        e = ext(rel)
        base = rel.rsplit("/", 1)[-1]
        if base.startswith(".") or "__MACOSX" in rel:
            return
        if e in UNSUPPORTED_IMAGE_EXT:
            skipped.append(Issue(level="uyarı", message=f"{rel}: {e} biçimi desteklenmiyor, JPG ya da PNG olarak kaydedin"))
            return
        if e not in IMAGE_EXT:
            skipped.append(Issue(level="bilgi", message=f"{rel}: görsel değil, yok sayıldı"))
            return
        if len(data) > MAX_IMAGE_BYTES:
            skipped.append(Issue(level="uyarı", message=f"{rel}: 15 MB'tan büyük, yok sayıldı"))
            return
        store.save_image(cid, rel, data)

    for f in images:
        data = await f.read()
        fname = safe_rel(f.filename or "dosya")
        if fname.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    for info in z.infolist()[:MAX_ZIP_FILES]:
                        if not info.is_dir() and info.file_size <= MAX_IMAGE_BYTES:
                            add(safe_rel(info.filename), z.read(info))
            except zipfile.BadZipFile:
                skipped.append(Issue(level="uyarı", message=f"{fname}: zip açılamadı"))
        else:
            add(fname, data)

    # Excel'e gömülü görseller ve hücredeki data URI görseller: satır numarasıyla saklanır, ürüne satırından bağlanır
    embedded: dict = {}
    for title, sh in book.items():
        for rowno, row in sh.rows:
            for v in row:
                d = data_uri_image(v)
                if d:
                    found.setdefault(title, {}).setdefault(rowno, []).append(d)
    for ti, (title, rows) in enumerate(found.items()):
        for rowno, imgs in rows.items():
            for k, (data, fmt) in enumerate(imgs):
                rel = f"excel-gorsel/s{ti + 1}-satir{rowno}" + (f"-{k + 1}" if k else "") + f".{fmt if fmt in ('png', 'jpg', 'webp') else 'png'}"
                if len(data) <= MAX_IMAGE_BYTES:
                    store.save_image(cid, rel, data)
                    embedded.setdefault(title, {}).setdefault(rowno, []).append(rel)

    infos = []
    for rel in store.list_images(cid):
        d = _dims(store.image_path(cid, rel).read_bytes())
        infos.append(ImageInfo(rel, *(d or (None, None))))
    prev = build_preview(cid, book, infos, kind, embedded, variants)
    prev.issues = skipped + prev.issues
    store.save_preview(prev)
    return prev


@router.get("/{cid}/preview", response_model=ImportPreview)
async def get_preview(cid: str, store: CollectionStore = Depends(get_store)) -> ImportPreview:
    try:
        prev = store.load_preview(cid)
    except KeyError:
        prev = None
    if prev is None:
        raise HTTPException(404, "Önizleme bulunamadı")
    return prev


@router.post("/{cid}/confirm", response_model=Collection)
async def confirm(cid: str, body: ConfirmRequest, store: CollectionStore = Depends(get_store)) -> Collection:
    """Önizlemede düzeltilen listeyi kaydeder. SKU'su ya da adı boş satırlar alınmaz, aynı SKU iki kez olamaz."""
    try:
        store.dir(cid)
    except KeyError:
        raise HTTPException(422, "Geçersiz koleksiyon kimliği")
    if runner.running(cid):
        raise HTTPException(409, "Koleksiyon şu an koşuyor; önce durdurun")
    items, seen = [], set()
    known = set(store.list_images(cid))
    for it in body.items:
        if not it.sku.strip() or not it.name.strip():
            continue
        if it.sku in seen:
            raise HTTPException(422, f"Aynı SKU iki kez: {it.sku}")
        seen.add(it.sku)
        items.append(it.model_copy(update={"images": [p for p in it.images if p in known]}))
    if not items:
        raise HTTPException(422, "Kaydedilecek ürün yok")
    try:
        old = store.load(cid)
        created = old.created
    except KeyError:
        created = time.time()
    col = Collection(id=cid, meta=body.meta, items=items, created=created, status="hazır")
    store.save(col)
    return col


@router.get("/{cid}", response_model=Collection)
async def get_collection(cid: str, store: CollectionStore = Depends(get_store)) -> Collection:
    return _load(store, cid)


@router.put("/{cid}/meta", response_model=Collection)
async def update_meta(cid: str, body: MetaUpdate, store: CollectionStore = Depends(get_store)) -> Collection:
    """Koleksiyon bilgisini (marka, bütçe, bölgeler...) günceller. Ürün listesi değişmez. Marka değişirse sonraki
    çalıştırmada ürünler yeniden sorulur."""
    if runner.running(cid):
        raise HTTPException(409, "Koleksiyon şu an koşuyor; önce durdurun")
    col = _load(store, cid)
    col.meta = body.meta
    store.save(col)
    return col


@router.get("/{cid}/images/{path:path}")
async def image(cid: str, path: str, store: CollectionStore = Depends(get_store)):
    try:
        return FileResponse(store.image_path(cid, path))
    except KeyError:
        raise HTTPException(404, "Görsel yok")


@router.post("/{cid}/run", response_model=RunStatus)
async def run(cid: str, opts: RunOptions, store: CollectionStore = Depends(get_store)) -> RunStatus:
    """Koşuyu arka planda başlatır; ilerleme için /status. Sonucu olan ürünler (girdi değişmediyse) atlanır."""
    col = _load(store, cid)
    m = _deps()
    ov = m.app.dependency_overrides
    engine = ov.get(m.get_engine, m.get_engine)()
    profiler = ov.get(m.get_profiler, m.get_profiler)()
    return runner.start(col, opts, store, engine, profiler, m.run_prediction, _fx(col))


@router.get("/{cid}/status", response_model=RunStatus)
async def status(cid: str, store: CollectionStore = Depends(get_store)) -> RunStatus:
    st = runner.get(cid)
    if not st.running and not st.total:
        col = _load(store, cid)
        res = store.results(cid, [i.sku for i in col.items])
        st = RunStatus(collection_id=cid, running=False, total=len(col.items), done=len(res),
                       failed=[s for s, r in res.items() if not r.get("response")])
    return st


@router.post("/{cid}/stop", response_model=RunStatus)
async def stop(cid: str) -> RunStatus:
    runner.stop(cid)
    return runner.get(cid)


def _result(cid: str, store: CollectionStore, whatif: Optional[WhatIf]) -> CollectionResult:
    col = _load(store, cid)
    return summarize(col, store.results(cid, [i.sku for i in col.items]), _fx(col), whatif, showcase=store.showcase(cid))


@router.get("/{cid}/result", response_model=CollectionResult)
async def result(cid: str, store: CollectionStore = Depends(get_store)) -> CollectionResult:
    return _result(cid, store, None)


@router.post("/{cid}/whatif", response_model=CollectionResult)
async def whatif(cid: str, body: WhatIf, store: CollectionStore = Depends(get_store)) -> CollectionResult:
    """Ürün çıkarma, planlanan fiyat ve bütçe değişikliği: LLM çağırmadan kayıtlı cevaplardan yeniden hesaplar."""
    return _result(cid, store, body)


@router.get("/{cid}/items/{sku}/prediction")
async def item_prediction(cid: str, sku: str, store: CollectionStore = Depends(get_store)) -> dict:
    """Ürünün tek ürün ekranındaki ayrıntılı sonucu (fiyat bölgeleri, iade, satış, senaryolar)."""
    try:
        r = store.load_result(cid, sku)
    except KeyError:
        r = None
    if not r or not r.get("response"):
        raise HTTPException(404, (r or {}).get("error") or "Bu ürünün sonucu yok")
    out = dict(r["response"])
    # Bu ekrandaki adet, satış ve stok hesabı ürünün koşudaki eşit bütçe payıyla yapıldı; koleksiyonun asıl kararı ve
    # adedi (bütçenin ürünler arasında talebe göre dağıtımı, renk payları) ayrıca verilir ki iki ekran karıştırılmasın.
    try:
        res = _result(cid, store, None)
        it = next((i for i in res.items if i.sku == sku), None)
    except Exception:
        it = None
    if it is not None:
        out["collection_context"] = {
            "decision": it.decision, "qty": it.recommended_qty.value, "qty_by_region": it.qty_by_region,
            "colors": [{"color": c.color, "qty": c.qty, "decision": c.decision} for c in it.colors],
            "detail_qty": sum(int(x.get("recommended_production_qty") or 0) for x in out.get("regional_breakdown", [])),
        }
    return out


@router.get("/{cid}/export.xlsx")
async def export(cid: str, store: CollectionStore = Depends(get_store)) -> Response:
    res = _result(cid, store, None)
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.title = "Ürünler"
    rate = res.fx_rate if res.currency == "TRY" else 1.0
    indep = res.kind == "bagimsiz"
    head = ["SKU", "Ürün", "Kategori", "Hedef kitle (dayanak)", "Karar", "Karar kaynağı", "Karar gerekçesi (dayanak)", "Talep skoru (ajan)",
            f"Önerilen fiyat ({res.currency}, ajan)", f"Kabul aralığı ({res.currency}, ajan)", "Net marj % (kural)"]
    if not indep:
        head += ["Sıra", "Sıra aralığı", "Koleksiyon içi fark (ajan)", "Hevesli % (ajan)", "Rol (kural)", "Rol nedeni", "Hedef rol"]
    head += ["Önerilen adet (kural)", "Planlanan adet", "Bayraklar"]
    for r in res.regions:
        head += [f"{r} talep", f"{r} önerilen fiyat ({res.currency})", f"{r} net marj %", f"{r} iade %", f"{r} adet"]
    ws.append(head)
    for c in ws[1]:
        c.font = Font(bold=True)
    for it in res.items:
        reg = {x.region: x for x in it.regions}
        rp = it.recommended_price
        a = it.audience
        row = [it.sku, it.name, it.category, f"{a.label} ({a.source})" if a else "", it.decision or "", it.decision_source if it.decision else "",
               "; ".join(f"{x.text} ({x.basis})" for x in it.decision_reasons), it.appeal.value,
               round(rp.value * rate, 2) if rp.value else None,
               f"{round(rp.low * rate):,} - {round(rp.high * rate):,}" if rp.low is not None else "", it.net_margin.value]
        if not indep:
            row += [it.rank.value, f"{int(it.rank.low)}-{int(it.rank.high)}" if it.rank.low is not None else "",
                    it.relative.value, it.enthusiast_pct.value, it.role, it.role_why, it.declared_role or ""]
        row += [it.recommended_qty.value, it.planned_qty, ", ".join(it.flags)]
        for r in res.regions:
            x = reg.get(r)
            row += [x.demand, round(x.optimal_price * rate, 2), x.net_margin_pct, x.return_pct, it.qty_by_region.get(r)] if x else [None] * 5
        ws.append(row)
    if any(it.colors for it in res.items):
        cp = res.color_plan
        rs = wb.create_sheet("Renkler")
        basis = cp.source if cp else "kural varsayımı"
        ch = ["SKU", "Ürün", "Model kararı", "Renk", "Renk kodu", "Renk ailesi", f"Pay % ({basis})", "Renk kararı",
              "Karar kaynağı", "Gerekçe (dayanak)", "Adet"] + [f"{r} adet" for r in res.regions]
        rs.append(ch)
        for c in rs[1]:
            c.font = Font(bold=True)
        for it in res.items:
            for c in it.colors:
                rs.append([it.sku, it.name, it.decision or "", c.color, c.code, c.family_label, c.share.value, c.decision or "",
                           c.decision_source if c.decision else "", "; ".join(f"{x.text} ({x.basis})" for x in c.reasons), c.qty]
                          + [c.qty_by_region.get(r) for r in res.regions])
        if cp:
            rs.append([])
            rs.append(["Renk ailesi", "Model", "Renk", "Adet", "Koleksiyon payı %"] + [f"{r} adet" for r in res.regions])
            for f in cp.families:
                rs.append([f.label, f.n_models, f.n_colors, f.qty, f.share_pct] + [f.by_region.get(r) for r in res.regions])
            rs.append([])
            rs.append([cp.source_note])
    notes = wb.create_sheet("Notlar")
    for a in res.summary.actions:
        notes.append([a.kind, a.text, a.basis])
    notes.append([])
    for n in res.notes:
        notes.append([n])
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{"urunler" if indep else "koleksiyon"}-{cid}.xlsx"'})
