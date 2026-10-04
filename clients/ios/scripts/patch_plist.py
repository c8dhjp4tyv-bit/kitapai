#!/usr/bin/env python3
"""`iosbuild bundle` sonrası Info.plist'i tamamlar.

`iosbuild` sabit bir Info.plist üretir (bkz. src/iosbuild/commands/bundle.py) ve
manifest'te özel anahtar kabul etmez. Uygulama adı, sürüm, ekran yönü ve ağ
ayarları burada eklenir. İmzalama bundle'dan *sonra* çalıştığı için bu yama
CodeDirectory karmalarını bozmaz — sıralama: build → bundle → patch → sign.

Kullanım:
    patch_plist.py build/KitapAI.app --display-name "kitap.ai" \
        --api https://makine.tailnet.ts.net [--allow-http]
"""

from __future__ import annotations

import argparse
import plistlib
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("app", type=Path, help=".app paketi")
    p.add_argument("--display-name", default="kitap.ai")
    p.add_argument("--version", default="2.0.0")
    p.add_argument("--build", default="1")
    p.add_argument("--api", default="", help="uygulamanın varsayılan API adresi")
    p.add_argument(
        "--allow-http", action="store_true",
        help="düz HTTP'ye izin ver (yalnızca yerel ağ / Tailscale IP'si için)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    plist_path = args.app / "Info.plist"
    if not plist_path.is_file():
        print(f"hata: {plist_path} yok — önce `iosbuild bundle` çalıştırın", file=sys.stderr)
        return 1

    info = plistlib.loads(plist_path.read_bytes())

    info["CFBundleDisplayName"] = args.display_name
    info["CFBundleName"] = args.display_name
    info["CFBundleShortVersionString"] = args.version
    info["CFBundleVersion"] = args.build
    info["UISupportedInterfaceOrientations"] = [
        "UIInterfaceOrientationPortrait",
        "UIInterfaceOrientationLandscapeLeft",
        "UIInterfaceOrientationLandscapeRight",
    ]
    # Yerel ağdaki (Tailscale dâhil) bir sunucuya bağlanmak iOS 14+ ile izin ister.
    info["NSLocalNetworkUsageDescription"] = (
        "Kitap önerileri kendi bilgisayarındaki kitap.ai sunucusundan gelir."
    )
    if args.api:
        info["KitapAIDefaultAPIURL"] = args.api

    if args.allow_http:
        # App Transport Security düz HTTP'yi engeller. `NSAllowsLocalNetworking` yalnızca
        # .local / özel ağ adreslerini kapsar; Tailscale adresleri (100.64.0.0/10) bunun
        # dışında kaldığından uygulama Safari'de açılan sunucuya bağlanamıyordu. Bu bayrak
        # bilinçli olarak tüm düz HTTP'ye izin verir: yalnızca kişisel/yan yükleme
        # kurulumları içindir; mağaza sürümü için HTTPS (`tailscale serve`) kullanın.
        info["NSAppTransportSecurity"] = {
            "NSAllowsArbitraryLoads": True,
        }

    plist_path.write_bytes(plistlib.dumps(info, fmt=plistlib.FMT_XML))
    print(f"Info.plist güncellendi: {plist_path}")
    for key in ("CFBundleDisplayName", "CFBundleShortVersionString", "KitapAIDefaultAPIURL"):
        if key in info:
            print(f"  {key} = {info[key]}")
    if args.allow_http:
        print("  NSAppTransportSecurity.NSAllowsArbitraryLoads = True")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
