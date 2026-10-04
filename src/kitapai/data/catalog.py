"""Open Library dump'larından sorgulanabilir katalog üretir.

Neden DuckDB? Gerçek dump'lar ~40 milyon baskı ve ~30 milyon eser içerir.
Bunları Python döngüsünde JSON olarak ayrıştırmak saatler sürer ve belleğe
sığmaz. DuckDB gz'li TSV'yi doğrudan akıtarak okur, JSON alanlarını C++
tarafında çıkarır, birleştirmeleri diske taşarak yapar. Etiketleme desenleri
`taxonomy.py`'den SQL'e derlenir — tek kaynak ilkesi korunur.

Çıktı tek dosya: `data/catalog.duckdb`
  books         → denormalize edilmiş, etiketlenmiş eser tablosu
  catalog_meta  → yeniden üretilebilirlik için derleme künyesi
  + `books` üzerinde BM25 tam metin indeksi
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import duckdb

from .. import taxonomy
from ..logging import get
from .sources import DumpSources

log = get("data.catalog")

# Dump satırı: type, key, revision, last_modified, JSON
_DUMP_COLUMNS = (
    "{'type':'VARCHAR','key':'VARCHAR','revision':'VARCHAR',"
    "'last_modified':'VARCHAR','js':'VARCHAR'}"
)
# Puan/okuma kaydı dump'ları 4 sütunludur ve JSON içermez.
_LOG_COLUMNS = (
    "{'work':'VARCHAR','edition':'VARCHAR','value':'VARCHAR','logged_at':'VARCHAR'}"
)

_YEAR_RE = "(1[0-9]{3}|20[0-9]{2})"


@dataclass
class BuildOptions:
    """Katalogun kapsamı ve kalite eşiği.

    Varsayılanlar "geniş ama çöpsüz" olacak şekilde seçildi: bir eserin
    katalogda kalması için ya okunmuş/puanlanmış olması ya da birden fazla
    baskısının bulunması gerekir. Böylece 30M ham eser ~1.5-3M gerçek kitaba
    iner; hem indeks küçülür hem öneriler tanınabilir kitaplardan gelir.
    """

    limit_works: int | None = None      # geliştirme koşuları için
    limit_editions: int | None = None
    min_rating_count: int = 0
    min_readers: int = 0
    #: Katalogu okuma sinyali belirler: bir eserin kalması için Open Library'de
    #: puanlanmış VEYA raflanmış olması gerekir. Baskı sayısını sinyal olarak
    #: kullanmak cazip görünüyor ama 30 milyon eser için baskı toplaması
    #: yapmayı zorunlu kılıyor ve DuckDB'yi diske taşırıyor (13 GB+). Üstelik
    #: kimsenin okumadığı eserler bir öneri motoru için zaten gürültü.
    #: Baskılar bu yüzden yalnızca *zenginleştirme* için kullanılır:
    #: sayfa, ISBN, dil, kapak, Türkçe başlık.
    require_signal: bool = True
    require_text: bool = True           # konu VEYA açıklama
    min_title_chars: int = 2
    max_subjects: int = 24
    max_genres: int = 4
    max_isbns: int = 8
    memory_limit: str = "3GB"
    threads: int = 4
    temp_dir: str | None = None
    #: Taşma alanı için diskte bırakılacak pay (GiB). DuckDB aksi hâlde diski
    #: sonuna kadar doldurabiliyor.
    reserve_gib: float = 3.0  # üst sınır; dar diskte boş alanın %25'ine iner
    preserve_stages: bool = False       # ara tabloları silme (hata ayıklama)
    #: Yarım kalmış bir katalogu kaldığı yerden sürdür. `editions` aşaması
    #: uzak akışta saatler sürüyor; ağ kopması, bellek hatası ya da oturumun
    #: kapanması bütün işi çöpe atmasın diye tamamlanmış aşamalar atlanır.
    resume: bool = False
    #: Baskı dump'ını hiç işleme. 11.7 GB'lık `editions` dosyası uzaktan
    #: akıtıldığında saatler sürüyor ve archive.org bağlantıyı donduruyor;
    #: dar diskte katalogu önce okuma sinyalleriyle kurup baskı verisini
    #: (sayfa, ISBN, dil, Türkçe başlık, kapak yedeği) sonradan eklemek
    #: makul bir ara adım. Bu alanlar o zamana kadar boş kalır.
    skip_editions: bool = False
    #: Bu aşamadan sonra dur. Dar diskte derlemeyi ikiye bölmek için: önce
    #: `prelim`e kadar kur, aradaki `works` dump'ını (3.8 GB) sil, sonra
    #: `--resume` ile baskı aşamasından devam et.
    stop_after: str | None = None


@dataclass
class BuildReport:
    stages: dict[str, int] = field(default_factory=dict)
    seconds: dict[str, float] = field(default_factory=dict)
    books: int = 0
    catalog_path: str = ""
    dump_date: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def _read_dump(
    path: str | None, *, limit: int | None = None, log_format: bool = False
) -> str:
    """Dump dosyası için `read_csv` ifadesi üretir (yerel yol veya https)."""
    if not path:
        raise FileNotFoundError(
            "Bu aşama için gereken dump yok. Tamamlanmış aşamaları atlamak için "
            "`--resume` kullanın; eksik dump'ı indirmek için `kitapai data download`."
        )
    columns = _LOG_COLUMNS if log_format else _DUMP_COLUMNS
    escaped = str(path).replace("'", "''")
    expr = (
        f"read_csv('{escaped}', delim='\t', header=false, quote='', escape='', "
        f"columns={columns}, ignore_errors=true, nullstr='', "
        f"auto_detect=false, parallel=true)"
    )
    if limit:
        return f"(SELECT * FROM {expr} LIMIT {limit})"
    return expr


def connect(db_path: Path, options: BuildOptions) -> duckdb.DuckDBPyConnection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    con.execute(f"SET memory_limit='{options.memory_limit}'")
    con.execute(f"SET threads={options.threads}")
    if options.temp_dir:
        temp_path = Path(options.temp_dir)
        temp_path.mkdir(parents=True, exist_ok=True)
        con.execute(f"SET temp_directory='{options.temp_dir}'")
        # DuckDB varsayılan olarak diskin TAMAMINI taşma alanı sayar; bir
        # toplama kaçarsa disk %100 doluyor ve sistem zarar görüyor. Payı
        # kendimiz bırakıyoruz: boş alanın bir kısmı her zaman boş kalsın.
        free_gib = shutil.disk_usage(temp_path).free / 2**30
        # Pay sabit olursa disk daraldıkça bütçe sıfıra iniyor ve en küçük
        # taşma bile derlemeyi öldürüyor. Bu yüzden pay, boş alanın bir oranı
        # ile sınırlanıyor: dar diskte küçülür, geniş diskte korunur.
        reserve = min(options.reserve_gib, free_gib * 0.25)
        budget = max(1.0, free_gib - reserve)
        con.execute(f"SET max_temp_directory_size='{budget:.1f}GiB'")
        log.info("taşma alanı: %s (en fazla %.1f GiB, %.1f GiB boş)",
                 options.temp_dir, budget, free_gib)
    con.execute("SET preserve_insertion_order=false")  # birleştirmelerde bellek tasarrufu
    return con


#: Uzak akış için DuckDB httpfs ayarları. Varsayılanlar (3 deneme, 100 ms
#: bekleme, 30 sn zaman aşımı) archive.org için fazla iyimser: 12 GB'lık bir
#: dosyayı saatlerce okurken kopma kaçınılmaz ve tek bir hata tüm derlemeyi
#: çöpe atar. Bu yüzden deneme sayısı ve bekleme süresi yükseltilir.
_HTTPFS_SETTINGS = {
    "http_retries": "20",
    "http_retry_wait_ms": "2000",
    "http_retry_backoff": "2",
    "http_timeout": "120",
    "http_keep_alive": "true",
}


def _ensure_httpfs(con: duckdb.DuckDBPyConnection, sources: DumpSources) -> None:
    if not sources.is_remote():
        return
    con.execute("INSTALL httpfs")
    con.execute("LOAD httpfs")
    for key, value in _HTTPFS_SETTINGS.items():
        try:
            con.execute(f"SET {key}='{value}'")
        except duckdb.Error as exc:  # sürüm farkı ölümcül olmasın
            log.warning("httpfs ayarı uygulanamadı (%s): %s", key, exc)
    log.info("uzak akış modu: dump'lar diske yazılmadan işlenecek "
             "(kopmalarda %s denemeye kadar sürdürülür)", _HTTPFS_SETTINGS["http_retries"])


class CatalogBuilder:
    """Dump → katalog dönüşümünü aşamalara bölerek yürütür."""

    def __init__(
        self,
        con: duckdb.DuckDBPyConnection,
        sources: DumpSources,
        options: BuildOptions | None = None,
    ) -> None:
        self.con = con
        self.sources = sources
        self.opt = options or BuildOptions()
        self.report = BuildReport()

    # ── yardımcılar ────────────────────────────────────────────────────────

    def _table_exists(self, name: str) -> bool:
        row = self.con.execute(
            "SELECT count(*) FROM duckdb_tables() WHERE table_name = ?", [name]
        ).fetchone()
        return bool(row and row[0])

    def _run(self, name: str, sql: str, *, count_table: str | None = None) -> int:
        table = count_table or name
        if self.opt.resume and self._table_exists(table):
            rows = self.con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            self.report.stages[name] = rows
            log.info("%-14s %10s satır  (mevcut — atlandı)", name, f"{rows:,}")
            return rows
        started = time.perf_counter()
        self.con.execute(sql)
        elapsed = time.perf_counter() - started
        table = count_table or name
        rows = self.con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        self.report.stages[name] = rows
        self.report.seconds[name] = round(elapsed, 2)
        log.info("%-14s %10s satır  (%.1fs)", name, f"{rows:,}", elapsed)
        return rows

    # ── aşamalar ───────────────────────────────────────────────────────────

    def stage_authors(self) -> None:
        self._run("authors", f"""
            CREATE OR REPLACE TABLE authors AS
            SELECT key AS author_key, name FROM (
              SELECT key,
                     coalesce(json_extract_string(js, '$.name'),
                              json_extract_string(js, '$.personal_name')) AS name
              FROM {_read_dump(self.sources.authors)}
              WHERE type = '/type/author'
            ) WHERE name IS NOT NULL AND length(trim(name)) > 0
        """)

    def stage_prelim(self) -> None:
        """Eser dump'ını okurken aday kümeyi doğrudan çıkarır.

        Ayrı bir `works` tablosu bilinçli olarak üretilmiyor: 21.5 milyon eseri
        diske yazmak ~3.5 GB tutuyor ve dar diskte derlemeyi durduruyor. Oysa
        eserlerin yalnızca ~%11'i Open Library'de puanlanmış ya da raflanmış.
        Puan/okuma tabloları küçük olduğu için önce onlar kuruluyor, dump
        akarken yarı-birleştirmeyle eleniyor ve diske yalnızca aday eserler
        yazılıyor.

        Metin filtresi de burada: konusu ve açıklaması olmayan eser zaten
        etiketlenemiyor.
        """
        opt = self.opt
        text_filter = (
            "AND (len(subjects) > 0 OR description IS NOT NULL)"
            if opt.require_text else ""
        )
        signal = (
            f"""
            WITH signal AS (
              SELECT work_key FROM ratings WHERE rating_count > {opt.min_rating_count}
              UNION
              SELECT work_key FROM readers WHERE readers > {opt.min_readers}
            )"""
            if opt.require_signal else
            "WITH signal AS (SELECT work_key FROM ratings UNION SELECT work_key FROM readers)"
        )
        join = "JOIN signal g ON g.work_key = w.work_key" if opt.require_signal else ""

        self._run("prelim", f"""
            CREATE OR REPLACE TABLE prelim AS
            {signal}
            SELECT w.*, r.rating_count, r.rating_avg, rd.readers, rd.finished
            FROM (
              SELECT * FROM (
                SELECT
                  key AS work_key,
                  trim(coalesce(json_extract_string(js, '$.title'), '')) AS title,
                  json_extract_string(js, '$.subtitle') AS subtitle,
                  coalesce(try_cast(json_extract_string(js, '$.authors[*].author.key')
                                    AS VARCHAR[]), []::VARCHAR[]) AS author_keys,
                  {self._subjects_expr()} AS subjects,
                  coalesce(json_extract_string(js, '$.description.value'),
                           json_extract_string(js, '$.description')) AS description,
                  try_cast(regexp_extract(
                    coalesce(json_extract_string(js, '$.first_publish_date'), ''),
                    '{_YEAR_RE}') AS INTEGER) AS work_year,
                  try_cast(json_extract(js, '$.covers[0]') AS INTEGER) AS work_cover
                FROM {_read_dump(self.sources.works, limit=opt.limit_works)}
                WHERE type = '/type/work'
              )
              WHERE length(title) >= {opt.min_title_chars}
                {text_filter}
            ) w
            {join}
            LEFT JOIN ratings  r  ON r.work_key = w.work_key
            LEFT JOIN readers  rd ON rd.work_key = w.work_key
        """)
        for table in ("ratings", "readers"):
            self.con.execute(f"DROP TABLE IF EXISTS {table}")
        self.con.execute("CHECKPOINT")

    def _subjects_expr(self) -> str:
        """Konu listesi: alt türler birleştirilir, makine etiketleri ayıklanır."""
        return f"""list_filter(list_distinct(list_concat(
                  coalesce(try_cast(json_extract(js, '$.subjects') AS VARCHAR[]), []::VARCHAR[]),
                  list_concat(
                    coalesce(try_cast(json_extract(js, '$.subject_places')
                             AS VARCHAR[]), []::VARCHAR[]),
                    list_concat(
                      coalesce(try_cast(json_extract(js, '$.subject_people')
                               AS VARCHAR[]), []::VARCHAR[]),
                      coalesce(try_cast(json_extract(js, '$.subject_times')
                               AS VARCHAR[]), []::VARCHAR[])
                    )))), s -> NOT regexp_matches(lower(s),
                      '^(nyt|ol|award|amazon):|new york times bestseller|'
                      '^long now manual|^accessible book$|^protected daisy$|'
                      '^in library$|^overdrive$|^internet archive wishlist$')
                  )[1:{self.opt.max_subjects}]"""

    def stage_editions(self) -> None:
        """Baskıları esere indirger: sayfa, dil, ISBN, kapak, Türkçe başlık."""
        if self.opt.skip_editions or not self.sources.editions:
            # Boş ama şema-uyumlu tablo: `candidates` LEFT JOIN'i bozulmaz,
            # baskıdan gelen alanlar NULL kalır.
            self.con.execute("""
                CREATE OR REPLACE TABLE editions AS SELECT
                  ''::VARCHAR AS work_key, 0::BIGINT AS edition_count,
                  NULL::INTEGER AS pages, NULL::INTEGER AS earliest_edition_year,
                  []::VARCHAR[] AS languages, []::VARCHAR[] AS isbns,
                  NULL::INTEGER AS edition_cover, NULL::VARCHAR AS title_tr
                WHERE false
            """)
            self.report.stages["editions"] = 0
            log.warning("baskı dump'ı atlandı — sayfa/ISBN/dil/Türkçe başlık "
                        "alanları boş kalacak (sonradan --resume ile eklenebilir)")
            return
        self._run("editions", f"""
            CREATE OR REPLACE TABLE editions AS
            WITH e AS (
              SELECT
                json_extract_string(js, '$.works[0].key') AS work_key,
                try_cast(json_extract_string(js, '$.number_of_pages') AS INTEGER) AS pages,
                list_transform(
                  coalesce(try_cast(json_extract_string(js, '$.languages[*].key')
                                    AS VARCHAR[]), []::VARCHAR[]),
                  x -> replace(x, '/languages/', '')) AS langs,
                list_concat(
                  coalesce(try_cast(json_extract(js, '$.isbn_13') AS VARCHAR[]), []::VARCHAR[]),
                  coalesce(try_cast(json_extract(js, '$.isbn_10') AS VARCHAR[]), []::VARCHAR[])
                ) AS isbns,
                try_cast(json_extract(js, '$.covers[0]') AS INTEGER) AS cover,
                try_cast(regexp_extract(
                  coalesce(json_extract_string(js, '$.publish_date'), ''),
                  '{_YEAR_RE}') AS INTEGER) AS year,
                trim(coalesce(json_extract_string(js, '$.title'), '')) AS title
              FROM {_read_dump(self.sources.editions, limit=self.opt.limit_editions)}
              WHERE type = '/type/edition'
            )
            -- Yalnızca aday eserlerin baskıları toplanır. Bu yarı-birleştirme
            -- olmadan grup sayısı ~30 milyon oluyor ve toplama diske taşıyor.
            SELECT
              work_key,
              count(*)                                              AS edition_count,
              -- `median` tüm değerleri bellekte tutar; 30M grupta taşar.
              -- Ortalama, sayfa kovalarını (kısa/orta/uzun) neredeyse hiç
              -- değiştirmiyor ve diske taşabiliyor.
              cast(avg(pages) FILTER (
                   WHERE pages BETWEEN 10 AND 5000) AS INTEGER)     AS pages,
              min(year) FILTER (WHERE year IS NOT NULL)             AS earliest_edition_year,
              -- Dil listesi `flatten(list(...))` ile toplanınca 50M satırda
              -- belleği patlatıyordu. Varlık bayrağı ucuz ve diske taşabiliyor;
              -- API zaten bu diller üzerinden filtreliyor ve gösteriyor.
              list_concat(
                CASE WHEN bool_or(list_contains(langs, 'tur'))
                     THEN ['tur'] ELSE []::VARCHAR[] END,
                list_concat(
                  CASE WHEN bool_or(list_contains(langs, 'eng'))
                       THEN ['eng'] ELSE []::VARCHAR[] END,
                  list_concat(
                    CASE WHEN bool_or(list_contains(langs, 'ger'))
                         THEN ['ger'] ELSE []::VARCHAR[] END,
                    CASE WHEN bool_or(list_contains(langs, 'fre'))
                         THEN ['fre'] ELSE []::VARCHAR[] END
                  )))                                               AS languages,
              -- Tüm ISBN'leri biriktirmek belleği şişiriyor (50M satır).
              -- Bunun yerine üç temsilci baskının ISBN'leri alınır: en dolu
              -- baskı, en dolu TÜRKÇE baskı ve en dolu İngilizce baskı.
              -- Türkçe baskıyı bulmak uygulamanın ana işlevlerinden biri.
              list_distinct(list_concat(
                coalesce(arg_max(isbns, coalesce(pages, 0))
                         FILTER (WHERE len(isbns) > 0), []::VARCHAR[]),
                list_concat(
                  coalesce(arg_max(isbns, coalesce(pages, 0)) FILTER (
                           WHERE len(isbns) > 0 AND list_contains(langs, 'tur')),
                           []::VARCHAR[]),
                  coalesce(arg_max(isbns, coalesce(pages, 0)) FILTER (
                           WHERE len(isbns) > 0 AND list_contains(langs, 'eng')),
                           []::VARCHAR[]))
              ))[1:{self.opt.max_isbns}]                            AS isbns,
              max(cover) FILTER (WHERE cover IS NOT NULL)           AS edition_cover,
              any_value(title) FILTER (
                   WHERE list_contains(langs, 'tur') AND length(title) > 1) AS title_tr
            FROM e
            WHERE work_key IS NOT NULL
              AND work_key IN (SELECT work_key FROM prelim)
            GROUP BY work_key
        """)

    def stage_ratings(self) -> None:
        if not self.sources.ratings:
            self.con.execute(
                "CREATE OR REPLACE TABLE ratings AS "
                "SELECT ''::VARCHAR AS work_key, 0::BIGINT AS rating_count, "
                "0.0::DOUBLE AS rating_avg WHERE false"
            )
            self.report.stages["ratings"] = 0
            return
        self._run("ratings", f"""
            CREATE OR REPLACE TABLE ratings AS
            SELECT work AS work_key,
                   count(*)                                   AS rating_count,
                   round(avg(try_cast(value AS DOUBLE)), 3)   AS rating_avg
            FROM {_read_dump(self.sources.ratings, log_format=True)}
            WHERE work LIKE '/works/%' AND try_cast(value AS INTEGER) BETWEEN 1 AND 5
            GROUP BY work
        """)

    def stage_readers(self) -> None:
        if not self.sources.reading_log:
            self.con.execute(
                "CREATE OR REPLACE TABLE readers AS "
                "SELECT ''::VARCHAR AS work_key, 0::BIGINT AS readers, "
                "0::BIGINT AS finished, 0::BIGINT AS want_to_read WHERE false"
            )
            self.report.stages["readers"] = 0
            return
        self._run("readers", f"""
            CREATE OR REPLACE TABLE readers AS
            SELECT work AS work_key,
                   count(*)                                AS readers,
                   count(*) FILTER (WHERE value = '3')     AS finished,
                   count(*) FILTER (WHERE value = '1')     AS want_to_read
            FROM {_read_dump(self.sources.reading_log, log_format=True)}
            WHERE work LIKE '/works/%'
            GROUP BY work
        """)

    def stage_candidates(self) -> None:
        """Birleştirme + sinyal filtresi — yazar adları henüz çözülmeden.

        Sıralama önemli: 21.5 milyon eserin yazarlarını çözmek `list()`
        toplaması gerektiriyor ve bellekte taşıyor. Oysa sinyal filtresinden
        (puan VEYA okur VEYA birden çok baskı) sonra geriye birkaç milyon eser
        kalıyor. Yazarları yalnızca onlar için çözmek hem belleği kurtarıyor
        hem de aşamayı birkaç kat hızlandırıyor.
        """
        self._run("candidates", """
            CREATE OR REPLACE TABLE candidates AS
            SELECT
              p.work_key, p.title, nullif(p.subtitle, '') AS subtitle, p.author_keys,
              e.title_tr, p.subjects, p.description,
              coalesce(p.work_year, e.earliest_edition_year)  AS first_published,
              nullif(coalesce(e.pages, 0), 0)                 AS pages,
              coalesce(e.languages, []::VARCHAR[])            AS languages,
              coalesce(e.isbns, []::VARCHAR[])                AS isbns,
              coalesce(p.work_cover, e.edition_cover)         AS cover_id,
              coalesce(e.edition_count, 0)                    AS edition_count,
              coalesce(p.rating_count, 0)                     AS rating_count,
              p.rating_avg,
              coalesce(p.readers, 0)                          AS readers,
              coalesce(p.finished, 0)                         AS finished
            FROM prelim p
            LEFT JOIN editions e ON e.work_key = p.work_key
        """)

        # Aday listesi çıkarıldıktan sonra kaynak tablolara gerek yok.
        # Tam dump'ta bunlar birkaç GB tutuyor; erken bırakmak derlemenin
        # zirve disk kullanımını belirgin şekilde düşürüyor.
        for table in ("prelim", "editions"):
            self.con.execute(f"DROP TABLE IF EXISTS {table}")
        self.con.execute("CHECKPOINT")

    def stage_work_authors(self) -> None:
        """Yazar anahtarlarını ada çevirir.

        Lambda içinde alt sorgu DuckDB'de desteklenmediği için anahtarlar
        açılıp (unnest) `authors` tablosuyla birleştirilir ve sıra korunarak
        yeniden listelenir. Bu aynı zamanda ilişkisel birleştirme olduğu için
        milyonlarca satırda korelasyonlu alt sorgudan çok daha hızlıdır.
        """
        self._run("work_authors", """
            CREATE OR REPLACE TABLE work_authors AS
            SELECT work_key, list(name ORDER BY idx) AS authors
            FROM (
              SELECT x.work_key, x.idx, a.name
              FROM (
                SELECT work_key,
                       unnest(author_keys) AS author_key,
                       generate_subscripts(author_keys, 1) AS idx
                FROM candidates
              ) x
              JOIN authors a ON a.author_key = x.author_key
            )
            GROUP BY work_key
        """)

    def stage_books(self) -> None:
        """Etiketleme ve nihai tablo. Filtreleme `stage_candidates`'te yapıldı."""
        opt = self.opt
        genres_sql = taxonomy.sql_genres_expr("subject_text", max_genres=opt.max_genres)
        moods_sql = taxonomy.sql_moods_expr("search_text", "genres")
        moods_dedup = taxonomy.sql_dedup_ordered("moods_raw", limit=4)

        self._run("books", f"""
            CREATE OR REPLACE TABLE books AS
            WITH joined AS (
              SELECT c.* EXCLUDE (author_keys),
                     coalesce(wa.authors, []::VARCHAR[]) AS authors
              FROM candidates c
              LEFT JOIN work_authors wa ON wa.work_key = c.work_key
            ),
            texted AS (
              SELECT *,
                lower(concat_ws(' | ',
                  title, coalesce(subtitle,''), array_to_string(authors, ', '),
                  array_to_string(subjects, ' | '), coalesce(description,''))) AS search_text,
                -- Tür tespiti YALNIZCA konulara bakar. Başlık da açıklama da
                -- desenleri yanlış tetikliyor: "Harry Potter and the
                -- Philosopher's Stone" felsefe, "...a Roman emperor" roman
                -- etiketi alıyordu. Bedeli ~47 bin kitabın tür etiketini
                -- kaybetmesi (%1.9); karşılığında popüler kitaplarda görünen
                -- yanlış etiketler ortadan kalkıyor.
                lower(array_to_string(subjects, ' | ')) AS subject_text
              FROM joined
            ),
            labeled AS (
              SELECT *, {genres_sql} AS genres FROM texted
            ),
            mooded AS (
              -- Ruh halleri önce ham hâliyle hesaplanır; tekilleştirme sıra
              -- korunarak bir sonraki adımda yapılır (bkz. sql_dedup_ordered).
              SELECT *, {moods_sql} AS moods_raw FROM labeled
            )
            SELECT
              work_key, title, subtitle, title_tr, authors, subjects,
              description, first_published, pages, languages, isbns,
              cover_id, edition_count, rating_count, rating_avg, readers, finished,
              genres,
              {moods_dedup}                                          AS moods,
              {taxonomy.sql_era_expr('first_published')}             AS era,
              {taxonomy.sql_length_expr('pages')}                    AS length_bucket,
              {taxonomy.sql_audience_expr('genres', 'search_text')}  AS audience,
              -- `search_text` bilerek dışarıda: yalnızca etiketleme için
              -- üretiliyor, serviste hiç okunmuyor ve kitap başına ~300 bayt
              -- tutuyordu (2.4M kitapta ~700 MB).
              CASE WHEN cover_id IS NULL THEN NULL
                   ELSE 'https://covers.openlibrary.org/b/id/' || cover_id || '-M.jpg' END
                                                                     AS cover_url,
              'https://openlibrary.org' || work_key                  AS openlibrary_url,
              3 * ln(1 + rating_count) + 2 * ln(1 + readers) + ln(1 + edition_count)
                                                                     AS signal
            FROM mooded
        """)

        # Bilinirliği 0-1 aralığına çek: ham sinyal logaritmik, en yüksek değere bölünür.
        self.con.execute("""
            ALTER TABLE books ADD COLUMN IF NOT EXISTS popularity DOUBLE;
            UPDATE books SET popularity = CASE
              WHEN (SELECT max(signal) FROM books) > 0
              THEN least(1.0, signal / (SELECT max(signal) FROM books))
              ELSE 0.0 END;
        """)

    def stage_index(self) -> None:
        """BM25 tam metin indeksi — sözcüksel arama bunun üzerinden çalışır."""
        started = time.perf_counter()
        self.con.execute("INSTALL fts")
        self.con.execute("LOAD fts")
        self.con.execute("""
            PRAGMA create_fts_index(
              'books', 'work_key', 'title', 'subtitle', 'title_tr',
              'authors_text', 'subjects_text', 'description',
              overwrite=1, stemmer='english', stopwords='english', lower=1, strip_accents=1
            )
        """)
        self.report.seconds["fts_index"] = round(time.perf_counter() - started, 2)
        log.info("%-14s %10s      (%.1fs)", "fts_index", "hazır",
                 self.report.seconds["fts_index"])

    def stage_text_columns(self) -> None:
        """FTS'in indeksleyebilmesi için liste sütunlarını metne düzleştirir."""
        self.con.execute("""
            ALTER TABLE books ADD COLUMN IF NOT EXISTS authors_text VARCHAR;
            ALTER TABLE books ADD COLUMN IF NOT EXISTS subjects_text VARCHAR;
            UPDATE books SET
              authors_text  = array_to_string(authors, ', '),
              subjects_text = array_to_string(subjects, ', ');
        """)

    def stage_meta(self) -> None:
        from .sources import dump_date

        self.report.dump_date = dump_date(self.sources.works)
        payload = {
            "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "dump_date": self.report.dump_date,
            "sources": self.sources.as_dict(),
            "options": asdict(self.opt),
            "stages": self.report.stages,
            "seconds": self.report.seconds,
            "taxonomy": {
                "genres": list(taxonomy.GENRE_SLUGS),
                "moods": list(taxonomy.MOOD_SLUGS),
            },
        }
        self.con.execute("CREATE OR REPLACE TABLE catalog_meta (key VARCHAR, value VARCHAR)")
        self.con.execute(
            "INSERT INTO catalog_meta VALUES ('build', ?)",
            [json.dumps(payload, ensure_ascii=False)],
        )

    def cleanup(self) -> None:
        if self.opt.preserve_stages:
            return
        for table in ("editions", "authors", "work_authors",
                          "candidates", "prelim", "ratings", "readers"):
            self.con.execute(f"DROP TABLE IF EXISTS {table}")
        self.con.execute("CHECKPOINT")

    # ── giriş noktası ──────────────────────────────────────────────────────

    #: Aşama sırası ve her birinin ürettiği tablo. Sonraki aşamalar önceki
    #: tabloları düşürdüğü için sürdürme noktası "var olan en ileri tablo"
    #: üzerinden bulunur.
    STAGES: tuple[tuple[str, str], ...] = (
        ("authors", "stage_authors"),
        ("ratings", "stage_ratings"),
        ("readers", "stage_readers"),
        ("prelim", "stage_prelim"),
        ("editions", "stage_editions"),
        ("candidates", "stage_candidates"),
        ("work_authors", "stage_work_authors"),
        ("books", "stage_books"),
    )

    def _resume_index(self) -> int:
        """Sürdürülecek ilk aşamanın sırası."""
        if not self.opt.resume:
            return 0
        last = -1
        for i, (table, _method) in enumerate(self.STAGES):
            if self._table_exists(table):
                last = i
        if last >= 0:
            log.info("sürdürülüyor: '%s' tablosu mevcut, sonraki aşamadan devam",
                     self.STAGES[last][0])
        return last + 1

    def build(self) -> BuildReport:
        started = time.perf_counter()
        start_at = self._resume_index()
        for i, (table, method) in enumerate(self.STAGES):
            if i < start_at:
                if self._table_exists(table):
                    rows = self.con.execute(
                        f"SELECT count(*) FROM {table}").fetchone()[0]
                    self.report.stages[table] = rows
                log.info("%-14s %10s      (tamamlanmış, atlandı)", table, "—")
                continue
            getattr(self, method)()
            if self.opt.stop_after == table:
                log.info("'%s' aşamasından sonra durduruldu (--stop-after). "
                         "Devam için: kitapai data build --resume", table)
                self.report.seconds["total"] = round(time.perf_counter() - started, 2)
                return self.report

        self.stage_text_columns()
        self.stage_index()
        self.stage_meta()
        self.cleanup()
        self.report.books = self.con.execute("SELECT count(*) FROM books").fetchone()[0]
        self.report.seconds["total"] = round(time.perf_counter() - started, 2)
        log.info("katalog hazır: %s kitap (%.1fs)",
                 f"{self.report.books:,}", self.report.seconds["total"])
        return self.report


def build_catalog(
    sources: DumpSources,
    db_path: Path,
    options: BuildOptions | None = None,
) -> BuildReport:
    options = options or BuildOptions()
    con = connect(db_path, options)
    try:
        _ensure_httpfs(con, sources)
        builder = CatalogBuilder(con, sources, options)
        report = builder.build()
        report.catalog_path = str(db_path)
        return report
    finally:
        con.close()
