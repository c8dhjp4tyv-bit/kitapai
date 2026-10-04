"""Değerlendirme ölçütleri."""

from __future__ import annotations

from pathlib import Path

import pytest

from kitapai.evaluation.metrics import EvalResult, copied_from, distinct_n, is_turkish
from kitapai.evaluation.run import evaluate
from kitapai.serve.engine import StubEngine


def test_turkce_tespiti():
    assert is_turkish("Karanlık bir distopya arıyorsan bu kitap tam sana göre.")
    assert not is_turkish("This is a novel about the story of a reader and the author.")
    assert not is_turkish("")


def test_kopyalama_tespiti():
    source = "A desert planet, a noble family's fall, and a messianic uprising that reshapes"
    assert copied_from("Kitap: A desert planet, a noble family's fall, and a messianic uprising that reshapes", source)
    assert not copied_from("Çölde geçen destansı bir roman.", source)


def test_distinct2_tekrari_yakaliyor():
    tekrar = ["aynı cümle burada"] * 10
    cesitli = [f"farklı bir cümle {i} burada" for i in range(10)]
    assert distinct_n(tekrar, 2) < distinct_n(cesitli, 2)


def test_degerlendirme_stub_uzerinde_calisiyor(dataset_dir: Path):
    result = evaluate(StubEngine(), dataset_dir / "select_train.jsonl", samples=15, mode="select")
    assert result.n > 0
    assert result.json_valid == 1.0
    assert result.id_valid == 1.0
    assert result.limit_respected == 1.0


class _OracleEngine(StubEngine):
    """Hedef yanıtı aynen döndürür — ölçütlerin üst sınırını doğrulamak için."""

    name = "oracle"

    def __init__(self, rows):
        self._targets = {r["messages"][1]["content"]: r["messages"][2]["content"] for r in rows}

    def generate(self, messages, **kwargs):
        return self._targets[messages[-1]["content"]]


def _rows(path: Path, n: int) -> list[dict]:
    import json

    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()[:n]]


def test_kahin_motoru_tam_isabet_veriyor(dataset_dir: Path):
    """Hedefi döndüren motor precision = recall = 1.0 almalı; ölçüt doğru çalışıyor."""
    path = dataset_dir / "select_train.jsonl"
    result = evaluate(_OracleEngine(_rows(path, 15)), path, samples=15, mode="select")
    assert result.pick_precision == 1.0
    assert result.pick_recall == 1.0
    assert result.id_valid == 1.0


def test_rastgele_siralama_kahinden_belirgin_kotu(dataset_dir: Path):
    """`stub` aday sırasına bakmadan ilk N'i seçer; aday listesi karıştırıldığı için bu
    şansa eşittir — modelin kazanımını anlamlı kılan taban çizgisi."""
    result = evaluate(StubEngine(), dataset_dir / "select_train.jsonl", samples=40, mode="select")
    assert result.pick_precision < 0.9
    assert 0.0 <= result.pick_recall <= 1.0


def test_eski_bicim_legacy_modunda_olculuyor(dataset_dir: Path):
    """v1-v3 adaptörlerini AYNI koşullarda yeniden ölçebilmek için eski biçim korunur."""
    path = dataset_dir / "train.jsonl"
    rows = _rows(path, 12)
    result = evaluate(_OracleEngine(rows), path, samples=12, mode="legacy")
    assert result.json_valid == 1.0
    assert result.pick_precision == 1.0


def test_bilinmeyen_mod_reddediliyor(dataset_dir: Path):
    with pytest.raises(ValueError, match="bilinmeyen mod"):
        evaluate(StubEngine(), dataset_dir / "select_train.jsonl", mode="xyz")


def test_secim_kayitlari_hakem_icin_yaziliyor(dataset_dir: Path, tmp_path: Path):
    import json

    rec = tmp_path / "picks.jsonl"
    evaluate(StubEngine(), dataset_dir / "select_train.jsonl", samples=5, mode="select",
             record_path=rec)
    lines = [json.loads(line) for line in rec.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 5
    assert {"i", "ids", "valid_ids", "reference"} <= set(lines[0])
    assert all(set(r["ids"]) <= set(r["valid_ids"]) for r in lines)


def test_yazim_modu_metin_kalitesini_olcuyor(tmp_path: Path):
    """YAZ modu: Türkçe, 'siz' hitabı ve kimlik kapsamı ölçülür."""
    import json

    user = ("OKURUN İSTEĞİ\nOkurun sözleri: x\n\nSEÇİLEN KİTAPLAR\n"
            "[a1] Dune — Frank Herbert · 1965\n     uyum: güçlü\n\n"
            "[a2] Hobbit — Tolkien · 1937\n     uyum: orta")
    good = ("a1: Çöl gezegeninde geçen epik bir hikâye arıyorsan tam senlik.\n"
            "a2: Yolculuk seven biri olarak bu macerayı çok seveceksin elbette.")
    row = {"messages": [{"role": "system", "content": "gerekçe yazarı"},
                        {"role": "user", "content": user},
                        {"role": "assistant", "content": good}]}
    path = tmp_path / "write.jsonl"
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")

    class Echo(StubEngine):
        def generate(self, messages, **kwargs):
            return good

    r = evaluate(Echo(), path, samples=1, mode="write")
    assert r.json_valid == 1.0 and r.id_coverage == 1.0
    assert r.turkish_ratio == 1.0 and r.formal_ratio == 0.0

    formal = "a1: Aradığınız epik hikâye burada sizi bekliyor, ilginizi çekecektir."

    class Formal(StubEngine):
        def generate(self, messages, **kwargs):
            return formal

    rf = evaluate(Formal(), path, samples=1, mode="write")
    assert rf.formal_ratio == 1.0 and rf.id_coverage == 0.5     # a2 için gerekçe yok


def test_sahte_sifir_olcut_kalmadi():
    """`filter_precision`/`calibration_error` hiç hesaplanmadan 0.0 basıyordu."""
    fields = EvalResult().as_dict()
    assert "filter_precision" not in fields and "calibration_error" not in fields
    assert {"pick_precision", "pick_recall", "conf_gap"} <= set(fields)
