"""Görsel gömme (embedding) arayüzü. Değiştirilebilir: model indirmeden çalışan basit gömücü
varsayılandır; CLIP kuruluysa `clip` seçilebilir. Yeni bir model eklemek için `GorselGomucu`
protokolünü uygulayan bir sınıf yazıp GOMUCULER'e eklemek yeter.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

import numpy as np
import pandas as pd


class GorselGomucu(Protocol):
    ad: str

    def gom(self, yol: Path) -> np.ndarray: ...


def _l2(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


class RenkDokuGomucu:
    """Model gerektirmeyen gömücü: ürün piksellerinde HSV renk histogramı, doku (kenar yoğunluğu,
    çizgi yönü) ve 8x8 siluet. Renk, desen ve kalıbı yakalar; stil/tasarım dilini YAKALAMAZ."""

    ad = "renk_doku"

    def gom(self, yol: Path) -> np.ndarray:
        from PIL import Image

        img = Image.open(yol).convert("RGB").resize((64, 64))
        rgb = np.asarray(img, dtype=float) / 255
        hsv = np.asarray(img.convert("HSV"), dtype=float) / 255
        kose = np.concatenate([rgb[:4, :4].reshape(-1, 3), rgb[-4:, -4:].reshape(-1, 3)]).mean(0)
        on = np.abs(rgb - kose).sum(2) > 0.12
        if on.sum() < 20:
            on = np.ones_like(on)
        h, s, v = hsv[..., 0][on], hsv[..., 1][on], hsv[..., 2][on]
        hist, _ = np.histogramdd(np.stack([h, s, v], 1), bins=(8, 3, 3), range=((0, 1), (0, 1), (0, 1)))
        gri = rgb.mean(2)
        gx, gy = np.abs(np.diff(gri, axis=1))[:-1], np.abs(np.diff(gri, axis=0))[:, :-1]
        icerde = on[:-1, :-1]
        doku = np.array([gx[icerde].mean(), gy[icerde].mean(), (gx[icerde] > 0.08).mean(), (gy[icerde] > 0.08).mean(), gri[on].std()])
        siluet = on.reshape(8, 8, 8, 8).mean((1, 3)).ravel()
        return np.concatenate([_l2(hist.ravel()), _l2(doku) * 0.7, _l2(siluet) * 0.7])


class ClipGomucu:
    """open_clip ile CLIP ViT-B-32 (yaklaşık 350 MB indirir). `pip install open_clip_torch` gerekir."""

    ad = "clip"

    def __init__(self, model: str = "ViT-B-32", agirlik: str = "laion2b_s34b_b79k"):
        try:
            import open_clip  # type: ignore
            import torch  # type: ignore
        except ImportError as e:  # pragma: no cover - opsiyonel bağımlılık
            raise RuntimeError("CLIP için `pip install open_clip_torch` gerekli; varsayılan 'renk_doku' gömücüsünü kullan.") from e
        self._torch = torch
        self._model, _, self._on_isle = open_clip.create_model_and_transforms(model, pretrained=agirlik)
        self._model.eval()

    def gom(self, yol: Path) -> np.ndarray:  # pragma: no cover
        from PIL import Image

        with self._torch.no_grad():
            x = self._on_isle(Image.open(yol).convert("RGB")).unsqueeze(0)
            return _l2(self._model.encode_image(x)[0].numpy())


class SahteGomucu:
    """Görsel yokken ya da testte: sabit sıfır vektör (benzerliğe katkı yapmaz)."""

    ad = "yok"

    def gom(self, yol: Path) -> np.ndarray:
        return np.zeros(1)


GOMUCULER = {"renk_doku": RenkDokuGomucu, "clip": ClipGomucu, "yok": SahteGomucu}


def gomucu_sec(ad: str = "renk_doku") -> GorselGomucu:
    if ad not in GOMUCULER:
        raise ValueError(f"Bilinmeyen görsel gömücü: {ad} (seçenekler: {', '.join(GOMUCULER)})")
    return GOMUCULER[ad]()


def urun_gomuleri(gorseller: pd.DataFrame | None, klasor: Path, gomucu: GorselGomucu) -> dict[str, np.ndarray]:
    """ur_id (urun_kodu|renk_kodu) ya da urun_kodu -> gömme. Renge özel görsel yoksa model görseli kullanılır.
    Sonuç klasördeki önbelleğe yazılır."""
    if gorseller is None or gorseller.empty or gomucu.ad == "yok":
        return {}
    onbellek = klasor / f".gomme_{gomucu.ad}.npz"
    eski: dict[str, np.ndarray] = dict(np.load(onbellek)) if onbellek.exists() else {}
    out: dict[str, list[np.ndarray]] = {}
    for row in gorseller.itertuples():
        yol = klasor / "gorseller" / str(row.dosya_adi)
        if not yol.exists():
            continue
        if str(row.dosya_adi) not in eski:
            eski[str(row.dosya_adi)] = gomucu.gom(yol)
        anahtar = f"{row.urun_kodu}|{row.renk_kodu}" if isinstance(row.renk_kodu, str) and row.renk_kodu else str(row.urun_kodu)
        out.setdefault(anahtar, []).append(eski[str(row.dosya_adi)])
    try:
        np.savez_compressed(onbellek, **eski)
    except OSError:
        pass
    return {k: _l2(np.mean(v, 0)) for k, v in out.items()}
