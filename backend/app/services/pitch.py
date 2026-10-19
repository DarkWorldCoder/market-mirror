"""Sales rehearsal: pitch a script to every simulated buyer, collect objections, answer them with rebuttals.

Turn 1: each person hears the pitch (as a message, call or demo) and answers as themselves: verdict, objection,
the question they would ask back. Turn 2: people who objected hear the rebuttal written for their objection type
(or the generic one) and say whether it moved them. The result scores the pitch, every rebuttal and every person
(lead score 0-100), so sales people see which objections the pitch cannot handle yet, which rebuttal works, and
whom to call first. Pure functions here; the API in market.py runs the interviews.
"""

import json
import re
from collections import Counter, defaultdict
from typing import Any, Callable, Dict, List, Optional

OBJECTION_TYPES = ["price", "trust", "relevance", "timing", "effort", "unclear", "privacy", "language",
                   "competitor", "authority", "none", "other"]
VERDICT_SCORE = {"yes": 1.0, "maybe": 0.5, "no": 0.0}


def pitch_prompt(script: str, product: str = "", channel: str = "message", seller: str = "a salesperson") -> str:
    how = {"call": "calls you", "demo": "shows you a short demo and says", "email": "emails you",
           "dm": "sends you a direct message"}.get(channel, "sends you a message")
    return (
        f"Step out of the feed for a moment. {seller[:80]} {how}"
        + (f" about {product[:200]}" if product else "") + ". Here is exactly what they say:\n\n"
        f"\"\"\"\n{script[:5000]}\n\"\"\"\n\n"
        "React as yourself, honestly, the way you really would: busy, maybe sceptical, maybe interested. "
        "It is fine to say no, to not care, or to ask a hard question back. Write your spoken reply in the "
        "language you normally use with strangers (plain English or your own script, not Latin-letter Hindi/Tagalog).\n"
        "Reply with only this JSON, no other text:\n"
        '{"reply": "what you would actually say back, 1-3 sentences, in your own voice", '
        '"verdict": "yes|maybe|no" (would you take the next step they ask for), '
        '"interest": 0-10, "trust": 0-10, '
        '"objection": "your biggest hesitation in one sentence, or empty", '
        '"objection_type": "price|trust|relevance|timing|effort|unclear|privacy|language|competitor|authority|none|other", '
        '"question_for_seller": "the one question you would ask them, or empty", '
        '"what_would_convince": "what they would have to say or show for you to say yes, one sentence", '
        '"decision_role": "I decide alone|I ask my partner/family|I ask my boss|not my decision", '
        '"best_time_to_reach": "when and where they should contact you (channel, time of day)"}'
    )


def rebuttal_prompt(prior: Dict[str, Any], rebuttal: str) -> str:
    return (
        "Same conversation, a moment later. You just said: "
        f"\"{str(prior.get('reply') or prior.get('objection') or '')[:400]}\". "
        f"The salesperson answers:\n\n\"\"\"\n{rebuttal[:2500]}\n\"\"\"\n\n"
        "Be honest: did that answer your hesitation, partly, or not at all? People rarely flip from no to yes "
        "because of one sentence; say what you really think now.\n"
        "Reply with only this JSON, no other text:\n"
        '{"reply": "what you say back, 1-2 sentences, in your own voice", '
        '"verdict": "yes|maybe|no" (would you take the next step now), '
        '"moved": "yes|partly|no" (did the answer change your mind), '
        '"remaining_objection": "what still holds you back, one sentence, or empty", '
        '"next_step_you_accept": "what you would agree to now: a call, a trial, a demo, more info, nothing"}'
    )


def _extract_json(text: Any) -> Optional[Dict[str, Any]]:
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


def _ynm(v: Any) -> Optional[str]:
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (int, float)):
        return "yes" if v >= 7 else "maybe" if v >= 4 else "no"
    s = str(v or "").strip().lower()
    if not s:
        return None
    if s.startswith(("maybe", "perhaps", "possibly", "not sure", "unsure", "might", "depends", "partly")):
        return "maybe"
    if s.startswith(("probably not", "unlikely", "never", "no", "nah", "nope")):
        return "no"
    if s.startswith(("yes", "yeah", "yep", "definitely", "sure", "probably", "likely", "absolutely")):
        return "yes"
    return None


def _score(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return 10.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(max(0, min(10, v)))
    m = re.search(r"\d+(\.\d+)?", str(v or ""))
    return float(max(0, min(10, float(m.group(0))))) if m else None


def parse_turn1(text: Any) -> Optional[Dict[str, Any]]:
    d = _extract_json(text)
    if not d:
        return None
    ot = str(d.get("objection_type") or "").strip().lower()
    if ot not in OBJECTION_TYPES:
        ot = "none" if not d.get("objection") else "other"
    out = {"reply": str(d.get("reply") or "").strip()[:400], "verdict": _ynm(d.get("verdict")),
           "interest": _score(d.get("interest")), "trust": _score(d.get("trust")),
           "objection": str(d.get("objection") or "").strip()[:300], "objection_type": ot,
           "question_for_seller": str(d.get("question_for_seller") or "").strip()[:300],
           "what_would_convince": str(d.get("what_would_convince") or "").strip()[:300],
           "decision_role": str(d.get("decision_role") or "").strip()[:60],
           "best_time_to_reach": str(d.get("best_time_to_reach") or "").strip()[:120]}
    if out["verdict"] is None and not out["reply"]:
        return None
    return out


def parse_turn2(text: Any) -> Optional[Dict[str, Any]]:
    d = _extract_json(text)
    if not d:
        return None
    moved = str(d.get("moved") or "").strip().lower()
    moved = "yes" if moved.startswith("yes") else "partly" if moved.startswith(("part", "some", "a bit")) else "no"
    return {"reply": str(d.get("reply") or "").strip()[:400], "verdict": _ynm(d.get("verdict")), "moved": moved,
            "remaining_objection": str(d.get("remaining_objection") or "").strip()[:300],
            "next_step": str(d.get("next_step_you_accept") or "").strip()[:120]}


def pick_rebuttal(objection_type: str, rebuttals: Dict[str, str]) -> Optional[str]:
    """rebuttals: {"price": "...", "trust": "...", "*": "generic"}; None when nothing fits."""
    if not rebuttals or objection_type in ("none", ""):
        return None
    return rebuttals.get(objection_type) or rebuttals.get("*") or rebuttals.get("default")


def parse_rebuttals(text_or_dict: Any) -> Dict[str, str]:
    """A dict, a JSON object, or a Markdown file with '## price' / '## trust' / '## any' headings."""
    if isinstance(text_or_dict, dict):
        return {str(k).strip().lower(): str(v) for k, v in text_or_dict.items() if str(v).strip()}
    s = str(text_or_dict or "").strip()
    if not s:
        return {}
    j = _extract_json(s)
    if j:
        return parse_rebuttals(j)
    out: Dict[str, str] = {}
    key = None
    for line in s.splitlines():
        m = re.match(r"^\s*#{1,3}\s*([A-Za-z*/ ]+)\s*$", line)
        if m:
            key = m.group(1).strip().lower()
            key = "*" if key in ("any", "generic", "default", "*", "all") else key
            out[key] = ""
        elif key is not None:
            out[key] = (out[key] + "\n" + line).strip()
    if not out:
        out["*"] = s
    return {k: v for k, v in out.items() if v}


def lead_score(t1: Optional[Dict[str, Any]], t2: Optional[Dict[str, Any]]) -> Optional[int]:
    if not t1:
        return None
    final = (t2 or {}).get("verdict") or t1.get("verdict")
    base = {"yes": 70, "maybe": 40, "no": 10}.get(final or "", 20)
    base += 0.15 * (t1.get("interest") or 0) * 10 * 0.5          # up to +7.5
    base += 0.10 * (t1.get("trust") or 0) * 10 * 0.5             # up to +5
    if t2:
        base += {"yes": 10, "partly": 5, "no": -5}.get(t2.get("moved"), 0)
    elif t1.get("verdict") == "yes":
        base += 10                                              # said yes without needing a rebuttal
    role = (t1.get("decision_role") or "").lower()
    if "alone" in role:
        base += 5
    elif "not my" in role:
        base -= 10
    if t1.get("objection_type") == "none":
        base += 5
    return int(max(0, min(100, round(base))))


def score(people: List[Dict[str, Any]], turn1: Dict[int, Optional[Dict[str, Any]]],
          turn2: Dict[int, Optional[Dict[str, Any]]], rebuttals: Dict[str, str]) -> Dict[str, Any]:
    """Aggregate both turns into the pitch.json summary."""
    rows = []
    for p in people:
        aid = p["agent_id"]
        t1, t2 = turn1.get(aid), turn2.get(aid)
        rows.append({"agent_id": aid, "name": p.get("name"), "segment": p.get("segment"), "country": p.get("country"),
                     "turn1": t1, "turn2": t2, "final_verdict": ((t2 or {}).get("verdict") or (t1 or {}).get("verdict")),
                     "lead_score": lead_score(t1, t2)})
    answered = [r for r in rows if r["turn1"]]
    n = len(answered)

    def mix(key: Callable[[Dict[str, Any]], Optional[str]]) -> Dict[str, float]:
        c = Counter(key(r) for r in answered)
        return {v: round(100.0 * c.get(v, 0) / n, 1) if n else 0.0 for v in ("yes", "maybe", "no")}

    before = mix(lambda r: r["turn1"].get("verdict"))
    after = mix(lambda r: r["final_verdict"])
    pitch_score = round(100 * sum(VERDICT_SCORE.get(r["final_verdict"] or "", 0) for r in answered) / n) if n else 0

    by_obj: Dict[str, Dict[str, Any]] = {}
    for r in answered:
        ot = r["turn1"].get("objection_type") or "other"
        b = by_obj.setdefault(ot, {"type": ot, "count": 0, "examples": [], "questions": [], "rebuttal": pick_rebuttal(ot, rebuttals),
                                   "answered": 0, "moved_yes": 0, "moved_partly": 0, "moved_no": 0, "segments": Counter()})
        b["count"] += 1
        b["segments"][r.get("segment") or "?"] += 1
        if r["turn1"].get("objection") and len(b["examples"]) < 4:
            b["examples"].append({"who": r.get("name"), "segment": r.get("segment"), "text": r["turn1"]["objection"]})
        if r["turn1"].get("question_for_seller") and len(b["questions"]) < 4:
            b["questions"].append(r["turn1"]["question_for_seller"])
        if r["turn2"]:
            b["answered"] += 1
            b["moved_" + r["turn2"]["moved"]] += 1
    objections = []
    for b in sorted(by_obj.values(), key=lambda x: -x["count"]):
        b["share"] = round(100.0 * b["count"] / n, 1) if n else 0.0
        b["rebuttal_success"] = round(100.0 * (b["moved_yes"] + 0.5 * b["moved_partly"]) / b["answered"], 1) if b["answered"] else None
        b["segments"] = dict(b["segments"].most_common(4))
        objections.append(b)

    seg_rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in answered:
        seg_rows[r.get("segment") or "Everyone"].append(r)
    by_segment = []
    for seg, rs in sorted(seg_rows.items(), key=lambda kv: -len(kv[1])):
        c = Counter(r["final_verdict"] for r in rs)
        top = Counter(r["turn1"].get("objection_type") for r in rs).most_common(1)
        by_segment.append({"segment": seg, "n": len(rs), "yes": round(100.0 * c.get("yes", 0) / len(rs), 1),
                           "maybe": round(100.0 * c.get("maybe", 0) / len(rs), 1), "no": round(100.0 * c.get("no", 0) / len(rs), 1),
                           "lead_score": round(sum(r["lead_score"] or 0 for r in rs) / len(rs)),
                           "top_objection": top[0][0] if top else None})

    unhandled = [o for o in objections if o["type"] != "none" and (o["rebuttal"] is None or (o["rebuttal_success"] or 0) < 60)]
    fixes = [(f"Write a better answer for '{o['type']}' objections ({o['share']}% raised it"
              + (f", current rebuttal moved {o['rebuttal_success']}%" if o["rebuttal_success"] is not None else ", no rebuttal given") + ")")
             for o in unhandled[:4]]
    quotes = sorted((r for r in answered if r["turn1"].get("reply")), key=lambda r: -(r["lead_score"] or 0))
    hot = [{"name": r["name"], "segment": r["segment"], "lead_score": r["lead_score"], "verdict": r["final_verdict"],
            "reach": r["turn1"].get("best_time_to_reach"), "next_step": (r["turn2"] or {}).get("next_step") or ""}
           for r in sorted(answered, key=lambda r: -(r["lead_score"] or 0)) if (r["lead_score"] or 0) >= 55][:15]
    return {"people_pitched": len(rows), "answered": n, "pitch_score": pitch_score, "verdict_before": before,
            "verdict_after": after, "rebuttals_given": len(rebuttals), "objections": objections, "by_segment": by_segment,
            "hot_leads": hot, "fixes": fixes,
            "best_replies": [{"name": r["name"], "segment": r["segment"], "text": r["turn1"]["reply"]} for r in quotes[:3]],
            "worst_replies": [{"name": r["name"], "segment": r["segment"], "text": r["turn1"]["reply"]} for r in quotes[-3:][::-1]],
            "decision_roles": dict(Counter(r["turn1"].get("decision_role") for r in answered if r["turn1"].get("decision_role")).most_common(5)),
            "people": rows}


def run(interview_batch: Callable[[List[Dict[str, Any]]], Dict[int, str]], people: List[Dict[str, Any]],
        script: str, rebuttals: Dict[str, str], product: str = "", channel: str = "message",
        batch: int = 8, progress: Optional[Callable[[int, int], None]] = None) -> Dict[str, Any]:
    """interview_batch([{agent_id, prompt}]) -> {agent_id: reply text}. Two turns, batched."""
    turn1: Dict[int, Optional[Dict[str, Any]]] = {}
    turn2: Dict[int, Optional[Dict[str, Any]]] = {}
    total = len(people) * (2 if rebuttals else 1)
    done = 0
    for i in range(0, len(people), max(1, batch)):
        chunk = people[i:i + batch]
        texts = interview_batch([{"agent_id": p["agent_id"], "prompt": (p.get("history") or "") + pitch_prompt(script, product, channel)}
                                 for p in chunk])
        for p in chunk:
            turn1[p["agent_id"]] = parse_turn1(texts.get(p["agent_id"]))
        done += len(chunk)
        if progress:
            progress(done, total)
    if rebuttals:
        second = [(p, pick_rebuttal((turn1.get(p["agent_id"]) or {}).get("objection_type") or "", rebuttals))
                  for p in people if turn1.get(p["agent_id"]) and (turn1[p["agent_id"]].get("verdict") != "yes")]
        second = [(p, rb) for p, rb in second if rb]
        for i in range(0, len(second), max(1, batch)):
            chunk = second[i:i + batch]
            texts = interview_batch([{"agent_id": p["agent_id"], "prompt": rebuttal_prompt(turn1[p["agent_id"]], rb)}
                                     for p, rb in chunk])
            for p, _ in chunk:
                turn2[p["agent_id"]] = parse_turn2(texts.get(p["agent_id"]))
            done += len(chunk)
            if progress:
                progress(min(done, total), total)
    try:                                                   # free-text intent rating of the replies (SSR), no LLM calls
        from . import ssr
        items = [(p["agent_id"], (turn1.get(p["agent_id"]) or {}).get("reply") or "") for p in people]
        rated = ssr.rate([("purchase", t) for _, t in items])
        for (aid, _), r in zip(items, rated):
            if r and turn1.get(aid) is not None:
                turn1[aid]["ssr_purchase"] = {"mean": r.get("mean"), "sd": r.get("sd")}
    except Exception:  # noqa: BLE001 - optional
        pass
    out = score(people, turn1, turn2, rebuttals)
    means = [t["ssr_purchase"]["mean"] for t in turn1.values() if t and t.get("ssr_purchase") and t["ssr_purchase"].get("mean") is not None]
    out["ssr_purchase_mean"] = round(sum(means) / len(means), 2) if means else None
    out["script"] = script[:5000]
    out["channel"] = channel
    out["rebuttals"] = rebuttals
    return out
