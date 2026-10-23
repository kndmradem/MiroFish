"""Görsel + teknik metin füzyonu (teknik doküman §3.1).

OpenAI uyumlu herhangi bir vision modeline (Qwen-VL, GPT-4o, Claude'un
OpenAI uyumlu uç noktası) görseli ve metni gönderip standart bir ürün kartı
alır. Kart, mock motorun kullandığı `features` sözlüğünü de içerir; böylece
iki motor aynı kartla çalışabilir.
"""
from typing import Optional

import httpx

from ..models import PredictionRequest
from .llm import extract_json
from .personas import VISION_PROMPT

FEATURE_KEYS = ["warmth", "waterproof", "sheen", "eco", "synthetic", "premium", "oversize", "heavy"]

_SCHEMA_HINT = (
    "Sadece JSON dön, açıklama yazma. Şema:\n"
    '{"fabric_texture": str, "composition": str, "gsm": int|null, '
    '"climate_fit": "sıcak"|"ılıman"|"soğuk", "style_category": str, '
    '"visual_description": str, "features": {'
    + ", ".join(f'"{k}": bool' for k in FEATURE_KEYS)
    + "}}\n"
    "features anlamları: warmth=ısı tutar, waterproof=su/rüzgar geçirmez, sheen=parlak/gösterişli yüzey, "
    "eco=sürdürülebilir/geri dönüştürülmüş, synthetic=belirgin sentetik oranı, premium=lüks algısı, "
    "oversize=bol kesim, heavy=ağır/kalın kumaş."
)


def _image_mime(b64: str) -> str:
    if b64.startswith("/9j/"):
        return "image/jpeg"
    if b64.startswith("UklGR"):
        return "image/webp"
    return "image/png"


class VisionFusion:
    def __init__(self, api_key: str, base_url: str, model: str, client: Optional[httpx.AsyncClient] = None):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.client = client or httpx.AsyncClient(timeout=90)

    async def fuse_product_card(self, req: PredictionRequest) -> dict:
        content = [{"type": "text", "text": (
            f"{VISION_PROMPT}\n\nÜrün adı: {req.product_name}\nTeknik metin: {req.technical_specs}\n\n{_SCHEMA_HINT}"
        )}]
        if req.image_base64:
            content.append({"type": "image_url", "image_url": {
                "url": f"data:{_image_mime(req.image_base64)};base64,{req.image_base64}"}})

        resp = await self.client.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "temperature": 0.2,
                  "messages": [{"role": "user", "content": content}]},
        )
        resp.raise_for_status()
        card = extract_json(resp.json()["choices"][0]["message"]["content"])
        features = card.get("features") or {}
        card["features"] = {k: bool(features.get(k, False)) for k in FEATURE_KEYS}
        card["product_name"] = req.product_name
        card["has_image"] = bool(req.image_base64)
        card["source"] = f"vision:{self.model}"
        return card
