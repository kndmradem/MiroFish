"""Ortam değişkenlerinden okunan ayarlar. Hiçbir anahtar yoksa her şey mock çalışır."""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:  # .env dosyaları: önce backend/.env, sonra repo kökündeki MiroFish .env (LLM_* ortak kullanılır)
    from dotenv import load_dotenv

    _here = Path(__file__).resolve()
    load_dotenv(_here.parents[1] / ".env")
    load_dotenv(_here.parents[3] / ".env")
except ImportError:  # python-dotenv yoksa yalnızca süreç ortamı okunur
    pass


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(name)
    return value if value not in (None, "") else default


@dataclass(frozen=True)
class Settings:
    # "mock" | "mirofish"
    sim_engine: str = field(default_factory=lambda: _env("SIM_ENGINE", "mock"))

    # MiroFish backend'i (kendi .env'inde LLM_* ve ZEP_API_KEY tanımlı olmalı)
    mirofish_url: str = field(default_factory=lambda: _env("MIROFISH_URL", "http://localhost:5001"))
    mirofish_state_file: str = field(default_factory=lambda: _env("MIROFISH_STATE_FILE", ".mirofish_world.json"))
    mirofish_max_rounds: int = field(default_factory=lambda: int(_env("MIROFISH_MAX_ROUNDS", "3")))
    mirofish_interview_timeout: int = field(default_factory=lambda: int(_env("MIROFISH_INTERVIEW_TIMEOUT", "180")))

    # Görsel + metin füzyonu için OpenAI uyumlu vision modeli (Qwen-VL, GPT-4o, Claude vb.)
    vision_api_key: Optional[str] = field(default_factory=lambda: _env("VISION_API_KEY"))
    vision_base_url: str = field(default_factory=lambda: _env("VISION_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"))
    vision_model: str = field(default_factory=lambda: _env("VISION_MODEL", "qwen-vl-plus"))

    # Marka profili ve öneriler için metin LLM'i (MiroFish'in LLM_* ayarlarıyla aynı adlar)
    llm_api_key: Optional[str] = field(default_factory=lambda: _env("LLM_API_KEY"))
    llm_base_url: str = field(default_factory=lambda: _env("LLM_BASE_URL", "https://api.openai.com/v1"))
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL_NAME", "gpt-4o-mini"))

    # Türkiye için TL gösterimi: 1 USD = ? TL (arayüzden istek bazında değiştirilebilir)
    usd_try_rate: float = field(default_factory=lambda: float(_env("USD_TRY_RATE", "42.0")))

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key)

    @property
    def vision_enabled(self) -> bool:
        return bool(self.vision_api_key)


settings = Settings()
