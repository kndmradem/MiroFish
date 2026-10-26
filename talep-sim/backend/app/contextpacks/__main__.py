"""Bağlam paketi komutları.

Bizim sunucumuzda (internet ve bulut model anahtarı var):
    python -m app.contextpacks anahtar --cikti anahtarlar/                    # bir kez: imza anahtarı üret
    python -m app.contextpacks taslak TR --tarih 2026-11-01 --cikti taslak/TR.json
    python -m app.contextpacks onayla taslak/TR.json --onaylayan "Adem" --cikti onayli/TR.json
    python -m app.contextpacks paketle onayli/*.json --anahtar anahtarlar/ozel.pem --cikti baglam-2026-11.tar.gz

Müşteri kurulumunda (ağa çıkmaz):
    python -m app.contextpacks ice-aktar baglam-2026-11.tar.gz --acik-anahtar acik.pem [--veri panel_data]

Taslak için ortam: CONTEXT_LLM_BASE_URL, CONTEXT_LLM_MODEL, CONTEXT_LLM_API_KEY ve isteğe bağlı
CONTEXT_LLM_EXTRA (sağlayıcının web arama aracını açan JSON, ör. tools tanımı; sağlayıcı dokümanına bak).
"""
import argparse
import asyncio
import json
import os
import sys
from datetime import date
from pathlib import Path

from ..panel.library import ContextPack


def _load(path: str) -> ContextPack:
    return ContextPack.model_validate_json(Path(path).read_text(encoding="utf-8"))


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m app.contextpacks")
    sub = p.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("anahtar")
    k.add_argument("--cikti", required=True)
    t = sub.add_parser("taslak")
    t.add_argument("bolge")
    t.add_argument("--tarih", default=date.today().isoformat())
    t.add_argument("--kategori", action="append")
    t.add_argument("--cikti", required=True)
    o = sub.add_parser("onayla")
    o.add_argument("dosya")
    o.add_argument("--onaylayan", required=True)
    o.add_argument("--surum")
    o.add_argument("--cikti", required=True)
    b = sub.add_parser("paketle")
    b.add_argument("dosyalar", nargs="+")
    b.add_argument("--anahtar", required=True)
    b.add_argument("--yayinci", default="talep-sim")
    b.add_argument("--cikti", required=True)
    i = sub.add_parser("ice-aktar")
    i.add_argument("paket")
    i.add_argument("--acik-anahtar", required=True)
    i.add_argument("--veri", default=None)
    a = p.parse_args()

    if a.cmd == "anahtar":
        from .bundle import generate_keys
        priv, pub = generate_keys()
        d = Path(a.cikti)
        d.mkdir(parents=True, exist_ok=True)
        (d / "ozel.pem").write_bytes(priv)
        os.chmod(d / "ozel.pem", 0o600)
        (d / "acik.pem").write_bytes(pub)
        print(f"{d}/ozel.pem (gizli, yalnızca bizim sunucumuzda) ve {d}/acik.pem (müşteri kurulumlarına) yazıldı.")
    elif a.cmd == "taslak":
        from .drafter import DraftRequest, OpenAICompatResearcher, draft_pack, dump, report_text
        base, model, key = (os.getenv("CONTEXT_LLM_BASE_URL"), os.getenv("CONTEXT_LLM_MODEL"),
                            os.getenv("CONTEXT_LLM_API_KEY"))
        if not (base and model and key):
            sys.exit("CONTEXT_LLM_BASE_URL, CONTEXT_LLM_MODEL ve CONTEXT_LLM_API_KEY gerekli")
        extra = json.loads(os.getenv("CONTEXT_LLM_EXTRA") or "{}")
        req = DraftRequest(region=a.bolge, as_of=date.fromisoformat(a.tarih),
                           **({"categories": a.kategori} if a.kategori else {}))
        pack, rep = asyncio.run(draft_pack(req, OpenAICompatResearcher(base, model, key, extra)))
        Path(a.cikti).parent.mkdir(parents=True, exist_ok=True)
        Path(a.cikti).write_text(dump(pack), encoding="utf-8")
        print(report_text(rep))
    elif a.cmd == "onayla":
        from .drafter import dump
        from .review import ApprovalError, approve
        try:
            pack = approve(_load(a.dosya), a.onaylayan, a.surum)
        except ApprovalError as e:
            sys.exit(str(e))
        Path(a.cikti).parent.mkdir(parents=True, exist_ok=True)
        Path(a.cikti).write_text(dump(pack), encoding="utf-8")
        print(f"Onaylandı: {pack.region} {pack.version} -> {a.cikti}")
    elif a.cmd == "paketle":
        from .bundle import build_bundle
        out = build_bundle([_load(f) for f in a.dosyalar], Path(a.anahtar).read_bytes(), Path(a.cikti), a.yayinci)
        print(f"İmzalı paket: {out}")
    else:
        from ..config import settings
        from ..panel.library import DEFAULT_DATA_DIR
        from .bundle import BundleError, import_bundle
        root = Path(a.veri or settings.panel_data_dir or DEFAULT_DATA_DIR)
        try:
            for w in import_bundle(Path(a.paket), root, Path(a.acik_anahtar).read_bytes()):
                print(f"İçe aktarıldı: {w}")
        except BundleError as e:
            sys.exit(f"Reddedildi: {e}")


if __name__ == "__main__":
    main()
