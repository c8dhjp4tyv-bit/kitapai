"""API sözleşmesi — sunucu, web, Android ve iOS istemcilerinin ortak dili.

Eski sürümde model markdown üretiyor, her istemci onu ayrı ayrı regex'le
ayrıştırıyordu. Burada sözleşme tiplidir: model yalnızca *seçim* ve *gerekçe*
üretir, kitap bilgisi (başlık, yazar, yıl, kapak, ISBN) daima katalogdan gelir.
Böylece uydurma meta veri yapısal olarak imkânsızdır.

TypeScript (`clients/shared/src/types.ts`) ve Swift
(`clients/ios/Sources/Models.swift`) karşılıkları elle tutulur;
`tests/test_contract.py` her koşuda alanların üç tarafta da aynı kaldığını
doğrular, böylece sürüklenme (drift) sessizce geçmez.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ── Ortak kısıtlar ─────────────────────────────────────────────────────────

MAX_QUERY_CHARS = 500
MAX_RESULTS = 10


class Language(str, Enum):
    """ISO 639-3 — Open Library baskılarında kullanılan kodlar."""

    TUR = "tur"
    ENG = "eng"


class Strictness(str, Enum):
    """Filtrelerin ne kadar bağlayıcı olduğu."""

    STRICT = "strict"  # tür/ruh hali filtrelerine uymayan aday elenir
    SOFT = "soft"      # filtreler yalnızca sıralamayı etkiler


# ── Katalog nesneleri ──────────────────────────────────────────────────────


class Rating(BaseModel):
    model_config = ConfigDict(frozen=True)

    average: Annotated[float, Field(ge=0, le=5)]
    count: Annotated[int, Field(ge=0)]


class Book(BaseModel):
    """Katalogdaki bir eser (Open Library `work`), en iyi baskısıyla birleşik."""

    model_config = ConfigDict(frozen=True)

    work_key: str = Field(description="Open Library eser anahtarı, örn. /works/OL45804W")
    title: str
    subtitle: str | None = None
    authors: list[str] = Field(default_factory=list)
    first_published: int | None = Field(default=None, description="İlk yayın yılı")
    description: str | None = Field(
        default=None, description="Open Library açıklaması (çoğunlukla İngilizce)"
    )
    genres: list[str] = Field(default_factory=list, description="Türkçe tür etiketleri")
    moods: list[str] = Field(default_factory=list, description="Türkçe ruh hali etiketleri")
    subjects: list[str] = Field(default_factory=list, description="Ham Open Library konuları")
    languages: list[str] = Field(default_factory=list)
    pages: int | None = None
    isbns: list[str] = Field(default_factory=list)
    cover_url: str | None = None
    openlibrary_url: str
    rating: Rating | None = None
    readers: int | None = Field(default=None, description="Open Library okuma kaydı sayısı")
    popularity: float = Field(default=0.0, description="0-1 arası normalize edilmiş bilinirlik")


class Recommendation(BaseModel):
    """Tek bir öneri: katalog kaydı + modelin ürettiği gerekçe."""

    rank: Annotated[int, Field(ge=1)]
    book: Book
    why: str = Field(description="Kullanıcının isteğine bağlanan Türkçe gerekçe")
    hooks: list[str] = Field(default_factory=list, description="Kısa çengel ifadeler")
    content_notes: list[str] = Field(
        default_factory=list, description="Tetikleyici/içerik uyarıları"
    )
    confidence: Annotated[float, Field(ge=0, le=1)] = 0.5
    grounded: bool = Field(default=True, description="Kitap katalogda doğrulandı mı")
    match_reasons: list[str] = Field(
        default_factory=list,
        description="Makine tarafından üretilen eşleşme kanıtı (tür/ruh/dönem)",
    )


# ── İstek / yanıt ──────────────────────────────────────────────────────────


class RecommendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(default="", max_length=MAX_QUERY_CHARS)
    genres: list[str] = Field(default_factory=list, description="Tür slug'ları; boş = fark etmez")
    moods: list[str] = Field(
        default_factory=list, description="Ruh hali slug'ları; boş = fark etmez"
    )
    languages: list[Language] = Field(default_factory=list)
    era: str | None = Field(default=None, description="klasik | modern | cagdas")
    length: str | None = Field(default=None, description="kisa | orta | uzun | tugla")
    audience: str | None = Field(default=None, description="cocuk | genc | yetiskin")
    exclude_work_keys: list[str] = Field(
        default_factory=list, description="Zaten okunanlar"
    )
    limit: Annotated[int, Field(ge=1, le=MAX_RESULTS)] = 3
    strictness: Strictness = Strictness.SOFT
    seed: int | None = Field(default=None, description="Tekrarlanabilir örnekleme için")

    @field_validator("query")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    def is_empty(self) -> bool:
        return not (self.query or self.genres or self.moods or self.era or self.audience)


class ResponseMeta(BaseModel):
    request_id: str
    model: str
    engine: str
    latency_ms: int
    retrieved: int = Field(description="Aday havuzunun büyüklüğü")
    grounded_ratio: float = Field(description="Katalogda doğrulanan önerilerin oranı")
    degraded: bool = Field(default=False, description="Model devre dışı; yedek sıralama kullanıldı")
    notes: list[str] = Field(default_factory=list)


class RecommendResponse(BaseModel):
    recommendations: list[Recommendation]
    followups: list[str] = Field(default_factory=list, description="Önerilen sonraki adım soruları")
    meta: ResponseMeta


class SearchResponse(BaseModel):
    books: list[Book]
    total: int
    meta: ResponseMeta


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    engine: str
    model: str
    catalog_books: int
    catalog_path: str
    vectors_loaded: bool
    device: str
    uptime_s: float


class TaxonomyResponse(BaseModel):
    """İstemciler tür/ruh listelerini sabit kodlamaz, buradan alır."""

    genres: list[dict]
    moods: list[dict]
    eras: list[dict]
    lengths: list[dict]
    audiences: list[dict]


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None
    request_id: str | None = None


# ── Modelin ürettiği ara biçim ─────────────────────────────────────────────
# Model ham kitap verisi üretmez; yalnızca aday listesinden seçim yapar.


class ModelPick(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(description="Aday listesindeki kısa kimlik, örn. 'a3'")
    why: str = ""
    hooks: list[str] = Field(default_factory=list)
    content_notes: list[str] = Field(default_factory=list)
    confidence: float = 0.6

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp(cls, v: object) -> float:
        try:
            f = float(v)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.6
        return min(1.0, max(0.0, f))

    @field_validator("hooks", "content_notes", mode="before")
    @classmethod
    def _listify(cls, v: object) -> list:
        if v is None:
            return []
        if isinstance(v, str):
            return [v] if v.strip() else []
        return list(v)  # type: ignore[arg-type]


class ModelOutput(BaseModel):
    """Modelin üretmesi beklenen tam JSON gövdesi."""

    model_config = ConfigDict(extra="ignore")

    picks: list[ModelPick] = Field(default_factory=list)
    followups: list[str] = Field(default_factory=list)

    @field_validator("followups", mode="before")
    @classmethod
    def _listify(cls, v: object) -> list:
        if v is None:
            return []
        if isinstance(v, str):
            return [v] if v.strip() else []
        return list(v)  # type: ignore[arg-type]
