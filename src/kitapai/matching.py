"""İstek ile kitap arasındaki uyum puanı — eğitim ve servis aynı ölçüyü kullanır.

Veri kümesi üretiminde hedef `confidence` bu puandan türetilir; serviste ise
adayların yeniden sıralanmasında ve `match_reasons` alanında kullanılır. Aynı
ölçüt iki yerde de geçerli olduğu için modelin öğrendiği kalibrasyon serviste
anlamını korur.
"""

from __future__ import annotations

from typing import Protocol


class MatchTarget(Protocol):
    """İstek benzeri herhangi bir nesne (GeneratedQuery, RecommendRequest)."""

    genres: list[str]
    moods: list[str]
    era: str | None
    length: str | None
    audience: str | None
    languages: list


def match_score(book: dict, q: MatchTarget) -> float:
    """0-1 arası gerçek uyum puanı.

    Hedef yanıttaki `confidence` bu puandan türetilir; böylece model rastgele
    değil, *kalibre* güven üretmeyi öğrenir.
    """
    score, weight = 0.0, 0.0

    if q.genres:
        weight += 3.0
        overlap = len(set(q.genres) & set(book.get("genres") or []))
        score += 3.0 * min(1.0, overlap / len(q.genres))
    if q.moods:
        weight += 2.0
        overlap = len(set(q.moods) & set(book.get("moods") or []))
        score += 2.0 * min(1.0, overlap / len(q.moods))
    if q.era:
        weight += 1.5
        score += 1.5 if book.get("era") == q.era else 0.0
    if q.length:
        weight += 1.5
        score += 1.5 if book.get("length_bucket") == q.length else 0.0
    if q.audience:
        weight += 1.0
        score += 1.0 if book.get("audience") == q.audience else 0.0
    if q.languages:
        # `RecommendRequest` Language enum'u taşır, `GeneratedQuery` düz string;
        # ikisini de aynı biçime indirger.
        wanted = {getattr(lang, "value", lang) for lang in q.languages}
        weight += 1.0
        score += 1.0 if wanted & set(book.get("languages") or []) else 0.0

    if weight == 0:
        # Filtresiz istek: bilinirlik ve veri tamlığı belirleyici.
        return 0.45 + 0.45 * float(book.get("popularity") or 0.0)

    base = score / weight
    # Bilinirlik küçük bir artı; hiç tanınmayan kitaplar güveni düşürür.
    return max(0.0, min(1.0, 0.85 * base + 0.15 * float(book.get("popularity") or 0.0)))


def match_reasons(book: dict, q: MatchTarget) -> list[str]:
    """Makine tarafından doğrulanabilir eşleşme kanıtı (değerlendirmede kullanılır)."""
    out = []
    for slug in set(q.genres) & set(book.get("genres") or []):
        out.append(f"tür:{slug}")
    for slug in set(q.moods) & set(book.get("moods") or []):
        out.append(f"ruh:{slug}")
    if q.era and book.get("era") == q.era:
        out.append(f"dönem:{q.era}")
    if q.length and book.get("length_bucket") == q.length:
        out.append(f"uzunluk:{q.length}")
    wanted = {getattr(lang, "value", lang) for lang in (q.languages or [])}
    if wanted & set(book.get("languages") or []):
        out.append("dil:" + ",".join(sorted(wanted & set(book.get("languages") or []))))
    return out
