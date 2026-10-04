"""Türkçe ek yardımcıları."""

from __future__ import annotations

import pytest

from kitapai.turkish import (
    accusative,
    capitalize,
    dative,
    genitive,
    join_and,
    locative,
    possessive,
)


@pytest.mark.parametrize("word,expected", [
    ("çöl", "çölde"), ("kitap", "kitapta"), ("okul", "okulda"),
    ("İstanbul", "İstanbul'da"), ("Londra", "Londra'da"),
    ("uzay yolculuğu", "uzay yolculuğunda"),   # ad tamlaması → kaynaştırma n'si
    ("ruh sağlığı", "ruh sağlığında"),
])
def test_bulunma_hali(word, expected):
    assert locative(word) == expected


@pytest.mark.parametrize("word,expected", [
    ("kitap", "kitaba"), ("dostluk", "dostluğa"), ("çöl", "çöle"),
    ("at", "ata"),                              # tek heceli: yumuşama yok
    ("sinema", "sinemaya"),
])
def test_yonelme_hali_ve_yumusama(word, expected):
    assert dative(word) == expected


def test_belirtme_ve_tamlayan():
    assert accusative("kitap") == "kitabı"
    assert genitive("dostluk") == "dostluğun"
    assert accusative("hayatın anlamı") == "hayatın anlamını"


def test_iyelik():
    assert possessive("kitap") == "kitabı"
    assert possessive("roman") == "romanı"
    assert possessive("okuma") == "okuması"


def test_buyuk_harf_turkce():
    assert capitalize("içini ısıtan") == "İçini ısıtan"
    assert capitalize("ılık") == "Ilık"
    assert capitalize("") == ""


def test_ve_ile_birlestirme():
    assert join_and(["a"]) == "a"
    assert join_and(["a", "b"]) == "a ve b"
    assert join_and(["a", "b", "c"]) == "a, b ve c"
    assert join_and([]) == ""
