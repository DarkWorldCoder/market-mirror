"""Optional local text embeddings for the memory graph (free, CPU, no API key).

Anthropic has no embeddings API, so the local memory backend embeds text with
`fastembed <https://github.com/qdrant/fastembed>`_ (ONNX Runtime). Everything
here is lazy and optional: if ``fastembed`` is not installed, or the model
cannot be downloaded/loaded, :meth:`FastEmbedEmbedder.embed` returns ``None``
and callers fall back to keyword (BM25) search only.

Vectors are L2-normalised ``float32`` so cosine similarity is a dot product.
"""

from __future__ import annotations

import hashlib
import threading
import time
from typing import Dict, List, Optional, Protocol, Sequence, runtime_checkable

import numpy as np

from .logger import get_logger

logger = get_logger("mirofish.embeddings")

DEFAULT_EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


@runtime_checkable
class Embedder(Protocol):
    """Minimal embedder interface used by ``LocalZep``.

    ``embed`` returns one normalised float32 vector per text, or ``None`` when
    embeddings are unavailable (callers must then fall back to BM25).
    """

    model_name: str

    def embed(self, texts: Sequence[str], *, query: bool = False) -> Optional[List[np.ndarray]]:
        ...


def text_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()


def normalize(vector: Sequence[float]) -> np.ndarray:
    array = np.asarray(vector, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(array))
    return array / norm if norm > 0 else array


def to_blob(vector: np.ndarray) -> bytes:
    return np.asarray(vector, dtype=np.float32).tobytes()


def from_blob(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def cosine_rank(query_vector: np.ndarray, vectors: Sequence[Optional[np.ndarray]],
                *, min_score: float = 0.0, top_k: Optional[int] = None) -> List[tuple[int, float]]:
    """Return ``(index, cosine)`` sorted best-first, skipping missing vectors."""

    indexed = [(i, v) for i, v in enumerate(vectors) if v is not None and v.shape == query_vector.shape]
    if not indexed:
        return []
    matrix = np.vstack([v for _i, v in indexed])
    scores = matrix @ query_vector
    ranked = [
        (indexed[pos][0], float(scores[pos]))
        for pos in np.argsort(-scores, kind="stable")
        if float(scores[pos]) >= min_score
    ]
    return ranked[:top_k] if top_k else ranked


def reciprocal_rank_fusion(rankings: Sequence[Sequence[int]], *, k: int = 60) -> List[tuple[int, float]]:
    """Fuse several best-first index lists; ties broken by first appearance."""

    scores: Dict[int, float] = {}
    first_seen: Dict[int, int] = {}
    order = 0
    for ranking in rankings:
        for rank, index in enumerate(ranking):
            scores[index] = scores.get(index, 0.0) + 1.0 / (k + rank + 1)
            if index not in first_seen:
                first_seen[index] = order
                order += 1
    return sorted(scores.items(), key=lambda item: (-item[1], first_seen[item[0]]))


class FastEmbedEmbedder:
    """Lazy fastembed wrapper. Loads the ONNX model on first use."""

    def __init__(self, model_name: str = DEFAULT_EMBED_MODEL, *, cache_dir: Optional[str] = None,
                 threads: Optional[int] = None, batch_size: int = 64):
        self.model_name = model_name
        self.cache_dir = cache_dir
        self.threads = threads
        self.batch_size = batch_size
        self._model = None
        self._failed = False
        self._lock = threading.Lock()
        self.load_seconds: Optional[float] = None

    @property
    def available(self) -> bool:
        return not self._failed

    def _load(self):
        if self._model is not None or self._failed:
            return self._model
        started = time.time()
        try:
            from fastembed import TextEmbedding  # noqa: WPS433 - optional dependency

            self._model = TextEmbedding(
                model_name=self.model_name, cache_dir=self.cache_dir, threads=self.threads
            )
            self.load_seconds = time.time() - started
            logger.info("Loaded embedding model %s in %.1fs", self.model_name, self.load_seconds)
        except Exception as error:  # noqa: BLE001 - ImportError, download or ONNX errors
            self._failed = True
            logger.warning(
                "Embeddings disabled (falling back to keyword search): cannot load %s: %s",
                self.model_name, error,
            )
        return self._model

    def embed(self, texts: Sequence[str], *, query: bool = False) -> Optional[List[np.ndarray]]:
        if not texts:
            return []
        with self._lock:  # ONNX session is shared; serialise to bound CPU use
            model = self._load()
            if model is None:
                return None
            try:
                items = [str(t or " ") for t in texts]
                method = model.query_embed if query else model.passage_embed
                vectors = list(method(items, batch_size=self.batch_size))
            except Exception as error:  # noqa: BLE001
                logger.warning("Embedding failed, using keyword search only: %s", error)
                return None
        return [normalize(vector) for vector in vectors]


_default_lock = threading.Lock()
_default_embedders: Dict[tuple, FastEmbedEmbedder] = {}


def get_default_embedder() -> Optional[FastEmbedEmbedder]:
    """Return the process-shared embedder from Config, or ``None`` if disabled."""

    from ..config import Config

    if not Config.MEMORY_EMBEDDINGS:
        return None
    key = (Config.MEMORY_EMBED_MODEL, Config.MEMORY_EMBED_CACHE_DIR)
    with _default_lock:
        embedder = _default_embedders.get(key)
        if embedder is None:
            embedder = FastEmbedEmbedder(Config.MEMORY_EMBED_MODEL, cache_dir=Config.MEMORY_EMBED_CACHE_DIR)
            _default_embedders[key] = embedder
        return embedder
