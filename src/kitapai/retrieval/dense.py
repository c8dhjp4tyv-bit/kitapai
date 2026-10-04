"""Gömme (embedding) tabanlı anlamsal arama.

Katalog İngilizce, istek Türkçe olduğu için çok dilli bir gömme modeli
kullanılır (varsayılan: `intfloat/multilingual-e5-small`, 384 boyut, ~470 MB).
Vektörler float16 olarak tek bir `.npy` dosyasında tutulur: 300 bin kitap için
~230 MB, sıradan bir dizüstünde belleğe rahatça sığar. Bu ölçekte FAISS'e
gerek yoktur; tek bir matris çarpımı milisaniyeler sürer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..logging import get

log = get("retrieval.dense")

# e5 ailesi girdilerin önek almasını bekler.
QUERY_PREFIX = "query: "
PASSAGE_PREFIX = "passage: "


@dataclass(frozen=True)
class Hit:
    work_key: str
    score: float


def _load_encoder(model_name: str):
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:  # pragma: no cover - kurulum uyarısı
        raise ImportError(
            "Gömme araması için `pip install 'kitapai[embed]'` gerekiyor."
        ) from exc
    return SentenceTransformer(model_name)


def passage_text(row: dict) -> str:
    """Bir kitabın gömme metni. Konular ve açıklama en ayırt edici alanlar."""
    parts = [
        row.get("title") or "",
        ", ".join(row.get("authors") or []),
        ", ".join((row.get("subjects") or [])[:12]),
        (row.get("description") or "")[:400],
    ]
    return PASSAGE_PREFIX + " | ".join(p for p in parts if p)


class DenseIndex:
    """Bellekteki vektör matrisi + anahtar listesi."""

    def __init__(self, keys: list[str], vectors: np.ndarray, model_name: str) -> None:
        self.keys = keys
        self.vectors = vectors                      # (N, D) float16, L2-normalize
        self.model_name = model_name
        self._index = {k: i for i, k in enumerate(keys)}
        self._encoder = None

    # ── kurulum ────────────────────────────────────────────────────────────

    @classmethod
    def build(
        cls,
        rows: list[dict],
        out_dir: Path,
        *,
        model_name: str,
        batch_size: int = 64,
        progress: bool = True,
    ) -> DenseIndex:
        encoder = _load_encoder(model_name)
        texts = [passage_text(r) for r in rows]
        keys = [r["work_key"] for r in rows]
        log.info("%s kitap gömülüyor (%s)", f"{len(texts):,}", model_name)
        vectors = encoder.encode(
            texts, batch_size=batch_size, convert_to_numpy=True,
            normalize_embeddings=True, show_progress_bar=progress,
        ).astype(np.float16)

        out_dir.mkdir(parents=True, exist_ok=True)
        np.save(out_dir / "vectors.npy", vectors)
        (out_dir / "keys.json").write_text(json.dumps(keys), encoding="utf-8")
        (out_dir / "meta.json").write_text(
            json.dumps({"model": model_name, "dim": int(vectors.shape[1]),
                        "count": len(keys)}, indent=2), encoding="utf-8")
        log.info("vektörler yazıldı: %s (%.1f MB)", out_dir, vectors.nbytes / 2**20)
        return cls(keys, vectors, model_name)

    @classmethod
    def load(cls, directory: Path) -> DenseIndex | None:
        directory = Path(directory)
        vec_path, key_path, meta_path = (
            directory / "vectors.npy", directory / "keys.json", directory / "meta.json"
        )
        if not (vec_path.exists() and key_path.exists()):
            return None
        vectors = np.load(vec_path)
        keys = json.loads(key_path.read_text(encoding="utf-8"))
        model = "bilinmiyor"
        if meta_path.exists():
            model = json.loads(meta_path.read_text(encoding="utf-8")).get("model", model)
        if len(keys) != vectors.shape[0]:
            log.error("vektör/anahtar sayısı uyuşmuyor (%s vs %s) — indeks yok sayıldı",
                      vectors.shape[0], len(keys))
            return None
        log.info("gömme indeksi yüklendi: %s vektör × %s boyut",
                 f"{vectors.shape[0]:,}", vectors.shape[1])
        return cls(keys, vectors, model)

    # ── arama ──────────────────────────────────────────────────────────────

    def encode_query(self, text: str) -> np.ndarray:
        if self._encoder is None:
            self._encoder = _load_encoder(self.model_name)
        vec = self._encoder.encode(
            [QUERY_PREFIX + text], convert_to_numpy=True, normalize_embeddings=True
        )
        return vec[0].astype(np.float32)

    def search(
        self, text: str, limit: int, *, allowed: set[str] | None = None
    ) -> list[Hit]:
        if not text.strip() or self.vectors.shape[0] == 0:
            return []
        q = self.encode_query(text)

        if allowed is not None:
            idx = np.array([self._index[k] for k in allowed if k in self._index], dtype=np.int64)
            if idx.size == 0:
                return []
            mat = self.vectors[idx].astype(np.float32)
            scores = mat @ q
            order = np.argsort(-scores)[:limit]
            return [Hit(self.keys[int(idx[i])], float(scores[i])) for i in order]

        # Bütün matris: float16 → float32 dönüşümü parça parça yapılır ki
        # büyük kataloglarda bellek iki katına çıkmasın.
        best_scores = np.empty(0, dtype=np.float32)
        best_idx = np.empty(0, dtype=np.int64)
        chunk = 200_000
        for start in range(0, self.vectors.shape[0], chunk):
            block = self.vectors[start:start + chunk].astype(np.float32)
            scores = block @ q
            take = min(limit, scores.shape[0])
            part = np.argpartition(-scores, take - 1)[:take]
            best_scores = np.concatenate([best_scores, scores[part]])
            best_idx = np.concatenate([best_idx, part + start])

        order = np.argsort(-best_scores)[:limit]
        return [Hit(self.keys[int(best_idx[i])], float(best_scores[i])) for i in order]
