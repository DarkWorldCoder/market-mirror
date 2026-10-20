"""
agent_thoughts.py - what the simulated people thought, said and did.

* run_thought_simulation: one model call per person in the cohort. Each person reports their first reaction, how
  they weigh it (budget, dealbreakers, who they would ask), what they privately think of it and what they would
  actually do. The person labels their own reaction and roadblock; nothing is filled in when a call fails.
* harvest_thoughts: collects text the model already wrote during a run (feed-test and landing-page thoughts,
  survey objections, pitch replies, social posts and comments), labelled by kind: a private thought, something the
  person said, or something they posted. Nothing is invented for people who left no text.
"""

from __future__ import annotations

import json
import os
import random
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from ..utils.logger import get_logger
from .feed_test import UsageMeter, _llm_json

logger = get_logger("mirofish.agent_thoughts")

THOUGHT_SYSTEM = (
    "You are one simulated person in a market test. Think in the first person, in your own words, from your life, "
    "budget and habits. Separate your first gut reaction, how you weigh it, what you privately think and what you "
    "would actually do. Use only what you are shown about the offer. Reply with JSON only.")
GUT_TAGS = ("curious", "skeptical", "price_shock", "ad_fatigue", "social_proof", "trust_signal", "indifferent", "urgent_need")
ROADBLOCK_TAGS = ("none", "price", "payment_or_signup", "trust", "needs_approval", "no_need", "effort", "unclear", "other")
ENGAGING = ("click", "tap", "sign", "buy", "subscrib", "download", "install", "register", "book", "start", "join", "visit")


def _tag(x: Any, allowed) -> str:
    s = str(x or "").strip().lower().replace(" ", "_")
    return s if s in allowed else ("other" if s and "other" in allowed else "")


def _stimulus(stimulus: Any) -> Dict[str, str]:
    if isinstance(stimulus, str):
        d = {"headline": "", "text": stimulus.strip(), "price": "", "channel": ""}
    elif isinstance(stimulus, dict):
        d = {"headline": str(stimulus.get("headline") or stimulus.get("title") or "").strip(),
             "text": str(stimulus.get("text") or stimulus.get("offer") or stimulus.get("prompt") or "").strip(),
             "price": str(stimulus.get("price") or "").strip(),
             "channel": str(stimulus.get("channel") or stimulus.get("platform") or "").strip()}
    else:
        raise ValueError("stimulus must be text or {headline, text, price, channel}")
    if not (d["text"] or d["headline"]):
        raise ValueError("the stimulus needs text or a headline")
    return d


def _thought_prompt(person: Dict[str, Any], st: Dict[str, str]) -> str:
    from .gtm_suite import person_card
    shown = "\n".join(x for x in (f"Headline: {st['headline']}" if st["headline"] else "", st["text"],
                                  f"Price: {st['price']}" if st["price"] else "") if x)
    where = st["channel"] or "your phone"
    return (f"WHO YOU ARE\n{person_card(person)}\n\nYou come across this on {where}:\n{shown}\n\n"
            'Return JSON: {"thought": "your unfiltered first reaction, one or two sentences in your own words", '
            f'"gut": "{"|".join(GUT_TAGS)}", "weighing": "how your budget, dealbreakers or the people you ask come into it", '
            f'"roadblock": "{"|".join(ROADBLOCK_TAGS)}", "private_verdict": "yes|maybe|no", '
            '"would_do": "what you would actually do next, in a few words", "conviction_0_10": 0-10}')


def run_thought_simulation(client: Any, model: str, stimulus: Any, people: List[Dict[str, Any]], max_personas: int = 40,
                           parallel: int = 8, seed: int = 7, progress: Optional[Callable[[int, int], None]] = None) -> Dict[str, Any]:
    """One call per person (up to max_personas, spread across segments)."""
    if client is None:
        raise ValueError("the thought test asks the simulated people, so it needs a model connection")
    from .gtm_suite import sample_people
    st = _stimulus(stimulus)
    cohort = sample_people(people, max_personas, seed)
    meter = client if isinstance(client, UsageMeter) else UsageMeter(client)
    lock = threading.Lock()
    done = [0]

    def one(p: Dict[str, Any]) -> Dict[str, Any]:
        row = {"agent_id": p.get("agent_id"), "name": p.get("name"), "segment": p.get("segment") or "",
               "country": p.get("country") or "", "source": "thought_test", "kind": "private_thought"}
        try:
            data, prov, mod = _llm_json(meter, model, THOUGHT_SYSTEM, _thought_prompt(p, st), temperature=0.7,
                                        max_tokens=600, agent_id=p.get("agent_id"), return_meta=True)
            data = data if isinstance(data, dict) else {}
            if not str(data.get("thought") or "").strip():
                raise ValueError("no thought in the answer")
            would = str(data.get("would_do") or "").strip()
            verdict = str(data.get("private_verdict") or "").strip().lower()
            row.update({"ok": True, "provider": prov, "model": mod, "text": str(data["thought"]).strip(),
                        "gut": _tag(data.get("gut"), GUT_TAGS), "weighing": str(data.get("weighing") or "").strip(),
                        "roadblock": _tag(data.get("roadblock"), ROADBLOCK_TAGS), "private_verdict": verdict,
                        "would_do": would,
                        "conviction": max(0.0, min(10.0, float(data["conviction_0_10"]))) if isinstance(data.get("conviction_0_10"), (int, float)) else None,
                        "said_yes_but_would_not_act": verdict in ("yes", "maybe") and bool(would) and not any(w in would.lower() for w in ENGAGING)})
        except Exception as e:  # noqa: BLE001 - kept as a failure
            row.update({"ok": False, "error": str(e)[:200]})
        with lock:
            done[0] += 1
            if progress:
                progress(done[0], len(cohort))
        return row

    with ThreadPoolExecutor(max_workers=max(1, min(parallel, len(cohort) or 1))) as ex:
        rows = list(ex.map(one, cohort))
    res = summarize_thoughts([r for r in rows if r.get("ok")], stimulus=(st["headline"] + ": " if st["headline"] else "") + st["text"][:160])
    res.update({"asked": len(rows), "failed": sum(1 for r in rows if not r.get("ok")),
                "errors": sorted({r["error"][:120] for r in rows if r.get("error")})[:5], "usage": meter.snapshot()})
    return res


def _load(folder: Optional[str], name: str) -> Any:
    if not folder:
        return None
    p = os.path.join(folder, name)
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def harvest_thoughts(sim_dir: str, run_dir: Optional[str] = None, limit_per_source: int = 300) -> Dict[str, Any]:
    """Text the model wrote during the run, by person and source. Looks in the run folder first, then the simulation."""
    def get(name: str) -> Any:
        return _load(run_dir, name) or _load(sim_dir, name)
    cfg = get("config.json") or get("simulation_config.json") or {}
    index = {}
    for r in cfg.get("persona_index") or []:
        if isinstance(r, dict) and r.get("agent_id") is not None:
            try:
                index[int(r["agent_id"])] = r
            except (TypeError, ValueError):
                pass

    def who(aid: Any, name: str = "", seg: str = "", country: str = "") -> Dict[str, Any]:
        try:
            p = index.get(int(aid), {})
        except (TypeError, ValueError):
            p = {}
        return {"agent_id": aid, "name": p.get("name") or name or (f"agent {aid}" if aid is not None else ""),
                "segment": p.get("segment") or seg or "", "country": p.get("country") or country or ""}

    items: List[Dict[str, Any]] = []
    lab = get("thought_stream.json")
    if isinstance(lab, dict):
        for r in (lab.get("entries") or [])[:limit_per_source]:
            if isinstance(r, dict) and r.get("text") and r.get("source") == "thought_test":
                items.append(r)
    ft = get("feed_test.json")
    if isinstance(ft, dict):
        first = ft.get("seed")
        n = 0
        for s in ft.get("sessions") or []:
            if n >= limit_per_source or not isinstance(s, dict) or (first is not None and s.get("seed") not in (None, first)):
                continue
            ad, land = s.get("ad") or {}, s.get("landing") or {}
            did = ("hid the ad" if ad.get("hide") else "clicked" if ad.get("click") else "stopped, then scrolled on"
                   if ad.get("stopped") else "scrolled past")
            if str(ad.get("thought") or "").strip():
                items.append({**who(s.get("agent_id"), s.get("name", ""), s.get("segment", ""), s.get("country", "")),
                              "source": "ad in feed", "kind": "private_thought", "text": str(ad["thought"]).strip(),
                              "did": did, "context": f"{s.get('platform', '')} ad {s.get('creative_id', '')}".strip()})
                n += 1
            if str(land.get("thought") or "").strip():
                items.append({**who(s.get("agent_id")), "source": "landing page", "kind": "private_thought",
                              "text": str(land["thought"]).strip(),
                              "did": "completed the form" if land.get("completed") else f"left the page{(': ' + str(land['drop_reason'])[:80]) if land.get('drop_reason') else ''}",
                              "context": f"after clicking {s.get('creative_id', '')}"})
                n += 1
    survey = get("survey.json")
    if isinstance(survey, dict):
        for r in (survey.get("responses") or [])[:limit_per_source]:
            a = r.get("answer") if isinstance(r, dict) else None
            if isinstance(a, dict) and str(a.get("main_objection") or "").strip():
                items.append({**who(r.get("agent_id"), r.get("name", "")), "source": "survey", "kind": "said",
                              "text": str(a["main_objection"]).strip(), "did": f"would {a.get('would_convert') or '?'} take it",
                              "context": str(survey.get("offer") or "")[:120]})
    pitch = get("pitch.json")
    if isinstance(pitch, dict):
        for r in (pitch.get("people") or [])[:limit_per_source]:
            t1 = (r or {}).get("turn1") or {}
            if str(t1.get("reply") or "").strip():
                items.append({**who(r.get("agent_id"), r.get("name", "")), "source": "sales pitch", "kind": "said",
                              "text": str(t1["reply"]).strip(), "did": f"verdict: {r.get('final_verdict') or t1.get('verdict') or '?'}",
                              "context": "reply to the pitch"})
    acts = get("actions.json")
    acts = acts.get("actions") if isinstance(acts, dict) else acts
    n = 0
    for a in acts or []:
        if n >= limit_per_source or not isinstance(a, dict):
            continue
        args = a.get("action_args") or {}
        text = str(args.get("content") or args.get("quote_content") or "").strip()
        if text and str(a.get("action_type") or "") in ("CREATE_POST", "CREATE_COMMENT", "QUOTE_POST"):
            items.append({**who(a.get("agent_id"), a.get("agent_name", "")), "source": "social feed", "kind": "posted",
                          "text": text, "did": str(a.get("action_type") or "").lower().replace("_", " "),
                          "context": f"{a.get('platform', '')} round {a.get('round_num', '?')}"})
            n += 1
    return summarize_thoughts(items)


def summarize_thoughts(entries: List[Dict[str, Any]], stimulus: str = "") -> Dict[str, Any]:
    from .gtm_suite import wilson
    lab = [e for e in entries if e.get("source") == "thought_test"]
    by_seg: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for e in lab:
        by_seg[str(e.get("segment") or "")].append(e)
    gaps = [e for e in lab if e.get("said_yes_but_would_not_act")]
    out = {
        "generated_at": datetime.now().isoformat(timespec="seconds"), "stimulus": stimulus,
        "total": len(entries), "people": len({e.get("agent_id") for e in entries if e.get("agent_id") is not None}),
        "by_source": dict(Counter(e.get("source") or "" for e in entries).most_common()),
        "by_kind": dict(Counter(e.get("kind") or "" for e in entries).most_common()),
        "by_provider": dict(Counter(e.get("provider") for e in entries if e.get("provider")).most_common()),
        "entries": entries[:400],
    }
    if lab:
        n = len(lab)
        out["thought_test"] = {
            "people": n,
            "gut": {k: wilson(v, n) for k, v in Counter(e.get("gut") or "unlabelled" for e in lab).most_common()},
            "roadblock": {k: wilson(v, n) for k, v in Counter(e.get("roadblock") or "unlabelled" for e in lab).most_common()},
            "private_verdict": {k: wilson(v, n) for k, v in Counter(e.get("private_verdict") or "unlabelled" for e in lab).most_common()},
            "said_yes_but_would_not_act": wilson(len(gaps), n),
            "by_segment": [{"segment": s, "people": len(rows),
                            "top_roadblock": Counter(r.get("roadblock") for r in rows if r.get("roadblock") not in (None, "", "none")).most_common(1)[0][0]
                            if any(r.get("roadblock") not in (None, "", "none") for r in rows) else "none",
                            "positive_verdict": wilson(sum(1 for r in rows if r.get("private_verdict") in ("yes", "maybe")), len(rows))}
                           for s, rows in sorted(by_seg.items(), key=lambda kv: -len(kv[1]))],
        }
    return out

