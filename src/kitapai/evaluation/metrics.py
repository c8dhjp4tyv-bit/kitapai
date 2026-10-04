"""Öneri kalitesi ölçütleri.

Bir kitap öneri modelini "kayıp düştü" diye değerlendirmek yetmez. Burada
modelin *işe yarar* olup olmadığını ölçen, tamamen otomatik ve tekrarlanabilir
ölçütler var:

  json_valid          → çıktı ayrıştırılabildi mi
  id_valid            → seçilen kimlikler gerçekten aday listesinde miydi
  limit_respected     → istenen sayıdan fazla öneri var mı
  pick_precision      → modelin seçtikleri referans (gerçekten uyan) kitaplar mı
  pick_recall         → referans kitapların kaçını model buldu
  turkish_ratio       → gerekçe Türkçe mi (İngilizce sızıntısı var mı)
  copy_ratio          → gerekçe, aday özetinden kopyalanmış mı
  distinct2           → gerekçelerde şablon tekrarı var mı
  conf_gap            → doğru seçimlerin güveni, yanlışlarınkinden ne kadar yüksek
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass, field

# Gerekçede İngilizce sızıntısını yakalamak için sık İngilizce işlev sözcükleri.
ENGLISH_MARKERS = re.compile(
    r"\b(the|and|of|with|this|that|from|about|which|their|when|where|while|"
    r"novel|story|book|reader|author)\b", re.IGNORECASE
)
# Türkçeye özgü harfler + sık Türkçe ekler/sözcükler.
TURKISH_MARKERS = re.compile(
    r"[çğıöşüÇĞİÖŞÜ]|\b(bir|bu|için|ile|ama|çok|daha|gibi|olan|var)\b", re.IGNORECASE
)
_WORD = re.compile(r"\w+", re.UNICODE)


@dataclass
class EvalResult:
    n: int = 0
    json_valid: float = 0.0
    repaired: float = 0.0
    id_valid: float = 0.0
    limit_respected: float = 0.0
    pick_precision: float = 0.0
    pick_recall: float = 0.0
    turkish_ratio: float = 0.0
    copy_ratio: float = 0.0
    distinct2: float = 0.0
    conf_correct: float = 0.0
    conf_wrong: float = 0.0
    conf_gap: float = 0.0
    formal_ratio: float = 0.0
    id_coverage: float = 0.0
    avg_picks: float = 0.0
    avg_why_chars: float = 0.0
    failures: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["failures"] = self.failures[:20]
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items()}


def is_turkish(text: str) -> bool:
    """Metin ağırlıklı Türkçe mi? (İngilizce sızıntısı denetimi)"""
    if not text.strip():
        return False
    tr = len(TURKISH_MARKERS.findall(text))
    en = len(ENGLISH_MARKERS.findall(text))
    return tr > en


def copied_from(why: str, source: str | None, *, n: int = 8) -> bool:
    """Gerekçe, aday özetinden alınmış bir n-gram içeriyor mu?"""
    if not source or not why:
        return False
    src_words = _WORD.findall(source.lower())
    why_words = _WORD.findall(why.lower())
    if len(src_words) < n or len(why_words) < n:
        return False
    src_grams = {tuple(src_words[i:i + n]) for i in range(len(src_words) - n + 1)}
    return any(
        tuple(why_words[i:i + n]) in src_grams for i in range(len(why_words) - n + 1)
    )


def distinct_n(texts: list[str], n: int = 2) -> float:
    """Farklı n-gram oranı: düşükse model tek bir kalıbı tekrarlıyor demektir."""
    grams: Counter = Counter()
    total = 0
    for text in texts:
        words = _WORD.findall(text.lower())
        for i in range(max(0, len(words) - n + 1)):
            grams[tuple(words[i:i + n])] += 1
            total += 1
    return len(grams) / total if total else 0.0
