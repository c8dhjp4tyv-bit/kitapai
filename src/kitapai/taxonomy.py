"""Tür / ruh hali / dönem taksonomisi ve Open Library konu eşlemesi.

Open Library'nin `subjects` alanı serbest metindir: aynı kitapta
"Science fiction", "Fiction, science fiction, general" ve "SF" birlikte
bulunabilir. Burada bu kaos, istemcilerde gösterilebilir Türkçe etiketlere
indirgenir.

Tek kaynak ilkesi: desenler yalnızca bu dosyada tanımlanır.
  • `classify()`        → Python tarafı (veri kümesi üretimi, testler)
  • `sql_label_expr()`  → aynı desenlerden üretilmiş DuckDB ifadesi
    (milyonlarca satırı Python döngüsüne sokmadan etiketlemek için)
`tests/test_taxonomy.py` ikisinin aynı sonucu verdiğini doğrular.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import cache

# ── Tanımlar ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Label:
    slug: str
    label: str           # Türkçe görünen ad
    patterns: tuple[str, ...]   # RE2-uyumlu, küçük harfe indirgenmiş konu desenleri
    mood_priors: tuple[str, ...] = ()   # tür → olası ruh halleri
    description: str = ""
    negative: tuple[str, ...] = field(default=())  # bu desenler varsa etiket verilmez
    #: Kesme (max_genres) yapılırken hangi türün kalacağını belirler.
    #: 1 = çok spesifik (polisiye, distopya), 3 = genel (roman, klasik).
    #: Genel türler listeyi doldurup spesifik olanları dışarıda bırakmasın diye.
    priority: int = 2

    def as_dict(self) -> dict:
        return {"slug": self.slug, "label": self.label, "description": self.description}


# Not: desenler `subjects` + başlık + açıklamadan oluşan tek bir küçük harfli
# metinde aranır. Aynı desenler DuckDB'nin RE2 motorunda da çalışmak zorunda:
# `\b` sınırları desteklenir ama ileri/geri bakış (?!...) (?<=...) DESTEKLENMEZ.
# "şu varsa etiketleme" kuralı için `negative` alanını kullanın.
# `tests/test_taxonomy.py::test_desenler_re2_uyumlu` bunu doğrular.

GENRES: tuple[Label, ...] = (
    Label("roman", "Roman",
          (r"\bfiction\b", r"\bnovels?\b", r"\bliterary fiction\b"),
          ("dusundurucu", "melankolik"),
          "Genel kurgu ve edebî roman"),
    Label("klasik", "Klasik",
          (r"\bclassic(s|al literature)?\b", r"\bworld literature\b", r"\bcanon\b",
           r"\b19th century\b.*\bfiction\b"),
          ("dusundurucu", "melankolik"),
          "Edebiyat kanonuna girmiş eserler"),
    Label("bilim-kurgu", "Bilim Kurgu",
          (r"\bscience fiction\b", r"\bsci-?fi\b", r"\bspace opera\b", r"\bcyberpunk\b",
           r"\btime travel\b", r"\bextraterrestrial\b", r"\bspace flight\b", r"\brobots?\b"),
          ("epik", "dusundurucu", "gizemli"),
          "Bilimsel varsayımlar üzerine kurulu kurgu"),
    Label("fantastik", "Fantastik",
          (r"\bfantasy\b", r"\bmagic\b", r"\bwizards?\b", r"\bdragons?\b", r"\bmythical\b",
           r"\bsword and sorcery\b", r"\bepic fantasy\b", r"\bimaginary places\b"),
          ("epik", "maceraci", "umutlu"),
          "Büyü ve mitoloji içeren kurgu"),
    Label("distopya", "Distopya",
          (r"\bdystopi", r"\butopi", r"\btotalitarian", r"\bpost-?apocalyp"),
          ("karanlik", "dusundurucu", "gerilimli"),
          "Karanlık gelecek tasavvurları"),
    Label("polisiye", "Polisiye",
          (r"\bdetective\b", r"\bmystery\b", r"\bcrime\b", r"\bmurder\b", r"\bwhodunit\b",
           r"\bprivate investigators?\b", r"\bpolice procedural\b"),
          ("gizemli", "gerilimli"),
          "Cinayet ve soruşturma kurgusu"),
    Label("gerilim", "Gerilim",
          (r"\bthriller\b", r"\bsuspense\b", r"\bespionage\b", r"\bspy stories\b",
           r"\bconspirac"),
          ("gerilimli", "karanlik"),
          "Yüksek tempolu, tedirgin edici anlatı"),
    Label("korku", "Korku",
          (r"\bhorror\b", r"\bghost stories\b", r"\bvampires?\b", r"\bsupernatural\b",
           r"\bmonsters?\b", r"\bhaunted\b"),
          ("karanlik", "gerilimli"),
          "Ürpertici ve doğaüstü anlatılar"),
    Label("macera", "Macera",
          (r"\badventure\b", r"\bsurvival\b", r"\bvoyages and travels\b", r"\bexplorers?\b",
           r"\bsea stories\b", r"\bquests?\b"),
          ("maceraci", "heyecanli"),
          "Yolculuk ve hayatta kalma"),
    Label("romantik", "Romantik",
          (r"\bromance\b", r"\blove stories\b", r"\bcourtship\b", r"\bman-woman relationships\b"),
          ("romantik", "sicak"),
          "Aşk ilişkileri merkezli"),
    Label("tarihi-kurgu", "Tarihî Kurgu",
          (r"\bhistorical fiction\b", r"\bhistorical novel", r"\bwar stories\b"),
          ("epik", "melankolik"),
          "Geçmişte geçen kurgu"),
    Label("genc-yetiskin", "Genç Yetişkin",
          (r"\byoung adult\b", r"\bteenagers?\b", r"\bcoming of age\b", r"\bya fiction\b",
           r"\bhigh school\b"),
          ("umutlu", "heyecanli"),
          "Ergen ve genç okur odaklı"),
    Label("cocuk", "Çocuk",
          (r"\bjuvenile fiction\b", r"\bchildren'?s (stories|fiction|literature)\b",
           r"\bpicture books?\b", r"\bfairy tales\b"),
          ("sicak", "umutlu"),
          "Çocuk edebiyatı"),
    Label("cizgi-roman", "Çizgi Roman",
          (r"\bcomics?\b", r"\bgraphic novels?\b", r"\bmanga\b", r"\bcartoons?\b"),
          ("heyecanli", "komik"),
          "Görsel anlatı"),
    Label("siir", "Şiir",
          (r"\bpoetry\b", r"\bpoems?\b", r"\bverse\b", r"\bsonnets?\b"),
          ("melankolik", "dusundurucu"),
          "Şiir ve nazım"),
    Label("tiyatro", "Tiyatro",
          (r"\bdrama\b", r"\bplays\b", r"\btheater\b", r"\btheatre\b", r"\btragedies\b"),
          ("dusundurucu", "melankolik"),
          "Oyun metinleri"),
    Label("deneme", "Deneme",
          (r"\bessays?\b", r"\bcriticism\b", r"\bliterary collections\b"),
          ("dusundurucu",),
          "Deneme ve eleştiri"),
    Label("felsefe", "Felsefe",
          (r"\bphilosoph", r"\bethics\b", r"\bmetaphysics\b", r"\bexistentialism\b",
           r"\bstoicism\b", r"\blogic\b"),
          ("dusundurucu",),
          "Felsefe metinleri"),
    Label("psikoloji", "Psikoloji",
          (r"\bpsychology\b", r"\bpsychological\b", r"\bmental health\b",
           r"\bcognitive\b", r"\bpsychiatry\b", r"\bbehavioral science\b"),
          ("dusundurucu", "ilham-verici"),
          "Zihin ve davranış",
          negative=(r"\bpsychological fiction\b", r"\bmental healing\b")),
    Label("kisisel-gelisim", "Kişisel Gelişim",
          (r"\bself-?help\b", r"\bself-?actualization\b", r"\bpersonal development\b",
           r"\bhabits?\b", r"\bmotivation\b", r"\bproductivity\b"),
          ("ilham-verici", "umutlu"),
          "Alışkanlık ve motivasyon"),
    Label("tarih", "Tarih",
          (r"\bhistory\b", r"\bhistoriograph", r"\bworld war\b", r"\bancient\b",
           r"\bcivilization\b", r"\bempire\b"),
          ("dusundurucu", "epik"),
          "Tarih araştırmaları",
          negative=(r"\bhistorical fiction\b", r"\bart history\b",
                    r"\bhistory and criticism\b", r"\bcase histories\b")),
    Label("biyografi", "Biyografi",
          (r"\bbiograph", r"\bautobiograph", r"\bmemoirs?\b", r"\bdiaries\b",
           r"\bpersonal narratives\b"),
          ("ilham-verici", "melankolik"),
          "Yaşam öyküleri"),
    Label("bilim", "Bilim",
          (r"\bscience\b", r"\bphysics\b", r"\bbiology\b", r"\bastronomy\b", r"\bchemistry\b",
           r"\bevolution\b", r"\bmathematics\b", r"\bneuroscience\b"),
          ("dusundurucu", "ilham-verici"),
          "Popüler bilim ve akademi",
          negative=(r"\bscience fiction\b", r"\bsocial science", r"\bpolitical science\b",
                    r"\bcomputer science\b", r"\blibrary science\b",
                    r"\bmilitary art and science\b", r"\bscience fantasy\b")),
    Label("teknoloji", "Teknoloji",
          (r"\bcomputer\b", r"\bprogramming\b", r"\bartificial intelligence\b",
           r"\bsoftware\b", r"\bengineering\b", r"\binternet\b", r"\bdata\b"),
          ("dusundurucu",),
          "Bilişim ve mühendislik"),
    Label("is-ekonomi", "İş ve Ekonomi",
          (r"\bbusiness\b", r"\beconomics\b", r"\bmanagement\b", r"\bfinance\b",
           r"\bentrepreneurship\b", r"\bmarketing\b", r"\binvestment"),
          ("ilham-verici",),
          "İşletme, ekonomi, girişimcilik"),
    Label("politika", "Politika",
          (r"\bpolitic", r"\bgovernment\b", r"\bdemocracy\b", r"\bsocial science\b",
           r"\binternational relations\b", r"\bsociolog"),
          ("dusundurucu", "karanlik"),
          "Siyaset ve toplum"),
    Label("din-maneviyat", "Din ve Maneviyat",
          (r"\breligion\b", r"\bspiritual", r"\btheolog", r"\bislam\b", r"\bchristian",
           r"\bbuddhis", r"\bmeditation\b", r"\bmysticism\b"),
          ("sakinlestirici", "dusundurucu"),
          "İnanç ve maneviyat"),
    Label("sanat", "Sanat",
          (r"\bart history\b", r"\bfine arts?\b", r"\bart criticism\b", r"\bpainting\b",
           r"\bphotograph", r"\barchitecture\b", r"\bsculpture\b", r"\bmusic\b",
           r"\bcinema\b", r"\bmotion pictures?\b", r"\bexhibitions\b"),
          ("ilham-verici",),
          "Görsel ve işitsel sanatlar",
          negative=(r"\bmilitary art\b", r"\bart of war\b")),
    Label("gezi", "Gezi",
          (r"\bdescription and travel\b", r"\btravel guides?\b", r"\bguidebooks?\b",
           r"\btravelers'? writings\b", r"\btourism\b"),
          ("maceraci", "sakinlestirici"),
          "Seyahat ve yer anlatıları"),
    Label("yemek", "Yemek",
          (r"\bcooking\b", r"\bcookbooks?\b", r"\brecipes\b", r"\bgastronom"),
          ("sicak", "sakinlestirici"),
          "Mutfak ve tarifler"),
    Label("mizah", "Mizah",
          (r"\bhumor\b", r"\bsatire\b", r"\bcomic fiction\b", r"\bwit\b", r"\bparody\b"),
          ("komik",),
          "Gülmece ve hiciv"),
    Label("saglik", "Sağlık",
          (r"\bhealth\b", r"\bmedicine\b", r"\bfitness\b", r"\bnutrition\b", r"\bdiet\b"),
          ("ilham-verici", "sakinlestirici"),
          "Sağlık ve beslenme"),
)

MOODS: tuple[Label, ...] = (
    Label("heyecanli", "Heyecan Verici",
          (r"\bthriller\b", r"\baction\b", r"\badventure\b", r"\bchase\b", r"\bfast-paced\b",
           r"\bescapes\b"),
          description="Tempolu, sürükleyici"),
    Label("dusundurucu", "Düşündürücü",
          (r"\bphilosoph", r"\bexistential", r"\bmoral\b", r"\bethics\b", r"\bideas\b",
           r"\bintrospect", r"\bconsciousness\b"),
          description="Zihin açan, sorgulatan"),
    Label("karanlik", "Karanlık",
          (r"\bdark\b", r"\btragedy\b", r"\bviolence\b", r"\bdespair\b", r"\bnoir\b",
           r"\bdystopi", r"\bhorror\b", r"\bdeath\b"),
          description="Ağır ve kasvetli"),
    Label("romantik", "Romantik",
          (r"\bromance\b", r"\blove\b", r"\bpassion\b", r"\bcourtship\b"),
          description="Aşk odaklı"),
    Label("komik", "Komik",
          (r"\bhumor\b", r"\bcomed", r"\bsatire\b", r"\bfunny\b", r"\bwit\b"),
          description="Güldüren"),
    Label("sakinlestirici", "Sakinleştirici",
          (r"\bmeditation\b", r"\bmindfulness\b", r"\bnature\b", r"\bgardening\b",
           r"\bslow\b", r"\bcozy\b", r"\bcalm\b"),
          description="Yavaş ve huzurlu"),
    Label("ilham-verici", "İlham Verici",
          (r"\binspiration\b", r"\bmotivation\b", r"\bsuccess\b", r"\bcourage\b",
           r"\bperseverance\b", r"\bhope\b"),
          description="Harekete geçiren"),
    Label("melankolik", "Melankolik",
          (r"\bgrief\b", r"\bloss\b", r"\bnostalgi", r"\bloneliness\b", r"\bmelanchol",
           r"\bsorrow\b"),
          description="Hüzünlü, iç burkan"),
    Label("gerilimli", "Gerilimli",
          (r"\bsuspense\b", r"\btension\b", r"\bpsychological thriller\b", r"\bparanoia\b"),
          description="Tırnak yedirten"),
    Label("sicak", "Sıcak ve Samimi",
          (r"\bfamily\b", r"\bfriendship\b", r"\bcommunity\b", r"\bheartwarming\b",
           r"\bdomestic fiction\b"),
          description="İçini ısıtan"),
    Label("epik", "Epik",
          (r"\bepic\b", r"\bsaga\b", r"\bheroes\b", r"\bmytholog", r"\blegends\b",
           r"\bempire\b", r"\bwar\b"),
          description="Geniş ölçekli, destansı"),
    Label("gizemli", "Gizemli",
          (r"\bmystery\b", r"\bsecrets?\b", r"\bpuzzle\b", r"\benigma\b", r"\bdetective\b",
           r"\boccult\b"),
          description="Bilmece gibi"),
    Label("umutlu", "Umut Veren",
          (r"\bhope\b", r"\bredemption\b", r"\bhealing\b", r"\brecovery\b", r"\boptimis"),
          description="İyi hissettiren"),
    Label("maceraci", "Maceracı",
          (r"\bexploration\b", r"\bvoyages\b", r"\bwilderness\b", r"\bexpedition\b",
           r"\btreasure\b"),
          description="Yola çıkaran"),
)

#: Türlerin cümle içinde doğal duran ad öbeği. Etiketler başlık için uygundur
#: ("Din ve Maneviyat") ama cümlede tek başına duramaz ("bir din ve maneviyat
#: okumak istiyorum" bozuk); bu tablo onu düzeltir.
GENRE_NOUNS: dict[str, str] = {
    "roman": "roman",
    "klasik": "klasik",
    "bilim-kurgu": "bilim kurgu romanı",
    "fantastik": "fantastik roman",
    "distopya": "distopya",
    "polisiye": "polisiye",
    "gerilim": "gerilim romanı",
    "korku": "korku kitabı",
    "macera": "macera romanı",
    "romantik": "aşk romanı",
    "tarihi-kurgu": "tarihî roman",
    "genc-yetiskin": "genç yetişkin romanı",
    "cocuk": "çocuk kitabı",
    "cizgi-roman": "çizgi roman",
    "siir": "şiir kitabı",
    "tiyatro": "tiyatro oyunu",
    "deneme": "deneme kitabı",
    "felsefe": "felsefe kitabı",
    "psikoloji": "psikoloji kitabı",
    "kisisel-gelisim": "kişisel gelişim kitabı",
    "tarih": "tarih kitabı",
    "biyografi": "biyografi",
    "bilim": "popüler bilim kitabı",
    "teknoloji": "teknoloji kitabı",
    "is-ekonomi": "iş ve ekonomi kitabı",
    "politika": "siyaset kitabı",
    "din-maneviyat": "maneviyat kitabı",
    "sanat": "sanat kitabı",
    "gezi": "gezi kitabı",
    "yemek": "yemek kitabı",
    "mizah": "mizah kitabı",
    "saglik": "sağlık kitabı",
}


def genre_noun(slug: str) -> str:
    """Cümle içinde kullanılabilir tür adı."""
    if slug in GENRE_NOUNS:
        return GENRE_NOUNS[slug]
    label = GENRE_BY_SLUG.get(slug)
    return label.label.lower() if label else slug


ERAS: tuple[tuple[str, str, int | None, int | None], ...] = (
    # (slug, etiket, başlangıç yılı, bitiş yılı)
    ("klasik", "Klasik (1900 öncesi)", None, 1899),
    ("modern", "Modern (1900-1989)", 1900, 1989),
    ("cagdas", "Çağdaş (1990 ve sonrası)", 1990, None),
)

LENGTHS: tuple[tuple[str, str, int | None, int | None], ...] = (
    ("kisa", "Kısa (200 sayfaya kadar)", None, 200),
    ("orta", "Orta (200-400 sayfa)", 201, 400),
    ("uzun", "Uzun (400-700 sayfa)", 401, 700),
    ("tugla", "Tuğla (700+ sayfa)", 701, None),
)

AUDIENCES: tuple[tuple[str, str], ...] = (
    ("cocuk", "Çocuk"),
    ("genc", "Genç"),
    ("yetiskin", "Yetişkin"),
)

# ── Aramalar ───────────────────────────────────────────────────────────────

#: Kesme (max_genres) sırasında hangi türün kalacağını belirler.
#: 1 = çok spesifik (polisiye, distopya), 3 = genel (roman, klasik).
#: Genel türler listeyi doldurup spesifik olanları dışarı itmesin diye
#: etiketler her zaman bu önceliğe göre sıralanır — hem Python hem SQL yolunda.
GENRE_PRIORITY: dict[str, int] = {
    "bilim-kurgu": 1, "fantastik": 1, "distopya": 1, "polisiye": 1, "gerilim": 1,
    "korku": 1, "cizgi-roman": 1, "siir": 1, "tiyatro": 1, "tarihi-kurgu": 1,
    "mizah": 1, "cocuk": 1, "genc-yetiskin": 1, "macera": 1, "romantik": 1,
    "roman": 3, "klasik": 3,
}


def genre_priority(slug: str) -> int:
    return GENRE_PRIORITY.get(slug, 2)


#: Etiketleme ve SQL üretimi bu sırayı kullanır (kararlı: öncelik, sonra tanım sırası).
GENRES_BY_PRIORITY: tuple[Label, ...] = tuple(
    sorted(GENRES, key=lambda g: (genre_priority(g.slug), GENRES.index(g)))
)

GENRE_BY_SLUG = {g.slug: g for g in GENRES}
MOOD_BY_SLUG = {m.slug: m for m in MOODS}
GENRE_SLUGS = tuple(g.slug for g in GENRES)
MOOD_SLUGS = tuple(m.slug for m in MOODS)
ERA_SLUGS = tuple(e[0] for e in ERAS)
LENGTH_SLUGS = tuple(length[0] for length in LENGTHS)
AUDIENCE_SLUGS = tuple(a[0] for a in AUDIENCES)


@cache
def _compiled(patterns: tuple[str, ...]) -> re.Pattern[str]:
    return re.compile("|".join(f"(?:{p})" for p in patterns))


def normalize_text(*parts: str | None) -> str:
    """Konu/başlık/açıklamayı tek bir aranabilir küçük harfli metne indirger."""
    joined = " | ".join(p for p in parts if p)
    joined = unicodedata.normalize("NFKD", joined)
    return joined.lower()


def classify(
    subjects: list[str] | None = None,
    *,
    title: str | None = None,
    description: str | None = None,
    max_genres: int = 4,
    max_moods: int = 3,
) -> tuple[list[str], list[str]]:
    """Ham konulardan Türkçe (tür, ruh hali) etiketleri üretir.

    Ruh halleri iki kaynaktan beslenir: doğrudan konu eşleşmesi ve
    türlerin `mood_priors` alanı. Doğrudan eşleşme önceliklidir.
    """
    # Tür yalnızca konulardan ve başlıktan çıkarılır. Açıklama metni serbest
    # düzyazıdır ve tür desenlerini yanlış tetikler ("...a Roman emperor..." →
    # roman, "...reshapes an empire" → tarih). Ruh hali ise tam tersine
    # açıklamanın tonundan beslenir.
    subject_text = normalize_text(" | ".join(subjects or []))
    full_text = normalize_text(" | ".join(subjects or []), title, description)
    if not subject_text and not full_text:
        return [], []

    genres: list[str] = []
    for g in GENRES_BY_PRIORITY:
        if _compiled(g.patterns).search(subject_text):
            if g.negative and _compiled(g.negative).search(subject_text):
                continue
            genres.append(g.slug)
    genres = genres[:max_genres]

    direct = [m.slug for m in MOODS if _compiled(m.patterns).search(full_text)]
    # Metinden doğrudan iki ruh hali çıktıysa tür önyargılarına gerek yok;
    # aksi hâlde tür önyargıları boşluğu doldurur.
    priors = [] if len(direct) >= 2 else [
        s for g in genres for s in GENRE_BY_SLUG[g].mood_priors
    ]

    moods: list[str] = []
    for slug in [*direct, *priors]:
        if slug not in moods:
            moods.append(slug)

    return genres, moods[:max_moods]


def era_of(year: int | None) -> str | None:
    if not year:
        return None
    for slug, _label, lo, hi in ERAS:
        if (lo is None or year >= lo) and (hi is None or year <= hi):
            return slug
    return None


def length_of(pages: int | None) -> str | None:
    if not pages or pages <= 0:
        return None
    for slug, _label, lo, hi in LENGTHS:
        if (lo is None or pages >= lo) and (hi is None or pages <= hi):
            return slug
    return None


def audience_of(genres: list[str], subjects: list[str] | None = None) -> str:
    text = normalize_text(" | ".join(subjects or []))
    if "cocuk" in genres or re.search(r"\bjuvenile\b|\bchildren", text):
        return "cocuk"
    if "genc-yetiskin" in genres or "young adult" in text:
        return "genc"
    return "yetiskin"


# ── DuckDB ifade üretimi ───────────────────────────────────────────────────


def _sql_regex(patterns: tuple[str, ...]) -> str:
    joined = "|".join(f"(?:{p})" for p in patterns)
    escaped = joined.replace("'", "''")
    return f"'{escaped}'"


def sql_label_expr(text_col: str, labels: tuple[Label, ...]) -> str:
    """`text_col` üzerinde çalışan, etiket slug'ları listesi döndüren SQL ifadesi.

    Python `classify()` ile aynı desenleri kullanır; böylece milyonlarca satır
    DuckDB içinde etiketlenirken tek kaynak ilkesi korunur.
    """
    pieces = []
    for lab in labels:
        cond = f"regexp_matches({text_col}, {_sql_regex(lab.patterns)})"
        if lab.negative:
            cond += f" AND NOT regexp_matches({text_col}, {_sql_regex(lab.negative)})"
        pieces.append(f"CASE WHEN {cond} THEN ['{lab.slug}'] ELSE [] END")
    return "list_concat(" + ", ".join(pieces) + ")" if len(pieces) > 1 else pieces[0]


def sql_genres_expr(text_col: str = "search_text", *, max_genres: int = 4) -> str:
    """`classify()` ile birebir aynı sırayı ve kesmeyi uygular."""
    expr = "[]::VARCHAR[]"
    for lab in GENRES_BY_PRIORITY:
        cond = f"regexp_matches({text_col}, {_sql_regex(lab.patterns)})"
        if lab.negative:
            cond += f" AND NOT regexp_matches({text_col}, {_sql_regex(lab.negative)})"
        expr = f"list_concat({expr}, CASE WHEN {cond} THEN ['{lab.slug}'] ELSE []::VARCHAR[] END)"
    # Her etiket kendi slug'ını en fazla bir kez ekler, bu yüzden tekrar olamaz;
    # `list_distinct` gereksiz olmanın ötesinde ZARARLI olurdu çünkü DuckDB'de
    # sırayı korumaz ve öncelik sıralamasını (spesifik → genel) bozar.
    return f"({expr})[1:{max_genres}]"


def sql_direct_moods_expr(text_col: str = "search_text") -> str:
    """Metinden doğrudan eşleşen ruh halleri."""
    expr = "[]::VARCHAR[]"
    for lab in MOODS:
        cond = f"regexp_matches({text_col}, {_sql_regex(lab.patterns)})"
        expr = f"list_concat({expr}, CASE WHEN {cond} THEN ['{lab.slug}'] ELSE []::VARCHAR[] END)"
    return expr


def sql_prior_moods_expr(genres_col: str = "genres") -> str:
    """Türlerden türetilen ruh hali önyargıları."""
    expr = "[]::VARCHAR[]"
    for g in GENRES:
        for prior in g.mood_priors:
            expr = (
                f"list_concat({expr}, CASE WHEN list_contains({genres_col}, '{g.slug}') "
                f"THEN ['{prior}'] ELSE []::VARCHAR[] END)"
            )
    return expr


def sql_moods_expr(text_col: str = "search_text", genres_col: str = "genres") -> str:
    """`classify()` ile aynı kural: 2+ doğrudan eşleşme varsa önyargı eklenmez.

    Sonuçta tekrar olabilir (aynı ruh hali hem doğrudan hem önyargı olarak);
    tekilleştirme `sql_dedup_ordered()` ile ayrı bir adımda yapılır — böylece
    dev ifade iki kez üretilmez ve sıra korunur.
    """
    direct = sql_direct_moods_expr(text_col)
    priors = sql_prior_moods_expr(genres_col)
    return (
        f"CASE WHEN len({direct}) >= 2 THEN {direct} "
        f"ELSE list_concat({direct}, {priors}) END"
    )


def sql_dedup_ordered(column: str, *, limit: int | None = None) -> str:
    """Sırayı koruyarak tekilleştirir.

    DuckDB'nin `list_distinct`'i sırayı korumaz (`['a','b','a']` → `['b','a']`),
    bu yüzden öncelik sıralaması yapılan listelerde kullanılamaz. Burada her
    ögenin yalnızca ilk geçtiği konumda tutulması sağlanır. `column` bir sütun
    adı olmalı — ifadeyi iki kez hesaplamamak için.
    """
    expr = f"list_filter({column}, (x, i) -> list_position({column}, x) = i)"
    return f"{expr}[1:{limit}]" if limit else expr


def sql_era_expr(year_col: str = "first_published") -> str:
    parts = [f"WHEN {year_col} IS NULL THEN NULL"]
    for slug, _label, lo, hi in ERAS:
        conds = []
        if lo is not None:
            conds.append(f"{year_col} >= {lo}")
        if hi is not None:
            conds.append(f"{year_col} <= {hi}")
        parts.append(f"WHEN {' AND '.join(conds)} THEN '{slug}'")
    return "CASE " + " ".join(parts) + " ELSE NULL END"


def sql_length_expr(pages_col: str = "pages") -> str:
    parts = [f"WHEN {pages_col} IS NULL OR {pages_col} <= 0 THEN NULL"]
    for slug, _label, lo, hi in LENGTHS:
        conds = []
        if lo is not None:
            conds.append(f"{pages_col} >= {lo}")
        if hi is not None:
            conds.append(f"{pages_col} <= {hi}")
        parts.append(f"WHEN {' AND '.join(conds)} THEN '{slug}'")
    return "CASE " + " ".join(parts) + " ELSE NULL END"


def sql_audience_expr(genres_col: str = "genres", text_col: str = "search_text") -> str:
    return (
        f"CASE WHEN list_contains({genres_col}, 'cocuk') "
        f"OR regexp_matches({text_col}, '\\bjuvenile\\b|\\bchildren') THEN 'cocuk' "
        f"WHEN list_contains({genres_col}, 'genc-yetiskin') "
        f"OR regexp_matches({text_col}, 'young adult') THEN 'genc' "
        f"ELSE 'yetiskin' END"
    )


def taxonomy_payload() -> dict:
    """`/api/taxonomy` yanıtı — istemciler listeleri sabit kodlamaz."""
    return {
        "genres": [g.as_dict() for g in GENRES],
        "moods": [m.as_dict() for m in MOODS],
        "eras": [{"slug": s, "label": lab, "description": ""} for s, lab, _, _ in ERAS],
        "lengths": [{"slug": s, "label": lab, "description": ""} for s, lab, _, _ in LENGTHS],
        "audiences": [{"slug": s, "label": lab, "description": ""} for s, lab in AUDIENCES],
    }
