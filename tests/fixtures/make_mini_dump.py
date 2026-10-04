"""Gerçek Open Library dump biçiminde küçük bir test kümesi üretir.

Amaç: 17 GB'lık gerçek dump olmadan tüm boru hattını (ayrıştırma → katalog →
veri kümesi → indeks → servis) uçtan uca çalıştırabilmek. Biçim birebir aynıdır:
5 sütunlu TSV (type, key, revision, last_modified, JSON), gzip'li.

Çalıştır:  python tests/fixtures/make_mini_dump.py
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "mini_dump"

TS = "2026-08-31T00:00:00.000000"


def row(typ: str, key: str, payload: dict) -> str:
    return "\t".join([typ, key, "1", TS, json.dumps(payload, ensure_ascii=False)])


AUTHORS = {
    "/authors/OL1A": {"name": "Frank Herbert", "birth_date": "1920"},
    "/authors/OL2A": {"name": "George Orwell", "birth_date": "1903"},
    "/authors/OL3A": {"name": "J. R. R. Tolkien", "birth_date": "1892"},
    "/authors/OL4A": {"name": "Agatha Christie", "birth_date": "1890"},
    "/authors/OL5A": {"name": "Marcus Aurelius"},
    "/authors/OL6A": {"name": "Ursula K. Le Guin", "birth_date": "1929"},
    "/authors/OL7A": {"name": "Carl Sagan", "birth_date": "1934"},
    "/authors/OL8A": {"name": "Jane Austen", "birth_date": "1775"},
    "/authors/OL9A": {"name": "Haruki Murakami", "birth_date": "1949"},
    "/authors/OL10A": {"name": "Yuval Noah Harari", "birth_date": "1976"},
    "/authors/OL11A": {"name": "Terry Pratchett", "birth_date": "1948"},
    "/authors/OL12A": {"name": "Mary Shelley", "birth_date": "1797"},
}

# (work_key, başlık, yazar anahtarları, konular, açıklama, ilk yayın, kapak)
WORKS = [
    ("/works/OL1W", "Dune", ["/authors/OL1A"],
     ["Science fiction", "Space flight", "Desert", "Ecology", "Epic", "Politics and government"],
     "A desert planet, a noble family's fall, and a messianic uprising that reshapes an empire.",
     "1965", 101),
    ("/works/OL2W", "Nineteen Eighty-Four", ["/authors/OL2A"],
     ["Fiction", "Dystopias", "Totalitarianism", "Surveillance", "Political fiction"],
     "A bleak vision of a surveillance state where language itself is a weapon.",
     "1949", 102),
    ("/works/OL3W", "The Hobbit", ["/authors/OL3A"],
     ["Fantasy", "Adventure", "Dragons", "Quests", "Juvenile fiction", "Imaginary places"],
     "A reluctant hobbit is swept into a quest for a dragon-guarded treasure.",
     "1937", 103),
    ("/works/OL4W", "Murder on the Orient Express", ["/authors/OL4A"],
     ["Detective and mystery stories", "Crime", "Murder", "Private investigators"],
     "A detective trapped on a snowbound train must unmask a killer among the passengers.",
     "1934", 104),
    ("/works/OL5W", "Meditations", ["/authors/OL5A"],
     ["Philosophy", "Stoicism", "Ethics", "Conduct of life", "Meditation"],
     "Private notes of a Roman emperor on duty, mortality and self-mastery.",
     "180", 105),
    ("/works/OL6W", "The Left Hand of Darkness", ["/authors/OL6A"],
     ["Science fiction", "Gender identity", "Anthropology", "Winter", "Diplomacy"],
     "An envoy on an icebound world learns that gender, loyalty and trust are all negotiable.",
     "1969", 106),
    ("/works/OL7W", "Cosmos", ["/authors/OL7A"],
     ["Science", "Astronomy", "Cosmology", "Popular works", "Evolution"],
     "A tour of the universe that ties human history to the physics of stars.",
     "1980", 107),
    ("/works/OL8W", "Pride and Prejudice", ["/authors/OL8A"],
     ["Fiction", "Romance", "Love stories", "Courtship", "Classic Literature",
      "Man-woman relationships", "Social classes"],
     "Wit, pride and misjudgement collide in Regency England.",
     "1813", 108),
    ("/works/OL9W", "Kafka on the Shore", ["/authors/OL9A"],
     ["Fiction", "Magic realism", "Dreams", "Loneliness", "Fate and fatalism"],
     "Two strange journeys converge in a dreamlike Japan where cats talk and fish fall from the sky.",
     "2002", 109),
    ("/works/OL10W", "Sapiens: A Brief History of Humankind", ["/authors/OL10A"],
     ["History", "Civilization", "Human evolution", "Social science", "Anthropology"],
     "How an unremarkable ape came to dominate the planet, told as a history of shared fictions.",
     "2011", 110),
    ("/works/OL11W", "Good Omens", ["/authors/OL11A", "/authors/OL3A"],
     ["Fiction", "Humor", "Satire", "Fantasy", "Angels", "Demons", "End of the world"],
     "An angel and a demon team up to stop an apocalypse neither of them wants.",
     "1990", 111),
    ("/works/OL12W", "Frankenstein", ["/authors/OL12A"],
     ["Horror", "Gothic fiction", "Science fiction", "Monsters", "Classic Literature", "Death"],
     "A student assembles life from dead matter and is destroyed by what he abandons.",
     "1818", 112),
    # Kalite filtresini test etmek için: başlıksız / konusuz / hiç okunmamış kayıtlar
    ("/works/OL90W", "", ["/authors/OL1A"], [], None, None, None),
    ("/works/OL91W", "Untitled Draft Manuscript", [], [], None, None, None),
]

EDITIONS = [
    # (edition_key, work_key, başlık, sayfa, diller, isbn13, yıl, kapak)
    ("/books/OL1M", "/works/OL1W", "Dune", 412, ["eng"], "9780441013593", "1990", 101),
    ("/books/OL2M", "/works/OL1W", "Dune (Çöl Gezegeni)", 640, ["tur"], "9789752119109", "2019", 201),
    ("/books/OL3M", "/works/OL2W", "1984", 328, ["eng"], "9780451524935", "1961", 102),
    ("/books/OL4M", "/works/OL2W", "Bin Dokuz Yüz Seksen Dört", 352, ["tur"], "9789750718533", "2014", 202),
    ("/books/OL5M", "/works/OL3W", "The Hobbit", 310, ["eng"], "9780547928227", "2012", 103),
    ("/books/OL6M", "/works/OL4W", "Murder on the Orient Express", 274, ["eng"], "9780062693662", "2017", 104),
    ("/books/OL7M", "/works/OL5W", "Meditations", 254, ["eng"], "9780140449334", "2006", 105),
    ("/books/OL8M", "/works/OL6W", "The Left Hand of Darkness", 304, ["eng"], "9780441478125", "2000", 106),
    ("/books/OL9M", "/works/OL7W", "Cosmos", 396, ["eng"], "9780345539434", "2013", 107),
    ("/books/OL10M", "/works/OL8W", "Pride and Prejudice", 279, ["eng"], "9780141439518", "2003", 108),
    ("/books/OL11M", "/works/OL9W", "Kafka on the Shore", 505, ["eng"], "9781400079278", "2006", 109),
    ("/books/OL12M", "/works/OL10W", "Sapiens", 443, ["eng"], "9780062316097", "2015", 110),
    ("/books/OL13M", "/works/OL11W", "Good Omens", 288, ["eng"], "9780060853983", "2006", 111),
    ("/books/OL14M", "/works/OL12W", "Frankenstein", 280, ["eng"], "9780486282114", "1994", 112),
    ("/books/OL15M", "/works/OL12W", "Frankenstein", 216, ["tur"], "9789750738616", "2016", 212),
    ("/books/OL99M", "/works/OL91W", "Untitled Draft Manuscript", None, [], None, None, None),
]

# (work_key, edition_key, puan) — /api/ratings dump biçimi
RATINGS = [
    ("/works/OL1W", "/books/OL1M", 5), ("/works/OL1W", "/books/OL1M", 5),
    ("/works/OL1W", "/books/OL2M", 4), ("/works/OL1W", "/books/OL1M", 4),
    ("/works/OL2W", "/books/OL3M", 5), ("/works/OL2W", "/books/OL3M", 4),
    ("/works/OL2W", "/books/OL4M", 5),
    ("/works/OL3W", "/books/OL5M", 5), ("/works/OL3W", "/books/OL5M", 5),
    ("/works/OL4W", "/books/OL6M", 4), ("/works/OL5W", "/books/OL7M", 5),
    ("/works/OL6W", "/books/OL8M", 4), ("/works/OL7W", "/books/OL9M", 5),
    ("/works/OL8W", "/books/OL10M", 4), ("/works/OL9W", "/books/OL11M", 4),
    ("/works/OL10W", "/books/OL12M", 4), ("/works/OL11W", "/books/OL13M", 5),
    ("/works/OL12W", "/books/OL14M", 3),
]

# (work_key, edition_key, raf) — 1=okunacak 2=okunuyor 3=okundu
READING_LOG = [
    ("/works/OL1W", "/books/OL1M", 3), ("/works/OL1W", "/books/OL1M", 1),
    ("/works/OL1W", "/books/OL2M", 1), ("/works/OL2W", "/books/OL3M", 3),
    ("/works/OL2W", "/books/OL3M", 3), ("/works/OL3W", "/books/OL5M", 3),
    ("/works/OL4W", "/books/OL6M", 1), ("/works/OL5W", "/books/OL7M", 2),
    ("/works/OL6W", "/books/OL8M", 3), ("/works/OL7W", "/books/OL9M", 1),
    ("/works/OL8W", "/books/OL10M", 3), ("/works/OL9W", "/books/OL11M", 2),
    ("/works/OL10W", "/books/OL12M", 3), ("/works/OL11W", "/books/OL13M", 1),
    ("/works/OL12W", "/books/OL14M", 3),
]


def write(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for ln in lines:
            fh.write(ln + "\n")
    print(f"  {path.name:38} {len(lines):>5} satır")


def main() -> None:
    print(f"mini dump → {OUT}")

    write(OUT / "ol_dump_authors_mini.txt.gz", [
        row("/type/author", k, {"key": k, **v}) for k, v in AUTHORS.items()
    ])

    work_rows = []
    for key, title, authors, subjects, desc, first, cover in WORKS:
        payload: dict = {"key": key, "type": {"key": "/type/work"}, "title": title}
        if authors:
            payload["authors"] = [
                {"author": {"key": a}, "type": {"key": "/type/author_role"}} for a in authors
            ]
        if subjects:
            payload["subjects"] = subjects
        if desc:
            # Open Library açıklamayı hem düz metin hem {type,value} olarak tutar;
            # ayrıştırıcının ikisini de kaldırdığını görmek için karıştırıyoruz.
            payload["description"] = (
                desc if key.endswith(("1W", "3W", "5W"))
                else {"type": "/type/text", "value": desc}
            )
        if first:
            payload["first_publish_date"] = first
        if cover:
            payload["covers"] = [cover]
        work_rows.append(row("/type/work", key, payload))
    write(OUT / "ol_dump_works_mini.txt.gz", work_rows)

    ed_rows = []
    for key, work, title, pages, langs, isbn, year, cover in EDITIONS:
        payload = {"key": key, "type": {"key": "/type/edition"}, "title": title,
                   "works": [{"key": work}]}
        if pages:
            payload["number_of_pages"] = pages
        if langs:
            payload["languages"] = [{"key": f"/languages/{lang}"} for lang in langs]
        if isbn:
            payload["isbn_13"] = [isbn]
        if year:
            payload["publish_date"] = year
        if cover:
            payload["covers"] = [cover]
        ed_rows.append(row("/type/edition", key, payload))
    write(OUT / "ol_dump_editions_mini.txt.gz", ed_rows)

    write(OUT / "ol_dump_ratings_mini.txt.gz",
          ["\t".join([w, e, str(r), "2026-01-01"]) for w, e, r in RATINGS])
    write(OUT / "ol_dump_reading-log_mini.txt.gz",
          ["\t".join([w, e, str(s), "2026-01-01"]) for w, e, s in READING_LOG])

    print("tamam")


if __name__ == "__main__":
    main()
