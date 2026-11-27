# Ortak ayarlar: bütün mac/*.sh betikleri bunu okur. Eski kurulumun portlarına (5001, 8000, 3100) dokunulmaz.
MIROFISH_PORT=5101
API_PORT=8100
PANEL_PORT=3200
OLLAMA_URL=http://localhost:11434

BU_KLASOR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM_KOK="$(cd "$BU_KLASOR/.." && pwd)"          # .../talep-sim-mirofish
REPO_KOK="$(cd "$SIM_KOK/.." && pwd)"           # yeni klasör, ör. ~/MiroFish-v2
ESKI_KOK="${ESKI_KOK:-$HOME/MiroFish}"          # eski kurulum: yalnızca .env'leri OKUNUR, değiştirilmez

if [ "$REPO_KOK" = "$ESKI_KOK" ]; then
  echo "DUR: Bu betikler eski klasörde ($ESKI_KOK) çalıştırılmamalı. Yeni klasörü kullan (ör. ~/MiroFish-v2)."
  exit 1
fi

# Yalnızca VERİLEN porttaki süreci kapatır (eski portlara dokunmaz)
portu_bosalt() {
  local p="$1" pids
  pids="$(lsof -ti tcp:"$p" -sTCP:LISTEN 2>/dev/null || true)"
  if [ -n "$pids" ]; then
    echo "Port $p dolu, eski süreç kapatılıyor: $pids"
    kill $pids 2>/dev/null || true
    sleep 1
  fi
}

# .env içinde ANAHTAR=değer yazar (varsa değiştirir, yoksa ekler)
env_yaz() {
  local dosya="$1" anahtar="$2" deger="$3"
  touch "$dosya"
  if grep -qE "^${anahtar}=" "$dosya"; then
    sed -i '' -e "s|^${anahtar}=.*|${anahtar}=${deger}|" "$dosya"
  else
    printf '%s=%s\n' "$anahtar" "$deger" >> "$dosya"
  fi
}

env_oku() {  # dosyadaki değer (yoksa boş)
  grep -E "^$2=" "$1" 2>/dev/null | tail -1 | cut -d= -f2- | sed -e 's/[[:space:]]*#.*$//' -e 's/^"//' -e 's/"$//'
}
