#!/usr/bin/env bash
# Gemini gerektiren kitapai komutları: anahtarı çalışma anında ~/.zshrc den okur.
# Kullanım: runs/gemini.sh judge ... | runs/gemini.sh dataset relabel ...
set -euo pipefail
cd "$(dirname "$0")/.."
KEY="$(python3 - <<'PY' | tail -1
import re, pathlib
for ln in (pathlib.Path.home() / ".zshrc").read_text(errors="replace").splitlines():
    m = re.match(r"^\s*(?:export\s+)?GCLOUD_API_KEY=(.*)$", ln)
    if m:
        print(m.group(1).strip().strip("'\""))
PY
)"
[ -n "$KEY" ] || { echo "GCLOUD_API_KEY ~/.zshrc'de bulunamadı" >&2; exit 1; }
export GCLOUD_API_KEY="$KEY"
exec .venv/bin/kitapai "$@"
