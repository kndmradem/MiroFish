import base64
import io
import json

import httpx
import pytest
from PIL import Image

from app.models import PredictionRequest
from app.services.llm import LLMClient, LLMError
from app.services.vision import VisionFusion, prepare_image

REQ = PredictionRequest(product_name="Kaban", image_base64="", technical_specs="yün", unit_cost="25",
                        total_production_budget=1000, target_regions=["EU"])


def png_b64(size=(3000, 2000), mode="RGBA") -> str:
    buf = io.BytesIO()
    Image.new(mode, size, (200, 30, 30, 128) if mode == "RGBA" else (200, 30, 30)).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def test_prepare_image_converts_to_small_jpeg():
    mime, data = prepare_image(png_b64())
    img = Image.open(io.BytesIO(base64.b64decode(data)))
    assert mime == "image/jpeg" and img.format == "JPEG" and max(img.size) == 1280


def test_prepare_image_strips_data_url_prefix():
    mime, data = prepare_image("data:image/png;base64," + png_b64((50, 50)))
    assert mime == "image/jpeg" and Image.open(io.BytesIO(base64.b64decode(data))).size == (50, 50)


def test_prepare_image_returns_original_when_undecodable():
    mime, data = prepare_image("bozukveri")
    assert data == "bozukveri"


def client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_vision_error_shows_server_body():
    def handler(request):
        return httpx.Response(400, json={"error": {"message": "model does not support images"}})

    fusion = VisionFusion("k", "http://ollama/v1", "qwen2.5vl:7b", client(handler))
    with pytest.raises(LLMError) as e:
        await fusion.fuse_product_card(REQ.model_copy(update={"image_base64": png_b64((40, 40))}))
    assert "model does not support images" in str(e.value) and "qwen2.5vl:7b" in str(e.value)


async def test_vision_sends_small_jpeg_data_url():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        card = {"fabric_texture": "yün", "features": {"warmth": True}}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(card)}}]})

    await VisionFusion("k", "http://x/v1", "m", client(handler)).fuse_product_card(
        REQ.model_copy(update={"image_base64": png_b64()}))
    url = seen["messages"][0]["content"][1]["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,") and len(url) < 200_000


async def test_llm_client_error_has_body_and_does_not_retry_4xx():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(400, text='{"error":"response_format not supported"}')

    llm = LLMClient("k", "http://ollama/v1", "m", client(handler))
    with pytest.raises(LLMError) as e:
        await llm.chat_json("s", "p")
    assert "response_format not supported" in str(e.value) and len(calls) == 1
