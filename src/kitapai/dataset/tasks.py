"""Eğitim örneği üretimi: aday havuzu, hedef JSON ve Türkçe gerekçe.

Tasarımın özü: model *meta veri* üretmez, *seçim* ve *gerekçe* üretir. Bu
yüzden her örnekte adaylar gerçek katalogdan gelir, hedef yanıt da yalnızca
`id` referansları ve Türkçe metin içerir. Böylece eğitim, serviste
doğrulanabilen bir davranışı öğretir.

Zor olumsuz örnekler (hard negatives) bilinçli olarak eklenir: aynı türden ama
yanlış ruh halinde, doğru ruh halinde ama yanlış türde, ya da kısıtı ihlal eden
kitaplar. Model "listedeki her şey uyar" kısayolunu öğrenemesin diye.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from typing import Any

from .. import taxonomy
from ..matching import match_reasons, match_score
from ..prompting import PROMPT_CANDIDATES, Candidate, build_messages, render_request
from ..turkish import capitalize, join_and, locative
from . import themes
from .queries import MOOD_ADJECTIVES, GeneratedQuery

# ── Gerekçe (why) bileşenleri ──────────────────────────────────────────────

BRIDGES_MOOD = (
    "{adj} bir şey istediğin için",
    "{adj} bir okuma arıyorsan",
    "Aradığın {adj} ton burada var:",
    "{adj} olmasını istemiştin;",
)
BRIDGES_THEME = (
    "{theme} ilgini çekiyorsa",
    "{theme} üzerine okumak istiyordun;",
    "Tam olarak {theme} anlatıyor:",
)
BRIDGES_PLAIN = (
    "Listede en çok buna yakınsın:",
    "İsteğine en iyi oturan kitap bu:",
    "Bunu kaçırma:",
    "",
    "",
)

CORE_FRAMES = (
    "{title}, {themes} etrafında dönen bir {genre}.",
    "{title} {themes} anlatıyor.",
    "{title}, {genre} olarak {themes} işliyor.",
    "{title} {themes} üzerine kurulu.",
)
CORE_NO_THEME = (
    "{title} tam anlamıyla bir {genre}.",
    "{title}, türünün güçlü örneklerinden.",
    "{title} bu isteğe uyan nadir kitaplardan.",
)

EVIDENCE_MOOD = (
    "Tonu {adj}, sürükleyiciliği düşürmeden.",
    "Anlatı boyunca {adj} bir hava korunuyor.",
    "{adj} yanı baştan sona hissediliyor.",
)
EVIDENCE_ERA = {
    "klasik": (
        "{year} tarihli olmasına rağmen dili bugün de taze.",
        "Klasik demek istediğin şey tam olarak bu: {year}.",
    ),
    "modern": (
        "{year} tarihli; türün kalıplarını kuran kitaplardan.",
        "{year} basımı, hâlâ referans gösteriliyor.",
    ),
    "cagdas": (
        "{year} tarihli, yani dili ve dünyası sana yakın.",
        "Yakın tarihli ({year}) olduğu için bugünün okuruna daha kolay geliyor.",
    ),
}
EVIDENCE_LENGTH = {
    "kisa": "{pages} sayfa — bir hafta sonunda biter.",
    "orta": "{pages} sayfayla ne fazla uzun ne de aceleye gelmiş.",
    "uzun": "{pages} sayfa; içine yerleşip kalmak isteyenler için.",
    "tugla": "{pages} sayfalık hacmiyle uzun bir yolculuk.",
}
EVIDENCE_RATING = (
    "Open Library'de {count} okur puanlamış, ortalama {avg}/5.",
    "{count} okurun ortalama {avg} verdiği bir kitap.",
)
EVIDENCE_TR = (
    "Türkçe baskısı da var.",
    "Türkçeye çevrildi, bulması kolay.",
)

CLOSERS = (
    "", "", "",
    "Beklentini karşılamazsa şaşırırım.",
    "Bu listeden ilk bunu denemeni öneririm.",
)

FOLLOWUPS = (
    "Daha kısa bir şey ister misin?",
    "Aynı türde devam edelim mi, yoksa tamamen farklı bir şey mi?",
    "Bunlardan birini okuduysan söyle, listeyi yenileyeyim.",
    "Türkçe baskısı olanlarla sınırlayayım mı?",
    "Daha hafif bir tona geçmemi ister misin?",
    "Hangi dönemden okumayı seversin: klasikler mi, yeni tarihliler mi?",
    "Sesli kitap olarak da arıyorsan belirt, ona göre seçeyim.",
)

FOLLOWUPS_VAGUE = (
    "Son beğendiğin kitabı söylersen çok daha isabetli seçebilirim.",
    "Nasıl bir ruh hâlindesin: dağılmak mı, düşünmek mi istiyorsun?",
    "Kalın kitaplardan kaçar mısın, yoksa uzun olması sorun değil mi?",
)


# ── Gerekçe metni ──────────────────────────────────────────────────────────


def _theme_phrase(
    book: dict, rng: random.Random, n: int = 2, *, avoid: str = ""
) -> str:
    """Kitabın Türkçe temalarından kısa bir öbek.

    `avoid` tür adını dışarıda bırakır; aksi hâlde "bilim kurgu romanı olarak
    bilim kurgu ... işliyor" gibi kendini tekrar eden cümleler çıkıyor.
    """
    found = [
        t[0] for t in themes.themes_for(list(book.get("subjects") or []), limit=6)
        if not (avoid and (t[0] in avoid or avoid in t[0]))
    ]
    if not found:
        return ""
    rng.shuffle(found)
    return join_and(found[:n])


def write_why(book: dict, q: GeneratedQuery, rng: random.Random) -> str:
    """Kitabın gerçek nitelikleriyle sınırlı, isteğe bağlanan Türkçe gerekçe.

    Hiçbir olay örgüsü uydurulmaz: yalnızca konular, tür, dönem, sayfa sayısı,
    puan ve dil bilgisi kullanılır.
    """
    title = book.get("title_tr") or book.get("title") or ""
    genres = list(book.get("genres") or [])
    genre_noun = taxonomy.genre_noun(genres[0]) if genres else "kitap"
    theme_text = _theme_phrase(book, rng, avoid=genre_noun)

    shared_mood = list(set(q.moods) & set(book.get("moods") or []))
    mood = shared_mood[0] if shared_mood else (
        (book.get("moods") or [None])[0] if book.get("moods") else None
    )
    adj = rng.choice(MOOD_ADJECTIVES.get(mood, ("etkileyici",))) if mood else "etkileyici"

    # 1) Köprü
    roll = rng.random()
    if shared_mood and roll < 0.45:
        bridge = rng.choice(BRIDGES_MOOD).format(adj=adj)
    elif theme_text and roll < 0.7:
        bridge = rng.choice(BRIDGES_THEME).format(theme=theme_text.split(" ve ")[0])
    else:
        bridge = rng.choice(BRIDGES_PLAIN)

    # 2) Çekirdek
    if theme_text:
        core = rng.choice(CORE_FRAMES).format(
            title=title, themes=theme_text, genre=genre_noun)
    else:
        core = rng.choice(CORE_NO_THEME).format(title=title, genre=genre_noun)

    # 3) Kanıt — yalnızca gerçekten var olan veriden
    evidence: list[str] = []
    pool: list[str] = []
    if mood:
        pool.append(rng.choice(EVIDENCE_MOOD).format(adj=adj))
    year, era = book.get("first_published"), book.get("era")
    if year and era in EVIDENCE_ERA:
        pool.append(rng.choice(EVIDENCE_ERA[era]).format(year=year))
    pages, bucket = book.get("pages"), book.get("length_bucket")
    if pages and bucket in EVIDENCE_LENGTH:
        pool.append(EVIDENCE_LENGTH[bucket].format(pages=pages))
    count, avg = book.get("rating_count") or 0, book.get("rating_avg")
    if count >= 5 and avg:
        pool.append(rng.choice(EVIDENCE_RATING).format(count=count, avg=f"{avg:.1f}"))
    if "tur" in (book.get("languages") or []) and (q.languages or rng.random() < 0.25):
        pool.append(rng.choice(EVIDENCE_TR))

    rng.shuffle(pool)
    # Kanıt cümleleri kendi başlarına birer cümle; sıfatla başlayanlarda
    # ("ağır yanı baştan sona...") büyük harfe çevrilmeleri gerekiyor.
    evidence = [capitalize(e) for e in pool[: rng.choice([1, 1, 2])]]

    # Köprü noktalamayla bitmiyorsa virgülle bağlanır, sonra çekirdek cümle
    # gelir. Cümle başı büyük harfe çevrilir (köprüler küçük harfle başlar).
    if bridge and not bridge.rstrip().endswith((":", ";", ",", ".", "!", "?")):
        bridge = bridge.rstrip() + ","
    parts = [p for p in [bridge, core, *evidence, rng.choice(CLOSERS)] if p]
    text = " ".join(" ".join(parts).split())
    return capitalize(text)


def write_hooks(book: dict, rng: random.Random, n: int = 2) -> list[str]:
    """Kısa çengel ifadeler — kart üzerinde etiket gibi gösterilir."""
    hooks: list[str] = []
    found = themes.themes_for(list(book.get("subjects") or []), limit=6)
    for name, kind in found:
        if kind == "mekan":
            hooks.append(f"{locative(name)} geçiyor")
        elif kind == "figur":
            hooks.append(name)
        else:
            hooks.append(name)
    for mood in (book.get("moods") or [])[:2]:
        adj = MOOD_ADJECTIVES.get(mood)
        if adj:
            hooks.append(f"{rng.choice(adj)} ton")
    rng.shuffle(hooks)
    seen, out = set(), []
    for h in hooks:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out[:n]


# ── Aday havuzu ────────────────────────────────────────────────────────────


@dataclass
class Sample:
    task: str
    messages: list[dict[str, str]]
    meta: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(
            {"task": self.task, "messages": self.messages, "meta": self.meta},
            ensure_ascii=False,
        )


def assemble_candidates(
    positives: list[dict],
    negatives: list[dict],
    rng: random.Random,
    *,
    total: int = PROMPT_CANDIDATES,
) -> tuple[list[Candidate], dict[str, dict]]:
    """Pozitif + olumsuz adayları karıştırıp kimliklendirir."""
    chosen = list(positives)
    seen = {b["work_key"] for b in chosen}
    for b in negatives:
        if len(chosen) >= total:
            break
        if b["work_key"] not in seen:
            seen.add(b["work_key"])
            chosen.append(b)

    rng.shuffle(chosen)
    cands, by_id = [], {}
    for i, book in enumerate(chosen, start=1):
        cid = f"a{i}"
        cands.append(Candidate.from_row(book, cid))
        by_id[cid] = book
    return cands, by_id


def build_sample(
    q: GeneratedQuery,
    positives: list[dict],
    negatives: list[dict],
    rng: random.Random,
    *,
    task: str = "grounded_recommend",
) -> Sample:
    """Bir istek + aday havuzundan tam bir eğitim örneği üretir."""
    cands, by_id = assemble_candidates(positives, negatives, rng)
    id_of = {book["work_key"]: cid for cid, book in by_id.items()}

    picks = []
    for book in positives[: q.limit]:
        cid = id_of.get(book["work_key"])
        if not cid:
            continue
        score = match_score(book, q)
        picks.append({
            "id": cid,
            "why": write_why(book, q, rng),
            "hooks": write_hooks(book, rng),
            "content_notes": themes.content_notes_for(
                list(book.get("subjects") or [])
            ),
            "confidence": round(min(0.97, max(0.3, score)), 2),
        })

    followups: list[str] = []
    vague = q.style == "belirsiz" or not (q.genres or q.moods or q.text)
    if vague or len(picks) < q.limit:
        followups = [rng.choice(FOLLOWUPS_VAGUE)]
    elif rng.random() < 0.45:
        followups = [rng.choice(FOLLOWUPS)]

    target = json.dumps({"picks": picks, "followups": followups}, ensure_ascii=False)

    request_block = render_request(
        query=q.text, genres=q.genres, moods=q.moods, era=q.era,
        length=q.length, audience=q.audience,
        languages=[str(lang) for lang in q.languages], limit=q.limit,
    )
    messages = build_messages(request_block, cands)
    messages.append({"role": "assistant", "content": target})

    return Sample(
        task=task,
        messages=messages,
        meta={
            "style": q.style,
            "query": q.text,
            "limit": q.limit,
            "n_candidates": len(cands),
            "n_picks": len(picks),
            "picked_keys": [b["work_key"] for b in positives[: q.limit]],
            "match_reasons": {
                b["work_key"]: match_reasons(b, q) for b in positives[: q.limit]
            },
        },
    )
