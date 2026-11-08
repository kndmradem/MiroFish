#!/usr/bin/env bash
# Pencere 3: Dashboard, port 3200 (API 8100'e bağlanır)
set -euo pipefail
source "$(dirname "$0")/ortak.sh"
portu_bosalt "$PANEL_PORT"
cd "$SIM_KOK/frontend"
echo "Dashboard başlıyor: http://localhost:$PANEL_PORT  (durdurmak için Ctrl+C)"
NEXT_PUBLIC_API_URL="http://localhost:$API_PORT" exec npx next dev -p "$PANEL_PORT"
