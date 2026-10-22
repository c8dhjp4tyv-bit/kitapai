"""24 haneli davet kodları üretir ve PS5'in okuduğu codes.txt dosyasına yazar.

  python scripts/ps5/make_codes.py codes.txt --count 10 --hours 72 --label "grup üyesi"

Dosya biçimi (her satır): KOD  bitiş_epoch  etiket. Kodlar 32 harfli karışmayan bir alfabeden
(0/O, 1/I/L yok) `secrets` ile üretilir: 24 hane ≈ 120 bit. Var olan dosya KORUNUR, yeni kodlar
eklenir; süresi dolanlar temizlenir. Kodu kullanıcıya XXXXXX-XXXXXX-XXXXXX-XXXXXX diye verin.
"""
from __future__ import annotations

import argparse
import secrets
import time
from pathlib import Path

ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"   # 31 simge; 0 O 1 I L yok
LENGTH = 24


def new_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(LENGTH))


def fmt(code: str) -> str:
    return "-".join(code[i:i + 6] for i in range(0, LENGTH, 6))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("file", type=Path)
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--hours", type=float, default=72)
    ap.add_argument("--label", default="")
    args = ap.parse_args()

    now = int(time.time())
    keep: list[str] = []
    if args.file.exists():
        for line in args.file.read_text(encoding="utf-8").splitlines():
            parts = line.split(None, 2)
            if len(parts) >= 2 and parts[1].isdigit() and int(parts[1]) > now:
                keep.append(line)
    expires = now + int(args.hours * 3600)
    fresh = [new_code() for _ in range(args.count)]
    label = args.label.replace("\n", " ").strip()
    keep += [f"{c} {expires} {label}".rstrip() for c in fresh]
    args.file.write_text("\n".join(keep) + "\n", encoding="utf-8")
    when = time.strftime("%d.%m.%Y %H:%M", time.localtime(expires))
    print(f"{len(fresh)} kod, {args.hours:g} saat geçerli (bitiş: {when}, bu bilgisayarın saatiyle):")
    for c in fresh:
        print("  " + fmt(c))


if __name__ == "__main__":
    main()
