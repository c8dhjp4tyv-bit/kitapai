"""Ayarlar — ortam değişkeni / .env / CLI bayrağı sırasıyla.

Tüm modüller `get_settings()` üzerinden okur; testler `get_settings.cache_clear()`
ile sıfırlayabilir.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from . import paths

EngineName = Literal["transformers", "openai", "stub"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="KITAPAI_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Servis
    host: str = "0.0.0.0"
    port: int = 8000
    api_key: str = ""
    cors_origins: str = "*"
    request_timeout_s: float = 120.0
    max_concurrent_generations: int = 1
    queue_limit: int = 8

    # Model
    engine: EngineName = "transformers"
    base_model: str = "unsloth/Qwen2.5-3B-Instruct-bnb-4bit"
    adapter_path: str = "models/kitapai-lora"   # eski tek-model adaptörü (değerlendirme için)
    select_adapter_path: str = "models/kitapai-select"
    write_adapter_path: str = "models/kitapai-write"
    #: Uyum puanı bunun altındaki seçimler (hedef varsa) elenir; aşağıdaki
    #: `serve/pipeline.py::_filter_weak` açıklamasına bakın.
    min_confidence: float = 0.5
    max_new_tokens: int = 700
    temperature: float = 0.6
    top_p: float = 0.9
    load_in_4bit: bool = True

    # OpenAI-uyumlu motor (llama.cpp / vLLM)
    openai_base_url: str = "http://127.0.0.1:8080/v1"
    openai_model: str = "kitapai"
    openai_api_key: str = "yok"

    # Veri
    catalog_path: str = "data/catalog.duckdb"
    vectors_path: str = "data/vectors"
    embedding_model: str = "intfloat/multilingual-e5-small"
    duckdb_memory_limit: str = "3GB"
    duckdb_threads: int = 4

    # Erişim/geri getirme
    candidate_pool: int = Field(default=40, ge=5, le=200)
    lexical_weight: float = 1.0
    dense_weight: float = 1.0
    popularity_weight: float = 0.35
    min_rating_count: int = 0

    log_level: str = "INFO"

    @field_validator("adapter_path", "select_adapter_path", "write_adapter_path",
                     "catalog_path", "vectors_path")
    @classmethod
    def _expand(cls, v: str) -> str:
        return str(Path(v).expanduser())

    # ── Türetilmiş ─────────────────────────────────────────────────────────

    def resolved(self, value: str) -> Path:
        """Göreli yolları depo köküne göre çözer."""
        p = Path(value).expanduser()
        return p if p.is_absolute() else paths.project_root() / p

    @property
    def catalog_file(self) -> Path:
        return self.resolved(self.catalog_path)

    @property
    def vectors_dir(self) -> Path:
        return self.resolved(self.vectors_path)

    @property
    def adapter_dir(self) -> Path:
        return self.resolved(self.adapter_path)

    @property
    def select_adapter_dir(self) -> Path:
        return self.resolved(self.select_adapter_path)

    @property
    def write_adapter_dir(self) -> Path:
        return self.resolved(self.write_adapter_path)

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
