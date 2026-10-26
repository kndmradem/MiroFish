"""Panel üyelerine toplu, yapılandırılmış soru: kişi başına tek LLM çağrısı, eşzamanlılık ayarlanabilir.

Cevap güvenliği üç katmanlı:
1. Sunucu destekliyorsa JSON şemasıyla kılavuzlu çözümleme (vLLM guided decoding, Ollama >= 0.5,
   OpenAI json_schema). Desteklemiyorsa otomatik olarak json_object'e, o da yoksa düz metne düşülür.
2. Hoşgörülü ayrıştırma (kod bloğu, metin içi JSON, eş anlamlı etiketler; answer_extractor ile ortak).
3. Bir küçük onarım denemesi: bozuk cevap modele geri verilir, yalnızca düzeltilmiş JSON istenir.
"""
import asyncio
import logging
import re
from dataclasses import dataclass
from typing import List, Optional

import httpx

from ..services.answer_extractor import parse_agent_answer
from ..services.llm import http_error_text
from .prompts import answer_schema, repair_prompt

log = logging.getLogger(__name__)
GUIDED_MODES = ("json_schema", "json_object", "none")


@dataclass
class PanelReply:
    answer: Optional[dict]
    status: str            # json | repaired | partial | failed | error
    text: str
    error: str = ""


class PanelLLM:
    """OpenAI uyumlu /chat/completions istemcisi (Ollama, vLLM, LM Studio, bulut)."""

    def __init__(self, base_url: str, model: str, api_key: str = "local", guided: str = "json_schema",
                 temperature: float = 0.7, max_tokens: int = 400, timeout: float = 180,
                 concurrency: int = 2, repair_retries: int = 1, client: Optional[httpx.AsyncClient] = None):
        if guided not in GUIDED_MODES:
            raise ValueError(f"guided {GUIDED_MODES} değerlerinden biri olmalı")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key or "local"
        self.guided = guided
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.repair_retries = max(0, repair_retries)
        self.client = client or httpx.AsyncClient(timeout=timeout)
        self.gate = asyncio.Semaphore(max(1, concurrency))
        self.calls = 0

    def _format(self, n_steps: int) -> Optional[dict]:
        if self.guided == "json_schema":
            return {"type": "json_schema", "json_schema": {"name": "panel_answer", "strict": True,
                                                           "schema": answer_schema(n_steps)}}
        if self.guided == "json_object":
            return {"type": "json_object"}
        return None

    async def _chat(self, messages: List[dict], n_steps: int, seed: Optional[int]) -> str:
        body = {"model": self.model, "messages": messages, "temperature": self.temperature,
                "max_tokens": self.max_tokens}
        if seed is not None:
            body["seed"] = seed
        while True:
            fmt = self._format(n_steps)
            if fmt:
                body["response_format"] = fmt
            else:
                body.pop("response_format", None)
            self.calls += 1
            resp = await self.client.post(f"{self.base_url}/chat/completions", json=body,
                                          headers={"Authorization": f"Bearer {self.api_key}"})
            # Şemayı tanımayan sunucu 400/422 döner: bir alt kipe inip aynı isteği tekrarla (kalıcı olarak).
            if resp.status_code in (400, 422) and fmt and re.search(r"response_format|json_schema|schema|format",
                                                                     resp.text, re.I):
                fallback = "json_object" if self.guided == "json_schema" else "none"
                log.warning("LLM sunucusu %s kipini desteklemiyor, %s kipine geçiliyor: %s",
                            self.guided, fallback, resp.text[:200])
                self.guided = fallback
                continue
            if resp.status_code >= 400:
                raise httpx.HTTPStatusError(http_error_text(resp), request=resp.request, response=resp)
            return resp.json()["choices"][0]["message"]["content"] or ""

    async def ask(self, system: str, user: str, ladder: List[float], seed: Optional[int] = None) -> PanelReply:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        async with self.gate:
            try:
                text = await self._chat(messages, len(ladder), seed)
            except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
                return PanelReply(None, "error", "", f"{type(e).__name__}: {e}")
            answer = parse_agent_answer(text, ladder)
            if answer is not None and answer["prices"] is not None:
                return PanelReply(answer, "json", text)
            for _ in range(self.repair_retries):
                problem = ("fiyat merdiveni etiketleri eksik ya da okunamadı" if answer is not None
                           else "geçerli bir JSON nesnesi bulunamadı")
                messages += [{"role": "assistant", "content": text[:1500]},
                             {"role": "user", "content": repair_prompt(problem, len(ladder))}]
                try:
                    fixed = await self._chat(messages, len(ladder), seed)
                except (httpx.HTTPError, KeyError, IndexError, ValueError):
                    break
                repaired = parse_agent_answer(fixed, ladder)
                if repaired is not None and repaired["prices"] is not None:
                    return PanelReply(repaired, "repaired", fixed)
                answer = answer or repaired
                text = fixed
            if answer is not None:
                return PanelReply(answer, "partial", text)  # yalnızca ilgi puanı
            return PanelReply(None, "failed", text)
