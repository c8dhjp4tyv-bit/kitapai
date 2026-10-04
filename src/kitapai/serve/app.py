"""FastAPI uygulaması.

Tailscale üzerinden telefondan erişilecek şekilde tasarlandı: 0.0.0.0'a bağlanır,
isteğe bağlı API anahtarı ister, CORS ayarı ortamdan gelir. HTTPS için
`scripts/tailscale-serve.sh` (bkz. README) kullanılır — iOS'ta düz HTTP
varsayılan olarak engellenir.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .. import __version__, taxonomy
from ..config import Settings, get_settings
from ..logging import get, setup
from ..prompting import PROMPT_VERSION
from ..retrieval.dense import DenseIndex
from ..retrieval.hybrid import Retriever
from ..schemas import (
    Book,
    ErrorResponse,
    HealthResponse,
    RecommendRequest,
    RecommendResponse,
    ResponseMeta,
    SearchResponse,
    TaxonomyResponse,
)
from .catalog import CatalogUnavailable, catalog_meta, open_catalog
from .engine import create_engine
from .pipeline import Overloaded, RecommendPipeline, to_book

log = get("serve.app")


class AppState:
    """Uygulama ömrü boyunca yaşayan kaynaklar."""

    def __init__(self) -> None:
        self.settings: Settings | None = None
        self.con = None
        self.retriever: Retriever | None = None
        self.engine = None
        self.pipeline: RecommendPipeline | None = None
        self.dense: DenseIndex | None = None
        self.started_at = time.time()
        self.catalog_books = 0


state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup()
    settings = get_settings()
    state.settings = settings

    state.con = open_catalog(settings.catalog_file, threads=settings.duckdb_threads)
    state.catalog_books = state.con.execute("SELECT count(*) FROM books").fetchone()[0]

    state.dense = DenseIndex.load(settings.vectors_dir)
    if state.dense is None:
        log.warning("gömme indeksi yok (%s) — yalnız BM25 kullanılacak; "
                    "kurmak için: kitapai index build", settings.vectors_dir)

    state.retriever = Retriever(
        state.con, state.dense,
        lexical_weight=settings.lexical_weight,
        dense_weight=settings.dense_weight,
        popularity_weight=settings.popularity_weight,
    )
    state.engine = create_engine(settings)
    state.pipeline = RecommendPipeline(state.retriever, state.engine, settings)

    # Isınma: gerçek bir istek gömme modelini, DuckDB sayfalarını ve iki adaptörü yükler;
    # yoksa ilk kullanıcı ~20 sn bekler (ölçüm: 21 sn → ~12 sn).
    try:
        await state.pipeline.recommend(RecommendRequest(query="klasik bir roman"))
    except Exception as exc:  # ısınma ölümcül değil
        log.warning("ısınma isteği başarısız: %s", exc)

    meta = catalog_meta(state.con)
    log.info("hazır — katalog %s, dump %s, istem sürümü %s",
             f"{state.catalog_books:,}", meta.get("dump_date", "?"), PROMPT_VERSION)
    try:
        yield
    finally:
        if state.con is not None:
            state.con.close()


app = FastAPI(
    title="kitap.ai",
    version=__version__,
    description="Open Library kataloğuna dayalı Türkçe kitap öneri servisi",
    lifespan=lifespan,
)


def _settings() -> Settings:
    return state.settings or get_settings()


app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_list,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


async def require_api_key(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    """API anahtarı ayarlanmışsa doğrular; boşsa kimlik doğrulama kapalıdır."""
    settings = _settings()
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="geçersiz veya eksik X-API-Key")


@app.middleware("http")
async def timing(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Process-Time-ms"] = str(int((time.perf_counter() - started) * 1000))
    return response


@app.exception_handler(CatalogUnavailable)
async def catalog_error(request: Request, exc: CatalogUnavailable):
    return JSONResponse(
        status_code=503,
        content=ErrorResponse(error="katalog_yok", detail=str(exc)).model_dump(),
    )


@app.exception_handler(Overloaded)
async def overloaded(request: Request, exc: Overloaded):
    return JSONResponse(
        status_code=503,
        content=ErrorResponse(error="mesgul", detail=str(exc)).model_dump(),
        headers={"Retry-After": "5"},
    )


# ── Uç noktalar ────────────────────────────────────────────────────────────


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = _settings()
    engine = state.engine
    return HealthResponse(
        status="ok" if engine and engine.name != "stub" else "degraded",
        version=__version__,
        engine=engine.name if engine else "yok",
        model=engine.model_id if engine else "yok",
        catalog_books=state.catalog_books,
        catalog_path=str(settings.catalog_file),
        vectors_loaded=state.dense is not None,
        device=engine.device if engine else "yok",
        uptime_s=round(time.time() - state.started_at, 1),
    )


@app.get("/api/taxonomy", response_model=TaxonomyResponse)
async def get_taxonomy() -> TaxonomyResponse:
    """İstemciler tür/ruh listelerini buradan alır — sabit kodlamaz."""
    return TaxonomyResponse(**taxonomy.taxonomy_payload())


@app.post("/api/recommend", response_model=RecommendResponse,
          dependencies=[Depends(require_api_key)])
async def recommend(request: RecommendRequest) -> RecommendResponse:
    if state.pipeline is None:
        raise CatalogUnavailable("servis henüz hazır değil")
    result = await state.pipeline.recommend(request)
    return result.response


@app.get("/api/search", response_model=SearchResponse,
         dependencies=[Depends(require_api_key)])
async def search(
    q: Annotated[str, Query(min_length=1, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> SearchResponse:
    """Katalog araması — model çalıştırmaz, sadece BM25 + filtre."""
    started = time.perf_counter()
    if state.retriever is None:
        raise CatalogUnavailable("servis henüz hazır değil")

    from ..retrieval.expand import expand
    from ..retrieval.filters import Filters

    exp = expand(q)
    hits = state.retriever.lexical.search(exp.query_text, Filters(), limit)
    rows = state.retriever.fetch([h.work_key for h in hits])
    books = [to_book(rows[h.work_key]) for h in hits if h.work_key in rows]
    return SearchResponse(
        books=books,
        total=len(books),
        meta=ResponseMeta(
            request_id="search", model="-", engine="lexical",
            latency_ms=int((time.perf_counter() - started) * 1000),
            retrieved=len(hits), grounded_ratio=1.0,
        ),
    )


@app.get("/api/book/{work_id}", response_model=Book,
         dependencies=[Depends(require_api_key)])
async def get_book(work_id: str) -> Book:
    if state.retriever is None:
        raise CatalogUnavailable("servis henüz hazır değil")
    key = work_id if work_id.startswith("/works/") else f"/works/{work_id}"
    rows = state.retriever.fetch([key])
    if key not in rows:
        raise HTTPException(status_code=404, detail=f"kitap bulunamadı: {key}")
    return to_book(rows[key])


@app.get("/api/similar/{work_id}", response_model=SearchResponse,
         dependencies=[Depends(require_api_key)])
async def similar(
    work_id: str, limit: Annotated[int, Query(ge=1, le=20)] = 8
) -> SearchResponse:
    started = time.perf_counter()
    if state.retriever is None:
        raise CatalogUnavailable("servis henüz hazır değil")
    key = work_id if work_id.startswith("/works/") else f"/works/{work_id}"
    rows = state.retriever.similar(key, limit=limit)
    return SearchResponse(
        books=[to_book(r) for r in rows],
        total=len(rows),
        meta=ResponseMeta(
            request_id="similar", model="-", engine="retrieval",
            latency_ms=int((time.perf_counter() - started) * 1000),
            retrieved=len(rows), grounded_ratio=1.0,
        ),
    )


@app.get("/api/meta")
async def meta() -> dict:
    """Katalog künyesi: hangi dump'tan, hangi seçeneklerle kuruldu."""
    if state.con is None:
        raise CatalogUnavailable("servis henüz hazır değil")
    return {
        "version": __version__,
        "prompt_version": PROMPT_VERSION,
        "catalog": catalog_meta(state.con),
    }
