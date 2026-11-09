#!/usr/bin/env bash
# Hangi servis ayakta? (yeni kurulum + eski kurulumun portları yalnızca bilgi için)
source "$(dirname "$0")/ortak.sh"
kontrol() { if curl -fs -m 3 "$2" >/dev/null 2>&1; then echo "  ✓ $1"; else echo "  ✗ $1  (kapalı)"; fi; }
echo "Yeni kurulum (karma motor: MiroFish + persona paneli):"
kontrol "Ollama            $OLLAMA_URL" "$OLLAMA_URL/api/version"
kontrol "MiroFish          :$MIROFISH_PORT" "http://127.0.0.1:$MIROFISH_PORT/health"
kontrol "Talep API         :$API_PORT" "http://localhost:$API_PORT/health"
kontrol "Dashboard         :$PANEL_PORT" "http://localhost:$PANEL_PORT"
curl -fs -m 3 "http://localhost:$API_PORT/health" 2>/dev/null && echo
echo "Eski kurulum (dokunulmadı, sadece bilgi): 5001 / 8000 / 3100"
for p in 5001 8000 3100; do lsof -ti tcp:$p -sTCP:LISTEN >/dev/null 2>&1 && echo "  • $p açık" || echo "  • $p kapalı"; done
