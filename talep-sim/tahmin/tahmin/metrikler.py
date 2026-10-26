"""Hata ve kalibrasyon metrikleri."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .belirsizlik import ARALIKLAR, q_kolon


def wape(y, yhat) -> float:
    y, yhat = np.asarray(y, float), np.asarray(yhat, float)
    return float(np.abs(y - yhat).sum() / max(y.sum(), 1e-9))


def bias(y, yhat) -> float:
    """(Toplam tahmin - toplam gerçek) / toplam gerçek. Pozitif = fazla tahmin."""
    y, yhat = np.asarray(y, float), np.asarray(yhat, float)
    return float((yhat.sum() - y.sum()) / max(y.sum(), 1e-9))


def kapsama(y, alt, ust) -> float:
    y = np.asarray(y, float)
    return float(((y >= np.asarray(alt) - 1e-9) & (y <= np.asarray(ust) + 1e-9)).mean())


def ozet(df: pd.DataFrame, gercek: str, tahmin: str = "tahmin") -> dict:
    d = {"n": len(df), "gercek_toplam": float(df[gercek].sum()), "wape": wape(df[gercek], df[tahmin]), "bias": bias(df[gercek], df[tahmin])}
    for yuzde, (a, u) in ARALIKLAR.items():
        if q_kolon(a) in df:
            d[f"kapsama_{yuzde}"] = kapsama(df[gercek], df[q_kolon(a)], df[q_kolon(u)])
    if "q10" in df:
        d["genislik_80"] = float(np.median((df["q90"] - df["q10"]) / np.maximum(df[tahmin], 1)))
    return d
