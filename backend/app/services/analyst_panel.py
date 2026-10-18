"""
Independent analyst panel.

Several analyst agents, each with a different professional lens, read the same
anonymized material (posts, comments, feed-test reactions, survey answers) and
work alone: no analyst sees another's output. The panel then reports where they
agree (best audience, best message, top themes, sentiment) and how strongly,
which is a cheap robustness check on any single reading of the simulation.

Material is anonymized before it reaches the analysts: only segment labels and
text, never persona names.
"""

from __future__ import annotations

import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from statistics import mean, pstdev
from typing import Any, Callable, Dict, List, Optional

from ..utils.logger import get_logger
from ..utils.openai_chat_compat import create_chat_completion, extract_chat_completion_text
from .persona_planner import parse_json_block

logger = get_logger('mirofish.analyst_panel')

LENSES = [
    ("Performance marketer", "You care about what will drive clicks and conversions at a good cost per result."),
    ("Brand strategist", "You care about positioning, trust, distinctiveness and long-term brand health."),
    ("Sales lead", "You care about objections, buying triggers, who the real decision maker is and how to close."),
    ("Consumer psychologist", "You look for motivations, fears, social proof and the emotions behind reactions."),
    ("Sceptical data analyst", "You distrust small samples and over-reading; you flag what the evidence cannot support."),
    ("Local market expert", "You know how culture, language, money and family shape decisions in each country."),
    ("Copywriter", "You judge which words and hooks land, and rewrite what does not."),
    ("Product manager", "You look for what the product or offer itself must change, not just the messaging."),
    ("Customer success lead", "You think about what happens after sign-up: expectations, churn risks, word of mouth."),
]

SYSTEM = (
    "You are an independent analyst reviewing results from a simulated market test. You work alone and have "
    "not seen any other analyst's view. Base every claim on the material; quote it as evidence. Say when the "
    "evidence is thin. The people in the material are simulated personas, identified only by audience segment. "
    "Return only valid JSON."
)

MAX_ITEMS = {"posts": 120, "comments": 200, "feed_comments": 200, "survey": 300}


def normalize_material(m: Any) -> Dict[str, Any]:
    if not isinstance(m, dict):
        raise ValueError("material must be an object with posts/comments/feed_comments/survey lists")
    out: Dict[str, Any] = {"context": str(m.get("context") or "")[:3000]}
    total = 0
    for key, cap in MAX_ITEMS.items():
        rows = []
        for r in (m.get(key) or [])[:cap]:
            if isinstance(r, str):
                r = {"text": r}
            if not isinstance(r, dict):
                continue
            text = str(r.get("text") or r.get("quote") or "").strip()
            if not text:
                continue
            rows.append({"segment": str(r.get("segment") or "unknown")[:80], "text": text[:500],
                         **({"extra": str(r.get("extra"))[:200]} if r.get("extra") else {})})
        out[key] = rows
        total += len(rows)
    if not total:
        raise ValueError("material has no text to analyse")
    return out


def _render(material: Dict[str, Any]) -> str:
    parts = []
    labels = {"posts": "Posts written during the simulation", "comments": "Comments during the simulation",
              "feed_comments": "Comments and reactions on the test ads (feed test)",
              "survey": "Buyer survey answers"}
    for key, label in labels.items():
        rows = material.get(key) or []
        if rows:
            parts.append(f"## {label} ({len(rows)})\n" + "\n".join(
                f"- [{r['segment']}] {r['text']}" + (f" ({r['extra']})" if r.get("extra") else "") for r in rows))
    return "\n\n".join(parts)


def _prompt(lens: str, focus: str, brief: str, material: Dict[str, Any]) -> str:
    return (
        f"Your lens: {lens}. {focus}\n\n"
        f"What the client wants to decide:\n{brief or 'Which audience and message to invest in, and what is blocking conversion.'}\n\n"
        + (f"Background:\n{material['context']}\n\n" if material.get("context") else "")
        + _render(material) + "\n\n"
        "Return JSON: {\"headline\": \"your single most important conclusion\", \"sentiment\": -100..100, "
        "\"purchase_intent_signal\": 0-10, \"best_audience\": \"segment name or 'unclear'\", "
        "\"best_message\": \"which message/ad/angle wins, or 'unclear'\", "
        "\"themes\": [{\"theme\": \"2-5 words\", \"weight\": 0-10, \"evidence\": \"short quote\"}], "
        "\"objections\": [\"...\"], \"opportunities\": [\"...\"], \"risks\": [\"...\"], "
        "\"recommendation\": \"what to do next, 1-2 sentences\", \"confidence\": 0-10, "
        "\"evidence_gaps\": \"what you would need to be more sure\"}"
    )


def _norm_key(s: Any) -> str:
    return re.sub(r"[^a-z0-9#]+", " ", str(s or "").lower()).strip()


def _clean(r: Dict[str, Any]) -> Dict[str, Any]:
    def num(v, lo, hi):
        try:
            return max(lo, min(hi, float(v)))
        except (TypeError, ValueError):
            return None
    themes = [t for t in (r.get("themes") or []) if isinstance(t, dict) and t.get("theme")]
    return {
        "headline": str(r.get("headline") or "")[:400],
        "sentiment": num(r.get("sentiment"), -100, 100),
        "purchase_intent_signal": num(r.get("purchase_intent_signal"), 0, 10),
        "best_audience": str(r.get("best_audience") or "unclear")[:120],
        "best_message": str(r.get("best_message") or "unclear")[:200],
        "themes": [{"theme": str(t["theme"])[:60], "weight": num(t.get("weight"), 0, 10) or 0,
                    "evidence": str(t.get("evidence") or "")[:240]} for t in themes[:8]],
        "objections": [str(x)[:200] for x in (r.get("objections") or [])][:6],
        "opportunities": [str(x)[:200] for x in (r.get("opportunities") or [])][:6],
        "risks": [str(x)[:200] for x in (r.get("risks") or [])][:5],
        "recommendation": str(r.get("recommendation") or "")[:500],
        "confidence": num(r.get("confidence"), 0, 10),
        "evidence_gaps": str(r.get("evidence_gaps") or "")[:400],
    }


def _vote(values: List[str]) -> Dict[str, Any]:
    keys = [_norm_key(v) for v in values if v and _norm_key(v) not in ("unclear", "")]
    if not keys:
        return {"winner": None, "agreement": None, "votes": {}}
    counts = Counter(keys)
    winner, n = counts.most_common(1)[0]
    original = next(v for v in values if _norm_key(v) == winner)
    return {"winner": original, "agreement": round(100 * n / len(values)), "votes": dict(counts)}


def aggregate(analysts: List[Dict[str, Any]]) -> Dict[str, Any]:
    ok = [a for a in analysts if a.get("result")]
    res = [a["result"] for a in ok]
    sent = [r["sentiment"] for r in res if r["sentiment"] is not None]
    intent = [r["purchase_intent_signal"] for r in res if r["purchase_intent_signal"] is not None]
    theme_hits: Dict[str, Dict[str, Any]] = {}
    for a in ok:
        for t in a["result"]["themes"]:
            words = set(_norm_key(t["theme"]).split())
            match = next((k for k, v in theme_hits.items()
                          if words and v["words"] and len(words & v["words"]) / min(len(words), len(v["words"])) >= 0.5),
                         None)
            if match is None:
                match = t["theme"]
                theme_hits[match] = {"words": words, "analysts": set(), "weight": [], "evidence": []}
            theme_hits[match]["analysts"].add(a["id"])
            theme_hits[match]["weight"].append(t["weight"])
            if t["evidence"]:
                theme_hits[match]["evidence"].append(t["evidence"])
    themes = sorted([{"theme": k, "analysts": len(v["analysts"]), "share": round(100 * len(v["analysts"]) / max(len(ok), 1)),
                      "weight": round(mean(v["weight"]), 1) if v["weight"] else 0, "evidence": v["evidence"][:3]}
                     for k, v in theme_hits.items()], key=lambda x: (-x["analysts"], -x["weight"]))
    audience, message = _vote([r["best_audience"] for r in res]), _vote([r["best_message"] for r in res])
    spread = pstdev(sent) if len(sent) > 1 else 0
    consensus = "strong" if (audience["agreement"] or 0) >= 70 and spread <= 25 else \
        "partial" if (audience["agreement"] or 0) >= 50 else "weak"
    return {
        "analysts_ok": len(ok), "analysts_failed": len(analysts) - len(ok),
        "sentiment_mean": round(mean(sent)) if sent else None, "sentiment_spread": round(spread) if sent else None,
        "intent_mean": round(mean(intent), 1) if intent else None,
        "confidence_mean": round(mean([r["confidence"] for r in res if r["confidence"] is not None]), 1)
        if any(r["confidence"] is not None for r in res) else None,
        "best_audience": audience, "best_message": message, "themes": themes[:12], "consensus": consensus,
    }


def run_panel(client, model: str, material: Dict[str, Any], brief: str = "", n: int = 5,
              progress: Optional[Callable[[int, int], None]] = None) -> Dict[str, Any]:
    lenses = LENSES[:max(2, min(n, len(LENSES)))]
    done = [0]

    def one(i_lens):
        i, (lens, focus) = i_lens
        try:
            resp = create_chat_completion(client, model=model, temperature=0.6, max_tokens=2500,
                                          messages=[{"role": "system", "content": SYSTEM},
                                                    {"role": "user", "content": _prompt(lens, focus, brief, material)}])
            data = parse_json_block(extract_chat_completion_text(resp))
            result = _clean(data if isinstance(data, dict) else {})
            err = None
        except Exception as e:  # noqa: BLE001 - one analyst failing is reported, not fatal
            logger.warning(f"analyst {lens} failed: {e}")
            result, err = None, str(e)[:200]
        done[0] += 1
        if progress:
            progress(done[0], len(lenses))
        return {"id": f"Analyst {chr(65 + i)}", "lens": lens, "result": result, "error": err}

    with ThreadPoolExecutor(max_workers=len(lenses)) as pool:
        analysts = list(pool.map(one, enumerate(lenses)))
    return {"brief": brief, "material_counts": {k: len(material.get(k) or []) for k in MAX_ITEMS},
            "analysts": analysts, "consensus": aggregate(analysts)}
