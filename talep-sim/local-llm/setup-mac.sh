#!/usr/bin/env bash
# macOS (Apple Silicon): Ollama'yı Docker olmadan kurar, RAM'e göre Qwen modellerini çeker.
# Kullanım: ./setup-mac.sh            (RAM'i otomatik algılar)
#           RAM_GB=16 ./setup-mac.sh  (elle seç: 8 veya 16)
# Model etiketleri Ollama kütüphanesinde değişebilir: https://ollama.com/library
set -euo pipefail

RAM_GB=${RAM_GB:-$(( $(sysctl -n hw.memsize) / 1024 / 1024 / 1024 ))}
if   [ "$RAM_GB" -ge 24 ]; then TEXT_MODEL=${TEXT_MODEL:-qwen2.5:14b-instruct}; VISION_MODEL=${VISION_MODEL:-qwen2.5vl:7b}
elif [ "$RAM_GB" -ge 12 ]; then TEXT_MODEL=${TEXT_MODEL:-qwen2.5:7b-instruct};  VISION_MODEL=${VISION_MODEL:-qwen2.5vl:7b}
else                            TEXT_MODEL=${TEXT_MODEL:-qwen2.5:3b-instruct};  VISION_MODEL=${VISION_MODEL:-qwen2.5vl:3b}
fi
echo "RAM: ${RAM_GB} GB -> metin: $TEXT_MODEL, görsel: $VISION_MODEL"

command -v brew >/dev/null || { echo "Homebrew yok: https://brew.sh adresinden kur, sonra tekrar çalıştır."; exit 1; }
command -v ollama >/dev/null || brew install ollama

# Ajan promptları uzun; varsayılan bağlam kısa kalırsa kesilir.
export OLLAMA_CONTEXT_LENGTH=${OLLAMA_CONTEXT_LENGTH:-8192}
if ! curl -fs http://localhost:11434/api/version >/dev/null; then
  echo "Ollama başlatılıyor (arka planda)..."
  nohup ollama serve >/tmp/ollama.log 2>&1 &
  for _ in $(seq 1 30); do curl -fs http://localhost:11434/api/version >/dev/null && break; sleep 1; done
fi

ollama pull "$TEXT_MODEL"
ollama pull "$VISION_MODEL"

echo; echo "Hızlı test:"
ollama run "$TEXT_MODEL" 'Sadece {"ok": true} JSON döndür.' || true

cat <<MSG

--- Bu satırları .env dosyalarına yaz ---
MiroFish kökündeki .env:
  LLM_BASE_URL=http://localhost:11434/v1
  LLM_API_KEY=ollama
  LLM_MODEL_NAME=$TEXT_MODEL
talep-sim/backend/.env:
  SIM_ENGINE=mirofish
  VISION_BASE_URL=http://localhost:11434/v1
  VISION_API_KEY=ollama
  VISION_MODEL=$VISION_MODEL
MSG
