#!/usr/bin/env bash
# Pencere 2: Talep simülasyonu API'si (SIM_ENGINE=mirofish), port 8100
set -euo pipefail
source "$(dirname "$0")/ortak.sh"
curl -fs "http://localhost:$MIROFISH_PORT/health" >/dev/null 2>&1 \
  || echo "! Uyarı: MiroFish ($MIROFISH_PORT) henüz cevap vermiyor. Önce 1-mirofish.sh penceresini kontrol et."
portu_bosalt "$API_PORT"
cd "$SIM_KOK/backend"
echo "API başlıyor: http://localhost:$API_PORT/docs  (durdurmak için Ctrl+C)"
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT"
