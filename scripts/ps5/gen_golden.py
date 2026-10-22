"""C++ çekirdeğini Python ile karşılaştıracak 'altın' değerleri üretir (golden test).

Çıktı: genişletme sonuçları, istek bloğu, aday gösterimi, uyum puanı ve çözücü örnekleri.
Kullanım: python scripts/ps5/gen_golden.py <bundle-dizini> <golden.json>
"""
from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

import duckdb

from kitapai.config import get_settings
from kitapai.matching import match_reasons, match_score
from kitapai.prompting import Candidate, render_candidate, render_request
from kitapai.retrieval.expand import expand
from kitapai.retrieval.hybrid import Retriever, Target
from kitapai.serve.decode import decode_select, decode_write


class Req:
    def __init__(self, **kw):
        self.query = kw.get("query", ""); self.genres = kw.get("genres", []); self.moods = kw.get("moods", [])
        self.languages = kw.get("languages", []); self.era = kw.get("era"); self.length = kw.get("length")
        self.audience = kw.get("audience"); self.exclude_work_keys = []; self.strictness = None; self.seed = None
        self.limit = kw.get("limit", 3)


def main() -> None:
    bundle, out = Path(sys.argv[1]), Path(sys.argv[2])
    rng = random.Random(7)
    con = duckdb.connect(str(get_settings().catalog_file), read_only=True)
    retriever = Retriever(con, None)

    queries: list[str] = []
    for line in Path("data/dataset/select_valid.jsonl").read_text(encoding="utf-8").splitlines()[:400]:
        user = json.loads(line)["messages"][1]["content"]
        m = re.search(r"Okurun sözleri: (.+)", user)
        if m and m.group(1) != "(belirtmedi)":
            queries.append(m.group(1))
    queries = list(dict.fromkeys(queries))[:60]
    queries += ["sorgulatan bir bilim kurgu romanı önerir misin?", "metroda okumak için, içini ısıtan bir kitap",
                "çölde geçen, ağır olmayan epik bir macera", "Dostoyevski tarzı karanlık psikolojik roman",
                "çocuğuma uyumadan önce okuyabileceğim kısa bir kitap", "asdkjh qwe zzz", "", "İSTANBUL'da geçen polisiye",
                "yas ve kayıp üzerine sakin bir roman", "yapay zekânın geleceği"]

    expansions = []
    for q in queries:
        e = expand(q, genres=[], moods=[])
        expansions.append({"query": q, "terms": e.terms, "genres": e.detected_genres, "moods": e.detected_moods,
                           "themes": e.detected_themes, "content_words": e.content_words,
                           "query_text": e.query_text})
    expansions.append({"query": "tema", "chips_genres": ["klasik"], "chips_moods": ["karanlik"],
                       **{k: v for k, v in zip(("terms", "genres", "moods", "themes", "content_words", "query_text"), (
                           (lambda e: (e.terms, e.detected_genres, e.detected_moods, e.detected_themes,
                                       e.content_words, e.query_text))(expand("tema", genres=["klasik"], moods=["karanlik"]))))}})

    # İstek blokları
    requests = [
        dict(query="karanlık bir distopya", genres=["bilim-kurgu"], moods=["karanlik"], era="modern", length="orta",
             audience="yetiskin", languages=["tur"], limit=3),
        dict(query="", genres=[], moods=[], limit=5),
        dict(query="  hafif  ", genres=["romantik"], moods=[], limit=2),
    ]
    request_blocks = [{"req": r, "block": render_request(
        query=r["query"], genres=r["genres"], moods=r["moods"], era=r.get("era"), length=r.get("length"),
        audience=r.get("audience"), languages=r.get("languages"), limit=r["limit"])} for r in requests]

    # Aday gösterimi + uyum puanı, ihraç edilen kümeden rastgele kitaplar
    keys = [l.split("\t", 1)[0] for l in (bundle / "books.tsv").read_text(encoding="utf-8").splitlines()]
    sample = rng.sample(keys, 150)
    rows = retriever.fetch(sample)
    renders, scores = [], []
    targets = [
        Target(), Target(genres=["bilim-kurgu"]), Target(genres=["klasik", "roman"], moods=["karanlik"]),
        Target(genres=["romantik"], era="modern", length="orta"), Target(audience="cocuk", languages=["tur"]),
    ]
    for k in sample:
        row = rows[k]
        cid = f"a{rng.randint(1, 12)}"
        renders.append({"key": k, "cid": cid, "text": render_candidate(Candidate.from_row(row, cid))})
        for i, t in enumerate(targets):
            scores.append({"key": k, "t": i, "score": match_score(row, t), "reasons": match_reasons(row, t)})

    decode = []
    for raw in ['{"ids": ["a6", "a5", "a7"]}', '```json\n{"ids":["a1","a1","a2",]}\n```', '{"ids":["a3","a4"',
                "", "yok", '{"picks":[]}', 'önce {"ids":["a2"]} sonra']:
        ids, err = decode_select(raw)
        decode.append({"kind": "select", "raw": raw, "ids": ids, "ok": ids is not None})
    for raw in ["a1: Tam senlik.\n\n- **a2**: Olur.\nçöp\na1: ikinci kez", "", "yok", "a10：Geniş iki nokta"]:
        items, err = decode_write(raw)
        decode.append({"kind": "write", "raw": raw, "items": {k: v["why"] for k, v in items.items()}, "ok": err is None})

    # Geri getirme: Python (tam katalog, yalnız sözcüksel) — yalnızca bilgi için örtüşme ölçülür.
    retrieval = []
    for q, kw in [(q, {}) for q in queries[:30]] + [
            ("sorgulatan bir roman", dict(genres=["bilim-kurgu"])), ("aşk", dict(moods=["romantik"], era="modern"))]:
        req = Req(query=q, **kw)
        res = retriever.retrieve(req, pool=40)
        retrieval.append({"req": {"query": q, **kw}, "keys": [b["work_key"] for b in res.books[:12]],
                          "browse": res.used_browse})

    out.write_text(json.dumps({"expansions": expansions, "request_blocks": request_blocks, "renders": renders,
                               "scores": scores, "targets": [t.__dict__ for t in targets], "decode": decode,
                               "retrieval": retrieval}, ensure_ascii=False), encoding="utf-8")
    print(f"{len(expansions)} genişletme, {len(renders)} gösterim, {len(scores)} puan, {len(retrieval)} geri getirme")


if __name__ == "__main__":
    main()
