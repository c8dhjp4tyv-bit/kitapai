"""Adaptörü taban modele birleştirme ve GGUF'a çevirme.

GGUF, modeli llama.cpp ile CPU'da ya da düşük VRAM'de çalıştırmak için gerekir;
servis tarafında `KITAPAI_ENGINE=openai` ile llama.cpp sunucusuna bağlanılır.
"""

from __future__ import annotations

from pathlib import Path

from ..logging import get

log = get("train.export")


def merge(adapter_dir: Path, base_model: str, out_dir: Path) -> Path:
    """LoRA ağırlıklarını taban modele işleyip 16-bit olarak kaydeder."""
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    log.info("taban model yükleniyor: %s", base_model)
    model = AutoModelForCausalLM.from_pretrained(
        base_model, dtype=torch.float16, device_map={"": "cpu"}
    )
    model = PeftModel.from_pretrained(model, str(adapter_dir))
    log.info("adaptör birleştiriliyor…")
    model = model.merge_and_unload()

    out_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(out_dir), safe_serialization=True)
    AutoTokenizer.from_pretrained(str(adapter_dir)).save_pretrained(str(out_dir))
    log.info("birleştirilmiş model: %s", out_dir)
    return out_dir


def to_gguf(merged_dir: Path, out_file: Path, *, quantization: str = "q4_k_m") -> Path:
    """llama.cpp'nin dönüştürücüsünü çağırır (kurulu olmalı)."""
    import shutil
    import subprocess

    converter = shutil.which("convert_hf_to_gguf.py") or shutil.which("convert-hf-to-gguf.py")
    if not converter:
        raise FileNotFoundError(
            "llama.cpp dönüştürücüsü bulunamadı. llama.cpp deposunu klonlayıp "
            "`convert_hf_to_gguf.py` dosyasını PATH'e ekleyin."
        )
    out_file.parent.mkdir(parents=True, exist_ok=True)
    cmd = [converter, str(merged_dir), "--outfile", str(out_file), "--outtype", quantization]
    log.info("GGUF dönüşümü: %s", " ".join(cmd))
    subprocess.run(cmd, check=True)
    return out_file
