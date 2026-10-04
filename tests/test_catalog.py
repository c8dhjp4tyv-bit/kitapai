"""Dump → katalog boru hattı."""

from __future__ import annotations


def test_kalitesiz_kayitlar_eleniyor(books):
    keys = {b["work_key"] for b in books}
    # Başlıksız eser ve tek baskılı, puansız taslak katalogda olmamalı.
    assert "/works/OL90W" not in keys
    assert "/works/OL91W" not in keys
    assert len(books) == 12


def test_yazar_adlari_cozuluyor(books):
    dune = next(b for b in books if b["title"] == "Dune")
    assert dune["authors"] == ["Frank Herbert"]
    good_omens = next(b for b in books if b["title"] == "Good Omens")
    assert good_omens["authors"] == ["Terry Pratchett", "J. R. R. Tolkien"]


def test_baskilardan_turetilen_alanlar(books):
    dune = next(b for b in books if b["title"] == "Dune")
    # İki baskının sayfa medyanı: (412 + 640) / 2
    assert dune["pages"] == 526
    assert set(dune["languages"]) == {"eng", "tur"}
    assert dune["title_tr"] == "Dune (Çöl Gezegeni)"
    assert len(dune["isbns"]) == 2


def test_aciklama_iki_bicimde_de_okunuyor(books):
    """Open Library açıklamayı düz metin ya da {type,value} olarak tutar."""
    for title in ("Dune", "Nineteen Eighty-Four"):
        book = next(b for b in books if b["title"] == title)
        assert book["description"]
        assert not book["description"].startswith("{")


def test_puan_ve_okur_sayilari(books):
    dune = next(b for b in books if b["title"] == "Dune")
    assert dune["rating_count"] == 4
    assert abs(dune["rating_avg"] - 4.5) < 0.01
    assert dune["readers"] == 3


def test_bilinirlik_normalize(books):
    pops = [b["popularity"] for b in books]
    assert max(pops) == 1.0
    assert all(0.0 <= p <= 1.0 for p in pops)


def test_turetilmis_etiketler(books):
    p_and_p = next(b for b in books if b["title"] == "Pride and Prejudice")
    assert p_and_p["era"] == "klasik"
    assert p_and_p["length_bucket"] == "orta"
    hobbit = next(b for b in books if b["title"] == "The Hobbit")
    assert hobbit["audience"] == "cocuk"   # "Juvenile fiction" konusundan


def test_kapak_ve_baglantilar(books):
    dune = next(b for b in books if b["title"] == "Dune")
    assert dune["cover_url"].startswith("https://covers.openlibrary.org/")
    assert dune["openlibrary_url"] == "https://openlibrary.org/works/OL1W"


def test_kunye_yazildi(catalog_con):
    from kitapai.serve.catalog import catalog_meta

    meta = catalog_meta(catalog_con)
    assert meta["sources"]["works"].endswith(".txt.gz")
    assert "genres" in meta["taxonomy"]
    assert meta["stages"]["books"] == 12


def test_fts_indeksi_calisiyor(catalog_con):
    catalog_con.execute("LOAD fts")
    rows = catalog_con.execute("""
        SELECT title FROM (
          SELECT title, fts_main_books.match_bm25(work_key, 'desert ecology') AS s FROM books
        ) WHERE s IS NOT NULL ORDER BY s DESC
    """).fetchall()
    assert rows and rows[0][0] == "Dune"


def test_stats_sorgulari_calisiyor(catalog_con):
    """`kitapai data stats` içindeki sorgular katalog şemasıyla uyumlu olmalı."""
    coverage = catalog_con.execute("""
        SELECT
          round(100.0 * count(*) FILTER (WHERE cover_id IS NOT NULL) / count(*), 1),
          round(100.0 * count(*) FILTER (WHERE description IS NOT NULL) / count(*), 1),
          round(100.0 * count(*) FILTER (WHERE len(genres) > 0) / count(*), 1),
          round(100.0 * count(*) FILTER (WHERE rating_count > 0) / count(*), 1),
          round(100.0 * count(*) FILTER (
            WHERE list_contains(languages, 'tur')) / count(*), 1)
        FROM books
    """).fetchone()
    assert all(0.0 <= value <= 100.0 for value in coverage)

    # unnest doğrudan GROUP BY ile kullanılamaz — alt sorgu şart.
    rows = catalog_con.execute("""
        SELECT g, count(*) AS n
        FROM (SELECT unnest(genres) AS g FROM books)
        GROUP BY g ORDER BY n DESC LIMIT 5
    """).fetchall()
    assert rows and rows[0][1] > 0


def test_karma_kaynak_eksikleri_uzaktan_cozer(tmp_path, monkeypatch):
    """Yerelde bulunmayan dump'lar URL'ye düşmeli (dar diskte akıtma yolu)."""
    from kitapai.data import sources

    # Yalnızca works ve authors yerelde; kalanlar uzaktan çözülmeli.
    for kind in ("works", "authors"):
        (tmp_path / f"ol_dump_{kind}_2026-08-31.txt.gz").write_bytes(b"")

    monkeypatch.setattr(
        sources, "resolve_latest",
        lambda kind, **_kw: f"https://ornek/ol_dump_{kind}_2026-08-31.txt.gz",
    )
    src = sources.mixed(tmp_path)

    assert src.works.startswith(str(tmp_path))
    assert src.authors.startswith(str(tmp_path))
    assert src.editions.startswith("https://")
    assert src.ratings.startswith("https://")
    assert src.is_remote()
