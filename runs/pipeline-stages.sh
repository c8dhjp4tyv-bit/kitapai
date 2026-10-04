#!/usr/bin/env bash
# SEÇ ve YAZ modellerini sırayla eğitir (GPU tek işe ait olsun diye ardışık).
cd "/home/umutcagand/Masaüstü/kitapai" || exit 1
export HF_HUB_OFFLINE=1 KITAPAI_LOG_LEVEL=INFO
step() { echo "[$(date +%H:%M:%S)] $1" >> runs/pipeline-stages.steps; }
rm -f runs/pipeline-stages.done runs/pipeline-stages.fail runs/pipeline-stages.steps
step "secici egitimi basladi"
.venv/bin/kitapai train -c configs/train-select.yaml > runs/train-select.log 2>&1 || { step "secici HATA"; touch runs/pipeline-stages.fail; exit 1; }
step "secici egitimi bitti"
.venv/bin/kitapai train -c configs/train-write.yaml > runs/train-write.log 2>&1 || { step "yazici HATA"; touch runs/pipeline-stages.fail; exit 1; }
step "yazici egitimi bitti"
touch runs/pipeline-stages.done
