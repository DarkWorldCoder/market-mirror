"""
marketing.py - turn a MiroFish run into marketing and sales answers.

1. A post-run survey: every simulated person answers the same short questionnaire
   (interest, trust, would click, would convert, recommend, best message, main
   objection, what would change their mind, a quote). Answers are parsed from the
   agents' interview replies.
2. Analysis: funnel, intent by segment / country / community / age band / gender,
   objections, winning messages, voice-of-customer quotes, plain-language verdicts.
3. HTML sections for the dashboard (stdlib only, same CSS tokens as exporter.py).

Stdlib only, so offline `export --run-dir` keeps working anywhere.
"""

from __future__ import annotations

import html
import json
import re
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

YES, MAYBE, NO = "yes", "maybe", "no"
OBJECTION_TYPES = ["price", "trust", "relevance", "timing", "effort", "unclear", "privacy", "language",
                   "none", "other"]
OBJECTION_LABELS = {
    "price": "Cost / not sure it is really free", "trust": "Trust / looks like a scam",
    "relevance": "Not relevant to me", "timing": "Not the right time", "effort": "Too much effort",
    "unclear": "Unclear what it is", "privacy": "Privacy / personal data", "language": "Language barrier",
    "none": "No objection", "other": "Other",
}
AGE_BANDS = [(0, 17, "Under 18"), (18, 24, "18-24"), (25, 34, "25-34"), (35, 44, "35-44"),
             (45, 54, "45-54"), (55, 64, "55-64"), (65, 200, "65+")]


# --------------------------------------------------------------------------
# Survey prompt and answer parsing
# --------------------------------------------------------------------------

def survey_prompt(offer: str = "", goal: str = "", messages: Optional[List[str]] = None,
                  assigned: Optional[int] = None, currency: Optional[str] = None) -> str:
    """The questionnaire. `assigned` (0-based) = split test: this person sees only that message.
    `currency` adds four price-sensitivity questions (Van Westendorp)."""
    about = f" about {offer}" if offer else " about the brand, product or offer you saw"
    goal_txt = goal or "take the action the offer asks for (sign up, buy, book or download)"
    msg_block, msg_fields = "", ""
    if messages and assigned is not None:
        msg_block = f"This is the ad/message you saw:\n\"{messages[assigned]}\"\n\n"
        msg_fields = '"message_reaction": 0-10, '
    elif messages:
        msg_block = "Here are the messages/ads being tested:\n" + "\n".join(
            f"{i + 1}. {m}" for i, m in enumerate(messages)) + "\n\n"
        msg_fields = '"best_message": "the number of the message that works best for you, or none", '
    price_fields = ""
    if currency:
        price_fields = (f'"price_too_cheap": "price in {currency} so low you would doubt the quality", '
                        f'"price_cheap": "price in {currency} that feels like a bargain", '
                        f'"price_expensive": "price in {currency} that starts to feel expensive but you might pay", '
                        f'"price_too_expensive": "price in {currency} you would never pay", ')
    return (
        "Step out of the feed for a moment. A market researcher asks you a few quick questions"
        f"{about}. Answer as yourself, honestly, the way you really think. It is fine to be negative, "
        "unsure or not interested.\n\n"
        f"{msg_block}"
        f"The action we care about: {goal_txt}.\n\n"
        "Reply with only this JSON, no other text (numbers as plain numbers):\n"
        '{"noticed": true, "interest": 0-10, "trust": 0-10, "would_click": "yes|maybe|no", '
        '"would_convert": "yes|maybe|no", "recommend": 0-10, '
        f"{msg_fields}{price_fields}"
        '"main_objection": "your biggest hesitation, one sentence", '
        '"objection_type": "price|trust|relevance|timing|effort|unclear|privacy|language|none|other", '
        '"would_change_mind": "what would make you say yes, one sentence", '
        '"quote": "one sentence in your own voice about it"}'
    )


def assign_messages(agent_ids: List[int], n_messages: int, seed: int = 11) -> Dict[int, int]:
    """Balanced random assignment of one message per person for a split test."""
    import random
    ids = sorted(agent_ids)
    rng = random.Random(seed)
    rng.shuffle(ids)
    return {aid: i % n_messages for i, aid in enumerate(ids)} if n_messages else {}


def _price(v: Any) -> Optional[float]:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) if v >= 0 else None
    m = re.search(r"\d[\d,]*(\.\d+)?", str(v))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    if isinstance(text, dict):
        return text
    if not isinstance(text, str) or not text.strip():
        return None
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1)
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end <= start:
        return None
    blob = t[start:end + 1]
    for attempt in (blob, re.sub(r",\s*}", "}", blob)):
        try:
            v = json.loads(attempt)
            return v if isinstance(v, dict) else None
        except ValueError:
            continue
    return None


def _score(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return 10.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(max(0, min(10, v)))
    if isinstance(v, str):
        m = re.search(r"\d+(\.\d+)?", v)
        if m:
            return float(max(0, min(10, float(m.group(0)))))
    return None


def _ynm(v: Any) -> Optional[str]:
    if isinstance(v, bool):
        return YES if v else NO
    if isinstance(v, (int, float)):
        return YES if v >= 7 else MAYBE if v >= 4 else NO
    if not isinstance(v, str):
        return None
    s = v.strip().lower()
    if s.startswith(("maybe", "perhaps", "possibly", "not sure", "unsure", "might", "depends", "it depends")):
        return MAYBE
    if s.startswith(("probably not", "unlikely", "never", "no", "nah", "nope")):
        return NO
    if s.startswith(("yes", "yeah", "yep", "definitely", "sure", "probably", "likely", "absolutely")):
        return YES
    return None


def _message_key(v: Any, n_messages: int = 0) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() in ("none", "n/a", "na", "no", "null", "-"):
        return None
    m = re.match(r"^\D{0,12}?(\d{1,2})\b", s)
    if m and (not n_messages or 1 <= int(m.group(1)) <= n_messages):
        return f"#{int(m.group(1))}"
    return s[:60]


def parse_answer(response: Any, n_messages: int = 0) -> Optional[Dict[str, Any]]:
    """Normalise one interview reply into survey fields, or None if nothing usable came back."""
    data = _extract_json(response if not isinstance(response, dict) else json.dumps(response))
    if data is None and isinstance(response, dict):
        data = response
    if not data:
        return None
    obj_type = str(data.get("objection_type") or "").strip().lower()
    if obj_type not in OBJECTION_TYPES:
        obj_type = "other" if obj_type else ("none" if not data.get("main_objection") else "other")
    out = {
        "noticed": bool(data.get("noticed")) if data.get("noticed") is not None else None,
        "interest": _score(data.get("interest")),
        "trust": _score(data.get("trust")),
        "would_click": _ynm(data.get("would_click")),
        "would_convert": _ynm(data.get("would_convert") or data.get("would_sign_up") or data.get("would_buy")),
        "recommend": _score(data.get("recommend")),
        "best_message": _message_key(data.get("best_message"), n_messages),
        "main_objection": str(data.get("main_objection") or "").strip()[:300],
        "objection_type": obj_type,
        "would_change_mind": str(data.get("would_change_mind") or "").strip()[:300],
        "quote": str(data.get("quote") or "").strip()[:300],
        "message_reaction": _score(data.get("message_reaction")),
    }
    prices = {k: _price(data.get(k)) for k in ("price_too_cheap", "price_cheap", "price_expensive",
                                                "price_too_expensive")}
    if any(v is not None for v in prices.values()):
        out.update(prices)
    if out["interest"] is None and out["would_convert"] is None and out["would_click"] is None:
        return None
    return out


def interview_texts(result: Any) -> Dict[int, str]:
    """Pull {agent_id: reply text} from the batch-interview API payload (any platform)."""
    res = result.get("result", result) if isinstance(result, dict) else {}
    items = res.get("results") if isinstance(res, dict) else None
    out: Dict[int, str] = {}
    if isinstance(items, dict):
        items = list(items.values())
    for it in items or []:
        if not isinstance(it, dict):
            continue
        aid, resp = it.get("agent_id"), it.get("response")
        if aid is None or resp in (None, ""):
            continue
        if isinstance(resp, (dict, list)):
            resp = json.dumps(resp, ensure_ascii=False)
        if int(aid) not in out or (not _extract_json(out[int(aid)]) and _extract_json(resp)):
            out[int(aid)] = str(resp)
    return out


# --------------------------------------------------------------------------
# Who is who
# --------------------------------------------------------------------------

def _profiles(bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
    for key in ("profiles_reddit", "profiles_twitter"):
        v = bundle.get(key)
        if isinstance(v, list) and v:
            return v
    return []


def agent_meta(bundle: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    """agent_id -> {name, kind, segment, country, communities, age, gender, ...}."""
    cfg = bundle.get("config") or {}
    meta: Dict[int, Dict[str, Any]] = {}
    for row in cfg.get("persona_index") or []:
        if isinstance(row, dict) and row.get("agent_id") is not None:
            meta[int(row["agent_id"])] = dict(row)
    for i, p in enumerate(_profiles(bundle)):
        aid = p.get("user_id", i)
        try:
            aid = int(aid)
        except (TypeError, ValueError):
            aid = i
        m = meta.setdefault(aid, {"agent_id": aid})
        m.setdefault("name", p.get("name") or p.get("username"))
        for k in ("age", "gender", "country"):
            if m.get(k) in (None, "") and p.get(k) not in (None, ""):
                m[k] = p.get(k)
        if "kind" not in m:
            m["kind"] = "graph" if str(p.get("gender") or "").lower() == "other" else "person"
        m.setdefault("segment", p.get("profession") if m["kind"] == "person" else None)
    return meta


def people_ids(meta: Dict[int, Dict[str, Any]]) -> List[int]:
    personas = [a for a, m in meta.items() if m.get("kind") == "persona"]
    if personas:
        return sorted(personas)
    return sorted(a for a, m in meta.items() if m.get("kind") in ("person", "persona"))


def age_band(age: Any) -> Optional[str]:
    try:
        a = int(age)
    except (TypeError, ValueError):
        return None
    for lo, hi, label in AGE_BANDS:
        if lo <= a <= hi:
            return label
    return None


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------

def _pct(n: float, d: float) -> Optional[float]:
    return round(100.0 * n / d, 1) if d else None


def _avg(xs: List[Optional[float]]) -> Optional[float]:
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 1) if xs else None


def _group_stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(rows)
    conv = Counter(r.get("would_convert") for r in rows)
    click = Counter(r.get("would_click") for r in rows)
    rec = [r.get("recommend") for r in rows if r.get("recommend") is not None]
    promoters = sum(1 for x in rec if x >= 9)
    detractors = sum(1 for x in rec if x <= 6)
    objections = Counter(r.get("objection_type") for r in rows if r.get("objection_type") not in (None, "none"))
    msgs = Counter(r.get("best_message") for r in rows if r.get("best_message"))
    return {
        "n": n,
        "interest": _avg([r.get("interest") for r in rows]),
        "trust": _avg([r.get("trust") for r in rows]),
        "click_yes": _pct(click[YES], n), "click_maybe": _pct(click[MAYBE], n),
        "convert_yes": _pct(conv[YES], n), "convert_maybe": _pct(conv[MAYBE], n), "convert_no": _pct(conv[NO], n),
        "nps": round(100.0 * (promoters - detractors) / len(rec)) if rec else None,
        "top_objection": objections.most_common(1)[0][0] if objections else None,
        "top_message": msgs.most_common(1)[0][0] if msgs else None,
    }


def analyze(bundle: Dict[str, Any]) -> Dict[str, Any]:
    meta = agent_meta(bundle)
    people = people_ids(meta)
    actions = bundle.get("actions") if isinstance(bundle.get("actions"), list) else []
    acted = Counter()
    for a in actions:
        if str(a.get("action_type") or "").upper() not in ("DO_NOTHING", "REFRESH", "INTERVIEW"):
            try:
                acted[int(a.get("agent_id"))] += 1
            except (TypeError, ValueError):
                pass
    survey = bundle.get("survey") or {}
    messages = survey.get("messages") or []
    rows = []
    for r in survey.get("responses") or []:
        ans = r.get("answer")
        if not ans:
            continue
        aid = int(r.get("agent_id"))
        m = meta.get(aid, {})
        rows.append({**ans, "agent_id": aid, "name": m.get("name") or r.get("name"),
                     "assigned": r.get("assigned_message"),
                     "segment": m.get("segment") or "Unassigned", "country": m.get("country") or "Unknown",
                     "communities": m.get("communities") or [], "age_band": age_band(m.get("age")),
                     "gender": m.get("gender"), "acted": acted.get(aid, 0)})

    out: Dict[str, Any] = {
        "has_survey": bool(rows), "people": len(people),
        "engaged": sum(1 for a in people if acted.get(a)),
        "surveyed": len(survey.get("responses") or []), "answered": len(rows),
        "offer": survey.get("offer"), "goal": survey.get("goal"), "messages": messages,
        "currency": survey.get("currency"),
    }
    # engagement by segment even without a survey
    seg_people: Dict[str, List[int]] = defaultdict(list)
    for a in people:
        seg_people[meta[a].get("segment") or "Unassigned"].append(a)
    out["engagement_by_segment"] = sorted(
        [{"key": s, "n": len(ids), "engaged": _pct(sum(1 for a in ids if acted.get(a)), len(ids)),
          "actions_per_person": round(sum(acted.get(a, 0) for a in ids) / len(ids), 1)}
         for s, ids in seg_people.items()], key=lambda r: -(r["actions_per_person"] or 0))
    if not rows:
        return out

    out["overall"] = _group_stats(rows)
    base = len(rows)
    out["funnel"] = [
        ("Simulated people", out["people"]),
        ("Answered the survey", base),
        ("Would click", sum(1 for r in rows if r.get("would_click") == YES)),
        (f"Would click and {_goal_verb(out['goal'])}",
         sum(1 for r in rows if r.get("would_click") == YES and r.get("would_convert") == YES)),
    ]

    def breakdown(keyfn) -> List[Dict[str, Any]]:
        groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for r in rows:
            for k in keyfn(r):
                if k:
                    groups[k].append(r)
        res = [{"key": k, **_group_stats(v)} for k, v in groups.items()]
        return sorted(res, key=lambda x: (-(x["convert_yes"] or 0), -(x["interest"] or 0), -x["n"]))

    out["by_segment"] = breakdown(lambda r: [r["segment"]])
    out["by_country"] = breakdown(lambda r: [r["country"]])
    out["by_community"] = breakdown(lambda r: r["communities"] or ["No community"])
    out["by_age"] = sorted(breakdown(lambda r: [r["age_band"]]),
                           key=lambda x: [b[2] for b in AGE_BANDS].index(x["key"]) if x["key"] in
                           [b[2] for b in AGE_BANDS] else 99)
    out["by_gender"] = breakdown(lambda r: [str(r["gender"]).title()] if r.get("gender") else [])

    obj = Counter(r["objection_type"] for r in rows if r.get("objection_type") not in (None, "none"))
    out["objections"] = [{"type": t, "label": OBJECTION_LABELS.get(t, t), "count": c, "share": _pct(c, base),
                          "examples": [{"name": r["name"], "segment": r["segment"], "text": r["main_objection"],
                                        "fix": r.get("would_change_mind")}
                                       for r in rows if r.get("objection_type") == t and r.get("main_objection")][:3]}
                         for t, c in obj.most_common()]
    by_obj_seg: Dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        if r.get("objection_type") not in (None, "none"):
            by_obj_seg[r["segment"]][r["objection_type"]] += 1
    out["objections_by_segment"] = {s: dict(c) for s, c in by_obj_seg.items()}

    split = survey.get("mode") == "split" and any(r.get("assigned") is not None for r in rows)
    out["split_test"] = split
    msg_rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        key = f"#{int(r['assigned']) + 1}" if split and r.get("assigned") is not None else r.get("best_message")
        if key:
            r["message_key"] = key
            msg_rows[key].append(r)
    if split:
        # each person saw exactly one message: compare conversion between equal-sized random groups
        out["messages_ranked"] = sorted(
            [{"key": k, "label": _message_label(k, messages), "votes": len(v), "share": _pct(len(v), base),
              **{f: s for f, s in _group_stats(v).items() if f in ("convert_yes", "convert_maybe", "convert_no",
                                                                   "click_yes", "interest", "trust")},
              "reaction": _avg([r.get("message_reaction") for r in v]),
              "segments": [s for s, _ in Counter(r["segment"] for r in v if r.get("would_convert") == YES).most_common(3)]}
             for k, v in msg_rows.items()],
            key=lambda x: (-(x["convert_yes"] or 0), -(x["reaction"] or 0), -(x["interest"] or 0)))
    else:
        out["messages_ranked"] = sorted(
            [{"key": k, "label": _message_label(k, messages), "votes": len(v), "share": _pct(len(v), base),
              "convert_yes": _pct(sum(1 for r in v if r.get("would_convert") == YES), len(v)),
              "segments": [s for s, _ in Counter(r["segment"] for r in v).most_common(3)]}
             for k, v in msg_rows.items()], key=lambda x: (-x["votes"], -(x["convert_yes"] or 0)))

    # segment x message grid: which message for which audience
    grid: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if r.get("message_key"):
            grid[r["segment"]][r["message_key"]].append(r)
    out["message_grid"] = {
        "messages": [m["key"] for m in out["messages_ranked"]],
        "rows": [{"segment": seg_, "cells": {k: {"n": len(v), "convert_yes": _pct(sum(1 for r in v if r.get("would_convert") == YES), len(v))}
                                              for k, v in cells.items()}}
                 for seg_, cells in sorted(grid.items())],
    } if grid else None

    out["pricing"] = pricing(rows)
    out["playbook"] = playbook(out, rows)

    def quotes(pred, limit=6):
        return [{"name": r["name"], "segment": r["segment"], "country": r["country"],
                 "text": r.get("quote") or r.get("main_objection"), "convert": r.get("would_convert")}
                for r in sorted(rows, key=lambda r: -(r.get("interest") or 0)) if pred(r) and
                (r.get("quote") or r.get("main_objection"))][:limit]
    out["quotes_yes"] = quotes(lambda r: r.get("would_convert") == YES)
    out["quotes_no"] = quotes(lambda r: r.get("would_convert") == NO)
    out["change_mind"] = [{"name": r["name"], "segment": r["segment"], "text": r["would_change_mind"]}
                          for r in rows if r.get("would_convert") != YES and r.get("would_change_mind")][:8]
    out["verdicts"] = verdicts(out)
    return out


def _median(xs: List[float]) -> Optional[float]:
    xs = sorted(xs)
    if not xs:
        return None
    mid = len(xs) // 2
    return xs[mid] if len(xs) % 2 else (xs[mid - 1] + xs[mid]) / 2


def _crossing(prices: List[float], falling, rising) -> Optional[float]:
    """First price where the rising curve meets or passes the falling one."""
    for p in prices:
        if rising(p) >= falling(p):
            return p
    return None


def pricing(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Van Westendorp price sensitivity from the four price answers (needs 4+ complete answers)."""
    keys = ("price_too_cheap", "price_cheap", "price_expensive", "price_too_expensive")
    full = [r for r in rows if all(isinstance(r.get(k), (int, float)) for k in keys)]
    if len(full) < 4:
        return None
    tc, ch, ex, te = ([r[k] for r in full] for k in keys)
    n = len(full)
    grid = sorted(set(tc + ch + ex + te))
    too_cheap = lambda p: sum(1 for v in tc if v >= p) / n          # noqa: E731 falls as price rises
    not_cheap = lambda p: sum(1 for v in ch if v <= p) / n          # noqa: E731 rises
    not_expensive = lambda p: sum(1 for v in ex if v >= p) / n      # noqa: E731 falls
    too_exp = lambda p: sum(1 for v in te if v <= p) / n            # noqa: E731 rises
    low = _crossing(grid, too_cheap, not_cheap)
    high = _crossing(grid, not_expensive, too_exp)
    optimal = _crossing(grid, too_cheap, too_exp)
    by_seg: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in full:
        by_seg[r["segment"]].append(r)
    step = max(1, len(grid) // 40)
    pts = grid[::step] + ([grid[-1]] if grid[-1] not in grid[::step] else [])
    return {
        "answers": n,
        "acceptable_low": low, "acceptable_high": high, "optimal": optimal,
        "curves": {"prices": pts,
                   "too_cheap": [round(100 * too_cheap(p), 1) for p in pts],
                   "cheap": [round(100 * (1 - not_cheap(p)), 1) for p in pts],
                   "expensive": [round(100 * (1 - not_expensive(p)), 1) for p in pts],
                   "too_expensive": [round(100 * too_exp(p), 1) for p in pts]},
        "median": {k: _median([r[k] for r in full]) for k in keys},
        "by_segment": [{"key": s, "n": len(v), "cheap": _median([r["price_cheap"] for r in v]),
                        "expensive": _median([r["price_expensive"] for r in v]),
                        "too_expensive": _median([r["price_too_expensive"] for r in v])}
                       for s, v in sorted(by_seg.items())],
    }


def playbook(a: Dict[str, Any], rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Per segment: who to target first, what to lead with, what to pre-empt and how."""
    grid = {r["segment"]: r["cells"] for r in ((a.get("message_grid") or {}).get("rows") or [])}
    comm = defaultdict(Counter)
    for r in rows:
        for c in r.get("communities") or []:
            comm[r["segment"]][c] += 1
    plays = []
    for s in a.get("by_segment") or []:
        seg_rows = [r for r in rows if r["segment"] == s["key"]]
        cells = grid.get(s["key"]) or {}
        lead = None
        if cells:
            lead = max(cells.items(), key=lambda kv: ((kv[1]["convert_yes"] or 0), kv[1]["n"]))[0]
        fixes = Counter(r["would_change_mind"].strip().rstrip(".") for r in seg_rows
                        if r.get("would_convert") != YES and r.get("would_change_mind"))
        hooks = [r.get("quote") for r in seg_rows if r.get("would_convert") == YES and r.get("quote")]
        plays.append({
            "segment": s["key"], "n": s["n"], "convert_yes": s["convert_yes"], "interest": s["interest"],
            "priority": "high" if (s["convert_yes"] or 0) >= 40 else "medium" if (s["convert_yes"] or 0) >= 20 else "low",
            "lead_with": _message_label(lead, a.get("messages") or []) if lead else None,
            "preempt": OBJECTION_LABELS.get(s.get("top_objection")) if s.get("top_objection") else None,
            "answer_with": fixes.most_common(1)[0][0] if fixes else None,
            "seed_in": comm[s["key"]].most_common(1)[0][0] if comm.get(s["key"]) else None,
            "proof_quote": hooks[0] if hooks else None,
        })
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(plays, key=lambda p: (order[p["priority"]], -(p["convert_yes"] or 0)))


def _goal_verb(goal: Optional[str]) -> str:
    if not goal:
        return "convert"
    g = goal.strip().rstrip(".")
    return g[:1].lower() + g[1:] if len(g) <= 40 else "convert"


def _message_label(key: str, messages: List[str]) -> str:
    m = re.match(r"#(\d+)$", key or "")
    if m and messages and 1 <= int(m.group(1)) <= len(messages):
        return f"{key} {messages[int(m.group(1)) - 1]}"
    return key


def verdicts(a: Dict[str, Any]) -> List[str]:
    """Plain-language headline findings."""
    out = []
    o = a.get("overall") or {}
    if o:
        out.append(f"{_fmt_pct(o.get('convert_yes'))} of the people surveyed say they would "
                   f"{_goal_verb(a.get('goal'))}, and {_fmt_pct(o.get('convert_maybe'))} more are on the fence.")
    segs = [s for s in a.get("by_segment") or [] if s["n"] >= 2]
    if len(segs) >= 2:
        best, worst = segs[0], segs[-1]
        out.append(f"Best audience: {best['key']} ({_fmt_pct(best['convert_yes'])} would convert, "
                   f"interest {best['interest']}/10). Weakest: {worst['key']} ({_fmt_pct(worst['convert_yes'])}).")
    objs = a.get("objections") or []
    if objs:
        top = objs[0]
        out.append(f"Biggest blocker: {top['label'].lower()}, raised by {_fmt_pct(top['share'])} of people.")
    msgs = a.get("messages_ranked") or []
    if msgs and a.get("split_test"):
        m = msgs[0]
        tail = ""
        if len(msgs) > 1:
            tail = f" vs {_fmt_pct(msgs[-1]['convert_yes'])} for the weakest ({msgs[-1]['key']})"
        out.append(f"Split test winner: {trunc_text(m['label'], 90)}, {_fmt_pct(m['convert_yes'])} of the people "
                   f"who saw it would convert{tail}.")
    elif msgs:
        m = msgs[0]
        out.append(f"Most persuasive message: {trunc_text(m['label'], 90)} "
                   f"(picked by {_fmt_pct(m['share'])}; {_fmt_pct(m['convert_yes'])} of them would convert).")
    pr = a.get("pricing")
    if pr and pr.get("acceptable_low") is not None and pr.get("acceptable_high") is not None:
        out.append(f"Acceptable price range: {pr['acceptable_low']:g} to {pr['acceptable_high']:g}"
                   + (f", sweet spot around {pr['optimal']:g}." if pr.get("optimal") is not None else "."))
    if o.get("nps") is not None:
        out.append(f"Word of mouth score (NPS-style): {o['nps']:+d}.")
    return out


def _fmt_pct(v: Optional[float]) -> str:
    return "–" if v is None else f"{v:.0f}%"


def trunc_text(s: Any, n: int) -> str:
    s = "" if s is None else str(s)
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"



# --------------------------------------------------------------------------
# HTML: MarketMirror theme (warm canvas, white cards, black pills, one accent)
# Charts are Apache ECharts containers rendered by MARKETING_JS; every chart
# has a table view next to it, so the numbers survive without the library.
# --------------------------------------------------------------------------

def _e(v: Any) -> str:
    return html.escape("" if v is None else str(v), quote=True)


MARKETING_CSS = """
:root{--bg:#eeeeea;--surface:#ffffff;--surface-2:#f6f6f3;--border:#dcdbd5;--text:#111111;--text-2:#3d3d3a;
--muted:#6b6b66;--grid:#e8e7e2;--axis:#c3c2b7;--accent:#111111;
--mm-accent:#f3d64b;--mm-accent-ink:#2b2005;--mm-accent-wash:#fbf1bf;--mm-panel:#121212;--mm-panel-2:#1d1d1c;
--mm-panel-ink:#f2f2ee;--mm-panel-muted:#9a9a93;--mm-mint:#cfefd9;--mm-orchid:#f1c6ee;--mm-sky:#cde7f6;--mm-lav:#d9d0f5;
--mm-yes:#2a78d6;--mm-maybe:#d6d5ce;--mm-no:#e34948;--mm-ink-bar:#111111;
--mm-seq:#f6f6f3,#cde2fb,#86b6ef,#3987e5,#1c5cab,#0d366b}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0d0d0c;--surface:#1a1a19;--surface-2:#242422;
--border:#33332f;--text:#f2f2ee;--text-2:#c3c2b7;--muted:#9a9a93;--grid:#2c2c2a;--axis:#383835;--accent:#f2f2ee;
--mm-panel:#000000;--mm-panel-2:#161615;--mm-yes:#3987e5;--mm-maybe:#4a4a46;--mm-no:#e66767;--mm-ink-bar:#f2f2ee;
--mm-mint:#1f3a28;--mm-orchid:#3d2240;--mm-sky:#1d3340;--mm-lav:#2b2546;--mm-accent-wash:#3a3210;
--mm-seq:#242422,#0d366b,#1c5cab,#3987e5,#86b6ef,#cde2fb}}
:root[data-theme="dark"]{--bg:#0d0d0c;--surface:#1a1a19;--surface-2:#242422;--border:#33332f;--text:#f2f2ee;
--text-2:#c3c2b7;--muted:#9a9a93;--grid:#2c2c2a;--axis:#383835;--accent:#f2f2ee;--mm-panel:#000000;--mm-panel-2:#161615;
--mm-yes:#3987e5;--mm-maybe:#4a4a46;--mm-no:#e66767;--mm-ink-bar:#f2f2ee;--mm-mint:#1f3a28;--mm-orchid:#3d2240;
--mm-sky:#1d3340;--mm-lav:#2b2546;--mm-accent-wash:#3a3210;--mm-seq:#242422,#0d366b,#1c5cab,#3987e5,#86b6ef,#cde2fb}
body{background:var(--bg);font-family:"Geist",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;font-size:14px;
-webkit-font-smoothing:antialiased}
::selection{background:var(--mm-accent);color:var(--mm-accent-ink)}
.wrap{max-width:1240px}
header.top{display:flex;flex-wrap:wrap;gap:20px 40px;align-items:flex-end;justify-content:space-between;margin-top:8px}
header.top h1{font-size:clamp(2.1rem,4.4vw,3.5rem);line-height:.95;font-weight:500;letter-spacing:-.045em;
text-transform:uppercase;margin:6px 0 10px;max-width:16ch}
header.top .req{color:var(--text-2);max-width:70ch}
.hero-stats{display:flex;gap:28px;flex-wrap:wrap}
.hero-stats div{min-width:90px}.hero-stats .v{font-size:2.4rem;font-weight:500;letter-spacing:-.04em;line-height:1}
.hero-stats .k{color:var(--muted);font-size:.82rem;margin-top:4px}
nav.toc{gap:8px;padding:10px 0}
nav.toc a{border-radius:999px;background:var(--surface);border:1px solid var(--border);padding:7px 15px;color:var(--text);
text-decoration:none;font-weight:500;font-size:.88rem;white-space:nowrap}
nav.toc a:hover{border-color:var(--text)}
nav.toc a:first-child{background:var(--text);border-color:var(--text);color:var(--surface)}
section{scroll-margin-top:64px;background:transparent;border:0;padding:0;margin:0 0 36px;border-radius:0}
#report,#posts,#agents,#timeline,#graph,#overview{background:var(--surface);border-radius:24px;padding:22px 24px}
#report .card,#posts .card,#agents .card,#timeline .card,#graph .card,#overview .card,#overview .tile{background:var(--surface-2)}
section h2{font-size:1.35rem;font-weight:500;letter-spacing:-.02em}
.card,.tile{background:var(--surface);border:0;border-radius:24px;padding:20px 22px;box-shadow:none}
.card h3{font-size:1.02rem;font-weight:500;letter-spacing:-.01em;margin:0 0 10px}
@media (prefers-reduced-motion:no-preference){.card,.kpi,.play{transition:transform .18s cubic-bezier(.22,1,.36,1),box-shadow .18s}
.card:hover,.kpi:hover,.play:hover{transform:translateY(-2px);box-shadow:0 10px 26px rgba(17,17,17,.07)}}
.grid2{gap:14px}
.mm-top{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(0,1fr);gap:14px}
@media (max-width:860px){.mm-top{grid-template-columns:1fr}}
.panel{background:var(--mm-panel);color:var(--mm-panel-ink);border-radius:24px;padding:22px 24px}
.panel .eyebrow{color:var(--mm-panel-muted);font-size:.8rem;text-transform:uppercase;letter-spacing:.08em}
.panel .headline{font-size:1.45rem;line-height:1.25;letter-spacing:-.02em;font-weight:500;margin:8px 0 14px}
.verdicts{list-style:none;padding:0;margin:0;display:grid;gap:10px}
.verdicts li{display:flex;gap:10px;align-items:flex-start;color:var(--mm-panel-ink);font-size:.95rem}
.verdicts li::before{content:"";flex:0 0 8px;height:8px;margin-top:7px;border-radius:50%;background:var(--mm-accent)}
.kpis{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.kpi{background:var(--surface);border-radius:20px;padding:16px 18px}
.kpi .v{font-size:2rem;font-weight:500;letter-spacing:-.04em;line-height:1.05}
.kpi .k{color:var(--text-2);font-size:.85rem;margin-top:4px}.kpi .h{color:var(--muted);font-size:.76rem;margin-top:2px}
.kpi.hl{background:var(--mm-accent);color:var(--mm-accent-ink)}.kpi.hl .k,.kpi.hl .h{color:var(--mm-accent-ink)}
.ec{width:100%;min-height:120px}
.ec-fallback{color:var(--muted);font-size:.85rem}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:.8rem;color:var(--muted);margin:2px 0 8px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px;vertical-align:-1px}
.i-yes{background:var(--mm-yes)}.i-maybe{background:var(--mm-maybe)}.i-no{background:var(--mm-no)}
.seg-tabs{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}
.seg-tabs button{font:inherit;font-size:.86rem;font-weight:500;border:1px solid var(--border);background:var(--surface);
color:var(--text);border-radius:999px;padding:6px 14px;cursor:pointer}
.seg-tabs button[aria-pressed="true"]{background:var(--text);border-color:var(--text);color:var(--surface)}
.seg-panel[hidden]{display:none}
details.tv{margin-top:8px}details.tv summary{cursor:pointer;color:var(--muted);font-size:.82rem}
.tbl table{font-size:.86rem}
.quotes{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px}
.quote{background:var(--surface-2);border-radius:18px;padding:12px 14px}
.quote p{margin:0 0 6px}.quote .who{color:var(--muted);font-size:.8rem}
.pill{display:inline-block;font-size:.74rem;font-weight:500;border-radius:999px;padding:3px 10px;background:var(--surface-2);color:var(--text-2)}
.pill.mint{background:var(--mm-mint)}.pill.orchid{background:var(--mm-orchid)}.pill.sky{background:var(--mm-sky)}
.pill.accent{background:var(--mm-accent);color:var(--mm-accent-ink)}
.callout{background:var(--surface);border-radius:24px;padding:18px 22px}
td.best{font-weight:600}
.plays{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:12px}
.play{background:var(--surface);border-radius:24px;padding:18px 20px}
.play.p-high{background:var(--mm-panel);color:var(--mm-panel-ink)}
.play.p-high dt,.play.p-high .muted{color:var(--mm-panel-muted)}
.play-h{display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:10px}
.play-h strong{font-size:1.05rem;font-weight:500}
.play dl{margin:0;display:grid;grid-template-columns:auto 1fr;gap:6px 12px;font-size:.9rem}
.play dt{color:var(--muted)}.play dd{margin:0}
h2.divider{margin-top:48px;padding-top:18px;border-top:1px solid var(--border);color:var(--muted);font-size:.85rem;
text-transform:uppercase;letter-spacing:.08em;font-weight:500}
"""

MARKETING_JS = r"""
(function(){
function css(n){return getComputedStyle(document.documentElement).getPropertyValue(n).trim();}
function th(){return {ink:css('--text'),ink2:css('--text-2'),muted:css('--muted'),grid:css('--grid'),axis:css('--axis'),
 card:css('--surface'),line:css('--border'),bar:css('--mm-ink-bar'),accent:css('--mm-accent'),accentInk:css('--mm-accent-ink'),
 yes:css('--mm-yes'),maybe:css('--mm-maybe'),no:css('--mm-no'),s:[css('--s1'),css('--s2'),css('--s3'),css('--s4')],
 seq:css('--mm-seq').split(',').map(function(x){return x.trim();}),font:getComputedStyle(document.body).fontFamily};}
function base(t){return {textStyle:{fontFamily:t.font,color:t.muted,fontSize:11},animationDuration:450,
 tooltip:{confine:true,backgroundColor:t.card,borderColor:t.line,borderWidth:1,padding:[8,12],textStyle:{color:t.ink,fontSize:12},
  extraCssText:'border-radius:12px;box-shadow:0 10px 26px rgba(0,0,0,.10)'}};}
function catAxis(t,data,extra){return Object.assign({type:'category',data:data,axisTick:{show:false},axisLine:{show:false},
 axisLabel:{color:t.ink2,fontSize:12,width:150,overflow:'truncate'}},extra||{});}
function valAxis(t,extra){return Object.assign({type:'value',axisLine:{show:false},axisTick:{show:false},
 splitLine:{lineStyle:{color:t.grid}},axisLabel:{color:t.muted}},extra||{});}
var B={
 funnel:function(s,t){var top=s.values[0]||1;return Object.assign(base(t),{grid:{left:8,right:110,top:6,bottom:6,containLabel:true},
  tooltip:Object.assign(base(t).tooltip,{trigger:'item',formatter:function(p){var i=p.dataIndex,prev=i?s.values[i-1]:null;
   return p.name+'<br><b>'+p.value+'</b> people'+(prev?' · '+Math.round(100*p.value/(prev||1))+'% of previous step':'');}}),
  xAxis:valAxis(t,{show:false,max:top}),yAxis:catAxis(t,s.stages,{inverse:true}),
  series:[{type:'bar',barMaxWidth:30,data:s.values.map(function(v,i){var last=i===s.values.length-1;
   return {value:v,itemStyle:{color:last?t.accent:t.bar,borderRadius:[0,8,8,0]}};}),
   label:{show:true,position:'right',color:t.ink,fontSize:12,formatter:function(p){return p.value+'  ('+Math.round(100*p.value/top)+'%)';}}}]});},
 intent:function(s,t){var mk=function(name,key,col,lbl){return {name:name,type:'bar',stack:'i',barMaxWidth:20,data:s[key],
   itemStyle:{color:col,borderColor:t.card,borderWidth:2,borderRadius:3},
   label:{show:lbl,position:'inside',color:'#fff',fontSize:11,formatter:function(p){return p.value>=12?Math.round(p.value)+'%':'';}}};};
  return Object.assign(base(t),{grid:{left:8,right:16,top:36,bottom:4,containLabel:true},
  legend:{top:0,left:0,icon:'roundRect',itemWidth:10,itemHeight:10,textStyle:{color:t.ink2}},
  tooltip:Object.assign(base(t).tooltip,{trigger:'axis',axisPointer:{type:'shadow',shadowStyle:{color:'rgba(127,127,127,.08)'}},
   valueFormatter:function(v){return Math.round(v)+'%';}}),
  xAxis:valAxis(t,{max:100,axisLabel:{color:t.muted,formatter:'{value}%'}}),yAxis:catAxis(t,s.cats,{inverse:true}),
  series:[mk('Would convert','yes',t.yes,true),mk('Maybe','maybe',t.maybe,false),mk('No','no',t.no,true)]});},
 bars:function(s,t){return Object.assign(base(t),{grid:{left:8,right:64,top:6,bottom:6,containLabel:true},
  tooltip:Object.assign(base(t).tooltip,{trigger:'item',formatter:function(p){return p.name+'<br><b>'+p.value+(s.unit||'')+'</b>'+(s.notes&&s.notes[p.dataIndex]?'<br>'+s.notes[p.dataIndex]:'');}}),
  xAxis:valAxis(t,{show:false,max:s.max||null}),yAxis:catAxis(t,s.cats,{inverse:true}),
  series:[{type:'bar',barMaxWidth:22,data:s.values.map(function(v,i){return {value:v,itemStyle:{color:i===s.highlight?t.accent:t.bar,borderRadius:[0,6,6,0]}};}),
   label:{show:true,position:'right',color:t.ink,fontSize:12,formatter:function(p){return p.value+(s.unit||'');}}}]});},
 heat:function(s,t){return Object.assign(base(t),{grid:{left:8,right:8,top:8,bottom:30,containLabel:true},
  tooltip:Object.assign(base(t).tooltip,{trigger:'item',formatter:function(p){var d=p.value;return s.y[d[1]]+' × '+s.x[d[0]]+'<br><b>'+d[2]+'%</b> would convert (n='+d[3]+')';}}),
  xAxis:catAxis(t,s.x,{position:'bottom',axisLabel:{color:t.ink2,fontSize:12}}),yAxis:catAxis(t,s.y,{inverse:true}),
  visualMap:{show:false,min:0,max:100,dimension:2,inRange:{color:t.seq}},
  series:[{type:'heatmap',data:s.cells.map(function(c){var light=document.documentElement.getAttribute('data-theme')==='dark'||
    (document.documentElement.getAttribute('data-theme')!=='light'&&matchMedia('(prefers-color-scheme: dark)').matches)?c[2]>=50:c[2]<50;
    return {value:c,label:{color:light?'#111111':'#ffffff'}};}),itemStyle:{borderColor:t.card,borderWidth:3,borderRadius:8},
   label:{show:true,fontSize:12,formatter:function(p){return p.value[2]+'%';}},
   emphasis:{itemStyle:{borderColor:t.ink,borderWidth:2}}}]});},
 price:function(s,t){var c=s.curves,mk=function(name,key,col,dash){return {name:name,type:'line',symbol:'none',smooth:false,
   data:c.prices.map(function(p,i){return [p,c[key][i]];}),lineStyle:{width:2,color:col,type:dash?'dashed':'solid'},itemStyle:{color:col},
   endLabel:{show:true,color:t.ink2,fontSize:11,formatter:name}};};
  var ser=[mk('Too cheap','too_cheap',t.s[0],true),mk('Bargain','cheap',t.s[0],false),mk('Getting expensive','expensive',t.s[1],false),mk('Too expensive','too_expensive',t.s[1],true)];
  if(s.low!=null&&s.high!=null)ser[1].markArea={silent:true,itemStyle:{color:t.accent,opacity:.28},data:[[{xAxis:s.low},{xAxis:s.high}]]};
  if(s.opt!=null)ser[1].markLine={symbol:'none',silent:true,lineStyle:{color:t.ink,type:'solid',width:1.5},label:{formatter:'Sweet spot '+s.opt,color:t.ink},data:[{xAxis:s.opt}]};
  return Object.assign(base(t),{grid:{left:8,right:120,top:40,bottom:8,containLabel:true},
  legend:{top:0,left:0,itemWidth:18,itemHeight:2,textStyle:{color:t.ink2}},
  tooltip:Object.assign(base(t).tooltip,{trigger:'axis',valueFormatter:function(v){return v+'%';}}),
  xAxis:valAxis(t,{name:s.currency||'',nameTextStyle:{color:t.muted},splitLine:{show:false},axisLine:{show:true,lineStyle:{color:t.axis}}}),
  yAxis:valAxis(t,{max:100,axisLabel:{color:t.muted,formatter:'{value}%'}}),series:ser});}
};
var made=[];
function draw(el){if(!window.echarts||el.__ec||el.offsetWidth===0)return;var s;try{s=JSON.parse(el.getAttribute('data-spec'));}catch(e){return;}
 var b=B[el.getAttribute('data-kind')];if(!b)return;var c=echarts.init(el,null,{renderer:'svg'});c.setOption(b(s,th()));el.__ec=c;made.push(el);}
function drawAll(){document.querySelectorAll('.ec').forEach(draw);}
function redraw(){made.forEach(function(el){if(el.__ec){el.__ec.dispose();el.__ec=null;}});made=[];drawAll();}
if(!window.echarts){document.querySelectorAll('.ec').forEach(function(el){el.style.minHeight='0';el.style.height='auto';
 el.innerHTML='<p class="ec-fallback">Chart library not included; see the table below.</p>';});}
document.querySelectorAll('.seg-tabs').forEach(function(tabs){
 tabs.addEventListener('click',function(ev){var b=ev.target.closest('button');if(!b)return;
  tabs.querySelectorAll('button').forEach(function(x){x.setAttribute('aria-pressed',x===b?'true':'false');});
  var root=tabs.parentElement;root.querySelectorAll('.seg-panel').forEach(function(p){p.hidden=p.dataset.panel!==b.dataset.panel;});
  drawAll();});});
drawAll();
var rt;window.addEventListener('resize',function(){clearTimeout(rt);rt=setTimeout(function(){made.forEach(function(el){el.__ec&&el.__ec.resize();});},120);});
try{matchMedia('(prefers-color-scheme: dark)').addEventListener('change',redraw);}catch(e){}
new MutationObserver(redraw).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
})();
"""


def chart(kind: str, spec: Dict[str, Any], height: int, label: str) -> str:
    return (f'<div class="ec" style="height:{int(height)}px" data-kind="{kind}" role="img" aria-label="{_e(label)}" '
            f'data-spec="{_e(json.dumps(spec, ensure_ascii=False))}"></div>')


def _table_view(head: List[str], rows: List[List[Any]], summary: str = "Show the numbers") -> str:
    th_ = "".join(f'<th{" class=num" if i else ""}>{_e(h)}</th>' for i, h in enumerate(head))
    body = "".join("<tr>" + "".join(f'<td{" class=num" if i else ""}>{_e(c)}</td>' for i, c in enumerate(r)) + "</tr>"
                   for r in rows)
    return (f'<details class="tv"><summary>{_e(summary)}</summary><div class="tbl"><table><thead><tr>{th_}</tr></thead>'
            f'<tbody>{body}</tbody></table></div></details>')


def _num(v: Any) -> str:
    return "–" if v is None else (f"{v:g}" if isinstance(v, (int, float)) else str(v))


def _breakdown_block(rows: List[Dict[str, Any]], label: str) -> str:
    if not rows:
        return '<p class="empty">No data.</p>'
    spec = {"cats": [r["key"] for r in rows], "yes": [r["convert_yes"] or 0 for r in rows],
            "maybe": [r["convert_maybe"] or 0 for r in rows], "no": [r["convert_no"] or 0 for r in rows]}
    ch = chart("intent", spec, 64 + 34 * len(rows), f"Would convert by {label.lower()}")
    best = max((r["convert_yes"] or 0) for r in rows)
    body = "".join(
        f'<tr><td class="{"best" if (r["convert_yes"] or 0) == best and best > 0 else ""}">{_e(r["key"])}</td>'
        f'<td class="num">{r["n"]}</td><td class="num">{_fmt_pct(r["convert_yes"])}</td>'
        f'<td class="num">{_fmt_pct(r["convert_maybe"])}</td><td class="num">{_fmt_pct(r["click_yes"])}</td>'
        f'<td class="num">{_num(r["interest"])}</td><td class="num">{_num(r["trust"])}</td>'
        f'<td>{_e(OBJECTION_LABELS.get(r["top_objection"], r["top_objection"] or "–"))}</td>'
        f'<td>{_e(r["top_message"] or "–")}</td></tr>' for r in rows)
    table = (f'<div class="tbl" style="margin-top:10px"><table><thead><tr><th>{_e(label)}</th><th class="num">People</th>'
             '<th class="num">Would convert</th><th class="num">Maybe</th><th class="num">Would click</th>'
             '<th class="num">Interest</th><th class="num">Trust</th><th>Top objection</th><th>Best message</th>'
             f'</tr></thead><tbody>{body}</tbody></table></div>')
    return ch + table


def hero_stats(a: Dict[str, Any]) -> str:
    """Big numbers for the page header (HYVE-style stats row)."""
    if not a.get("has_survey"):
        items = [(str(a.get("people") or 0), "Simulated people"), (str(a.get("engaged") or 0), "Joined the conversation")]
    else:
        o = a["overall"]
        items = [(_fmt_pct(o["convert_yes"]), f"Would {_goal_verb(a.get('goal'))}"),
                 (_fmt_pct(o["click_yes"]), "Would click"), (str(a["answered"]), "People surveyed")]
    return '<div class="hero-stats">' + "".join(
        f'<div><div class="v">{_e(v)}</div><div class="k">{_e(k)}</div></div>' for v, k in items) + "</div>"


def render_sections(a: Dict[str, Any]) -> List[Tuple[str, str, str]]:
    """[(anchor, nav label, section html)] for the marketing part of the dashboard."""
    sections: List[Tuple[str, str, str]] = []
    if not a.get("has_survey"):
        eng = a.get("engagement_by_segment") or []
        body = '<p class="empty">No activity yet.</p>'
        if eng:
            body = chart("bars", {"cats": [r["key"] for r in eng], "values": [r["actions_per_person"] for r in eng],
                                  "highlight": 0, "notes": [f'{_fmt_pct(r["engaged"])} took part' for r in eng]},
                         40 + 34 * len(eng), "Actions per person by segment") + _table_view(
                ["Segment", "People", "Took part", "Actions per person"],
                [[r["key"], r["n"], _fmt_pct(r["engaged"]), r["actions_per_person"]] for r in eng])
        sections.append(("results", "Results", (
            '<h2>Marketing results</h2><div class="mm-top"><div class="panel"><div class="eyebrow">Next step</div>'
            '<div class="headline">Run the buyer survey to see who would click, convert and why not.</div>'
            '<p style="margin:0;color:var(--mm-panel-muted)"><code>mirofish.py survey --simulation &lt;id&gt; --offer "..." '
            '--goal "..." --messages @ads.txt --split</code></p></div>'
            f'<div class="card"><h3>Who is talking most</h3>{body}</div></div>')))
        return sections

    o = a["overall"]
    verdicts_ = a.get("verdicts") or []
    panel = ('<div class="panel"><div class="eyebrow">What the simulation says</div>'
             f'<div class="headline">{_e(verdicts_[0] if verdicts_ else "")}</div>'
             '<ul class="verdicts">' + "".join(f"<li>{_e(v)}</li>" for v in verdicts_[1:]) + "</ul></div>")
    kpis = [
        ("Would " + _goal_verb(a.get("goal")), _fmt_pct(o["convert_yes"]), f'+{_fmt_pct(o["convert_maybe"])} maybe', True),
        ("Would click", _fmt_pct(o["click_yes"]), f'+{_fmt_pct(o["click_maybe"])} maybe', False),
        ("Interest", f'{o["interest"]}/10' if o["interest"] is not None else "–", "average", False),
        ("Trust", f'{o["trust"]}/10' if o["trust"] is not None else "–", "average", False),
        ("Word of mouth", f'{o["nps"]:+d}' if o["nps"] is not None else "–", "NPS-style, −100 to +100", False),
        ("People surveyed", str(a["answered"]), f'of {a["people"]} simulated · {a["engaged"]} joined the conversation', False),
    ]
    kpi_html = '<div class="kpis">' + "".join(
        f'<div class="kpi{" hl" if hl else ""}"><div class="v">{_e(v)}</div><div class="k">{_e(k)}</div>'
        f'<div class="h">{_e(h)}</div></div>' for k, v, h, hl in kpis) + "</div>"
    offer = ""
    if a.get("offer") or a.get("goal"):
        offer = ('<p style="display:flex;gap:8px;flex-wrap:wrap;margin:0 0 12px">'
                 + (f'<span class="pill accent">Offer: {_e(a.get("offer"))}</span>' if a.get("offer") else "")
                 + (f'<span class="pill">Goal: {_e(a.get("goal"))}</span>' if a.get("goal") else "")
                 + (f'<span class="pill sky">Split test of {len(a.get("messages") or [])} messages</span>' if a.get("split_test") else "")
                 + "</p>")
    sections.append(("results", "Results", f'<h2>Marketing results</h2>{offer}<div class="mm-top">{panel}{kpi_html}</div>'))

    plays = a.get("playbook") or []
    if plays:
        cards = "".join(
            f'<div class="play p-{p["priority"]}"><div class="play-h"><strong>{_e(p["segment"])}</strong>'
            f'<span class="pill {"accent" if p["priority"] == "high" else "mint" if p["priority"] == "medium" else ""}">'
            f'{_e(p["priority"])} priority · {_fmt_pct(p["convert_yes"])}</span></div><dl>'
            + (f'<dt>Lead with</dt><dd>{_e(trunc_text(p["lead_with"], 160))}</dd>' if p.get("lead_with") else "")
            + (f'<dt>Pre-empt</dt><dd>{_e(p["preempt"])}</dd>' if p.get("preempt") else "")
            + (f'<dt>Answer with</dt><dd>{_e(trunc_text(p["answer_with"], 200))}</dd>' if p.get("answer_with") else "")
            + (f'<dt>Seed it in</dt><dd>{_e(p["seed_in"])}</dd>' if p.get("seed_in") else "")
            + (f'<dt>Proof line</dt><dd>“{_e(trunc_text(p["proof_quote"], 180))}”</dd>' if p.get("proof_quote") else "")
            + "</dl></div>" for p in plays)
        sections.append(("playbook", "Playbook", '<h2>Sales &amp; marketing playbook</h2>'
                         '<p class="muted small">One card per audience, highest priority first. Built from what the '
                         'simulated people said: confirm on real traffic before scaling spend.</p>'
                         f'<div class="plays">{cards}</div>'))

    fn = a["funnel"]
    fn_chart = chart("funnel", {"stages": [x[0] for x in fn], "values": [x[1] for x in fn]}, 48 * len(fn) + 12,
                     "Funnel from simulated people to would convert")
    fn_rows, prev = [], None
    for label, v in fn:
        fn_rows.append([label, v, "–" if not prev else f"{100 * v / prev:.0f}%"])
        prev = v
    sections.append(("funnel", "Funnel", '<h2>Funnel</h2><div class="card"><p class="muted small">From everyone simulated '
                     'to people who say they would act. Hover a step for the drop-off.</p>'
                     f'{fn_chart}{_table_view(["Step", "People", "Of previous step"], fn_rows)}</div>'))

    tabs = [("segment", "Segment", a["by_segment"]), ("country", "Country", a["by_country"]),
            ("community", "Community", a["by_community"]), ("age", "Age", a["by_age"]),
            ("gender", "Gender", a["by_gender"])]
    tabs = [t for t in tabs if t[2]]
    tab_btns = "".join(f'<button type="button" data-panel="{k}" aria-pressed="{"true" if i == 0 else "false"}">{_e(lbl)}</button>'
                       for i, (k, lbl, _) in enumerate(tabs))
    panels = "".join(f'<div class="seg-panel" data-panel="{k}"{"" if i == 0 else " hidden"}>{_breakdown_block(rows_, lbl)}</div>'
                     for i, (k, lbl, rows_) in enumerate(tabs))
    sections.append(("audiences", "Audiences", '<h2>Which audience to target</h2><div class="card">'
                     f'<div class="seg-tabs" role="group" aria-label="Break down by">{tab_btns}</div>'
                     '<p class="muted small" style="margin-top:0">Sorted best first. Blue = would convert, grey = maybe, '
                     f'red = no.</p>{panels}</div>'))

    objs = a.get("objections") or []
    obj_chart = '<p class="empty">No objections raised.</p>'
    if objs:
        obj_chart = chart("bars", {"cats": [x["label"] for x in objs], "values": [x["share"] or 0 for x in objs],
                                   "unit": "%", "highlight": 0, "notes": [f'{x["count"]} people' for x in objs]},
                          40 + 34 * len(objs), "Share of people raising each objection") + _table_view(
            ["Objection", "People", "Share"], [[x["label"], x["count"], _fmt_pct(x["share"])] for x in objs])
    obj_examples = "".join(
        f'<div class="quote"><span class="pill orchid">{_e(x["label"])}</span>'
        + "".join(f'<p style="margin-top:8px">“{_e(trunc_text(ex["text"], 220))}”</p><div class="who">{_e(ex["name"])} · '
                  f'{_e(ex["segment"])}' + (f' · would say yes if: {_e(trunc_text(ex["fix"], 140))}' if ex.get("fix") else "")
                  + "</div>" for ex in x["examples"][:2]) + "</div>" for x in objs[:4])
    sections.append(("objections", "Objections", '<h2>What stops people</h2><div class="grid2">'
                     f'<div class="card"><h3>Objections</h3>{obj_chart}</div>'
                     f'<div class="card"><h3>In their words</h3><div class="quotes">{obj_examples or "<p class=empty>None.</p>"}</div></div></div>'))

    msgs = a.get("messages_ranked") or []
    if msgs:
        split = a.get("split_test")
        msg_chart = chart("bars", {"cats": [trunc_text(m["label"], 46) for m in msgs],
                                   "values": [m["convert_yes"] or 0 for m in msgs], "unit": "%", "max": 100,
                                   "highlight": 0, "notes": [f'{m["votes"]} people' for m in msgs]},
                          40 + 38 * len(msgs), "Would convert by message")
        head = (["Message", "Shown to", "Would convert", "Would click", "Reaction"] if split
                else ["Message", "Picked by", "Share", "Of them would convert"])
        rows_ = ([[m["label"], m["votes"], _fmt_pct(m["convert_yes"]), _fmt_pct(m.get("click_yes")), _num(m.get("reaction"))]
                  for m in msgs] if split else
                 [[m["label"], m["votes"], _fmt_pct(m["share"]), _fmt_pct(m["convert_yes"])] for m in msgs])
        note = ("Each person saw one message, assigned at random in equal groups, so the bars compare like with like."
                if split else "People saw every message and picked the one that works best for them.")
        grid = a.get("message_grid") or {}
        heat = ""
        if grid.get("rows") and grid.get("messages"):
            xs, ys = grid["messages"], [r["segment"] for r in grid["rows"]]
            cells = [[xi, yi, round(r["cells"][m]["convert_yes"] or 0), r["cells"][m]["n"]]
                     for yi, r in enumerate(grid["rows"]) for xi, m in enumerate(xs) if m in r["cells"]]
            heat = ('<h3 style="margin-top:18px">Best message for each audience</h3><p class="muted small">Share who would '
                    'convert. Darker = better. Small cells are noisy.</p>'
                    + chart("heat", {"x": xs, "y": ys, "cells": cells}, 60 + 46 * len(ys), "Would convert by audience and message")
                    + _table_view(["Audience"] + xs, [[r["segment"]] + [
                        f'{_fmt_pct(r["cells"][m]["convert_yes"])} (n={r["cells"][m]["n"]})' if m in r["cells"] else "–"
                        for m in xs] for r in grid["rows"]]))
        sections.append(("messages", "Messages", f'<h2>Which message wins{" (split test)" if split else ""}</h2>'
                         f'<div class="card"><p class="muted small">{_e(note)}</p>{msg_chart}{_table_view(head, rows_)}{heat}</div>'))

    pr = a.get("pricing")
    if pr:
        med = pr["median"]
        lo, hi, opt = pr.get("acceptable_low"), pr.get("acceptable_high"), pr.get("optimal")
        cur = (a.get("currency") or "")
        price_chart = chart("price", {"curves": pr["curves"], "low": lo, "high": hi, "opt": opt, "currency": cur},
                            340, "Van Westendorp price sensitivity curves")
        sections.append(("pricing", "Pricing", '<h2>What people would pay</h2><div class="grid2">'
                         '<div class="kpis" style="align-content:start">'
                         f'<div class="kpi hl"><div class="v">{_num(lo)} – {_num(hi)}</div><div class="k">Acceptable range {_e(cur)}</div></div>'
                         f'<div class="kpi"><div class="v">{_num(opt)}</div><div class="k">Sweet spot</div></div>'
                         f'<div class="kpi"><div class="v">{_num(med.get("price_cheap"))}</div><div class="k">Median "bargain"</div></div>'
                         f'<div class="kpi"><div class="v">{_num(med.get("price_too_expensive"))}</div><div class="k">Median "never pay"</div></div></div>'
                         f'<div class="card"><h3>Price sensitivity</h3>{price_chart}'
                         + _table_view(["Segment", "Answers", "Bargain", "Getting expensive", "Never pay"],
                                       [[s["key"], s["n"], _num(s["cheap"]), _num(s["expensive"]), _num(s["too_expensive"])]
                                        for s in pr["by_segment"]], "Show prices by segment")
                         + f'<p class="muted small">Van Westendorp method, {pr["answers"]} answers. The shaded band is '
                         'the acceptable range; the line is the sweet spot.</p></div></div>'))

    def qcards(qs):
        return "".join(f'<div class="quote"><p>“{_e(trunc_text(q["text"], 260))}”</p><div class="who">{_e(q["name"])} · '
                       f'{_e(q["segment"])} · {_e(q["country"])}</div></div>' for q in qs) or '<p class="empty">None.</p>'
    change = "".join(f'<li><span class="pill">{_e(c["segment"])}</span> {_e(trunc_text(c["text"], 200))}</li>'
                     for c in a.get("change_mind") or [])
    sections.append(("voices", "Voices", '<h2>Voice of the customer</h2><div class="grid2">'
                     f'<div class="card"><h3><span class="pill mint">Would say yes</span></h3><div class="quotes">{qcards(a.get("quotes_yes") or [])}</div></div>'
                     f'<div class="card"><h3><span class="pill orchid">Would say no</span></h3><div class="quotes">{qcards(a.get("quotes_no") or [])}</div></div></div>'
                     + (f'<div class="card" style="margin-top:14px"><h3>What would change their mind</h3>'
                        f'<ul style="display:grid;gap:8px;padding-left:18px">{change}</ul></div>' if change else "")))
    return sections


def summary_block(a: Dict[str, Any]) -> Dict[str, Any]:
    """Compact numbers for summary.json."""
    if not a.get("has_survey"):
        return {"has_survey": False, "people": a.get("people"), "engaged": a.get("engaged"),
                "engagement_by_segment": a.get("engagement_by_segment")}
    keep = ("has_survey", "people", "engaged", "answered", "offer", "goal", "overall", "funnel", "verdicts",
            "by_segment", "by_country", "by_community", "by_age", "objections", "messages_ranked", "split_test",
            "message_grid", "pricing", "playbook")
    out = {k: a.get(k) for k in keep}
    out["objections"] = [{k: v for k, v in x.items() if k != "examples"} for x in a.get("objections") or []]
    if out.get("pricing"):
        out["pricing"] = {k: v for k, v in out["pricing"].items() if k != "curves"}
    return out
