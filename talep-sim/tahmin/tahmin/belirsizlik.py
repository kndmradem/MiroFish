"""Tahmin aralıkları: doğrulama sezonundaki hatalardan (konformal) öğrenilir.

Bir yöntem önce doğrulama sezonunu (test sezonundan önceki, kendi karar anı kuralıyla) tahmin
eder; gerçekleşen / tahmin oranının log dağılımı tahmin büyüklüğüne göre kovalara ayrılıp
saklanır. Test sezonunda aynı oranlar tahmine uygulanır. Böylece "%80 aralık" gerçekten
geçmişte %80 tutmuş bir genişliktir; test sezonunda tutup tutmadığı ayrıca ölçülür.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SEVIYELER = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)
ARALIKLAR = {50: (0.25, 0.75), 80: (0.10, 0.90), 90: (0.05, 0.95)}


def q_kolon(s: float) -> str:
    return f"q{int(round(s * 100)):02d}"


class KonformalAralik:
    def __init__(self, kova_sayisi: int = 3):
        self.kova_sayisi = kova_sayisi
        self.sinirlar: np.ndarray = np.array([])
        self.kantiller: np.ndarray = np.zeros((1, len(SEVIYELER)))

    def ogren(self, tahmin: np.ndarray, gercek: np.ndarray) -> "KonformalAralik":
        tahmin, gercek = np.asarray(tahmin, float), np.asarray(gercek, float)
        r = np.log1p(gercek) - np.log1p(np.maximum(tahmin, 0))
        n = len(r)
        k = max(1, min(self.kova_sayisi, n // 30))
        self.sinirlar = np.quantile(tahmin, np.linspace(0, 1, k + 1)[1:-1]) if k > 1 else np.array([])
        kova = np.searchsorted(self.sinirlar, tahmin)
        self.kantiller = np.vstack([
            np.quantile(r[kova == b], SEVIYELER) if (kova == b).sum() >= 10 else np.quantile(r, SEVIYELER)
            for b in range(k)])
        return self

    def uygula(self, tahmin: np.ndarray) -> pd.DataFrame:
        tahmin = np.maximum(np.asarray(tahmin, float), 0)
        kova = np.searchsorted(self.sinirlar, tahmin)
        q = self.kantiller[kova]
        deger = np.expm1(np.log1p(tahmin)[:, None] + q).clip(min=0)
        return pd.DataFrame(deger, columns=[q_kolon(s) for s in SEVIYELER])


def kantil_degeri(satir: pd.Series | dict, olasilik: float) -> float:
    """Kantil kolonları arasında doğrusal ara değer (gazeteci/newsvendor miktarı için)."""
    x = np.array(SEVIYELER)
    y = np.array([satir[q_kolon(s)] for s in SEVIYELER], float)
    return float(np.interp(np.clip(olasilik, x[0], x[-1]), x, np.maximum.accumulate(y)))
