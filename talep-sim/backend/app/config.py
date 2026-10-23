"""Ortam değişkenlerinden okunan ayarlar. Hiçbir anahtar yoksa her şey mock çalışır."""
import os
from dataclasses import dataclass, field
from typing import Optional


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

    @property
    def vision_enabled(self) -> bool:
        return bool(self.vision_api_key)


settings = Settings()
