#!/usr/bin/env bash
# Büyük dosyaları (veri, modeller, IPA) GitHub Release eki olarak yükler.
# Her parça paketlenir → yüklenir → yerelden silinir (diskte yer dar).
# Sonunda depoyu herkese açar.
set -uo pipefail
cd "/home/umutcagand/Masaüstü/kitapai" || exit 1
REPO=c8dhjp4tyv-bit/kitapai
TAG=v2.0-artifacts
STAGE=/home/umutcagand/kitapai-stage
LOG=runs/publish-assets.log
rm -rf "$STAGE" "$LOG"; mkdir -p "$STAGE"
log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

gh release view "$TAG" --repo "$REPO" >/dev/null 2>&1 || gh release create "$TAG" --repo "$REPO" \
  --title "Veri ve model dosyaları (v2.0)" --notes-file runs/RELEASE_NOTES.md >> "$LOG" 2>&1

up() {  # up <dosya>
  local f="$1" try
  for try in 1 2 3 4 5; do
    gh release upload "$TAG" "$f" --repo "$REPO" --clobber >> "$LOG" 2>&1 && { log "yüklendi: $(basename "$f")"; return 0; }
    log "yükleme başarısız ($try/5): $(basename "$f")"; sleep 20
  done
  return 1
}
pack_dir() {  # pack_dir <ad> <dizin>  (zstd; sıkışmayan dosyalar için düşük seviye)
  local name="$1" dir="$2"
  tar -C "$(dirname "$dir")" -cf - "$(basename "$dir")" | zstd -T0 -3 -q -o "$STAGE/$name.tar.zst"
}

FAIL=0
for m in kitapai-select kitapai-write kitapai-lora kitapai-lora-v2 kitapai-lora-v3; do
  log "paketleniyor: $m"; pack_dir "$m" "models/$m"
  ( cd "$STAGE" && sha256sum "$m.tar.zst" >> SHA256SUMS.txt )
  up "$STAGE/$m.tar.zst" || FAIL=1; rm -f "$STAGE/$m.tar.zst"
done
for d in dataset dataset_eski vectors; do
  log "paketleniyor: data-$d"; pack_dir "data-$d" "data/$d"
  ( cd "$STAGE" && sha256sum "data-$d.tar.zst" >> SHA256SUMS.txt )
  up "$STAGE/data-$d.tar.zst" || FAIL=1; rm -f "$STAGE/data-$d.tar.zst"
done
log "paketleniyor: open-library dump'ları"; pack_dir data-dumps data/dumps
( cd "$STAGE" && sha256sum data-dumps.tar.zst >> SHA256SUMS.txt )
up "$STAGE/data-dumps.tar.zst" || FAIL=1; rm -f "$STAGE/data-dumps.tar.zst"

log "katalog bölünüyor (2 GB sınırı)"
split -b 1200M -d data/catalog.duckdb "$STAGE/catalog.duckdb.part"
( cd "$STAGE" && sha256sum catalog.duckdb.part* >> SHA256SUMS.txt )
for p in "$STAGE"/catalog.duckdb.part*; do up "$p" || FAIL=1; rm -f "$p"; done
cp clients/ios/build/KitapAI.ipa "$STAGE/KitapAI.ipa"; ( cd "$STAGE" && sha256sum KitapAI.ipa >> SHA256SUMS.txt )
up "$STAGE/KitapAI.ipa" || FAIL=1
up "$STAGE/SHA256SUMS.txt" || FAIL=1
if [ "$FAIL" = 0 ]; then
  log "tüm dosyalar yüklendi; depo herkese açılıyor"
  gh repo edit "$REPO" --visibility public --accept-visibility-change-consequences >> "$LOG" 2>&1 && log "DEPO PUBLIC" || log "public yapılamadı"
  touch runs/publish-assets.done
else
  log "BAZI YÜKLEMELER BAŞARISIZ — depo özel bırakıldı"; touch runs/publish-assets.fail
fi
