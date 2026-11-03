"""Koleksiyonların diskte saklanması. Uzun koşu kesilirse kaldığı yerden devam edebilmek için her ürün sonucu
ayrı dosyaya yazılır.

collections/<id>/collection.json   üst bilgi + ürün listesi
collections/<id>/images/           yüklenen görseller (göreli yollarıyla)
collections/<id>/results/<sku>.json  ürün sonucu (tek ürün akışının PredictionResponse'u + girdi özeti)
collections/<id>/preview.json      son içe aktarma önizlemesi
"""
import hashlib
import json
import re
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from .models import Collection, ImportPreview

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "collections_data"


def safe_rel(path: str) -> str:
    """Yüklenen dosyanın göreli yolu; '..' ve mutlak yol temizlenir."""
    parts = [p for p in re.split(r"[\\/]+", path) if p not in ("", ".", "..")]
    return "/".join(parts)[-240:] or "dosya"


def sku_file(sku: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "_", sku)[:60]
    return f"{clean}-{hashlib.sha1(sku.encode()).hexdigest()[:6]}.json"


class CollectionStore:
    def __init__(self, root: Optional[str] = None):
        self.root = Path(root) if root else DEFAULT_DIR

    def new_id(self) -> str:
        return time.strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:8]

    def dir(self, cid: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9-]{4,40}", cid):
            raise KeyError(cid)
        return self.root / cid

    def image_dir(self, cid: str) -> Path:
        return self.dir(cid) / "images"

    def save_image(self, cid: str, rel: str, data: bytes) -> str:
        rel = safe_rel(rel)
        p = self.image_dir(cid) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return rel

    def image_path(self, cid: str, rel: str) -> Path:
        p = (self.image_dir(cid) / safe_rel(rel)).resolve()
        if not str(p).startswith(str(self.image_dir(cid).resolve())) or not p.is_file():
            raise KeyError(rel)
        return p

    def list_images(self, cid: str) -> List[str]:
        base = self.image_dir(cid)
        if not base.exists():
            return []
        return sorted(str(p.relative_to(base)).replace("\\", "/") for p in base.rglob("*") if p.is_file())

    def save_preview(self, prev: ImportPreview) -> None:
        d = self.dir(prev.collection_id)
        d.mkdir(parents=True, exist_ok=True)
        (d / "preview.json").write_text(prev.model_dump_json(indent=1), encoding="utf-8")

    def load_preview(self, cid: str) -> Optional[ImportPreview]:
        p = self.dir(cid) / "preview.json"
        return ImportPreview.model_validate_json(p.read_text(encoding="utf-8")) if p.exists() else None

    def save(self, col: Collection) -> None:
        d = self.dir(col.id)
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / "collection.json.tmp"
        tmp.write_text(col.model_dump_json(indent=1), encoding="utf-8")
        tmp.replace(d / "collection.json")

    def load(self, cid: str) -> Collection:
        p = self.dir(cid) / "collection.json"
        if not p.exists():
            raise KeyError(cid)
        return Collection.model_validate_json(p.read_text(encoding="utf-8"))

    def list(self) -> List[Collection]:
        if not self.root.exists():
            return []
        out = []
        for p in sorted(self.root.glob("*/collection.json"), reverse=True):
            try:
                out.append(Collection.model_validate_json(p.read_text(encoding="utf-8")))
            except Exception:
                continue
        return out

    def save_result(self, cid: str, sku: str, payload: dict) -> None:
        d = self.dir(cid) / "results"
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / (sku_file(sku) + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(d / sku_file(sku))

    def load_result(self, cid: str, sku: str) -> Optional[dict]:
        p = self.dir(cid) / "results" / sku_file(sku)
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def results(self, cid: str, skus: List[str]) -> Dict[str, dict]:
        return {s: r for s in skus if (r := self.load_result(cid, s)) is not None}

    def save_brand(self, cid: str, profile: dict) -> None:
        (self.dir(cid) / "brand.json").write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")

    def load_brand(self, cid: str) -> Optional[dict]:
        p = self.dir(cid) / "brand.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
