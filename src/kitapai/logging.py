"""Tek satırlık, yapılandırılmış log kurulumu.

Kütüphane kodu asla `print` kullanmaz; CLI zengin çıktı için Rich'e,
servis ise uvicorn'un log akışına yazar.
"""

from __future__ import annotations

import logging
import os
import sys

_CONFIGURED = False


def setup(level: str | int | None = None) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    lvl = level or os.environ.get("KITAPAI_LOG_LEVEL", "INFO")
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root = logging.getLogger("kitapai")
    root.setLevel(lvl)
    root.handlers[:] = [handler]
    root.propagate = False
    _CONFIGURED = True


def get(name: str) -> logging.Logger:
    setup()
    return logging.getLogger(f"kitapai.{name}")
