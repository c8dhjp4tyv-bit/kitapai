"""DuckDB FTS (BM25) üzerinden sözcüksel arama."""

from __future__ import annotations

from dataclasses import dataclass

import duckdb

from ..logging import get
from .filters import Filters

log = get("retrieval.lexical")


@dataclass(frozen=True)
class Hit:
    work_key: str
    score: float


class LexicalIndex:
    """`books` tablosu üzerindeki BM25 indeksini sorgular."""

    def __init__(self, con: duckdb.DuckDBPyConnection) -> None:
        self.con = con
        self._available = self._probe()

    def _probe(self) -> bool:
        try:
            self.con.execute("LOAD fts")
            self.con.execute(
                "SELECT fts_main_books.match_bm25(work_key, 'test') FROM books LIMIT 1"
            ).fetchall()
            return True
        except duckdb.Error as exc:  # indeks kurulmamışsa servis yine çalışsın
            log.warning("FTS indeksi kullanılamıyor (%s) — yalnız filtre/bilinirlik", exc)
            return False

    @property
    def available(self) -> bool:
        return self._available

    def search(self, text: str, filters: Filters, limit: int) -> list[Hit]:
        if not self._available or not text.strip():
            return []
        where, params = filters.sql("b")
        sql = f"""
            WITH scored AS (
              SELECT work_key, fts_main_books.match_bm25(work_key, ?) AS bm25 FROM books
            )
            SELECT b.work_key, s.bm25
            FROM scored s JOIN books b USING (work_key)
            WHERE s.bm25 IS NOT NULL AND {where}
            ORDER BY s.bm25 DESC
            LIMIT ?
        """
        rows = self.con.execute(sql, [text, *params, limit]).fetchall()
        return [Hit(k, float(s)) for k, s in rows]

    def browse(self, filters: Filters, limit: int, *, seed: float | None = None) -> list[Hit]:
        """Metin yokken (veya BM25 boş dönerken) bilinirliğe göre gezinme.

        `seed` verilirse aynı filtreyle tekrar tekrar aynı kitapların gelmemesi
        için hafif bir rastgelelik eklenir.
        """
        where, params = filters.sql("b")
        jitter = (
            "" if seed is None
            else f" * (0.75 + 0.5 * abs(hash(b.work_key || '{seed}') % 1000) / 1000.0)"
        )
        sql = f"""
            SELECT b.work_key, b.popularity{jitter} AS score
            FROM books b WHERE {where}
            ORDER BY score DESC LIMIT ?
        """
        rows = self.con.execute(sql, [*params, limit]).fetchall()
        return [Hit(k, float(s)) for k, s in rows]
