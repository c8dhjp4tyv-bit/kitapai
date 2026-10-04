"""Proje içi yol çözümlemesi.

Tek bir yerden yönetilir ki CLI, servis ve testler aynı düzeni görsün.
`KITAPAI_DATA_DIR` ile veri kökü taşınabilir (örn. harici diske).
"""

from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    """Depo kökü: bu dosyanın iki üstü (src/kitapai/paths.py -> kök)."""
    return Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    env = os.environ.get("KITAPAI_DATA_DIR")
    return Path(env).expanduser().resolve() if env else project_root() / "data"


def dumps_dir() -> Path:
    return data_dir() / "dumps"


def models_dir() -> Path:
    env = os.environ.get("KITAPAI_MODELS_DIR")
    return Path(env).expanduser().resolve() if env else project_root() / "models"


def runs_dir() -> Path:
    return project_root() / "runs"


def ensure(path: Path) -> Path:
    """Dizini (gerekirse üst dizinleriyle) oluşturup geri döner."""
    path.mkdir(parents=True, exist_ok=True)
    return path
