"""Gemini hakem değerlendirmesi: modelin seçimleri gerçekten isteğe uyuyor mu?

Referans tabanlı isabet (`evaluation/run.py`) yalnızca eğitim hedefinin seçtiği
birkaç kitabı "doğru" sayar. Belirsiz bir istekte (örn. "güzel bir klasik") uyan
yüzlerce kitap vardır; model referanstakinden farklı ama eşit derecede iyi bir
kitap seçince ölçüt onu cezalandırır. Hakem bu yanlılığı giderir: her örnek için
**tüm adaylara bir kez** 0–2 not verir, modellerin seçimleri bu notlarla puanlanır.

  2  isteğin koşullarına açıkça uyuyor
  1  kısmen uyuyor
  0  uymuyor

Notlar örnek başına önbelleğe alınır; aynı örnekler üzerinde v1/v2/v3/seçici
karşılaştırması tek hakem maliyetiyle yapılır ve notlar modelden bağımsızdır.
Rastgele seçim ve ideal seçim alt/üst sınır olarak raporlanır.
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..dataset.distill import DistillError, GeminiClient, extract_json
from ..logging import get

log = get("judge")

_CANDIDATE_LINE = re.compile(r"^\[(a\d+)\]", re.MULTILINE)
_LIMIT = re.compile(r"İstenen öneri sayısı:\s*(\d+)")

JUDGE_SYSTEM = """Sen tarafsız bir kitap önerisi hakemisin.

Bir okurun isteği ve aday kitaplar verilir. HER aday için, kitabın isteğe uygunluğunu
0, 1 ya da 2 ile notla:
  2 = istekteki koşulların (tür, ruh hali, konu, dönem, uzunluk, dil, ton) hepsine
      açıkça uyuyor; okura rahatça önerilir
  1 = kısmen uyuyor ya da kanıt zayıf (bir koşul eksik/belirsiz)
  0 = uymuyor ya da isteğe ters (yanlış tür, istenmeyen ton, alakasız konu)

Kurallar:
- Adayın verilen bilgilerine dayan (tür, ruh, konular, özet). Kitabı gerçekten
  tanıyorsan bilgini de kullanabilirsin ama bilmediğin kitaba not uydurma; belirsizse 1 ver.
- Okurun sözleri filtrelerle çelişirse okurun sözlerini esas al.
- Aday listesinin sırası bir ipucu değildir.
- Tüm adaylar için not ver, hiçbirini atlama.
Yanıt YALNIZCA JSON olsun: {"ratings":{"a1":2,"a2":0,...}}"""


@dataclass
class JudgedSample:
    i: int
    ratings: dict[str, int]


@dataclass
class JudgeScore:
    """Bir modelin hakem puanı. Notlar 0–2 aralığındadır."""

    label: str
    n: int = 0
    mean_grade: float = 0.0      # seçilen kitapların ortalama notu
    good_rate: float = 0.0       # seçilenlerin kaçı 2 aldı
    bad_rate: float = 0.0        # seçilenlerin kaçı 0 aldı
    no_pick: float = 0.0         # hiç seçim üretemeyen örnek oranı
    random_grade: float = 0.0    # alt sınır: adaylardan rastgele seçim (beklenen)
    ideal_grade: float = 0.0     # üst sınır: en yüksek notlu `limit` aday
    normalized: float = 0.0      # (model - rastgele) / (ideal - rastgele)
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        d = asdict(self)
        d.pop("extra")
        return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in d.items()}


def candidate_ids(user_message: str) -> list[str]:
    return _CANDIDATE_LINE.findall(user_message)


def request_limit(user_message: str) -> int:
    m = _LIMIT.search(user_message)
    return int(m.group(1)) if m else 3


def parse_ratings(payload: dict, valid_ids: list[str]) -> dict[str, int]:
    """Hakem yanıtından {kimlik: 0|1|2} çıkarır; aday dışı/bozuk girdileri atar.

    Eksik adaylar notsuz kalır (puanlamada yok sayılır) — varsayılan not uydurmak
    hakemin sessizce yanlı çıkmasına yol açardı.
    """
    raw = payload.get("ratings")
    if not isinstance(raw, dict):
        raise DistillError("yanıtta 'ratings' nesnesi yok")
    valid = set(valid_ids)
    out: dict[str, int] = {}
    for cid, grade in raw.items():
        if cid not in valid or isinstance(grade, bool):
            continue
        try:
            value = int(grade)
        except (TypeError, ValueError):
            continue
        if value in (0, 1, 2):
            out[cid] = value
    if len(out) < max(2, len(valid_ids) // 2):
        raise DistillError(
            f"hakem adayların yarısından azını notladı ({len(out)}/{len(valid_ids)})")
    return out


def _load_rows(dataset_path: Path, samples: int) -> list[dict]:
    rows: list[dict] = []
    with dataset_path.open(encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            if i >= samples:
                break
            rows.append(json.loads(line))
    return rows


def _load_cache(path: Path) -> dict[int, dict[str, int]]:
    cache: dict[int, dict[str, int]] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                cache[row["i"]] = {k: int(v) for k, v in row["ratings"].items()}
    return cache


def judge_samples(
    client: GeminiClient,
    dataset_path: Path,
    cache_path: Path,
    *,
    samples: int = 100,
    workers: int = 8,
) -> dict[int, dict[str, int]]:
    """Her örneğin adaylarını notlar; yalnızca önbellekte olmayanları sorar.

    Hata veren örnek atlanır (sonraki çalıştırma yalnızca onu yeniden dener).
    """
    rows = _load_rows(dataset_path, samples)
    cache = _load_cache(cache_path)
    todo = [i for i in range(len(rows)) if i not in cache]
    if todo:
        cache_path.parent.mkdir(parents=True, exist_ok=True)

        def work(i: int) -> tuple[int, dict[str, int]]:
            user = rows[i]["messages"][1]["content"]
            payload = extract_json(client.generate(JUDGE_SYSTEM, user, temperature=0.0))
            return i, parse_ratings(payload, candidate_ids(user))

        failed = 0
        with cache_path.open("a", encoding="utf-8") as out, \
                ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(work, i): i for i in todo}
            for done, fut in enumerate(as_completed(futures), 1):
                try:
                    i, ratings = fut.result()
                except Exception as exc:   # tek örnek bütün işi düşürmesin
                    failed += 1
                    log.warning("örnek %d notlanamadı: %s", futures[fut], exc)
                    continue
                cache[i] = ratings
                out.write(json.dumps({"i": i, "ratings": ratings}, ensure_ascii=False) + "\n")
                out.flush()
                if done % 20 == 0:
                    log.info("hakem: %d/%d", done, len(todo))
        if failed:
            log.warning("%d örnek notlanamadı; yeniden çalıştırınca denenir", failed)
    return {i: r for i, r in cache.items() if i < len(rows)}


def score_records(
    label: str,
    records: list[dict],
    ratings: dict[int, dict[str, int]],
    limits: dict[int, int],
) -> JudgeScore:
    """Bir modelin kayıtlarını (`evaluate(..., record_path=)`) hakem notlarıyla puanlar.

    Yalnızca hakemin notladığı örnekler sayılır; aynı örnek kümesinde rastgele ve
    ideal seçim de hesaplanır ki sayı tek başına yorumlanabilsin.
    """
    chosen_grades: list[int] = []
    rand, ideal = [], []
    n = no_pick = 0
    for rec in records:
        i = rec["i"]
        grades = ratings.get(i)
        if not grades:
            continue
        n += 1
        limit = limits.get(i, 3)
        values = sorted(grades.values(), reverse=True)
        top = values[:limit]
        ideal.append(sum(top) / len(top))
        rand.append(sum(values) / len(values))
        picked = [grades[c] for c in rec.get("ids", []) if c in grades][:limit]
        if not picked:
            no_pick += 1
            continue
        chosen_grades.extend(picked)

    score = JudgeScore(label=label, n=n)
    if not n:
        return score
    score.no_pick = no_pick / n
    score.random_grade = sum(rand) / n
    score.ideal_grade = sum(ideal) / n
    if chosen_grades:
        score.mean_grade = sum(chosen_grades) / len(chosen_grades)
        score.good_rate = sum(g == 2 for g in chosen_grades) / len(chosen_grades)
        score.bad_rate = sum(g == 0 for g in chosen_grades) / len(chosen_grades)
    span = score.ideal_grade - score.random_grade
    score.normalized = (score.mean_grade - score.random_grade) / span if span > 1e-9 else 0.0
    return score


def reference_records(dataset_path: Path, samples: int) -> list[dict]:
    """Eğitim hedefini (referans seçim) model kaydı gibi döndürür; hakemin referans notu."""
    from .run import _reference_ids

    out = []
    for i, row in enumerate(_load_rows(dataset_path, samples)):
        try:
            target = json.loads(row["messages"][-1]["content"])
            ids = target["ids"] if "ids" in target else [p["id"] for p in target["picks"]]
        except (KeyError, ValueError, TypeError):
            ids = sorted(_reference_ids(row))
        out.append({"i": i, "ids": ids})
    return out


def limits_for(dataset_path: Path, samples: int) -> dict[int, int]:
    return {i: request_limit(r["messages"][1]["content"])
            for i, r in enumerate(_load_rows(dataset_path, samples))}


def load_records(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


# ── hakem notlarından eğitim etiketi ────────────────────────────────────────


def judged_pick_ids(
    grades: dict[str, int], reference: list[str], limit: int, order: list[str]
) -> list[str]:
    """Hakem notlarından seçim etiketi: önce 2'ler, `limit` dolmazsa 1'ler; 0 asla.

    Eşit notlu adaylar arasında önce referans seçimdeki sıra (kural tabanlı uyum
    puanından geldi) sonra listedeki sıra belirler; böylece etiket deterministik ve
    eski sinyali tamamen çöpe atmayan bir hâle gelir. `ids` boş dönebilir: hiçbir aday
    en azından kısmen uymuyor.
    """
    ref_pos = {c: n for n, c in enumerate(reference)}
    pos = {c: n for n, c in enumerate(order)}
    ranked = sorted(
        (c for c, g in grades.items() if g >= 1 and c in pos),
        key=lambda c: (-grades[c], ref_pos.get(c, len(ref_pos)), pos[c]),
    )
    return ranked[:limit]


def relabel_rows(
    rows: list[dict], ratings: dict[int, dict[str, int]]
) -> tuple[list[dict], dict[str, int]]:
    """Seçim örneklerinin hedefini hakem notlarıyla yeniden yazar.

    Notlanmamış ya da hiç uygun adayı olmayan örnekler atılır (boş seçim öğretmek,
    sunucuda bu durumu karşılayan bir yol olmadan, modeli reddetmeye iter).
    """
    out: list[dict] = []
    stats = {"toplam": len(rows), "notsuz": 0, "uygun_yok": 0, "degisen": 0,
             "ref_kotu_elenen": 0}
    for i, row in enumerate(rows):
        grades = ratings.get(i)
        if not grades:
            stats["notsuz"] += 1
            continue
        user = row["messages"][1]["content"]
        limit = request_limit(user)
        old = json.loads(row["messages"][-1]["content"]).get("ids", [])
        new = judged_pick_ids(grades, old, limit, candidate_ids(user))
        if not new:
            stats["uygun_yok"] += 1
            continue
        stats["ref_kotu_elenen"] += sum(1 for c in old if grades.get(c, 0) == 0)
        stats["degisen"] += int(new != old)
        meta = dict(row.get("meta") or {})
        meta["judge_grades"] = {c: grades[c] for c in new}
        meta["ref_ids"] = old
        out.append({**row, "meta": meta, "messages": [
            *row["messages"][:-1],
            {"role": "assistant", "content": json.dumps({"ids": new}, ensure_ascii=False)},
        ]})
    stats["kalan"] = len(out)
    return out, stats


# ── yazıcı hakemi: gerekçeler kitap bilgisiyle destekleniyor mu? ─────────────

WRITE_JUDGE_SYSTEM = """Sen bir kitap öneri metni denetçisisin.

Bir okurun isteği, önerilen kitapların VERİLEN bilgileri ve her kitap için yazılmış
gerekçe (why) verilir. Her gerekçeyi iki ölçüte göre 0, 1 ya da 2 ile notla:

grounded (dayanak): gerekçedeki somut iddialar verilen bilgiyle (tür, ruh, konular,
  özet, sayfa, puan) destekleniyor mu?
  2 = iddiaların hepsi desteklenir ya da gerekçe genel kalır, uydurma yok
  1 = küçük bir şüpheli ayrıntı var
  0 = verilen bilgide olmayan olay/tema/karakter/ayrıntı uyduruyor ya da bilgiyle çelişiyor
  (Kitabı gerçekten tanıyorsan ve iddia doğruysa 2 verebilirsin; emin değilsen 1.)
useful (yarar): okura bu kitabın neden istediğine uyduğunu (ya da nerede uymadığını)
  dürüstçe ve kişisel bir dille anlatıyor mu?
  2 = açık, isteğe bağlı, dürüst  1 = genel/şablon gibi  0 = alakasız, yanlış ya da bozuk

Yanıt YALNIZCA JSON: {"items":{"a1":{"grounded":2,"useful":1}, ...}}"""


@dataclass
class WriteScore:
    label: str
    n: int = 0
    grounded: float = 0.0        # ortalama dayanak notu (0-2)
    fabricated: float = 0.0      # dayanak=0 alan gerekçe oranı
    useful: float = 0.0          # ortalama yarar notu (0-2)
    items: int = 0

    def as_dict(self) -> dict:
        return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in asdict(self).items()}


def parse_write_ratings(payload: dict, wanted: list[str]) -> dict[str, dict[str, int]]:
    raw = payload.get("items")
    if not isinstance(raw, dict):
        raise DistillError("yanıtta 'items' nesnesi yok")
    out: dict[str, dict[str, int]] = {}
    for cid in wanted:
        entry = raw.get(cid)
        if not isinstance(entry, dict):
            continue
        try:
            g, u = int(entry["grounded"]), int(entry["useful"])
        except (KeyError, TypeError, ValueError):
            continue
        if g in (0, 1, 2) and u in (0, 1, 2):
            out[cid] = {"grounded": g, "useful": u}
    if not out:
        raise DistillError("hakem hiçbir gerekçeyi notlamadı")
    return out


def _write_prompt(user_message: str, items: dict[str, dict]) -> str:
    shown = {cid: it["why"] for cid, it in items.items() if it.get("why")}
    return f"{user_message}\n\nYAZILAN GEREKÇELER\n{json.dumps(shown, ensure_ascii=False)}"


def judge_writing(
    client: GeminiClient,
    dataset_path: Path,
    records: list[dict],
    cache_path: Path,
    *,
    workers: int = 8,
) -> dict[int, dict[str, dict[str, int]]]:
    """Kayıtlardaki (`eval --mode write --record`) gerekçeleri notlar. Önbellek: (örnek, metin
    özeti) — aynı metin yeniden sorulmaz, değişen metin yeniden notlanır."""
    import hashlib

    rows = _load_rows(dataset_path, max((r["i"] for r in records), default=-1) + 1)
    cache: dict[str, dict] = {}
    if cache_path.exists():
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                cache[row["key"]] = row["ratings"]

    def key(rec: dict) -> str:
        blob = json.dumps(rec.get("items", {}), ensure_ascii=False, sort_keys=True)
        return f"{rec['i']}:{hashlib.sha256(blob.encode()).hexdigest()[:16]}"

    todo = [r for r in records if r.get("items") and key(r) not in cache]
    if todo:
        cache_path.parent.mkdir(parents=True, exist_ok=True)

        def work(rec: dict) -> tuple[str, dict]:
            user = rows[rec["i"]]["messages"][1]["content"]
            payload = extract_json(client.generate(
                WRITE_JUDGE_SYSTEM, _write_prompt(user, rec["items"]), temperature=0.0))
            return key(rec), parse_write_ratings(payload, list(rec["items"]))

        with cache_path.open("a", encoding="utf-8") as out, \
                ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(work, r): r["i"] for r in todo}
            for fut in as_completed(futures):
                try:
                    k, ratings = fut.result()
                except Exception as exc:
                    log.warning("örnek %d notlanamadı: %s", futures[fut], exc)
                    continue
                cache[k] = ratings
                out.write(json.dumps({"key": k, "ratings": ratings}, ensure_ascii=False) + "\n")
                out.flush()
    return {r["i"]: cache[key(r)] for r in records if r.get("items") and key(r) in cache}


def score_writing(label: str, rated: dict[int, dict[str, dict[str, int]]]) -> WriteScore:
    g = [v["grounded"] for r in rated.values() for v in r.values()]
    u = [v["useful"] for r in rated.values() for v in r.values()]
    s = WriteScore(label=label, n=len(rated), items=len(g))
    if g:
        s.grounded = sum(g) / len(g)
        s.fabricated = sum(x == 0 for x in g) / len(g)
        s.useful = sum(u) / len(u)
    return s


def reference_writing_records(dataset_path: Path, samples: int) -> list[dict]:
    """Gemini'den damıtılmış hedef gerekçeleri model kaydı gibi döndürür (tavan)."""
    out = []
    for i, row in enumerate(_load_rows(dataset_path, samples)):
        from ..serve.decode import decode_write

        items, err = decode_write(row["messages"][-1]["content"])
        if not err:
            out.append({"i": i, "items": items})
    return out
