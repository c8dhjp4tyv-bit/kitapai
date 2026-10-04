"""Sentetik eğitim verisi üretimi."""

from __future__ import annotations

import json
import random

from kitapai.dataset import queries, themes
from kitapai.dataset.tasks import write_hooks, write_why
from kitapai.matching import match_score
from kitapai.prompting import SYSTEM_PROMPT
from kitapai.schemas import ModelOutput


def test_tema_sozlugu_ceviriyor():
    assert themes.theme_for("Science fiction") == ("bilim kurgu", "konu")
    assert themes.theme_for("Fiction, science fiction, general")[0] == "bilim kurgu"
    assert themes.theme_for("bilinmeyen konu xyz") is None


def test_icerik_uyarilari():
    notes = themes.content_notes_for(["Murder", "Violence", "Friendship"])
    assert "cinayet" in notes and "şiddet" in notes


def test_istekler_dogal_ve_tutarli(books):
    rng = random.Random(1)
    for _ in range(80):
        book = rng.choice(books)
        q = queries.generate(book, rng, anchor=rng.choice(books))
        assert q.text.strip()
        assert not q.text.startswith(" ")
        # Bozuk ek/şablon izleri kalmamalı
        assert "{" not in q.text and "}" not in q.text
        assert "  " not in q.text
        assert 1 <= q.limit <= 5
        assert q.style in {*queries.STYLES, "benzer"}


def test_gerekce_kitabin_gercek_verisine_dayaniyor(books):
    rng = random.Random(3)
    dune = next(b for b in books if b["title"] == "Dune")
    q = queries.GeneratedQuery(text="epik bilim kurgu", style="tur_ruh",
                               genres=["bilim-kurgu"], moods=["epik"])
    why = write_why(dune, q, rng)
    assert why[0].isupper()
    assert "{" not in why
    # Sayfa sayısı geçiyorsa gerçek değer olmalı
    if "sayfa" in why:
        assert "526" in why


def test_cengeller_benzersiz(books):
    rng = random.Random(5)
    for book in books:
        hooks = write_hooks(book, rng)
        assert len(hooks) == len(set(hooks))


def test_uyum_puani_kalibre(books):
    dune = next(b for b in books if b["title"] == "Dune")
    hobbit = next(b for b in books if b["title"] == "The Hobbit")
    q = queries.GeneratedQuery(text="", style="tur_ruh", genres=["bilim-kurgu"])
    assert match_score(dune, q) > match_score(hobbit, q)


def test_uretilen_ornekler_gecerli(dataset_dir):
    train = (dataset_dir / "train.jsonl").read_text(encoding="utf-8").splitlines()
    assert train

    for line in train:
        row = json.loads(line)
        messages = row["messages"]
        assert [m["role"] for m in messages] == ["system", "user", "assistant"]
        assert messages[0]["content"] == SYSTEM_PROMPT

        # Hedef geçerli JSON ve şemaya uygun olmalı
        target = ModelOutput.model_validate_json(messages[2]["content"])
        assert target.picks

        # Seçilen her kimlik aday listesinde bulunmalı
        user = messages[1]["content"]
        for pick in target.picks:
            assert f"[{pick.id}]" in user
            assert pick.why.strip()
            assert 0.0 <= pick.confidence <= 1.0

        # İstenen sayıdan fazla öneri olmamalı
        assert len(target.picks) <= row["meta"]["limit"]


def test_istatistik_dosyasi(dataset_dir):
    stats = json.loads((dataset_dir / "stats.json").read_text(encoding="utf-8"))
    assert stats["total"] > 0
    assert stats["train"] + stats["valid"] == stats["total"]
    assert stats["by_style"]


# ── tohum kitap kalitesi ────────────────────────────────────────────────────
# Eskiden tohum kitap denetlenmiyordu: "sorgulatan bir kitap" için amfibi rehberi,
# "Amerika'da geçen hikâye" için ev sigortası kitabı doğru cevap sayılıyordu.


def test_tohum_kitap_kendi_istegine_uyuyor(dataset_dir):
    """İlk seçim (tohum) her örnekte `min_seed_score` üstünde güven taşımalı."""
    from kitapai.dataset.build import DatasetOptions

    floor = DatasetOptions().min_seed_score
    rows = [json.loads(line) for line in
            (dataset_dir / "train.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows
    for row in rows:
        first = json.loads(row["messages"][2]["content"])["picks"][0]
        assert first["confidence"] >= floor - 0.011, (row["meta"]["query"], first["confidence"])


def test_bilgisiz_ve_taninmayan_kitap_cevap_olamaz():
    from kitapai.dataset.build import DatasetOptions, _informative

    opt = DatasetOptions()
    assert not _informative({"readers": 3, "subjects": ["a", "b"], "description": "x" * 100}, opt)
    assert not _informative({"readers": 500, "subjects": ["a"], "description": None}, opt)
    assert _informative({"readers": 500, "subjects": ["a", "b"], "description": None}, opt)
    assert _informative({"readers": 40, "subjects": [], "description": "x" * 80}, opt)


def test_benzer_istegin_cevabi_referansla_iliskili(books):
    """"X gibi" isteğinin cevabı X ile aynı ayırt edici türden olmalı, X'in kendisi olmamalı."""
    from kitapai.dataset.build import GENERIC_GENRES, BookPool, DatasetOptions, _related_seed

    pool = BookPool(books)
    anchor = next(b for b in books if b["title"] == "Dune")
    opt = DatasetOptions(min_seed_readers=0)
    for seed in range(20):
        found = _related_seed(pool, anchor, random.Random(seed), opt)
        if found is None:      # mini katalogda bazı türler çok küçük
            continue
        book, genre = found
        assert book["work_key"] != anchor["work_key"]
        assert genre in book["genres"] and genre in anchor["genres"]
        assert genre not in GENERIC_GENRES or set(anchor["genres"]) <= GENERIC_GENRES
