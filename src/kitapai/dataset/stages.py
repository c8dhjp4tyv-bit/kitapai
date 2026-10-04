"""Mevcut örnekleri iki göreve ayırır: SEÇ ve YAZ (bkz. prompting.py'deki gerekçe).

Yeni veri üretilmez; var olan iki dosyadan türetilir:
  • train.jsonl / valid.jsonl      → SEÇ  (aynı istem ve adaylar, hedef yalnızca kimlikler)
  • distilled.jsonl                → YAZ  (istek + yalnızca seçilen kitaplar → Gemini gerekçesi)

SEÇ hedefi kural tabanlı referans seçimdir; kaybın %100'ü seçim kararındadır. YAZ
hedefi damıtılmış metindir ve istem, serviste yazıcıya gidecek istemin AYNISIDIR.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..prompting import SELECT_SYSTEM_PROMPT, WRITE_SYSTEM_PROMPT, format_write_target
from .distill import build_user_prompt


def select_sample(row: dict) -> dict:
    """Seçim örneği: aynı kullanıcı mesajı, hedef `{"ids":[...]}`."""
    target = json.loads(row["messages"][2]["content"])
    ids = [p["id"] for p in target["picks"]]
    return {
        "task": "select",
        "messages": [
            {"role": "system", "content": SELECT_SYSTEM_PROMPT},
            {"role": "user", "content": row["messages"][1]["content"]},
            {"role": "assistant", "content": json.dumps({"ids": ids}, ensure_ascii=False)},
        ],
        "meta": row.get("meta", {}),
    }


def write_sample(row: dict) -> dict | None:
    """Yazım örneği: (istek + seçilen kitaplar + uyum) → damıtılmış gerekçeler."""
    prompt, ids = build_user_prompt(row)
    if not ids:
        return None
    by_id = {p["id"]: p for p in json.loads(row["messages"][2]["content"])["picks"]}
    items = [(i, by_id[i]["why"]) for i in ids]
    return {
        "task": "write",
        "messages": [
            {"role": "system", "content": WRITE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": format_write_target(items)},
        ],
        "meta": row.get("meta", {}),
    }


def _write_jsonl(path: Path, rows: list[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(rows)


def build_stages(dataset_dir: Path, *, write_valid: int = 200) -> dict[str, int]:
    """`dataset_dir` içinde select_*.jsonl ve write_*.jsonl dosyalarını üretir."""
    def load(name: str) -> list[dict]:
        path = dataset_dir / name
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    counts = {
        "select_train": _write_jsonl(
            dataset_dir / "select_train.jsonl", [select_sample(r) for r in load("train.jsonl")]),
        "select_valid": _write_jsonl(
            dataset_dir / "select_valid.jsonl", [select_sample(r) for r in load("valid.jsonl")]),
    }
    written = [w for r in load("distilled.jsonl") if (w := write_sample(r)) is not None]
    # Doğrulama: sondaki örnekler. Damıtma tamamlanma sırasıyla yazıldığından yaklaşık
    # rastgele; eğitimin kullandığı baştaki örneklerle çakışmaz.
    held = written[-write_valid:] if len(written) > write_valid * 3 else []
    counts["write_train"] = _write_jsonl(
        dataset_dir / "write_train.jsonl", written[: len(written) - len(held)])
    counts["write_valid"] = _write_jsonl(dataset_dir / "write_valid.jsonl", held)
    return counts
