"""Ağ dayanıklılığı — archive.org düzenli olarak bağlantı düşürüyor.

Open Library dump'ları archive.org aynalarından geliyor ve hem URL çözümleme
(HEAD + yönlendirme) hem de saatler süren indirme sırasında
"Connection reset by peer" almak kural, istisna değil. Yeniden deneme mantığı
burada tek bir yerde durur; `sources` ve `download` modülleri onu paylaşır
(döngüsel import olmasın diye ayrı dosya).
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import TypeVar

import httpx

from ..logging import get

log = get("data.http")

MAX_ATTEMPTS = 8
BASE_DELAY = 2.0
MAX_DELAY = 60.0

#: Yeniden denenebilir sunucu yanıtları. 403 dâhil, çünkü archive.org yük
#: altında geçici olarak 403 döndürebiliyor.
RETRY_STATUS = frozenset({403, 408, 425, 429, 500, 502, 503, 504})

T = TypeVar("T")


def backoff(attempt: int) -> float:
    """Üstel geri çekilme + jitter (eşzamanlı isteklerin üst üste binmemesi için)."""
    delay = min(MAX_DELAY, BASE_DELAY * 2 ** (attempt - 1))
    return delay * (0.5 + random.random() / 2)


def retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRY_STATUS
    return isinstance(exc, httpx.TransportError)


def with_retries(fn: Callable[[], T], *, what: str, attempts: int = MAX_ATTEMPTS) -> T:
    """`fn`'i geçici ağ hatalarında üstel geri çekilmeyle yeniden dener."""
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:
            if not retryable(exc) or attempt == attempts:
                raise
            delay = backoff(attempt)
            log.warning("%s başarısız (%s) — %.1f sn sonra %d/%d. deneme",
                        what, exc.__class__.__name__, delay, attempt + 1, attempts)
            time.sleep(delay)
    raise AssertionError("ulaşılamaz")
