"""Eğitimde kullanılan 4-bit tabanı LoRA'sız, AÇILMIŞ (dequantize) bf16 olarak kaydeder.
Çalışma zamanında LoRA'lar bunun üzerine uygulanacak (llama.cpp --lora)."""
import json, sys
from pathlib import Path
import bitsandbytes as bnb
import torch
from safetensors.torch import save_file
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

tok_src, out = Path(sys.argv[1]), Path(sys.argv[2])
base = "unsloth/Qwen2.5-3B-Instruct-bnb-4bit"
quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.bfloat16,
                           bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True)
model = AutoModelForCausalLM.from_pretrained(base, quantization_config=quant, device_map={"": 0})
state = {}
for name, mod in model.named_modules():
    if isinstance(mod, bnb.nn.Linear4bit):
        state[name + ".weight"] = bnb.functional.dequantize_4bit(
            mod.weight.data, mod.weight.quant_state).to(torch.bfloat16).cpu()
        if mod.bias is not None:
            state[name + ".bias"] = mod.bias.data.to(torch.bfloat16).cpu()
for name, p in model.named_parameters():
    if name not in state:
        state[name] = p.data.to(torch.bfloat16).cpu()
out.mkdir(parents=True, exist_ok=True)
save_file({k: v.contiguous() for k, v in state.items()}, str(out / "model.safetensors"), metadata={"format": "pt"})
c = model.config.to_dict(); c.pop("quantization_config", None); c["torch_dtype"] = "bfloat16"
(out / "config.json").write_text(json.dumps(c, indent=2))
AutoTokenizer.from_pretrained(tok_src).save_pretrained(out)
print("kaydedildi:", out, f"{sum(v.numel() for v in state.values())/1e9:.2f} milyar parametre")
