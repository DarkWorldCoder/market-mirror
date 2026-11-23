"""Bring your own questionnaire: the saved simulated people answer your questions, not ours.

The buyer survey asks a fixed set of questions. Brand trackers, concept surveys, onboarding polls and customer
questionnaires use their own wording and scales, so this takes the questions as you wrote them:
  scale   rating from `low` to `high` (default 1-5), with optional end labels
  nps     0-10 "how likely to recommend", reported as an NPS score
  choice  one of `options`
  multi   any of `options`
  open    free text

Two known weaknesses of model answers are handled in the open:
- Position bias: models favour options by where they appear. Every person sees the options of each choice and multi
  question in their own seeded order, the order is saved, and `position_check` reports how often the first option
  shown was picked against the 1/k expected from shuffling alone.
- Too little spread: simulated answers cluster more than real ones (154 of 164 outcomes across 19 studies, arXiv
  2509.19088). A scale whose answers barely vary, or a question where one answer takes 90% or more, is flagged
  `too_alike`. `calibrate` against real answers to the same questions is the check.

An answer outside the allowed values is recorded as missing, never coerced. Results are simulated directions.
Stdlib only; `complete(system, user) -> (text, usage)` is injected, as in focus_group.
"""

from __future__ import annotations

import json
import random
import re
import statistics
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .focus_group import Meter, rebuild

VERSION = 1
TYPES = ("scale", "nps", "choice", "multi", "open")
MAX_QUESTIONS = 25
MAX_OPTIONS = 12

Complete = Callable[[str, str], Tuple[str, Dict[str, Any]]]

_LINE_SCALE = re.compile(r"\[(\d+)\s*-\s*(\d+)\]\s*$")
_LINE_CHOICE = re.compile(r"\{([^{}]+)\}\s*$")


def _clean(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def parse_lines(text: str) -> List[Dict[str, Any]]:
    """One question per line. Ends with [1-5] -> scale, {A | B | C} -> choice, {A | B}+ -> multi, [nps] -> nps,
    anything else -> open. Blank lines and lines starting with # are skipped."""
    out = []
    for raw in text.splitlines():
        line = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", raw).strip()
        if not line or raw.strip().startswith("#"):
            continue
        if line.lower().endswith("[nps]"):
            out.append({"text": line[:-5].strip(), "type": "nps"})
        elif (m := _LINE_SCALE.search(line)):
            out.append({"text": line[:m.start()].strip(), "type": "scale", "low": int(m[1]), "high": int(m[2])})
        elif line.endswith("}+") and (m := _LINE_CHOICE.search(line[:-1])):
            out.append({"text": line[:m.start()].strip(), "type": "multi", "options": m[1].split("|")})
        elif (m := _LINE_CHOICE.search(line)):
            out.append({"text": line[:m.start()].strip(), "type": "choice", "options": m[1].split("|")})
        else:
            out.append({"text": line, "type": "open"})
    return out


def normalize(spec: Any) -> Dict[str, Any]:
    """{title?, intro?, questions: [...]} or a list of questions or text lines -> a checked spec. Raises ValueError."""
    if isinstance(spec, str):
        stripped = spec.strip()
        spec = json.loads(stripped) if stripped[:1] in "[{" else parse_lines(stripped)
    if isinstance(spec, list):
        spec = {"questions": spec}
    if not isinstance(spec, dict) or not isinstance(spec.get("questions"), list) or not spec["questions"]:
        raise ValueError("questions must be a non-empty list")
    if len(spec["questions"]) > MAX_QUESTIONS:
        raise ValueError(f"at most {MAX_QUESTIONS} questions per questionnaire")
    questions, seen = [], set()
    for i, q in enumerate(spec["questions"]):
        q = {"text": q} if isinstance(q, str) else q
        if not isinstance(q, dict) or not _clean(q.get("text"), 600):
            raise ValueError(f"question {i + 1} needs text")
        kind = str(q.get("type") or "open").lower()
        if kind not in TYPES:
            raise ValueError(f"question {i + 1}: type must be one of {', '.join(TYPES)}")
        qid = re.sub(r"[^a-z0-9_]", "_", str(q.get("id") or f"q{i + 1}").lower())[:40]
        if qid in seen:
            raise ValueError(f"question id {qid} is used twice")
        seen.add(qid)
        item: Dict[str, Any] = {"id": qid, "text": _clean(q["text"], 600), "type": kind}
        if kind in ("choice", "multi"):
            opts = list(dict.fromkeys(_clean(o, 120) for o in (q.get("options") or []) if _clean(o, 120)))
            if not 2 <= len(opts) <= MAX_OPTIONS:
                raise ValueError(f"question {i + 1}: give 2 to {MAX_OPTIONS} different options")
            item["options"] = opts
        if kind == "scale":
            low, high = q.get("low", 1), q.get("high", 5)
            if isinstance(low, bool) or isinstance(high, bool) or not isinstance(low, int) or not isinstance(high, int) \
                    or not 0 <= low < high <= 10:
                raise ValueError(f"question {i + 1}: scale needs whole numbers with 0 <= low < high <= 10")
            item.update(low=low, high=high, low_label=_clean(q.get("low_label"), 60), high_label=_clean(q.get("high_label"), 60))
        if kind == "nps":
            item.update(low=0, high=10)
        questions.append(item)
    return {"title": _clean(spec.get("title"), 160), "intro": _clean(spec.get("intro"), 1200), "questions": questions}


def option_order(question: Dict[str, Any], agent_id: Any, seed: int) -> List[str]:
    """This person's order for a choice or multi question: seeded by seed, person and question, so it is stable."""
    opts = list(question["options"])
    random.Random(f"{seed}:{agent_id}:{question['id']}").shuffle(opts)
    return opts


def prompt(spec: Dict[str, Any], agent_id: Any, seed: int) -> Tuple[str, Dict[str, List[str]]]:
    """The user message for one person, and the option order they were shown."""
    lines, orders = [], {}
    for n, q in enumerate(spec["questions"], 1):
        if q["type"] in ("choice", "multi"):
            orders[q["id"]] = option_order(q, agent_id, seed)
            how = ("pick exactly one, copied exactly" if q["type"] == "choice" else "a list of every one that applies, copied exactly, or []")
            lines.append(f'{n}. [{q["id"]}] {q["text"]}\n   Options: ' + " | ".join(orders[q["id"]]) + f"\n   Answer: {how}")
        elif q["type"] in ("scale", "nps"):
            ends = ""
            if q["type"] == "nps":
                ends = " (0 = not at all likely, 10 = extremely likely)"
            elif q.get("low_label") or q.get("high_label"):
                ends = f' ({q["low"]} = {q.get("low_label") or "lowest"}, {q["high"]} = {q.get("high_label") or "highest"})'
            lines.append(f'{n}. [{q["id"]}] {q["text"]}\n   Answer: a whole number from {q["low"]} to {q["high"]}{ends}')
        else:
            lines.append(f'{n}. [{q["id"]}] {q["text"]}\n   Answer: one or two sentences in your own words')
    keys = ", ".join(f'"{q["id"]}": ...' for q in spec["questions"])
    user = ((f"{spec['intro']}\n\n" if spec.get("intro") else "")
            + "A researcher asks you to fill in this questionnaire. Answer every question as yourself, honestly. "
              "It is fine to be negative, unsure or uninterested; use the low end of a scale when that is the truth.\n\n"
            + "\n".join(lines)
            + f'\n\nReply with JSON only: {{"answers": {{{keys}}}}}')
    return user, orders


def _match(value: Any, options: Sequence[str]) -> Optional[str]:
    v = _clean(value, 200).strip("\"'“”").lower()
    return next((o for o in options if o.lower() == v), None)


def read(text: str, spec: Dict[str, Any]) -> Dict[str, Any]:
    """Model reply -> {question id: value or None}. Anything outside the allowed values is None, never coerced."""
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        data = json.loads(m.group(0)) if m else {}
    except ValueError:
        data = {}
    answers = data.get("answers") if isinstance(data.get("answers"), dict) else data
    out: Dict[str, Any] = {}
    for q in spec["questions"]:
        v = answers.get(q["id"]) if isinstance(answers, dict) else None
        if q["type"] in ("scale", "nps"):
            ok = isinstance(v, int) and not isinstance(v, bool) or (isinstance(v, float) and v.is_integer())
            out[q["id"]] = int(v) if ok and q["low"] <= v <= q["high"] else None
        elif q["type"] == "choice":
            out[q["id"]] = _match(v, q["options"])
        elif q["type"] == "multi":
            picked = [_match(x, q["options"]) for x in v] if isinstance(v, list) else None
            out[q["id"]] = None if picked is None or None in picked else list(dict.fromkeys(picked))
        else:
            out[q["id"]] = _clean(v, 600) or None
    return out


def _summary(q: Dict[str, Any], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    vals = [r["answers"].get(q["id"]) for r in rows]
    got = [v for v in vals if v is not None]
    s: Dict[str, Any] = {"n": len(got), "missing": len(vals) - len(got)}
    if not got:
        return s
    if q["type"] in ("scale", "nps"):
        counts = {str(k): sum(1 for v in got if v == k) for k in range(q["low"], q["high"] + 1)}
        sd = statistics.pstdev(got) if len(got) > 1 else 0.0
        s.update(distribution=counts, mean=round(statistics.fmean(got), 2), sd=round(sd, 2))
        if q["type"] == "nps":
            s["nps"] = round(100 * (sum(v >= 9 for v in got) - sum(v <= 6 for v in got)) / len(got))
        else:
            s["top_box"] = round(sum(v == q["high"] for v in got) / len(got), 3)
        top_share = max(counts.values()) / len(got)
        s["too_alike"] = len(got) >= 5 and (top_share >= 0.9 or sd < 0.1 * (q["high"] - q["low"]))
    elif q["type"] in ("choice", "multi"):
        flat = got if q["type"] == "choice" else [x for v in got for x in v]
        s["distribution"] = {o: sum(1 for x in flat if x == o) for o in q["options"]}
        s["shares"] = {o: round(c / len(got), 3) for o, c in s["distribution"].items()}
        if q["type"] == "choice":
            s["too_alike"] = len(got) >= 5 and max(s["distribution"].values()) / len(got) >= 0.9
    else:
        s["quotes"] = [{"agent_id": r["agent_id"], "segment": r.get("segment") or "", "text": r["answers"][q["id"]]}
                       for r in rows if r["answers"].get(q["id"])][:8]
    return s


def position_check(spec: Dict[str, Any], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """How often the option shown first was picked, against 1/k from the shuffle alone (choice questions)."""
    picked_first, expected, n = 0, 0.0, 0
    for q in spec["questions"]:
        if q["type"] != "choice":
            continue
        for r in rows:
            v, order = r["answers"].get(q["id"]), (r.get("order") or {}).get(q["id"])
            if v is None or not order:
                continue
            n += 1
            picked_first += v == order[0]
            expected += 1 / len(order)
    if not n:
        return {}
    share, exp = picked_first / n, expected / n
    return {"answers": n, "first_shown_share": round(share, 3), "expected_share": round(exp, 3),
            "flag": n >= 20 and share >= exp + 0.15}


def summarize(spec: Dict[str, Any], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    segments = sorted({str(r.get("segment") or "") for r in rows} - {""})
    out = []
    for q in spec["questions"]:
        item = {**q, "all": _summary(q, rows)}
        if len(segments) > 1:
            item["by_segment"] = {s: _summary(q, [r for r in rows if str(r.get("segment") or "") == s]) for s in segments}
        out.append(item)
    flagged = [q["id"] for q in out if q["all"].get("too_alike")]
    return {"questions": out, "segments": segments, "position_check": position_check(spec, rows),
            "too_alike": flagged}


def run(people: List[Dict[str, Any]], spec: Dict[str, Any], complete: Complete, parallel: int = 4, seed: int = 7,
        progress: Optional[Callable[[int, int], None]] = None) -> Dict[str, Any]:
    """Every person answers the whole questionnaire in one call. Returns the saved questionnaire.json content."""
    spec = normalize(spec)
    ask, done = Meter(complete), [0]

    def one(p):
        user, orders = prompt(spec, p.get("agent_id"), seed)
        try:
            text = ask(rebuild(p), user)
        except Exception:  # noqa: BLE001 - a failed person is recorded with every answer missing
            text = ""
        done[0] += 1
        if progress:
            progress(done[0], len(people))
        return {"agent_id": p.get("agent_id"), "name": p.get("name"), "segment": p.get("segment") or "",
                "country": p.get("country") or "", "order": orders, "answers": read(text, spec)}

    with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
        rows = list(pool.map(one, people))
    answered = sum(1 for r in rows if any(v is not None for v in r["answers"].values()))
    if people and not answered:
        raise RuntimeError("no usable answers: check the model settings, then run the questionnaire again")
    result = {"version": VERSION, "title": spec["title"], "seed": seed, "people": len(rows), "answered": answered,
              **summarize(spec, rows), "rows": rows, "usage": ask.usage,
              "note": "Simulated answers from fictional people. Read them as directions; check with real answers "
                      "to the same questions before deciding."}
    result["markdown"] = to_markdown(result)
    result["csv_rows"] = to_csv_rows(result)
    return result


def to_csv_rows(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One row per person, one column per question (multi answers joined with |), for comparing with real answers."""
    ids = [q["id"] for q in result.get("questions") or []]
    out = []
    for r in result.get("rows") or []:
        row = {"respondent": f"sim_{r.get('agent_id')}", "segment": r.get("segment") or "", "country": r.get("country") or ""}
        for i in ids:
            v = r["answers"].get(i)
            row[i] = "|".join(v) if isinstance(v, list) else ("" if v is None else v)
        out.append(row)
    return out


def to_markdown(result: Dict[str, Any]) -> str:
    lines = [f"# {result.get('title') or 'Questionnaire'} (simulated answers)", "",
             f"{result.get('answered')} of {result.get('people')} simulated people answered. {result.get('note')}", ""]
    for q in result.get("questions") or []:
        a = q["all"]
        lines.append(f"## {q['text']}")
        if q["type"] in ("scale", "nps"):
            extra = f", NPS {a['nps']}" if "nps" in a else (f", top box {round(100 * a['top_box'])}%" if "top_box" in a else "")
            lines.append(f"Mean {a.get('mean')} (SD {a.get('sd')}, n={a['n']}{extra})")
            lines.append("  ".join(f"{k}: {v}" for k, v in (a.get("distribution") or {}).items()))
        elif q["type"] in ("choice", "multi"):
            for o, c in sorted((a.get("distribution") or {}).items(), key=lambda kv: -kv[1]):
                lines.append(f"- {o}: {c} ({round(100 * a['shares'][o])}%)")
        else:
            lines += [f"- \"{x['text']}\" ({x['segment'] or 'no segment'})" for x in a.get("quotes") or []]
        if a.get("too_alike"):
            lines.append("_Answers barely vary: simulated people tend to answer too alike. Check with real answers._")
        lines.append("")
    pc = result.get("position_check") or {}
    if pc.get("flag"):
        lines.append(f"Position check: the option shown first was picked {round(100 * pc['first_shown_share'])}% of the "
                     f"time against {round(100 * pc['expected_share'])}% expected. Treat choice results with care.")
    return "\n".join(lines).rstrip() + "\n"
