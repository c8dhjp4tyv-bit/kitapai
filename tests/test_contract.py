"""API sözleşmesinin üç istemcide de aynı kaldığını doğrular.

Sunucu şeması değişip TypeScript ya da Swift karşılığı güncellenmezse istemci
sessizce bozulur: alan `undefined`/`nil` gelir, arayüz boş görünür. Bu test o
sürüklenmeyi derleme zamanında değil, test zamanında yakalar.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from kitapai import schemas

ROOT = Path(__file__).resolve().parents[1]
TS_TYPES = ROOT / "clients" / "shared" / "src" / "types.ts"
SWIFT_MODELS = ROOT / "clients" / "ios" / "Sources" / "Models.swift"

#: İstemcilerin karşılığını tutması gereken modeller.
SHARED_MODELS = [
    schemas.Rating,
    schemas.Book,
    schemas.Recommendation,
    schemas.ResponseMeta,
    schemas.RecommendResponse,
    schemas.SearchResponse,
    schemas.HealthResponse,
    schemas.RecommendRequest,
    schemas.ErrorResponse,
]


def _fields(model) -> set[str]:
    return set(model.model_fields)


@pytest.mark.parametrize("model", SHARED_MODELS, ids=lambda m: m.__name__)
def test_typescript_tum_alanlari_iceriyor(model):
    text = TS_TYPES.read_text(encoding="utf-8")
    # `interface Book { ... }` gövdesini yakala
    match = re.search(rf"interface {model.__name__} \{{(.*?)\n\}}", text, re.DOTALL)
    assert match, f"{model.__name__} TypeScript tarafında yok: {TS_TYPES}"
    body = match.group(1)
    missing = {f for f in _fields(model) if not re.search(rf"\b{re.escape(f)}\??:", body)}
    assert not missing, f"{model.__name__}: TypeScript'te eksik alan(lar) {sorted(missing)}"


@pytest.mark.parametrize("model", [
    schemas.Rating, schemas.Book, schemas.Recommendation, schemas.ResponseMeta,
    schemas.RecommendResponse, schemas.SearchResponse, schemas.HealthResponse,
    schemas.RecommendRequest, schemas.ErrorResponse,
], ids=lambda m: m.__name__)
def test_swift_tum_alanlari_iceriyor(model):
    text = SWIFT_MODELS.read_text(encoding="utf-8")
    match = re.search(rf"struct {model.__name__}[^{{]*\{{(.*?)\n\}}", text, re.DOTALL)
    assert match, f"{model.__name__} Swift tarafında yok: {SWIFT_MODELS}"
    body = match.group(1)
    missing = {
        f for f in _fields(model)
        if not re.search(rf"\b(let|var) {re.escape(f)}\s*:", body)
    }
    assert not missing, f"{model.__name__}: Swift'te eksik alan(lar) {sorted(missing)}"


def test_taksonomi_alanlari_istemcilerde_var():
    """`/api/taxonomy` yanıtının anahtarları üç tarafta da aynı olmalı."""
    from kitapai import taxonomy

    payload = taxonomy.taxonomy_payload()
    ts = TS_TYPES.read_text(encoding="utf-8")
    swift = SWIFT_MODELS.read_text(encoding="utf-8")
    for key in payload:
        assert re.search(rf"\b{key}:", ts), f"TaxonomyResponse.{key} TypeScript'te yok"
        assert re.search(rf"\blet {key}:", swift), f"TaxonomyResponse.{key} Swift'te yok"


def test_model_ciktisi_sema_disina_tasmiyor():
    """Model yalnızca `picks`/`followups` üretir; fazlası yok sayılır."""
    output = schemas.ModelOutput.model_validate({
        "picks": [{"id": "a1", "why": "x"}],
        "followups": [],
        "uydurma_alan": {"title": "Olmayan Kitap"},
    })
    assert output.picks[0].id == "a1"
    assert not hasattr(output, "uydurma_alan")


def test_istek_bilinmeyen_alani_reddediyor():
    """`extra=forbid`: istemci yanlış alan gönderirse sessizce yutulmaz."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        schemas.RecommendRequest.model_validate({"query": "x", "bilinmeyen": 1})
