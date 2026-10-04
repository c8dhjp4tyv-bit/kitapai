"""Dump indirici — kesintiden sonra kaldığı yerden devam eder.

Open Library dosyaları onlarca GB ve archive.org bağlantıyı düzenli olarak
düşürüyor ("Connection reset by peer"). 12 GB'lık `editions` dump'ı saatler
sürdüğü için tek bir sıfırlamada pes etmek indirmeyi imkânsız kılar. Bu yüzden:

  • her HTTP çağrısı üstel geri çekilmeyle yeniden denenir,
  • akış koparsa dosyanın mevcut boyutundan Range ile devam edilir,
  • ilerleme kaydedildiğinde deneme sayacı sıfırlanır (uzun indirmelerde
    arada yaşanan kopmalar bütçeyi tüketmesin).
"""

from __future__ import annotations

import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from ..logging import get
from . import sources
from .http import MAX_ATTEMPTS, RETRY_STATUS, backoff, retryable, with_retries

log = get("data.download")

CHUNK = 1 << 20  # 1 MiB

__all__ = ["DownloadResult", "download", "download_all", "free_bytes", "remote_size"]
@dataclass
class DownloadResult:
    kind: str
    path: Path
    bytes_total: int
    resumed: bool
    skipped: bool


def free_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


def remote_size(url: str, *, timeout: float = 30.0) -> int | None:
    """Uzak dosyanın boyutu. HEAD reddedilirse 1 baytlık Range ile sorulur."""

    def _head() -> int | None:
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            resp = client.head(url)
            if resp.status_code in RETRY_STATUS:
                resp.raise_for_status()
            if resp.status_code >= 400:
                # Bazı aynalar HEAD'i desteklemiyor; Range ile toplam boyutu al.
                ranged = client.get(url, headers={"Range": "bytes=0-0"})
                ranged.raise_for_status()
                content_range = ranged.headers.get("content-range", "")
                return int(content_range.rsplit("/", 1)[-1]) if "/" in content_range else None
            raw = resp.headers.get("content-length")
            return int(raw) if raw and raw.isdigit() else None

    return with_retries(_head, what=f"boyut sorgusu ({Path(url).name})")


def _stream_once(
    url: str,
    dest: Path,
    have: int,
    *,
    total: int | None,
    timeout: float,
    progress: Callable[[int, int | None], None] | None,
) -> int:
    """Tek bir bağlantıda indirir; yazılan toplam bayt sayısını döndürür.

    `have` baytı zaten diskteyse Range ile oradan devam eder. Kopma hâlinde
    istisna yükselir ve çağıran yeniden dener — dosya kısmi hâliyle kalır,
    bir sonraki deneme kaldığı yerden sürer.
    """
    headers = {"Range": f"bytes={have}-"} if have else {}
    mode = "ab" if have else "wb"

    with (
        httpx.Client(follow_redirects=True, timeout=timeout) as client,
        client.stream("GET", url, headers=headers) as resp,
    ):
        if have and resp.status_code == 200:
            # Sunucu Range'i yok saydı; baştan yazmak zorundayız.
            log.warning("%s: sunucu sürdürmeyi desteklemedi, baştan", dest.name)
            have, mode = 0, "wb"
        resp.raise_for_status()
        with dest.open(mode) as fh:
            for chunk in resp.iter_bytes(CHUNK):
                fh.write(chunk)
                have += len(chunk)
                if progress:
                    progress(have, total)
    return have


def download(
    url: str,
    dest: Path,
    *,
    kind: str = "dump",
    progress: Callable[[int, int | None], None] | None = None,
    timeout: float = 60.0,
    attempts: int = MAX_ATTEMPTS,
) -> DownloadResult:
    """`url` → `dest`. Kopmalarda kaldığı yerden devam eder, tamsa atlar."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    total = remote_size(url)
    have = dest.stat().st_size if dest.exists() else 0

    if total is not None and have == total:
        log.info("%s zaten tam (%s bayt) — atlanıyor", dest.name, f"{total:,}")
        return DownloadResult(kind, dest, total, resumed=False, skipped=True)

    if total is not None:
        need = total - have
        free = free_bytes(dest.parent)
        if need > free:
            raise OSError(
                f"{dest.name} için {need / 2**30:.1f} GiB gerekiyor ama "
                f"{free / 2**30:.1f} GiB boş alan var. Yer açın veya "
                f"KITAPAI_DATA_DIR ile başka bir diske yönlendirin."
            )

    resumed = bool(have)
    if resumed:
        log.info("%s: %s bayttan devam", dest.name, f"{have:,}")

    attempt = 0
    while True:
        attempt += 1
        # Diskteki dosya tek doğruluk kaynağı: kopan bir denemede yazılan
        # baytlar bellekteki sayaca yansımadığı için her turda yeniden okunur.
        # Aksi hâlde her kopmada indirme sıfırdan başlar.
        have = dest.stat().st_size if dest.exists() else 0
        before = have
        try:
            have = _stream_once(
                url, dest, have, total=total, timeout=timeout, progress=progress
            )
        except Exception as exc:
            if not retryable(exc):
                raise
            complete = False
        else:
            complete = total is None or have >= total
            if complete:
                break
            log.warning("%s: akış erken bitti (%s/%s)", dest.name,
                        f"{have:,}", f"{total:,}")

        # İlerleme kaydedildiyse deneme bütçesi tazelenir: saatlerce süren bir
        # indirmede arada yaşanan kopmalar toplamı tüketmemeli.
        written = (dest.stat().st_size if dest.exists() else 0)
        if written > before:
            attempt = 0
            resumed = True
            have = written
        elif attempt >= attempts:
            raise OSError(
                f"{dest.name}: {attempts} denemede ilerleme yok "
                f"({have:,}/{total if total is not None else '?'} bayt indirildi). "
                f"Aynı komutu tekrar çalıştırırsan kaldığı yerden devam eder."
            )
        time.sleep(backoff(max(1, attempt)))

    if total is not None and have != total:
        raise OSError(f"{dest.name}: boyut uyuşmuyor ({have:,} ≠ {total:,})")

    return DownloadResult(kind, dest, have, resumed=resumed, skipped=False)


def download_all(
    dest_dir: Path,
    *,
    kinds: list[str] | None = None,
    progress: Callable[[str, int, int | None], None] | None = None,
) -> list[DownloadResult]:
    """Gerekli tüm dump'ları indirir.

    Küçükten büyüğe sıralanır (erken hata ucuz olsun). Bir dump tüm
    denemelerden sonra da inmezse diğerleri denenmeye devam eder; saatler süren
    bir koşuda tek bir aynanın çökmesi bütün işi iptal etmemeli. Başarısızlıklar
    sonunda toplu olarak bildirilir.
    """
    wanted = kinds or list(sources.DUMPS)
    # ratings/reading-log birkaç MB; works/editions on GB. Küçükler önce.
    order = ["ratings", "reading-log", "authors", "works", "editions"]
    wanted = sorted(wanted, key=lambda k: order.index(k) if k in order else 99)

    results: list[DownloadResult] = []
    failures: list[tuple[str, Exception]] = []

    for kind in wanted:
        try:
            url = sources.resolve_latest(kind)
            dest = dest_dir / Path(url).name
            results.append(
                download(
                    url, dest, kind=kind,
                    progress=(lambda d, t, k=kind: progress(k, d, t)) if progress else None,
                )
            )
        except Exception as exc:
            log.error("%s indirilemedi: %s", kind, exc)
            failures.append((kind, exc))

    if failures:
        names = ", ".join(k for k, _ in failures)
        log.error("başarısız dump(lar): %s — aynı komutu tekrar çalıştırırsan "
                  "tamamlananlar atlanır, eksikler kaldığı yerden devam eder", names)
        if len(failures) == len(wanted):
            raise failures[0][1]

    return results
