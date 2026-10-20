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

Optional engine: Jev (TypeSafe's decision model, services/jev.py). With SSR_ENGINE=jev (or engine "jev" per
request) each answer is sent whole as the state of one `score` question whose five levels are this scale's
anchor statements (level 0 -> rating 1 ... level 4 -> rating 5); Jev's level probabilities are the rating
distribution. An answer Jev fails on gets no rating (counted as failed). Engine "auto" uses Jev when a key is
configured and the embeddings for the answers Jev did not rate, and records which engine rated each answer.

Only the verdict clause of an answer is embedded: the first sentence, cut at the
first colon or dash. The survey asks every answer to open with a verdict ("No /
Probably not / Maybe / Probably yes / Yes, definitely") followed by a reason, and
personas write it as "Maybe: only if the reviews…"; the reasons and conditions pull
every answer toward the middle of the scale. On 40 hand-labelled answers from a
real run, the first sentence raised the Pearson r of the purchase mean against the
labels from 0.22 to 0.57; on 12 verdict-first answers, cutting at the colon or dash
raised it from 0.64 to 0.77.
"""

from __future__ import annotations

import math
import re
import threading
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from ..utils.logger import get_logger
from . import jev

logger = get_logger("mirofish.ssr")

POINTS = 5
ANCHORS_VERSION = "2026-10-ssr-v3-verdict-clause"

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


# the verdict ends at the first colon, en/em dash or spaced hyphen ("20-30%" stays whole)
_VERDICT_END = re.compile(r"\s*[:\u2013\u2014]\s*|\s+-\s+")


def verdict_clause(text: str) -> str:
    """The first sentence cut at its first colon or dash: "Maybe: only if…" -> "Maybe"."""
    lead = lead_sentence(text)
    head = _VERDICT_END.split(lead, maxsplit=1)[0].strip()
    return head or lead


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
    lead_only: embed only the answer's verdict clause, see verdict_clause.

    Raises SSRUnavailable when the embedding model cannot be used."""
    embedder = embedder or get_embedder()
    if embedder is None:
        raise SSRUnavailable("no embedding model configured")
    out: List[Optional[Dict[str, Any]]] = [None] * len(items)
    todo = [(i, scale, str(text).strip()) for i, (scale, text) in enumerate(items)
            if scale in ANCHORS and text is not None and str(text).strip()]
    if not todo:
        return out
    vecs = _embed(embedder, [verdict_clause(t) if lead_only else t for _, _, t in todo])
    for (i, scale, _), v in zip(todo, vecs):
        anchors = anchor_matrix(embedder, scale)
        sims = anchors @ v                                                  # (sets, points)
        out[i] = describe(pmf_from_similarities(sims, temperature, epsilon))
    return out


# --------------------------------------------------------------------------
# Engines: local embeddings (default), Jev, or Jev with embeddings for what it did not rate
# --------------------------------------------------------------------------

ENGINES = ("embeddings", "jev", "auto")
_ENGINE_ALIASES = {"embedding": "embeddings", "embeddings": "embeddings", "fastembed": "embeddings", "local": "embeddings",
                   "jev": "jev", "auto": "auto"}
SCALE_TOPICS = {"interest": "how interested they are in the offer",
                "trust": "how much they trust the offer and the company behind it",
                "purchase": "whether they would take the action they were asked about (sign up or buy)",
                "recommend": "whether they would recommend it to other people"}


def engine_name(value: Any = None, env: Optional[Dict[str, str]] = None) -> str:
    """The SSR engine: `value`, else SSR_ENGINE, else embeddings. Raises ValueError for an unknown name."""
    raw = str(value or "").strip().lower() or jev.settings(env)["ssr_engine"]
    if raw not in _ENGINE_ALIASES:
        raise ValueError(f"unknown SSR engine {raw!r} (choose from {', '.join(ENGINES)})")
    return _ENGINE_ALIASES[raw]


def jev_levels(scale: str) -> List[str]:
    """The scale's anchor statements as Jev score levels: level k lists every anchor set's statement for point k+1."""
    return [" / ".join(f'"{st[k]}"' for st in ANCHORS[scale]) for k in range(POINTS)]


def _jev_instructions(scale: str) -> str:
    return (f"The state is one simulated buyer's free-text answer to a survey question about {SCALE_TOPICS[scale]}. "
            "Pick the level whose example statements best match what the answer says, from the most negative "
            "(level 0) to the most positive (level 4).")


def _texts(items: Sequence[Tuple[str, str]]) -> List[Tuple[int, str, str]]:
    return [(i, scale, str(text).strip()) for i, (scale, text) in enumerate(items)
            if scale in ANCHORS and text is not None and str(text).strip()]


def rate_jev(items: Sequence[Tuple[str, str]], usage: Optional["jev.JevUsage"] = None, parallel: Optional[int] = None,
             env: Optional[Dict[str, str]] = None) -> Tuple[List[Optional[Dict[str, Any]]], Dict[str, Any]]:
    """[(scale, text)] -> (one {pmf, mean, sd, score10} or None per item, info). One Jev request per answer.
    info: model, rated, failed (answers sent but not rated), usage. Raises jev.JevUnavailable without a key."""
    usage = usage or jev.JevUsage()
    out: List[Optional[Dict[str, Any]]] = [None] * len(items)
    todo = _texts(items)
    jobs = [(text, {"rating": jev.score_question(jev_levels(scale), _jev_instructions(scale))}) for _, scale, text in todo]
    answers = jev.ask_many(jobs, parallel=parallel, usage=usage, env=env) if jobs else []
    models: Dict[str, int] = {}
    failed = 0
    for (i, _, _), res in zip(todo, answers):
        pmf = jev.score_pmf((res.get("answers") or {}).get("rating"), POINTS) if res.get("ok") else None
        if pmf is None:
            failed += 1
            continue
        out[i] = describe(pmf)
        models[res["model"]] = models.get(res["model"], 0) + 1
    model = max(models, key=models.get) if models else None
    return out, {"model": model, "rated": len(todo) - failed, "failed": failed, "usage": usage.snapshot()}


def rate_engine(items: Sequence[Tuple[str, str]], engine: Any = None, temperature: float = 1.0,
                env: Optional[Dict[str, str]] = None
                ) -> Tuple[List[Optional[Dict[str, Any]]], List[Optional[str]], Dict[str, Any]]:
    """[(scale, text)] -> (ratings, engine per item, info) with the chosen engine.

    info names the engine and the method that produced the distributions ("embeddings (<model>)", "jev (<model>)",
    or both for auto) and counts the answers each engine rated and the failures. The embeddings read the verdict
    clause, Jev the whole answer. Raises SSRUnavailable (embeddings) or jev.JevUnavailable (jev without a key)."""
    name = engine_name(engine, env)
    n_text = len(_texts(items))
    if name == "embeddings":
        rated = rate(items, temperature=temperature)
        model = getattr(get_embedder(), "model_name", None)
        n = sum(1 for r in rated if r)
        return rated, ["embeddings" if r else None for r in rated], {
            "engine": "embeddings", "method": f"embeddings ({model})" if model else "embeddings", "model": model,
            "input": "verdict clause", "counts": {"embeddings": n, "failed": n_text - n}}
    if name == "jev":
        rated, ji = rate_jev(items, env=env)
        return rated, ["jev" if r else None for r in rated], {
            "engine": "jev", "method": jev.method_label(ji["model"]), "model": ji["model"], "input": "full answer",
            "counts": {"jev": ji["rated"], "failed": ji["failed"]}, "usage": ji["usage"]}
    # auto: Jev when configured, the embeddings for every answer Jev did not rate
    jev_cfg = jev.settings(env)
    rated: List[Optional[Dict[str, Any]]] = [None] * len(items)
    ji: Dict[str, Any] = {}
    if jev_cfg["configured"]:
        rated, ji = rate_jev(items, env=env)
    engines: List[Optional[str]] = ["jev" if r else None for r in rated]
    rest = [i for i, _, _ in _texts(items) if rated[i] is None]
    emb_model, emb_error = None, None
    if rest:
        try:
            for i, r in zip(rest, rate([items[i] for i in rest], temperature=temperature)):
                if r:
                    rated[i], engines[i] = r, "embeddings"
            emb_model = getattr(get_embedder(), "model_name", None)
        except SSRUnavailable as e:
            emb_error = str(e)
    n_jev, n_emb = engines.count("jev"), engines.count("embeddings")
    parts = ([f"{jev.method_label(ji.get('model'))} for {n_jev}"] if n_jev else []) + \
            ([f"embeddings ({emb_model or 'local'}) for {n_emb}"] if n_emb else [])
    info: Dict[str, Any] = {
        "engine": "auto", "method": "auto: " + (", ".join(parts) if parts else "nothing rated"),
        "model": ji.get("model") if n_jev >= n_emb else emb_model, "jev_model": ji.get("model"),
        "embedding_model": emb_model, "input": {"jev": "full answer", "embeddings": "verdict clause"},
        "counts": {"jev": n_jev, "embeddings": n_emb, "failed": n_text - n_jev - n_emb, "jev_failed": ji.get("failed", 0)}}
    if ji.get("usage"):
        info["usage"] = ji["usage"]
    if not jev_cfg["configured"]:
        info["jev_unavailable"] = jev_cfg["reason"]
    if emb_error:
        info["embeddings_unavailable"] = emb_error
    return rated, engines, info
