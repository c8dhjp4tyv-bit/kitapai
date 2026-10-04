"""HTTP katmanı — stub motoruyla uçtan uca."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(catalog_path, monkeypatch_session):
    import kitapai.config as config
    from kitapai.serve import app as app_module

    config.get_settings.cache_clear()
    monkeypatch_session.setenv("KITAPAI_ENGINE", "stub")
    monkeypatch_session.setenv("KITAPAI_CATALOG_PATH", str(catalog_path))
    monkeypatch_session.setenv("KITAPAI_API_KEY", "")
    config.get_settings.cache_clear()

    with TestClient(app_module.app) as test_client:
        yield test_client
    config.get_settings.cache_clear()


@pytest.fixture(scope="session")
def monkeypatch_session():
    from _pytest.monkeypatch import MonkeyPatch

    mp = MonkeyPatch()
    yield mp
    mp.undo()


def test_health(client):
    body = client.get("/health").json()
    assert body["catalog_books"] == 12
    assert body["engine"] == "stub"


def test_taxonomy(client):
    body = client.get("/api/taxonomy").json()
    assert {"genres", "moods", "eras", "lengths", "audiences"} <= set(body)
    slugs = {g["slug"] for g in body["genres"]}
    assert {"bilim-kurgu", "polisiye", "felsefe"} <= slugs


def test_oneri_katalogdan_geliyor(client):
    response = client.post(
        "/api/recommend",
        json={"query": "karanlık ve düşündürücü bir distopya", "limit": 2},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["recommendations"]
    assert len(body["recommendations"]) <= 2

    for rec in body["recommendations"]:
        book = rec["book"]
        # Katalogdan gelen gerçek alanlar — model bunları üretemez
        assert book["work_key"].startswith("/works/")
        assert book["openlibrary_url"].startswith("https://openlibrary.org/works/")
        assert rec["grounded"] is True
        assert rec["why"].strip()


def test_okunanlar_dislaniyor(client):
    body = client.post("/api/recommend", json={
        "query": "distopya", "limit": 3, "exclude_work_keys": ["/works/OL2W"],
    }).json()
    assert all(r["book"]["work_key"] != "/works/OL2W" for r in body["recommendations"])


def test_bilinmeyen_alan_reddediliyor(client):
    response = client.post("/api/recommend", json={"query": "x", "uydurma": 1})
    assert response.status_code == 422


def test_limit_siniri(client):
    assert client.post("/api/recommend", json={"query": "x", "limit": 99}).status_code == 422


def test_arama(client):
    body = client.get("/api/search", params={"q": "distopya", "limit": 5}).json()
    assert body["books"]
    assert body["meta"]["engine"] == "lexical"


def test_tek_kitap_ve_benzerleri(client):
    book = client.get("/api/book/OL1W").json()
    assert book["work_key"] == "/works/OL1W"
    assert client.get("/api/book/OLYOKW").status_code == 404

    similar = client.get("/api/similar/OL1W", params={"limit": 3}).json()
    assert all(b["work_key"] != "/works/OL1W" for b in similar["books"])


def test_meta_kunyesi(client):
    body = client.get("/api/meta").json()
    assert body["prompt_version"]
    assert body["catalog"]["stages"]["books"] == 12
