"""
gtm_suite.py - marketing and sales tests answered by the simulated people.

Every engine asks each person in its cohort (one model call per person, or per decision unit) and aggregates
their answers: counts, shares with 95% Wilson intervals, paired differences for before/after comparisons, and
real quotes. Nothing is filled in when a call fails; failures are counted. No product, market or statistic is
built in: the offer, competitors, prices and messages come from the caller or the project's product profile.

Engines: buying committee, creative optimizer, sales battlecard (with rebuttal test), customer journey,
pricing choice, competitor choice (with optional counter-moves). The CRO lab lives in cro_and_sparring.py and
reuses the helpers here.
"""

from __future__ import annotations

import json
import math
import os
import random
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ..utils.logger import get_logger
from .feed_test import UsageMeter, _llm_json

logger = get_logger("mirofish.gtm")

CONCERN_TYPES = ("price", "trust", "relevance", "effort", "timing", "unclear", "privacy", "competitor",
                 "authority", "habit", "other")
PERSON_SYSTEM = (
    "You are one simulated person in a market test. Answer as that person would, from their life, budget and "
    "habits, not as a helpful assistant: be honest, busy and sometimes indifferent, and say no when they would. "
    "Use only what you are shown about the product; do not assume facts that are not there. Reply with JSON only.")
WRITER_SYSTEM = (
    "You are a careful marketing and sales writer. Use only the facts you are given. Never invent statistics, "
    "ratings, user counts, testimonials, awards, prices, guarantees or features. Reply with JSON only.")
ENGINE_LABELS = {
    "committee": "Buying committee", "creative": "Creative optimizer", "battlecard": "Sales battlecard",
    "journey": "Customer journey", "pricing": "Pricing and packaging", "competitors": "Competitor choice",
}


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------

def wilson(k: int, n: int, z: float = 1.96) -> Dict[str, Any]:
    """Share in % with a 95% Wilson interval."""
    if not n:
        return {"k": k, "n": n, "pct": None, "lo": None, "hi": None}
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return {"k": k, "n": n, "pct": round(100 * p, 1), "lo": round(100 * max(0.0, c - h), 1), "hi": round(100 * min(1.0, c + h), 1)}


def mean_ci(values: Sequence[float], z: float = 1.96) -> Dict[str, Any]:
    v = [float(x) for x in values if isinstance(x, (int, float)) and not isinstance(x, bool)]
    if not v:
        return {"n": 0, "mean": None, "lo": None, "hi": None}
    m = sum(v) / len(v)
    if len(v) < 2:
        return {"n": len(v), "mean": round(m, 3), "lo": None, "hi": None}
    sd = math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1))
    h = z * sd / math.sqrt(len(v))
    return {"n": len(v), "mean": round(m, 3), "lo": round(m - h, 3), "hi": round(m + h, 3)}


def verdict_from_ci(ci: Dict[str, Any]) -> str:
    if ci.get("lo") is None or ci.get("hi") is None:
        return "too few answers"
    if ci["lo"] > 0:
        return "better"
    if ci["hi"] < 0:
        return "worse"
    return "no clear difference"


def _f(x: Any) -> Optional[float]:
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _prob(x: Any) -> Optional[float]:
    v = _f(x)
    if v is None:
        return None
    if v > 1:
        v = v / 100.0
    return max(0.0, min(1.0, v))


def _ctype(x: Any) -> str:
    s = str(x or "").strip().lower().replace(" ", "_")
    return s if s in CONCERN_TYPES else ("other" if s else "")


def _short(x: Any, n: int = 240) -> str:
    s = " ".join(str(x or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def offer_dict(offer: Any, profile: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """Normalize the offer from a string, a dict or the product profile."""
    prof = profile or {}
    if isinstance(offer, str) and offer.strip():
        d = {"headline": offer.strip()[:160], "text": offer.strip()}
    elif isinstance(offer, dict):
        d = {k: str(offer.get(k) or "").strip() for k in ("headline", "text", "price", "cta", "name", "platform")}
        d["headline"] = d["headline"] or str(offer.get("title") or offer.get("offer") or "").strip()
        d["text"] = d["text"] or str(offer.get("body") or offer.get("offer") or offer.get("description") or "").strip()
    else:
        d = {}
    pricing = prof.get("pricing") or {}
    pts = pricing.get("price_points") or []
    d.setdefault("name", "")
    d["name"] = d.get("name") or str(prof.get("name") or "").strip()
    d["headline"] = d.get("headline") or str(prof.get("offer") or prof.get("one_liner") or "").strip()
    d["text"] = d.get("text") or str(prof.get("what_it_does") or prof.get("one_liner") or "").strip()
    if not d.get("price") and pts:
        cur = pricing.get("currency") or ""
        d["price"] = ", ".join(f"{cur} {p}".strip() if isinstance(p, (int, float)) else str(p) for p in pts[:3])
    for k in ("price", "cta", "platform"):
        d.setdefault(k, "")
    if not (d["headline"] or d["text"]):
        raise ValueError("an offer is required (pass offer text, or run `understand` so the project has a product profile)")
    return d


def offer_text(o: Dict[str, str]) -> str:
    parts = [f"Product: {o['name']}" if o.get("name") else "", f"Headline: {o['headline']}" if o.get("headline") else "",
             o.get("text", ""), f"Price: {o['price']}" if o.get("price") else "", f"Call to action: {o['cta']}" if o.get("cta") else ""]
    return "\n".join(p for p in parts if p)[:2500]


def product_facts(profile: Optional[Dict[str, Any]], o: Dict[str, str]) -> str:
    if profile:
        try:
            from . import product_profile as pp
            return pp.render_text(profile, 1800)
        except Exception:  # noqa: BLE001 - optional
            pass
    return offer_text(o)


def person_card(p: Dict[str, Any], limit: int = 1100) -> str:
    """Who this simulated person is: profile text, their decision card and what already happened to them."""
    head = ", ".join(str(x) for x in (p.get("name"), p.get("age"), p.get("gender"), p.get("country"), p.get("segment")) if x)
    bits = [head, _short(p.get("persona"), limit)]
    bde = p.get("bde") if isinstance(p.get("bde"), dict) else None
    if bde:
        bits.append("How they decide (their own profile card): " + _short(json.dumps(bde, ensure_ascii=False), 700))
    if p.get("history"):
        bits.append(str(p["history"])[:600])
    return "\n".join(b for b in bits if b)


def sample_people(people: List[Dict[str, Any]], n: int, seed: int) -> List[Dict[str, Any]]:
    """Up to n people, spread across segments (round robin over shuffled segments)."""
    pool = [p for p in people if p.get("agent_id") is not None]
    if n <= 0 or len(pool) <= n:
        return list(pool)
    rng = random.Random(seed)
    by: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for p in pool:
        by[str(p.get("segment") or "")].append(p)
    for v in by.values():
        rng.shuffle(v)
    keys = sorted(by)
    rng.shuffle(keys)
    out: List[Dict[str, Any]] = []
    while len(out) < n:
        for k in keys:
            if by[k] and len(out) < n:
                out.append(by[k].pop())
    return out


def ask_people(client, model: str, jobs: List[Dict[str, Any]], parallel: int = 8,
               progress: Optional[Callable[[int, int], None]] = None, max_tokens: int = 700,
               temperature: float = 0.8, system: str = PERSON_SYSTEM) -> List[Dict[str, Any]]:
    """jobs: [{"person": p, "prompt": str, ...}] -> same list with "ok", "data", "provider", "model", "error".
    One call per job; a failed call stays failed (no substitute answer)."""
    total = len(jobs)
    done = [0]
    lock = threading.Lock()

    def one(job: Dict[str, Any]) -> Dict[str, Any]:
        p = job.get("person") or {}
        try:
            data, prov, mod = _llm_json(client, model, job.get("system") or system, job["prompt"], temperature=temperature,
                                        max_tokens=job.get("max_tokens") or max_tokens, agent_id=p.get("agent_id"), return_meta=True)
            res = {**job, "ok": isinstance(data, dict), "data": data if isinstance(data, dict) else {}, "provider": prov, "model": mod}
            if not res["ok"]:
                res["error"] = "the answer was not a JSON object"
        except Exception as e:  # noqa: BLE001 - recorded as a failure
            res = {**job, "ok": False, "data": {}, "error": str(e)[:200]}
        with lock:
            done[0] += 1
            if progress:
                progress(done[0], total)
        return res

    if not jobs:
        return []
    with ThreadPoolExecutor(max_workers=max(1, min(parallel, len(jobs)))) as ex:
        return list(ex.map(one, jobs))


def write_once(client, model: str, prompt: str, max_tokens: int = 1800, temperature: float = 0.6) -> Dict[str, Any]:
    data = _llm_json(client, model, WRITER_SYSTEM, prompt, temperature=temperature, max_tokens=max_tokens)
    return data if isinstance(data, dict) else {}


def guard_numbers(obj: Any, facts: Any) -> Any:
    """Drop sentences that quote a number absent from the facts (same guard as the written report)."""
    from .market_report import _check_numbers, _fact_numbers
    allowed = _fact_numbers(facts if isinstance(facts, dict) else {"facts": facts})

    def walk(v: Any) -> Any:
        if isinstance(v, str):
            return _check_numbers(v, allowed)
        if isinstance(v, list):
            return [walk(x) for x in v]
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        return v
    return walk(obj)


def ranked(items: List[Tuple[str, str]], n_total: int, top: int = 8, quotes: int = 3) -> List[Dict[str, Any]]:
    """[(key, quote)] -> [{key, count, share: wilson, quotes}] by count."""
    counts: Counter = Counter()
    ex: Dict[str, List[str]] = defaultdict(list)
    for k, q in items:
        if not k:
            continue
        counts[k] += 1
        if q and len(ex[k]) < quotes and q not in ex[k]:
            ex[k].append(_short(q, 220))
    return [{"key": k, "count": c, "share": wilson(c, n_total), "quotes": ex[k]} for k, c in counts.most_common(top)]


def envelope(engine: str, asked: List[Dict[str, Any]], meter: UsageMeter, **extra: Any) -> Dict[str, Any]:
    ok = [r for r in asked if r.get("ok")]
    prov = Counter(str(r.get("provider") or "") for r in ok if r.get("provider"))
    return {"engine": engine, "label": ENGINE_LABELS.get(engine, engine), "evidence": "simulated people",
            "asked": len(asked), "answered": len(ok), "failed": len(asked) - len(ok),
            "errors": sorted({str(r.get("error"))[:120] for r in asked if not r.get("ok") and r.get("error")})[:5],
            "providers": dict(prov), "usage": meter.snapshot(), **extra}


def _meter(client) -> UsageMeter:
    return client if isinstance(client, UsageMeter) else UsageMeter(client)


def _need(client) -> None:
    if client is None:
        raise ValueError("these tests ask the simulated people, so they need a model connection (run them through the backend)")


def _pick(rng: random.Random, seq: Sequence[Any]) -> List[Any]:
    out = list(seq)
    rng.shuffle(out)
    return out


# --------------------------------------------------------------------------
# 1. Buying committee
# --------------------------------------------------------------------------

def run_buying_committee(client, model: str, offer: Any, people: List[Dict[str, Any]], mode: str = "auto",
                         committee_count: int = 12, seed: int = 17, profile: Optional[Dict[str, Any]] = None,
                         parallel: int = 8, progress: Optional[Callable[[int, int], None]] = None) -> Dict[str, Any]:
    """One call per buyer: the people who would really weigh in on this purchase talk it over without the seller."""
    _need(client)
    meter = _meter(client)
    o = offer_dict(offer, profile)
    cohort = sample_people(people, committee_count, seed)
    setting_hint = {"b2b": "This is a work purchase.", "household": "This is a personal or household purchase."}.get(mode, "")
    jobs = [{"person": p, "prompt": (
        f"WHAT IS BEING OFFERED\n{offer_text(o)}\n\nTHE BUYER\n{person_card(p)}\n\n{setting_hint}\n"
        "Simulate how this decision really gets made in this buyer's life. Include only the people who would actually "
        "weigh in: the buyer plus up to three others they would really consult (for example a partner, parent, friend, "
        "manager, finance, IT), or nobody else if they decide alone. They talk it over without the seller present; give "
        "each person's words and what they privately think. Be realistic: most offers do not get a yes on first look.\n"
        'Return JSON: {"setting": "solo|household|friends|work", "participants": [{"role": "...", "relation": "who they '
        'are to the buyer", "says": "...", "privately_thinks": "...", "stance": "yes|maybe|no", "concern": "...", '
        f'"concern_type": "{"|".join(CONCERN_TYPES)}"}}], "outcome": "buy|try_first|wait|no", "deciding_voice": "role whose '
        'view decided it", "blocker": "one sentence, or empty", "blocker_type": "same types as concern_type, or empty", '
        '"what_would_unblock": "one sentence"}')} for p in cohort]
    asked = ask_people(meter, model, jobs, parallel, progress, max_tokens=1100)
    ok = [r for r in asked if r["ok"]]
    n = len(ok)
    outcomes = Counter(str(r["data"].get("outcome") or "").lower() for r in ok)
    rows, blockers, deciders, nos, unblock = [], [], [], [], []
    sizes = []
    for r in ok:
        d, p = r["data"], r["person"]
        parts = [x for x in d.get("participants") or [] if isinstance(x, dict)][:4]
        sizes.append(len(parts) or 1)
        for x in parts:
            if str(x.get("stance") or "").lower() == "no":
                nos.append((_short(x.get("role"), 40).lower(), x.get("privately_thinks") or x.get("says")))
        if d.get("blocker"):
            blockers.append((_ctype(d.get("blocker_type")) or "other", d.get("blocker")))
        if d.get("deciding_voice"):
            deciders.append((_short(d.get("deciding_voice"), 40).lower(), ""))
        if d.get("what_would_unblock"):
            unblock.append(_short(d.get("what_would_unblock"), 220))
        rows.append({"agent_id": p.get("agent_id"), "name": p.get("name"), "segment": p.get("segment"),
                     "setting": d.get("setting"), "outcome": d.get("outcome"), "blocker": _short(d.get("blocker"), 200),
                     "what_would_unblock": _short(d.get("what_would_unblock"), 200), "provider": r.get("provider"),
                     "participants": [{k: _short(x.get(k), 220) for k in ("role", "relation", "says", "privately_thinks", "stance", "concern_type")}
                                      for x in parts]})
    summary = {
        "outcomes": {k: wilson(outcomes.get(k, 0), n) for k in ("buy", "try_first", "wait", "no")},
        "settings": dict(Counter(str(r["data"].get("setting") or "").lower() for r in ok)),
        "people_per_decision": mean_ci(sizes),
        "blockers": ranked(blockers, n), "deciding_voices": ranked(deciders, n, quotes=0),
        "roles_saying_no": ranked(nos, n), "what_would_unblock": unblock[:10],
    }
    return envelope("committee", asked, meter, offer=o, summary=summary, rows=rows)


# --------------------------------------------------------------------------
# 2. Creative optimizer
# --------------------------------------------------------------------------

def _creative(c: Any) -> Dict[str, str]:
    if isinstance(c, str):
        return {"headline": "", "text": c.strip(), "cta": ""}
    if isinstance(c, dict):
        return {"headline": str(c.get("headline") or "").strip(), "text": str(c.get("text") or c.get("body") or "").strip(),
                "cta": str(c.get("cta") or "").strip(), "platform": str(c.get("platform") or "").strip()}
    raise ValueError("creative must be text or {headline, text, cta}")


def reaction_prompt(p: Dict[str, Any], ad: Dict[str, str], brand: str = "") -> str:
    where = ad.get("platform") or "your social feed"
    return (f"WHO YOU ARE\n{person_card(p)}\n\nYou are scrolling {where} and this sponsored post from {brand or 'a brand'} appears:\n"
            f"{('HEADLINE: ' + ad['headline'] + chr(10)) if ad.get('headline') else ''}{ad.get('text', '')}\n"
            f"{('BUTTON: ' + ad['cta']) if ad.get('cta') else ''}\n\nReact the way you really would at a glance.\n"
            'Return JSON: {"stopped": true|false, "p_click": 0.0-1.0 (your honest chance of tapping it), '
            '"reaction": "your first thought in your own words", "objection": "what holds you back, or empty", '
            f'"objection_type": "{"|".join(CONCERN_TYPES)}|none"}}')


def score_ad(client, model: str, ad: Dict[str, str], cohort: List[Dict[str, Any]], brand: str = "", parallel: int = 8,
             progress=None) -> Dict[str, Any]:
    asked = ask_people(client, model, [{"person": p, "prompt": reaction_prompt(p, ad, brand)} for p in cohort], parallel, progress, 500)
    ok = [r for r in asked if r["ok"]]
    pc = {r["person"]["agent_id"]: _prob(r["data"].get("p_click")) for r in ok}
    stopped = sum(1 for r in ok if r["data"].get("stopped") is True)
    clickers = sum(1 for v in pc.values() if v is not None and v >= 0.5)
    obj = [(_ctype(r["data"].get("objection_type")), r["data"].get("objection")) for r in ok
           if r["data"].get("objection") and _ctype(r["data"].get("objection_type")) not in ("", "none")]
    return {"ad": ad, "asked": len(asked), "answered": len(ok), "p_click": mean_ci([v for v in pc.values() if v is not None]),
            "stopped": wilson(stopped, len(ok)), "would_click": wilson(clickers, len(ok)), "objections": ranked(obj, len(ok)),
            "reactions": [_short(r["data"].get("reaction"), 180) for r in ok[:6] if r["data"].get("reaction")],
            "_by_person": pc, "_asked": asked}


def run_creative_optimizer(client, model: str, creative: Any, people: List[Dict[str, Any]], generations: int = 3,
                           seed: int = 23, cohort_size: int = 40, profile: Optional[Dict[str, Any]] = None,
                           parallel: int = 8, progress: Optional[Callable[[int, int], None]] = None) -> Dict[str, Any]:
    """Test the ad, rewrite it from the objections people actually raised, re-test on the same people."""
    _need(client)
    meter = _meter(client)
    base = _creative(creative)
    if not (base["text"] or base["headline"]):
        raise ValueError("a creative is required")
    brand = str((profile or {}).get("name") or "")
    facts = product_facts(profile, {"name": brand, "headline": base["headline"], "text": base["text"], "price": "", "cta": base["cta"]})
    cohort = sample_people(people, cohort_size, seed)
    generations = max(1, min(int(generations), 5))
    total = len(cohort) * generations
    done = [0]

    def prog(_d, _t):
        done[0] += 1
        if progress:
            progress(done[0], total)

    gens: List[Dict[str, Any]] = []
    all_asked: List[Dict[str, Any]] = []
    current = dict(base)
    for g in range(1, generations + 1):
        res = score_ad(meter, model, current, cohort, brand, parallel, prog)
        all_asked += res.pop("_asked")
        res["generation"] = g
        res["change_summary"] = current.pop("_why", "Your original ad") if g > 1 else "Your original ad"
        if gens:
            base_pc = gens[0]["_by_person"]
            diffs = [res["_by_person"][a] - base_pc[a] for a in res["_by_person"]
                     if a in base_pc and res["_by_person"][a] is not None and base_pc[a] is not None]
            res["vs_original"] = {**mean_ci(diffs), "verdict": verdict_from_ci(mean_ci(diffs)), "metric": "chance of tapping, same people"}
        gens.append(res)
        if g == generations:
            break
        top = res["objections"][:4]
        if not top:
            break
        brief = {"product_facts": facts, "current_ad": current,
                 "what_people_said": [{"objection": t["key"], "people": t["count"], "examples": t["quotes"]} for t in top]}
        new = write_once(meter, model, (
            "Rewrite this ad so it answers what held people back, using only the product facts.\n"
            f"{json.dumps(brief, ensure_ascii=False)[:5000]}\n"
            'Return JSON: {"headline": "...", "text": "...", "cta": "...", "change_summary": "what you changed and which objection it answers, one sentence"}'))
        if not (new.get("text") or new.get("headline")):
            break
        current = {"headline": _short(new.get("headline"), 160), "text": _short(new.get("text"), 900), "cta": _short(new.get("cta"), 60),
                   "platform": base.get("platform", ""), "_why": _short(new.get("change_summary"), 240)}
    for x in gens:
        x.pop("_by_person", None)
    better = [x for x in gens[1:] if (x.get("vs_original") or {}).get("verdict") == "better"]
    best = max(better, key=lambda x: x["vs_original"]["mean"]) if better else None
    summary = {"generations": gens, "best_generation": best["generation"] if best else 1,
               "conclusion": (f"Version {best['generation']} raised the chance of tapping by {best['vs_original']['mean'] * 100:.1f} points "
                              f"for the same people (95% range {best['vs_original']['lo'] * 100:.1f} to {best['vs_original']['hi'] * 100:.1f})."
                              if best else "No rewrite beat the original by more than the noise; keep testing on real traffic.")}
    return envelope("creative", all_asked, meter, cohort=len(cohort), summary=summary)


# --------------------------------------------------------------------------
# 3. Sales battlecard (built from real objections, rebuttals tested)
# --------------------------------------------------------------------------

def gather_objections(survey: Optional[Dict[str, Any]] = None, pitch: Optional[Dict[str, Any]] = None,
                      feed: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """[{agent_id, type, text, source}] from the run's survey, pitch and feed comments."""
    out = []
    for r in (survey or {}).get("responses") or []:
        a = r.get("answer") or {}
        if a.get("main_objection"):
            out.append({"agent_id": r.get("agent_id"), "type": _ctype(a.get("objection_type")) or "other",
                        "text": _short(a["main_objection"], 240), "source": "survey"})
    for r in (pitch or {}).get("people") or []:
        t1 = r.get("turn1") or {}
        if t1.get("objection"):
            out.append({"agent_id": r.get("agent_id"), "type": _ctype(t1.get("objection_type")) or "other",
                        "text": _short(t1["objection"], 240), "source": "pitch"})
    for s in (feed or {}).get("sessions") or []:
        c = (s.get("ad") or {}).get("comment")
        if c:
            out.append({"agent_id": s.get("agent_id"), "type": "", "text": _short(c, 240), "source": "ad comment"})
    return out


def run_sales_battlecard(client, model: str, people: List[Dict[str, Any]], offer: Any = "", competitor: str = "",
                         pitch_data: Optional[Dict[str, Any]] = None, feed_data: Optional[Dict[str, Any]] = None,
                         survey_data: Optional[Dict[str, Any]] = None, profile: Optional[Dict[str, Any]] = None,
                         cohort_size: int = 40, seed: int = 31, parallel: int = 8,
                         progress: Optional[Callable[[int, int], None]] = None) -> Dict[str, Any]:
    """Objection playbook from what the simulated people said, then each rebuttal tested on the people who raised it."""
    _need(client)
    meter = _meter(client)
    o = offer_dict(offer, profile)
    objs = [x for x in gather_objections(survey_data, pitch_data, feed_data) if x["type"]]
    asked: List[Dict[str, Any]] = []
    cohort = sample_people(people, cohort_size, seed)
    if len(objs) < 5:                               # no run data yet: ask the cohort what would stop them
        q = ask_people(meter, model, [{"person": p, "prompt": (
            f"WHAT IS BEING OFFERED\n{offer_text(o)}\n\nWHO YOU ARE\n{person_card(p)}\n\n"
            "If a salesperson offered you this today, what would make you hesitate or say no?\n"
            f'Return JSON: {{"objection": "in your own words", "objection_type": "{"|".join(CONCERN_TYPES)}"}}')} for p in cohort],
            parallel, None, 300)
        asked += q
        objs = [{"agent_id": r["person"]["agent_id"], "type": _ctype(r["data"].get("objection_type")) or "other",
                 "text": _short(r["data"].get("objection"), 240), "source": "asked"} for r in q if r["ok"] and r["data"].get("objection")]
    if not objs:
        return envelope("battlecard", asked, meter, offer=o, summary={"available": False,
                        "reason": "No objections were found or given, so there is nothing to build a battlecard from."})
    n_obj = len(objs)
    by_type = ranked([(x["type"], x["text"]) for x in objs], n_obj, top=6, quotes=4)
    facts = {"product": product_facts(profile, o), "competitor": competitor or "", "objections": [
        {"type": t["key"], "people": t["count"], "examples": t["quotes"]} for t in by_type],
        "channels": (profile or {}).get("channels") or []}
    card = write_once(meter, model, (
        "Write a sales battlecard from these real buyer objections. For each objection type: what the buyer says (paraphrase "
        "their words), a spoken rebuttal of at most three sentences that is honest and uses only the product facts, one "
        "discovery question, the proof the seller should have ready (say what evidence to prepare; do not claim it "
        "exists), and what not to say. Then a short outreach sequence using the product's channels if given (otherwise "
        "email and a call), and five qualification questions.\n"
        f"{json.dumps(facts, ensure_ascii=False)[:6000]}\n"
        'Return JSON: {"objections": [{"type": "...", "buyer_says": "...", "rebuttal": "...", "discovery_question": "...", '
        '"proof_to_prepare": "...", "avoid_saying": "..."}], "outreach": [{"step": 1, "day": 0, "channel": "...", "message": "..."}], '
        '"qualification_questions": ["..."]}'), max_tokens=2600)
    card = guard_numbers(card, facts)
    rebuttals = {(_ctype(x.get("type")) or "other"): x for x in card.get("objections") or [] if isinstance(x, dict) and x.get("rebuttal")}
    by_person = {p["agent_id"]: p for p in people if p.get("agent_id") is not None}
    tests = []
    seen = set()
    for x in objs:
        if x["type"] in rebuttals and x["agent_id"] in by_person and x["agent_id"] not in seen and len(tests) < cohort_size:
            seen.add(x["agent_id"])
            tests.append({"person": by_person[x["agent_id"]], "otype": x["type"], "prompt": (
                f"WHO YOU ARE\n{person_card(by_person[x['agent_id']])}\n\nAbout this offer:\n{offer_text(o)}\n\n"
                f"You told the salesperson: \"{x['text']}\"\nThey answer: \"{rebuttals[x['type']]['rebuttal']}\"\n\n"
                "How do you honestly react?\n"
                'Return JSON: {"moved": "yes|somewhat|no", "reply": "what you say back", "still_worried_about": "one sentence or empty"}')})
    tested = ask_people(meter, model, tests, parallel, progress, 350)
    asked += tested
    eff = []
    for t, info in rebuttals.items():
        rs = [r for r in tested if r["ok"] and r["otype"] == t]
        moved = Counter(str(r["data"].get("moved") or "").lower() for r in rs)
        eff.append({"type": t, "tested_on": len(rs), "moved_yes": wilson(moved.get("yes", 0), len(rs)),
                    "moved_somewhat": wilson(moved.get("somewhat", 0), len(rs)),
                    "still_worried": [_short(r["data"].get("still_worried_about"), 180) for r in rs if r["data"].get("still_worried_about")][:4],
                    "replies": [_short(r["data"].get("reply"), 180) for r in rs if r["data"].get("reply")][:3]})
    summary = {"objections": by_type, "objection_sources": dict(Counter(x["source"] for x in objs)),
               "card": card, "rebuttal_test": eff}
    return envelope("battlecard", asked, meter, offer=o, competitor=competitor, summary=summary)


# --------------------------------------------------------------------------
# 4. Customer journey (several touches, each person remembers the earlier ones)
# --------------------------------------------------------------------------

def _touches(meter, model: str, o: Dict[str, str], facts: str, touches: Optional[List[Any]]) -> Tuple[List[Dict[str, str]], bool]:
    if touches and len(touches) >= 2:
        out = []
        for i, t in enumerate(touches[:4]):
            t = t if isinstance(t, dict) else {"text": str(t)}
            out.append({"name": str(t.get("name") or f"touch {i + 1}"), "channel": str(t.get("channel") or ""),
                        "day": str(t.get("day") or ""), "text": _short(t.get("text") or t.get("message"), 900)})
        return out, False
    gen = write_once(meter, model, (
        "Write the messages for a simple four-step customer journey for this offer, using only the facts: 1) the first ad, "
        "2) a reminder a few days later for people who did not respond, 3) what the offer page says, 4) a follow-up a week "
        f"later.\nFACTS:\n{facts}\n{offer_text(o)}\n"
        'Return JSON: {"touches": [{"name": "first ad", "channel": "...", "day": "0", "text": "..."}, {"name": "reminder", ...}, '
        '{"name": "offer page", ...}, {"name": "follow-up", ...}]}'), max_tokens=1600)
    out = [{"name": _short(t.get("name"), 40), "channel": _short(t.get("channel"), 40), "day": _short(t.get("day"), 10),
            "text": _short(t.get("text"), 900)} for t in gen.get("touches") or [] if isinstance(t, dict) and t.get("text")]
    if len(out) < 4:
        raise RuntimeError("could not write the journey messages; pass touches yourself")
    return out[:4], True


def run_journey_simulation(client, model: str, offer: Any, people: List[Dict[str, Any]], touches: Optional[List[Any]] = None,
                           cohort_size: int = 40, spend: Optional[float] = None, audience: Optional[int] = None,
                           price: Optional[float] = None, currency: str = "", seed: int = 29,
                           profile: Optional[Dict[str, Any]] = None, parallel: int = 8,
                           progress: Optional[Callable[[int, int], None]] = None, **_ignored: Any) -> Dict[str, Any]:
    """First ad -> reminder -> offer page -> follow-up. Each step is one call per person who reaches it, with memory."""
    _need(client)
    meter = _meter(client)
    o = offer_dict(offer, profile)
    facts = product_facts(profile, o)
    steps, generated = _touches(meter, model, o, facts, touches)
    cohort = sample_people(people, cohort_size, seed)
    state = {p["agent_id"]: {"person": p, "memory": [], "status": "unaware", "first_click": None, "signed_at": None,
                             "drop": None, "recommend": None} for p in cohort}
    asked: List[Dict[str, Any]] = []
    spec = [
        (0, lambda s: s["status"] == "unaware", "ignore|notice|click", "click"),
        (1, lambda s: s["status"] in ("unaware", "noticed"), "ignore|notice|click", "click"),
        (2, lambda s: s["status"] == "clicked", "leave|sign_up|buy", "sign_up"),
        (3, lambda s: s["status"] in ("left", "signed_up", "bought"), "", ""),
    ]
    for idx, who, actions, _ in spec:
        t = steps[idx]
        jobs = []
        for aid, s in state.items():
            if not who(s):
                continue
            mem = ("What already happened:\n" + "\n".join(f"- {m}" for m in s["memory"]) + "\n") if s["memory"] else ""
            if idx < 3:
                ask = f'Return JSON: {{"action": "{actions}", "why": "one sentence in your own words"}}'
            elif s["status"] == "left":
                ask = 'Return JSON: {"action": "ignore|come_back|sign_up|unsubscribe", "why": "one sentence"}'
            else:
                ask = ('Return JSON: {"action": "keep_using|stop|pay|cancel", "why": "one sentence", '
                       '"would_recommend": true|false}')
            jobs.append({"person": s["person"], "aid": aid, "prompt": (
                f"WHO YOU ARE\n{person_card(s['person'])}\n\n{mem}NOW ({t['name']}{', ' + t['channel'] if t['channel'] else ''}"
                f"{', day ' + t['day'] if t['day'] else ''}):\n{t['text']}\n\nWhat do you actually do?\n{ask}")})
        res = ask_people(meter, model, jobs, parallel, progress, 300)
        asked += res
        for r in res:
            s = state[r["aid"]]
            if not r["ok"]:
                s["status"] = "failed"
                continue
            act = str(r["data"].get("action") or "").lower()
            why = _short(r["data"].get("why"), 200)
            s["memory"].append(f"{t['name']}: you chose to {act.replace('_', ' ')} ({why})")
            if idx < 2:
                if act == "click":
                    s["status"], s["first_click"] = "clicked", t["name"]
                elif act == "notice":
                    s["status"] = "noticed"
                if idx == 1 and act != "click":
                    s["drop"] = s["drop"] or (t["name"], why)
            elif idx == 2:
                if act in ("sign_up", "buy"):
                    s["status"], s["signed_at"] = ("bought" if act == "buy" else "signed_up"), t["name"]
                else:
                    s["status"], s["drop"] = "left", (t["name"], why)
            else:
                if s["status"] == "left" and act in ("come_back", "sign_up"):
                    s["status"], s["signed_at"] = "signed_up", t["name"]
                elif s["status"] in ("signed_up", "bought"):
                    s["status"] = "paying" if act in ("keep_using", "pay") else "churned"
                    s["recommend"] = r["data"].get("would_recommend") is True
                    if s["status"] == "churned":
                        s["drop"] = (t["name"], why)
    valid = [s for s in state.values() if s["status"] != "failed"]
    n = len(valid)
    clicked = [s for s in valid if s["first_click"]]
    signed = [s for s in valid if s["signed_at"]]
    paying = [s for s in valid if s["status"] == "paying"]
    funnel = [{"stage": "reached", **wilson(n, n)}, {"stage": "clicked", **wilson(len(clicked), n)},
              {"stage": "signed up", **wilson(len(signed), n)}, {"stage": "still using after the follow-up", **wilson(len(paying), n)}]
    drops = ranked([(s["drop"][0], s["drop"][1]) for s in valid if s["drop"]], n, quotes=3)
    first_touch = dict(Counter(s["first_click"] for s in signed))
    last_touch = dict(Counter(s["signed_at"] for s in signed))
    rec = [s for s in valid if s["recommend"] is not None]
    summary = {"touches": steps, "touches_generated": generated, "funnel": funnel, "drop_off": drops,
               "first_touch_of_signups": first_touch, "converting_touch": last_touch,
               "would_recommend": wilson(sum(1 for s in rec if s["recommend"]), len(rec))}
    if spend and audience and n:
        rate = wilson(len(signed), n)
        def cac(pct):
            return round(float(spend) / (audience * pct / 100.0), 2) if pct else None
        summary["economics"] = {"spend": spend, "audience": audience, "currency": currency,
                                "signup_rate_pct": rate["pct"], "cost_per_signup": cac(rate["pct"]),
                                "cost_per_signup_range": [cac(rate["hi"]), cac(rate["lo"])],
                                "basis": "your spend and audience size, divided by the simulated sign-up rate and its 95% range"}
        if price:
            summary["economics"]["first_month_revenue"] = round(audience * len(paying) / n * float(price), 2)
    return envelope("journey", asked, meter, offer=o, cohort=len(cohort), summary=summary,
                    rows=[{"agent_id": s["person"].get("agent_id"), "name": s["person"].get("name"), "segment": s["person"].get("segment"),
                           "path": s["memory"], "status": s["status"]} for s in valid][:200])


# --------------------------------------------------------------------------
# 5. Pricing and packaging: each person picks one option or none
# --------------------------------------------------------------------------

def _tiers(meter, model: str, o: Dict[str, str], facts: str, tiers: Optional[List[Any]], currency: str) -> Tuple[List[Dict[str, Any]], bool]:
    if tiers:
        out = []
        for i, t in enumerate(tiers[:6]):
            t = t if isinstance(t, dict) else {"name": str(t)}
            out.append({"id": str(t.get("id") or chr(65 + i)), "name": _short(t.get("name") or f"Option {i + 1}", 60),
                        "price": _f(t.get("price")), "billing": _short(t.get("billing"), 40),
                        "includes": _short(t.get("includes") or t.get("description"), 300), "terms": _short(t.get("terms"), 200)})
        return out, False
    gen = write_once(meter, model, (
        "Propose three or four realistic ways to package and price THIS offer (for example the current price, a cheaper or "
        "smaller plan, a longer commitment, a different trial). Use only the facts; do not add features that are not there.\n"
        f"FACTS:\n{facts}\n{offer_text(o)}\nCurrency: {currency or 'the one in the facts'}\n"
        'Return JSON: {"options": [{"name": "...", "price": 0.0, "billing": "per month|per year|one-off|...", '
        '"includes": "...", "terms": "..."}]}'), max_tokens=1200)
    out = [{"id": chr(65 + i), "name": _short(t.get("name"), 60), "price": _f(t.get("price")), "billing": _short(t.get("billing"), 40),
            "includes": _short(t.get("includes"), 300), "terms": _short(t.get("terms"), 200)}
           for i, t in enumerate([t for t in gen.get("options") or [] if isinstance(t, dict) and t.get("name")][:5])]
    if len(out) < 2:
        raise RuntimeError("could not propose pricing options; pass tiers yourself")
    return out, True


def run_pricing_conjoint(client, model: str, people: List[Dict[str, Any]], tiers: Optional[List[Any]] = None,
                         base_price: Optional[float] = None, currency: str = "", seed: int = 37, offer: Any = None,
                         cohort_size: int = 60, profile: Optional[Dict[str, Any]] = None, parallel: int = 8,
                         progress: Optional[Callable[[int, int], None]] = None) -> Dict[str, Any]:
    """Each person sees the options in a random order plus "none of these" and picks one. Shares add up to 100%."""
    _need(client)
    meter = _meter(client)
    o = offer_dict(offer or {}, profile) if (offer or profile) else {"name": "", "headline": "", "text": "", "price": "", "cta": ""}
    cur = currency or str(((profile or {}).get("pricing") or {}).get("currency") or "")
    opts, generated = _tiers(meter, model, o, product_facts(profile, o), tiers, cur)
    cohort = sample_people(people, cohort_size, seed)
    rng = random.Random(seed)
    jobs = []
    for p in cohort:
        order = _pick(rng, opts)
        listing = "\n".join(f"{x['id']}) {x['name']}: {'' if x['price'] is None else f'{cur} {x['price']:g} '}{x['billing']}. "
                            f"{x['includes']} {x['terms']}".strip() for x in order)
        jobs.append({"person": p, "prompt": (
            f"WHO YOU ARE\n{person_card(p)}\n\nTHE PRODUCT\n{offer_text(o)}\n\nYour options:\n{listing}\nNONE) none of these\n\n"
            "Which one would you actually choose today, given your budget and situation?\n"
            'Return JSON: {"choice": "the letter, or NONE", "why": "one sentence", "max_price_you_would_pay": number or null, '
            '"deal_breaker": "what would stop you, or empty"}')})
    asked = ask_people(meter, model, jobs, parallel, progress, 350)
    ok = [r for r in asked if r["ok"]]
    n = len(ok)
    ids = {x["id"] for x in opts}
    picks = [(str(r["data"].get("choice") or "").strip().upper()[:4], r) for r in ok]
    picks = [(c if c in ids else "NONE", r) for c, r in picks]
    counts = Counter(c for c, _ in picks)
    seg = defaultdict(Counter)
    for c, r in picks:
        seg[str(r["person"].get("segment") or "")][c] += 1
    options = []
    for x in opts:
        sh = wilson(counts.get(x["id"], 0), n)
        options.append({**x, "share": sh, "reasons": [_short(r["data"].get("why"), 180) for c, r in picks if c == x["id"] and r["data"].get("why")][:4],
                        "revenue_per_100_people": round(sh["pct"] * x["price"], 2) if sh["pct"] is not None and x["price"] is not None else None})
    summary = {"options": options, "options_generated": generated, "currency": cur,
               "none": {"share": wilson(counts.get("NONE", 0), n),
                        "reasons": [_short(r["data"].get("why"), 180) for c, r in picks if c == "NONE" and r["data"].get("why")][:5]},
               "by_segment": {k: {"n": sum(v.values()), "top": v.most_common(1)[0][0] if v else None,
                                  "shares": {c: wilson(k2, sum(v.values()))["pct"] for c, k2 in v.items()}} for k, v in seg.items()},
               "deal_breakers": ranked([("deal breaker", r["data"].get("deal_breaker")) for _, r in picks if r["data"].get("deal_breaker")], n, top=1, quotes=6),
               "revenue_basis": "share choosing the option x its price, per 100 simulated people"}
    return envelope("pricing", asked, meter, offer=o, cohort=len(cohort), summary=summary)


# --------------------------------------------------------------------------
# 6. Competitor choice
# --------------------------------------------------------------------------

def competitor_list(competitors: Optional[List[Any]], profile: Optional[Dict[str, Any]]) -> List[Dict[str, str]]:
    out = []
    for c in competitors or (profile or {}).get("competitors") or []:
        if isinstance(c, dict):
            name = str(c.get("name") or "").strip()
            desc = str(c.get("description") or c.get("how_they_win") or c.get("offer") or "").strip()
        else:
            name, desc = str(c).strip(), ""
        if name and name.lower() not in {x["name"].lower() for x in out}:
            out.append({"name": name[:80], "description": desc[:400]})
    return out[:5]


def _choice_jobs(cohort, brand: str, o: Dict[str, str], comps: List[Dict[str, str]], rng: random.Random, move: str = ""):
    jobs = []
    for p in cohort:
        options = [{"name": brand or "this product", "description": offer_text(o)}] + comps
        options.append({"name": "None of these (keep doing what I do now)", "description": ""})
        order = _pick(rng, options[:-1]) + [options[-1]]
        listing = "\n".join(f"- {x['name']}{(': ' + x['description']) if x['description'] else ''}" for x in order)
        news = f"\nNEWS THIS WEEK: {move}\n" if move else ""
        jobs.append({"person": p, "prompt": (
            f"WHO YOU ARE\n{person_card(p)}\n\nYou are choosing between these options:\n{listing}\n{news}\n"
            "Which would you actually pick, given your situation?\n"
            f'Return JSON: {{"choice": "exact name from the list", "why": "one sentence", "what_would_make_you_choose_{(brand or "this product")[:30]}": '
            '"one sentence, or empty if you chose it"}')})
    return jobs


def _choice_name(data: Dict[str, Any], names: List[str]) -> str:
    c = str(data.get("choice") or "").strip().lower()
    for nm in names:
        if c == nm.lower() or (c and (c in nm.lower() or nm.lower() in c)):
            return nm
    return names[-1] if c.startswith("none") else ""


def run_competitor_intelligence(client, model: str, offer: Any, people: List[Dict[str, Any]],
                                competitors: Optional[List[Any]] = None, seed: int = 41, moves: Optional[List[str]] = None,
                                cohort_size: int = 60, profile: Optional[Dict[str, Any]] = None, parallel: int = 8,
                                progress: Optional[Callable[[int, int], None]] = None) -> Dict[str, Any]:
    """Each person chooses between you, your competitors and doing nothing. Suggestions cite what people said."""
    _need(client)
    meter = _meter(client)
    o = offer_dict(offer, profile)
    comps = competitor_list(competitors, profile)
    if not comps:
        return envelope("competitors", [], meter, offer=o, summary={"available": False, "reason": (
            "No competitors were given and the product profile lists none. Pass --competitors (names, or "
            "@competitors.json with name and description) to run this test.")})
    brand = o.get("name") or "this product"
    names = [brand] + [c["name"] for c in comps] + ["None of these (keep doing what I do now)"]
    cohort = sample_people(people, cohort_size, seed)
    moves = [m for m in (moves or []) if str(m).strip()][:3]
    total = len(cohort) * (1 + len(moves))
    done = [0]

    def prog(_d, _t):
        done[0] += 1
        if progress:
            progress(done[0], total)

    base = ask_people(meter, model, _choice_jobs(cohort, brand, o, comps, random.Random(seed)), parallel, prog, 350)
    asked = list(base)
    ok = [r for r in base if r["ok"]]
    n = len(ok)
    chosen = {r["person"]["agent_id"]: _choice_name(r["data"], names) for r in ok}
    counts = Counter(v for v in chosen.values() if v)
    key = next((k for k in (ok[0]["data"] if ok else {}) if k.startswith("what_would_make_you_choose")), "")
    options = [{"name": nm, "share": wilson(counts.get(nm, 0), n),
                "why_people_chose_it": [_short(r["data"].get("why"), 180) for r in ok if chosen.get(r["person"]["agent_id"]) == nm and r["data"].get("why")][:4]}
               for nm in names]
    triggers = [(_short(r["data"].get(key), 200), "") for r in ok if key and r["data"].get(key) and chosen.get(r["person"]["agent_id"]) != brand]
    trig = [t for t, _ in triggers][:12]
    facts = {"brand": brand, "options": [{"name": x["name"], "chosen_by": x["share"]["k"], "of": n,
                                          "reasons": x["why_people_chose_it"]} for x in options],
             "what_would_make_them_choose_the_brand": trig, "product": product_facts(profile, o)}
    sugg = write_once(meter, model, (
        f"These are the choices simulated buyers made between {brand}, its competitors and doing nothing, with their "
        "reasons. Suggest up to five concrete changes for the brand (product, price or packaging, trust, message), each "
        "tied to what people said. Cite only the counts given; do not invent numbers or facts.\n"
        f"{json.dumps(facts, ensure_ascii=False)[:6000]}\n"
        'Return JSON: {"suggestions": [{"title": "...", "change": "what to do", "evidence": "what people said, with the counts '
        'given", "kind": "product|pricing|trust|message|channel", "effort": "low|medium|high"}]}'), max_tokens=1600)
    sugg = guard_numbers(sugg, facts)
    move_results = []
    for i, m in enumerate(moves):
        res = ask_people(meter, model, _choice_jobs(cohort, brand, o, comps, random.Random(seed), move=m), parallel, prog, 350)
        asked += res
        after = {r["person"]["agent_id"]: _choice_name(r["data"], names) for r in res if r["ok"]}
        both = [a for a in after if a in chosen]
        lost = sum(1 for a in both if chosen[a] == brand and after[a] != brand)
        won = sum(1 for a in both if chosen[a] != brand and after[a] == brand)
        b0 = sum(1 for a in both if chosen[a] == brand)
        b1 = sum(1 for a in both if after[a] == brand)
        move_results.append({"move": m, "people": len(both), "brand_share_before": wilson(b0, len(both)),
                             "brand_share_after": wilson(b1, len(both)), "switched_away": lost, "switched_to_brand": won,
                             "why": [_short(r["data"].get("why"), 180) for r in res if r["ok"] and after.get(r["person"]["agent_id"]) != chosen.get(r["person"]["agent_id"])][:4]})
    summary = {"competitors": comps, "options": options, "brand": brand,
               "what_would_make_them_choose_you": trig,
               "suggestions": [s for s in sugg.get("suggestions") or [] if isinstance(s, dict) and s.get("title")][:5],
               "moves": move_results}
    return envelope("competitors", asked, meter, offer=o, cohort=len(cohort), summary=summary)


# --------------------------------------------------------------------------
# Several engines in one pass
# --------------------------------------------------------------------------

ENGINES = ("committee", "creative", "battlecard", "journey", "pricing", "competitors")
FILES = {"committee": "buying_committee.json", "creative": "creative_optimizer.json", "battlecard": "sales_battlecard.json",
         "journey": "journey_sim.json", "pricing": "pricing_conjoint.json", "competitors": "competitor_intel.json"}


def run_engine(name: str, client, model: str, people: List[Dict[str, Any]], opts: Dict[str, Any],
               profile: Optional[Dict[str, Any]] = None, run_data: Optional[Dict[str, Any]] = None,
               progress: Optional[Callable[[int, int], None]] = None) -> Dict[str, Any]:
    rd = run_data or {}
    offer = opts.get("offer")
    cohort = int(opts.get("cohort") or 0)
    par = int(opts.get("parallel") or 8)
    seed = int(opts.get("seed") or 19)
    if name == "committee":
        return run_buying_committee(client, model, offer, people, mode=str(opts.get("mode") or "auto"),
                                    committee_count=cohort or 12, seed=seed, profile=profile, parallel=par, progress=progress)
    if name == "creative":
        creative = opts.get("creative") or offer or ((rd.get("feed_test") or {}).get("creatives") or [None])[0]
        return run_creative_optimizer(client, model, creative, people, generations=int(opts.get("generations") or 3),
                                      seed=seed, cohort_size=cohort or 40, profile=profile, parallel=par, progress=progress)
    if name == "battlecard":
        return run_sales_battlecard(client, model, people, offer=offer, competitor=str(opts.get("competitor") or ""),
                                    pitch_data=rd.get("pitch"), feed_data=rd.get("feed_test"), survey_data=rd.get("survey"),
                                    profile=profile, cohort_size=cohort or 40, seed=seed, parallel=par, progress=progress)
    if name == "journey":
        return run_journey_simulation(client, model, offer, people, touches=opts.get("touches"), cohort_size=cohort or 40,
                                      spend=_f(opts.get("spend")), audience=int(opts["audience"]) if opts.get("audience") else None,
                                      price=_f(opts.get("price")), currency=str(opts.get("currency") or ""), seed=seed,
                                      profile=profile, parallel=par, progress=progress)
    if name == "pricing":
        return run_pricing_conjoint(client, model, people, tiers=opts.get("tiers"), currency=str(opts.get("currency") or ""),
                                    seed=seed, offer=offer, cohort_size=cohort or 60, profile=profile, parallel=par, progress=progress)
    if name == "competitors":
        return run_competitor_intelligence(client, model, offer, people, competitors=opts.get("competitors"), seed=seed,
                                           moves=opts.get("moves"), cohort_size=cohort or 60, profile=profile,
                                           parallel=par, progress=progress)
    raise ValueError(f"unknown test: {name} (choose from {', '.join(ENGINES)})")


def run_full_gtm_suite(client, model: str, people: List[Dict[str, Any]], offer: Any = None, competitor: str = "",
                       competitors: Optional[List[Any]] = None, run_dir: Optional[str] = None, seed: int = 19,
                       engines: Optional[List[str]] = None, opts: Optional[Dict[str, Any]] = None,
                       profile: Optional[Dict[str, Any]] = None, run_data: Optional[Dict[str, Any]] = None,
                       progress: Optional[Callable[[int, int], None]] = None) -> Dict[str, Any]:
    """Run the chosen engines (default: all) and save each result plus gtm_suite.json in run_dir."""
    _need(client)
    names = [e for e in (engines or ENGINES) if e in ENGINES]
    o = {**(opts or {}), "offer": offer, "competitor": competitor, "competitors": competitors, "seed": seed}
    out: Dict[str, Any] = {"engines": {}, "errors": {}}
    for i, name in enumerate(names):
        def prog(d, t, i=i):
            if progress:
                progress(i * 1000 + int(1000 * d / max(t, 1)), len(names) * 1000)
        try:
            res = run_engine(name, client, model, people, o, profile, run_data, prog)
            out["engines"][name] = res
            if run_dir:
                with open(os.path.join(run_dir, FILES[name]), "w", encoding="utf-8") as f:
                    json.dump(res, f, ensure_ascii=False, indent=2)
        except Exception as e:  # noqa: BLE001 - one engine failing does not stop the others
            logger.warning(f"gtm {name} failed: {e}")
            out["errors"][name] = str(e)[:300]
    if run_dir:
        with open(os.path.join(run_dir, "gtm_suite.json"), "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
    return out
