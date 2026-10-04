#!/usr/bin/env bash
# kitap.ai iOS uygulamasını Linux'ta derler (Xcode/macOS gerekmez).
#
#   ./build.sh                                   # derle + paketle + imzala + .ipa
#   ./build.sh --api https://pc.tailnet.ts.net   # varsayılan sunucu adresini göm
#   ./build.sh --allow-http                      # düz HTTP'ye (Tailscale IP) izin ver
#   ./build.sh --stage bundle                    # sadece belirli adıma kadar
#
# Gereksinimler: https://github.com/c8dhjp4tyv-bit/iosbuild
#   - iosbuild PATH'te veya IOSBUILD_HOME ayarlı
#   - `iosbuild sdk import` ile bir iPhoneOS SDK kayıtlı
#   - swiftc (iOS hedefli, augmented toolchain) ve ldid

set -euo pipefail
cd "$(dirname "$0")"

API_URL=""
ALLOW_HTTP=0
STAGE="ipa"
VERSION="2.0.0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --api)        API_URL="$2"; shift 2 ;;
    --allow-http) ALLOW_HTTP=1; shift ;;
    --stage)      STAGE="$2"; shift 2 ;;
    --version)    VERSION="$2"; shift 2 ;;
    -h|--help)    sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "bilinmeyen seçenek: $1" >&2; exit 2 ;;
  esac
done

# iosbuild'i bul: PATH, IOSBUILD_HOME/.venv, ~/iosbuild/.venv
if command -v iosbuild >/dev/null 2>&1; then
  IOSBUILD="$(command -v iosbuild)"
elif [[ -n "${IOSBUILD_HOME:-}" && -x "$IOSBUILD_HOME/.venv/bin/iosbuild" ]]; then
  IOSBUILD="$IOSBUILD_HOME/.venv/bin/iosbuild"
elif [[ -x "$HOME/iosbuild/.venv/bin/iosbuild" ]]; then
  IOSBUILD="$HOME/iosbuild/.venv/bin/iosbuild"
else
  echo "hata: iosbuild bulunamadı." >&2
  echo "  git clone https://github.com/c8dhjp4tyv-bit/iosbuild && cd iosbuild && ./bootstrap.sh" >&2
  exit 1
fi
echo "iosbuild: $IOSBUILD"

run_stage() {
  echo "── $1 ──"
  "$IOSBUILD" -C . "$1"
}

run_stage build
[[ "$STAGE" == "build" ]] && exit 0

run_stage bundle
# iosbuild sabit bir Info.plist yazar; uygulama adını, sürümü ve ağ ayarlarını
# imzalamadan ÖNCE burada ekliyoruz.
PATCH_ARGS=(build/KitapAI.app --version "$VERSION" --display-name "kitap.ai")
[[ -n "$API_URL" ]] && PATCH_ARGS+=(--api "$API_URL")
[[ "$ALLOW_HTTP" == "1" ]] && PATCH_ARGS+=(--allow-http)
python3 scripts/patch_plist.py "${PATCH_ARGS[@]}"
[[ "$STAGE" == "bundle" ]] && exit 0

run_stage sign
[[ "$STAGE" == "sign" ]] && exit 0

run_stage ipa
echo
echo "hazır:"
ls -lh build/*.ipa 2>/dev/null || echo "  (ipa üretilmedi)"
