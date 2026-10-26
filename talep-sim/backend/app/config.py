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
    # "mock" | "panel" (MiroFish'siz, önerilen) | "mirofish"
    sim_engine: str = field(default_factory=lambda: _env("SIM_ENGINE", "mock"))

    # --- SIM_ENGINE=panel: doğrudan persona paneli (Zep/MiroFish yok) ---
    # Persona kütüphanesi, bağlam paketleri, active.json ve calibration.json bu klasörde (boşsa backend/panel_data)
    panel_data_dir: Optional[str] = field(default_factory=lambda: _env("PANEL_DATA_DIR"))
    # true (üretim): yerel model yalnızca insan onaylı, imzalı paketle gelen bağlamı görür
    panel_require_verified: bool = field(default_factory=lambda: _env("PANEL_REQUIRE_VERIFIED", "false").lower() in ("1", "true", "yes", "on"))
    panel_size: int = field(default_factory=lambda: int(_env("PANEL_SIZE", "12")))          # bölge başına kişi
    panel_min_valid: int = field(default_factory=lambda: int(_env("PANEL_MIN_VALID", "4")))
    panel_concurrency: int = field(default_factory=lambda: int(_env("PANEL_CONCURRENCY", "2")))  # aynı anda LLM çağrısı
    # json_schema (vLLM, Ollama >= 0.5) | json_object | none; desteklenmezse otomatik bir alta iner
    panel_guided: str = field(default_factory=lambda: _env("PANEL_GUIDED", "json_schema"))
    panel_temperature: float = field(default_factory=lambda: float(_env("PANEL_TEMPERATURE", "0.7")))
    panel_timeout: int = field(default_factory=lambda: int(_env("PANEL_TIMEOUT", "180")))
    panel_repair_retries: int = field(default_factory=lambda: int(_env("PANEL_REPAIR_RETRIES", "1")))
    panel_peer_round: bool = field(default_factory=lambda: _env("PANEL_PEER_ROUND", "false").lower() in ("1", "true", "yes", "on"))
    # Boşsa LLM_* ayarları kullanılır (aynı yerel model)
    panel_llm_base_url: Optional[str] = field(default_factory=lambda: _env("PANEL_LLM_BASE_URL"))
    panel_llm_model: Optional[str] = field(default_factory=lambda: _env("PANEL_LLM_MODEL"))

    # MiroFish backend'i (kendi .env'inde LLM_* ve ZEP_API_KEY tanımlı olmalı)
    mirofish_url: str = field(default_factory=lambda: _env("MIROFISH_URL", "http://localhost:5001"))
    mirofish_state_file: str = field(default_factory=lambda: _env("MIROFISH_STATE_FILE", ".mirofish_world.json"))
    mirofish_max_rounds: int = field(default_factory=lambda: int(_env("MIROFISH_MAX_ROUNDS", "3")))
    mirofish_interview_timeout: int = field(default_factory=lambda: int(_env("MIROFISH_INTERVIEW_TIMEOUT", "180")))
    # Yavaş yerel model için: grup başına ajan sayısı, zaman aşımında yeniden deneme,
    # aynı anda kaç bölge, bir bölge için gereken en az geçerli ajan cevabı
    # Dünya kurma çağrıları (ontoloji, grafik, hazırlık) için saniye cinsinden okuma zaman aşımı
    mirofish_build_timeout: int = field(default_factory=lambda: int(_env("MIROFISH_BUILD_TIMEOUT", "3600")))
    mirofish_batch_size: int = field(default_factory=lambda: int(_env("MIROFISH_BATCH_SIZE", "3")))
    mirofish_timeout_retries: int = field(default_factory=lambda: int(_env("MIROFISH_TIMEOUT_RETRIES", "1")))
    mirofish_concurrency: int = field(default_factory=lambda: int(_env("MIROFISH_CONCURRENCY", "1")))
    mirofish_agents_per_region: int = field(default_factory=lambda: int(_env("MIROFISH_AGENTS_PER_REGION", "10")))
    mirofish_min_valid: int = field(default_factory=lambda: int(_env("MIROFISH_MIN_VALID", "2")))

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
