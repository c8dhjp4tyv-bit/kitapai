"""Sorgu genişletme ve hibrit geri getirme."""

from __future__ import annotations

from kitapai.retrieval.expand import expand
from kitapai.retrieval.filters import Filters
from kitapai.retrieval.hybrid import Retriever, reciprocal_rank_fusion
from kitapai.schemas import Language, RecommendRequest, Strictness


def test_turkce_istek_ingilizce_terimlere_cevriliyor():
    exp = expand("karanlık ve düşündürücü bir distopya")
    assert "distopya" in exp.detected_genres
    assert "karanlik" in exp.detected_moods
    assert any("dystopi" in t for t in exp.terms)


def test_ekli_kelimeler_de_yakalaniyor():
    exp = expand("çölde geçen bir roman")
    assert "çöl" in exp.detected_themes
    assert "deserts" in exp.terms or "desert" in exp.terms


def test_bos_istek_coken_yok():
    exp = expand("")
    assert exp.terms == [] and exp.query_text == ""


def test_rrf_sirayi_odullendiriyor():
    scores = reciprocal_rank_fusion([(["a", "b", "c"], 1.0), (["c", "a"], 1.0)])
    assert scores["a"] > scores["b"]
    assert scores["c"] > scores["b"]


def test_metin_aramasi_dogru_kitabi_buluyor(catalog_con):
    r = Retriever(catalog_con)
    res = r.retrieve(RecommendRequest(query="karanlık ve düşündürücü bir distopya"), pool=5)
    assert res.books
    assert res.books[0]["title"] == "Nineteen Eighty-Four"


def test_polisiye_istegi(catalog_con):
    r = Retriever(catalog_con)
    res = r.retrieve(RecommendRequest(query="tırnak yediren bir polisiye"), pool=5)
    assert res.books[0]["title"] == "Murder on the Orient Express"


def test_bos_istek_gezinmeye_dusuyor(catalog_con):
    r = Retriever(catalog_con)
    res = r.retrieve(RecommendRequest(query="", genres=["klasik"]), pool=5)
    assert res.books
    assert all("klasik" in b["genres"] for b in res.books[:2])


def test_katı_mod_filtre_disini_eliyor(catalog_con):
    r = Retriever(catalog_con)
    res = r.retrieve(
        RecommendRequest(query="kitap", genres=["polisiye"], strictness=Strictness.STRICT),
        pool=10,
    )
    assert all("polisiye" in b["genres"] for b in res.books)


def test_dil_filtresi_her_zaman_sert(catalog_con):
    """Türkçe baskı istendiyse İngilizce-only kitap dönmemeli."""
    r = Retriever(catalog_con)
    res = r.retrieve(RecommendRequest(query="kitap", languages=[Language.TUR]), pool=10)
    assert res.books
    assert all("tur" in b["languages"] for b in res.books)


def test_okunanlar_dislaniyor(catalog_con):
    r = Retriever(catalog_con)
    res = r.retrieve(
        RecommendRequest(query="distopya", exclude_work_keys=["/works/OL2W"]), pool=10
    )
    assert "/works/OL2W" not in [b["work_key"] for b in res.books]


def test_benzer_kitaplar(catalog_con):
    r = Retriever(catalog_con)
    similar = r.similar("/works/OL1W", limit=3)
    assert similar
    assert all(b["work_key"] != "/works/OL1W" for b in similar)


def test_filtre_sql_parametreleri():
    clause, params = Filters(genres=["roman"], strict=True, min_rating_count=2).sql()
    assert "list_has_any" in clause
    assert ["roman"] in params


def test_turkce_islev_sozcukleri_aramadan_ayikliniyor():
    """Katalog İngilizce; Türkçe işlev sözcükleri BM25'i yanıltıyordu.

    "yas ve kayıp üzerine sakin bir roman" sorgusu, "üzerine"/"bir" gibi
    sözcükler yüzünden Türkçe akademik kitapları getiriyordu.
    """
    exp = expand("yas ve kayıp üzerine sakin bir roman")
    words = exp.content_words
    assert "üzerine" not in words and "bir" not in words and "ve" not in words
    assert "yas" not in words or "kayıp" in words  # kısa sözcükler elenir
    # İngilizce karşılıklar korunur
    assert "grief" in exp.terms or "loss" in exp.terms
    assert "üzerine" not in exp.query_text


def test_anlam_tasiyan_sozcukler_korunuyor():
    exp = expand("çölde geçen epik bir bilim kurgu romanı")
    assert "çölde" in exp.content_words       # tema olarak tanındı ama tam eşleşme değil
    assert "bir" not in exp.content_words     # işlev sözcüğü


def test_taksonomiye_cevrilen_sozcukler_bm25e_gitmiyor():
    """Tanınan tür/ruh sözcükleri İngilizce karşılığıyla aranır, ham hâliyle değil.

    "klasik" sözcüğü İngilizce katalogda yalnızca Endonezce/Malayca başlıklarla
    eşleşiyordu ("Gerbang sastra Indonesia klasik"); anlamı zaten `classic`
    terimine çevrilmiş durumda.
    """
    exp = expand("klasik bir roman")
    assert "klasik" in exp.detected_genres
    assert "klasik" not in exp.content_words
    assert any("classic" in t for t in exp.terms)

    exp2 = expand("çölde geçen epik bir bilim kurgu romanı")
    assert "bilim" not in exp2.content_words
    assert "science fiction" in exp2.terms


def test_gomme_sorgusu_ingilizceye_cevriliyor():
    """Çok dilli gömme modeli kısa metinlerde dile göre kümeliyor.

    Ham Türkçe sorgu ("yapay zekânın geleceği") Svahili/Urduca romanlara
    yakın düşüyordu; İngilizce karşılığı ise doğrudan yapay zekâ kitaplarını
    buluyor. Bu yüzden vektör aramasına yalnızca çeviri gönderilir.
    """
    exp = expand("yapay zekânın geleceği hakkında bir kitap")
    assert "artificial intelligence" in exp.dense_query
    assert "yapay" not in exp.dense_query

    # Çeviri çıkmazsa özgün metne düşülmeli (sessizce boş sorgu gönderilmesin)
    bos = expand("zzz qqq")
    assert bos.dense_query == "zzz qqq"


def test_serbest_metinden_cikarilan_tur_puana_giriyor(catalog_con):
    """Chip seçilmese bile metindeki tür/ruh hedefe girmeli (eskiden yalnızca bilinirlik)."""
    r = Retriever(catalog_con)
    res = r.retrieve(RecommendRequest(query="karanlık ve düşündürücü bir distopya"), pool=10)
    assert "distopya" in res.target.genres
    assert "karanlik" in res.target.moods or "dusundurucu" in res.target.moods

    from kitapai.matching import match_score

    by_title = {b["title"]: match_score(b, res.target) for b in res.books}
    # Distopya olan kitap, olmayandan belirgin yüksek puan almalı
    assert by_title["Nineteen Eighty-Four"] > by_title.get("Cosmos", 0.0) + 0.1


def test_kullanici_secimi_metinden_cikarilanin_onune_geciyor(catalog_con):
    r = Retriever(catalog_con)
    res = r.retrieve(RecommendRequest(query="karanlık distopya", genres=["polisiye"]), pool=10)
    assert res.target.genres == ["polisiye"]       # açık seçim, metinden çıkarılanı ezer
