"""Doğrulama kümesi üzerinde modeli çalıştırıp ölçütleri hesaplar.

Üç mod (`mode`):
  select  SEÇ modeli: istek + adaylar → kimlikler. Ölçüt: referansa isabet (precision/
          recall), geçerli JSON, aday dışı kimlik.
  write   YAZ modeli: seçilen kitaplar → gerekçe. Ölçüt: Türkçe oranı, "siz" hitabı,
          kopyalama, çeşitlilik, kimlik kapsamı.
  legacy  Eski tek-model biçimi (v1-v3): `picks[]` hem seçim hem gerekçe. Yalnızca
          eski adaptörleri AYNI koşullarda yeniden ölçmek için.

Üretim toplu yapılır (`generate_batch`); örnek başına ~20 sn yerine birkaç sn sürer.
`record_path` verilirse her örneğin seçimleri JSONL'e yazılır — hakem değerlendirmesi
(`evaluation/judge.py`) bu kayıtları kullanır.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..dataset.distill import FORMAL_ADDRESS
from ..logging import get
from ..serve.decode import decode, decode_select, decode_write
from ..serve.engine import Engine
from .metrics import EvalResult, copied_from, distinct_n, is_turkish

log = get("evaluation")

_CANDIDATE_LINE = re.compile(r"^\[(a\d+)\]", re.MULTILINE)
_LIMIT = re.compile(r"İstenen öneri sayısı:\s*(\d+)")
_SUMMARY = re.compile(r"^\s+özet: (.+)$", re.MULTILINE)
_BLOCK = re.compile(r"\n(?=\[a\d+\])")

MODES = ("select", "write", "legacy")


def _candidate_ids(user_message: str) -> list[str]:
    return _CANDIDATE_LINE.findall(user_message)


def _reference_ids(row: dict) -> set[str]:
    """Hedef yanıtın seçtiği kimlikler (kanıtlanabilir biçimde uyan adaylar).

    Hedefler isteğe uyan kitaplardan üretildi; aday listesindeki diğerleri zor olumsuz
    örnek. Modelin seçimi bu kümeyle karşılaştırılır. Uyarı: belirsiz isteklerde uyan
    kitap çoktur ama referans yalnızca birkaçını sayar — bu ölçüt kaliteyi eksik ölçebilir.
    """
    try:
        target = json.loads(row["messages"][-1]["content"])
    except (KeyError, ValueError, TypeError, AttributeError):
        return set()
    if isinstance(target.get("ids"), list):                  # select
        return {i for i in target["ids"] if isinstance(i, str)}
    return {p["id"] for p in target.get("picks", []) if isinstance(p, dict) and "id" in p}


def _prompt(row: dict) -> list[dict[str, str]]:
    return [m for m in row["messages"] if m["role"] != "assistant"]


def _gen_kwargs(mode: str, batch_size: int) -> dict:
    if mode == "select":
        return {"adapter": "select", "max_new_tokens": 60, "temperature": 0.0,
                "batch_size": batch_size}
    if mode == "write":
        return {"adapter": "write", "max_new_tokens": 450, "temperature": 0.3,
                "batch_size": batch_size}
    return {"batch_size": batch_size}        # legacy: motorun varsayılanları (eski koşullar)


def evaluate(
    engine: Engine,
    dataset_path: Path,
    *,
    samples: int = 200,
    mode: str = "select",
    batch_size: int = 8,
    record_path: Path | None = None,
) -> EvalResult:
    """`dataset_path` üzerinde modeli çalıştırıp ölçütleri döndürür."""
    if mode not in MODES:
        raise ValueError(f"bilinmeyen mod: {mode} ({', '.join(MODES)})")
    rows: list[dict] = []
    with dataset_path.open(encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            if i >= samples:
                break
            rows.append(json.loads(line))
    if not rows:
        raise ValueError(f"{dataset_path} boş")

    try:
        raws = engine.generate_batch([_prompt(r) for r in rows], **_gen_kwargs(mode, batch_size))
    except Exception as exc:
        raise RuntimeError(f"toplu üretim başarısız: {exc}") from exc

    result = EvalResult(n=len(rows))
    records: list[dict] = []
    why_all: list[str] = []
    n_json = n_repaired = n_ids_ok = n_limit = 0
    hit = picked_total = ref_total = 0
    tr = cp = fm = n_whys = coverage_num = coverage_den = 0
    chars = picks_total = 0

    for idx, (row, raw) in enumerate(zip(rows, raws, strict=True)):
        user = row["messages"][1]["content"]
        valid_ids = set(_candidate_ids(user))
        limit_match = _LIMIT.search(user)
        limit = int(limit_match.group(1)) if limit_match else 3
        reference = _reference_ids(row)
        picks: list[str] = []
        record = {"i": idx, "valid_ids": sorted(valid_ids), "reference": sorted(reference),
                  "ids": [], "error": None}

        if mode == "write":
            items, error = decode_write(raw)
            blocks = {
                m.group(1): b for b in _BLOCK.split(user) if (m := re.match(r"\[(a\d+)\]", b))
            }
            wanted = list(blocks)
            if error:
                result.failures.append(f"örnek {idx}: {error}")
                record["error"] = error
            else:
                n_json += 1
            record["items"] = {cid: {"why": it["why"], "hooks": it["hooks"]}
                               for cid, it in items.items()}
            coverage_den += len(wanted)
            coverage_num += sum(1 for i in wanted if items.get(i, {}).get("why"))
            for cid, it in items.items():
                if not it["why"]:
                    continue
                n_whys += 1
                chars += len(it["why"])
                why_all.append(it["why"])
                tr += int(is_turkish(it["why"]))
                fm += int(bool(FORMAL_ADDRESS.search(it["why"])))
                cp += int(copied_from(it["why"], blocks.get(cid), n=7))
            records.append(record)
            continue

        if mode == "select":
            decoded, error = decode_select(raw)
            if decoded is None:
                result.failures.append(f"örnek {idx}: {error}")
                record["error"] = error
                records.append(record)
                continue
            n_json += 1
            picks = decoded
        else:                                                   # legacy
            dec = decode(raw)
            if not dec.ok:
                result.failures.append(f"örnek {idx}: {dec.error}")
                record["error"] = dec.error
                records.append(record)
                continue
            n_json += 1
            n_repaired += int(dec.repaired)
            picks = [p.id for p in dec.output.picks]
            for p in dec.output.picks:
                why_all.append(p.why)
                chars += len(p.why)
                n_whys += 1
                tr += int(is_turkish(p.why))
                cp += int(any(copied_from(p.why, x) for x in _SUMMARY.findall(user)))

        record["ids"] = picks
        records.append(record)
        picks_total += len(picks)
        if picks and all(i in valid_ids for i in picks):
            n_ids_ok += 1
        else:
            bad = [i for i in picks if i not in valid_ids]
            if bad:
                result.failures.append(f"örnek {idx}: listede olmayan kimlik {bad}")
        n_limit += int(len(picks) <= limit)
        chosen = set(picks)
        hit += len(chosen & reference)
        picked_total += len(chosen)
        ref_total += min(len(reference), limit)

    n = len(rows)
    result.json_valid = n_json / n
    result.repaired = n_repaired / max(1, n_json)
    if mode == "write":
        result.id_coverage = coverage_num / max(1, coverage_den)
    else:
        result.id_valid = n_ids_ok / n
        result.limit_respected = n_limit / n
        result.pick_precision = hit / picked_total if picked_total else 0.0
        result.pick_recall = hit / ref_total if ref_total else 0.0
        result.avg_picks = picks_total / n
    if n_whys:
        result.turkish_ratio = tr / n_whys
        result.copy_ratio = cp / n_whys
        result.formal_ratio = fm / n_whys
        result.avg_why_chars = chars / n_whys
        result.distinct2 = distinct_n(why_all, 2)

    if record_path is not None:
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
            encoding="utf-8")
    log.info("değerlendirme (%s) bitti: json=%.2f kimlik=%.2f isabet=%.2f/%.2f türkçe=%.2f",
             mode, result.json_valid, result.id_valid, result.pick_precision,
             result.pick_recall, result.turkish_ratio)
    return result
