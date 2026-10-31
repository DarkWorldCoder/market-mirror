"""MarketMirror-Bench: score the simulated buyers against open human data, next to simpler comparators.

Two suites, both on public data under CC BY 4.0:

upworthy   The Upworthy Research Archive (Matias et al., Scientific Data 2021, https://upworthy.natematias.com):
           real headline A/B tests with impressions and clicks. Task: pick the headline that got the most clicks.
           Kept: tests with 2-4 headlines, 1,000+ impressions each, and a clear winner (two-proportion z >= 2.58
           over the runner-up). Methods: chance (analytic), generic_reader (one call ranks the headlines with no
           persona; the comparator that beat a persona panel in Maiorano 2026, arXiv 2609.25010) and persona_panel
           (P simulated people from a run each pick the headline they would click; ranking by votes).
twin2k     Twin-2K-500 (Toubia et al. 2025, https://huggingface.co/datasets/LLM-Digital-Twin/Twin-2K-500): 2,058 US
           people, waves 1-3 as the persona, wave 4 answers as ground truth; the same wave-4 questions answered in
           waves 1-3 give each person's test-retest ceiling. Default slice: the 40 "would you buy this product at
           this price" questions. Methods: majority (leave-one-out most common answer), no_persona (a typical US
           adult) and twin (a summary of that person's waves 1-3, made once per person and cached).

Metrics: top-choice accuracy, Spearman between predicted and real ranking (upworthy); accuracy, accuracy
normalised by test-retest, Brier score on purchase yes/no and the predicted-vs-real purchase share (twin2k);
calls and tokens per method. Misses are kept in the results: the point is an honest record, not a leaderboard.

Spend: nothing calls a model unless `approve_spend` is set; otherwise `run` returns an estimate. The sample is
fixed by hashing ids with a salt, so a run is reproducible without committing the data.

Stdlib only; `complete(system, user) -> (text, usage)` is injected.
"""

from __future__ import annotations

import csv
import hashlib
import html
import json
import math
import os
import re
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

VERSION = 1
SALT = "marketmirror-bench-v1"
Complete = Callable[[str, str], Tuple[str, Dict[str, Any]]]
TWIN_ROWS_URL = ("https://datasets-server.huggingface.co/rows?dataset=LLM-Digital-Twin/Twin-2K-500&config=wave_split"
                 "&split=data&offset={offset}&length={length}")
PRICE_PER_MTOK = {"input": 1.0, "output": 5.0}       # Claude Haiku 4.5 list price, for the estimate only


def pick(ids: Sequence[Any], n: int, salt: str = SALT) -> List[Any]:
    """A fixed sample: the n ids with the smallest salted hash."""
    return sorted(ids, key=lambda i: hashlib.sha256(f"{salt}:{i}".encode()).hexdigest())[:n]


def _json_block(text: str) -> Any:
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    for o, c in (("{", "}"), ("[", "]")):
        a, b = text.find(o), text.rfind(c)
        if a != -1 and b > a:
            try:
                return json.loads(text[a:b + 1])
            except ValueError:
                continue
    return None


def spearman(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    n = len(a)
    if n < 2:
        return None

    def ranks(xs):
        order = sorted(range(n), key=lambda i: xs[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and xs[order[j + 1]] == xs[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return r
    ra, rb = ranks(a), ranks(b)
    ma, mb = sum(ra) / n, sum(rb) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return num / den if den else None


class Meter:
    def __init__(self, complete: Complete):
        self.complete, self.calls, self.input_tokens, self.output_tokens = complete, 0, 0, 0

    def __call__(self, system: str, user: str) -> str:
        text, u = self.complete(system, user)
        self.calls += 1
        self.input_tokens += int((u or {}).get("input_tokens") or 0)
        self.output_tokens += int((u or {}).get("output_tokens") or 0)
        return text

    def usage(self) -> Dict[str, int]:
        return {"calls": self.calls, "input_tokens": self.input_tokens, "output_tokens": self.output_tokens}


def cost(input_tokens: float, output_tokens: float) -> float:
    return round(input_tokens / 1e6 * PRICE_PER_MTOK["input"] + output_tokens / 1e6 * PRICE_PER_MTOK["output"], 2)


# --------------------------------------------------------------------------
# upworthy
# --------------------------------------------------------------------------

def load_upworthy(path: str, min_impressions: int = 1000, max_arms: int = 4, z_min: float = 2.58) -> List[Dict[str, Any]]:
    """Packages CSV -> tests [{id, arms: [{headline, impressions, clicks, ctr}], winner}] with a clear winner."""
    tests: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            try:
                imp, clk = int(float(r.get("impressions") or 0)), int(float(r.get("clicks") or 0))
            except ValueError:
                continue
            head = (r.get("headline") or "").strip()
            tid = (r.get("clickability_test_id") or "").strip()
            if not tid or not head or imp < min_impressions:
                continue
            tests[tid].append({"headline": head, "impressions": imp, "clicks": clk, "ctr": clk / imp})
    out = []
    for tid, arms in tests.items():
        by_head: Dict[str, Dict[str, Any]] = {}
        for a in arms:                                    # same headline with other images: pool its arms
            b = by_head.setdefault(a["headline"], {"headline": a["headline"], "impressions": 0, "clicks": 0})
            b["impressions"] += a["impressions"]
            b["clicks"] += a["clicks"]
        arms = [{**b, "ctr": b["clicks"] / b["impressions"]} for b in by_head.values()]
        if not 2 <= len(arms) <= max_arms:
            continue
        arms.sort(key=lambda a: -a["ctr"])
        a, b = arms[0], arms[1]
        p = (a["clicks"] + b["clicks"]) / (a["impressions"] + b["impressions"])
        se = math.sqrt(p * (1 - p) * (1 / a["impressions"] + 1 / b["impressions"])) if 0 < p < 1 else 0
        if se and (a["ctr"] - b["ctr"]) / se >= z_min:
            out.append({"id": tid, "arms": arms, "winner": 0})
    return out


GENERIC_SYSTEM = ("You predict which headline gets the most clicks from ordinary readers scrolling a news feed. "
                  "Reply with JSON only.")


def generic_reader(test: Dict[str, Any], ask: Callable[[str, str], str], order: List[int]) -> Optional[List[float]]:
    lines = "\n".join(f"{k + 1}. {test['arms'][i]['headline']}" for k, i in enumerate(order))
    text = ask(GENERIC_SYSTEM, f"Headlines shown to equal random groups of readers:\n{lines}\n\nGive each a 0-100 score "
                               'for how many readers would click it. Reply: {"scores": [n, n, ...]} in the order above.')
    d = _json_block(text)
    sc = d.get("scores") if isinstance(d, dict) else d
    if not isinstance(sc, list) or len(sc) != len(order):
        return None
    out = [0.0] * len(order)
    try:
        for k, i in enumerate(order):
            out[i] = float(sc[k])
    except (TypeError, ValueError):
        return None
    return out


PANEL_SYSTEM = "You are this person, scrolling your feed. Answer as yourself. Reply with JSON only."


def persona_panel(test: Dict[str, Any], ask: Callable[[str, str], str], people: List[Dict[str, Any]],
                  order: List[int]) -> Optional[List[float]]:
    votes = [0.0] * len(test["arms"])
    lines = "\n".join(f"{k + 1}. {test['arms'][i]['headline']}" for k, i in enumerate(order))
    got = 0
    for p in people:
        who = str(p.get("persona") or p.get("bio") or p.get("name") or "an adult")[:1200]
        d = _json_block(ask(PANEL_SYSTEM, f"Who you are: {who}\n\nThese headlines are in your feed:\n{lines}\n\n"
                                          'Which one would you click, if any? Reply: {"click": number or 0}'))
        try:
            k = int((d or {}).get("click") or 0)
        except (TypeError, ValueError, AttributeError):
            continue
        got += 1
        if 1 <= k <= len(order):
            votes[order[k - 1]] += 1
    return votes if got else None


def score_upworthy(tests: List[Dict[str, Any]], preds: Dict[str, Optional[List[float]]]) -> Dict[str, Any]:
    hits, rhos, n = 0, [], 0
    for t in tests:
        p = preds.get(t["id"])
        if not p:
            continue
        n += 1
        top = max(range(len(p)), key=lambda i: (p[i], -i))
        hits += int(top == t["winner"] and p.count(p[top]) == 1)      # a tie at the top is not a hit
        rho = spearman(p, [a["ctr"] for a in t["arms"]])
        if rho is not None:
            rhos.append(rho)
    return {"n": n, "top_choice_accuracy": round(hits / n, 3) if n else None,
            "spearman": round(sum(rhos) / len(rhos), 3) if rhos else None, "missing": len(tests) - n}


def run_upworthy(path: str, n: int, complete: Optional[Complete], methods: Sequence[str], people: Sequence[Dict[str, Any]] = (),
                 panel_size: int = 10, approve_spend: bool = False, parallel: int = 4) -> Dict[str, Any]:
    tests = load_upworthy(path)
    sample = [t for t in tests if t["id"] in set(pick([t["id"] for t in tests], n))]
    chance = sum(1 / len(t["arms"]) for t in sample) / len(sample) if sample else None
    out: Dict[str, Any] = {"suite": "upworthy", "tests_available": len(tests), "tests": len(sample),
                           "methods": {"chance": {"top_choice_accuracy": round(chance, 3) if chance else None,
                                                  "n": len(sample), "calls": 0}}}
    people = list(people)[:panel_size]
    if "persona_panel" in methods and not people:
        out["methods"]["persona_panel"] = {"skipped": "needs people: pass --run-dir of a prepared run"}
    calls = {"generic_reader": len(sample), "persona_panel": len(sample) * len(people)}
    est_in = sum(calls[m] for m in methods if m in calls) * 400
    out["estimate"] = {"calls": sum(calls[m] for m in methods if m in calls), "usd_at_haiku": cost(est_in, est_in / 8)}
    if not approve_spend or complete is None:
        out["dry_run"] = True
        return out
    for m in methods:
        if m not in calls or (m == "persona_panel" and not people):
            continue
        meter = Meter(complete)

        def one(t):
            order = pick(list(range(len(t["arms"]))), len(t["arms"]), salt=t["id"])   # fixed shuffled order
            try:
                if m == "generic_reader":
                    return t["id"], generic_reader(t, meter, order)
                return t["id"], persona_panel(t, meter, people, order)
            except Exception:  # noqa: BLE001 - a failed test is counted as missing
                return t["id"], None
        with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
            preds = dict(pool.map(one, sample))
        out["methods"][m] = {**score_upworthy(sample, preds), **meter.usage(),
                             "usd_at_haiku": cost(meter.input_tokens, meter.output_tokens)}
    return out


# --------------------------------------------------------------------------
# twin2k
# --------------------------------------------------------------------------

def fetch_twin(cache_dir: str, n: int, log: Callable[[str], None] = lambda m: None) -> List[str]:
    """Download the first n wave_split rows (public, no key) into cache_dir as one JSON file per pid."""
    os.makedirs(cache_dir, exist_ok=True)
    paths = []
    for off in range(0, n, 20):
        url = TWIN_ROWS_URL.format(offset=off, length=min(20, n - off))
        with urllib.request.urlopen(url, timeout=120) as resp:            # noqa: S310 - fixed public URL
            data = json.load(resp)
        for row in data.get("rows") or []:
            r = row.get("row") or {}
            p = os.path.join(cache_dir, f"twin_{r.get('pid')}.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump(r, f)
            paths.append(p)
        log(f"bench: fetched {len(paths)} Twin-2K-500 rows")
    return paths


def twin_items(row: Dict[str, Any], blocks: str = "pricing") -> List[Dict[str, Any]]:
    """Single-answer items (MC questions and Likert matrix rows) with the wave-4 answer and the waves 1-3 answer."""
    def parse(s):
        return json.loads(s) if isinstance(s, str) else (s or [])
    w4, w13 = parse(row.get("wave4_Q_wave4_A")), parse(row.get("wave4_Q_wave1_3_A"))
    earlier = {}
    for blk in w13:
        for q in blk.get("Questions") or []:
            earlier[q.get("QuestionID")] = (q.get("Answers") or {}).get("SelectedByPosition")
    items = []
    for blk in w4:
        if blocks == "pricing" and "pricing" not in str(blk.get("BlockName") or "").lower():
            continue
        for q in blk.get("Questions") or []:
            ans = (q.get("Answers") or {}).get("SelectedByPosition")
            prev = earlier.get(q.get("QuestionID"))
            if q.get("QuestionType") == "MC" and isinstance(ans, int) and q.get("Options"):
                items.append({"id": q["QuestionID"], "text": q["QuestionText"], "options": q["Options"],
                              "answer": ans, "retest": prev if isinstance(prev, int) else None})
            elif q.get("QuestionType") == "Matrix" and isinstance(ans, list) and q.get("Columns"):
                for k, row_text in enumerate(q.get("Rows") or []):
                    if k < len(ans) and isinstance(ans[k], int):
                        pv = prev[k] if isinstance(prev, list) and k < len(prev) and isinstance(prev[k], int) else None
                        items.append({"id": f"{q['QuestionID']}_{k}", "text": f"{q['QuestionText']} {row_text}",
                                      "options": q["Columns"], "answer": ans[k], "retest": pv})
    return items


SUMMARY_SYSTEM = ("Summarise a survey respondent for someone who must predict their future answers: demographics, "
                  "values, habits, money and shopping behaviour, typical answer style. Plain prose, under 900 words.")
ANSWER_SYSTEM = "You predict how a specific person answers survey questions. Reply with JSON only."


def twin_summary(row: Dict[str, Any], ask: Callable[[str, str], str], cache_dir: Optional[str]) -> str:
    path = os.path.join(cache_dir, f"summary_{row.get('pid')}.txt") if cache_dir else None
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            return f.read()
    text = ask(SUMMARY_SYSTEM, str(row.get("wave1_3_persona_text") or "")[:120000])
    if path and text.strip():
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    return text


def answer_items(persona: str, items: List[Dict[str, Any]], ask: Callable[[str, str], str]) -> Dict[str, int]:
    qs = "\n".join(f"{k + 1}. {it['text']}\n   Options: " + " | ".join(f"{j + 1}) {o}" for j, o in enumerate(it["options"]))
                   for k, it in enumerate(items))
    d = _json_block(ask(ANSWER_SYSTEM, f"The person:\n{persona}\n\nQuestions:\n{qs}\n\nGive the option number this "
                                       'person picks for each question. Reply: {"answers": [n, n, ...]} in order.'))
    ans = d.get("answers") if isinstance(d, dict) else d
    out = {}
    for it, a in zip(items, ans if isinstance(ans, list) else []):
        try:
            out[it["id"]] = int(a)
        except (TypeError, ValueError):
            continue
    return out


def _is_yes(it: Dict[str, Any], pos: Optional[int]) -> Optional[bool]:
    if pos is None or not 1 <= pos <= len(it["options"]):
        return None
    return str(it["options"][pos - 1]).lower().startswith("yes")


def score_twin(people: List[Dict[str, Any]], preds: Dict[Tuple[Any, str], int]) -> Dict[str, Any]:
    n = hit = retest_n = retest_hit = 0
    brier, sim_yes, real_yes, yn = [], 0, 0, 0
    for p in people:
        for it in p["items"]:
            pr = preds.get((p["pid"], it["id"]))
            if pr is None:
                continue
            n += 1
            hit += int(pr == it["answer"])
            if it.get("retest") is not None:
                retest_n += 1
                retest_hit += int(it["retest"] == it["answer"])
            ys, yr = _is_yes(it, pr), _is_yes(it, it["answer"])
            if ys is not None and yr is not None:
                yn += 1
                sim_yes += ys
                real_yes += yr
                brier.append((float(ys) - float(yr)) ** 2)
    acc = hit / n if n else None
    ceiling = retest_hit / retest_n if retest_n else None
    return {"n": n, "accuracy": round(acc, 3) if acc is not None else None,
            "test_retest": round(ceiling, 3) if ceiling is not None else None,
            "normalized_accuracy": round(acc / ceiling, 3) if acc is not None and ceiling else None,
            "brier_purchase": round(sum(brier) / len(brier), 3) if brier else None,
            "predicted_purchase_share": round(sim_yes / yn, 3) if yn else None,
            "real_purchase_share": round(real_yes / yn, 3) if yn else None}


def run_twin(rows: List[Dict[str, Any]], n: int, complete: Optional[Complete], methods: Sequence[str],
             items_per_person: int = 20, blocks: str = "pricing", approve_spend: bool = False,
             cache_dir: Optional[str] = None, parallel: int = 4) -> Dict[str, Any]:
    by_pid = {r.get("pid"): r for r in rows if r.get("pid") is not None}
    chosen = pick(list(by_pid), n)
    people = []
    for pid in chosen:
        items = twin_items(by_pid[pid], blocks)
        keep = set(pick([it["id"] for it in items], items_per_person, salt=f"{SALT}:{pid}"))
        people.append({"pid": pid, "items": [it for it in items if it["id"] in keep], "row": by_pid[pid]})
    out: Dict[str, Any] = {"suite": "twin2k", "blocks": blocks, "people": len(people),
                           "items": sum(len(p["items"]) for p in people), "methods": {}}
    # leave-one-out majority: the most common wave-4 answer among the other people
    counts: Dict[str, Counter] = defaultdict(Counter)
    for p in people:
        for it in p["items"]:
            counts[it["id"]][it["answer"]] += 1
    maj = {}
    for p in people:
        for it in p["items"]:
            c = counts[it["id"]].copy()
            c[it["answer"]] -= 1
            best = [k for k, v in c.most_common() if v > 0]
            if best:
                maj[(p["pid"], it["id"])] = best[0]
    out["methods"]["majority"] = {**score_twin(people, maj), "calls": 0}
    calls = {"no_persona": len(people), "twin": 2 * len(people)}
    est_in = len(people) * 1500 + (len(people) * 30000 if "twin" in methods else 0)
    out["estimate"] = {"calls": sum(calls[m] for m in methods if m in calls), "usd_at_haiku": cost(est_in, len(people) * 1500)}
    if not approve_spend or complete is None:
        out["dry_run"] = True
        return out
    for m in methods:
        if m not in calls:
            continue
        meter = Meter(complete)

        def one(p):
            try:
                persona = ("A typical adult living in the United States." if m == "no_persona"
                           else twin_summary(p["row"], meter, cache_dir))
                return p["pid"], answer_items(persona, p["items"], meter)
            except Exception:  # noqa: BLE001 - a failed person is counted as missing
                return p["pid"], {}
        with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
            got = dict(pool.map(one, people))
        preds = {(pid, qid): a for pid, ans in got.items() for qid, a in ans.items()}
        out["methods"][m] = {**score_twin(people, preds), **meter.usage(),
                             "usd_at_haiku": cost(meter.input_tokens, meter.output_tokens)}
    return out


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------

def render_markdown(res: Dict[str, Any]) -> str:
    lines = [f"# MarketMirror-Bench: {res.get('suite')}", ""]
    if res.get("dry_run"):
        e = res.get("estimate") or {}
        lines += [f"Dry run: about {e.get('calls')} model calls, roughly ${e.get('usd_at_haiku')} at Claude Haiku 4.5 prices. "
                  "Nothing was spent; rerun with --approve-spend.", ""]
    keys = sorted({k for m in res["methods"].values() for k in m if k not in ("skipped",)})
    lines.append("| method | " + " | ".join(keys) + " |")
    lines.append("|---" * (len(keys) + 1) + "|")
    for name, m in res["methods"].items():
        lines.append(f"| {name} | " + " | ".join(str(m.get(k, "")) for k in keys) + " |")
    lines += ["", "Human data: CC BY 4.0. Simulated answers are compared with what real people did; a method that does "
                  "not beat the simpler comparators is reported as such."]
    return "\n".join(lines)


def render_html(results: List[Dict[str, Any]]) -> str:
    body = "".join(f"<section><pre>{html.escape(render_markdown(r))}</pre></section>" for r in results)
    return ("<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width,"
            "initial-scale=1'><title>MarketMirror-Bench</title><style>body{font:15px/1.5 system-ui;max-width:900px;"
            "margin:24px auto;padding:0 16px;background:#fff;color:#111}pre{white-space:pre-wrap;overflow-x:auto}"
            "@media(prefers-color-scheme:dark){body{background:#111;color:#eee}}</style></head><body>"
            "<h1>MarketMirror-Bench</h1>" + body + "</body></html>")
