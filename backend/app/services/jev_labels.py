"""Jev as an outside labeller: fixed-label judgments made after a run, by a model that did not play the people.

Jev (services/jev.py) answers typed `choice` questions with a confidence. It is used here only where a label is
applied after the fact, never where it would change what a simulated person says or hears:

  sentiment     replies and posts in the social feed (feed_story), and real voices from `research`, which are often
                Hindi, Tagalog or mixed-language text that a word list misreads
  drop causes   the free-text reasons people gave for leaving the landing page, grouped into ranked causes
  concerns      ad comments that carry no objection type (battlecard), and an independent check of the objection
                type each person gave in the sales pitch, next to their own tag

Mode: MM_JEV_LABELS = auto (default: on when a Jev key is set) | on | off. Without a key, or when off, callers keep
their existing labels (word lists, raw reasons, self-tags). A failed request leaves its text unlabelled; nothing is
guessed. Labels are cached by text in a JSON file next to the run, so a text is never paid for twice.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence

from . import jev

MODES = ("auto", "on", "off")

# Concern types as Jev `choice` criteria: the same labels the model classifier returns (shared with search_and_geo)
CONCERN_CRITERIA = {
    "price": "Cost or value for money, or doubt that it is really free",
    "trust": "Doubt that it is legitimate, safe or honest; fear of a scam or a hidden catch",
    "relevance": "It does not fit the person's needs or situation",
    "effort": "Too much time, work or hassle to start or to use",
    "timing": "Not the right time; maybe later",
    "unclear": "Not clear what it is, what it does or what happens next",
    "privacy": "Worry about personal data, tracking or being contacted",
    "competitor": "Already uses or prefers another product or a free alternative",
    "authority": "Needs someone else's approval or advice before deciding",
    "habit": "Content with the current way of doing things and does not want to change",
    "other": "A concern that fits none of the other types",
    "none": "No concern: praise, a plain description or an unrelated remark",
}
JEV_CONCERN_INSTRUCTIONS = ("The state is a short text from a market study, quoted exactly. Pick the one concern it "
                            "mainly expresses, or none when it expresses no concern.")

SENTIMENT_CRITERIA = {
    "pos": "Positive: likes it, agrees, is pleased, excited, grateful or recommends it",
    "neg": "Negative: dislikes it, disagrees, is annoyed, worried, sarcastic or warns others",
    "neu": "Neutral or mixed: a question, a plain fact, an unrelated remark, or both good and bad in equal measure",
}
SENTIMENT_INSTRUCTIONS = ("The state is a short post, reply or review, quoted exactly; it may be in any language or "
                          "mix languages. Pick the overall feeling the writer expresses toward the subject.")

DROP_CRITERIA = {
    "price": "The price, a fee, or being asked to pay or enter a card",
    "trust": "Doubt that the page or company is legitimate or safe",
    "form": "The form is too long or asks for too much: phone number, personal details, a sign-up",
    "speed": "The page was slow, broken, showed an error or asked for a code that did not work",
    "unclear": "Could not tell what it is, what they get or what happens next",
    "relevance": "It is not for them or does not fit their need",
    "not_now": "Not the right time; would come back later",
    "other": "A reason that fits none of the other types",
}
DROP_INSTRUCTIONS = ("The state is one person's reason for leaving a landing page without signing up, in their own "
                     "words. Pick the main cause.")


def mode(value: Any = None, env: Optional[Dict[str, str]] = None) -> str:
    env = os.environ if env is None else env
    m = str(value if value is not None else env.get("MM_JEV_LABELS") or "auto").strip().lower()
    return m if m in MODES else "auto"


def enabled(value: Any = None, env: Optional[Dict[str, str]] = None) -> bool:
    """True when Jev labels should be used: mode on or auto, and a Jev key is configured."""
    return mode(value, env) != "off" and jev.available()


def jev_label_texts(texts: List[str], criteria: Dict[str, str], instructions: str,
                    usage: Optional[jev.JevUsage] = None, parallel: Optional[int] = None) -> List[Dict[str, Any]]:
    """One Jev `choice` question per text -> [{ok, label, confidence, model, error}] in order. A failed request, or a
    choice outside the criteria, stays unlabelled. Raises jev.JevUnavailable without a key."""
    jobs = [(t, {"label": jev.choice_question(criteria, instructions)}) for t in texts]
    out = []
    for r in jev.ask_many(jobs, parallel=parallel, usage=usage) if jobs else []:
        ans = (r.get("answers") or {}).get("label") if r.get("ok") else None
        label = jev.choice_label(ans, list(criteria))
        out.append({"ok": label is not None, "label": label, "model": r.get("model"),
                    "confidence": ans.get("confidence") if isinstance(ans, dict) else None,
                    "error": r.get("error") or (None if label else "Jev chose a label outside the criteria")})
    return out


# --------------------------------------------------------------------------
# cached labelling
# --------------------------------------------------------------------------

CACHE_FILE = "jev_labels.json"
_lock = threading.Lock()


def _key(kind: str, text: str) -> str:
    return hashlib.sha1(f"{kind}\n{' '.join(str(text).split())}".encode("utf-8")).hexdigest()


def _load(path: Optional[str]) -> Dict[str, Any]:
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(path: Optional[str], data: Dict[str, Any]) -> None:
    if not path:
        return
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        pass


KINDS = {"sentiment": (SENTIMENT_CRITERIA, SENTIMENT_INSTRUCTIONS),
         "drop": (DROP_CRITERIA, DROP_INSTRUCTIONS),
         "concern": (CONCERN_CRITERIA, JEV_CONCERN_INSTRUCTIONS)}


def label(texts: Sequence[str], kind: str, cache_path: Optional[str] = None,
          usage: Optional[jev.JevUsage] = None) -> List[Optional[Dict[str, Any]]]:
    """Labels for texts (same order): {label, confidence, model} or None when Jev failed on that text. Texts already
    in the cache are not sent again; identical texts are sent once."""
    criteria, instructions = KINDS[kind]
    texts = [str(t or "")[:1200] for t in texts]
    with _lock:
        cache = _load(cache_path)
    todo = sorted({_key(kind, t): t for t in texts if t.strip() and _key(kind, t) not in cache}.items())
    if todo:
        got = jev_label_texts([t for _, t in todo], criteria, instructions, usage)
        fresh = {k: {"label": g["label"], "confidence": g["confidence"], "model": g["model"]}
                 for (k, _), g in zip(todo, got) if g["ok"]}
        if fresh:
            with _lock:
                cache = {**_load(cache_path), **fresh}
                _save(cache_path, cache)
        cache = {**cache, **fresh}
    return [cache.get(_key(kind, t)) if t.strip() else None for t in texts]


def method(labels: Sequence[Optional[Dict[str, Any]]]) -> str:
    models = Counter(x["model"] for x in labels if x and x.get("model"))
    return jev.method_label(models.most_common(1)[0][0] if models else None)


# --------------------------------------------------------------------------
# uses
# --------------------------------------------------------------------------

def sentiment_labeler(cache_path: Optional[str] = None):
    """texts -> 'pos' | 'neg' | 'neu' or None per text, by Jev (cached). After a call, `method_name` names the model,
    for feed_story.build_feed_story(labeler=...) and research.run(labeler=...)."""
    def lab(texts: List[str]) -> List[Optional[str]]:
        try:
            got = label(texts, "sentiment", cache_path)
        except Exception:  # noqa: BLE001 - no key or Jev down: every text keeps its word-list label
            got = [None] * len(texts)
        lab.method_name = method(got)
        return [x["label"] if x else None for x in got]
    lab.method_name = None
    return lab


def drop_causes(result: Dict[str, Any], cache_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Landing-page drop reasons from a feed test grouped into ranked causes, overall and per ad."""
    rows = [(s.get("creative_id"), str((s.get("landing") or {}).get("drop_reason") or "").strip())
            for s in result.get("sessions") or [] if isinstance(s, dict)]
    rows = [(cid, r) for cid, r in rows if r]
    if not rows:
        return None
    labs = label([r for _, r in rows], "drop", cache_path)

    def rank(pairs):
        c = Counter(lab["label"] for (_, _), lab in pairs if lab)
        n = sum(c.values())
        out = []
        for cause, k in c.most_common():
            ex = [r for (_, r), lab in pairs if lab and lab["label"] == cause][:2]
            out.append({"cause": cause, "count": k, "share_pct": round(100.0 * k / n, 1) if n else 0.0, "examples": ex})
        return out
    pairs = list(zip(rows, labs))
    per = {}
    for cid in sorted({cid for cid, _ in rows if cid is not None}, key=str):
        per[str(cid)] = rank([(row, lab) for row, lab in pairs if row[0] == cid])
    return {"overall": rank(pairs), "per_creative": per, "reasons": len(rows),
            "labelled": sum(1 for x in labs if x), "method": method(labs),
            "note": "Simulated people's reasons, grouped by Jev; counts are simulated."}


def label_concerns(items: List[Dict[str, Any]], cache_path: Optional[str] = None) -> int:
    """Fill an empty `type` on objection items (e.g. ad comments) with Jev's concern label; returns how many."""
    todo = [it for it in items if not it.get("type") and str(it.get("text") or "").strip()]
    if not todo:
        return 0
    labs = label([it["text"] for it in todo], "concern", cache_path)
    n = 0
    for it, lab in zip(todo, labs):
        if lab and lab["label"] != "none":
            it["type"], it["type_by"] = lab["label"], "jev"
            n += 1
    return n


def pitch_objection_check(result: Dict[str, Any], types: Sequence[str]) -> Optional[Dict[str, Any]]:
    """Jev labels each objection raised in the pitch with the same types the buyer tagged it with; agreement with the
    buyer's own tag (Wilson 95% range). The buyer's tag still decides which rebuttal was played."""
    from .search_and_geo import run_objection_check   # lazy: search_and_geo imports the GTM services
    items = [{"id": r.get("agent_id"), "text": (r.get("turn1") or {}).get("objection"),
              "self_tag": (r.get("turn1") or {}).get("objection_type")}
             for r in result.get("people") or [] if isinstance(r, dict) and (r.get("turn1") or {}).get("objection")]
    if not items:
        return None
    criteria = {t: CONCERN_CRITERIA.get(t, {"language": "The language or wording is a barrier: hard to read or "
                                                        "not in their language"}.get(t, t)) for t in types}
    return run_objection_check(items, criteria)
