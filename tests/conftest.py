"""Ortak test düzeneği.

Küçük ama biçimi gerçek dump'la birebir aynı olan `mini_dump` üzerinden tüm
boru hattı bir kez kurulur ve testler arasında paylaşılır.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Testler GPU'ya dokunmasın: eğitim/değerlendirme çalışırken VRAM'i onlardan çalmasın
# (gömme modeli CUDA'da yüklenip OOM veriyordu).
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

FIXTURES = Path(__file__).resolve().parent / "fixtures"
MINI_DUMP = FIXTURES / "mini_dump"


@pytest.fixture(scope="session", autouse=True)
def _ensure_fixture() -> None:
    """Dump dosyaları yoksa üretir (depoya küçük olduğu için de girerler)."""
    if not (MINI_DUMP / "ol_dump_works_mini.txt.gz").exists():
        sys.path.insert(0, str(FIXTURES))
        import make_mini_dump

        make_mini_dump.main()


@pytest.fixture(scope="session")
def catalog_path(tmp_path_factory, _ensure_fixture) -> Path:
    from kitapai.data import sources
    from kitapai.data.catalog import BuildOptions, build_catalog

    target = tmp_path_factory.mktemp("katalog") / "catalog.duckdb"
    build_catalog(
        sources.from_directory(MINI_DUMP),
        target,
        BuildOptions(memory_limit="1GB", threads=2),
    )
    return target


@pytest.fixture(scope="session")
def catalog_con(catalog_path):
    import duckdb

    con = duckdb.connect(str(catalog_path), read_only=True)
    yield con
    con.close()


@pytest.fixture(scope="session")
def books(catalog_con) -> list[dict]:
    cols = [d[0] for d in catalog_con.execute("SELECT * FROM books LIMIT 0").description]
    rows = catalog_con.execute("SELECT * FROM books").fetchall()
    return [dict(zip(cols, r, strict=True)) for r in rows]


@pytest.fixture(scope="session")
def dataset_dir(catalog_path, tmp_path_factory) -> Path:
    from kitapai.dataset.build import DatasetOptions, build_dataset

    out = tmp_path_factory.mktemp("veri")
    build_dataset(
        catalog_path, out,
        # Fixture'daki kitapların okuru 1-3; gerçek eşik (15) hepsini eler.
        DatasetOptions(samples=60, pool_size=12, candidates=8, max_per_book=30,
                       valid_ratio=0.2, min_seed_readers=0),
    )
    from kitapai.dataset.stages import build_stages

    build_stages(out)      # select_*.jsonl (fixture'da damıtılmış veri yok → write_* boş)
    return out
