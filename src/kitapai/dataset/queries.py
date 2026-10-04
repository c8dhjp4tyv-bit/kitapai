"""Katalog kayıtlarından sentetik Türkçe okur isteği üretir.

Eğitim verisinin girdisi gerçek kullanıcı cümlelerine benzemek zorunda. Gerçek
kullanıcılar "Tür: Bilim Kurgu" yazmaz; "uzayda geçen ama ağır olmayan bir şey"
yazar. Bu modül, bir kitabın nitelikleriyle tutarlı ama *doğal* istekler üretir.

Kalıp bankası yedi biçeme ayrılmıştır (tür/ruh, tema, durum, benzerlik, kısıt,
belirsiz, olumsuz). Her biçem farklı bir gerçek kullanım kalıbını temsil eder;
`build.py` bunları oranlayarak karıştırır.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from .. import taxonomy
from ..turkish import capitalize, dative, join_and, locative
from . import themes

# ── Sözcük bankaları ───────────────────────────────────────────────────────

MOOD_ADJECTIVES: dict[str, tuple[str, ...]] = {
    "heyecanli": ("tempolu", "sürükleyici", "adrenalin dolu", "soluksuz okunan"),
    "dusundurucu": ("düşündürücü", "kafa açan", "sorgulatan", "zihin açıcı"),
    "karanlik": ("karanlık", "ağır", "kasvetli", "rahatsız edici"),
    "romantik": ("romantik", "aşk dolu", "kalbi kıpırdatan"),
    "komik": ("komik", "güldüren", "eğlenceli", "keyifli"),
    "sakinlestirici": ("sakinleştirici", "huzur veren", "yavaş tempolu", "dingin"),
    "ilham-verici": ("ilham verici", "motive eden", "harekete geçiren"),
    "melankolik": ("melankolik", "hüzünlü", "içe işleyen", "buruk"),
    "gerilimli": ("gerilimli", "tırnak yediren", "nefes kesen"),
    "sicak": ("sıcacık", "içini ısıtan", "samimi"),
    "epik": ("epik", "destansı", "geniş soluklu"),
    "gizemli": ("gizemli", "merak uyandıran", "bilmece gibi"),
    "umutlu": ("umut veren", "iyi hissettiren", "moral veren"),
    "maceraci": ("maceralı", "insanı yola çıkaran", "keşif dolu"),
}

BOOK_WORDS = ("kitap", "roman", "şey", "okuma")

SITUATIONS = (
    "tatilde okumak için",
    "uzun bir uçak yolculuğu için",
    "uykudan önce birkaç sayfa okumak için",
    "metroda okumak için",
    "hafta sonu tek oturuşta bitirmek için",
    "zor bir dönemden geçiyorum, dağılmak için",
    "uzun zamandır kitap okumuyorum, tekrar başlamak için",
    "okuma alışkanlığımı geri kazanmak için",
    "kış akşamlarına uygun",
    "kafamı dağıtmak için",
    "yeni bir şeyler denemek istiyorum",
    "arkadaşıma hediye edeceğim",
    "kitap kulübünde tartışmak için",
)

OPENERS = (
    "", "", "",  # çoğu zaman girişsiz — kullanıcılar kısa yazar
    "Merhaba, ", "Selam, ", "Şöyle bir şey arıyorum: ",
)

CLOSERS = (
    "", "", "", "", " önerir misin?", " ne önerirsin?", " bir şeyler var mı?",
    " öneri alabilir miyim?",
)


@dataclass
class GeneratedQuery:
    """Üretilmiş istek + ondan türeyen yapısal filtreler."""

    text: str
    style: str
    genres: list[str] = field(default_factory=list)
    moods: list[str] = field(default_factory=list)
    era: str | None = None
    length: str | None = None
    audience: str | None = None
    languages: list[str] = field(default_factory=list)
    limit: int = 3
    #: Bu isteğin hangi niteliklerin *zorunlu* olduğunu belirtir; sert
    #: olumsuz örnek üretiminde ve değerlendirmede kullanılır.
    hard_constraints: dict[str, Any] = field(default_factory=dict)


def _genre_label(slug: str) -> str:
    """Cümlede doğal duran tür adı ("maneviyat kitabı", "bilim kurgu romanı")."""
    return taxonomy.genre_noun(slug)


def _mood_adj(slug: str, rng: random.Random) -> str:
    return rng.choice(MOOD_ADJECTIVES.get(slug, (slug,)))


def _pick_theme(book: dict, rng: random.Random, kind: str | None = None) -> tuple[str, str] | None:
    found = themes.themes_for(list(book.get("subjects") or []), limit=8)
    if kind:
        found = [t for t in found if t[1] == kind] or found
    return rng.choice(found) if found else None


# ── Biçemler ───────────────────────────────────────────────────────────────


def _style_tur_ruh(book: dict, rng: random.Random) -> GeneratedQuery:
    """Tür + ruh hali: en doğrudan istek biçimi."""
    genres = list(book.get("genres") or [])
    moods = list(book.get("moods") or [])
    g = rng.choice(genres) if genres else None
    m = rng.choice(moods) if moods else None
    word = rng.choice(BOOK_WORDS)

    if g and m:
        text = rng.choice([
            f"{_mood_adj(m, rng)} bir {_genre_label(g)}",
            f"{_mood_adj(m, rng)} bir {_genre_label(g)} arıyorum",
            f"Canım {_mood_adj(m, rng)} bir {_genre_label(g)} okumak istiyor",
            f"{_genre_label(g)} seviyorum ama {_mood_adj(m, rng)} olsun",
        ])
    elif g:
        text = rng.choice([
            f"İyi bir {_genre_label(g)} arıyorum",
            f"{_genre_label(g)} okumak istiyorum",
            f"Hiç {_genre_label(g)} okumadım, nereden başlamalıyım",
        ])
    else:
        text = f"{_mood_adj(m or 'dusundurucu', rng)} bir {word}"  # noqa: RUF100

    return GeneratedQuery(
        text=text, style="tur_ruh",
        genres=[g] if g and rng.random() < 0.75 else [],
        moods=[m] if m and rng.random() < 0.6 else [],
    )


def _style_tema(book: dict, rng: random.Random) -> GeneratedQuery:
    """Konu odaklı istek — kullanıcı ne hakkında okumak istediğini söyler."""
    theme = _pick_theme(book, rng)
    if not theme:
        return _style_tur_ruh(book, rng)
    name, kind = theme
    moods = list(book.get("moods") or [])
    m = rng.choice(moods) if moods and rng.random() < 0.6 else None
    adj = f"{_mood_adj(m, rng)} " if m else ""

    if kind == "mekan":
        text = rng.choice([
            f"{locative(name)} geçen {adj}bir roman",
            f"{locative(name)} geçen bir hikâye okumak istiyorum",
            f"Beni {dative(name)} götürecek bir kitap",
        ])
    elif kind == "figur":
        text = rng.choice([
            f"{name} hakkında {adj}bir kitap",
            f"Başrolünde {name} olan bir roman",
            f"{name} anlatan bir şey",
        ])
    else:
        text = rng.choice([
            f"{name} üzerine {adj}bir kitap",
            f"{name} temalı {adj}bir roman",
            f"{name} hakkında bir şeyler okumak istiyorum",
            f"Konusu {name} olan {adj}bir kitap arıyorum",
            f"{name} ilgimi çekiyor, bu konuda ne okumalıyım",
        ])

    return GeneratedQuery(
        text=text, style="tema",
        moods=[m] if m and rng.random() < 0.4 else [],
        genres=list(book.get("genres") or [])[:1] if rng.random() < 0.25 else [],
    )


def _style_durum(book: dict, rng: random.Random) -> GeneratedQuery:
    """Bağlam odaklı istek — gerçek kullanıcıların en sık yazdığı biçim."""
    moods = list(book.get("moods") or [])
    m = rng.choice(moods) if moods else "sakinlestirici"
    sit = rng.choice(SITUATIONS)
    genres = list(book.get("genres") or [])
    g = rng.choice(genres) if genres and rng.random() < 0.5 else None

    parts = [sit, f"{_mood_adj(m, rng)} bir {rng.choice(BOOK_WORDS)}"]
    if g:
        parts.append(f"tercihen {_genre_label(g)}")
    text = ", ".join(parts)

    length = book.get("length_bucket") if rng.random() < 0.35 else None
    return GeneratedQuery(
        text=text, style="durum",
        moods=[m] if rng.random() < 0.5 else [],
        genres=[g] if g and rng.random() < 0.4 else [],
        length=length,
        hard_constraints={"length": length} if length else {},
    )


def _style_benzer(book: dict, rng: random.Random, anchor: dict | None = None) -> GeneratedQuery:
    """'X gibi bir şey' — benzerlik isteği. `anchor` referans kitaptır."""
    if not anchor:
        return _style_tur_ruh(book, rng)
    title = anchor.get("title_tr") or anchor.get("title") or ""
    authors = list(anchor.get("authors") or [])
    author = authors[0] if authors else None

    options = [
        f"{title} çok hoşuma gitti, benzeri var mı",
        f"{title} gibi bir kitap arıyorum",
        f"{title} okudum, şimdi ne okumalıyım",
    ]
    if author:
        options += [
            f"{author} tarzı yazarlar",
            f"{author} sevenler başka ne okur",
        ]
    return GeneratedQuery(
        text=rng.choice(options), style="benzer",
        genres=list(anchor.get("genres") or [])[:1] if rng.random() < 0.3 else [],
    )


def _style_kisit(book: dict, rng: random.Random) -> GeneratedQuery:
    """Sert kısıt: uzunluk, dil, dönem, okur kitlesi."""
    q = GeneratedQuery(text="", style="kisit")
    genres = list(book.get("genres") or [])
    if genres:
        g = rng.choice(genres)
        subject = f"bir {_genre_label(g)}"
        q.genres = [g]
    else:
        subject = f"bir {rng.choice(BOOK_WORDS)}"

    choice = rng.choice(["uzunluk", "dil", "donem", "okur"])
    if choice == "uzunluk":
        bucket = book.get("length_bucket") or "kisa"
        clause = {
            "kisa": "ama 200 sayfayı geçmesin",
            "orta": "ama çok uzun olmasın",
            "uzun": "uzun ve doyurucu olsun",
            "tugla": "kalın olsun, uzun süre yetsin",
        }[bucket]
        q.length = bucket
        q.hard_constraints["length"] = bucket
    elif choice == "dil":
        clause = rng.choice(["ama Türkçesi olsun", "Türkçe çevirisi olan"])
        q.languages = ["tur"]
        q.hard_constraints["language"] = "tur"
    elif choice == "donem":
        era = book.get("era") or "cagdas"
        clause = {
            "klasik": "klasiklerden olsun",
            "modern": "20. yüzyıldan olsun",
            "cagdas": "yeni tarihli olsun",
        }[era]
        q.era = era
        q.hard_constraints["era"] = era
    else:
        aud = book.get("audience") or "yetiskin"
        clause = {
            "cocuk": "çocuğuma okuyacağım",
            "genc": "lise çağındaki yeğenim için",
            "yetiskin": "yetişkin bir okur için",
        }[aud]
        q.audience = aud
        q.hard_constraints["audience"] = aud

    q.text = rng.choice([
        f"{subject} istiyorum, {clause}",
        f"{subject} arıyorum, {clause}",
        f"{capitalize(clause.removeprefix('ama '))} {subject}",
    ])
    return q


def _style_belirsiz(book: dict, rng: random.Random) -> GeneratedQuery:
    """Kullanıcı ne istediğini bilmiyor — modelin soru sormayı öğrendiği yer."""
    q = GeneratedQuery(
        text=rng.choice([
            "ne okuyacağımı bilmiyorum",
            "canım kitap okumak istiyor ama ne olduğuna karar veremedim",
            "iyi bir şeyler öner",
            "sürpriz olsun, sen seç",
            "son zamanlarda okuduğum hiçbir şey tatmin etmedi",
        ]),
        style="belirsiz",
    )
    if rng.random() < 0.5 and book.get("genres"):
        q.genres = [book["genres"][0]]
    return q


def _style_olumsuz(book: dict, rng: random.Random) -> GeneratedQuery:
    """Olumsuz kısıt — 'şu olmasın'. Model istenmeyeni elemeyi öğrenir."""
    moods = list(book.get("moods") or [])
    m = rng.choice(moods) if moods else "umutlu"
    avoid = rng.choice([
        "ağır olmasın", "çok karanlık olmasın", "aşk romanı olmasın",
        "şiddet içermesin", "hüzünlü bitmesin", "akademik dille yazılmış olmasın",
        "çok kalın olmasın",
    ])
    genres = list(book.get("genres") or [])
    g = rng.choice(genres) if genres else None
    base = f"{_mood_adj(m, rng)} bir {_genre_label(g)}" if g else f"{_mood_adj(m, rng)} bir kitap"
    return GeneratedQuery(
        text=f"{base} olsun ama {avoid}",
        style="olumsuz",
        moods=[m] if rng.random() < 0.5 else [],
        genres=[g] if g and rng.random() < 0.5 else [],
    )


STYLES = {
    "tur_ruh": _style_tur_ruh,
    "tema": _style_tema,
    "durum": _style_durum,
    "kisit": _style_kisit,
    "belirsiz": _style_belirsiz,
    "olumsuz": _style_olumsuz,
}

#: `build.py` için varsayılan karışım. Gerçek kullanımda tema ve durum
#: istekleri baskın olduğu için ağırlıkları yüksek.
DEFAULT_MIX: dict[str, float] = {
    "tema": 0.28,
    "tur_ruh": 0.22,
    "durum": 0.20,
    "benzer": 0.12,
    "kisit": 0.10,
    "olumsuz": 0.05,
    "belirsiz": 0.03,
}


def generate(
    book: dict,
    rng: random.Random,
    *,
    style: str | None = None,
    anchor: dict | None = None,
) -> GeneratedQuery:
    """Bir kitaba uygun sentetik istek üretir."""
    if style == "benzer" or (style is None and anchor is not None and rng.random() < 0.2):
        q = _style_benzer(book, rng, anchor)
    else:
        name = style or rng.choices(
            list(DEFAULT_MIX), weights=list(DEFAULT_MIX.values())
        )[0]
        q = _style_benzer(book, rng, anchor) if name == "benzer" else STYLES[name](book, rng)

    closer = rng.choice(CLOSERS)
    # Metin zaten soru hâlindeyse ikinci bir soru eki cümleyi bozar
    # ("benzeri var mı önerir misin?").
    if any(q.text.rstrip().endswith(s) for s in ("mı", "mi", "mu", "mü", "?", "misin", "mısın")):
        closer = ""
    q.text = (rng.choice(OPENERS) + q.text + closer).strip()
    q.limit = rng.choices([2, 3, 4, 5], weights=[0.15, 0.55, 0.2, 0.1])[0]
    return q


def summarize_mix(queries: list[GeneratedQuery]) -> dict[str, int]:
    out: dict[str, int] = {}
    for q in queries:
        out[q.style] = out.get(q.style, 0) + 1
    return out


__all__ = ["DEFAULT_MIX", "STYLES", "GeneratedQuery", "generate", "join_and", "summarize_mix"]
