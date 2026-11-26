"""Mantık denetimi uç noktaları (/api/denetim/...)."""
import io
import zipfile
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse

from . import kural_listesi
from .rapor import html_, md

router = APIRouter(prefix="/api/denetim", tags=["denetim"])


@router.get("/kurallar")
async def kurallar() -> list:
    return kural_listesi()


@router.get("/koleksiyon/{cid}")
async def koleksiyon(cid: str, bicim: str = "json"):
    """Kayıtlı koleksiyonun bugünkü sonucunun denetimi. bicim: json | md | html (kurulum raporu, yazdırma)."""
    from ..collection import routes as cr
    res = cr._result(cid, cr.get_store(), None)
    r = res.denetim
    if bicim == "md":
        return PlainTextResponse(md(r, f"Mantık denetimi: {res.name}"))
    if bicim == "html":
        return HTMLResponse(html_(r, f"Mantık denetimi: {res.name}"))
    return r.model_dump()


@router.post("/ilk-test")
async def ilk_test(sheet: Optional[UploadFile] = File(None, description="Ürün listesi (koleksiyon şablonu); yoksa ERP urunler tablosu"),
                   images: List[UploadFile] = File(default_factory=list, description="Görseller ya da zip"),
                   erp_klasor: Optional[str] = Form(None, description="Sunucudaki ERP CSV klasörü (kurulumdaki ilk çekim)"),
                   ornek: int = Form(6, ge=1, le=30),
                   motor: str = Form("ayar", description="ayar (.env motoru) ya da mock (LLM'siz hızlı mantık testi)")) -> dict:
    """Kurulum sihirbazının ilk veri testi: ürün listesi + ERP kalite kontrolü + örnek koşu, tek denetim raporu."""
    from .. import main as m
    from ..config import settings
    from .ilk_test import calistir
    if motor not in ("ayar", "mock"):
        raise HTTPException(422, "motor ayar ya da mock olmalı")
    if motor == "mock":
        from ..services.engine import MockSimulationEngine
        engine = MockSimulationEngine(latency_s=0)
    else:
        ov = m.app.dependency_overrides
        engine = ov.get(m.get_engine, m.get_engine)()
    profiler = m.app.dependency_overrides.get(m.get_profiler, m.get_profiler)()
    gorseller = []
    for f in images:
        data = await f.read()
        if (f.filename or "").lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                gorseller += [(i.filename, z.read(i)) for i in z.infolist() if not i.is_dir() and "__MACOSX" not in i.filename]
        else:
            gorseller.append((f.filename or "gorsel.png", data))
    try:
        out = await calistir(await sheet.read() if sheet else None, (sheet.filename if sheet else None) or "liste.xlsx", gorseller, engine, profiler, m.run_prediction,
                             settings.usd_try_rate, ornek=ornek, erp_klasor=erp_klasor)
    except ValueError as e:
        raise HTTPException(422, str(e))
    g = out["genel"]
    not_ = f"{out['kosu_notu']} Süre {out['sure_s']} sn. Motor: {'mock (yalnızca mantık hattı)' if motor == 'mock' else settings.sim_engine}."
    return {"genel": g.model_dump(), "parcalar": [{"ad": ad, "rapor": r.model_dump()} for ad, r in out["parcalar"]], "not": not_,
            "md": md(g, "İlk veri testi: mantık denetimi", out["parcalar"], not_),
            "html": html_(g, "İlk veri testi: mantık denetimi", out["parcalar"], not_)}
