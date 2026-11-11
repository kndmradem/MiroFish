#!/usr/bin/env python3
"""Ollama'nın OpenAI uyumlu uç noktasını teşhis eder (yalnızca standart kütüphane).

Kullanım: python3 check-ollama.py [görsel_yolu]
  LLM_MODEL_NAME ve VISION_MODEL ortam değişkenleri yoksa qwen2.5:7b-instruct / qwen2.5vl:7b denenir.
Üç test yapar: metin, metin + JSON modu, (görsel verildiyse) görsel. Her birinin HTTP durumunu ve
sunucunun cevap gövdesini yazar; 400'ün gerçek nedeni orada görünür.
"""
import base64
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request

BASE = os.getenv("OLLAMA_URL", "http://localhost:11434/v1")
TEXT_MODEL = os.getenv("LLM_MODEL_NAME", "qwen2.5:7b-instruct")
VISION_MODEL = os.getenv("VISION_MODEL", "qwen2.5vl:7b")


def call(title, payload):
    req = urllib.request.Request(f"{BASE}/chat/completions", json.dumps(payload).encode(),
                                 {"Content-Type": "application/json", "Authorization": "Bearer ollama"})
    print(f"\n== {title} (model: {payload['model']})")
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            body = json.loads(r.read())
            print("HTTP", r.status, "->", body["choices"][0]["message"]["content"][:200].replace("\n", " "))
    except urllib.error.HTTPError as e:
        print("HTTP", e.code, "->", e.read().decode()[:600])
    except Exception as e:  # bağlantı, zaman aşımı vb.
        print("HATA:", type(e).__name__, e)


msg = [{"role": "user", "content": "Sadece {\"ok\": true} JSON'unu döndür."}]
call("1) düz metin", {"model": TEXT_MODEL, "messages": msg})
call("2) JSON modu", {"model": TEXT_MODEL, "messages": msg, "response_format": {"type": "json_object"}})

if len(sys.argv) > 1:
    path = sys.argv[1]
    mime = mimetypes.guess_type(path)[0] or "image/jpeg"
    data = base64.b64encode(open(path, "rb").read()).decode()
    print(f"\nGörsel: {path} ({os.path.getsize(path) // 1024} KB, {mime})")
    call("3) görsel", {"model": VISION_MODEL, "messages": [{"role": "user", "content": [
        {"type": "text", "text": "Bu görseldeki ürün nedir? Tek cümle."},
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}}]}]})
