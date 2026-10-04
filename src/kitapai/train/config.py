"""Eğitim yapılandırması (YAML'dan okunur)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml


@dataclass
class TrainConfig:
    # Model
    base_model: str = "unsloth/Qwen2.5-3B-Instruct-bnb-4bit"
    max_seq_length: int = 2048
    load_in_4bit: bool = True

    # LoRA
    lora_r: int = 32
    lora_alpha: int = 32
    lora_dropout: float = 0.0
    target_modules: list[str] = field(default_factory=lambda: [
        "q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj",
    ])
    use_rslora: bool = True
    gradient_checkpointing: str = "unsloth"

    # Optimizasyon
    epochs: float = 2.0
    batch_size: int = 2
    grad_accum: int = 8
    learning_rate: float = 1e-4
    warmup_ratio: float = 0.03
    weight_decay: float = 0.01
    lr_scheduler: str = "cosine"
    optim: str = "adamw_bnb_8bit"
    seed: int = 20260918
    bf16: bool = True

    # Veri
    dataset_dir: str = "data/dataset"
    #: Eğitim dosyası. Damıtılmış gerekçelerle eğitmek için `distilled.jsonl`.
    train_file: str = "train.jsonl"
    valid_file: str = "valid.jsonl"
    output_dir: str = "models/kitapai-lora"
    eval_steps: int = 200
    save_steps: int = 400
    logging_steps: int = 20
    max_samples: int | None = None
    #: Eğitim sırasında değerlendirilecek örnek sayısı. 400 örnek 4.5 dakika
    #: sürüyordu (1.5 örnek/sn); gerçek kalite ölçümü zaten üretimle yapılan
    #: `kitapai eval`'dir, buradaki yalnızca kayıp eğrisi içindir.
    eval_samples: int = 100

    @classmethod
    def load(cls, path: str | Path | None) -> TrainConfig:
        if path is None:
            return cls()
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"{path}: bilinmeyen anahtar(lar): {sorted(unknown)}")
        return cls(**data)

    def as_dict(self) -> dict:
        return asdict(self)
