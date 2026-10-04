"""Öneri boru hattı: geri getir → üret → doğrula → zenginleştir.

Kritik nokta 3. adımdır: modelin ürettiği `id` referansları katalog kayıtlarına
geri çözülür. Model listede olmayan bir kimlik uydurursa o seçim düşer. Bu
yüzden yanıttaki hiçbir başlık, yazar, yıl veya ISBN modelden gelmez.
"""

from __future__ import annotations

import asyncio
import random
import time
import uuid
from dataclasses import dataclass, field

from .. import __version__
from ..dataset.queries import GeneratedQuery
from ..dataset.tasks import write_hooks, write_why
from ..dataset.themes import content_notes_for
from ..logging import get
from ..matching import match_reasons, match_score
from ..prompting import (
    PROMPT_CANDIDATES,
    WRITE_BASE_TOKENS,
    WRITE_TOKENS_PER_BOOK,
    Candidate,
    build_select_messages,
    build_write_messages,
    match_strength,
    render_candidate,
    render_request,
)
from ..schemas import (
    Book,
    Rating,
    Recommendation,
    RecommendRequest,
    RecommendResponse,
    ResponseMeta,
)
from .decode import decode_select, decode_write
from .engine import Engine

log = get("serve.pipeline")


class Overloaded(RuntimeError):
    """Üretim kuyruğu dolu."""


def to_book(row: dict) -> Book:
    """Katalog satırı → API `Book` nesnesi."""
    rating = None
    if row.get("rating_avg") and row.get("rating_count"):
        rating = Rating(average=float(row["rating_avg"]), count=int(row["rating_count"]))
    return Book(
        work_key=row["work_key"],
        title=row.get("title_tr") or row.get("title") or "",
        subtitle=row.get("subtitle"),
        authors=list(row.get("authors") or []),
        first_published=row.get("first_published"),
        description=row.get("description"),
        genres=list(row.get("genres") or []),
        moods=list(row.get("moods") or []),
        subjects=list(row.get("subjects") or [])[:12],
        languages=list(row.get("languages") or []),
        pages=row.get("pages"),
        isbns=list(row.get("isbns") or [])[:4],
        cover_url=row.get("cover_url"),
        openlibrary_url=row.get("openlibrary_url")
        or f"https://openlibrary.org{row['work_key']}",
        rating=rating,
        readers=row.get("readers"),
        popularity=float(row.get("popularity") or 0.0),
    )


@dataclass
class PipelineResult:
    response: RecommendResponse
    raw_select: str = ""
    raw_write: str = ""
    errors: list[str] = field(default_factory=list)


def _has_target(target) -> bool:
    """Uyum puanının anlamlı olması için en az bir kısıt/hedef gerekir."""
    return bool(target.genres or target.moods or target.era or target.length
                or target.audience or target.languages)


class RecommendPipeline:
    """Geri getir → SEÇ → zayıfları ele → YAZ → doğrula.

    SEÇ ve YAZ ayrı LoRA'lardır (bkz. `prompting.py`'deki gerekçe). Her aşamanın kendi
    yedek yolu var: SEÇ çökerse geri getirme sıralaması, YAZ çökerse şablon gerekçe
    kullanılır; böylece biri bozulsa bile istek boş dönmez.

    Yanıttaki başlık, yazar, yıl, ISBN gibi bilgilerin hiçbiri modelden gelmez;
    güven puanı ve eşleşme kanıtı da kural tabanlıdır.
    """

    def __init__(self, retriever, engine: Engine, settings) -> None:
        self.retriever = retriever
        self.engine = engine
        self.settings = settings
        self._semaphore = asyncio.Semaphore(max(1, settings.max_concurrent_generations))
        self._waiting = 0

    # ── üretim ─────────────────────────────────────────────────────────────

    async def _run(self, fn, *args, **kwargs):
        """Üretim çağrısını kuyruğa alıp bir iş parçacığında çalıştırır.

        Tek GPU'da eşzamanlı üretim belleği patlattığı için semafor ile sıraya sokulur;
        kuyruk sınırı aşılırsa istek beklemek yerine hemen reddedilir (503) — böylece
        zaman aşımı yığılmaz.
        """
        if self._waiting >= self.settings.queue_limit:
            raise Overloaded(
                f"üretim kuyruğu dolu ({self._waiting}/{self.settings.queue_limit})"
            )
        self._waiting += 1
        try:
            async with self._semaphore:
                return await asyncio.wait_for(
                    asyncio.to_thread(fn, *args, **kwargs),
                    timeout=self.settings.request_timeout_s,
                )
        finally:
            self._waiting -= 1

    async def _generate(self, messages: list[dict[str, str]], **kwargs) -> str:
        return await self._run(self.engine.generate, messages, **kwargs)

    # ── kural tabanlı yardımcılar ──────────────────────────────────────────

    @staticmethod
    def _template(row: dict, target) -> tuple[str, list[str]]:
        """Şablon gerekçe + çengel (YAZ çökerse). Eğitim öncesi sistemle aynı üretici."""
        pseudo = GeneratedQuery(
            text="", style="servis",
            genres=list(target.genres), moods=list(target.moods), era=target.era,
            length=target.length, audience=target.audience,
            languages=[getattr(lang, "value", lang) for lang in target.languages],
        )
        rng = random.Random(0)
        return write_why(row, pseudo, rng), write_hooks(row, rng)

    def _filter_weak(
        self, picked: list[tuple[str, dict, float]], target
    ) -> tuple[list[tuple[str, dict, float]], int]:
        """Hedefe kural tabanlı uyumu zayıf seçimleri eler.

        Model "tarihle ilgisi yok" yazıp aynı kitabı yine listeliyordu: dürüst ama
        işe yaramaz. Kural puanı zaten elimizde olduğundan, zayıf eşleşmeyi göstermek
        yerine hiç göstermemek daha iyi. Yalnızca hedef VARSA uygulanır (kısıtsız
        isteklerde puan bilinirliğe dayanır, eşik anlamsızdır) ve en az bir öneri
        her zaman kalır.
        """
        if not _has_target(target) or not picked:
            return picked, 0
        kept = [t for t in picked if t[2] >= self.settings.min_confidence]
        if not kept:
            kept = [max(picked, key=lambda t: t[2])]
        return kept, len(picked) - len(kept)

    @staticmethod
    def _followups(n_shown: int, limit: int, dropped: int, confs: list[float]) -> list[str]:
        out: list[str] = []
        if dropped or n_shown < limit:
            out.append("Filtreleri biraz gevşetmemi ister misin? Uyan kitap az çıktı.")
        elif confs and min(confs) < 0.6:
            out.append("Daha isabetli öneri için tür ya da ruh halini belirtir misin?")
        return out[:2]

    # ── ana akış ───────────────────────────────────────────────────────────

    async def recommend(self, request: RecommendRequest) -> PipelineResult:
        started = time.perf_counter()
        request_id = uuid.uuid4().hex[:12]
        notes: list[str] = []
        errors: list[str] = []

        def meta(**kw) -> ResponseMeta:
            return ResponseMeta(
                request_id=request_id, model=self.engine.model_id, engine=self.engine.name,
                latency_ms=int((time.perf_counter() - started) * 1000), notes=notes, **kw)

        retrieval = await asyncio.to_thread(
            self.retriever.retrieve, request, pool=self.settings.candidate_pool
        )
        t_retrieve = time.perf_counter()
        if not retrieval.books:
            notes.append("aday bulunamadı")
            return PipelineResult(RecommendResponse(
                recommendations=[],
                followups=["Filtreleri gevşetmeyi dener misin? Bu kısıtlara uyan kitap bulamadım."],
                meta=meta(retrieved=0, grounded_ratio=0.0, degraded=False),
            ))

        if retrieval.used_browse:
            notes.append("metin eşleşmesi yok; bilinirliğe göre gezinme kullanıldı")
        exp = retrieval.expansion
        if exp and exp.detected_genres and not request.genres:
            notes.append("metinden çıkarılan tür: " + ", ".join(exp.detected_genres))

        target = retrieval.target
        shortlist = retrieval.books[:PROMPT_CANDIDATES]
        candidates = {f"a{i}": Candidate.from_row(row, f"a{i}")
                      for i, row in enumerate(shortlist, 1)}
        by_id = {f"a{i}": row for i, row in enumerate(shortlist, 1)}
        request_block = render_request(
            query=request.query, genres=list(request.genres), moods=list(request.moods),
            era=request.era, length=request.length, audience=request.audience,
            languages=[lang.value for lang in request.languages], limit=request.limit,
        )

        # ── 1) SEÇ ──────────────────────────────────────────────────────────
        degraded = False
        raw_select = ""
        ids: list[str] = []
        try:
            raw_select = await self._generate(
                build_select_messages(request_block, list(candidates.values())),
                adapter="select", max_new_tokens=60, temperature=0.0,
            )
            decoded, err = decode_select(raw_select)
            if decoded is None:
                errors.append(f"seçici: {err}")
            else:
                ids = [i for i in decoded if i in by_id]
                if len(ids) < len(decoded):
                    notes.append("bilinmeyen aday kimliği atlandı")
        except Overloaded:
            raise
        except TimeoutError:
            errors.append("seçici zaman aşımı")
        except Exception as exc:
            log.exception("seçici hatası")
            errors.append(f"seçici: {exc}")
        ids = ids[: request.limit]
        if not ids:
            degraded = True
            ids = list(by_id)[: request.limit]     # yedek: geri getirme sıralaması
            notes.append(f"yedek sıralama kullanıldı ({errors[-1] if errors else 'boş seçim'})")

        t_select = time.perf_counter()
        picked = [(i, by_id[i], round(match_score(by_id[i], target), 2)) for i in ids]
        picked, dropped = self._filter_weak(picked, target)
        if dropped:
            notes.append(f"{dropped} zayıf eşleşme elendi")

        # ── 2) YAZ ──────────────────────────────────────────────────────────
        books = [(render_candidate(candidates[i]), match_strength(conf)) for i, _r, conf in picked]
        items: dict[str, dict] = {}
        raw_write = ""
        try:
            raw_write = await self._generate(
                build_write_messages(request_block, books),
                adapter="write", temperature=0.3,
                max_new_tokens=WRITE_BASE_TOKENS + WRITE_TOKENS_PER_BOOK * len(books),
            )
            items, err = decode_write(raw_write)
            if err:
                errors.append(f"yazıcı: {err}")
        except Overloaded:
            raise
        except TimeoutError:
            errors.append("yazıcı zaman aşımı")
        except Exception as exc:
            log.exception("yazıcı hatası")
            errors.append(f"yazıcı: {exc}")

        t_write = time.perf_counter()
        recommendations: list[Recommendation] = []
        for cid, row, conf in picked:
            item = items.get(cid) or {}
            why, hooks = (item.get("why") or "").strip(), list(item.get("hooks") or [])
            if not why:
                why, hooks = self._template(row, target)
                degraded = True
            elif not hooks:                       # yazıcı çengel üretmez: kural tabanlı
                hooks = self._template(row, target)[1]
            recommendations.append(Recommendation(
                rank=len(recommendations) + 1,
                book=to_book(row),
                why=why,
                hooks=hooks[:2],
                content_notes=content_notes_for(list(row.get("subjects") or [])),
                confidence=conf,
                grounded=True,
                match_reasons=match_reasons(row, target),
            ))
        if degraded and not any("yedek" in n for n in notes):
            notes.append("gerekçe şablonla yazıldı (yazıcı yanıtı kullanılamadı)")

        followups = self._followups(
            len(recommendations), request.limit, dropped, [r.confidence for r in recommendations])
        response = RecommendResponse(
            recommendations=recommendations, followups=followups,
            meta=meta(retrieved=len(retrieval.books),
                      grounded_ratio=1.0 if recommendations else 0.0, degraded=degraded),
        )
        log.info("öneri %s: %s sonuç, %s aday, %s ms (getir %d · seç %d · yaz %d, %d kr)%s",
                 request_id, len(recommendations), len(retrieval.books),
                 response.meta.latency_ms, 1000 * (t_retrieve - started),
                 1000 * (t_select - t_retrieve), 1000 * (t_write - t_select), len(raw_write),
                 " (yedek)" if degraded else "")
        return PipelineResult(response, raw_select=raw_select, raw_write=raw_write, errors=errors)


def version_info() -> str:
    return __version__
