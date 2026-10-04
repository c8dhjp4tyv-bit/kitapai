#!/usr/bin/env bash
# Geliştirme ortamı: API + web arayüzü birlikte.
#
#   ./scripts/dev.sh              # gerçek model (KITAPAI_ENGINE=.env'den)
#   ./scripts/dev.sh --stub       # modelsiz: boru hattını hızlıca denemek için
#   ./scripts/dev.sh --port 8077

set -euo pipefail
cd "$(dirname "$0")/.."

PORT=8000
while [[ $# -gt 0 ]]; do
  case "$1" in
    --stub) export KITAPAI_ENGINE=stub; shift ;;
    --port) PORT="$2"; shift 2 ;;
    *) echo "bilinmeyen seçenek: $1" >&2; exit 2 ;;
  esac
done

PY=".venv/bin/python"
[[ -x "$PY" ]] || PY="python3"

cleanup() {
  echo; echo "kapatılıyor…"
  kill 0 2>/dev/null || true
}
trap cleanup EXIT INT TERM

"$PY" -m kitapai.cli serve --port "$PORT" &
sleep 3

VITE_API_URL="http://localhost:${PORT}" npm run dev --prefix clients/web &

wait
