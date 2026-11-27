import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tahmin.sentetik import SentetikAyar, uret  # noqa: E402


@pytest.fixture(scope="session")
def sentetik_klasor(tmp_path_factory):
    """Küçük sentetik veri: 3 yıl (6 sezon), sezon başına 12 model."""
    klasor = tmp_path_factory.mktemp("sentetik")
    uret(klasor, SentetikAyar(tohum=3, model_sayisi=12))
    return klasor
