"""Model çalıştırma soyutlaması.

Üç motor:
  • `transformers` — yerel 4-bit taban model + LoRA adaptörü (CUDA)
  • `openai`       — llama.cpp / vLLM gibi OpenAI-uyumlu bir sunucuya proxy
  • `stub`         — modelsiz, deterministik; testler ve GPU'suz geliştirme için

Ağır kütüphaneler (torch, transformers, peft) yalnızca `transformers` motoru
seçildiğinde yüklenir. Böylece veri hattı ve testler GPU'suz bir makinede
çalışabilir.
"""

from __future__ import annotations

import json
import re
import threading
import time
from abc import ABC, abstractmethod
from pathlib import Path

from ..logging import get
from ..prompting import format_write_target

log = get("serve.engine")


class Engine(ABC):
    """Sohbet mesajlarından metin üreten en küçük arayüz."""

    name: str = "base"
    model_id: str = "bilinmiyor"

    @abstractmethod
    def generate(self, messages: list[dict[str, str]], **kwargs) -> str: ...

    def generate_batch(self, batch: list[list[dict[str, str]]], **kwargs) -> list[str]:
        """Birden çok istemi üretir. Varsayılan sırayla; GPU motoru gerçek toplu üretir."""
        kwargs.pop("batch_size", None)
        return [self.generate(messages, **kwargs) for messages in batch]

    @property
    def device(self) -> str:
        return "cpu"

    def warmup(self) -> None:  # noqa: B027 - bilinçli olarak isteğe bağlı
        """İsteğe bağlı ısınma — ilk isteğin gecikmesini düşürür.

        Varsayılan olarak hiçbir şey yapmaz; yalnızca ağır motorlar uygular.
        """


class StubEngine(Engine):
    """Modelsiz motor: SEÇ'te ilk `limit` adayı seçer, YAZ'da şablon bir gerekçe yazar.

    Gerçek bir öneri kalitesi sunmaz; amacı servis boru hattının, şemaların ve
    istemcilerin model olmadan uçtan uca çalıştırılabilmesidir.
    """

    name = "stub"
    model_id = "stub"

    _ID = re.compile(r"^\[(a\d+)\]\s*(.+?)(?:\s+—|\s+·|$)", re.MULTILINE)
    _LIMIT = re.compile(r"İstenen öneri sayısı:\s*(\d+)")

    def generate(self, messages: list[dict[str, str]], **kwargs) -> str:
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        found = self._ID.findall(user)

        if "gerekçe yazarı" in system:           # YAZ
            return format_write_target(
                [(cid, f"{title.strip()} isteğine yakın bir seçim.") for cid, title in found])

        limit_match = self._LIMIT.search(user)    # SEÇ
        limit = int(limit_match.group(1)) if limit_match else 3
        return json.dumps({"ids": [cid for cid, _ in found[:limit]]}, ensure_ascii=False)


class OpenAICompatEngine(Engine):
    """OpenAI uyumlu `/chat/completions` uç noktasına proxy.

    llama.cpp `--server`, vLLM, TGI ve benzerleri bu arayüzü konuşur; modeli
    GGUF olarak çalıştırmak istediğinde (CPU'da bile) bu motor kullanılır.
    """

    name = "openai"

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "yok",
        *,
        timeout: float = 120.0,
    ) -> None:
        import httpx

        self.model_id = model
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    def generate(self, messages: list[dict[str, str]], **kwargs) -> str:
        payload = {
            "model": self.model_id,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.6),
            "top_p": kwargs.get("top_p", 0.9),
            "max_tokens": kwargs.get("max_new_tokens", 700),
            # Destekleyen sunucularda JSON'u zorlar; desteklemeyenler yok sayar.
            "response_format": {"type": "json_object"},
        }
        resp = self._client.post(f"{self.base_url}/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


class TransformersEngine(Engine):
    """Yerel 4-bit taban model + LoRA adaptörü."""

    name = "transformers"

    def __init__(
        self,
        base_model: str,
        adapter_path: Path | None = None,
        *,
        adapters: dict[str, Path] | None = None,
        load_in_4bit: bool = True,
        max_new_tokens: int = 700,
        temperature: float = 0.6,
        top_p: float = 0.9,
    ) -> None:
        import torch  # ağır import — yalnızca bu motor seçilince

        self.model_id = base_model
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature
        self.top_p = top_p
        self._lock = threading.Lock()
        self._torch = torch
        self._device = "cuda" if torch.cuda.is_available() else "cpu"

        started = time.perf_counter()
        self._load(base_model, adapter_path, adapters or {}, load_in_4bit)
        log.info("model yüklendi: %s (%s, %.1fs)",
                 base_model, self._device, time.perf_counter() - started)

    def _load(
        self,
        base_model: str,
        adapter_path: Path | None,
        adapters: dict[str, Path],
        load_in_4bit: bool,
    ) -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        # Tokenizer: ilk geçerli adaptörün dizininden (sohbet şablonu orada kayıtlı).
        first = next((Path(p) for p in adapters.values() if Path(p).is_dir()), None)
        if first is None and adapter_path is not None and Path(adapter_path).is_dir():
            first = Path(adapter_path)
        self.tokenizer = AutoTokenizer.from_pretrained(
            str(first) if first else base_model, trust_remote_code=True)
        # Toplu üretimde kısa istemler SOLDAN doldurulmalı; aksi hâlde üretim, boşluk
        # token'larının ardından başlar ve çıktı bozulur.
        self.tokenizer.padding_side = "left"
        if self.tokenizer.pad_token_id is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token

        kwargs: dict = {"trust_remote_code": True}
        if self._device == "cuda" and load_in_4bit:
            from transformers import BitsAndBytesConfig

            kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True,
            )
            kwargs["device_map"] = {"": 0}
        elif self._device == "cuda":
            kwargs["dtype"] = torch.float16
            kwargs["device_map"] = {"": 0}
        else:
            # CPU'da 4-bit yüklenemez. 7B bir modeli float32 ile CPU'ya almak
            # ~28 GB RAM ister; bu yüzden uyarıp devam ediyoruz — kullanıcı
            # küçük bir model seçtiyse çalışır, seçmediyse net hata alır.
            log.warning(
                "CUDA yok: model CPU'da çalışacak, üretim çok yavaş olacak"
            )
            kwargs["dtype"] = torch.float32
            kwargs["device_map"] = {"": "cpu"}

        model = AutoModelForCausalLM.from_pretrained(base_model, **kwargs)

        self.adapters: list[str] = []
        valid = {n: Path(p) for n, p in adapters.items() if Path(p).is_dir()}
        for name, path in adapters.items():
            if name not in valid:
                log.warning("adaptör bulunamadı (%s: %s)", name, path)
        if valid:
            from peft import PeftModel

            # Tek taban, birden çok LoRA: SEÇ ve YAZ görevleri ayrı adaptörlerde.
            # Taban belleğe bir kez yüklenir; adaptör değişimi `set_adapter` ile.
            names = list(valid)
            model = PeftModel.from_pretrained(model, str(valid[names[0]]), adapter_name=names[0])
            for name in names[1:]:
                model.load_adapter(str(valid[name]), adapter_name=name)
            self.adapters = names
            log.info("LoRA adaptörleri bağlandı: %s", ", ".join(names))
        elif adapter_path and Path(adapter_path).is_dir():
            from peft import PeftModel

            model = PeftModel.from_pretrained(model, str(adapter_path))
            log.info("LoRA adaptörü bağlandı: %s", adapter_path)
        else:
            log.warning("adaptör bulunamadı — taban model kullanılıyor")

        model.eval()
        self.model = model

    @property
    def device(self) -> str:
        return self._device

    def warmup(self) -> None:
        try:
            self.generate(
                [{"role": "user", "content": "merhaba"}], max_new_tokens=4, temperature=0.0
            )
        except Exception as exc:  # pragma: no cover - ısınma hatası ölümcül değil
            log.warning("ısınma başarısız: %s", exc)

    def _generate_texts(self, texts: list[str], kwargs: dict) -> list[str]:
        torch = self._torch
        inputs = self.tokenizer(texts, return_tensors="pt", padding=True).to(self.model.device)
        temperature = kwargs.get("temperature", self.temperature)
        adapter = kwargs.get("adapter")

        # Tek GPU'da eşzamanlı generate çağrıları belleği patlatır; kilit üretimi
        # sıraya sokar (kuyruk sınırı `pipeline` tarafında). Adaptör değişimi de
        # kilit içinde: iki istek birbirinin adaptörünü ezmesin.
        with self._lock, torch.no_grad():
            if adapter and adapter in self.adapters:
                self.model.set_adapter(adapter)
            output = self.model.generate(
                **inputs,
                max_new_tokens=kwargs.get("max_new_tokens", self.max_new_tokens),
                do_sample=temperature > 0,
                temperature=temperature if temperature > 0 else None,
                top_p=kwargs.get("top_p", self.top_p) if temperature > 0 else None,
                pad_token_id=self.tokenizer.pad_token_id,
                eos_token_id=self.tokenizer.eos_token_id,
            )
        width = inputs["input_ids"].shape[1]
        return [
            self.tokenizer.decode(row[width:], skip_special_tokens=True) for row in output
        ]

    def generate(self, messages: list[dict[str, str]], **kwargs) -> str:
        text = self.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True)
        return self._generate_texts([text], kwargs)[0]

    def generate_batch(self, batch: list[list[dict[str, str]]], **kwargs) -> list[str]:
        """Gerçek toplu üretim (sol dolgu). Değerlendirmeyi örnek başına ~20 sn'den
        ~3 sn'ye indirir; VRAM'e göre `batch_size` ayarlanmalıdır."""
        texts = [
            self.tokenizer.apply_chat_template(m, tokenize=False, add_generation_prompt=True)
            for m in batch
        ]
        size = max(1, int(kwargs.pop("batch_size", 8)))
        out: list[str] = []
        for i in range(0, len(texts), size):
            out.extend(self._generate_texts(texts[i:i + size], kwargs))
        return out


def create_engine(settings, *, legacy: bool = False) -> Engine:
    """Ayarlara göre motoru kurar; yerel model yüklenemezse stub'a düşer."""
    name = settings.engine
    if name == "stub":
        return StubEngine()
    if name == "openai":
        return OpenAICompatEngine(
            settings.openai_base_url, settings.openai_model, settings.openai_api_key
        )
    try:
        return TransformersEngine(
            settings.base_model,
            settings.adapter_dir,
            # legacy: yalnızca eski tek-model adaptörü (v1-v3'ü yeniden ölçmek için).
            adapters={} if legacy else {
                "select": settings.select_adapter_dir, "write": settings.write_adapter_dir},
            load_in_4bit=settings.load_in_4bit,
            max_new_tokens=settings.max_new_tokens,
            temperature=settings.temperature,
            top_p=settings.top_p,
        )
    except Exception as exc:
        log.error("yerel model yüklenemedi (%s) — stub motoruna düşülüyor", exc)
        return StubEngine()
