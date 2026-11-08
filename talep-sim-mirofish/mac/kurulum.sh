#!/usr/bin/env bash
# Bir kez çalıştırılır. Yeni klasörde .env dosyalarını hazırlar ve bağımlılıkları kurar.
# Eski klasördeki (~/MiroFish) .env dosyalarından anahtarları KOPYALAR; eski dosyalar değiştirilmez.
set -euo pipefail
source "$(dirname "$0")/ortak.sh"

echo "Yeni klasör : $REPO_KOK"
echo "Eski klasör : $ESKI_KOK (yalnızca okunur)"
echo

# --- 1) MiroFish kök .env (LLM + Zep), port 5101 ---
KOK_ENV="$REPO_KOK/.env"
if [ ! -f "$KOK_ENV" ]; then
  if [ -f "$ESKI_KOK/.env" ]; then cp "$ESKI_KOK/.env" "$KOK_ENV"; echo "✓ MiroFish .env eski klasörden kopyalandı"
  else cp "$REPO_KOK/.env.example" "$KOK_ENV"; echo "! Eski .env bulunamadı, örnekten oluşturuldu"; fi
fi
env_yaz "$KOK_ENV" FLASK_PORT "$MIROFISH_PORT"
case "$(env_oku "$KOK_ENV" LLM_API_KEY)" in ""|your_api_key_here)
  env_yaz "$KOK_ENV" LLM_API_KEY ollama
  env_yaz "$KOK_ENV" LLM_BASE_URL "$OLLAMA_URL/v1"
  env_yaz "$KOK_ENV" LLM_MODEL_NAME qwen2.5:7b-instruct ;;
esac
# MiroFish'in örnek .env'indeki boş "hızlandırma" satırları gerçek değer sanılmasın
if [ "$(env_oku "$KOK_ENV" LLM_BOOST_API_KEY)" = "your_api_key_here" ]; then
  sed -i '' -e '/^LLM_BOOST_/d' "$KOK_ENV"
fi
ZEP="$(env_oku "$KOK_ENV" ZEP_API_KEY)"
if [ -z "$ZEP" ] || [ "$ZEP" = "your_zep_api_key_here" ]; then
  echo "! ZEP_API_KEY boş. $KOK_ENV dosyasını aç, ZEP_API_KEY= satırına Zep anahtarını yaz."
fi

# --- 2) Talep API .env, motor = hybrid (MiroFish + panel), port 8100 -> MiroFish 5101 ---
API_ENV="$SIM_KOK/backend/.env"
if [ ! -f "$API_ENV" ]; then
  if [ -f "$ESKI_KOK/talep-sim/backend/.env" ]; then cp "$ESKI_KOK/talep-sim/backend/.env" "$API_ENV"; echo "✓ API .env eski klasörden kopyalandı"
  else cp "$SIM_KOK/backend/.env.example" "$API_ENV"; echo "! Eski API .env bulunamadı, örnekten oluşturuldu"; fi
fi
env_yaz "$API_ENV" SIM_ENGINE hybrid
env_yaz "$API_ENV" HYBRID_FALLBACK true
env_yaz "$API_ENV" MIROFISH_URL "http://localhost:$MIROFISH_PORT"
env_yaz "$API_ENV" CORS_ORIGINS "http://localhost:$PANEL_PORT,http://127.0.0.1:$PANEL_PORT"
if [ -z "$(env_oku "$API_ENV" VISION_API_KEY)" ]; then
  env_yaz "$API_ENV" VISION_API_KEY ollama
  env_yaz "$API_ENV" VISION_BASE_URL "$OLLAMA_URL/v1"
  env_yaz "$API_ENV" VISION_MODEL qwen2.5vl:7b
fi
echo "✓ .env dosyaları hazır (MiroFish $MIROFISH_PORT, API $API_PORT, panel $PANEL_PORT)"
echo

# --- 3) MiroFish backend bağımlılıkları (uv) ---
if ! command -v uv >/dev/null; then
  echo "uv bulunamadı, Homebrew ile kuruluyor..."; brew install uv
fi
(cd "$REPO_KOK/backend" && uv sync)
echo "✓ MiroFish backend bağımlılıkları kuruldu"

# --- 4) Talep API sanal ortamı (Python 3.11+) ---
(cd "$SIM_KOK/backend" && uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt)
echo "✓ Talep API bağımlılıkları kuruldu"

# --- 5) Dashboard (Next.js) ---
(cd "$SIM_KOK/frontend" && npm install)
echo "✓ Dashboard bağımlılıkları kuruldu"

echo
echo "KURULUM TAMAM. Şimdi üç ayrı Terminal penceresinde sırayla:"
echo "  1) $BU_KLASOR/1-mirofish.sh"
echo "  2) $BU_KLASOR/2-api.sh"
echo "  3) $BU_KLASOR/3-panel.sh"
echo "Sonra tarayıcıda: http://localhost:$PANEL_PORT"
