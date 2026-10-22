import json

import httpx
import pytest

from kitapai.config import Settings
from kitapai.serve.engine import LlamaServerEngine, chatml, create_engine


def make(handler=None):
    seen: list[dict] = []

    def default(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"content": '{"ids":["a1"]}'})

    transport = httpx.MockTransport(handler or default)
    return LlamaServerEngine("http://ps5:8081/", {"select": 0, "write": 1},
                             transport=transport), seen


MESSAGES = [{"role": "system", "content": "sistem"}, {"role": "user", "content": "istek"}]


def test_chatml_matches_qwen_template_shape():
    assert chatml(MESSAGES) == (
        "<|im_start|>system\nsistem<|im_end|>\n<|im_start|>user\nistek<|im_end|>\n"
        "<|im_start|>assistant\n")


def test_selects_adapter_with_integer_scales_only():
    engine, seen = make()
    out = engine.generate(MESSAGES, adapter="select", max_new_tokens=60, temperature=0.0)
    assert out == '{"ids":["a1"]}'
    engine.generate(MESSAGES, adapter="write", max_new_tokens=300, temperature=0.3)
    select, write = seen
    assert select["lora"] == [{"id": 0, "scale": 1}, {"id": 1, "scale": 0}]
    assert write["lora"] == [{"id": 0, "scale": 0}, {"id": 1, "scale": 1}]
    assert select["top_k"] == 1 and "top_k" not in write    # yazıcı: sunucunun --temp'i
    assert select["n_predict"] == 60 and write["n_predict"] == 300
    for body in seen:                                        # JSON'da hiç ondalık sayı yok
        assert not [v for k, v in body.items() if isinstance(v, float)]
        assert "temperature" not in body


def test_no_adapter_turns_all_loras_off():
    engine, seen = make()
    engine.generate(MESSAGES)
    assert seen[0]["lora"] == [{"id": 0, "scale": 0}, {"id": 1, "scale": 0}]


def test_unknown_adapter_and_floats_are_rejected():
    engine, _ = make()
    with pytest.raises(ValueError, match="bilinmeyen adaptör"):
        engine.generate(MESSAGES, adapter="yok")
    with pytest.raises(ValueError, match="ondalık"):
        LlamaServerEngine._no_floats({"lora": [{"id": 0, "scale": 5.6569}]})


def test_http_error_propagates():
    engine, _ = make(lambda r: httpx.Response(503))
    with pytest.raises(httpx.HTTPStatusError):
        engine.generate(MESSAGES, adapter="select")


def test_create_engine_llama_and_requires_url():
    engine = create_engine(Settings(engine="llama", llama_url="http://x:1",
                                    llama_adapters="select:2,write:3"))
    assert isinstance(engine, LlamaServerEngine) and engine.adapters == {"select": 2, "write": 3}
    with pytest.raises(ValueError):
        create_engine(Settings(engine="llama"))
