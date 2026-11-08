#!/usr/bin/env bash
# Pencere 1: MiroFish ajan sürüsü backend'i, port 5101
set -euo pipefail
source "$(dirname "$0")/ortak.sh"
curl -fs "$OLLAMA_URL/api/version" >/dev/null || { echo "! Ollama çalışmıyor. Ollama uygulamasını aç (veya: ollama serve) ve tekrar dene."; exit 1; }
portu_bosalt "$MIROFISH_PORT"
cd "$REPO_KOK/backend"
echo "MiroFish başlıyor: http://localhost:$MIROFISH_PORT  (durdurmak için Ctrl+C)"
FLASK_PORT="$MIROFISH_PORT" exec uv run python run.py
