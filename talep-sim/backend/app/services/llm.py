"""OpenAI uyumlu sohbet uç noktası için JSON odaklı ince istemci (marka profili, öneriler).

Yerel Ollama/Qwen, bulut LLM ya da MiroFish ile aynı LLM_* ayarları kullanılabilir.
"""
import json
import re
from typing import Optional

import httpx


class LLMError(RuntimeError):
    pass


def http_error_text(resp: httpx.Response) -> str:
    """Sunucunun cevap gövdesini de içeren hata metni (Ollama 400'ün nedenini gövdede yazar)."""
    return f"HTTP {resp.status_code} {resp.request.url}: {resp.text.strip()[:600] or '(boş cevap)'}"


def extract_json(text: str):
    """Cevabın içindeki ilk JSON nesnesini ya da dizisini çıkarır."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)  # düşünen modellerin izi
    match = re.search(r"(\{.*\}|\[.*\])", text, re.S)
    if not match:
        raise LLMError(f"Model JSON dönmedi: {text[:200]!r}")
    try:
        return json.loads(match.group(1))
    except ValueError as e:
        raise LLMError(f"Model geçersiz JSON döndü: {e}") from e


class LLMClient:
    def __init__(self, api_key: str, base_url: str, model: str,
                 client: Optional[httpx.AsyncClient] = None, timeout: float = 240):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.client = client or httpx.AsyncClient(timeout=timeout)

    async def chat_json(self, system: str, prompt: str, retries: int = 1):
        """JSON cevap ister; ayrıştırılamazsa `retries` kez daha sorar."""
        last: Optional[Exception] = None
        for _ in range(1 + retries):
            try:
                resp = await self.client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"model": self.model, "temperature": 0.2,
                          "response_format": {"type": "json_object"},
                          "messages": [{"role": "system", "content": system},
                                       {"role": "user", "content": prompt}]},
                )
                if resp.status_code >= 400:
                    raise LLMError(http_error_text(resp))
                return extract_json(resp.json()["choices"][0]["message"]["content"])
            except (httpx.HTTPError, KeyError, IndexError, LLMError, ValueError) as e:
                last = e if str(e) else LLMError(type(e).__name__)
                if isinstance(e, LLMError) and str(e).startswith("HTTP 4"):
                    break  # istemci hatası tekrarla düzelmez
        raise LLMError(f"LLM çağrısı başarısız: {last}") from last
