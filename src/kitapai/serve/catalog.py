"""Servis tarafında katalog erişimi."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from ..logging import get

log = get("serve.catalog")


class CatalogUnavailable(RuntimeError):
    """Katalog dosyası yok ya da içi boş."""


def open_catalog(path: Path, *, threads: int = 4) -> duckdb.DuckDBPyConnection:
    """Salt okunur bağlantı açar ve temel doğrulamayı yapar."""
    if not Path(path).exists():
        raise CatalogUnavailable(
            f"katalog bulunamadı: {path}\n"
            f"Önce kurun:  kitapai data build --dumps <dizin>"
        )
    con = duckdb.connect(str(path), read_only=True)
    con.execute(f"SET threads={threads}")
    try:
        count = con.execute("SELECT count(*) FROM books").fetchone()[0]
    except duckdb.Error as exc:
        con.close()
        raise CatalogUnavailable(f"{path} geçerli bir katalog değil: {exc}") from exc
    if count == 0:
        con.close()
        raise CatalogUnavailable(f"{path} içinde hiç kitap yok")
    log.info("katalog açıldı: %s (%s kitap)", path, f"{count:,}")
    return con


def catalog_meta(con: duckdb.DuckDBPyConnection) -> dict:
    """Derleme künyesi (yoksa boş sözlük)."""
    try:
        row = con.execute("SELECT value FROM catalog_meta WHERE key='build'").fetchone()
    except duckdb.Error:
        return {}
    return json.loads(row[0]) if row else {}
