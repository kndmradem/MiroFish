import pytest

from app.advisor import Advisor
from app.main import app, get_advisor, get_engine, get_profiler
from app.services.brand_profiler import BrandProfiler
from app.services.engine import MockSimulationEngine


@pytest.fixture(autouse=True)
def isolated_app():
    """Testler ortamdaki .env/LLM anahtarından etkilenmesin: mock motor, LLM'siz profiler ve danışman."""
    app.dependency_overrides[get_engine] = lambda: MockSimulationEngine(latency_s=0)
    app.dependency_overrides[get_profiler] = lambda: BrandProfiler(None)
    app.dependency_overrides[get_advisor] = lambda: Advisor(None)
    yield app.dependency_overrides
    app.dependency_overrides.clear()
