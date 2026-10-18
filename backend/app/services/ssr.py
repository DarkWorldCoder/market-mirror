"""
Semantic similarity rating (SSR): turn a persona's free-text answer into a
rating distribution instead of asking for a number.

LLM personas asked for a 0-10 score or yes/maybe/no compress their answers
toward the middle-positive and match real buyers poorly. Maier et al. 2025,
"LLMs Reproduce Human Purchase Intent via Semantic Similarity Elicitation of
Likert Ratings" (arXiv 2510.08338), let the persona answer in its own words
and map the text onto a 5-point Likert scale by embedding similarity against
anchor statements, which reproduces human rating distributions far better.

For each scale there are several anchor sets, each with one statement per
scale point (1 = most negative, 5 = most positive). For one anchor set:

    gamma_k = cosine(answer, anchor_k)
    p_k     = (gamma_k - min(gamma) + epsilon) ** (1 / temperature), normalised

and the distribution is the average over anchor sets. The embedder is the
local multilingual fastembed model also used by the memory graph, so answers
in any language map onto the English anchors at no API cost.

Only the first sentence of an answer is embedded. The survey asks every answer
to open with a verdict ("No / Probably not / Maybe / Probably yes / Yes,
definitely") followed by a reason; the reasons and conditions ("only if the
reviews…") pull every answer toward the middle of the scale. On 40 hand-labelled
answers from a real run, embedding the first sentence raised the Pearson r of
the purchase mean against the labels from 0.22 to 0.57.
"""

from __future__ import annotations

import math
import re
import threading
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from ..utils.logger import get_logger

logger = get_logger("mirofish.ssr")

POINTS = 5
ANCHORS_VERSION = "2026-10-ssr-v2-lead-sentence"

# scale -> anchor sets; each set lists one statement per point, from 1 (lowest) to 5 (highest)
ANCHORS: Dict[str, List[List[str]]] = {
    "interest": [
        ["I'm not interested in this at all.", "I'm not really interested.", "I'm somewhat interested, but not sure.",
         "I'm quite interested in this.", "I'm very interested, this is exactly what I want."],
        ["This doesn't appeal to me in any way.", "It doesn't appeal to me much.", "It's okay, I'm neutral about it.",
         "This appeals to me and I'd like to know more.", "This really appeals to me, I'm excited about it."],
        ["I have zero interest and would ignore it.", "Probably not for me, I'm only slightly curious.",
         "I'm a bit curious but undecided.", "I'm interested and would look into it.",
         "I'm extremely interested and want it right away."],
    ],
    "trust": [
        ["I don't trust this at all, it looks like a scam.", "I'm suspicious and don't really trust it.",
         "I'm not sure whether to trust it.", "It seems mostly trustworthy.",
         "I fully trust this, it is clearly legitimate."],
        ["I have no confidence in this, it seems fake.", "I have doubts about whether this is legitimate.",
         "It might be legitimate, I can't tell yet.", "I think this is legitimate and fairly reliable.",
         "I have complete confidence in them."],
        ["I completely distrust them.", "I'm wary, it feels a bit shady.", "I neither trust nor distrust it.",
         "I trust it reasonably well.", "This is completely trustworthy and reliable."],
    ],
    "purchase": [
        ["I definitely would not do this.", "I probably would not do this.", "I might or might not do it.",
         "I would probably do it.", "I would definitely do it."],
        ["There is no way I would sign up or buy.", "I'm unlikely to sign up or buy.",
         "Maybe, I'm undecided whether to sign up or buy.", "I'm likely to sign up or buy.",
         "I'm certain I will sign up or buy."],
        ["I will certainly not go ahead with it.", "I don't think I'll go ahead with it.",
         "It depends, I could go either way.", "I think I'll go ahead with it.", "I'll do it right away for sure."],
    ],
    "recommend": [
        ["I would never recommend this to anyone.", "I probably wouldn't recommend it.",
         "I might recommend it to some people.", "I would probably recommend it to friends.",
         "I would definitely recommend it to everyone I know."],
        ["I'd warn my friends against it.", "I doubt I'd mention it to friends.",
         "Maybe I'd mention it, depending on the person.", "I'd likely tell people about it.",
         "I'd strongly recommend it to my friends."],
        ["Definitely not something I'd tell others about.", "I'm unlikely to suggest it to anyone.",
         "I'm unsure if I'd recommend it.", "I think I'd suggest it to others.", "I'd tell everyone about it for sure."],
    ],
}
SCALES = tuple(ANCHORS)

# Latin sentence ends need a following space (keeps "4.5" whole); danda and CJK stops do not
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|(?<=[\u0964\u0965\u3002\uff01\uff1f])\s*")


def lead_sentence(text: str) -> str:
    """The verdict an answer opens with: its first sentence. (Joining a lead-in such as "Honestly?" to the
    next sentence was tried and lowered the correlation with hand labels from 0.57 to 0.39.)"""
    parts = [p.strip() for p in _SENTENCE_SPLIT.split(str(text or "").strip()) if p.strip()]
    return parts[0] if parts else ""


class SSRUnavailable(RuntimeError):
    """The embedding model could not be loaded, so free text cannot be mapped."""


_lock = threading.Lock()
_anchor_cache: Dict[str, Dict[str, np.ndarray]] = {}
_embedder = None


def get_embedder():
    """The process-shared fastembed model (same model and cache as the memory graph).

    SSR needs embeddings even when graph memory runs without them, so it builds its
    own instance when MEMORY_EMBEDDINGS is off."""
    global _embedder
    from ..utils.embeddings import FastEmbedEmbedder, get_default_embedder
    from ..config import Config
    shared = get_default_embedder()
    if shared is not None:
        return shared
    with _lock:
        if _embedder is None:
            _embedder = FastEmbedEmbedder(Config.MEMORY_EMBED_MODEL, cache_dir=Config.MEMORY_EMBED_CACHE_DIR)
        return _embedder


def _embed(embedder, texts: Sequence[str]) -> np.ndarray:
    vecs = embedder.embed(list(texts))
    if vecs is None or len(vecs) != len(texts):
        raise SSRUnavailable(f"embedding model {getattr(embedder, 'model_name', '?')} is unavailable")
    m = np.vstack([np.asarray(v, dtype=np.float32).reshape(-1) for v in vecs])
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    return m / np.where(norms > 0, norms, 1.0)


def anchor_matrix(embedder, scale: str) -> np.ndarray:
    """(sets, points, dim) anchor embeddings, cached per model."""
    key = getattr(embedder, "model_name", repr(embedder))
    with _lock:
        cached = _anchor_cache.setdefault(key, {})
        if scale in cached:
            return cached[scale]
    sets = ANCHORS[scale]
    flat = _embed(embedder, [s for st in sets for s in st])
    m = flat.reshape(len(sets), POINTS, -1)
    with _lock:
        _anchor_cache[key][scale] = m
    return m


def pmf_from_similarities(sims: np.ndarray, temperature: float = 1.0, epsilon: float = 0.0) -> np.ndarray:
    """sims: (sets, points) cosine similarities -> averaged probability mass over the points."""
    sims = np.atleast_2d(np.asarray(sims, dtype=np.float64))
    p = sims - sims.min(axis=1, keepdims=True) + max(epsilon, 0.0)
    p = np.where(p.sum(axis=1, keepdims=True) > 0, p, 1.0)           # identical similarities -> uniform
    if temperature and temperature != 1.0:
        p = p ** (1.0 / max(temperature, 1e-3))
    p = p / p.sum(axis=1, keepdims=True)
    return p.mean(axis=0)


def describe(pmf: Sequence[float]) -> Dict[str, Any]:
    """Mean and spread on the 1-5 scale, plus a 0-10 equivalent of the mean."""
    p = [float(x) for x in pmf]
    mean = sum((k + 1) * x for k, x in enumerate(p))
    var = sum(((k + 1) - mean) ** 2 * x for k, x in enumerate(p))
    return {"pmf": [round(x, 4) for x in p], "mean": round(mean, 3), "sd": round(math.sqrt(max(var, 0.0)), 3),
            "score10": round((mean - 1) * 2.5, 2)}


def rate(items: Sequence[Tuple[str, str]], embedder=None, temperature: float = 1.0,
         epsilon: float = 0.0, lead_only: bool = True) -> List[Optional[Dict[str, Any]]]:
    """[(scale, text)] -> one {pmf, mean, sd, score10} per item, or None for empty text / unknown scale.
    lead_only: embed only the answer's first sentence (its verdict), see lead_sentence.

    Raises SSRUnavailable when the embedding model cannot be used."""
    embedder = embedder or get_embedder()
    if embedder is None:
        raise SSRUnavailable("no embedding model configured")
    out: List[Optional[Dict[str, Any]]] = [None] * len(items)
    todo = [(i, scale, str(text).strip()) for i, (scale, text) in enumerate(items)
            if scale in ANCHORS and text is not None and str(text).strip()]
    if not todo:
        return out
    vecs = _embed(embedder, [lead_sentence(t) if lead_only else t for _, _, t in todo])
    for (i, scale, _), v in zip(todo, vecs):
        anchors = anchor_matrix(embedder, scale)
        sims = anchors @ v                                                  # (sets, points)
        out[i] = describe(pmf_from_similarities(sims, temperature, epsilon))
    return out
