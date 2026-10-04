"""Taksonomi: sınıflandırma doğruluğu ve Python/SQL eşdeğerliği."""

from __future__ import annotations

import duckdb
import pytest

from kitapai import taxonomy


def test_bilinen_kitaplar_dogru_etiketleniyor():
    genres, moods = taxonomy.classify(
        ["Science fiction", "Space flight", "Desert", "Politics and government"],
        title="Dune",
    )
    assert "bilim-kurgu" in genres
    assert "politika" in genres
    assert moods


def test_aciklama_tur_tespitini_kirletmiyor():
    """'Roman emperor' İngilizce bir ifade; Türkçe 'roman' türünü tetiklememeli."""
    genres, _ = taxonomy.classify(
        ["Philosophy", "Stoicism", "Ethics"],
        title="Meditations",
        description="Private notes of a Roman emperor on duty and mortality.",
    )
    assert "roman" not in genres
    assert "felsefe" in genres


def test_tarih_kurgu_tarihten_ayriliyor():
    genres, _ = taxonomy.classify(["Historical fiction", "War stories"])
    assert "tarihi-kurgu" in genres
    assert "tarih" not in genres  # negatif desen devrede


def test_bilim_kurgu_bilimden_ayriliyor():
    genres, _ = taxonomy.classify(["Science fiction", "Space flight"])
    assert "bilim-kurgu" in genres
    assert "bilim" not in genres


def test_donem_ve_uzunluk():
    assert taxonomy.era_of(1813) == "klasik"
    assert taxonomy.era_of(1965) == "modern"
    assert taxonomy.era_of(2011) == "cagdas"
    assert taxonomy.era_of(None) is None
    assert taxonomy.length_of(150) == "kisa"
    assert taxonomy.length_of(900) == "tugla"
    assert taxonomy.length_of(0) is None


def test_her_turun_dogal_ad_obegi_var():
    for slug in taxonomy.GENRE_SLUGS:
        assert taxonomy.genre_noun(slug), slug


@pytest.mark.parametrize("subjects,title", [
    (["Science fiction", "Space flight", "Desert"], "Dune"),
    (["Fiction", "Dystopias", "Totalitarianism"], "1984"),
    (["Detective and mystery stories", "Crime", "Murder"], "Orient"),
    (["Philosophy", "Stoicism", "Ethics"], "Meditations"),
    (["Humor", "Satire", "Fantasy", "Angels"], "Good Omens"),
])
def test_sql_ve_python_ayni_turleri_uretiyor(subjects, title):
    """`classify()` ile DuckDB ifadesi aynı sonucu vermeli — tek kaynak ilkesi."""
    py_genres, _ = taxonomy.classify(subjects, title=title)

    con = duckdb.connect()
    text = taxonomy.normalize_text(" | ".join(subjects), title)
    expr = taxonomy.sql_genres_expr("subject_text")
    sql_genres = con.execute(
        f"SELECT list_distinct({expr}) FROM (SELECT ? AS subject_text)", [text]
    ).fetchone()[0]
    con.close()

    assert set(py_genres) == set(sql_genres)


def test_desenler_re2_uyumlu():
    """Desenler hem Python `re` hem DuckDB RE2 tarafından derlenebilmeli.

    RE2 ileri/geri bakış desteklemez; böyle bir desen Python testlerinden geçer
    ama katalog kurulumu gerçek veride çöker. Bu test o sürüklenmeyi yakalar.
    """
    con = duckdb.connect()
    for table in (taxonomy.GENRES, taxonomy.MOODS):
        for label in table:
            for pattern in (*label.patterns, *label.negative):
                assert "(?!" not in pattern and "(?<" not in pattern, (
                    f"{label.slug}: RE2 ileri/geri bakışı desteklemiyor → {pattern}"
                )
                con.execute("SELECT regexp_matches('deneme metni', ?)", [pattern])
    con.close()


def test_genel_turler_spesifik_olanlari_dislamiyor():
    """Kesme yapılırken 'roman'/'klasik' spesifik türü dışarı itmemeli."""
    genres, _ = taxonomy.classify(
        ["Detective and mystery stories", "Fiction", "Classics", "Love stories"]
    )
    assert genres[0] == "polisiye"
    assert len(genres) <= 4


def test_yanlis_eslesmeler_kapandi():
    """Gerçek Open Library verisinde tespit edilen hatalı eşleşmeler."""
    assert "psikoloji" not in taxonomy.classify(["Psychological fiction"])[0]
    assert "bilim" not in taxonomy.classify(["Social science", "Political science"])[0]
    assert "bilim" not in taxonomy.classify(["Computer science"])[0]
    assert "tarih" not in taxonomy.classify(["History and criticism"])[0]
    assert taxonomy.classify(["Military art and science"])[0] == []
    # Doğru olanlar bozulmadı
    assert "psikoloji" in taxonomy.classify(["Psychology", "Cognitive science"])[0]
    assert "bilim" in taxonomy.classify(["Science", "Astronomy"])[0]
    assert "tarih" in taxonomy.classify(["History", "World war, 1939-1945"])[0]
