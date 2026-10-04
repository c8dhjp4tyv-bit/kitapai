"""Eğitim etiket maskelemesi — gerçek Qwen tokenizer'ıyla.

Kaybın yalnızca asistan yanıtında hesaplandığı, bitiş belirtecinin dâhil
olduğu ve bağlama sığmayan örneğin sessizce kesilmediği doğrulanır.
Tokenizer yerel önbellekte yoksa testler atlanır (ağ gerektirmesin).
"""

from __future__ import annotations

import json

import pytest

from kitapai.train import data as td

MODEL = "Qwen/Qwen2.5-3B-Instruct"


@pytest.fixture(scope="module")
def tok():
    transformers = pytest.importorskip("transformers")
    try:
        return transformers.AutoTokenizer.from_pretrained(MODEL, local_files_only=True)
    except Exception:  # önbellekte yok
        pytest.skip("Qwen tokenizer yerel önbellekte yok")


MESSAGES = [
    {"role": "system", "content": "Sen bir kitap uzmanısın."},
    {"role": "user",
     "content": "İSTEK\nkaranlık bir distopya\n\nADAYLAR\n[a1] 1984 — George Orwell"},
    {"role": "assistant", "content": json.dumps(
        {"picks": [{"id": "a1", "why": "Karanlık bir gözetim distopyası."}], "followups": []},
        ensure_ascii=False)},
]


def test_yalnizca_asistan_yaniti_denetleniyor(tok):
    t = td.tokenize_example(tok, MESSAGES, max_length=1024)
    supervised = [i for i, lab in zip(t.input_ids, t.labels, strict=True) if lab != td.IGNORE_INDEX]
    decoded = tok.decode(supervised)
    assert decoded == MESSAGES[-1]["content"] + "<|im_end|>"
    # İstem, sistem mesajı ve aday listesi asla denetlenmez
    assert "ADAYLAR" not in decoded and "kitap uzmanısın" not in decoded


def test_bitis_belirteci_kayba_dahil(tok):
    """Model JSON'u bitirip durmayı da öğrenmeli; yoksa üretim sonsuza uzar."""
    t = td.tokenize_example(tok, MESSAGES, max_length=1024)
    end = tok.convert_tokens_to_ids("<|im_end|>")
    assert t.labels[t.input_ids.index(end, len(t.input_ids) - 5)] == end
    # Bitişten sonraki şablon satır sonu maskeli
    assert t.labels[-1] == td.IGNORE_INDEX


def test_etiket_ve_girdi_ayni_uzunlukta(tok):
    t = td.tokenize_example(tok, MESSAGES, max_length=1024)
    assert len(t.input_ids) == len(t.labels)
    assert t.n_supervised > 0


def test_baglama_sigmayan_ornek_sessizce_kesilmiyor(tok):
    """Kesilen kısım sondaki asistan yanıtı olurdu; eğitim işe yaramazdı."""
    with pytest.raises(td.TruncatedExampleError, match="kesilirdi"):
        td.tokenize_example(tok, MESSAGES, max_length=20)


def test_asistan_yaniti_olmayan_ornek_reddediliyor(tok):
    with pytest.raises(ValueError, match="asistan"):
        td.tokenize_example(tok, MESSAGES[:-1], max_length=1024)


def test_veri_kumesi_istatistigi(tok):
    rows = [{"messages": MESSAGES}, {"messages": MESSAGES}]
    _, stats = td.tokenize_dataset(tok, rows, max_length=1024)
    assert stats["kullanilan"] == 2 and stats["atilan_uzun"] == 0
    assert stats["denetlenen_token"] < stats["toplam_token"] / 2  # istem baskın
    _, short = td.tokenize_dataset(tok, rows, max_length=20)
    assert short["kullanilan"] == 0 and short["atilan_uzun"] == 2


def test_toplu_doldurma_etiketleri_maskeliyor():
    batch = [
        {"input_ids": [1, 2, 3], "labels": [-100, 2, 3]},
        {"input_ids": [1, 2], "labels": [-100, 2]},
    ]
    padded = td.pad_batch(batch, pad_id=0)
    assert padded["input_ids"][1] == [1, 2, 0]
    assert padded["labels"][1] == [-100, 2, -100]
    assert padded["attention_mask"][1] == [1, 1, 0]
