"""İmzalı dağıtım paketi: bizim sunucumuzda paketlenir, müşteri kurulumunda doğrulanarak içe aktarılır.

Paket (.tar.gz) içeriği:
    manifest.json   {"format": 1, "publisher", "created_at", "files": {"context/TR/2026-11-01.json": sha256, ...}}
    manifest.sig    manifest.json baytlarının Ed25519 imzası (base64)
    context/<BÖLGE>/<as_of>.json

Müşteri tarafı yalnızca bizim açık anahtarımızla imzalanmış, özetleri tutan ve içindeki her paketi insan onaylı
(verified + approved_by) olan dosyaları kabul eder. İçe aktarma ağa çıkmaz.
"""
import base64
import hashlib
import io
import json
import re
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Sequence, Tuple

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from ..models import ALL_REGIONS
from ..panel.library import ContextPack

_MEMBER = re.compile(r"^context/(%s)/\d{4}-\d{2}-\d{2}\.json$" % "|".join(ALL_REGIONS))


class BundleError(ValueError):
    pass


def generate_keys() -> Tuple[bytes, bytes]:
    """(özel anahtar PEM, açık anahtar PEM). Özel anahtar yalnızca bizim sunucumuzda kalır."""
    key = Ed25519PrivateKey.generate()
    priv = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    pub = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    return priv, pub


def _add(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mtime = 0
    tar.addfile(info, io.BytesIO(data))


def build_bundle(packs: Sequence[ContextPack], private_key_pem: bytes, out: Path, publisher: str) -> Path:
    if not packs:
        raise BundleError("Paketlenecek bağlam paketi yok")
    files = {}
    for p in packs:
        if not (p.verified and p.approved_by):
            raise BundleError(f"{p.region} {p.version}: onaysız paket dağıtılamaz")
        name = f"context/{p.region}/{p.as_of.isoformat()}.json"
        files[name] = json.dumps(json.loads(p.model_dump_json()), ensure_ascii=False, indent=2).encode()
    manifest = json.dumps({"format": 1, "publisher": publisher,
                           "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                           "files": {n: hashlib.sha256(b).hexdigest() for n, b in sorted(files.items())}},
                          ensure_ascii=False, indent=2).encode()
    key = serialization.load_pem_private_key(private_key_pem, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise BundleError("Ed25519 özel anahtarı bekleniyordu")
    sig = base64.b64encode(key.sign(manifest))
    with tarfile.open(out, "w:gz") as tar:
        _add(tar, "manifest.json", manifest)
        _add(tar, "manifest.sig", sig)
        for n, b in sorted(files.items()):
            _add(tar, n, b)
    return out


def verify_bundle(bundle: Path, public_key_pem: bytes) -> Tuple[dict, List[ContextPack]]:
    """İmzayı, özetleri ve onayları doğrular; diske hiçbir şey yazmaz."""
    key = serialization.load_pem_public_key(public_key_pem)
    if not isinstance(key, Ed25519PublicKey):
        raise BundleError("Ed25519 açık anahtarı bekleniyordu")
    try:
        tar = tarfile.open(bundle, "r:gz")
    except (OSError, tarfile.TarError) as e:
        raise BundleError(f"Paket açılamadı: {e}") from e
    with tar:
        blobs = {}
        for m in tar.getmembers():
            if not m.isfile() or not (m.name in ("manifest.json", "manifest.sig") or _MEMBER.match(m.name)):
                raise BundleError(f"Beklenmeyen dosya: {m.name}")
            blobs[m.name] = tar.extractfile(m).read()
    if "manifest.json" not in blobs or "manifest.sig" not in blobs:
        raise BundleError("Manifest ya da imza eksik")
    try:
        key.verify(base64.b64decode(blobs["manifest.sig"]), blobs["manifest.json"])
    except (InvalidSignature, ValueError) as e:
        raise BundleError("İmza geçersiz: paket bizim tarafımızdan imzalanmamış ya da değiştirilmiş") from e
    manifest = json.loads(blobs["manifest.json"])
    listed = manifest.get("files") or {}
    present = {n for n in blobs if n.startswith("context/")}
    if set(listed) != present:
        raise BundleError("Manifestteki dosya listesi paketle uyuşmuyor")
    packs = []
    for name, digest in listed.items():
        if hashlib.sha256(blobs[name]).hexdigest() != digest:
            raise BundleError(f"{name}: özet tutmuyor (dosya değiştirilmiş)")
        pack = ContextPack.model_validate_json(blobs[name])
        if not (pack.verified and pack.approved_by):
            raise BundleError(f"{name}: onaysız paket")
        if name != f"context/{pack.region}/{pack.as_of.isoformat()}.json":
            raise BundleError(f"{name}: dosya adı paketin bölge/tarihiyle uyuşmuyor")
        packs.append(pack)
    return manifest, packs


def import_bundle(bundle: Path, data_root: Path, public_key_pem: bytes) -> List[str]:
    """Doğrulanan paketleri `data_root/context/<BÖLGE>/` altına yazar; yazılan yolları döner."""
    _, packs = verify_bundle(bundle, public_key_pem)
    written = []
    for p in packs:
        path = Path(data_root) / "context" / p.region / f"{p.as_of.isoformat()}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(json.loads(p.model_dump_json()), ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(str(path))
    return written
