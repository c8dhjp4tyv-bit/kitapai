#!/usr/bin/env bash
# GPU boşalınca (eski modellerin ölçümü bitince) SEÇ+YAZ eğitimini başlatır.
cd "/home/umutcagand/Masaüstü/kitapai" || exit 1
while [ ! -e runs/eval-legacy.done ] && [ ! -e runs/eval-legacy.fail ]; do sleep 20; done
exec runs/pipeline-stages.sh
