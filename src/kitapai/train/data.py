"""Eğitim örneklerinin tokenizasyonu ve etiket maskelemesi.

Neden TRL'nin `DataCollatorForCompletionOnlyLM`'i kullanılmıyor? TRL 0.24'te bu
sınıf kaldırıldı, `max_seq_length` → `max_length`, `tokenizer` →
`processing_class` oldu. Eğitimin doğruluğu bir kütüphanenin sürüm kaymasına
bağlı kalmamalı. Maskeleme burada, sürümden bağımsız ve test edilebilir.

Kayıp yalnızca *asistan yanıtı* üzerinden hesaplanır. İstemin büyük kısmı aday
listesidir (~2000 token); model onu ezberlemeye çalışırsa asıl öğrenmesi
gereken şeyden — seçim ve gerekçe — kopar.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

IGNORE_INDEX = -100


class TruncatedExampleError(ValueError):
    """Örnek bağlama sığmıyor; asistan yanıtı kesilirdi."""


@dataclass(frozen=True)
class Tokenized:
    input_ids: list[int]
    labels: list[int]

    @property
    def n_supervised(self) -> int:
        return sum(1 for x in self.labels if x != IGNORE_INDEX)


def tokenize_example(tokenizer: Any, messages: list[dict[str, str]], max_length: int) -> Tokenized:
    """Bir sohbet örneğini `input_ids` + maskelenmiş `labels`'a çevirir.

    İstem kısmı (`system` + `user` + asistan başlığı) `-100` ile maskelenir,
    yalnızca asistanın yanıtı ve bitiş belirteci denetlenir. Bitiş belirteci
    (`<|im_end|>`) bilinçli olarak kayba dâhil: model JSON'u bitirip durmayı
    da öğrenmeli, yoksa üretim token sınırına kadar uzar ve JSON kesilir.

    Örnek `max_length`'e sığmıyorsa sessizce kesmek yerine hata verir: kesilen
    kısım sondaki asistan yanıtı olurdu ve eğitim işe yaramazdı.
    """
    if not messages or messages[-1]["role"] != "assistant":
        raise ValueError("son mesaj asistan yanıtı olmalı")

    prompt_text = tokenizer.apply_chat_template(
        messages[:-1], tokenize=False, add_generation_prompt=True
    )
    full_text = tokenizer.apply_chat_template(messages, tokenize=False)
    if not full_text.startswith(prompt_text):
        # Sohbet şablonu istem kısmını farklı üretiyorsa maskeleme yanlış yeri
        # keserdi; bunu tahmin etmek yerine açıkça reddet.
        raise ValueError("sohbet şablonu istem ön ekini korumuyor; maskeleme güvenilmez")

    prompt_ids = tokenizer(prompt_text, add_special_tokens=False)["input_ids"]
    full_ids = tokenizer(full_text, add_special_tokens=False)["input_ids"]
    if full_ids[: len(prompt_ids)] != prompt_ids:
        raise ValueError("istem token'ları tam metnin başında değil (birleşme sınırı kayması)")

    if len(full_ids) > max_length:
        raise TruncatedExampleError(
            f"örnek {len(full_ids)} token, bağlam {max_length}: asistan yanıtı kesilirdi"
        )

    # Şablonun sonuna eklediği satır sonu ("<|im_end|>\n") öğretilecek bir şey
    # değil; bitiş belirtecinden sonrasını maskele.
    end = len(full_ids)
    end_token = tokenizer.convert_tokens_to_ids("<|im_end|>")
    if end_token is not None and end_token in full_ids[len(prompt_ids):]:
        end = len(prompt_ids) + full_ids[len(prompt_ids):].index(end_token) + 1

    labels = [IGNORE_INDEX] * len(prompt_ids) + full_ids[len(prompt_ids):end]
    labels += [IGNORE_INDEX] * (len(full_ids) - len(labels))
    return Tokenized(input_ids=full_ids, labels=labels)


def load_jsonl(path: Path, limit: int | None = None) -> list[dict]:
    rows: list[dict] = []
    with Path(path).open(encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            if limit and i >= limit:
                break
            rows.append(json.loads(line))
    return rows


def tokenize_dataset(
    tokenizer: Any, rows: list[dict], max_length: int
) -> tuple[list[dict[str, list[int]]], dict[str, int]]:
    """Tüm örnekleri tokenlar; sığmayanları atar ve sayısını raporlar."""
    out: list[dict[str, list[int]]] = []
    dropped = 0
    supervised = 0
    for row in rows:
        try:
            t = tokenize_example(tokenizer, row["messages"], max_length)
        except TruncatedExampleError:
            dropped += 1
            continue
        out.append({"input_ids": t.input_ids, "labels": t.labels})
        supervised += t.n_supervised
    stats = {
        "kullanilan": len(out),
        "atilan_uzun": dropped,
        "denetlenen_token": supervised,
        "toplam_token": sum(len(x["input_ids"]) for x in out),
    }
    return out, stats


def pad_batch(batch: list[dict[str, list[int]]], pad_id: int) -> dict[str, list[list[int]]]:
    """Toplu işi en uzun örneğe sağdan doldurur (etiketler -100 ile)."""
    longest = max(len(x["input_ids"]) for x in batch)
    ids, labels, mask = [], [], []
    for x in batch:
        pad = longest - len(x["input_ids"])
        ids.append(x["input_ids"] + [pad_id] * pad)
        labels.append(x["labels"] + [IGNORE_INDEX] * pad)
        mask.append([1] * len(x["input_ids"]) + [0] * pad)
    return {"input_ids": ids, "labels": labels, "attention_mask": mask}
