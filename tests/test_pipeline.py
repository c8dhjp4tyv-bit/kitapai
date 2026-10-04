"""İki aşamalı hat: SEÇ → zayıfları ele → YAZ, her aşamanın yedek yoluyla."""

from __future__ import annotations

import json

import pytest

from kitapai.config import Settings
from kitapai.retrieval.hybrid import Retriever
from kitapai.schemas import RecommendRequest
from kitapai.serve.decode import decode_select, decode_write
from kitapai.serve.engine import StubEngine
from kitapai.serve.pipeline import RecommendPipeline


class SpyEngine(StubEngine):
    """Çağrıları kaydeder; SEÇ/YAZ çıktısını dışarıdan ayarlanabilir kılar."""

    name = "spy"

    def __init__(self, select=None, write=None):
        self.calls: list[tuple[str, dict]] = []
        self._select, self._write = select, write

    def generate(self, messages, **kwargs):
        system = messages[0]["content"]
        stage = "write" if "gerekçe yazarı" in system else "select"
        self.calls.append((stage, kwargs))
        override = self._write if stage == "write" else self._select
        if override is not None:
            return override(messages) if callable(override) else override
        return super().generate(messages, **kwargs)


def make_pipeline(catalog_con, engine, **settings) -> RecommendPipeline:
    cfg = Settings(engine="stub", candidate_pool=20, **settings)
    return RecommendPipeline(Retriever(catalog_con), engine, cfg)


# ── ayrıştırıcılar ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw,expected", [
    ('{"ids":["a3","a1"]}', ["a3", "a1"]),
    ('```json\n{"ids":["a2"]}\n```', ["a2"]),
    ('önsöz {"ids":["a1","a1","a2"]} son', ["a1", "a2"]),          # tekrar atılır, sıra korunur
    ('{"ids":["a1","a2"', ["a1", "a2"]),                            # kesik çıktı onarılır
    ('{"ids":[]}', []),
])
def test_secici_cikti_ayristirma(raw, expected):
    ids, err = decode_select(raw)
    assert err is None and ids == expected


@pytest.mark.parametrize("raw", ["", "json yok", '{"picks":[]}', '{"ids":"a1"}'])
def test_secici_gecersiz_cikti_hata_veriyor(raw):
    ids, err = decode_select(raw)
    assert ids is None and err


def test_yazici_cikti_ayristirma():
    raw = "a1:   Tam senlik.  \n\n- **a2**: Olur.\nçöp satır\na1: ikinci kez\nA3 yok"
    items, err = decode_write(raw)
    assert err is None
    assert items == {"a1": {"why": "Tam senlik.", "hooks": []},        # ilki geçerli
                     "a2": {"why": "Olur.", "hooks": []}}              # çengeli model yazmaz
    assert decode_write("")[1] and decode_write('{"ids":[]}')[1]


# ── aşama dosyaları ─────────────────────────────────────────────────────────


def test_secim_ornegi_yalniz_kimlik_iceriyor(dataset_dir):
    from kitapai.dataset.stages import select_sample
    from kitapai.prompting import SELECT_SYSTEM_PROMPT

    row = json.loads((dataset_dir / "train.jsonl").read_text(encoding="utf-8").splitlines()[0])
    s = select_sample(row)
    target = json.loads(s["messages"][2]["content"])
    assert set(target) == {"ids"}                                     # gerekçe/güven yok
    assert target["ids"] == [p["id"] for p in json.loads(row["messages"][2]["content"])["picks"]]
    assert s["messages"][0]["content"] == SELECT_SYSTEM_PROMPT
    assert s["messages"][1]["content"] == row["messages"][1]["content"]   # istem aynen


def test_yazim_ornegi_servis_istemiyle_ayni_bicimde():
    """Eğitimdeki YAZ istemi ile serviste yazıcıya giden istem aynı olmalı."""
    from kitapai.dataset.distill import apply_distilled
    from kitapai.dataset.stages import write_sample
    from kitapai.prompting import WRITE_SYSTEM_PROMPT, build_write_user_message
    from test_distill import GOOD, make_sample

    row = apply_distilled(make_sample(), GOOD["items"])
    w = write_sample(row)
    assert w["messages"][0]["content"] == WRITE_SYSTEM_PROMPT
    user = w["messages"][1]["content"]
    assert user.startswith("OKURUN İSTEĞİ") and "SEÇİLEN KİTAPLAR" in user
    assert "uyum: güçlü" in user and "uyum: orta" in user
    assert "Hobbit" not in user                                         # seçilmeyen aday yok
    request_block = user.split("\n\nSEÇİLEN KİTAPLAR")[0].removeprefix("OKURUN İSTEĞİ\n")
    assert build_write_user_message(request_block, [("[a1] x", "güçlü")]).startswith(
        "OKURUN İSTEĞİ\n" + request_block)
    items, err = decode_write(w["messages"][2]["content"])
    assert err is None and list(items) == ["a1", "a3"] and items["a1"]["why"].startswith("Karanlık")


# ── hat ─────────────────────────────────────────────────────────────────────


async def test_mutlu_yol_iki_asama_dogru_adaptorle_cagriliyor(catalog_con):
    spy = SpyEngine()
    result = await make_pipeline(catalog_con, spy).recommend(
        RecommendRequest(query="karanlık ve düşündürücü bir distopya", limit=2))
    resp = result.response
    assert [c[0] for c in spy.calls] == ["select", "write"]
    assert spy.calls[0][1]["adapter"] == "select" and spy.calls[0][1]["temperature"] == 0.0
    assert spy.calls[1][1]["adapter"] == "write"
    assert resp.recommendations and not resp.meta.degraded
    assert all(r.why.endswith("isteğine yakın bir seçim.") for r in resp.recommendations)
    # güven kural tabanlı (modelden değil) ve her öneri için anlamlı
    assert all(0.0 <= r.confidence <= 1.0 for r in resp.recommendations)
    assert resp.recommendations[0].book.work_key.startswith("/works/")


async def test_secici_cokerse_geri_getirme_siralamasina_dusuyor(catalog_con):
    spy = SpyEngine(select="çöp çıktı, json değil")
    result = await make_pipeline(catalog_con, spy).recommend(
        RecommendRequest(query="distopya", limit=2))
    resp = result.response
    assert resp.meta.degraded and resp.recommendations
    assert any("yedek sıralama" in n for n in resp.meta.notes)
    assert result.errors and "seçici" in result.errors[0]


async def test_yazici_cokerse_sablon_gerekce_kullaniliyor(catalog_con):
    spy = SpyEngine(write="bozuk")
    result = await make_pipeline(catalog_con, spy).recommend(
        RecommendRequest(query="distopya", limit=2))
    resp = result.response
    assert resp.meta.degraded
    assert all(r.why.strip() for r in resp.recommendations)             # boş gerekçe yok
    assert any("şablon" in n for n in resp.meta.notes)


async def test_bilinmeyen_kimlik_yok_sayiliyor(catalog_con):
    spy = SpyEngine(select='{"ids":["a99","a1"]}')
    resp = (await make_pipeline(catalog_con, spy).recommend(
        RecommendRequest(query="distopya", limit=3))).response
    assert len(resp.recommendations) == 1
    assert any("bilinmeyen aday kimliği" in n for n in resp.meta.notes)


async def test_zayif_eslesmeler_elenir_ama_en_az_biri_kalir(catalog_con):
    """Hedef (tür) varken uyumu zayıf seçimler gösterilmez; boş liste de dönmez."""
    spy = SpyEngine(select=json.dumps({"ids": [f"a{i}" for i in range(1, 9)]}))
    # Boş sorgu + tür: gezinme modu, fixture'daki tüm kitaplar aday; yalnızca klasikler
    # hedefe uyar, diğerlerinin puanı düşük kalır.
    req = RecommendRequest(query="", genres=["klasik"], limit=8)
    resp = (await make_pipeline(catalog_con, spy, min_confidence=0.7).recommend(req)).response
    assert 1 <= len(resp.recommendations) < 8
    assert any("zayıf eşleşme elendi" in n for n in resp.meta.notes)
    assert resp.followups                                               # "gevşetmemi ister misin"

    # eşik imkânsızsa bile en az bir öneri kalır
    resp2 = (await make_pipeline(catalog_con, spy, min_confidence=2.0).recommend(req)).response
    assert len(resp2.recommendations) == 1


async def test_hedefsiz_istekte_zayif_filtresi_uygulanmaz(catalog_con):
    """Kısıtsız isteklerde puan bilinirliğe dayanır; eşik anlamsızdır, kimse elenmez."""
    spy = SpyEngine(select='{"ids":["a1","a2","a3"]}')
    resp = (await make_pipeline(catalog_con, spy, min_confidence=0.99).recommend(
        RecommendRequest(query="zzzz qqqq", limit=3))).response
    assert len(resp.recommendations) == 3
    assert not any("elendi" in n for n in resp.meta.notes)


async def test_yazici_yalniz_secilenleri_goruyor(catalog_con):
    seen: list[str] = []

    def capture(messages):
        seen.append(messages[1]["content"])
        return ""

    spy = SpyEngine(select='{"ids":["a2"]}', write=capture)
    await make_pipeline(catalog_con, spy).recommend(
        RecommendRequest(query="", genres=["klasik"], limit=3))     # çok aday: a2 mevcut
    assert seen and seen[0].count("[a") == 1 and "[a2]" in seen[0]      # tek kitap
    assert "uyum:" in seen[0]
