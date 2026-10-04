#!/usr/bin/env bash
# Gemini ile gerekçe damıtma — sır bu dosyada YOK, anahtar çalışma anında ~/.zshrc'den okunur.
cd "/home/umutcagand/Masaüstü/kitapai" || exit 1
rm -f runs/distill.done runs/distill.fail
KEY="$(python3 - <<'PY' | tail -1
import re, pathlib
for ln in (pathlib.Path.home() / ".zshrc").read_text(errors="replace").splitlines():
    m = re.match(r"^\s*(?:export\s+)?GCLOUD_API_KEY=(.*)$", ln)
    if m:
        print(m.group(1).strip().strip("'\""))
PY
)"
[ -n "$KEY" ] || { echo "GCLOUD_API_KEY ~/.zshrc'de bulunamadı" >&2; touch runs/distill.fail; exit 1; }
export GCLOUD_API_KEY="$KEY" KITAPAI_LOG_LEVEL=INFO
.venv/bin/kitapai dataset distill --n 12000 --workers 16 > runs/distill.log 2>&1 \
  && touch runs/distill.done || touch runs/distill.fail
