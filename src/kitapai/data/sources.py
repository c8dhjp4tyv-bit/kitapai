"""Open Library dump dosyalarının nerede olduğunu çözer.

Üç kaynak desteklenir:
  • `latest` → openlibrary.org'un yönlendirdiği güncel archive.org dosyası
  • yerel dizin → daha önce indirilmiş `*.txt.gz`
  • doğrudan URL → DuckDB httpfs ile diske yazmadan akış

Disk darsa (`kitapai doctor` uyarır) `--source url` ile 17 GB'lık gz'leri
diske indirmeden doğrudan işleyebilirsin; karşılığında yeniden başlatma
maliyeti yüksektir.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import httpx

from ..logging import get
from .http import with_retries

log = get("data.sources")

BASE = "https://openlibrary.org/data"

#: Boru hattının kullandığı dump türleri. `required=False` olanlar yoksa
#: ilgili sinyal (puan/okur sayısı) sıfır kabul edilir.
DUMPS: dict[str, bool] = {
    "works": True,
    "editions": True,
    "authors": True,
    "ratings": False,
    "reading-log": False,
}


@dataclass(frozen=True)
class DumpSources:
    """Her dump türü için DuckDB'nin okuyabileceği tek bir yol/URL."""

    works: str | None = None
    authors: str | None = None
    editions: str | None = None
    ratings: str | None = None
    reading_log: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "works": self.works,
            "editions": self.editions,
            "authors": self.authors,
            "ratings": self.ratings,
            "reading-log": self.reading_log,
        }

    def is_remote(self) -> bool:
        return any(str(v).startswith("http") for v in self.as_dict().values() if v)


def latest_url(kind: str) -> str:
    return f"{BASE}/ol_dump_{kind}_latest.txt.gz"


def resolve_latest(kind: str, *, timeout: float = 30.0) -> str:
    """`_latest` yönlendirmesini gerçek archive.org URL'sine çevirir.

    DuckDB'nin httpfs'i yönlendirmeleri izler, ama gerçek URL'yi çözmek
    indirme sürdürme (range request) ve kayıt tutma için gereklidir.
    """
    url = latest_url(kind)

    def _resolve() -> str:
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            resp = client.head(url)
            resp.raise_for_status()
            return str(resp.url)

    return with_retries(_resolve, what=f"{kind} URL çözümlemesi")


def dump_date(url_or_path: str) -> str | None:
    """Dosya adındaki tarih damgasını döndürür (ol_dump_works_2026-08-31...)."""
    m = re.search(r"(\d{4}-\d{2}-\d{2})", str(url_or_path))
    return m.group(1) if m else None


def from_directory(
    directory: Path,
    *,
    pattern: str = "*.txt.gz",
    allow_missing: tuple[str, ...] = (),
) -> DumpSources:
    """Bir dizindeki dump dosyalarını türlerine göre eşler.

    Dosya adında tür anahtarı geçmesi yeterlidir; böylece hem
    `ol_dump_works_2026-08-31.txt.gz` hem de test fixture'ındaki
    `ol_dump_works_mini.txt.gz` bulunur.
    """
    directory = Path(directory)
    if not directory.is_dir():
        raise FileNotFoundError(f"dump dizini yok: {directory}")

    files = sorted(directory.glob(pattern))
    found: dict[str, str] = {}
    # En uzun anahtar önce eşleşmeli: "reading-log" içinde "log" yok ama
    # "editions" ile "works" karışmasın diye tam ek kullanıyoruz.
    for kind in sorted(DUMPS, key=len, reverse=True):
        for f in files:
            if f.name.startswith(f"ol_dump_{kind}_") and kind not in found:
                found[kind] = str(f)

    missing = [
        k for k, required in DUMPS.items()
        if required and k not in found and k not in allow_missing
    ]
    if missing:
        raise FileNotFoundError(
            f"{directory} içinde zorunlu dump(lar) yok: {', '.join(missing)}. "
            f"`kitapai data download` ile indirebilirsin."
        )
    for kind in DUMPS:
        if kind not in found:
            log.warning("%s dump'ı yok — bu sinyal olmadan devam edilecek", kind)

    return DumpSources(
        works=found.get("works"),
        authors=found.get("authors"),
        editions=found.get("editions"),
        ratings=found.get("ratings"),
        reading_log=found.get("reading-log"),
    )


def mixed(directory: Path, *, resolve: bool = True) -> DumpSources:
    """Yerelde olanı diskten, olmayanı doğrudan URL'den okur.

    Disk dar olduğunda işe yarar: 12 GB'lık `editions` dump'ını indirmek yerine
    DuckDB httpfs ile akıtıp yalnızca sıkıştırılmış katalog çıktısını saklarsın.
    İndirilmiş dump'lar tekrar tekrar kullanılabildiği için elde olanı yeniden
    indirmek de gerekmez.
    """
    directory = Path(directory)
    found: dict[str, str] = {}
    if directory.is_dir():
        for kind in DUMPS:
            for f in sorted(directory.glob("*.txt.gz")):
                if f.name.startswith(f"ol_dump_{kind}_") and kind not in found:
                    found[kind] = str(f)

    urls: dict[str, str] = {}
    for kind in DUMPS:
        if kind in found:
            log.info("%-12s yerel  %s", kind, Path(found[kind]).name)
            continue
        urls[kind] = resolve_latest(kind) if resolve else latest_url(kind)
        log.info("%-12s uzak   %s (diske yazılmadan akıtılacak)", kind, urls[kind])

    def pick(kind: str) -> str | None:
        return found.get(kind) or urls.get(kind)

    works, editions, authors = pick("works"), pick("editions"), pick("authors")

    return DumpSources(
        works=works, authors=authors, editions=editions,
        ratings=pick("ratings"), reading_log=pick("reading-log"),
    )


def from_remote(*, resolve: bool = True) -> DumpSources:
    """Diske indirmeden, doğrudan akış için kaynak listesi."""
    urls: dict[str, str] = {}
    for kind in DUMPS:
        urls[kind] = resolve_latest(kind) if resolve else latest_url(kind)
        log.info("%-12s → %s", kind, urls[kind])
    return DumpSources(
        works=urls["works"],
        authors=urls["authors"],
        editions=urls.get("editions"),
        ratings=urls.get("ratings"),
        reading_log=urls.get("reading-log"),
    )
