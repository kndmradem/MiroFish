"""Test ve demo için sahte OpenAI uyumlu LLM sunucusu (gerçek model yokken panel motorunu uçtan uca koşmak için).

Cevaplar kişinin prompttaki fiyat duyarlılığına ve fiyat merdivenine göre deterministik üretilir; anlamlı bir
tüketici görüşü DEĞİLDİR, yalnızca boru hattını sınar.

    uvicorn app.panel.mock_llm:app --port 11500
    PANEL_LLM_BASE_URL=http://localhost:11500/v1 SIM_ENGINE=panel uvicorn app.main:app --port 8000

Davranış bayrakları (ortam değişkeni): MOCK_LLM_NO_SCHEMA=1 json_schema'yı 400 ile reddeder (alt kipe düşüşü
sınar), MOCK_LLM_BROKEN_FIRST=1 her konuşmanın ilk cevabını bozuk yazar (onarım denemesini sınar).
"""
import hashlib
import json
import os
import re
from typing import List

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

OBJECTIONS = ("Fiyatı bütçeme göre yüksek", "Kumaşın bakımı zahmetli görünüyor", "Renk seçeneği az",
              "Benzerini daha uygun fiyata bulabilirim", "Kesimi bana uymayabilir")


def fake_answer(messages: List[dict]) -> dict:
    system = next((m["content"] for m in messages if m["role"] == "system"), "")
    user = next((m["content"] for m in messages if m["role"] == "user"), "")
    m = re.search(r"\((\d\.\d+)/1\)", system)
    sens = float(m.group(1)) if m else 0.5
    ladder = [float(x.replace(",", "")) for x in re.findall(r"^\d+\) \$([\d,\.]+)", user, re.M)]
    h = int(hashlib.sha256(system.encode()).hexdigest()[:6], 16)
    if not ladder:
        return {"interest": 50, "ladder": {}, "objection": "", "reason": ""}
    center = ladder[len(ladder) // 2] * (1.25 - 0.5 * sens)
    labels = {}
    for i, p in enumerate(ladder, 1):
        r = p / center
        labels[str(i)] = "supheli" if r < 0.55 else "uygun" if r < 1.1 else "pahali" if r < 1.5 else "cok_pahali"
    interest = int(max(5, min(95, 78 - 35 * sens + (h % 15) - 7 + (5 if "Diğer tüketicilerin" in user else 0))))
    return {"interest": interest, "ladder": labels, "objection": OBJECTIONS[h % len(OBJECTIONS)],
            "reason": "deterministik test cevabı"}


def completion(content: str, model: str) -> dict:
    return {"id": "mock", "object": "chat.completion", "model": model,
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}]}


def handle(body: dict, no_schema: bool = False, broken_first: bool = False):
    """(durum kodu, gövde). httpx.MockTransport ve FastAPI uygulaması ortak kullanır."""
    fmt = (body.get("response_format") or {}).get("type")
    if no_schema and fmt == "json_schema":
        return 400, {"error": {"message": "response_format json_schema is not supported"}}
    messages = body.get("messages", [])
    if broken_first and not any(m["role"] == "assistant" for m in messages):
        return 200, completion("Bence güzel bir ürün ama fiyatı biraz yüksek, emin değilim.", body.get("model", ""))
    return 200, completion(json.dumps(fake_answer(messages), ensure_ascii=False), body.get("model", ""))


app = FastAPI(title="Sahte LLM (panel testi)")


@app.post("/v1/chat/completions")
async def chat(request: Request):
    code, data = handle(await request.json(), os.getenv("MOCK_LLM_NO_SCHEMA") == "1",
                        os.getenv("MOCK_LLM_BROKEN_FIRST") == "1")
    return JSONResponse(data, status_code=code)
