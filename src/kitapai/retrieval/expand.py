"""Türkçe isteği katalogda arayabilecek hâle getirir.

Open Library meta verisi İngilizcedir; kullanıcı Türkçe yazar. Sözcüksel arama
bu boşlukta işe yaramaz ("karanlık distopya" hiçbir konuyla eşleşmez). Burada
istek metni, taksonomi ve tema sözlüğü üzerinden İngilizce arama terimlerine
genişletilir. Yan fayda: kullanıcı hiç filtre seçmese bile metninden tür ve
ruh hali çıkarılır.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

from .. import taxonomy
from ..dataset import themes
from ..dataset.queries import MOOD_ADJECTIVES

#: BM25 sorgusundan atılacak Türkçe işlev sözcükleri. Katalog metni İngilizce
#: olduğu ve FTS indeksi İngilizce stopword listesiyle kurulduğu için bu
#: sözcükler indekste "anlamlı terim" sayılıyor ve Türkçe başlıklarla
#: eşleşiyordu: "yas ve kayıp ÜZERİNE sakin BİR roman" sorgusu Türkçe akademik
#: kitapları getiriyordu. Tür/ruh tespiti özgün metin üzerinde yapıldığı için
#: bu ayıklama yalnızca arama terimlerini etkiler.
TURKISH_STOPWORDS: frozenset[str] = frozenset({
    "acaba", "ait", "ama", "ancak", "arıyorum", "ayrıca", "bana", "bazı", "beni", "benim",
    "bir", "bu", "bütün", "da", "daha", "de", "değil", "diye", "en", "fakat", "gibi",
    "göre", "hakkında", "hatta", "hem", "her", "hiç", "ile", "ise", "isterim", "istiyorum",
    "için", "kadar", "kendi", "ki", "lütfen", "merhaba", "mi", "misin", "mu", "musun",
    "mü", "mı", "mısın", "ne", "o", "okudum", "okumak", "okuyacağım", "olan", "olarak",
    "sadece", "sana", "selam", "sen", "senin", "sonra", "tüm", "var", "ve", "veya", "ya",
    "yalnızca", "yani", "yok", "zaten", "çok", "önce", "öner", "önerin", "önerir",
    "üzerinde", "üzerine", "şey", "şeyler", "şu"
})

# Regex desenlerinden düz sözcükleri çıkarmak için: sadece harf, boşluk ve
# \b içeren desenler güvenle anahtar sözcüğe çevrilebilir.
# Desenin BAŞINDAKİ düz sözcük dizisini alır. Tam eşleşme aramak yetmiyordu:
# `\bclassic(s|al literature)?\b` gibi opsiyonel grup içeren desenler tamamen
# atlanıyor ve türün en önemli anahtar sözcüğü ("classic") arama terimlerine
# hiç girmiyordu.
_LITERAL = re.compile(r"^(?:\\b)?([a-z][a-z \-']*[a-z])")


@lru_cache(maxsize=1)
def _label_keywords() -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Tür/ruh slug'ı → İngilizce anahtar sözcükler."""
    genres: dict[str, list[str]] = {}
    moods: dict[str, list[str]] = {}
    for table, target in ((taxonomy.GENRES, genres), (taxonomy.MOODS, moods)):
        for lab in table:
            words = []
            for pattern in lab.patterns:
                m = _LITERAL.match(pattern)
                if m:
                    words.append(m.group(1))
            target[lab.slug] = words[:4]
    return genres, moods


@lru_cache(maxsize=1)
def _theme_reverse() -> dict[str, str]:
    """Türkçe tema → İngilizce Open Library konusu."""
    out: dict[str, str] = {}
    for subject, (tr_name, _kind) in themes.THEMES.items():
        out.setdefault(tr_name.lower(), subject)
    return out


@lru_cache(maxsize=1)
def _mood_adjective_index() -> dict[str, str]:
    """Türkçe sıfat → ruh hali slug'ı."""
    out: dict[str, str] = {}
    for slug, adjectives in MOOD_ADJECTIVES.items():
        for adj in adjectives:
            out[adj.lower()] = slug
        label = taxonomy.MOOD_BY_SLUG.get(slug)
        if label:
            out[label.label.lower()] = slug
    return out


@lru_cache(maxsize=1)
def _genre_name_index() -> dict[str, str]:
    """Türkçe tür adı → slug."""
    out: dict[str, str] = {}
    for lab in taxonomy.GENRES:
        out[lab.label.lower()] = lab.slug
        out[taxonomy.genre_noun(lab.slug).lower()] = lab.slug
        out[lab.slug.replace("-", " ")] = lab.slug
    return out


def _mentions(needle: str, haystack: str) -> bool:
    """`needle` sözcük başında geçiyor mu? (Türkçe ekleri tolere eder.)

    "çöl" → "çölde", "dostluk" → "dostluğa" eşleşir; ama "din" sözcüğü
    "dinlenmek" içinde sözcük başında olduğu için kaçınılmaz bir miktar gürültü
    kalır — sıralama bunu zaten telafi eder.
    """
    return re.search(r"(?:^|[\s,.;:!?()\-])" + re.escape(needle), haystack) is not None


def _fold(text: str) -> str:
    """Türkçe harfleri sadeleştirip küçük harfe indirger (eşleşme toleransı)."""
    table = str.maketrans("âîûÂÎÛ", "aiuAIU")
    return text.translate(table).lower()


@dataclass
class Expansion:
    """Genişletilmiş arama isteği."""

    original: str
    terms: list[str] = field(default_factory=list)          # İngilizce arama terimleri
    detected_genres: list[str] = field(default_factory=list)
    detected_moods: list[str] = field(default_factory=list)
    detected_themes: list[str] = field(default_factory=list)
    #: Taksonomi/tema olarak tanınıp İngilizce karşılığa çevrilmiş sözcükler.
    #: Bunlar BM25'e ham hâliyle gönderilmez: "klasik" sözcüğü İngilizce
    #: katalogda yalnızca Endonezce/Malayca başlıklarla eşleşiyordu
    #: ("Gerbang sastra Indonesia klasik"), oysa anlamı zaten `classic`
    #: terimine çevrilmiş durumda.
    consumed: set[str] = field(default_factory=set)

    @property
    def content_words(self) -> list[str]:
        """Özgün metinden işlev sözcükleri ayıklanmış hâli."""
        return [
            w for w in re.findall(r"[\w'’]+", self.original.lower(), re.UNICODE)
            if w not in TURKISH_STOPWORDS and len(w) > 2 and w not in self.consumed
        ]

    @property
    def dense_query(self) -> str:
        """Gömme aramasına verilecek metin: YALNIZCA İngilizce terimler.

        Çok dilli gömme modeli kısa metinlerde anlamdan çok *dile* göre
        kümeliyor: "yapay zekânın geleceği" sorgusu Svahili/Urduca romanları
        getiriyordu (skor 0.83), oysa aynı anlamın İngilizcesi "artificial
        intelligence future" doğrudan AI 2041 ve Our final invention'ı buluyor
        (skor 0.88). Özgün Türkçe metni terimlere EKLEMEK de sonucu bozuyor —
        vektör yine dil kümesine çekiliyor. Bu yüzden yalnızca çeviri
        gönderilir; çeviri çıkmazsa özgün metne düşülür.
        """
        return " ".join(self.terms) or self.original

    @property
    def query_text(self) -> str:
        """BM25'e verilecek metin: anlam taşıyan sözcükler + İngilizce karşılıklar."""
        return " ".join([*self.content_words, *self.terms]).strip()


def expand(
    text: str,
    *,
    genres: list[str] | None = None,
    moods: list[str] | None = None,
) -> Expansion:
    """İsteği İngilizce terimlerle genişletir ve örtük filtreleri çıkarır."""
    folded = _fold(text or "")
    exp = Expansion(original=text or "")
    genre_kw, mood_kw = _label_keywords()

    # 1) Metinde geçen Türkçe temalar → İngilizce konu adları
    for tr_name, subject in _theme_reverse().items():
        if len(tr_name) >= 3 and _mentions(_fold(tr_name), folded):
            exp.terms.append(subject)
            exp.detected_themes.append(tr_name)
            exp.consumed.update(_fold(tr_name).split())

    # 2) Metinde geçen tür adları
    for name, slug in _genre_name_index().items():
        if len(name) >= 4 and _mentions(_fold(name), folded) and slug not in exp.detected_genres:
            exp.detected_genres.append(slug)
            exp.consumed.update(_fold(name).split())

    # 3) Metinde geçen ruh hali sıfatları
    for adj, slug in _mood_adjective_index().items():
        if len(adj) >= 4 and _mentions(_fold(adj), folded) and slug not in exp.detected_moods:
            exp.detected_moods.append(slug)
            exp.consumed.update(_fold(adj).split())

    # 4) Açıkça seçilmiş filtreler de terimlere katkı verir
    for slug in [*(genres or []), *exp.detected_genres]:
        exp.terms.extend(genre_kw.get(slug, []))
    for slug in [*(moods or []), *exp.detected_moods]:
        exp.terms.extend(mood_kw.get(slug, []))

    # Benzersizleştir, sırayı koru
    seen: set[str] = set()
    exp.terms = [t for t in exp.terms if not (t in seen or seen.add(t))][:24]
    return exp
