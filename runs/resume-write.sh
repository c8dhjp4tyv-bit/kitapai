#!/usr/bin/env bash
# Disk dolduğu için çöken yazıcı eğitimini son sağlam kontrol noktasından sürdürür.
cd "/home/umutcagand/Masaüstü/kitapai" || exit 1
export HF_HUB_OFFLINE=1 KITAPAI_LOG_LEVEL=INFO
rm -f runs/pipeline-stages.fail runs/pipeline-stages.done
echo "[$(date +%H:%M:%S)] yazici devam (checkpoint-200)" >> runs/pipeline-stages.steps
.venv/bin/kitapai train -c configs/train-write.yaml --resume >> runs/train-write.log 2>&1 \
  || { echo "[$(date +%H:%M:%S)] yazici HATA" >> runs/pipeline-stages.steps; touch runs/pipeline-stages.fail; exit 1; }
echo "[$(date +%H:%M:%S)] yazici egitimi bitti" >> runs/pipeline-stages.steps
touch runs/pipeline-stages.done
