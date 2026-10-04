"""Model çıktısından JSON çıkarma ve onarma.

İnce ayarlı model çoğunlukla temiz JSON üretir, ama üretim ortamında
"çoğunlukla" yetmez: kod bloğu sarmalayabilir, üretimi token sınırında
kesilebilir, sonda fazladan virgül bırakabilir. Bu modül bu durumları
kurtarır; kurtaramazsa sessizce yanlış veri döndürmek yerine açıkça
başarısız olur ve boru hattı yedek sıralamaya düşer.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from ..logging import get
from ..schemas import ModelOutput

log = get("serve.decode")

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")


@dataclass
class DecodeResult:
    output: ModelOutput | None
    repaired: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.output is not None


def _strip_fences(text: str) -> str:
    m = _FENCE.search(text)
    return m.group(1) if m else text


def _first_object(text: str) -> str | None:
    """İlk dengeli `{...}` bloğunu bulur (dize içindeki parantezleri sayar)."""
    start = text.find("{")
    if start < 0:
        return None
    depth, in_string, escaped = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _close_truncated(fragment: str) -> str:
    """Token sınırında kesilmiş JSON'u kapatmayı dener.

    Açık parantezler bir yığında tutulur ve ters sırayla kapatılır; sayarak
    kapatmak iç içe yapılarda bozuk sonuç verir
    (`{"picks":[{"id":"a1"` → `]}` değil, `}]}`).
    """
    text = fragment.rstrip()
    stack: list[str] = []
    in_string = escaped = False
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]" and stack:
            stack.pop()

    if in_string:
        text += '"'
    text = text.rstrip().rstrip(",")
    # Yarım kalmış anahtar/değer çifti varsa (`"why":` gibi) boş değer ekle.
    if text.rstrip().endswith(":"):
        text += '""'
    for opener in reversed(stack):
        text += "}" if opener == "{" else "]"
    return text


def decode(raw: str) -> DecodeResult:
    """Ham model çıktısını `ModelOutput`'a çevirir."""
    if not raw or not raw.strip():
        return DecodeResult(None, error="boş çıktı")

    text = _strip_fences(raw.strip())
    candidate = _first_object(text)
    repaired = False

    if candidate is None:
        # Dengeli blok yok: muhtemelen kesilmiş.
        candidate = _close_truncated(text[text.find("{"):] if "{" in text else text)
        repaired = True

    for attempt, payload in enumerate((candidate, _TRAILING_COMMA.sub(r"\1", candidate),
                                       _close_truncated(candidate))):
        try:
            data = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        try:
            output = ModelOutput.model_validate(data)
        except Exception as exc:  # pydantic doğrulama hatası
            return DecodeResult(None, error=f"şema hatası: {exc}")
        return DecodeResult(output, repaired=repaired or attempt > 0)

    log.warning("JSON çözülemedi (%s karakter): %s…", len(raw), raw[:160])
    return DecodeResult(None, error="geçersiz JSON")


# ── iki aşamalı biçimler (SEÇ / YAZ) ────────────────────────────────────────


def _parse_object(raw: str) -> tuple[dict | None, bool, str | None]:
    """Ham çıktıdan JSON nesnesi: (veri, onarıldı mı, hata)."""
    if not raw or not raw.strip():
        return None, False, "boş çıktı"
    text = _strip_fences(raw.strip())
    candidate = _first_object(text)
    repaired = False
    if candidate is None:
        candidate = _close_truncated(text[text.find("{"):] if "{" in text else text)
        repaired = True
    for attempt, payload in enumerate(
        (candidate, _TRAILING_COMMA.sub(r"\1", candidate), _close_truncated(candidate))
    ):
        try:
            data = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict):
            return data, repaired or attempt > 0, None
    return None, False, "geçersiz JSON"


def decode_select(raw: str) -> tuple[list[str] | None, str | None]:
    """SEÇ çıktısı → (kimlikler, hata). Tekrarlar atılır, sıra korunur."""
    data, _repaired, error = _parse_object(raw)
    if data is None:
        return None, error
    ids = data.get("ids")
    if not isinstance(ids, list):
        return None, "'ids' listesi yok"
    seen: list[str] = []
    for i in ids:
        if isinstance(i, str) and i not in seen:
            seen.append(i)
    return seen, None


_WRITE_LINE = re.compile(r"^\s*[-*]?\s*\**(a\d+)\**\s*[:：]\s*(.+?)\s*$")


def decode_write(raw: str) -> tuple[dict[str, dict], str | None]:
    """YAZ çıktısı (`a1: gerekçe` satırları) → ({id: {why, hooks}}, hata).

    Çengeller modelden gelmez (`hooks` her zaman boş); çağıran kural tabanlı doldurur.
    Kimlik tekrarlanırsa ilki geçerli. Satırı olmayan çıktı hatadır.
    """
    out: dict[str, dict] = {}
    for line in raw.splitlines():
        m = _WRITE_LINE.match(line)
        if m and m.group(1) not in out:
            out[m.group(1)] = {"why": m.group(2), "hooks": []}
    if not out:
        return {}, "gerekçe satırı yok (beklenen: 'a1: ...')"
    return out, None
