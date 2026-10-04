"""Katalog sorgularına uygulanan filtreler (SQL'e çevrilebilir)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Filters:
    genres: list[str] = field(default_factory=list)
    moods: list[str] = field(default_factory=list)
    era: str | None = None
    length: str | None = None
    audience: str | None = None
    languages: list[str] = field(default_factory=list)
    exclude_keys: list[str] = field(default_factory=list)
    min_rating_count: int = 0
    #: `strict` ise tür/ruh/dönem filtreleri SQL'de eleme yapar; değilse
    #: yalnızca sıralamayı etkiler (geri getirme kapsamı geniş kalır).
    strict: bool = False

    def sql(self, alias: str = "b") -> tuple[str, list]:
        """(WHERE parçası, parametreler)."""
        clauses: list[str] = []
        params: list = []

        if self.exclude_keys:
            clauses.append(f"NOT list_contains(?::VARCHAR[], {alias}.work_key)")
            params.append(self.exclude_keys)
        if self.min_rating_count:
            clauses.append(f"{alias}.rating_count >= ?")
            params.append(self.min_rating_count)
        if self.languages:
            # Dil her zaman sert kısıttır: Türkçe baskı istendiyse İngilizce
            # kitap önermek kullanıcının işine yaramaz.
            clauses.append(f"list_has_any({alias}.languages, ?::VARCHAR[])")
            params.append(self.languages)

        # Dönem, uzunluk ve okur kitlesi de öyle. Bunlar serbest metinden
        # çıkarılmaz, kullanıcı arayüzde açıkça seçer; "1900 öncesi klasik"
        # seçip 2001 tarihli kitap görmek tercih değil hatadır. `strictness`
        # yalnızca tür/ruh hali gibi geniş ve çıkarımsal filtreleri yönetir.
        if self.era:
            clauses.append(f"{alias}.era = ?")
            params.append(self.era)
        if self.length:
            clauses.append(f"{alias}.length_bucket = ?")
            params.append(self.length)
        if self.audience:
            clauses.append(f"{alias}.audience = ?")
            params.append(self.audience)

        if self.strict:
            if self.genres:
                clauses.append(f"list_has_any({alias}.genres, ?::VARCHAR[])")
                params.append(self.genres)
            if self.moods:
                clauses.append(f"list_has_any({alias}.moods, ?::VARCHAR[])")
                params.append(self.moods)
        return (" AND ".join(clauses) if clauses else "true"), params
