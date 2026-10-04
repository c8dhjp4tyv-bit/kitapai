#!/usr/bin/env bash
# v3: Gemini ile damıtılmış gerekçelerle eğitim. GPU çakışmasın diye v2 hattı VE damıtma bitince başlar.
cd "/home/umutcagand/Masaüstü/kitapai" || exit 1
export HF_HUB_OFFLINE=1 KITAPAI_LOG_LEVEL=INFO KITAPAI_ENGINE=transformers
step() { echo "[$(date +%H:%M:%S)] $1" >> runs/pipeline-v3.steps; }
rm -f runs/pipeline-v3.done runs/pipeline-v3.fail runs/pipeline-v3.steps
step "bekliyor: v2 hattı + damıtma"
until { [ -e runs/pipeline-v2.done ] || [ -e runs/pipeline-v2.fail ]; } && { [ -e runs/distill.done ] || [ -e runs/distill.fail ]; }; do sleep 60; done
if [ -e runs/pipeline-v2.fail ] || [ -e runs/distill.fail ]; then step "ÖN KOŞUL HATA (v2 ya da damıtma)"; touch runs/pipeline-v3.fail; exit 1; fi
n=$(wc -l < data/dataset/distilled.jsonl); step "damitilmis ornek: $n"
[ "$n" -ge 3000 ] || { step "yetersiz damitilmis veri"; touch runs/pipeline-v3.fail; exit 1; }
step "egitim basladi"
.venv/bin/kitapai train -c configs/train-3b-8gb-v3.yaml > runs/train-3b-v3.log 2>&1 || { step "egitim HATA"; touch runs/pipeline-v3.fail; exit 1; }
step "egitim bitti"
KITAPAI_ADAPTER_PATH=models/kitapai-lora-v3 .venv/bin/kitapai eval --samples 100 --out runs/eval-v3.json > runs/eval-v3.log 2>&1 || step "eval v3 HATA"
step "eval v3 bitti"
touch runs/pipeline-v3.done
