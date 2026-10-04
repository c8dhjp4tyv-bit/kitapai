"""Eğitim ve servis için TEK istem (prompt) biçimi.

Bu dosyanın varlık sebebi: eğitimde kullanılan istem ile serviste kullanılan
istem birbirinden ayrılırsa model, gördüğü şeyden farklı bir girdiyle karşılaşır
ve kalite sessizce düşer. Bu yüzden hem `dataset/` hem `serve/` buradan okur.

`PROMPT_VERSION` değişirse veri kümesi yeniden üretilmeli ve model yeniden
eğitilmelidir; `serve` yükleme sırasında adaptörün künyesiyle karşılaştırır.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import taxonomy
from .turkish import join_and

PROMPT_VERSION = "3.0"

#: Adayların istemde kaç tanesinin gösterileceği. Geri getirme daha geniş bir
#: havuz döndürür (bkz. `Settings.candidate_pool`), buraya en iyiler girer.
#:
#: Bu sayı doğrudan eğitim bağlamını belirliyor. 14 adayla örnekler ortalama
#: 2685 token tutuyordu ve 2048'lik bağlamda %99.8'i kesiliyordu — hem de
#: sondan, yani modelin öğrenmesi gereken asistan yanıtından. Aşağıdaki
#: değerler `scripts` yerine ölçümle seçildi (bkz. dataset/build.py token raporu).
PROMPT_CANDIDATES = 12

#: Aday açıklamaları bu uzunlukta kesilir — istem bütçesini korumak için.
DESCRIPTION_CHARS = 170

SYSTEM_PROMPT = """Sen kitap.ai'nin öneri motorusun.

Sana bir okurun isteği ve katalogdan gelen ADAYLAR listesi verilir. Görevin,
adaylar arasından isteğe en iyi uyanları seçmek ve her biri için okuru ikna
eden, kişisel bir gerekçe yazmaktır.

KURALLAR
1. Yalnızca ADAYLAR listesindeki kitapları seç. Listede olmayan bir kitabı
   asla önerme, uydurma.
2. Her seçimi `id` alanıyla (örn. "a3") belirt.
3. "why" alanı Türkçe, 1-3 cümle olsun ve okurun isteğindeki sözcüklere
   bağlansın. Aday bilgisi İngilizce olsa da yanıtın tamamen Türkçe olmalı.
4. Arka kapak yazısı kopyalama; kitabın okura *neden* uyduğunu anlat.
5. İstenen sayıdan fazla seçme. Gerçekten uyan aday yoksa daha az seç ve
   "followups" içinde okura netleştirici bir soru sor.
6. Hassas içerik (şiddet, yas, istismar vb.) varsa "content_notes" alanına
   kısa bir uyarı yaz.
7. Yanıtın SADECE geçerli JSON olsun. Markdown, kod bloğu, açıklama ekleme.

JSON ŞEMASI
{"picks":[{"id":"a1","why":"...","hooks":["kısa ifade"],"content_notes":[],
"confidence":0.0-1.0}],"followups":["..."]}"""


# ── Seçim / yazım ayrımı ───────────────────────────────────────────────────
# Tek model hem kitap seçip hem gerekçe yazınca, yüksek entropili serbest metin eğitim
# sinyalinin çoğunu aldı ve SEÇİM kötüleşti (Gemini gerekçeli v3: isabet 0.716 → 0.578).
# Bu yüzden iki ayrı görev, iki ayrı LoRA:
#   • SEÇ  — uzun istem (istek + aday listesi), çıktı yalnızca kimlikler (~15 token):
#            kaybın %100'ü seçim kararında.
#   • YAZ  — kısa istem (istek + yalnızca seçilen kitaplar + uyum), çıktı gerekçe.

SELECT_SYSTEM_PROMPT = """Sen kitap.ai'nin seçici modülüsün.

İSTEK ve ADAYLAR verilir. İsteğe en uygun adayları, en uygundan başlayarak seç.
Yalnızca listedeki kimlikleri kullan. İstenen sayıdan fazla seçme; gerçekten uyan
aday azsa daha az seç.
Yanıt YALNIZCA şu biçimde JSON olsun: {"ids":["a3","a1"]}"""

WRITE_SYSTEM_PROMPT = """Sen kitap.ai'nin gerekçe yazarısın.

Okurun isteği ve seçilmiş kitapların katalog bilgisi verilir. Her kitap için okura
"sen" diye hitap eden, 1-2 cümlelik doğal bir Türkçe gerekçe yaz.
Yalnızca verilen bilgiye dayan, bilgi uydurma. Kitabın "uyum"u orta ya da zayıfsa
eksiği dürüstçe söyle.
Yanıt YALNIZCA kitap başına bir satır olsun (JSON değil), kimlik + iki nokta + gerekçe:
a1: ...
a3: ..."""

#: Kitap başına çıktı bütçesi (gerekçe ort. 49, p90 58 token + kimlik öneki).
WRITE_BASE_TOKENS = 40
WRITE_TOKENS_PER_BOOK = 90


def format_write_target(items: list[tuple[str, str]]) -> str:
    """YAZ çıktısı: `[(id, gerekçe)]` → satır biçimi. Eğitim hedefi ve motor ortak kullanır.

    JSON yerine satır: çıktıdaki ek yük (anahtarlar, tırnaklar, süslü parantezler) ve
    çengeller ~%35 token'dır; üretim hızı token sayısıyla orantılı olduğundan gecikmeyi
    doğrudan düşürür. Çengeller kural tabanlı üretilir (`pipeline._template`).
    """
    return "\n".join(f"{cid}: {' '.join(why.split())}" for cid, why in items)


def build_select_messages(request_block: str, candidates: list[Candidate]) -> list[dict[str, str]]:
    """SEÇ görevi: istek + tüm adaylar → kimlikler."""
    return [
        {"role": "system", "content": SELECT_SYSTEM_PROMPT},
        {"role": "user", "content": build_user_message(request_block, candidates)},
    ]


def match_strength(confidence: float | None) -> str:
    """Kural tabanlı uyum puanını sözel dereceye çevirir (bkz. matching.match_score)."""
    c = 0.5 if confidence is None else float(confidence)
    return "güçlü" if c >= 0.75 else ("orta" if c >= 0.5 else "zayıf")


def build_write_user_message(request_block: str, books: list[tuple[str, str]]) -> str:
    """YAZ görevinin kullanıcı mesajı. `books` = [(aday bloğu, uyum derecesi)].

    Eğitimde (damıtılmış veri) ve serviste AYNI biçim kullanılır; ikisi ayrışırsa
    modelin gördüğü girdi eğitimdekinden farklı olur.
    """
    body = "\n\n".join(f"{block}\n     uyum: {strength}" for block, strength in books)
    return f"OKURUN İSTEĞİ\n{request_block}\n\nSEÇİLEN KİTAPLAR\n{body}"


def build_write_messages(request_block: str, books: list[tuple[str, str]]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": WRITE_SYSTEM_PROMPT},
        {"role": "user", "content": build_write_user_message(request_block, books)},
    ]


@dataclass(frozen=True)
class Candidate:
    """İsteme yazılacak aday. `serve` katalogdan, `dataset` veri kümesinden üretir."""

    cid: str
    work_key: str
    title: str
    authors: list[str]
    year: int | None = None
    genres: list[str] = None  # type: ignore[assignment]
    moods: list[str] = None  # type: ignore[assignment]
    subjects: list[str] = None  # type: ignore[assignment]
    description: str | None = None
    pages: int | None = None
    rating_avg: float | None = None
    rating_count: int = 0
    era: str | None = None
    title_tr: str | None = None
    languages: list[str] = None  # type: ignore[assignment]

    @classmethod
    def from_row(cls, row: dict[str, Any], cid: str) -> Candidate:
        return cls(
            cid=cid,
            work_key=row.get("work_key", ""),
            title=row.get("title", ""),
            authors=list(row.get("authors") or []),
            year=row.get("first_published"),
            genres=list(row.get("genres") or []),
            moods=list(row.get("moods") or []),
            subjects=list(row.get("subjects") or []),
            description=row.get("description"),
            pages=row.get("pages"),
            rating_avg=row.get("rating_avg"),
            rating_count=int(row.get("rating_count") or 0),
            era=row.get("era"),
            title_tr=row.get("title_tr"),
            languages=list(row.get("languages") or []),
        )


def _labels(slugs: list[str] | None, table: dict[str, taxonomy.Label]) -> str:
    if not slugs:
        return ""
    return ", ".join(table[s].label for s in slugs if s in table)


def render_candidate(c: Candidate) -> str:
    """Tek adayın istemdeki gösterimi."""
    head = f"[{c.cid}] {c.title}"
    if c.title_tr and c.title_tr.lower() != c.title.lower():
        head += f" (TR: {c.title_tr})"
    if c.authors:
        head += f" — {join_and(c.authors[:2])}"
    if c.year:
        head += f" · {c.year}"

    facts: list[str] = []
    genres = _labels(c.genres, taxonomy.GENRE_BY_SLUG)
    moods = _labels(c.moods, taxonomy.MOOD_BY_SLUG)
    if genres:
        facts.append(f"tür: {genres}")
    if moods:
        facts.append(f"ruh: {moods}")
    if c.pages:
        facts.append(f"{c.pages} sf.")
    if c.rating_avg and c.rating_count:
        facts.append(f"puan {c.rating_avg:.1f}/5 ({c.rating_count} oy)")
    if c.languages and "tur" in c.languages:
        facts.append("Türkçe baskısı var")

    lines = [head]
    if facts:
        lines.append("     " + " | ".join(facts))
    if c.subjects:
        lines.append("     konular: " + ", ".join(c.subjects[:6]))
    if c.description:
        desc = " ".join(c.description.split())
        if len(desc) > DESCRIPTION_CHARS:
            desc = desc[:DESCRIPTION_CHARS].rsplit(" ", 1)[0] + "…"
        lines.append("     özet: " + desc)
    return "\n".join(lines)


def render_candidates(candidates: list[Candidate]) -> str:
    return "\n".join(render_candidate(c) for c in candidates)


def render_request(
    *,
    query: str = "",
    genres: list[str] | None = None,
    moods: list[str] | None = None,
    era: str | None = None,
    length: str | None = None,
    audience: str | None = None,
    languages: list[str] | None = None,
    limit: int = 3,
    exclude_titles: list[str] | None = None,
) -> str:
    """Okur isteğinin istemdeki gösterimi."""
    lines: list[str] = []
    lines.append(f"Okurun sözleri: {query}" if query else "Okurun sözleri: (belirtmedi)")

    filters: list[str] = []
    if genres:
        filters.append(f"tür: {_labels(genres, taxonomy.GENRE_BY_SLUG)}")
    if moods:
        filters.append(f"ruh hali: {_labels(moods, taxonomy.MOOD_BY_SLUG)}")
    if era:
        era_label = dict((s, lab) for s, lab, _, _ in taxonomy.ERAS).get(era, era)
        filters.append(f"dönem: {era_label}")
    if length:
        len_label = dict((s, lab) for s, lab, _, _ in taxonomy.LENGTHS).get(length, length)
        filters.append(f"uzunluk: {len_label}")
    if audience:
        aud_label = dict(taxonomy.AUDIENCES).get(audience, audience)
        filters.append(f"okur: {aud_label}")
    if languages:
        filters.append("dil: " + ", ".join(languages))
    if filters:
        lines.append("Filtreler: " + " | ".join(filters))
    if exclude_titles:
        lines.append("Zaten okudu: " + join_and(exclude_titles[:5]))
    lines.append(f"İstenen öneri sayısı: {limit}")
    return "\n".join(lines)


def build_user_message(request_block: str, candidates: list[Candidate]) -> str:
    return (
        "İSTEK\n"
        f"{request_block}\n\n"
        "ADAYLAR\n"
        f"{render_candidates(candidates)}\n\n"
        "Yanıtı yalnızca JSON olarak ver."
    )


def build_messages(request_block: str, candidates: list[Candidate]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_message(request_block, candidates)},
    ]
