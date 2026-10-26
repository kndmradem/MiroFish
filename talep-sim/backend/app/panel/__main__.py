"""Panel komut satırı: veri durumu ve ERP verisiyle backtest.

    python -m app.panel durum
    python -m app.panel geriye-test <erp_csv_klasoru> --surum v1 --surum v2 --usd-try 42 --en-fazla 30 [--terfi]

LLM ayarları .env'den (PANEL_LLM_* ya da LLM_*) okunur. Her ürün x bölge x kişi bir LLM çağrısıdır:
30 ürün, 3 bölge, 8 kişi ~ 720 çağrı (adaylar ve kalibrasyonlu tekrar koşu bunun katları); yerel modelde uzun sürer.
"""
import argparse
import asyncio
import json

from ..config import settings
from ..models import ALL_REGIONS


def _status() -> None:
    from .library import library_status
    from ..main import panel_store
    store = panel_store(settings)
    print(json.dumps({"active": store.active_version(), "versions": store.persona_versions(),
                      "regions": library_status(store, list(ALL_REGIONS))}, ensure_ascii=False, indent=2))


async def _backtest(a) -> None:
    from ..main import _fuser, panel_store
    from ..services.engine import MockSimulationEngine
    from .backtest import Candidate, compare, pipeline_predictor, promote
    from .erp_cases import load_cases
    from .questioner import PanelLLM

    store = panel_store(settings)
    cases = load_cases(a.klasor, regions=a.bolge or None, usd_try=a.usd_try)
    if a.en_fazla:  # zaman yayılımı korunsun diye eşit aralıklı örnek
        step = max(1, len(cases) // a.en_fazla)
        cases = cases[::step][: a.en_fazla]
    llm = PanelLLM(settings.panel_llm_base_url or settings.llm_base_url, settings.panel_llm_model or settings.llm_model,
                   settings.llm_api_key or "local", guided=settings.panel_guided, timeout=settings.panel_timeout,
                   concurrency=settings.panel_concurrency, repair_retries=settings.panel_repair_retries)
    predictor = pipeline_predictor(store, llm, _fuser(settings, MockSimulationEngine(latency_s=0)),
                                   panel_size=a.kisi, min_valid=min(settings.panel_min_valid, a.kisi))
    versions = a.surum or [store.active_version()]
    print(f"{len(cases)} ürün, sürümler: {', '.join(versions)}")
    results = await compare(cases, [Candidate(v, v) for v in versions], predictor)
    for r in results:
        print(f"{r.label}: kalibrasyonsuz WAPE %{r.raw_wape_pct}, kalibrasyonlu %{r.calibrated_wape_pct}, "
              f"oran {r.bias_ratio}, bölge {r.by_region} (eğitim {r.train_n}, test {r.test_n} ürün)")
    if a.terfi:
        print(promote(store, results)[1])


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m app.panel")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("durum")
    b = sub.add_parser("geriye-test")
    b.add_argument("klasor")
    b.add_argument("--surum", action="append")
    b.add_argument("--bolge", action="append", choices=ALL_REGIONS)
    b.add_argument("--usd-try", type=float, default=None)
    b.add_argument("--en-fazla", type=int, default=30)
    b.add_argument("--kisi", type=int, default=8)
    b.add_argument("--terfi", action="store_true")
    a = p.parse_args()
    if a.cmd == "durum":
        _status()
    else:
        asyncio.run(_backtest(a))


if __name__ == "__main__":
    main()
