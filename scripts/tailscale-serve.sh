#!/usr/bin/env bash
# kitap.ai API'sini tailnet üzerinde HTTPS olarak yayınlar.
#
# Neden gerekli: iOS, App Transport Security nedeniyle düz HTTP'yi engeller.
# `tailscale serve` MagicDNS adına gerçek bir Let's Encrypt sertifikası
# bağladığı için uygulamada hiçbir istisna tanımlamaya gerek kalmaz.
#
#   ./scripts/tailscale-serve.sh          # varsayılan port 8000
#   ./scripts/tailscale-serve.sh 8077
#   ./scripts/tailscale-serve.sh --off    # yayını kapat

set -euo pipefail

PORT="${1:-8000}"

if ! command -v tailscale >/dev/null 2>&1; then
  echo "hata: tailscale kurulu değil (https://tailscale.com/download)" >&2
  exit 1
fi

if [[ "$PORT" == "--off" ]]; then
  tailscale serve --https=443 off
  echo "yayın kapatıldı"
  exit 0
fi

# MagicDNS ve HTTPS sertifikaları tailnet ayarlarından açık olmalı.
if ! tailscale status >/dev/null 2>&1; then
  echo "hata: tailscale bağlı değil — `tailscale up` çalıştırın" >&2
  exit 1
fi

echo "yerel :$PORT → tailnet HTTPS"
tailscale serve --bg --https=443 "http://127.0.0.1:${PORT}"
tailscale serve status

cat <<'NOTE'

Telefonda kullanmak için:
  iOS   → uygulamada "sunucu" düğmesine dokun, yukarıdaki https:// adresini gir
  Web   → tarayıcıda https://<makine>.<tailnet>.ts.net
  Android → aynı adres (düz HTTP de çalışır)

Kapatmak için: ./scripts/tailscale-serve.sh --off
NOTE
