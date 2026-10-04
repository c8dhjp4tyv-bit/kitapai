#!/usr/bin/env bash
# v1 (zaten çalışan 200 örneklik koşu) bitince v2 ve v3'ü 100 örnekle ölçer; hakem sonra puanlar.
cd "/home/umutcagand/Masaüstü/kitapai" || exit 1
export HF_HUB_OFFLINE=1 KITAPAI_LOG_LEVEL=INFO
while kill -0 1313445 2>/dev/null; do sleep 10; done
echo "lora bitti $(date +%H:%M:%S)" >> runs/eval-legacy.steps
for v in lora-v2 lora-v3; do
  KITAPAI_ADAPTER_PATH=models/kitapai-$v .venv/bin/kitapai eval --mode legacy -n 100 --batch 8 \
    --record runs/picks-$v.jsonl --out runs/eval100-$v.json > runs/eval100-$v.log 2>&1 \
    || { echo "$v HATA" >> runs/eval-legacy.steps; touch runs/eval-legacy.fail; exit 1; }
  echo "$v bitti $(date +%H:%M:%S)" >> runs/eval-legacy.steps
done
touch runs/eval-legacy.done
