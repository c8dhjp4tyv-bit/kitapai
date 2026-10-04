"""Gerekçe damıtma — gerçek ağa çıkmadan, sahte Gemini sunucusuyla.

Bu testler API'nin gerçek davranışını DOĞRULAMAZ (anahtar olmadan mümkün değil);
istemcinin kendi mantığını doğrular: kalite kapıları, yeniden deneme, devam etme
ve anahtarın sızmaması.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from kitapai.data import http as http_mod
from kitapai.dataset import distill as dist

KEY = "TEST-ANAHTARI-GIZLI-123"

USER = (
    "İSTEK\nOkurun sözleri: karanlık bir distopya\nİstenen öneri sayısı: 2\n\n"
    "ADAYLAR\n"
    "[a1] Nineteen Eighty-Four — George Orwell · 1949\n     tür: Distopya | ruh: Karanlık\n"
    "     özet: A bleak vision of a surveillance state where language itself is a weapon.\n"
    "[a2] The Hobbit — J. R. R. Tolkien · 1937\n     tür: Fantastik\n"
    "[a3] Dune — Frank Herbert · 1965\n     tür: Bilim Kurgu\n\n"
    "Yanıtı yalnızca JSON olarak ver."
)
TARGET = {"picks": [
    {"id": "a1", "why": "ŞABLON", "hooks": ["x"], "content_notes": ["şiddet"], "confidence": 0.9},
    {"id": "a3", "why": "ŞABLON", "hooks": ["y"], "content_notes": [], "confidence": 0.6},
], "followups": []}


def make_sample() -> dict:
    return {"task": "grounded_recommend", "meta": {"style": "tur_ruh"}, "messages": [
        {"role": "system", "content": "s"},
        {"role": "user", "content": USER},
        {"role": "assistant", "content": json.dumps(TARGET, ensure_ascii=False)},
    ]}


GOOD = {"items": [
    {"id": "a1", "hooks": ["gözetim devleti", "karanlık ton"],
     "why": "Karanlık bir distopya aradığın için bu kitap tam yerinde: gözetim ve dilin "
            "silaha dönüştüğü bir dünyayı anlatıyor."},
    {"id": "a3", "hooks": ["çöl gezegeni"],
     "why": "Düşündürücü bir uzay hikâyesi arıyorsan bu klasik, siyaset ve ekoloji üzerine "
            "geniş soluklu bir okuma sunuyor."},
]}


def gemini_body(payload: dict) -> dict:
    text = json.dumps(payload, ensure_ascii=False)
    return {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 700, "candidatesTokenCount": 300,
                              "thoughtsTokenCount": 120}}


class FakeGemini(httpx.BaseTransport):
    def __init__(self, handler):
        self.handler, self.calls, self.seen_urls, self.seen_headers = handler, 0, [], []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        self.seen_urls.append(str(request.url))
        self.seen_headers.append(dict(request.headers))
        return self.handler(self.calls, request)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(http_mod.time, "sleep", lambda _s: None)


def client_for(handler) -> tuple[dist.GeminiClient, FakeGemini]:
    transport = FakeGemini(handler)
    return dist.GeminiClient(api_key=KEY, transport=transport), transport


def test_anahtar_yoksa_net_hata(monkeypatch):
    monkeypatch.delenv(dist.API_KEY_ENV, raising=False)
    with pytest.raises(dist.DistillError, match="GCLOUD_API_KEY"):
        dist.GeminiClient()


def test_istem_yalniz_secilen_kitaplari_iceriyor():
    prompt, ids = dist.build_user_prompt(make_sample())
    assert ids == ["a1", "a3"]
    assert "Nineteen Eighty-Four" in prompt and "Dune" in prompt
    assert "Hobbit" not in prompt          # seçilmeyen aday gönderilmez
    assert "karanlık bir distopya" in prompt


def test_basarili_damitma_yalniz_metni_degistiriyor():
    sample = make_sample()
    out = dist.apply_distilled(sample, GOOD["items"])
    new = json.loads(out["messages"][2]["content"])
    old = json.loads(sample["messages"][2]["content"])
    assert new["picks"][0]["why"].startswith("Karanlık bir distopya")
    # seçim, güven ve içerik uyarısı kural tabanlı kalır — LLM bunları değiştiremez
    assert [p["id"] for p in new["picks"]] == [p["id"] for p in old["picks"]]
    assert new["picks"][0]["confidence"] == 0.9
    assert new["picks"][0]["content_notes"] == ["şiddet"]
    assert out["meta"]["distilled"] is True
    assert old["picks"][0]["why"] == "ŞABLON"      # kaynak örnek değişmedi


def test_kimlik_uyusmazligi_reddediliyor():
    items = [{"id": "a1", "why": GOOD["items"][0]["why"], "hooks": []},
             {"id": "a9", "why": GOOD["items"][1]["why"], "hooks": []}]  # a9 uydurma
    probs = dist.validate_items(items, ["a1", "a3"], {})
    assert probs and "kimlikler uyuşmuyor" in probs[0]


@pytest.mark.parametrize("why,neden", [
    ("kısa", "uzunluğu"),
    ("x " * 200, "uzunluğu"),
    ("This is a bleak vision of the world and the author tells the story of the reader.", "Türkçe"),
    ("A bleak vision of a surveillance state where language itself is a weapon ok.", "kopyalama"),
])
def test_kalite_kapilari(why, neden):
    items = [{"id": "a1", "why": why, "hooks": []}]
    sources = {"a1": "özet: A bleak vision of a surveillance state where language "
                     "itself is a weapon."}
    assert any(neden in p for p in dist.validate_items(items, ["a1"], sources))


def test_cengel_cok_uzunsa_reddedilir():
    items = [{"id": "a1", "why": GOOD["items"][0]["why"], "hooks": ["bir iki üç dört beş altı"]}]
    assert any("çengel" in p for p in dist.validate_items(items, ["a1"], {}))


def test_thinking_parcalari_yok_sayiliyor():
    resp = {"candidates": [{"content": {"parts": [
        {"text": "iç düşünce, JSON değil", "thought": True},
        {"text": json.dumps(GOOD, ensure_ascii=False)}]}}]}
    assert dist.extract_json(resp)["items"][0]["id"] == "a1"


def test_kod_blogu_sarmasi_soyuluyor():
    resp = {"candidates": [{"content": {"parts": [
        {"text": "```json\n" + json.dumps(GOOD, ensure_ascii=False) + "\n```"}]}}]}
    assert dist.extract_json(resp)["items"][0]["id"] == "a1"


def test_bos_yanit_anlamli_hata_veriyor():
    with pytest.raises(dist.DistillError, match="finishReason=SAFETY"):
        dist.extract_json({"candidates": [{"finishReason": "SAFETY"}]})


def test_429da_yeniden_deniyor_ve_kullanimi_sayiyor():
    def handler(n, _req):
        if n <= 2:
            return httpx.Response(429, json={"error": {"message": "kota"}})
        return httpx.Response(200, json=gemini_body(GOOD))

    client, transport = client_for(handler)
    resp = client.generate("s", "u")
    assert resp["candidates"]
    assert transport.calls == 3
    u = client.usage.as_dict()
    assert u["prompt_tokens"] == 700 and u["thought_tokens"] == 120


def test_yanlis_uc_nokta_sonrakine_dusuyor_ve_hatirliyor():
    def handler(n, req):
        if "/projects/" in str(req.url):
            return httpx.Response(404, json={"error": {"message": "yok"}})
        return httpx.Response(200, json=gemini_body(GOOD))

    client, transport = client_for(handler)
    client.generate("s", "u")
    first_calls = transport.calls
    client.generate("s", "u")
    assert transport.calls == first_calls + 1      # ikinci istek doğrudan çalışan uca gitti


def test_anahtar_url_de_degil_baslikta():
    client, transport = client_for(lambda n, r: httpx.Response(200, json=gemini_body(GOOD)))
    client.generate("s", "u")
    assert all(KEY not in url for url in transport.seen_urls)
    assert transport.seen_headers[0]["x-goog-api-key"] == KEY


def test_dosya_damitma_ve_devam_etme(tmp_path: Path):
    src = tmp_path / "train.jsonl"
    src.write_text("\n".join(json.dumps(make_sample(), ensure_ascii=False) for _ in range(4)),
                   encoding="utf-8")
    out = tmp_path / "distilled.jsonl"
    client, transport = client_for(lambda n, r: httpx.Response(200, json=gemini_body(GOOD)))

    r1 = dist.distill_file(client, src, out, limit=2, workers=2)
    assert r1.accepted == 2 and r1.rejected == 0
    assert transport.calls == 2

    r2 = dist.distill_file(client, src, out, limit=4, workers=2)     # devam
    assert r2.skipped_done == 2 and r2.accepted == 2
    assert transport.calls == 4                                       # eskiler yeniden istenmedi
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert sorted(r["meta"]["source_index"] for r in rows) == [0, 1, 2, 3]
    assert KEY not in out.read_text(encoding="utf-8")                 # anahtar çıktıya sızmaz


def test_gecersiz_yanit_reddedilir_ve_sayilir(tmp_path: Path):
    src = tmp_path / "train.jsonl"
    src.write_text(json.dumps(make_sample(), ensure_ascii=False), encoding="utf-8")
    bad = {"items": [{"id": "a1", "why": "kısa", "hooks": []}]}
    client, _ = client_for(lambda n, r: httpx.Response(200, json=gemini_body(bad)))
    rep = dist.distill_file(client, src, tmp_path / "o.jsonl", workers=1)
    assert rep.accepted == 0 and rep.rejected == 1
    assert (tmp_path / "o.jsonl").read_text(encoding="utf-8") == ""   # kötü çıktı yazılmaz


def test_dusunme_ayari_istege_ekleniyor_ve_kapatilabiliyor():
    """Varsayılan düşünme maliyeti görünen çıktının ~4 katıydı; ayar gönderilmeli."""
    seen: list[dict] = []

    def handler(_n, req):
        seen.append(json.loads(req.content))
        return httpx.Response(200, json=gemini_body(GOOD))

    client, _ = client_for(handler)
    client.generate("s", "u")
    assert seen[0]["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "low"}

    off = dist.GeminiClient(api_key=KEY, thinking=None, transport=FakeGemini(handler))
    off.generate("s", "u")
    assert "thinkingConfig" not in seen[1]["generationConfig"]


def test_uyum_bilgisi_istemde_gonderiliyor():
    """Kural tabanlı uyum Gemini'ye gider: zayıf eşleşmeyi parlatmasın, eksiği söylesin."""
    prompt, _ = dist.build_user_prompt(make_sample())
    assert "uyum: güçlü" in prompt      # a1, güven 0.9
    assert "uyum: orta" in prompt       # a3, güven 0.6
    assert dist.match_strength(0.2) == "zayıf"
    assert dist.match_strength(None) == "orta"


def test_sistem_talimati_dürüstlük_ve_sen_hitabini_istiyor():
    s = dist.SYSTEM_INSTRUCTION
    assert "DÜRÜST" in s and "zayıf" in s and "sen" in s
    assert "uydurma" in s


@pytest.mark.parametrize("metin,resmi", [
    ("Aradığınız derin hüznü güçlü biçimde hissettiriyor.", True),
    ("Bu kitap ilginizi çekecektir, denemenizi öneririm.", True),
    ("Distopya arıyorsanız bu tam yerinde bir seçim olabilir.", True),
    ("Aradığın karanlık tonu burada bulacaksın.", False),
    ("Denemeni öneririm, gözetim temasını seveceksin.", False),
])
def test_resmi_hitap_reddediliyor(metin, resmi):
    items = [{"id": "a1", "why": metin, "hooks": []}]
    problems = dist.validate_items(items, ["a1"], {})
    assert any("resmi hitap" in p for p in problems) is resmi
