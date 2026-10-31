"""Choice methods on simulated buyers: MaxDiff, choice-based conjoint (CBC) and Gabor-Granger pricing.

The survey already has Van Westendorp and the GTM lab a single tier choice. Missing were the three methods market
researchers use most when a list or a price has to be decided:

maxdiff        rank 6-20 claims, features or benefits: each person sees sets of 4 and picks the most and the least
               important; best-minus-worst counts per item with bootstrap intervals over people.
conjoint       which attributes drive choice: each person chooses among 3 product profiles (or none) in several tasks;
               a multinomial logit gives part-worths and attribute importance, and, when a price attribute is numeric,
               a willingness-to-pay *direction*.
gabor_granger  a demand curve: each person says yes / no to the product at each price (in a random order); the share
               who buy at each price and the revenue-maximising price on that curve.

Evidence and limits: LLM conjoint recovers realistic *directions* but willingness to pay is often off and sometimes
wrong-signed (Brand, Israeli & Ngwe, SSRN 4395751), and changing only the price makes models infer other changes
(Gui & Toubia, arXiv 2312.15524). So every task states that everything else is held fixed, WTP is labelled
"direction only", and all shares are simulated.

Stdlib only; `complete(system, user) -> (text, usage)` is injected.
"""

from __future__ import annotations

import json
import math
import random
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

VERSION = 1
Complete = Callable[[str, str], Tuple[str, Dict[str, Any]]]
SYSTEM = ("You are this person answering a short market-research exercise. Answer as yourself, from your own needs and "
          "budget; it is fine to choose none. Reply with JSON only.")


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


def person_text(p: Dict[str, Any]) -> str:
    who = ", ".join(str(p[k]) for k in ("age", "gender", "occupation", "city", "country") if p.get(k))
    return f"{p.get('name') or 'A person'}{f' ({who})' if who else ''}. {str(p.get('persona') or '')[:1500]}"


def _price_num(v: Any) -> Optional[float]:
    m = re.search(r"\d+(?:[.,]\d+)?", str(v).replace(",", ""))
    return float(m.group(0)) if m else None


# --------------------------------------------------------------------------
# MaxDiff
# --------------------------------------------------------------------------

def maxdiff_design(items: Sequence[str], per_set: int = 4, sets: Optional[int] = None, seed: int = 7) -> List[List[int]]:
    """Sets of item indices; every item appears about equally often and never twice in a set."""
    n = len(items)
    if n < 3:
        raise ValueError("MaxDiff needs at least 3 items")
    per_set = max(2, min(per_set, n))
    sets = sets or max(3, math.ceil(3 * n / per_set))
    rng = random.Random(seed)
    seq: List[int] = []
    while len(seq) < sets * per_set:
        block = list(range(n))
        rng.shuffle(block)
        seq += block
    out: List[List[int]] = []
    for _ in range(sets):
        chunk: List[int] = []
        i = 0
        while len(chunk) < per_set and i < len(seq):
            if seq[i] not in chunk:
                chunk.append(seq.pop(i))
            else:
                i += 1
        out.append(chunk)
    return out


def maxdiff_prompt(items: Sequence[str], design: List[List[int]], topic: str) -> str:
    blocks = "\n".join(f"Set {k + 1}: " + " | ".join(f"{j + 1}) {items[i]}" for j, i in enumerate(s)) for k, s in enumerate(design))
    return (f"About {topic or 'this product'}: in each set, which one matters MOST to you and which one matters LEAST?\n"
            f"{blocks}\n\nReply: " + '{"sets": [{"most": number, "least": number}, ...]} with the numbers inside each set.')


def maxdiff_parse(text: str, design: List[List[int]]) -> List[Tuple[int, int]]:
    d = _json_block(text)
    out = []
    for s, r in zip(design, (d or {}).get("sets") or []):
        try:
            most, least = int(r.get("most")), int(r.get("least"))
        except (TypeError, ValueError, AttributeError):
            continue
        if 1 <= most <= len(s) and 1 <= least <= len(s) and most != least:
            out.append((s[most - 1], s[least - 1]))
    return out


def maxdiff_scores(items: Sequence[str], answers: List[Dict[str, Any]], design: List[List[int]],
                   boot: int = 300, seed: int = 11) -> List[Dict[str, Any]]:
    """answers: [{segment, picks: [(best, worst)]}] -> per item best-minus-worst share of appearances, with a
    95% bootstrap interval over people, sorted best first."""
    shown = [0] * len(items)
    for s in design:
        for i in s:
            shown[i] += 1

    def score(rows):
        b, w = [0] * len(items), [0] * len(items)
        for a in rows:
            for best, worst in a["picks"]:
                b[best] += 1
                w[worst] += 1
        n = max(1, len(rows))
        return [(b[i] - w[i]) / (shown[i] * n) if shown[i] else 0.0 for i in range(len(items))], b, w
    base, b, w = score(answers)
    rng = random.Random(seed)
    draws = [score([rng.choice(answers) for _ in answers])[0] for _ in range(boot)] if answers else []
    out = []
    for i, it in enumerate(items):
        xs = sorted(d[i] for d in draws)
        lo, hi = (xs[int(0.025 * (len(xs) - 1))], xs[int(0.975 * (len(xs) - 1))]) if xs else (None, None)
        out.append({"item": it, "score": round(base[i], 3), "best": b[i], "worst": w[i],
                    "ci": [round(lo, 3), round(hi, 3)] if lo is not None else None})
    return sorted(out, key=lambda r: -r["score"])


# --------------------------------------------------------------------------
# Choice-based conjoint
# --------------------------------------------------------------------------

def cbc_design(attributes: Dict[str, List[str]], tasks: int = 8, alts: int = 3, seed: int = 7) -> List[List[Dict[str, str]]]:
    """Random tasks of `alts` distinct profiles; each level of each attribute is shown about equally often."""
    if len(attributes) < 2 or any(len(v) < 2 for v in attributes.values()):
        raise ValueError("conjoint needs 2+ attributes with 2+ levels each")
    rng = random.Random(seed)
    queues: Dict[str, List[str]] = {a: [] for a in attributes}

    def draw(a):
        if not queues[a]:
            queues[a] = list(attributes[a])
            rng.shuffle(queues[a])
        return queues[a].pop()
    out = []
    for _ in range(tasks):
        task: List[Dict[str, str]] = []
        tries = 0
        while len(task) < alts and tries < 50:
            tries += 1
            prof = {a: draw(a) for a in attributes}
            if prof not in task:
                task.append(prof)
        out.append(task)
    return out


def cbc_prompt(design: List[List[Dict[str, str]]], topic: str, held_fixed: str = "") -> str:
    blocks = []
    for k, task in enumerate(design):
        opts = "\n".join(f"  Option {j + 1}: " + "; ".join(f"{a}: {v}" for a, v in prof.items()) for j, prof in enumerate(task))
        blocks.append(f"Task {k + 1}:\n{opts}")
    return (f"Choosing {topic or 'a product'}. Everything not listed is the same across options"
            + (f" ({held_fixed})" if held_fixed else "") + ". In each task pick the option you would actually buy, or 0 "
            "for none of them.\n" + "\n".join(blocks) + '\n\nReply: {"choices": [number or 0, ...]} one per task.')


def cbc_parse(text: str, design: List[List[Dict[str, str]]]) -> List[Optional[int]]:
    d = _json_block(text)
    out: List[Optional[int]] = []
    for task, c in zip(design, (d or {}).get("choices") or []):
        try:
            k = int(c)
        except (TypeError, ValueError):
            continue
        out.append(k - 1 if 1 <= k <= len(task) else None)
    return out


def _features(prof: Dict[str, str], attributes: Dict[str, List[str]]) -> List[float]:
    x = []
    for a, levels in attributes.items():
        x += [1.0 if prof.get(a) == lv else 0.0 for lv in levels[1:]]      # first level = reference
    return x + [0.0]                                                         # last: the "none" constant


def mnl_fit(observations: List[Tuple[List[Dict[str, str]], Optional[int]]], attributes: Dict[str, List[str]],
            steps: int = 400, lr: float = 0.5, l2: float = 0.01) -> Dict[str, Any]:
    """Multinomial logit with a none option, by gradient ascent (L2-regularised): part-worths per level
    (reference level = 0), the none constant, and attribute importance (range share)."""
    k = sum(len(v) - 1 for v in attributes.values()) + 1
    beta = [0.0] * k
    data = []
    for task, chosen in observations:
        xs = [_features(p, attributes) for p in task] + [[0.0] * (k - 1) + [1.0]]
        data.append((xs, len(task) if chosen is None else chosen))
    n = max(1, len(data))
    for _ in range(steps):
        grad = [0.0] * k
        for xs, y in data:
            us = [sum(b * v for b, v in zip(beta, x)) for x in xs]
            m = max(us)
            es = [math.exp(u - m) for u in us]
            z = sum(es)
            for j, x in enumerate(xs):
                p = es[j] / z
                for d in range(k):
                    grad[d] += ((1.0 if j == y else 0.0) - p) * x[d]
        beta = [b + lr * (g / n - l2 * b) for b, g in zip(beta, grad)]
    pw: Dict[str, Dict[str, float]] = {}
    i = 0
    for a, levels in attributes.items():
        pw[a] = {levels[0]: 0.0}
        for lv in levels[1:]:
            pw[a][lv] = round(beta[i], 3)
            i += 1
    ranges = {a: max(v.values()) - min(v.values()) for a, v in pw.items()}
    tot = sum(ranges.values()) or 1.0
    return {"part_worths": pw, "none": round(beta[-1], 3),
            "importance": {a: round(r / tot, 3) for a, r in sorted(ranges.items(), key=lambda kv: -kv[1])},
            "observations": len(data)}


def wtp_direction(fit: Dict[str, Any], price_attr: Optional[str]) -> Optional[Dict[str, Any]]:
    """Utility per currency unit from the price levels (least squares), and each level's value in money: a direction,
    not a measured willingness to pay."""
    if not price_attr or price_attr not in fit["part_worths"]:
        return None
    pts = [(_price_num(lv), u) for lv, u in fit["part_worths"][price_attr].items()]
    pts = [(p, u) for p, u in pts if p is not None]
    if len(pts) < 2:
        return None
    mp, mu = sum(p for p, _ in pts) / len(pts), sum(u for _, u in pts) / len(pts)
    var = sum((p - mp) ** 2 for p, _ in pts)
    slope = sum((p - mp) * (u - mu) for p, u in pts) / var if var else 0.0
    out = {"utility_per_unit": round(slope, 4), "sign_ok": slope < 0,
           "note": "direction only: LLM willingness to pay is often off and sometimes wrong-signed"}
    if slope < 0:
        out["levels"] = {a: {lv: round(-u / slope, 2) for lv, u in v.items()}
                         for a, v in fit["part_worths"].items() if a != price_attr}
    return out


# --------------------------------------------------------------------------
# Gabor-Granger
# --------------------------------------------------------------------------

def gg_prompt(prices: List[str], topic: str, order: List[int]) -> str:
    lines = "\n".join(f"{k + 1}) {prices[i]}" for k, i in enumerate(order))
    return (f"{topic or 'The product'}: would you buy it at each of these prices? Everything else about it stays the "
            f"same; only the price changes.\n{lines}\n\n" + 'Reply: {"buy": [true|false, ...]} in the order above.')


def gg_parse(text: str, order: List[int], n: int) -> Optional[List[Optional[bool]]]:
    d = _json_block(text)
    got = (d or {}).get("buy")
    if not isinstance(got, list) or len(got) != len(order):
        return None
    out: List[Optional[bool]] = [None] * n
    for k, i in enumerate(order):
        v = got[k]
        out[i] = v if isinstance(v, bool) else (str(v).lower() in ("yes", "true", "1") if v is not None else None)
    return out


def gg_curve(prices: List[str], answers: List[List[Optional[bool]]]) -> Dict[str, Any]:
    rows = []
    for i, p in enumerate(prices):
        ys = [a[i] for a in answers if a and a[i] is not None]
        share = sum(ys) / len(ys) if ys else None
        num = _price_num(p)
        rows.append({"price": p, "n": len(ys), "share_buy": round(share, 3) if share is not None else None,
                     "revenue_index": round(num * share, 3) if num is not None and share is not None else None})
    best = max((r for r in rows if r["revenue_index"] is not None), key=lambda r: r["revenue_index"], default=None)
    inconsistent = sum(1 for a in answers if a and _non_monotone(prices, a))
    return {"curve": rows, "revenue_max_price": best["price"] if best else None,
            "inconsistent_people": inconsistent,
            "note": "stated purchase at each price, simulated; stated willingness to pay runs optimistic"}


def _non_monotone(prices: List[str], a: List[Optional[bool]]) -> bool:
    pts = sorted(((_price_num(p), v) for p, v in zip(prices, a) if v is not None and _price_num(p) is not None))
    seen_no = False
    for _, v in pts:
        if not v:
            seen_no = True
        elif seen_no:
            return True
    return False


# --------------------------------------------------------------------------
# run on simulated people
# --------------------------------------------------------------------------

def run(kind: str, people: List[Dict[str, Any]], spec: Dict[str, Any], complete: Complete, parallel: int = 8,
        seed: int = 7) -> Dict[str, Any]:
    """One call per person with all their tasks. spec: maxdiff {items, per_set?, sets?, topic};
    conjoint {attributes: {name: [levels]}, tasks?, alts?, price_attribute?, held_fixed?, topic};
    gabor_granger {prices: [..], topic}."""
    usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
    topic = str(spec.get("topic") or spec.get("offer") or "")
    if kind == "maxdiff":
        items = [str(x) for x in spec.get("items") or []]
        design = maxdiff_design(items, int(spec.get("per_set") or 4), spec.get("sets"), seed)
        ask = maxdiff_prompt(items, design, topic)
    elif kind == "conjoint":
        attrs = {str(a): [str(x) for x in v] for a, v in (spec.get("attributes") or {}).items()}
        design = cbc_design(attrs, int(spec.get("tasks") or 8), int(spec.get("alts") or 3), seed)
        ask = cbc_prompt(design, topic, str(spec.get("held_fixed") or ""))
    elif kind == "gabor_granger":
        prices = [str(p) for p in spec.get("prices") or []]
        if len(prices) < 3:
            raise ValueError("Gabor-Granger needs 3+ prices")
    else:
        raise ValueError("kind must be maxdiff, conjoint or gabor_granger")

    def one(p):
        order = (random.Random(f"{seed}:{p.get('agent_id')}").sample(range(len(prices)), len(prices))
                 if kind == "gabor_granger" else [])
        user = gg_prompt(prices, topic, order) if kind == "gabor_granger" else ask
        try:
            text, u = complete(SYSTEM + "\nWho you are: " + person_text(p), user)
        except Exception:  # noqa: BLE001 - a failed person is left out
            return p, None, {}, order
        return p, text, u or {}, order
    with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
        results = list(pool.map(one, people))
    answers, failed = [], 0
    for p, text, u, order in results:
        if text is not None:
            usage["calls"] += 1
            for k in ("input_tokens", "output_tokens"):
                usage[k] += int(u.get(k) or 0)
        seg = str(p.get("segment") or "")
        if text is None:
            failed += 1
            continue
        if kind == "maxdiff":
            picks = maxdiff_parse(text, design)
            if picks:
                answers.append({"segment": seg, "picks": picks})
            else:
                failed += 1
        elif kind == "conjoint":
            ch = cbc_parse(text, design)
            if ch:
                answers.append({"segment": seg, "choices": ch})
            else:
                failed += 1
        else:
            got = gg_parse(text, order, len(prices))
            if got:
                answers.append({"segment": seg, "buy": got})
            else:
                failed += 1
    out: Dict[str, Any] = {"version": VERSION, "kind": kind, "topic": topic, "people": len(people),
                           "answered": len(answers), "failed": failed, "usage": usage,
                           "note": "Simulated people: directions, not measured shares."}
    if kind == "maxdiff":
        out["design"] = design
        out["ranking"] = maxdiff_scores(items, answers, design)
        segs = sorted({a["segment"] for a in answers})
        if len(segs) > 1:
            out["by_segment"] = {s: maxdiff_scores(items, [a for a in answers if a["segment"] == s], design, boot=100)[:5]
                                 for s in segs}
    elif kind == "conjoint":
        obs = [(task, c) for a in answers for task, c in zip(design, a["choices"])]
        fit = mnl_fit(obs, attrs)
        out.update({"design": design, "fit": fit, "none_share": round(sum(1 for _, c in obs if c is None) / max(1, len(obs)), 3),
                    "wtp": wtp_direction(fit, spec.get("price_attribute"))})
    else:
        out.update({"prices": prices, **gg_curve(prices, [a["buy"] for a in answers])})
    return out
