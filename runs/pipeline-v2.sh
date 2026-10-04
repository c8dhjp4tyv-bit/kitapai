#!/usr/bin/env bash
# v2: yalnızca etiket düzeltmesi (şablon gerekçeler). Sıra: eğit → v2'yi ölç → v1'i AYNI doğrulama kümesinde ölç.
cd "/home/umutcagand/Masaüstü/kitapai" || exit 1
export HF_HUB_OFFLINE=1 KITAPAI_LOG_LEVEL=INFO KITAPAI_ENGINE=transformers
rm -f runs/pipeline-v2.done runs/pipeline-v2.fail
step() { echo "[$(date +%H:%M:%S)] $1" >> runs/pipeline-v2.steps; }
step "egitim basladi"
.venv/bin/kitapai train -c configs/train-3b-8gb-v2.yaml > runs/train-3b-v2.log 2>&1 || { step "egitim HATA"; touch runs/pipeline-v2.fail; exit 1; }
step "egitim bitti"
KITAPAI_ADAPTER_PATH=models/kitapai-lora-v2 .venv/bin/kitapai eval --samples 100 --out runs/eval-v2.json > runs/eval-v2.log 2>&1 || step "eval v2 HATA"
step "eval v2 bitti"
KITAPAI_ADAPTER_PATH=models/kitapai-lora .venv/bin/kitapai eval --samples 100 --out runs/eval-v1-yenikume.json > runs/eval-v1-yenikume.log 2>&1 || step "eval v1 HATA"
step "eval v1 bitti"
touch runs/pipeline-v2.done
