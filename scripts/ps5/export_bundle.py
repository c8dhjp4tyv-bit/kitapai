"""PS5 payload'u için veri paketini üretir (PC'de, bir kez).

PS5'te Python/DuckDB yok; payload yalnızca algoritmayı taşır, veri buradan gelir:
  books.tsv   bilinen kitapların alt kümesi (varsayılan: >=15 okuyucu), tek satır = bir kitap
  meta.json   istem metinleri, taksonomi, sorgu genişletme tabloları, etiket sözlükleri

Alan ayırıcı \\t, liste ayırıcı \\x1f. Metinlerdeki \\t/\\n/\\x1f boşluğa çevrilir.
Kullanım: python scripts/ps5/export_bundle.py <çıktı-dizini> [--min-readers 15]
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import duckdb

from kitapai import taxonomy
from kitapai.config import get_settings
from kitapai.dataset import themes
from kitapai.dataset.queries import MOOD_ADJECTIVES
from kitapai.prompting import (
    DESCRIPTION_CHARS, PROMPT_CANDIDATES, SELECT_SYSTEM_PROMPT, WRITE_SYSTEM_PROMPT,
)
from kitapai.retrieval import expand as ex
from kitapai.serve.pipeline import WRITE_BASE_TOKENS, WRITE_TOKENS_PER_BOOK

import random
import unicodedata

from kitapai.dataset.tasks import write_hooks

COLUMNS = [
    "work_key", "title", "subtitle", "title_tr", "authors", "subjects", "description",
    "first_published", "pages", "languages", "isbns", "genres", "moods", "era",
    "length_bucket", "audience", "rating_avg", "rating_count", "readers", "popularity",
    "cover_url", "content_notes", "hooks",
]
LISTS = {"authors", "subjects", "languages", "isbns", "genres", "moods", "content_notes", "hooks"}
DESC_CHARS = 500
SUBJECTS_KEEP = 12


def clean(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"[\t\r\n\x1f]+", " ", str(value)).strip()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--min-readers", type=int, default=15)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(get_settings().catalog_file), read_only=True)
    derived = {"content_notes", "hooks"}
    cols = ", ".join(c for c in COLUMNS if c not in derived)
    rows = con.execute(
        f"SELECT {cols} FROM books WHERE readers >= ? ORDER BY popularity DESC", [args.min_readers]
    ).fetchall()
    names = [c for c in COLUMNS if c not in derived]

    with (args.out / "books.tsv").open("w", encoding="utf-8") as fh:
        for r in rows:
            row = dict(zip(names, r, strict=True))
            row["description"] = (row.get("description") or "")[:DESC_CHARS]
            subjects = list(row.get("subjects") or [])
            row["content_notes"] = themes.content_notes_for(subjects)
            # Çengeller kural tabanlı ve kitap başına sabit olsun (rastgele ama yeniden üretilebilir).
            row["hooks"] = write_hooks(dict(row, subjects=subjects),
                                       random.Random(row["work_key"]))
            row["subjects"] = subjects[:SUBJECTS_KEEP]
            fields = []
            for c in COLUMNS:
                v = row.get(c)
                if c in LISTS:
                    fields.append("\x1f".join(clean(x) for x in (v or [])))
                else:
                    fields.append(clean(v))
            fh.write("\t".join(fields) + "\n")

    genre_kw, mood_kw = ex._label_keywords()
    fold: dict[str, str] = {}
    for cp in range(0xC0, 0x250):
        base = "".join(c for c in unicodedata.normalize("NFKD", chr(cp)) if not unicodedata.combining(c))
        if base and all("a" <= c.lower() <= "z" for c in base):
            fold[str(cp)] = base.lower()
    meta = {
        "fold": fold,
        "version": 1,
        "columns": COLUMNS,
        "books": len(rows),
        "prompts": {"select": SELECT_SYSTEM_PROMPT, "write": WRITE_SYSTEM_PROMPT},
        "constants": {
            "prompt_candidates": PROMPT_CANDIDATES, "description_chars": DESCRIPTION_CHARS,
            "write_base_tokens": WRITE_BASE_TOKENS, "write_tokens_per_book": WRITE_TOKENS_PER_BOOK,
        },
        "taxonomy": taxonomy.taxonomy_payload(),
        "labels": {
            "genre": {g.slug: g.label for g in taxonomy.GENRES},
            "mood": {m.slug: m.label for m in taxonomy.MOODS},
            "era": {s: lab for s, lab, _, _ in taxonomy.ERAS},
            "length": {s: lab for s, lab, _, _ in taxonomy.LENGTHS},
            "audience": dict(taxonomy.AUDIENCES),
        },
        "stopwords": sorted(ex.TURKISH_STOPWORDS),
        "expansion": {
            "themes": [[tr, subj] for tr, subj in ex._theme_reverse().items()],
            "genre_names": [[n, s] for n, s in ex._genre_name_index().items()],
            "mood_adjectives": [[a, s] for a, s in ex._mood_adjective_index().items()],
            "genre_keywords": genre_kw,
            "mood_keywords": mood_kw,
        },
    }
    (args.out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    size = (args.out / "books.tsv").stat().st_size / 1e6
    print(f"{len(rows):,} kitap, books.tsv {size:.1f} MB; meta.json "
          f"{(args.out / 'meta.json').stat().st_size / 1e3:.0f} KB")


if __name__ == "__main__":
    main()
