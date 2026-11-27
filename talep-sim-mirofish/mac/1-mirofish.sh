#!/usr/bin/env bash
# Pencere 1: MiroFish ajan sürüsü backend'i, port 5101
set -euo pipefail
source "$(dirname "$0")/ortak.sh"
curl -fs "$OLLAMA_URL/api/version" >/dev/null || { echo "! Ollama çalışmıyor. Ollama uygulamasını aç (veya: ollama serve) ve tekrar dene."; exit 1; }
if curl -fs -m 3 "http://127.0.0.1:$MIROFISH_PORT/health" >/dev/null 2>&1; then
  echo "MiroFish zaten başka bir pencerede çalışıyor (port $MIROFISH_PORT). O pencereyi KAPATMA."
  echo "Bu pencereyi 2-api.sh veya 3-panel.sh için kullanabilirsin."
  exit 0
fi
portu_bosalt "$MIROFISH_PORT"
echo "ÖNEMLİ: Bu pencere MiroFish'e ait. Açık kalmalı; başka komutu YENİ bir pencerede (Cmd+T) çalıştır."
cd "$REPO_KOK/backend"
echo "MiroFish başlıyor: http://localhost:$MIROFISH_PORT  (durdurmak için Ctrl+C)"
FLASK_PORT="$MIROFISH_PORT" exec uv run python run.py
