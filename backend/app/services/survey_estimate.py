"""Segment-level answer distributions, asked for directly, as a second estimate next to the per-person survey.

The survey asks every simulated person and maps each free-text answer to a 1-5 distribution (SSR). Two findings say
that alone is not enough:
- asked one by one, instruction-tuned models give answers that are too alike, so per-person sampling reproduces
  human answer distributions worse than asking a model to describe the distribution directly (Jang, Kim & Lee 2026,
  arXiv 2607.25292: total variation 0.22 describing vs 0.46 sampling on OpinionQA; preprint);
- simulated respondents are under-dispersed (Peng, Gui, Toubia et al. 2025, arXiv 2509.19088: 154 of 164 outcomes).

So for each audience segment one call describes how that segment's answers would spread over the five verdicts on
the four survey scales (interest, trust, purchase, recommend). It is asked twice, once with the verdicts in each
order, and averaged (option order moves answers: Dominguez-Olmedo et al., NeurIPS 2024). `blend` puts it next to
the pooled per-person SSR distribution: their average is the blended estimate and their distance is shown as an
extra margin: when the two methods disagree, neither should be read to the point.

Both are simulated. Neither is a measured share of real buyers.

Stdlib only.
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

VERSION = 1
LEVELS = ["No", "Probably not", "Maybe", "Probably yes", "Yes, definitely"]
SCALES = {
    "interest": "Are they interested in it?",
    "trust": "Do they trust it?",
    "purchase": "Would they actually {goal}?",
    "recommend": "Would they tell a friend or family member about it?",
}
MAX_CARDS = 8

Complete = Callable[[str, str], Tuple[str, Dict[str, Any]]]

SYSTEM = ("You are a market researcher who knows how real people answer surveys: answers spread out, few people are "
          "certain, and polite enthusiasm is rarer than models assume. You describe distributions of answers; you do not "
          "role-play one person. Reply with JSON only.")


def person_card(p: Dict[str, Any]) -> str:
    bits = [str(p.get(k)) for k in ("age", "gender", "occupation", "city", "country") if p.get(k)]
    bde = p.get("bde") if isinstance(p.get("bde"), dict) else {}
    ev = bde.get("evaluation") if isinstance(bde.get("evaluation"), dict) else {}
    who = ((bde.get("background") or {}).get("who") if isinstance(bde.get("background"), dict) else "") or ""
    extra = "; ".join(x for x in (who, ", ".join(ev.get("dealbreakers") or [])[:120]) if x)
    return ", ".join(bits) + (f" ({extra[:220]})" if extra else "")


def prompt(segment: str, people: List[Dict[str, Any]], offer: str, goal: str, reverse: bool = False,
           message: str = "") -> Tuple[str, str]:
    levels = list(reversed(LEVELS)) if reverse else LEVELS
    cards = "\n".join(f"- {person_card(p)}" for p in people[:MAX_CARDS]) or "- (no profiles)"
    goal_txt = goal or "take the action the offer asks for"
    qs = "\n".join(f"- {k}: {q.format(goal=goal_txt)}" for k, q in SCALES.items())
    schema = {k: {lv: 0.0 for lv in levels} for k in SCALES}
    schema["why"] = "one sentence"
    user = (f"Audience segment: {segment} ({len(people)} people). Some of them:\n{cards}\n\n"
            f"What they are asked about: {offer or 'the offer'}" + (f'\nThe message they saw: "{message}"' if message else "")
            + f"\n\nFor each question, give the share of this segment (0-1, adding to 1) who would answer each verdict, in "
            f"this order: {' / '.join(levels)}.\n{qs}\n\nReply with only this JSON:\n{json.dumps(schema)}")
    return SYSTEM, user


def _json_block(text: str) -> Any:
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    a, b = text.find("{"), text.rfind("}")
    if a != -1 and b > a:
        try:
            return json.loads(text[a:b + 1])
        except ValueError:
            return None
    return None


def parse_pmf(raw: Any) -> Optional[List[float]]:
    """{verdict: share} (any order) or a 5-list (No..Yes) -> a normalised 5-point pmf, or None."""
    if isinstance(raw, dict):
        norm = {re.sub(r"[^a-z]", "", str(k).lower()): v for k, v in raw.items()}
        vals = [norm.get(re.sub(r"[^a-z]", "", lv.lower())) for lv in LEVELS]
    elif isinstance(raw, list) and len(raw) == 5:
        vals = raw
    else:
        return None
    try:
        xs = [max(0.0, float(v)) for v in vals]
    except (TypeError, ValueError):
        return None
    tot = sum(xs)
    if tot <= 0:
        return None
    return [x / tot for x in xs]


def mean_of(pmf: Sequence[float]) -> float:
    return sum((k + 1) * p for k, p in enumerate(pmf))


def tv(a: Sequence[float], b: Sequence[float]) -> float:
    return 0.5 * sum(abs(x - y) for x, y in zip(a, b))


def describe_segment(segment: str, people: List[Dict[str, Any]], offer: str, goal: str, complete: Complete,
                     message: str = "") -> Tuple[Dict[str, Any], Dict[str, int]]:
    """Two calls (both verdict orders), averaged per scale. A scale neither call answered is left out."""
    usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
    got: Dict[str, List[List[float]]] = {k: [] for k in SCALES}
    why = []
    for reverse in (False, True):
        try:
            text, u = complete(*prompt(segment, people, offer, goal, reverse, message))
        except Exception:  # noqa: BLE001 - one failed order leaves the other
            continue
        usage["calls"] += 1
        for k in ("input_tokens", "output_tokens"):
            usage[k] += int((u or {}).get(k) or 0)
        d = _json_block(text)
        if not isinstance(d, dict):
            continue
        if d.get("why"):
            why.append(str(d["why"])[:200])
        for scale in SCALES:
            pmf = parse_pmf(d.get(scale))
            if pmf:
                got[scale].append(pmf)
    out: Dict[str, Any] = {"n_people": len(people), "orders": usage["calls"]}
    for scale, pmfs in got.items():
        if pmfs:
            avg = [sum(p[k] for p in pmfs) / len(pmfs) for k in range(5)]
            out[scale] = {"pmf": [round(x, 3) for x in avg], "mean": round(mean_of(avg), 2),
                          "order_gap": round(tv(pmfs[0], pmfs[1]), 3) if len(pmfs) == 2 else None}
    if why:
        out["why"] = why[0]
    return out, usage


def run(segments: Dict[str, List[Dict[str, Any]]], offer: str, goal: str, complete: Complete, message: str = "",
        parallel: int = 4) -> Dict[str, Any]:
    names = sorted(segments)

    def one(name):
        return name, *describe_segment(name, segments[name], offer, goal, complete, message)
    with ThreadPoolExecutor(max_workers=max(1, min(parallel, len(names) or 1))) as pool:
        results = list(pool.map(one, names))
    usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
    by = {}
    for name, res, u in results:
        by[name] = res
        for k in usage:
            usage[k] += u.get(k, 0)
    return {"version": VERSION, "method": "segment-level described distributions, both verdict orders averaged",
            "by_segment": by, "usage": usage}


def uniform_gap(pmf: Sequence[float]) -> float:
    return tv(pmf, [0.2] * 5)


def blend(ssr_pmf: Optional[Sequence[float]], described: Optional[Sequence[float]]) -> Optional[Dict[str, Any]]:
    """The two estimates side by side: their average, their distance (an extra margin) and the mean of each."""
    if not ssr_pmf and not described:
        return None
    if not ssr_pmf or not described:
        only = list(ssr_pmf or described)
        return {"pmf": [round(x, 3) for x in only], "mean": round(mean_of(only), 2), "methods": 1,
                "source": "ssr" if ssr_pmf else "described"}
    avg = [(a + b) / 2 for a, b in zip(ssr_pmf, described)]
    return {"pmf": [round(x, 3) for x in avg], "mean": round(mean_of(avg), 2), "methods": 2,
            "ssr_mean": round(mean_of(ssr_pmf), 2), "described_mean": round(mean_of(described), 2),
            "method_gap": round(tv(ssr_pmf, described), 3),
            "mean_margin": round(abs(mean_of(ssr_pmf) - mean_of(described)) / 2, 2)}
