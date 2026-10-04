"""Open Library konularının Türkçe tema karşılıkları.

Open Library konuları İngilizcedir. Eğitim verisindeki kullanıcı isteklerinin
doğal Türkçe olması için sık geçen konular elle çevrildi. Bu sözlük yalnızca
*istek üretimi* ve *gerekçe yazımı* için kullanılır; modelin girdisinde konular
ham hâliyle de bulunur, böylece model İngilizce meta veriden Türkçe yanıt
üretmeyi öğrenir (servis anında da durum budur).

Anahtarlar küçük harfe indirgenmiş konu adlarıdır; eşleşme önce tam ad, sonra
alt dize üzerinden denenir.
"""

from __future__ import annotations

# ── tema sözlüğü: konu → (Türkçe tema, tema türü) ──────────────────────────
# tema türü: "konu" (neyi anlatıyor) | "duygu" | "mekan" | "figur"

THEMES: dict[str, tuple[str, str]] = {
    # İnsan ilişkileri / duygular
    "friendship": ("dostluk", "konu"),
    "love": ("aşk", "konu"),
    "love stories": ("aşk", "konu"),
    "romance": ("aşk", "konu"),
    "marriage": ("evlilik", "konu"),
    "divorce": ("ayrılık", "konu"),
    "family": ("aile", "konu"),
    "families": ("aile", "konu"),
    "mothers and daughters": ("anne-kız ilişkisi", "konu"),
    "fathers and sons": ("baba-oğul ilişkisi", "konu"),
    "brothers and sisters": ("kardeşlik", "konu"),
    "friendship in children": ("çocuk dostlukları", "konu"),
    "loneliness": ("yalnızlık", "duygu"),
    "grief": ("yas", "duygu"),
    "loss": ("kayıp", "duygu"),
    "betrayal": ("ihanet", "duygu"),
    "revenge": ("intikam", "duygu"),
    "guilt": ("suçluluk", "duygu"),
    "hope": ("umut", "duygu"),
    "fear": ("korku", "duygu"),
    "courage": ("cesaret", "duygu"),
    "jealousy": ("kıskançlık", "duygu"),
    "forgiveness": ("bağışlama", "duygu"),
    "nostalgia": ("nostalji", "duygu"),
    "identity": ("kimlik arayışı", "konu"),
    "self-realization": ("kendini bulma", "konu"),
    "coming of age": ("büyüme sancıları", "konu"),
    "alienation": ("yabancılaşma", "konu"),
    "belonging": ("aidiyet", "konu"),

    # Toplum / politika
    "politics and government": ("siyaset", "konu"),
    "totalitarianism": ("totaliter rejimler", "konu"),
    "dystopias": ("distopya", "konu"),
    "utopias": ("ütopya", "konu"),
    "revolutions": ("devrim", "konu"),
    "social classes": ("sınıf farkları", "konu"),
    "poverty": ("yoksulluk", "konu"),
    "racism": ("ırkçılık", "konu"),
    "feminism": ("feminizm", "konu"),
    "women": ("kadınlar", "konu"),
    "gender identity": ("toplumsal cinsiyet", "konu"),
    "slavery": ("kölelik", "konu"),
    "immigrants": ("göçmenlik", "konu"),
    "refugees": ("mültecilik", "konu"),
    "surveillance": ("gözetim", "konu"),
    "propaganda": ("propaganda", "konu"),
    "censorship": ("sansür", "konu"),
    "justice": ("adalet", "konu"),
    "human rights": ("insan hakları", "konu"),
    "capitalism": ("kapitalizm", "konu"),
    "war": ("savaş", "konu"),
    "world war, 1939-1945": ("İkinci Dünya Savaşı", "konu"),
    "world war, 1914-1918": ("Birinci Dünya Savaşı", "konu"),
    "holocaust, jewish (1939-1945)": ("Holokost", "konu"),
    "genocide": ("soykırım", "konu"),
    "terrorism": ("terör", "konu"),
    "colonialism": ("sömürgecilik", "konu"),

    # Suç / gizem
    "crime": ("suç", "konu"),
    "murder": ("cinayet", "konu"),
    "detective and mystery stories": ("dedektiflik", "konu"),
    "private investigators": ("özel dedektifler", "figur"),
    "police": ("polisiye soruşturma", "konu"),
    "serial murders": ("seri cinayetler", "konu"),
    "kidnapping": ("kaçırılma", "konu"),
    "conspiracies": ("komplo", "konu"),
    "espionage": ("casusluk", "konu"),
    "secrets": ("sırlar", "konu"),
    "missing persons": ("kayıp kişiler", "konu"),
    "trials": ("mahkeme", "konu"),

    # Bilim kurgu / fantastik
    "science fiction": ("bilim kurgu", "konu"),
    "space flight": ("uzay yolculuğu", "konu"),
    "outer space": ("uzay", "konu"),
    "space": ("uzay", "konu"),
    "future": ("gelecek", "konu"),
    "forecasting": ("gelecek", "konu"),
    "interplanetary voyages": ("gezegenler arası yolculuk", "konu"),
    "space colonies": ("uzay kolonileri", "konu"),
    "extraterrestrial beings": ("uzaylılar", "figur"),
    "time travel": ("zaman yolculuğu", "konu"),
    "robots": ("robotlar", "figur"),
    "artificial intelligence": ("yapay zekâ", "konu"),
    "cyberpunk": ("siberpunk", "konu"),
    "virtual reality": ("sanal gerçeklik", "konu"),
    "genetic engineering": ("genetik mühendislik", "konu"),
    "post-apocalyptic": ("kıyamet sonrası", "konu"),
    "magic": ("büyü", "konu"),
    "wizards": ("büyücüler", "figur"),
    "dragons": ("ejderhalar", "figur"),
    "vampires": ("vampirler", "figur"),
    "ghosts": ("hayaletler", "figur"),
    "monsters": ("canavarlar", "figur"),
    "witches": ("cadılar", "figur"),
    "mythology": ("mitoloji", "konu"),
    "folklore": ("halk anlatıları", "konu"),
    "fairy tales": ("masallar", "konu"),
    "imaginary places": ("hayalî diyarlar", "mekan"),
    "quests": ("uzun bir arayış", "konu"),
    "heroes": ("kahramanlık", "konu"),
    "immortality": ("ölümsüzlük", "konu"),
    "parallel universes": ("paralel evrenler", "konu"),
    "magic realism": ("büyülü gerçekçilik", "konu"),

    # Macera / mekân
    "adventure": ("macera", "konu"),
    "survival": ("hayatta kalma", "konu"),
    "voyages and travels": ("uzun yolculuklar", "konu"),
    "exploration": ("keşif", "konu"),
    "shipwrecks": ("gemi kazaları", "konu"),
    "sea stories": ("deniz", "mekan"),
    "islands": ("adalar", "mekan"),
    "deserts": ("çöl", "mekan"),
    "desert": ("çöl", "mekan"),
    "mountains": ("dağlar", "mekan"),
    "wilderness": ("vahşi doğa", "mekan"),
    "forests": ("ormanlar", "mekan"),
    "arctic regions": ("kutuplar", "mekan"),
    "cities and towns": ("şehir hayatı", "mekan"),
    "country life": ("taşra", "mekan"),
    "london (england)": ("Londra", "mekan"),
    "paris (france)": ("Paris", "mekan"),
    "new york (n.y.)": ("New York", "mekan"),
    "japan": ("Japonya", "mekan"),
    "istanbul (turkey)": ("İstanbul", "mekan"),
    "russia": ("Rusya", "mekan"),
    "india": ("Hindistan", "mekan"),
    "africa": ("Afrika", "mekan"),

    # Düşünce / bilim
    "philosophy": ("felsefe", "konu"),
    "ethics": ("etik", "konu"),
    "stoicism": ("stoacılık", "konu"),
    "existentialism": ("varoluşçuluk", "konu"),
    "metaphysics": ("metafizik", "konu"),
    "consciousness": ("bilinç", "konu"),
    "meaning of life": ("hayatın anlamı", "konu"),
    "death": ("ölüm", "konu"),
    "time": ("zaman", "konu"),
    "religion": ("din", "konu"),
    "spirituality": ("maneviyat", "konu"),
    "meditation": ("meditasyon", "konu"),
    "mysticism": ("tasavvuf", "konu"),
    "islam": ("İslam", "konu"),
    "buddhism": ("Budizm", "konu"),
    "science": ("bilim", "konu"),
    "physics": ("fizik", "konu"),
    "quantum theory": ("kuantum", "konu"),
    "astronomy": ("astronomi", "konu"),
    "cosmology": ("kozmoloji", "konu"),
    "evolution": ("evrim", "konu"),
    "biology": ("biyoloji", "konu"),
    "neuroscience": ("sinirbilim", "konu"),
    "mathematics": ("matematik", "konu"),
    "human evolution": ("insanın evrimi", "konu"),
    "anthropology": ("antropoloji", "konu"),
    "civilization": ("uygarlık tarihi", "konu"),
    "history": ("tarih", "konu"),
    "ancient history": ("antik çağ", "konu"),
    "middle ages": ("Orta Çağ", "konu"),
    "economics": ("ekonomi", "konu"),
    "sociology": ("toplumbilim", "konu"),
    "psychology": ("psikoloji", "konu"),
    "mental health": ("ruh sağlığı", "konu"),
    "depression, mental": ("depresyon", "konu"),
    "trauma": ("travma", "konu"),
    "memory": ("hafıza", "konu"),
    "dreams": ("rüyalar", "konu"),
    "happiness": ("mutluluk", "konu"),
    "habits": ("alışkanlıklar", "konu"),
    "success": ("başarı", "konu"),
    "leadership": ("liderlik", "konu"),
    "creativity": ("yaratıcılık", "konu"),
    "productivity": ("üretkenlik", "konu"),
    "decision making": ("karar verme", "konu"),
    "negotiation": ("müzakere", "konu"),
    "entrepreneurship": ("girişimcilik", "konu"),
    "management": ("yönetim", "konu"),
    "finance": ("finans", "konu"),
    "investments": ("yatırım", "konu"),
    "marketing": ("pazarlama", "konu"),
    "computer programming": ("programlama", "konu"),
    "computers": ("bilgisayarlar", "konu"),
    "internet": ("internet", "konu"),
    "technology": ("teknoloji", "konu"),
    "climate change": ("iklim krizi", "konu"),
    "ecology": ("ekoloji", "konu"),
    "nature": ("doğa", "konu"),
    "animals": ("hayvanlar", "konu"),
    "food": ("yemek", "konu"),
    "cooking": ("mutfak", "konu"),
    "art": ("sanat", "konu"),
    "music": ("müzik", "konu"),
    "painting": ("resim", "konu"),
    "photography": ("fotoğraf", "konu"),
    "architecture": ("mimari", "konu"),
    "motion pictures": ("sinema", "konu"),
    "sports": ("spor", "konu"),
    "medicine": ("tıp", "konu"),
    "health": ("sağlık", "konu"),
    "nutrition": ("beslenme", "konu"),
    "education": ("eğitim", "konu"),
    "language and languages": ("diller", "konu"),
    "writing": ("yazarlık", "konu"),
    "books and reading": ("kitaplar ve okumak", "konu"),

    # Yaşam öyküleri
    "biography": ("bir hayat hikâyesi", "konu"),
    "autobiography": ("otobiyografi", "konu"),
    "memoirs": ("anı", "konu"),
    "diaries": ("günlükler", "konu"),
    "childhood": ("çocukluk", "konu"),
    "old age": ("yaşlılık", "konu"),
    "school": ("okul", "mekan"),
    "high school": ("lise", "mekan"),
    "teachers": ("öğretmenler", "figur"),
    "physicians": ("doktorlar", "figur"),
    "soldiers": ("askerler", "figur"),
    "artists": ("sanatçılar", "figur"),
    "scientists": ("bilim insanları", "figur"),
    "kings and rulers": ("hükümdarlar", "figur"),
    "orphans": ("yetimler", "figur"),
    "cats": ("kediler", "figur"),
    "dogs": ("köpekler", "figur"),
    "horses": ("atlar", "figur"),

    # ── Gerçek katalogda sık geçip karşılığı olmayan konular ──────────────
    # (2026-09-19 ölçümü: konusu olan kitapların %59'unda tema bulunuyordu.
    #  Yalnızca *gerçek tema* olanlar eklendi; "Fiction", "General",
    #  "Large type books", "Handbooks" gibi yapısal etiketler bilinçli olarak
    #  dışarıda — onlardan "büyük puntolu kitap üzerine bir roman" gibi
    #  anlamsız istekler üretilirdi.)
    "man-woman relationships": ("aşk ilişkileri", "konu"),
    "interpersonal relations": ("insan ilişkileri", "konu"),
    "social life and customs": ("toplumsal yaşam", "konu"),
    "manners and customs": ("gelenekler", "konu"),
    "criticism and interpretation": ("edebiyat eleştirisi", "konu"),
    "christianity": ("Hristiyanlık", "konu"),
    "bible": ("İncil", "konu"),
    "church history": ("kilise tarihi", "konu"),
    "english language": ("İngilizce", "konu"),
    "world politics": ("dünya siyaseti", "konu"),
    "international relations": ("uluslararası ilişkiler", "konu"),
    "social conditions": ("toplumsal koşullar", "konu"),
    "economic conditions": ("ekonomik koşullar", "konu"),
    "civil rights": ("sivil haklar", "konu"),
    "public opinion": ("kamuoyu", "konu"),
    "united states": ("Amerika", "mekan"),
    "great britain": ("İngiltere", "mekan"),
    "england": ("İngiltere", "mekan"),
    "scotland": ("İskoçya", "mekan"),
    "ireland": ("İrlanda", "mekan"),
    "france": ("Fransa", "mekan"),
    "germany": ("Almanya", "mekan"),
    "italy": ("İtalya", "mekan"),
    "spain": ("İspanya", "mekan"),
    "china": ("Çin", "mekan"),
    "greece": ("Yunanistan", "mekan"),
    "turkey": ("Türkiye", "mekan"),
    "canada": ("Kanada", "mekan"),
    "australia": ("Avustralya", "mekan"),
    "california": ("Kaliforniya", "mekan"),
    "husband and wife": ("evlilik", "konu"),
    "self-help techniques": ("kendine yardım", "konu"),
    "conduct of life": ("yaşam felsefesi", "konu"),
    "success in business": ("iş hayatında başarı", "konu"),
    "human-animal relationships": ("insan-hayvan ilişkisi", "konu"),
    "environmental protection": ("çevre koruma", "konu"),
    "agriculture": ("tarım", "konu"),
    "architecture, domestic": ("ev mimarisi", "konu"),
}

#: İçerik uyarısı gerektiren konular → Türkçe uyarı metni.
CONTENT_FLAGS: dict[str, str] = {
    "suicide": "intihar",
    "sexual abuse": "cinsel istismar",
    "child abuse": "çocuk istismarı",
    "rape": "cinsel şiddet",
    "domestic violence": "aile içi şiddet",
    "violence": "şiddet",
    "torture": "işkence",
    "drug abuse": "madde bağımlılığı",
    "alcoholism": "alkolizm",
    "eating disorders": "yeme bozukluğu",
    "genocide": "soykırım",
    "holocaust": "Holokost",
    "war": "savaş sahneleri",
    "murder": "cinayet",
    "death": "ölüm teması",
    "grief": "yas",
    "depression, mental": "depresyon",
    "racism": "ırkçılık",
    "slavery": "kölelik",
    "terminal illness": "ölümcül hastalık",
}


def _norm(subject: str) -> str:
    return subject.strip().lower()


def theme_for(subject: str) -> tuple[str, str] | None:
    """Tek bir konuyu Türkçe temaya çevirir (tam eşleşme → alt dize)."""
    key = _norm(subject)
    if key in THEMES:
        return THEMES[key]
    # "Fiction, science fiction, general" gibi bileşik konular için alt dize.
    for candidate, value in THEMES.items():
        if len(candidate) >= 6 and candidate in key:
            return value
    return None


def themes_for(subjects: list[str], *, limit: int = 6) -> list[tuple[str, str]]:
    """Konu listesinden benzersiz Türkçe temalar."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for s in subjects:
        hit = theme_for(s)
        if hit and hit[0] not in seen:
            seen.add(hit[0])
            out.append(hit)
        if len(out) >= limit:
            break
    return out


def content_notes_for(subjects: list[str], *, limit: int = 3) -> list[str]:
    """Hassas içerik uyarıları (Türkçe)."""
    notes: list[str] = []
    joined = " | ".join(_norm(s) for s in subjects)
    for needle, note in CONTENT_FLAGS.items():
        if needle in joined and note not in notes:
            notes.append(note)
        if len(notes) >= limit:
            break
    return notes
