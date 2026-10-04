#!/usr/bin/env bash
# Eğitim bitince: seçici + yazıcı ölçümü, ardından hakem puanı (tüm modeller aynı örneklerde).
cd "/home/umutcagand/Masaüstü/kitapai" || exit 1
export HF_HUB_OFFLINE=1 KITAPAI_LOG_LEVEL=INFO
rm -f runs/post-train.done runs/post-train.fail
while [ ! -e runs/pipeline-stages.done ] && [ ! -e runs/pipeline-stages.fail ]; do sleep 30; done
[ -e runs/pipeline-stages.fail ] && { touch runs/post-train.fail; exit 1; }
.venv/bin/kitapai eval --mode select -n 200 --batch 8 --record runs/picks-select.jsonl \
  --out runs/eval200-select.json > runs/eval200-select.log 2>&1 || { touch runs/post-train.fail; exit 1; }
.venv/bin/kitapai eval --mode write -n 100 --batch 4 --out runs/eval100-write.json \
  > runs/eval100-write.log 2>&1 || true
runs/gemini.sh judge select=runs/picks-select.jsonl v1=runs/picks-lora.jsonl \
  v2=runs/picks-lora-v2.jsonl v3=runs/picks-lora-v3.jsonl -n 200 \
  --out runs/judge-final.json > runs/judge-final.log 2>&1 || { touch runs/post-train.fail; exit 1; }
touch runs/post-train.done
