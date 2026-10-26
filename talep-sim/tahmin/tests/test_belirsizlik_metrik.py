import numpy as np

from tahmin.belirsizlik import SEVIYELER, KonformalAralik, kantil_degeri, q_kolon
from tahmin.metrikler import bias, kapsama, wape


def test_metrikler():
    assert wape([10, 10], [12, 8]) == 0.2
    assert bias([10, 10], [12, 10]) == 0.1
    assert kapsama([1, 5, 9], [0, 6, 0], [2, 7, 10]) == 2 / 3


def test_konformal_kapsama_nominale_yakin():
    rng = np.random.default_rng(0)
    def ornek(n):
        tahmin = rng.lognormal(3, 1, n)
        return tahmin, rng.poisson(tahmin * rng.lognormal(0, 0.4, n))
    a = KonformalAralik().ogren(*ornek(3000))
    t, y = ornek(3000)
    q = a.uygula(t)
    for alt, ust, hedef in ((0.25, 0.75, 0.5), (0.10, 0.90, 0.8), (0.05, 0.95, 0.9)):
        assert abs(kapsama(y, q[q_kolon(alt)], q[q_kolon(ust)]) - hedef) < 0.04


def test_kantil_degeri_monoton_ve_sinirli():
    satir = {q_kolon(s): v for s, v in zip(SEVIYELER, [5, 8, 10, 12, 15, 20, 25])}
    assert kantil_degeri(satir, 0.5) == 12
    assert kantil_degeri(satir, 0.99) == 25
    assert kantil_degeri(satir, 0.6) < kantil_degeri(satir, 0.7)
