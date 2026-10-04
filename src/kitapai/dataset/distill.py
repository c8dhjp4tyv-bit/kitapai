"""Gerekçe damıtma: şablonla üretilmiş `why`/`hooks` metinlerini bir LLM'e yazdırır.

Şablon gerekçeler modelin öğrenebileceği tavanı belirliyor: "Tonu sürükleyici,
sürükleyiciliği düşürmeden" gibi anlamsız kalıplar ve tema sözlüğünden gelen yanlış
iddialar ("Corpus Delicti sağlık üzerine kurulu") eğitim hedefinde duruyor ve model
bunları birebir öğreniyor. Burada yalnızca *gerekçe metni* yeniden yazılır; hangi
kitabın seçildiği, güven puanı ve içerik uyarıları kural tabanlı kalır. Yani LLM
seçimi değiştiremez, yalnızca seçilmiş kitaba doğru bir açıklama yazar.

Sağlayıcı: Vertex AI üzerinde Gemini (ham HTTP, ek bağımlılık yok).

Kimlik doğrulama — sırayla:
  1. `GCLOUD_API_KEY` ortam değişkeni  → `x-goog-api-key` başlığı
  2. `--auth adc`                       → `gcloud auth application-default print-access-token`
Anahtar asla günlüğe, URL'ye ya da çıktı dosyasına yazılmaz.

Çıktı `distilled.jsonl` kaynak örnekle aynı biçimdedir; yalnızca asistan mesajındaki
`why` ve `hooks` değişir. Betik kaldığı yerden devam eder (indeks bazlı).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from ..data.http import with_retries
from ..evaluation.metrics import copied_from, is_turkish
from ..logging import get
from ..prompting import build_write_user_message, match_strength

log = get("dataset.distill")

DEFAULT_MODEL = "gemini-3.8-flash"
DEFAULT_PROJECT = "flint-client"
API_KEY_ENV = "GCLOUD_API_KEY"

#: Düşünme ayarı. ÖLÇÜLDÜ (2026-10-02, gemini-3.8-flash): ayar verilmediğinde 78 token'lık bir
#: istek için 553 düşünme token'ı harcanıyor (görünen çıktının ~4 katı, çıktı olarak
#: faturalanır). `thinkingLevel: "low"` bunu 0'a indirdi; "minimal" bu modelde 400 veriyor.
DEFAULT_THINKING: dict = {"thinkingLevel": "low"}

MAX_WHY_CHARS = 320
MIN_WHY_CHARS = 25
MAX_HOOK_WORDS = 4

SYSTEM_INSTRUCTION = """Sen kitap.ai için gerekçe yazan bir editörsün.

Sana bir okurun isteği ve o isteğe uygun bulunmuş kitapların katalog bilgisi verilir.
Her kitap için okurun isteğine bağlanan, doğal ve akıcı bir Türkçe gerekçe yaz.

KURALLAR
1. YALNIZCA verilen bilgilere dayan (tür, ruh hali, konular, özet, yıl, sayfa, puan).
   Olay örgüsü, karakter adı, sonuç ya da verilmemiş başka bir bilgi uydurma.
   Bilgi azsa kısa ve genel kal; boşluğu "ilginç ayrıntılar", "keyifli bir yolculuk"
   gibi içi boş ifadelerle doldurma.
2. DÜRÜST OL. Her kitapta bir "uyum" bilgisi var (güçlü / orta / zayıf).
   - güçlü: isteğe nasıl bağlandığını anlat.
   - orta: ne uyduğunu söyle, varsa eksiği tek kısa ifadeyle belirt.
   - zayıf: eksiği AÇIKÇA söyle ("roman değil, şiir kitabı ama...", "kurgu değil,
     bilgi kitabı..."). Kitabın türü ya da biçimi istekle çelişiyorsa bunu gizleme.
   Zayıf bir eşleşmeyi güçlüymüş gibi anlatmak yasak.
3. Okura "sen" diye hitap et ("aradığın", "seveceksin", "denemeni öneririm").
   Asla "siz" biçimi kullanma ("aradığınız", "ilginizi çekecektir" YASAK).
4. "why": 1-2 cümle, en fazla 300 karakter. Okurun kendi sözcüklerine bağlan.
   Kalıp cümleler ve tekrar eden açılışlar kullanma; her kitap farklı yazılsın.
5. Özet metnini kopyalama, çevirip yeniden yazma.
6. "hooks": en fazla 2 çengel ifade, her biri en fazla 4 sözcük; verilen bilgiye dayansın.
7. Aday bilgisi İngilizce olabilir; yanıtın tamamı Türkçe olsun.
8. Yanıt YALNIZCA şu biçimde geçerli JSON olsun:
{"items":[{"id":"a1","why":"...","hooks":["...","..."]}]}"""


class DistillError(RuntimeError):
    """Kimlik, uç nokta ya da yanıt biçimi hatası."""


# ── istemci ────────────────────────────────────────────────────────────────


@dataclass
class Usage:
    """Gerçek token kullanımı — maliyet tahmini varsayımla değil bununla yapılır."""

    requests: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    thought_tokens: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, meta: dict | None) -> None:
        meta = meta or {}
        with self._lock:
            self.requests += 1
            self.prompt_tokens += int(meta.get("promptTokenCount") or 0)
            self.output_tokens += int(meta.get("candidatesTokenCount") or 0)
            self.thought_tokens += int(meta.get("thoughtsTokenCount") or 0)

    def as_dict(self) -> dict:
        n = max(1, self.requests)
        return {
            "requests": self.requests,
            "prompt_tokens": self.prompt_tokens,
            "output_tokens": self.output_tokens,
            "thought_tokens": self.thought_tokens,
            "per_request": {
                "prompt": round(self.prompt_tokens / n),
                "output": round(self.output_tokens / n),
                "thought": round(self.thought_tokens / n),
            },
        }


class GeminiClient:
    """Vertex AI `generateContent` için minimal istemci."""

    def __init__(
        self,
        *,
        project: str = DEFAULT_PROJECT,
        model: str = DEFAULT_MODEL,
        location: str = "global",
        auth: str = "key",
        api_key: str | None = None,
        thinking: dict | None = DEFAULT_THINKING,
        timeout: float = 90.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.project, self.model, self.location, self.auth = project, model, location, auth
        self.thinking = thinking
        self._key = api_key if api_key is not None else os.environ.get(API_KEY_ENV, "")
        if auth == "key" and not self._key:
            raise DistillError(
                f"{API_KEY_ENV} ortam değişkeni yok. Anahtarı ~/.zshrc'ye "
                f"`export {API_KEY_ENV}=...` olarak yazıp YENİ bir terminal açın "
                f"(ya da `--auth adc` ile `gcloud auth application-default login` kullanın)."
            )
        self._client = httpx.Client(timeout=timeout, transport=transport)
        self.usage = Usage()
        self._endpoint: str | None = None
        self._lock = threading.Lock()

    # Anahtar yalnızca başlıkta; URL'ye eklenmez (günlük/proxy'lerde sızmasın).
    def _headers(self) -> dict[str, str]:
        if self.auth == "adc":
            r = subprocess.run(
                ["gcloud", "auth", "application-default", "print-access-token"],
                capture_output=True, text=True, check=False,
            )
            if r.returncode != 0:
                raise DistillError("ADC token alınamadı: `gcloud auth application-default login`")
            return {"Authorization": f"Bearer {r.stdout.strip()}"}
        return {"x-goog-api-key": self._key}

    def _urls(self) -> list[str]:
        """Aday uç noktalar. API anahtarı hem 'express' hem proje URL'siyle gelebilir."""
        suffix = f"publishers/google/models/{self.model}:generateContent"
        express = f"https://aiplatform.googleapis.com/v1/{suffix}"
        project = (f"https://aiplatform.googleapis.com/v1/projects/{self.project}"
                   f"/locations/{self.location}/{suffix}")
        return [project, express] if self.auth == "adc" else [express, project]

    def generate(self, system: str, user: str, *, temperature: float = 0.7) -> dict:
        """Ham yanıt sözlüğünü döndürür. Geçici hatalarda yeniden dener."""
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": temperature,
                "responseMimeType": "application/json",
            },
        }
        if self.thinking:
            body["generationConfig"]["thinkingConfig"] = self.thinking
        headers = self._headers()

        def call() -> dict:
            urls = [self._endpoint] if self._endpoint else self._urls()
            last: httpx.Response | None = None
            for url in urls:
                resp = self._client.post(url, json=body, headers=headers)
                if resp.status_code == 200:
                    with self._lock:
                        self._endpoint = url
                    return resp.json()
                last = resp
                # Yanlış uç nokta: sıradakini dene. Geçici hata: yeniden denenecek.
                if resp.status_code not in (400, 401, 403, 404):
                    break
            assert last is not None
            last.raise_for_status()
            raise DistillError(f"beklenmeyen yanıt: {last.status_code}")

        data = with_retries(call, what=f"{self.model} isteği")
        self.usage.add(data.get("usageMetadata"))
        return data


# ── istem ve doğrulama ─────────────────────────────────────────────────────

_CAND_BLOCK = re.compile(r"\n(?=\[a\d+\])")
_CAND_ID = re.compile(r"^\[(a\d+)\]")


def split_candidates(user_message: str) -> dict[str, str]:
    """İstem metnindeki aday bloklarını `{id: blok}` olarak ayırır."""
    if "ADAYLAR\n" not in user_message:
        return {}
    body = user_message.split("ADAYLAR\n", 1)[1].split("\n\nYanıtı", 1)[0]
    out: dict[str, str] = {}
    for block in _CAND_BLOCK.split(body):
        m = _CAND_ID.match(block)
        if m:
            out[m.group(1)] = block.strip()
    return out


def build_user_prompt(sample: dict) -> tuple[str, list[str]]:
    """Gemini'ye gidecek metin ve beklenen kimlikler.

    Yalnızca *seçilen* kitapların bilgisi gönderilir (12 adayın tamamı değil):
    girdi yaklaşık dörtte birine iner ve gerekçe zaten yalnızca seçilenler için.
    """
    user = sample["messages"][1]["content"]
    request = user.split("ADAYLAR")[0].replace("İSTEK\n", "").strip()
    target = json.loads(sample["messages"][2]["content"])
    blocks = split_candidates(user)
    picks = [p for p in target["picks"] if p["id"] in blocks]
    ids = [p["id"] for p in picks]
    books = [(blocks[p["id"]], match_strength(p.get("confidence"))) for p in picks]
    return build_write_user_message(request, books), ids


def extract_json(response: dict) -> dict:
    """Yanıttan JSON gövdesini çıkarır; düşünme parçalarını yok sayar."""
    try:
        parts = response["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError) as exc:
        reason = (response.get("candidates") or [{}])[0].get("finishReason", "bilinmiyor")
        raise DistillError(f"yanıt boş (finishReason={reason})") from exc
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise DistillError(f"geçersiz JSON: {text[:80]!r}") from exc


#: "siz" hitabı kalıpları. Arayüz tonu "sen"; karışık hitap modele öğretilmesin.
FORMAL_ADDRESS = re.compile(
    r"\b(?:\w*(?:ınız|iniz|unuz|ünüz|nızı|nizi|nuzu|nüzü|ınızı|inizi)\b|"
    r"\w*(?:sanız|seniz)\b|\w*(?:ınızın|inizin)\b|ediniz|ediniz|göz atınız)",
    re.IGNORECASE,
)


def validate_items(
    items: list[dict], expected_ids: list[str], sources: dict[str, str]
) -> list[str]:
    """Kalite kapıları. Boş liste = geçti; aksi hâlde ret nedenleri."""
    problems: list[str] = []
    got = [i.get("id") for i in items]
    if sorted(got) != sorted(expected_ids):
        return [f"kimlikler uyuşmuyor: beklenen {expected_ids}, gelen {got}"]
    for item in items:
        why = (item.get("why") or "").strip()
        iid = item["id"]
        if not (MIN_WHY_CHARS <= len(why) <= MAX_WHY_CHARS):
            problems.append(f"{iid}: gerekçe uzunluğu {len(why)}")
        elif not is_turkish(why):
            problems.append(f"{iid}: Türkçe değil")
        elif copied_from(why, sources.get(iid), n=7):
            problems.append(f"{iid}: özetten kopyalama")
        elif FORMAL_ADDRESS.search(why):
            problems.append(f"{iid}: resmi hitap (siz)")
        hooks = item.get("hooks") or []
        if not isinstance(hooks, list) or any(
            len(str(h).split()) > MAX_HOOK_WORDS for h in hooks
        ):
            problems.append(f"{iid}: çengel biçimi")
    return problems


def apply_distilled(sample: dict, items: list[dict]) -> dict:
    """Şablon `why`/`hooks` yerine damıtılmışları koyar; geri kalan her şey aynı kalır."""
    target = json.loads(sample["messages"][2]["content"])
    by_id = {i["id"]: i for i in items}
    for pick in target["picks"]:
        new = by_id.get(pick["id"])
        if new:
            pick["why"] = new["why"].strip()
            pick["hooks"] = [str(h).strip() for h in (new.get("hooks") or [])][:2]
    out = json.loads(json.dumps(sample))
    out["messages"][2]["content"] = json.dumps(target, ensure_ascii=False)
    out.setdefault("meta", {})["distilled"] = True
    return out


# ── toplu çalıştırma ───────────────────────────────────────────────────────


@dataclass
class DistillReport:
    attempted: int = 0
    accepted: int = 0
    rejected: int = 0
    skipped_done: int = 0
    errors: int = 0
    reasons: dict[str, int] = field(default_factory=dict)
    usage: dict = field(default_factory=dict)


def distill_file(
    client: GeminiClient,
    source: Path,
    out: Path,
    *,
    limit: int | None = None,
    start: int = 0,
    workers: int = 6,
    on_progress: Callable[[int, int], None] | None = None,
) -> DistillReport:
    """`source` JSONL'sinden örnekleri damıtıp `out`'a ekler. Devam edilebilir."""
    rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()]
    window = list(enumerate(rows))[start:(start + limit) if limit else None]

    done: set[int] = set()
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(line)["meta"]["source_index"])
            except (KeyError, ValueError):
                continue
    todo = [(i, r) for i, r in window if i not in done]
    report = DistillReport(skipped_done=len(window) - len(todo))
    out.parent.mkdir(parents=True, exist_ok=True)
    write_lock = threading.Lock()

    def work(idx: int, sample: dict) -> tuple[int, dict | None, str | None]:
        prompt, ids = build_user_prompt(sample)
        if not ids:
            return idx, None, "seçilen kitap bulunamadı"
        sources = split_candidates(sample["messages"][1]["content"])
        try:
            items = extract_json(client.generate(SYSTEM_INSTRUCTION, prompt)).get("items") or []
        except (DistillError, httpx.HTTPError, KeyError) as exc:
            return idx, None, f"hata: {type(exc).__name__}"
        problems = validate_items(items, ids, sources)
        if problems:
            return idx, None, problems[0].split(":", 1)[-1].strip()[:40]
        return idx, apply_distilled(sample, items), None

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool, out.open(
        "a", encoding="utf-8"
    ) as fh:
        futures = [pool.submit(work, i, r) for i, r in todo]
        for n, fut in enumerate(as_completed(futures), start=1):
            idx, result, reason = fut.result()
            report.attempted += 1
            if result is not None:
                result["meta"]["source_index"] = idx
                with write_lock:
                    fh.write(json.dumps(result, ensure_ascii=False) + "\n")
                    fh.flush()
                report.accepted += 1
            else:
                report.rejected += 1
                if reason and reason.startswith("hata"):
                    report.errors += 1
                report.reasons[reason or "?"] = report.reasons.get(reason or "?", 0) + 1
            if on_progress:
                on_progress(n, len(todo))
            # Saatler süren koşuda ilerleme ve gerçek token kullanımı görünsün; süreç
            # ölürse bile son durum günlükte kalır (rapor yalnızca sonda basılıyordu).
            if n % 250 == 0 or n == len(todo):
                u = client.usage.as_dict()
                log.info("ilerleme %d/%d · kabul %d · ret %d · hata %d · token girdi %s çıktı %s",
                         n, len(todo), report.accepted, report.rejected, report.errors,
                         f"{u['prompt_tokens']:,}", f"{u['output_tokens']:,}")

    report.usage = client.usage.as_dict()
    log.info("damıtma: %d kabul, %d ret, %d atlandı (%.0f sn)", report.accepted,
             report.rejected, report.skipped_done, time.perf_counter() - started)
    return report
