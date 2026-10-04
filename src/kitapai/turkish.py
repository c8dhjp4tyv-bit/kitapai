"""Küçük Türkçe biçimbilim yardımcıları.

Şablonla üretilen eğitim verisinin "dostluk-de geçen" gibi bozuk ekler
içermemesi için ünlü uyumu ve ünsüz yumuşaması burada tek yerde çözülür.
"""

from __future__ import annotations

BACK = "aıou"
FRONT = "eiöü"
ROUND = "ouöü"
VOWELS = BACK + FRONT
HARD = "fstkçşhp"  # sert ünsüzler: ek başındaki d → t


def last_vowel(word: str) -> str:
    for ch in reversed(word.lower()):
        if ch in VOWELS:
            return ch
    return "a"


def _two_way(word: str) -> str:
    """e/a seçimi (belirtme, yönelme)."""
    return "a" if last_vowel(word) in BACK else "e"


def _four_way(word: str) -> str:
    """ı/i/u/ü seçimi."""
    v = last_vowel(word)
    if v in "aı":
        return "ı"
    if v in "ei":
        return "i"
    if v in "ou":
        return "u"
    return "ü"


SOFTEN = {"p": "b", "ç": "c", "t": "d", "k": "ğ"}


def syllables(word: str) -> int:
    """Türkçede hece sayısı ≈ ünlü sayısı."""
    return sum(1 for ch in word.lower() if ch in VOWELS)


def _soften(word: str) -> str:
    """Ünsüz yumuşaması: kitap→kitab(ı), dostluk→dostluğ(u).

    Tek heceli sözcükler kural dışıdır (at→atı, kat→katı), bu yüzden
    yalnızca çok heceliler yumuşatılır.
    """
    if syllables(word) < 2 or not word:
        return word
    last = word[-1].lower()
    if last not in SOFTEN:
        return word
    repl = SOFTEN[last]
    return word[:-1] + (repl.upper() if word[-1].isupper() else repl)


def _needs_pronominal_n(word: str) -> bool:
    """Ad tamlamasında 3. tekil iyelik ekinden sonra kaynaştırma n'si gerekir.

    "uzay yolculuğu" + -da → "uzay yolculuğunda". Tek sözcüklü adlarda bu
    durum yoktur ("sinema" + -da → "sinemada"), bu yüzden ölçüt birden fazla
    sözcük ve ünlüyle bitiş.
    """
    return " " in word.strip() and bool(word) and word.rstrip()[-1].lower() in VOWELS


def _is_proper(word: str) -> bool:
    return bool(word) and word[0].isupper()


def _sep(word: str) -> str:
    """Özel adlarda ek kesme işaretiyle ayrılır: İstanbul'da."""
    return "'" if _is_proper(word) else ""


def locative(word: str) -> str:
    """-de / -da / -te / -ta."""
    base = word.rstrip()
    if _needs_pronominal_n(base):
        return f"{base}nd{_two_way(base)}"
    cons = "t" if base and base[-1].lower() in HARD else "d"
    return f"{base}{_sep(base)}{cons}{_two_way(base)}"


def dative(word: str) -> str:
    """-e / -a (y veya n kaynaştırmasıyla)."""
    base = word.rstrip()
    if _needs_pronominal_n(base):
        return f"{base}n{_two_way(base)}"
    stem = _soften(base)
    buf = "y" if stem and stem[-1].lower() in VOWELS else ""
    return f"{stem}{_sep(stem)}{buf}{_two_way(stem)}"


def accusative(word: str) -> str:
    """-ı / -i / -u / -ü (y veya n kaynaştırmasıyla)."""
    base = word.rstrip()
    if _needs_pronominal_n(base):
        return f"{base}n{_four_way(base)}"
    stem = _soften(base)
    buf = "y" if stem and stem[-1].lower() in VOWELS else ""
    return f"{stem}{_sep(stem)}{buf}{_four_way(stem)}"


def genitive(word: str) -> str:
    """-ın / -in / -un / -ün (n kaynaştırmasıyla)."""
    base = word.rstrip()
    if _needs_pronominal_n(base):
        return f"{base}n{_four_way(base)}n"
    stem = _soften(base)
    buf = "n" if stem and stem[-1].lower() in VOWELS else ""
    return f"{stem}{_sep(stem)}{buf}{_four_way(stem)}n"


def possessive(word: str) -> str:
    """3. tekil iyelik: ad tamlamasının ikinci ögesi (korku + kitap → kitabı).

    Ünlüyle bitenlerde -sı/-si/-su/-sü, ünsüzle bitenlerde yumuşama + -ı/-i/-u/-ü.
    """
    base = word.rstrip()
    if not base:
        return base
    if base[-1].lower() in VOWELS:
        return f"{base}s{_four_way(base)}"
    stem = _soften(base)
    return f"{stem}{_four_way(stem)}"


def with_suffix(word: str, kind: str) -> str:
    return {
        "de": locative, "e": dative, "i": accusative, "in": genitive,
        "si": possessive,
    }[kind](word)


def capitalize(text: str) -> str:
    """Türkçe duyarlı baş harf büyütme.

    Python'un `str.upper()` metodu 'i' harfini 'I' yapar; Türkçede doğrusu
    'İ'dir ("içini" → "İçini", "Icini" değil).
    """
    if not text:
        return text
    first = text[0]
    mapping = {"i": "İ", "ı": "I"}
    return mapping.get(first, first.upper()) + text[1:]


def join_and(items: list[str]) -> str:
    """['a','b','c'] → 'a, b ve c'."""
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " ve " + items[-1]
