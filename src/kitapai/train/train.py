"""QLoRA ince ayarı.

Unsloth varsa onu kullanır (8 GB VRAM'de 3B modeli 3072 token bağlamla eğitmeyi
mümkün kılan bellek optimizasyonları için); yoksa peft + bitsandbytes ile devam
eder.

Eğitim döngüsü TRL'nin `SFTTrainer`'ına DEĞİL, düz `transformers.Trainer`'a
dayanır. TRL'nin tamamlama-maskeleme API'si sürümler arasında kırıldı
(`DataCollatorForCompletionOnlyLM` 0.24'te kaldırıldı); etiket maskeleme bu
yüzden `train/data.py`'de, sürümden bağımsız ve testli olarak yapılır.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from ..logging import get
from ..prompting import PROMPT_VERSION, SYSTEM_PROMPT
from . import data as td
from .config import TrainConfig

log = get("train")

#: Bağlama sığmadığı için atılan örnek oranı bunu aşarsa eğitim başlamaz.
#: Atılanlar rastgele değil en uzun örneklerdir; oran yüksekse dağılım kayar.
MAX_DROPPED_RATIO = 0.02


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _load_model(config: TrainConfig):
    """(model, tokenizer, backend) döndürür."""
    try:
        from unsloth import FastLanguageModel

        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=config.base_model,
            max_seq_length=config.max_seq_length,
            load_in_4bit=config.load_in_4bit,
            dtype=None,
        )
        model = FastLanguageModel.get_peft_model(
            model,
            r=config.lora_r,
            lora_alpha=config.lora_alpha,
            lora_dropout=config.lora_dropout,
            target_modules=config.target_modules,
            use_rslora=config.use_rslora,
            use_gradient_checkpointing=config.gradient_checkpointing,
            random_state=config.seed,
        )
        return model, tokenizer, "unsloth"
    except ImportError:
        log.warning("unsloth yok — peft + bitsandbytes ile devam ediliyor "
                    "(8 GB VRAM'de sınırda kalabilir)")

    import torch
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    dtype = torch.bfloat16 if config.bf16 else torch.float16
    quant = BitsAndBytesConfig(
        load_in_4bit=config.load_in_4bit,
        bnb_4bit_compute_dtype=dtype,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
    )
    tokenizer = AutoTokenizer.from_pretrained(config.base_model)
    model = AutoModelForCausalLM.from_pretrained(
        config.base_model, quantization_config=quant, device_map={"": 0},
    )
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    model = get_peft_model(model, LoraConfig(
        r=config.lora_r, lora_alpha=config.lora_alpha,
        lora_dropout=config.lora_dropout, target_modules=config.target_modules,
        use_rslora=config.use_rslora, bias="none", task_type="CAUSAL_LM",
    ))
    return model, tokenizer, "peft"


def train(config: TrainConfig, *, resume: bool = False, max_steps: int | None = None) -> dict:
    """Eğitimi çalıştırır ve adaptörü `config.output_dir` altına yazar.

    `max_steps` verilirse kısa bir duman testi yapılır (örn. 20 adım): bellek,
    hız ve kaybın düştüğü eğitime saatler harcamadan görülür.
    """
    started = time.perf_counter()
    dataset_dir = Path(config.dataset_dir)
    train_path, valid_path = dataset_dir / config.train_file, dataset_dir / config.valid_file
    if not train_path.exists():
        raise FileNotFoundError(
            f"eğitim verisi yok: {train_path}\nÖnce üretin:  kitapai dataset build"
        )

    model, tokenizer, backend = _load_model(config)
    log.info("model hazır (%s): %s", backend, config.base_model)

    # ── veri: tokenizasyon + etiket maskeleme ──────────────────────────────
    train_rows = td.load_jsonl(train_path, config.max_samples)
    valid_rows = td.load_jsonl(valid_path, config.eval_samples) if valid_path.exists() else []
    train_ds, train_stats = td.tokenize_dataset(tokenizer, train_rows, config.max_seq_length)
    valid_ds, valid_stats = td.tokenize_dataset(tokenizer, valid_rows, config.max_seq_length)

    dropped_ratio = train_stats["atilan_uzun"] / max(1, len(train_rows))
    log.info("eğitim: %s örnek (%s atıldı, %.1f%%) · %s denetlenen / %s toplam token",
             f"{train_stats['kullanilan']:,}", train_stats["atilan_uzun"],
             100 * dropped_ratio, f"{train_stats['denetlenen_token']:,}",
             f"{train_stats['toplam_token']:,}")
    if dropped_ratio > MAX_DROPPED_RATIO:
        raise ValueError(
            f"örneklerin %{100 * dropped_ratio:.1f}'i max_seq_length={config.max_seq_length}'e "
            f"sığmıyor. Bağlamı yükseltin ya da `prompting.PROMPT_CANDIDATES` / "
            f"`DESCRIPTION_CHARS` değerlerini düşürün."
        )
    if not train_ds:
        raise ValueError("tokenizasyondan sonra eğitim örneği kalmadı")

    # ── eğitici ────────────────────────────────────────────────────────────
    import torch
    from transformers import Trainer, TrainingArguments

    pad_id = tokenizer.pad_token_id
    if pad_id is None:
        pad_id = tokenizer.eos_token_id

    def collate(batch: list[dict]) -> dict:
        padded = td.pad_batch(batch, pad_id)
        return {k: torch.tensor(v) for k, v in padded.items()}

    args = TrainingArguments(
        output_dir=str(Path(config.output_dir) / "checkpoints"),
        per_device_train_batch_size=config.batch_size,
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=config.grad_accum,
        num_train_epochs=config.epochs,
        max_steps=max_steps if max_steps else -1,
        learning_rate=config.learning_rate,
        warmup_ratio=config.warmup_ratio,
        weight_decay=config.weight_decay,
        lr_scheduler_type=config.lr_scheduler,
        optim=config.optim,
        logging_steps=config.logging_steps,
        save_steps=config.save_steps,
        save_total_limit=2,  # disk dar: yalnızca son iki kontrol noktası
        eval_steps=config.eval_steps if valid_ds else None,
        eval_strategy="steps" if valid_ds else "no",
        seed=config.seed,
        bf16=config.bf16,
        fp16=not config.bf16,
        gradient_checkpointing=(backend == "peft"),  # unsloth kendi yöntemini kullanır
        remove_unused_columns=False,
        dataloader_num_workers=0,
        report_to=[],
    )
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=train_ds,
        eval_dataset=valid_ds or None,
        data_collator=collate,
    )

    result = trainer.train(resume_from_checkpoint=resume or None)
    peak_gb = torch.cuda.max_memory_allocated() / 2**30 if torch.cuda.is_available() else 0.0

    # ── kaydet ─────────────────────────────────────────────────────────────
    out = Path(config.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(out))
    tokenizer.save_pretrained(str(out))

    meta = {
        "prompt_version": PROMPT_VERSION,
        "base_model": config.base_model,
        "backend": backend,
        "config": config.as_dict(),
        "max_steps": max_steps,
        "train_samples": train_stats["kullanilan"],
        "dropped_samples": train_stats["atilan_uzun"],
        "valid_samples": valid_stats["kullanilan"],
        "supervised_tokens": train_stats["denetlenen_token"],
        "train_loss": float(result.training_loss) if result else None,
        "peak_vram_gb": round(peak_gb, 2),
        "seconds": round(time.perf_counter() - started, 1),
        "system_prompt_sha": _sha(SYSTEM_PROMPT),
    }
    (out / "kitapai_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log.info("adaptör kaydedildi: %s (%.1f dk, tepe VRAM %.1f GB)",
             out, meta["seconds"] / 60, peak_gb)
    return meta
