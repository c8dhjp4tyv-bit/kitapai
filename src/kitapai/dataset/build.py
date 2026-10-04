"""Veri kümesi üretimi: katalog → eğitim/doğrulama JSONL dosyaları.

Akış
  1. Katalogdan çalışma havuzu yüklenir (bilinirliğe göre üst dilim + rastgele
     kuyruk, böylece hem tanınan kitaplar hem uzun kuyruk temsil edilir).
  2. Her örnek için bir çekirdek kitap seçilir, ondan sentetik istek üretilir.
  3. İsteğe gerçekten uyan diğer kitaplar pozitif, uymayanlar zor olumsuz
     aday olarak listeye girer.
  4. Hedef JSON yazılır, örnek JSONL'e eklenir.

Çıktı: `data/dataset/train.jsonl`, `valid.jsonl`, `stats.json`
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from ..logging import get
from . import queries as qmod
from .tasks import Sample, build_sample, match_score

log = get("dataset.build")


@dataclass
class DatasetOptions:
    samples: int = 20_000
    valid_ratio: float = 0.04
    pool_size: int = 120_000          # bellekte tutulan çalışma havuzu
    popular_fraction: float = 0.6     # havuzun ne kadarı en bilinenlerden
    candidates: int = 14
    hard_negative_ratio: float = 0.65
    min_positive_score: float = 0.55  # ek pozitif için eşik
    #: TOHUM kitabın (asıl doğru cevap) kendi isteğine uyum eşiği. Eskiden tohum
    #: hiç denetlenmiyordu: eğitimde "sorgulatan bir kitap" için amfibi saha
    #: rehberi, "Amerika'da geçen hikâye" için ev sigortası kitabı "doğru cevap"
    #: olarak etiketlenmişti (tohumların %14'ü zayıf eşleşmeydi).
    min_seed_score: float = 0.6
    #: Tohum kitabın en az bu kadar okuyucusu olmalı (medyan 15). Kısıtsız
    #: isteklerde uyum puanı yalnızca bilinirliğe dayandığı için bu eşik, bilinmeyen
    #: kitapların belirsiz isteklere "cevap" olmasını engeller.
    min_seed_readers: int = 15
    seed: int = 20260918
    max_per_book: int = 6             # aynı kitabın kaç kez seçilebileceği
    #: Eğitim bağlamı (bkz. configs/train-*.yaml `max_seq_length`). Üretim
    #: sonunda örneklerin gerçek token uzunluğu ölçülür ve bu bütçeyi aşan
    #: örnek oranı yüksekse UYARI verilir. Neden: örnekler bağlama sığmazsa
    #: kesilen yer SONDAKİ asistan yanıtıdır, yani modelin öğrenmesi gereken
    #: tek şey. 2026-09-19'da 14 adaylı istemde örnekler 2685 token tutuyordu
    #: ve 2048'lik bağlamda %99.8'i sessizce kesiliyordu.
    token_budget: int = 3072
    tokenizer_name: str = "Qwen/Qwen2.5-3B-Instruct"


def measure_tokens(
    samples: list[Sample], tokenizer_name: str, *, sample_size: int = 300
) -> dict[str, int] | None:
    """Örneklerin gerçek token uzunlukları. Tokenizer yoksa None döner."""
    try:
        from transformers import AutoTokenizer
    except ImportError:
        log.warning("transformers kurulu değil — token uzunluğu ölçülemiyor. "
                    "Eğitim öncesi `pip install transformers` ile doğrulayın.")
        return None

    try:
        tok = AutoTokenizer.from_pretrained(tokenizer_name)
    except Exception as exc:  # ağ yok, model adı yanlış vb.
        log.warning("tokenizer yüklenemedi (%s) — token uzunluğu ölçülemiyor", exc)
        return None

    subset = samples[:sample_size]
    lengths = sorted(
        len(tok(tok.apply_chat_template(s.messages, tokenize=False)).input_ids)
        for s in subset
    )
    n = len(lengths)
    return {
        "ortalama": sum(lengths) // n,
        "medyan": lengths[n // 2],
        "p95": lengths[int(n * 0.95)],
        "max": lengths[-1],
    }


@dataclass
class DatasetStats:
    total: int = 0
    train: int = 0
    valid: int = 0
    by_style: dict[str, int] = field(default_factory=dict)
    by_task: dict[str, int] = field(default_factory=dict)
    picks_histogram: dict[int, int] = field(default_factory=dict)
    unique_books: int = 0
    avg_candidates: float = 0.0
    avg_chars: float = 0.0
    approx_tokens: int = 0
    token_lengths: dict[str, int] | None = None
    over_budget_ratio: float = 0.0

    def as_dict(self) -> dict:
        return {
            "total": self.total, "train": self.train, "valid": self.valid,
            "by_style": self.by_style, "by_task": self.by_task,
            "picks_histogram": {str(k): v for k, v in sorted(self.picks_histogram.items())},
            "unique_books": self.unique_books,
            "avg_candidates": round(self.avg_candidates, 2),
            "avg_chars": round(self.avg_chars, 1),
            "approx_tokens": self.approx_tokens,
            "token_lengths": self.token_lengths,
            "over_budget_ratio": round(self.over_budget_ratio, 4),
        }


class BookPool:
    """Bellekte tutulan, filtrelerle indekslenmiş çalışma havuzu."""

    COLUMNS = (
        "work_key, title, title_tr, authors, subjects, description, first_published, "
        "pages, languages, genres, moods, era, length_bucket, audience, rating_avg, "
        "rating_count, readers, popularity, cover_url"
    )

    def __init__(self, books: list[dict]) -> None:
        self.books = books
        self.by_key = {b["work_key"]: b for b in books}
        self.by_genre: dict[str, list[dict]] = defaultdict(list)
        self.by_mood: dict[str, list[dict]] = defaultdict(list)
        self.by_era: dict[str, list[dict]] = defaultdict(list)
        self.by_length: dict[str, list[dict]] = defaultdict(list)
        for b in books:
            for g in b.get("genres") or []:
                self.by_genre[g].append(b)
            for m in b.get("moods") or []:
                self.by_mood[m].append(b)
            if b.get("era"):
                self.by_era[b["era"]].append(b)
            if b.get("length_bucket"):
                self.by_length[b["length_bucket"]].append(b)

    def __len__(self) -> int:
        return len(self.books)

    @classmethod
    def from_catalog(
        cls,
        con: duckdb.DuckDBPyConnection,
        *,
        size: int,
        popular_fraction: float,
        seed: int,
    ) -> BookPool:
        top_n = max(1, int(size * popular_fraction))
        tail_n = max(0, size - top_n)
        con.execute(f"SELECT setseed({(seed % 1000) / 1000.0})")
        # Havuz iki parçadan oluşur: en bilinen `top_n` kitap (öneri kalitesi
        # için) ve kuyruktan rastgele `tail_n` kitap (çeşitlilik için).
        # LIMIT ve UNION'ı aynı ifadede birleştirmek yerine pencere işlevi
        # kullanılır; DuckDB parantezsiz LIMIT+UNION'ı ayrıştıramıyor.
        sql = f"""
            WITH ranked AS (
              SELECT {cls.COLUMNS},
                     row_number() OVER (ORDER BY popularity DESC, work_key) AS rn
              FROM books
            )
            SELECT {cls.COLUMNS} FROM ranked WHERE rn <= {top_n}
        """
        if tail_n:
            sql += f"""
            UNION ALL
            SELECT {cls.COLUMNS} FROM (
              SELECT {cls.COLUMNS} FROM ranked WHERE rn > {top_n}
            ) USING SAMPLE {tail_n} ROWS
            """
        rows = con.execute(sql).fetchall()
        cols = [c.strip() for c in cls.COLUMNS.split(",")]
        books = [dict(zip(cols, r, strict=True)) for r in rows]
        log.info("çalışma havuzu: %s kitap (%s popüler + %s kuyruk)",
                 f"{len(books):,}", f"{top_n:,}", f"{tail_n:,}")
        return cls(books)

    # ── örnekleme ──────────────────────────────────────────────────────────

    def matching(self, q: qmod.GeneratedQuery, rng: random.Random, *, n: int = 40) -> list[dict]:
        """İsteğin filtrelerine uyan aday kümesi (kaba ön eleme)."""
        buckets: list[list[dict]] = []
        for g in q.genres:
            if self.by_genre.get(g):
                buckets.append(self.by_genre[g])
        for m in q.moods:
            if self.by_mood.get(m):
                buckets.append(self.by_mood[m])
        if q.era and self.by_era.get(q.era):
            buckets.append(self.by_era[q.era])
        if q.length and self.by_length.get(q.length):
            buckets.append(self.by_length[q.length])
        if not buckets:
            buckets = [self.books]

        smallest = min(buckets, key=len)
        sample = rng.sample(smallest, min(len(smallest), n * 4))
        return sample

    def random_books(self, rng: random.Random, n: int) -> list[dict]:
        return rng.sample(self.books, min(max(0, n), len(self.books)))

    def hard_negatives(
        self, q: qmod.GeneratedQuery, positives: list[dict], rng: random.Random, n: int
    ) -> list[dict]:
        """İsteğe *yakın ama yanlış* kitaplar.

        Model, aynı türden olmanın yetmediğini; ruh hali, uzunluk ve dönem
        kısıtlarının da tutması gerektiğini bu örneklerden öğrenir.
        """
        taken = {b["work_key"] for b in positives}
        out: list[dict] = []

        pools: list[list[dict]] = []
        # Aynı tür, farklı ruh hali
        for g in q.genres:
            pools.append([
                b for b in self.by_genre.get(g, [])[:2000]
                if not (set(q.moods) & set(b.get("moods") or []))
            ])
        # Doğru ruh hali, farklı tür
        for m in q.moods:
            pools.append([
                b for b in self.by_mood.get(m, [])[:2000]
                if not (set(q.genres) & set(b.get("genres") or []))
            ])
        # Kısıt ihlali: yanlış uzunluk / dönem
        if q.length:
            pools.append([
                b for b in self.books[:5000] if b.get("length_bucket") != q.length
            ])
        if q.era:
            pools.append([b for b in self.books[:5000] if b.get("era") != q.era])

        pools = [p for p in pools if p]
        if not pools:
            return out
        # Havuz küçükse (ya da uygun kitapların hepsi zaten alınmışsa) sonsuz
        # döngüye girmemek için deneme sayısı sınırlıdır.
        for _ in range(n * 12):
            if len(out) >= n:
                break
            book = rng.choice(rng.choice(pools))
            if book["work_key"] in taken:
                continue
            taken.add(book["work_key"])
            out.append(book)
        return out


#: Benzerlik isteğinde ayırt edici olmayan türler: "roman" türü neredeyse her kurguda var.
GENERIC_GENRES = frozenset({"roman", "klasik"})


def _informative(book: dict, opt: DatasetOptions) -> bool:
    """Doğru cevap olabilecek kadar tanınan ve bilgi taşıyan kitap mı."""
    if int(book.get("readers") or 0) < opt.min_seed_readers:
        return False
    desc = book.get("description") or ""
    return len(book.get("subjects") or []) >= 2 or len(desc) >= 60


def _related_seed(
    pool: BookPool, anchor: dict, rng: random.Random, opt: DatasetOptions
) -> tuple[dict, str] | None:
    """"X gibi bir kitap" isteğinin doğru cevabı: X ile GERÇEKTEN ilişkili bir kitap.

    Eskiden cevap, referans kitapla hiçbir ilgisi olmayan rastgele bir tohum kitaptı
    ("Freya Marske sevenler başka ne okur" → alakasız bir kitap; bu biçemin %42'si
    zayıf eşleşmeydi). Burada cevap, referansın ayırt edici türünden seçilir ve ortak
    konu sayısına göre sıralanır.
    """
    genres = [g for g in (anchor.get("genres") or []) if g not in GENERIC_GENRES] \
        or list(anchor.get("genres") or [])
    if not genres:
        return None
    genre = rng.choice(genres)
    bucket = pool.by_genre.get(genre) or []
    if len(bucket) < 5:
        return None
    anchor_subjects = {x.lower() for x in (anchor.get("subjects") or [])}
    sample = rng.sample(bucket, min(len(bucket), 300))
    scored = []
    for b in sample:
        if b["work_key"] == anchor["work_key"] or not _informative(b, opt):
            continue
        shared = len(anchor_subjects & {x.lower() for x in (b.get("subjects") or [])})
        same_era = 0.5 if b.get("era") and b.get("era") == anchor.get("era") else 0.0
        scored.append((shared + same_era, rng.random(), b))
    if not scored:
        return None
    scored.sort(key=lambda t: (-t[0], t[1]))
    return rng.choice(scored[:10])[2], genre


def _iter_samples(
    pool: BookPool, opt: DatasetOptions, rng: random.Random
) -> list[Sample]:
    samples: list[Sample] = []
    seen_keys: dict[str, int] = defaultdict(int)
    seen_hashes: set[int] = set()

    # Bilinirliğe göre ağırlıklı çekirdek seçimi: tanınan kitaplar daha sık,
    # ama uzun kuyruk da temsil edilsin diye taban ağırlık eklenir.
    weights = [0.2 + float(b.get("popularity") or 0.0) for b in pool.books]
    # Referans kitap seçimi çok daha keskin ağırlıklı: yalnızca gerçekten
    # tanınan kitaplar "beğendiğim kitap" olarak geçsin.
    anchor_weights = [float(b.get("popularity") or 0.0) ** 3 for b in pool.books]
    if not any(anchor_weights):
        anchor_weights = weights

    attempts = 0
    max_attempts = opt.samples * 6
    while len(samples) < opt.samples and attempts < max_attempts:
        attempts += 1
        seed_book = rng.choices(pool.books, weights=weights, k=1)[0]
        if seen_keys[seed_book["work_key"]] >= opt.max_per_book:
            continue
        if not _informative(seed_book, opt):
            continue

        # "X gibi bir kitap" isteğinde referans kitap TANINMIŞ olmalı: kimse
        # "The geochemistry of natural waters gibi bir kitap arıyorum" demez.
        # Bu yüzden referans, bilinirliğe göre ağırlıklı seçilir.
        anchor = rng.choices(pool.books, weights=anchor_weights, k=1)[0] \
            if rng.random() < 0.25 else None
        q = qmod.generate(seed_book, rng, anchor=anchor)

        if q.style == "benzer" and anchor is not None:
            related = _related_seed(pool, anchor, rng, opt)
            if related is None:
                continue
            seed_book, genre = related
            q.genres = [genre]
            if seen_keys[seed_book["work_key"]] >= opt.max_per_book:
                continue

        # Tohum kitap kendi isteğine gerçekten uymalı (bkz. min_seed_score).
        if match_score(seed_book, q) < opt.min_seed_score:
            continue

        fingerprint = hash((q.text, seed_book["work_key"], q.limit))
        if fingerprint in seen_hashes:
            continue
        seen_hashes.add(fingerprint)

        # Ek pozitifler: aynı isteğe gerçekten uyan başka kitaplar
        positives = [seed_book]
        for cand in pool.matching(q, rng, n=30):
            if len(positives) >= q.limit:
                break
            if cand["work_key"] in {b["work_key"] for b in positives}:
                continue
            if match_score(cand, q) >= opt.min_positive_score:
                positives.append(cand)

        n_neg = max(0, opt.candidates - len(positives))
        n_hard = int(n_neg * opt.hard_negative_ratio)
        negatives = pool.hard_negatives(q, positives, rng, n_hard)
        negatives += pool.random_books(rng, n_neg - len(negatives) + 4)

        sample = build_sample(q, positives, negatives, rng)
        if not sample.meta["n_picks"]:
            continue

        samples.append(sample)
        for b in positives[: q.limit]:
            seen_keys[b["work_key"]] += 1

        if len(samples) % 2000 == 0:
            log.info("%s / %s örnek", f"{len(samples):,}", f"{opt.samples:,}")

    if attempts >= max_attempts:
        log.warning("örnek üretimi denemede tükendi: %s üretildi", len(samples))
    return samples


def _stats(samples: list[Sample], n_train: int) -> DatasetStats:
    st = DatasetStats(total=len(samples), train=n_train, valid=len(samples) - n_train)
    books: set[str] = set()
    chars = cands = 0
    for s in samples:
        st.by_style[s.meta["style"]] = st.by_style.get(s.meta["style"], 0) + 1
        st.by_task[s.task] = st.by_task.get(s.task, 0) + 1
        st.picks_histogram[s.meta["n_picks"]] = st.picks_histogram.get(s.meta["n_picks"], 0) + 1
        books.update(s.meta["picked_keys"])
        cands += s.meta["n_candidates"]
        chars += sum(len(m["content"]) for m in s.messages)
    n = max(1, len(samples))
    st.unique_books = len(books)
    st.avg_candidates = cands / n
    st.avg_chars = chars / n
    # Qwen tokenizer'ında Türkçe için kabaca 3.2 karakter/token (yaklaşık).
    st.approx_tokens = int(chars / 3.2)
    return st


def build_dataset(
    catalog_path: Path,
    out_dir: Path,
    options: DatasetOptions | None = None,
) -> DatasetStats:
    opt = options or DatasetOptions()
    rng = random.Random(opt.seed)
    out_dir.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(catalog_path), read_only=True)
    try:
        total_books = con.execute("SELECT count(*) FROM books").fetchone()[0]
        if total_books == 0:
            raise ValueError(f"{catalog_path} içinde kitap yok — önce katalog kur")
        pool = BookPool.from_catalog(
            con, size=min(opt.pool_size, total_books),
            popular_fraction=opt.popular_fraction, seed=opt.seed,
        )
    finally:
        con.close()

    samples = _iter_samples(pool, opt, rng)
    rng.shuffle(samples)

    n_valid = max(1, int(len(samples) * opt.valid_ratio)) if samples else 0
    valid, train = samples[:n_valid], samples[n_valid:]

    for name, subset in (("train", train), ("valid", valid)):
        path = out_dir / f"{name}.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            for s in subset:
                fh.write(s.to_json() + "\n")
        log.info("%-6s → %s (%s örnek)", name, path, f"{len(subset):,}")

    stats = _stats(samples, len(train))

    # Token bütçesi denetimi — eğitime bozuk veriyle girmemek için.
    stats.token_lengths = measure_tokens(samples, opt.tokenizer_name)
    if stats.token_lengths:
        p95 = stats.token_lengths["p95"]
        log.info("token uzunluğu: ortalama %s, medyan %s, p95 %s, max %s",
                 stats.token_lengths["ortalama"], stats.token_lengths["medyan"],
                 p95, stats.token_lengths["max"])
        if p95 > opt.token_budget:
            stats.over_budget_ratio = 1.0
            log.error(
                "ÖRNEKLER BAĞLAMA SIĞMIYOR: p95=%s > bütçe=%s. Kesilen kısım "
                "örneğin SONUNDAKİ asistan yanıtı olur ve eğitim işe yaramaz. "
                "Ya `max_seq_length`'i yükseltin ya da `prompting.PROMPT_CANDIDATES` "
                "/ `DESCRIPTION_CHARS` değerlerini düşürün.",
                p95, opt.token_budget)
        else:
            log.info("token bütçesi uygun (p95 %s ≤ %s)", p95, opt.token_budget)
    (out_dir / "stats.json").write_text(
        json.dumps(stats.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log.info("veri kümesi hazır: %s örnek, %s benzersiz kitap, ~%s token",
             f"{stats.total:,}", f"{stats.unique_books:,}", f"{stats.approx_tokens:,}")
    return stats
