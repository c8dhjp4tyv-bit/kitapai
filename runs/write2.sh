#!/usr/bin/env bash
# Satır biçimli yazıcıyı eğitir, ölçer ve hakemle puanlar.
cd "/home/umutcagand/Masaüstü/kitapai" || exit 1
export HF_HUB_OFFLINE=1 KITAPAI_LOG_LEVEL=INFO
rm -f runs/write2.done runs/write2.fail
.venv/bin/kitapai train -c configs/train-write.yaml > runs/train-write2.log 2>&1 || { touch runs/write2.fail; exit 1; }
KITAPAI_WRITE_ADAPTER_PATH=models/kitapai-write2 .venv/bin/kitapai eval --mode write -n 100 --batch 4 \
  --record runs/writes-v2.jsonl --out runs/eval100-write2.json > runs/eval100-write2.log 2>&1 || { touch runs/write2.fail; exit 1; }
runs/gemini.sh judge-write yazici-v2=runs/writes-v2.jsonl -n 100 > runs/judge-write2.log 2>&1 || { touch runs/write2.fail; exit 1; }
touch runs/write2.done
