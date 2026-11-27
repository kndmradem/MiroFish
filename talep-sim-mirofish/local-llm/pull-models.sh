#!/usr/bin/env bash
# Kullanım: ./pull-models.sh            (docker compose ile çalışan ollama)
#           OLLAMA="ollama" ./pull-models.sh   (doğrudan kurulu ollama)
# Etiketler Ollama kütüphanesinde değişebilir; hata alırsan https://ollama.com/library adresinden kontrol et.
set -euo pipefail
OLLAMA=${OLLAMA:-"docker compose exec ollama ollama"}
TEXT_MODEL=${TEXT_MODEL:-qwen2.5:14b-instruct}   # MiroFish: persona + ajan cevapları (~9 GB, 4-bit)
VISION_MODEL=${VISION_MODEL:-qwen2.5vl:7b}       # görsel + metin füzyonu (~6 GB)
$OLLAMA pull "$TEXT_MODEL"
$OLLAMA pull "$VISION_MODEL"
cat <<MSG

MiroFish .env:
  LLM_BASE_URL=http://localhost:11434/v1
  LLM_API_KEY=ollama
  LLM_MODEL_NAME=$TEXT_MODEL
talep-sim/backend/.env:
  VISION_BASE_URL=http://localhost:11434/v1
  VISION_API_KEY=ollama
  VISION_MODEL=$VISION_MODEL
MSG
