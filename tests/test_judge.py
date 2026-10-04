import json

import pytest

from kitapai.dataset.distill import DistillError
from kitapai.evaluation import judge as J


def _row(n=4, limit=2):
    cands = "\n".join(f"[a{i}] Kitap {i} — Yazar · 2000\n     özet: x" for i in range(1, n + 1))
    user = f"İSTEK\nOkurun sözleri: x\nİstenen öneri sayısı: {limit}\n\nADAYLAR\n{cands}"
    return {"messages": [{"role": "system", "content": "s"}, {"role": "user", "content": user},
                         {"role": "assistant", "content": json.dumps({"ids": ["a1", "a2"]})}]}


class FakeClient:
    model = "fake"

    def __init__(self, ratings):
        self.ratings, self.calls = ratings, 0

    def generate(self, system, user, *, temperature=0.7):
        self.calls += 1
        body = json.dumps({"ratings": self.ratings})
        return {"candidates": [{"content": {"parts": [{"text": body}]}}]}


def _dataset(tmp_path, rows):
    p = tmp_path / "v.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return p


def test_parse_ratings_drops_unknown_and_bad_values():
    out = J.parse_ratings({"ratings": {"a1": 2, "a2": "1", "a3": 5, "zz": 2, "a4": True}},
                          ["a1", "a2", "a3", "a4"])
    assert out == {"a1": 2, "a2": 1}


def test_parse_ratings_rejects_mostly_missing():
    with pytest.raises(DistillError):
        J.parse_ratings({"ratings": {"a1": 2}}, ["a1", "a2", "a3", "a4"])
    with pytest.raises(DistillError):
        J.parse_ratings({}, ["a1"])


def test_cache_makes_second_run_free(tmp_path):
    ds = _dataset(tmp_path, [_row(), _row()])
    client = FakeClient({"a1": 2, "a2": 0, "a3": 1, "a4": 2})
    cache = tmp_path / "c.jsonl"
    first = J.judge_samples(client, ds, cache, samples=2, workers=2)
    assert client.calls == 2 and set(first) == {0, 1}
    J.judge_samples(client, ds, cache, samples=2, workers=2)
    assert client.calls == 2


def test_score_has_bounds_and_normalizes():
    ratings = {0: {"a1": 2, "a2": 0, "a3": 1, "a4": 2}}
    limits = {0: 2}
    ideal = J.score_records("i", [{"i": 0, "ids": ["a1", "a4"]}], ratings, limits)
    bad = J.score_records("b", [{"i": 0, "ids": ["a2", "a3"]}], ratings, limits)
    assert ideal.mean_grade == 2.0 and ideal.ideal_grade == 2.0
    assert ideal.normalized == pytest.approx(1.0)
    assert bad.mean_grade == 0.5 and bad.bad_rate == 0.5 and bad.normalized < 0
    assert ideal.random_grade == pytest.approx(1.25)


def test_no_pick_is_counted_and_limit_applies():
    ratings = {0: {"a1": 2, "a2": 2, "a3": 0, "a4": 0}}
    s = J.score_records("m", [{"i": 0, "ids": []}], ratings, {0: 2})
    assert s.no_pick == 1.0 and s.mean_grade == 0.0
    s = J.score_records("m", [{"i": 0, "ids": ["a1", "a2", "a3"]}], ratings, {0: 2})
    assert s.mean_grade == 2.0            # üçüncü seçim limit dışı sayılmaz


def test_reference_records_and_limits(tmp_path):
    ds = _dataset(tmp_path, [_row(limit=3)])
    assert J.reference_records(ds, 1) == [{"i": 0, "ids": ["a1", "a2"]}]
    assert J.limits_for(ds, 1) == {0: 3}


def test_judged_pick_ids_prefers_grade_then_reference_then_order():
    grades = {"a1": 1, "a2": 2, "a3": 0, "a4": 2, "a5": 1}
    order = ["a1", "a2", "a3", "a4", "a5"]
    # 2'ler önce; eşit notta referans sırası (a4 referansta önde)
    assert J.judged_pick_ids(grades, ["a4", "a1"], 3, order) == ["a4", "a2", "a1"]
    assert J.judged_pick_ids(grades, [], 1, order) == ["a2"]
    assert J.judged_pick_ids({"a1": 0, "a2": 0}, [], 3, ["a1", "a2"]) == []


def test_relabel_rows_rewrites_target_and_drops_hopeless():
    rows = [_row(limit=2), _row(limit=2), _row(limit=2)]
    ratings = {0: {"a1": 0, "a2": 0, "a3": 2, "a4": 1}, 1: {"a1": 0, "a2": 0, "a3": 0, "a4": 0}}
    out, stats = J.relabel_rows(rows, ratings)
    assert len(out) == 1
    assert json.loads(out[0]["messages"][-1]["content"]) == {"ids": ["a3", "a4"]}
    assert out[0]["meta"]["ref_ids"] == ["a1", "a2"]
    assert stats["notsuz"] == 1 and stats["uygun_yok"] == 1 and stats["ref_kotu_elenen"] == 2


def test_parse_write_ratings_and_score():
    out = J.parse_write_ratings(
        {"items": {"a1": {"grounded": 0, "useful": 2}, "a2": {"grounded": 2, "useful": 1},
                   "a3": {"grounded": 9, "useful": 1}}}, ["a1", "a2", "a3", "a9"])
    assert set(out) == {"a1", "a2"}
    s = J.score_writing("m", {0: out})
    assert s.items == 2 and s.fabricated == 0.5 and s.grounded == 1.0 and s.useful == 1.5
    with pytest.raises(DistillError):
        J.parse_write_ratings({"items": {}}, ["a1"])


def test_judge_writing_cache_keys_on_text(tmp_path):
    ds = _dataset(tmp_path, [_row()])
    client = FakeClient({})
    client.generate = lambda system, user, *, temperature=0.7: {"candidates": [{"content": {
        "parts": [{"text": json.dumps({"items": {"a1": {"grounded": 2, "useful": 2}}})}]}}]}
    calls = []
    orig = client.generate
    client.generate = lambda *a, **k: (calls.append(1), orig(*a, **k))[1]
    cache = tmp_path / "w.jsonl"
    rec = {"i": 0, "items": {"a1": {"why": "bir", "hooks": []}}}
    J.judge_writing(client, ds, [rec], cache)
    J.judge_writing(client, ds, [rec], cache)
    assert len(calls) == 1
    J.judge_writing(client, ds, [{"i": 0, "items": {"a1": {"why": "iki", "hooks": []}}}], cache)
    assert len(calls) == 2
