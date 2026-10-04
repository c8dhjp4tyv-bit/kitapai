"""Sözcüksel + anlamsal aramayı birleştiren geri getirme katmanı.

Füzyon için Reciprocal Rank Fusion (RRF) kullanılır: iki listenin ham puanları
farklı ölçeklerde olduğu için (BM25 sınırsız, kosinüs 0-1) puanları normalize
etmek yerine *sıraları* birleştirmek daha kararlı sonuç verir.

Son sıralama üç bileşenden oluşur:
  RRF füzyonu  +  istek-kitap uyum puanı  +  bilinirlik
"""

from __future__ import annotations

from dataclasses import dataclass, field

import duckdb

from ..logging import get
from ..matching import match_score
from .dense import DenseIndex
from .expand import Expansion, expand
from .filters import Filters
from .lexical import LexicalIndex

log = get("retrieval.hybrid")

RRF_K = 60  # RRF sabiti: küçük değerler ilk sıraları daha çok ödüllendirir


@dataclass(frozen=True)
class Target:
    """Uyum puanının hesaplandığı ETKİN hedef: kullanıcının seçtikleri + metinden çıkarılanlar.

    Eskiden puanlama özgün isteği kullanıyordu; kullanıcı chip seçmeden serbest metin
    yazdığında ("karanlık ve düşündürücü bir distopya") tür/ruh hali puana hiç girmiyor,
    puan yalnızca bilinirliğe dayanıyordu. Güven göstergesi de aynı hedefle hesaplanır.
    """

    genres: list[str] = field(default_factory=list)
    moods: list[str] = field(default_factory=list)
    era: str | None = None
    length: str | None = None
    audience: str | None = None
    languages: list = field(default_factory=list)


@dataclass
class RetrievalResult:
    target: Target = field(default_factory=Target)
    books: list[dict] = field(default_factory=list)
    expansion: Expansion | None = None
    lexical_count: int = 0
    dense_count: int = 0
    used_browse: bool = False

    @property
    def keys(self) -> list[str]:
        return [b["work_key"] for b in self.books]


def reciprocal_rank_fusion(
    ranked_lists: list[tuple[list[str], float]], *, k: int = RRF_K
) -> dict[str, float]:
    """[(sıralı anahtarlar, ağırlık)] → anahtar başına füzyon puanı."""
    scores: dict[str, float] = {}
    for keys, weight in ranked_lists:
        for rank, key in enumerate(keys, start=1):
            scores[key] = scores.get(key, 0.0) + weight / (k + rank)
    return scores


class Retriever:
    """Katalogdan aday kitap havuzu çıkarır."""

    SELECT = (
        "work_key, title, subtitle, title_tr, authors, subjects, description, "
        "first_published, pages, languages, isbns, genres, moods, "
        "era, length_bucket, audience, rating_avg, rating_count, readers, popularity, "
        "cover_url, openlibrary_url"
    )

    def __init__(
        self,
        con: duckdb.DuckDBPyConnection,
        dense: DenseIndex | None = None,
        *,
        lexical_weight: float = 1.0,
        dense_weight: float = 1.0,
        popularity_weight: float = 0.35,
        match_weight: float = 1.2,
    ) -> None:
        self.con = con
        self.lexical = LexicalIndex(con)
        self.dense = dense
        self.lexical_weight = lexical_weight
        self.dense_weight = dense_weight
        self.popularity_weight = popularity_weight
        self.match_weight = match_weight

    # ── yardımcılar ────────────────────────────────────────────────────────

    def fetch(self, keys: list[str]) -> dict[str, dict]:
        if not keys:
            return {}
        rows = self.con.execute(
            f"SELECT {self.SELECT} FROM books WHERE list_contains(?::VARCHAR[], work_key)",
            [keys],
        ).fetchall()
        cols = [c.strip() for c in self.SELECT.split(",")]
        return {r[0]: dict(zip(cols, r, strict=True)) for r in rows}

    def count(self) -> int:
        return int(self.con.execute("SELECT count(*) FROM books").fetchone()[0])

    # ── ana akış ───────────────────────────────────────────────────────────

    def retrieve(self, request, *, pool: int = 40) -> RetrievalResult:
        """`RecommendRequest` benzeri bir nesne için aday havuzu döndürür."""
        genres = list(request.genres or [])
        moods = list(request.moods or [])
        languages = [getattr(lang, "value", lang) for lang in (request.languages or [])]

        exp = expand(request.query or "", genres=genres, moods=moods)
        # Kullanıcı filtre seçmediyse metinden çıkarılanlar devreye girer.
        effective_genres = genres or exp.detected_genres[:2]
        effective_moods = moods or exp.detected_moods[:2]

        strict = getattr(request, "strictness", None)
        strict_flag = getattr(strict, "value", strict) == "strict"

        filters = Filters(
            genres=effective_genres,
            moods=effective_moods,
            era=request.era,
            length=request.length,
            audience=request.audience,
            languages=languages,
            exclude_keys=list(request.exclude_work_keys or []),
            strict=strict_flag,
        )

        target = Target(
            genres=list(effective_genres), moods=list(effective_moods), era=request.era,
            length=request.length, audience=request.audience, languages=list(languages),
        )
        result = RetrievalResult(expansion=exp, target=target)
        lexical_hits = self.lexical.search(exp.query_text, filters, pool)
        result.lexical_count = len(lexical_hits)

        dense_hits = []
        if self.dense is not None and (request.query or "").strip():
            # Ham Türkçe DEĞİL, İngilizceye çevrilmiş sorgu (bkz. dense_query).
            dense_hits = self.dense.search(exp.dense_query, pool)
        result.dense_count = len(dense_hits)

        fused = reciprocal_rank_fusion([
            ([h.work_key for h in lexical_hits], self.lexical_weight),
            ([h.work_key for h in dense_hits], self.dense_weight),
        ])

        if not fused:
            # Metin eşleşmedi ya da istek boş: filtrelere uyan popüler kitaplar.
            browse = self.lexical.browse(filters, pool, seed=getattr(request, "seed", None))
            fused = {h.work_key: h.score for h in browse}
            result.used_browse = True

        rows = self.fetch(list(fused))
        # Gömme indeksi katalogdan eski olabilir; bulunamayan anahtarlar elenir.
        candidates = [rows[k] for k in fused if k in rows]

        exclude = set(request.exclude_work_keys or [])
        candidates = [b for b in candidates if b["work_key"] not in exclude]

        if strict_flag:
            candidates = [b for b in candidates if self._passes(b, filters)]

        # Nihai sıralama: füzyon + uyum + bilinirlik
        scored = []
        for book in candidates:
            fusion = fused.get(book["work_key"], 0.0)
            # RRF puanları küçük (≈0.016 tavan); aynı ölçeğe getirmek için
            # RRF_K ile çarpılır.
            normalized_fusion = min(1.0, fusion * RRF_K)
            total = (
                normalized_fusion
                + self.match_weight * match_score(book, target)
                + self.popularity_weight * float(book.get("popularity") or 0.0)
            )
            scored.append((total, book))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        result.books = [book for _score, book in scored[:pool]]
        return result

    @staticmethod
    def _passes(book: dict, filters: Filters) -> bool:
        if filters.genres and not set(filters.genres) & set(book.get("genres") or []):
            return False
        if filters.moods and not set(filters.moods) & set(book.get("moods") or []):
            return False
        if filters.era and book.get("era") != filters.era:
            return False
        if filters.length and book.get("length_bucket") != filters.length:
            return False
        if filters.audience and book.get("audience") != filters.audience:
            return False
        return not (
            filters.languages
            and not set(filters.languages) & set(book.get("languages") or [])
        )

    def similar(self, work_key: str, *, limit: int = 10) -> list[dict]:
        """Bir kitaba benzer eserler: gömme varsa vektörle, yoksa tür/konu örtüşmesiyle."""
        if self.dense is not None and work_key in self.dense._index:
            import numpy as np

            idx = self.dense._index[work_key]
            vec = self.dense.vectors[idx].astype(np.float32)
            scores = self.dense.vectors.astype(np.float32) @ vec
            order = np.argsort(-scores)[: limit + 1]
            keys = [self.dense.keys[int(i)] for i in order if self.dense.keys[int(i)] != work_key]
            rows = self.fetch(keys[:limit])
            return [rows[k] for k in keys[:limit] if k in rows]

        row = self.fetch([work_key]).get(work_key)
        if not row:
            return []
        rows = self.con.execute(f"""
            SELECT {self.SELECT} FROM books
            WHERE work_key <> ?
              AND list_has_any(genres, ?::VARCHAR[])
            ORDER BY len(list_intersect(subjects, ?::VARCHAR[])) DESC, popularity DESC
            LIMIT ?
        """, [work_key, row.get("genres") or [], row.get("subjects") or [], limit]).fetchall()
        cols = [c.strip() for c in self.SELECT.split(",")]
        return [dict(zip(cols, r, strict=True)) for r in rows]
