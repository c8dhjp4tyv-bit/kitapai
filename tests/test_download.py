"""İndirici: sürdürme ve geçici ağ hatalarında yeniden deneme.

archive.org 12 GB'lık dump'ı indirirken bağlantıyı düzenli olarak düşürüyor.
Bu testler gerçek ağa çıkmadan, sahte bir httpx taşıyıcısıyla o davranışı
taklit eder.
"""

from __future__ import annotations

import httpx
import pytest

from kitapai.data import download as dl

PAYLOAD = b"".join(bytes([i % 251]) for i in range(5000))


class FlakyTransport(httpx.BaseTransport):
    """İlk `fail_times` GET isteğini akışın ortasında koparır."""

    def __init__(self, payload: bytes, fail_times: int = 0, cut_at: int = 1000) -> None:
        self.payload = payload
        self.fail_times = fail_times
        self.cut_at = cut_at
        self.requests: list[tuple[str, str | None]] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        rng = request.headers.get("range")
        self.requests.append((request.method, rng))

        if request.method == "HEAD":
            return httpx.Response(200, headers={"content-length": str(len(self.payload))})

        start = 0
        if rng:
            start = int(rng.removeprefix("bytes=").split("-")[0])
        body = self.payload[start:]

        if self.fail_times > 0:
            self.fail_times -= 1
            cut = body[: self.cut_at]

            def broken():
                yield cut
                raise httpx.ReadError("bağlantı sıfırlandı")

            return httpx.Response(
                206 if rng else 200, stream=httpx.SyncByteStream() if False else _Gen(broken())
            )

        return httpx.Response(206 if rng else 200, content=body)


class _Gen(httpx.SyncByteStream):
    def __init__(self, gen):
        self._gen = gen

    def __iter__(self):
        yield from self._gen


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    """Testler geri çekilme süresini beklemesin."""
    monkeypatch.setattr(dl.time, "sleep", lambda _s: None)


@pytest.fixture(autouse=True)
def _small_chunks(monkeypatch):
    """Parça boyutunu küçült.

    Gerçek 1 MiB tampon, bu testteki 5 KB'lık yükte hiç dolmadan biterdi;
    kopma anında diske hiçbir şey yazılmaz ve sürdürme yolu hiç sınanmazdı.
    """
    monkeypatch.setattr(dl, "CHUNK", 256)


def _patch_client(monkeypatch, transport: FlakyTransport) -> None:
    original = httpx.Client

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr(dl.httpx, "Client", factory)


def test_temiz_indirme(tmp_path, monkeypatch):
    transport = FlakyTransport(PAYLOAD)
    _patch_client(monkeypatch, transport)
    result = dl.download("https://ornek/dump.gz", tmp_path / "dump.gz")
    assert (tmp_path / "dump.gz").read_bytes() == PAYLOAD
    assert result.bytes_total == len(PAYLOAD)
    assert not result.skipped


def test_kopan_baglanti_kaldigi_yerden_devam(tmp_path, monkeypatch):
    """Akış ortada koparsa Range ile sürdürülmeli, dosya bozulmamalı."""
    transport = FlakyTransport(PAYLOAD, fail_times=2, cut_at=1500)
    _patch_client(monkeypatch, transport)

    result = dl.download("https://ornek/dump.gz", tmp_path / "dump.gz")

    assert (tmp_path / "dump.gz").read_bytes() == PAYLOAD
    assert result.resumed is True

    # İlk GET Range'siz; kopmalardan sonrakiler diskteki boyuttan devam etmeli.
    gets = [r for r in transport.requests if r[0] == "GET"]
    assert len(gets) == 3
    assert gets[0][1] is None
    # Sürdürme noktaları: diske yazılmış tam parça sayısı kadar, artan sırada.
    offsets = [int(r[1].removeprefix("bytes=").rstrip("-")) for r in gets[1:]]
    assert offsets == sorted(offsets) and offsets[0] > 0
    assert all(o % dl.CHUNK == 0 for o in offsets), offsets


def test_tam_dosya_atlaniyor(tmp_path, monkeypatch):
    dest = tmp_path / "dump.gz"
    dest.write_bytes(PAYLOAD)
    transport = FlakyTransport(PAYLOAD)
    _patch_client(monkeypatch, transport)

    result = dl.download("https://ornek/dump.gz", dest)
    assert result.skipped
    assert not [r for r in transport.requests if r[0] == "GET"]


def test_yarim_dosya_sürdürülüyor(tmp_path, monkeypatch):
    dest = tmp_path / "dump.gz"
    dest.write_bytes(PAYLOAD[:2000])
    transport = FlakyTransport(PAYLOAD)
    _patch_client(monkeypatch, transport)

    result = dl.download("https://ornek/dump.gz", dest)
    assert dest.read_bytes() == PAYLOAD
    assert result.resumed
    first_get = next(r for r in transport.requests if r[0] == "GET")
    assert first_get[1] == "bytes=2000-"


def test_ilerleme_yoksa_pes_ediyor(tmp_path, monkeypatch):
    """Hiç bayt gelmiyorsa sonsuz döngüye girmeden anlamlı hata vermeli."""
    transport = FlakyTransport(PAYLOAD, fail_times=99, cut_at=0)
    _patch_client(monkeypatch, transport)

    with pytest.raises(OSError, match="denemede ilerleme yok"):
        dl.download("https://ornek/dump.gz", tmp_path / "dump.gz", attempts=3)


def test_yer_yoksa_baslamadan_hata(tmp_path, monkeypatch):
    transport = FlakyTransport(PAYLOAD)
    _patch_client(monkeypatch, transport)
    monkeypatch.setattr(dl, "free_bytes", lambda _p: 10)

    with pytest.raises(OSError, match="boş alan"):
        dl.download("https://ornek/dump.gz", tmp_path / "dump.gz")


def test_geri_cekilme_ustel_ve_sinirli():
    from kitapai.data import http

    delays = [http.backoff(n) for n in range(1, 10)]
    assert all(d <= http.MAX_DELAY for d in delays)
    assert delays[3] > delays[0]


@pytest.mark.parametrize("status,retry", [
    (503, True), (429, True), (403, True), (404, False), (401, False),
])
def test_yeniden_denenecek_durumlar(status, retry):
    response = httpx.Response(status, request=httpx.Request("GET", "https://x/"))
    exc = httpx.HTTPStatusError("x", request=response.request, response=response)
    assert dl.retryable(exc) is retry
    assert dl.retryable(httpx.ReadError("kopma")) is True
