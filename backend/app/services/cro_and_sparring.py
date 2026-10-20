"""
cro_and_sparring.py - conversion and sales-practice tests answered by the simulated people.

  * fetch_url_snapshot: the text of a public page (redirects re-checked, private addresses refused).
  * run_landing_teardown: a five-second test and a scroll test of a landing page, one call per person, then one
    grading call that checks whether each person understood what the product is.
  * run_sales_roleplay: the rep's messages played to each buyer in turn; each buyer answers and scores the rep.
  * run_causal_whatif_model: a small choice experiment. Each person picks between two randomly built versions of
    the offer in several rounds; the effect of each attribute level is the difference in pick rate, with a 95%
    range from resampling people.
  * run_segment_personalizer: one ad variant written per audience from that audience's own objections, tested
    against the original on the same people.
"""

from __future__ import annotations

import html as _html
import json
import random
import re
import urllib.request
from collections import Counter, defaultdict
from typing import Any, Callable, Dict, List, Optional

from .gtm_suite import (CONCERN_TYPES, _f, _need, _short, ask_people, envelope, gather_objections, mean_ci, offer_dict,
                        offer_text, person_card, product_facts, ranked, sample_people, score_ad, verdict_from_ci, wilson,
                        write_once, _creative, _meter)
from .website_test import validate_url

UA = "MarketMirror/0.3 (simulated buyer page check)"


# --------------------------------------------------------------------------
# Page text
# --------------------------------------------------------------------------

def _strip_tags(raw_html: str) -> str:
    txt = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", raw_html)
    txt = re.sub(r"(?s)<[^>]+>", " ", txt)
    return _html.unescape(re.sub(r"\s+", " ", txt)).strip()


class _CheckedRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl, allow_loopback=False, resolve=True)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_url_snapshot(url: str, timeout: float = 8.0) -> Dict[str, Any]:
    """Title, headings, buttons, prices and readable text of a public page. Private and loopback addresses are
    refused, including after a redirect."""
    safe_url = validate_url(url, allow_loopback=False, resolve=True)
    opener = urllib.request.build_opener(_CheckedRedirects)
    with opener.open(urllib.request.Request(safe_url, headers={"User-Agent": UA}), timeout=timeout) as resp:
        raw = resp.read(400_000).decode("utf-8", errors="replace")
    title = re.search(r"(?is)<title[^>]*>(.*?)</title>", raw)
    meta = re.search(r'(?is)<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', raw)
    h1 = [t for t in (_strip_tags(m) for m in re.findall(r"(?is)<h1[^>]*>(.*?)</h1>", raw)) if t][:3]
    h2 = [t for t in (_strip_tags(m) for m in re.findall(r"(?is)<h2[^>]*>(.*?)</h2>", raw)) if t][:8]
    buttons = [t for t in (_strip_tags(m) for m in re.findall(r"(?is)<button[^>]*>(.*?)</button>", raw)) if 2 <= len(t) <= 45][:6]
    text = _strip_tags(raw)
    prices = re.findall(r"(?:[A-Z]{3}|[$₹€£¥])\s?\d[\d,]*(?:\.\d{1,2})?(?:\s*/\s*\w+)?", text)[:6]
    return {"url": safe_url, "title": _strip_tags(title.group(1)) if title else "",
            "meta_description": _html.unescape(meta.group(1)).strip() if meta else "", "h1": h1[0] if h1 else "",
            "h2_list": h2, "buttons": buttons, "pricing_snippets": prices, "text": text[:6000]}


def _page(page: Any) -> Dict[str, Any]:
    if isinstance(page, dict):
        text = str(page.get("text") or page.get("body") or "")
        return {"url": str(page.get("url") or ""), "title": str(page.get("title") or ""), "h1": str(page.get("h1") or page.get("headline") or ""),
                "text": text[:6000]}
    s = str(page or "").strip()
    if not s:
        raise ValueError("a page is required: a public URL or the page text")
    if re.match(r"^https?://", s, re.I):
        return fetch_url_snapshot(s)
    return {"url": "", "title": "", "h1": "", "text": s[:6000]}


# --------------------------------------------------------------------------
# Landing page: five-second test and scroll test
# --------------------------------------------------------------------------

def run_landing_teardown(client, model: str, page: Any, people: List[Dict[str, Any]], seed: int = 23,
                         cohort_size: int = 40, profile: Optional[Dict[str, Any]] = None, parallel: int = 8,
                         progress: Optional[Callable[[int, int], None]] = None) -> Dict[str, Any]:
    _need(client)
    meter = _meter(client)
    pg = _page(page)
    top = " ".join(x for x in (pg.get("title"), pg.get("h1"), pg["text"][:600]) if x)
    rest = pg["text"][600:4000]
    cohort = sample_people(people, cohort_size, seed)
    jobs = [{"person": p, "prompt": (
        f"WHO YOU ARE\n{person_card(p)}\n\nYou tapped an ad and this page opens. In the first five seconds you see:\n{top}\n\n"
        f"If you keep scrolling, the page continues:\n{rest}\n\n"
        "Answer as yourself, honestly.\n"
        'Return JSON: {"what_is_it": "what you think this is, in your words", "who_is_it_for": "...", '
        '"would_continue": "yes|maybe|no", "read_until": "top|middle|end", "confusing": "what was unclear, or empty", '
        f'"confusing_type": "{"|".join(CONCERN_TYPES)}|none", "missing_to_decide": "what you would need to know, or empty", '
        '"noticed_trust_signal": "what made it feel trustworthy, or empty"}')} for p in cohort]
    asked = ask_people(meter, model, jobs, parallel, progress, 450)
    ok = [r for r in asked if r["ok"]]
    n = len(ok)
    truth = str((profile or {}).get("one_liner") or (profile or {}).get("what_it_does") or pg.get("h1") or pg.get("title") or "")
    grades: Dict[int, str] = {}
    if truth and ok:
        answers = [{"i": i, "answer": _short(r["data"].get("what_is_it"), 200)} for i, r in enumerate(ok)]
        g = write_once(meter, model, (
            f"The product is: {truth}\nGrade each answer: did the person understand what it is? correct, partly or wrong.\n"
            f"{json.dumps(answers, ensure_ascii=False)[:9000]}\n"
            'Return JSON: {"grades": [{"i": 0, "grade": "correct|partly|wrong"}]}'), max_tokens=1500, temperature=0.1)
        for x in g.get("grades") or []:
            if isinstance(x, dict) and isinstance(x.get("i"), int) and 0 <= x["i"] < len(ok):
                grades[x["i"]] = str(x.get("grade") or "").lower()
    cont = Counter(str(r["data"].get("would_continue") or "").lower() for r in ok)
    depth = Counter(str(r["data"].get("read_until") or "").lower() for r in ok)
    graded = [v for v in grades.values() if v in ("correct", "partly", "wrong")]
    summary = {"page": {k: pg.get(k) for k in ("url", "title", "h1")},
               "understood": {k: wilson(graded.count(k), len(graded)) for k in ("correct", "partly", "wrong")} if graded else None,
               "understood_basis": f"graded against: {truth[:200]}" if graded else "no product description to grade against",
               "would_continue": {k: wilson(cont.get(k, 0), n) for k in ("yes", "maybe", "no")},
               "read_until": {k: wilson(depth.get(k, 0), n) for k in ("top", "middle", "end")},
               "confusing": ranked([(str(r["data"].get("confusing_type") or "other").lower(), r["data"].get("confusing"))
                                    for r in ok if r["data"].get("confusing")], n),
               "missing_to_decide": ranked([("missing", r["data"].get("missing_to_decide")) for r in ok if r["data"].get("missing_to_decide")], n, top=1, quotes=8),
               "trust_signals_noticed": [_short(r["data"].get("noticed_trust_signal"), 160) for r in ok if r["data"].get("noticed_trust_signal")][:6],
               "what_people_thought_it_was": [_short(r["data"].get("what_is_it"), 160) for r in ok[:8]]}
    return envelope("teardown", asked, meter, cohort=len(cohort), summary=summary)


# --------------------------------------------------------------------------
# Sales roleplay: the rep's messages, each buyer answers and scores
# --------------------------------------------------------------------------

def run_sales_roleplay(client, model: str, people: List[Dict[str, Any]], offer: Any = "", rep_messages: Optional[List[str]] = None,
                       seed: int = 29, cohort_size: int = 20, profile: Optional[Dict[str, Any]] = None, parallel: int = 8,
                       progress: Optional[Callable[[int, int], None]] = None) -> Dict[str, Any]:
    _need(client)
    meter = _meter(client)
    msgs = [str(m).strip() for m in (rep_messages or []) if str(m).strip()][:4]
    if not msgs:
        raise ValueError("pass the rep's messages (an opener and up to three follow-ups) to play to the buyers")
    o = offer_dict(offer, profile) if (offer or profile) else {"name": "", "headline": "", "text": "", "price": "", "cta": ""}
    cohort = sample_people(people, cohort_size, seed)
    script = "\n".join(f"Message {i + 1}: {m}" for i, m in enumerate(msgs))
    jobs = [{"person": p, "prompt": (
        f"WHO YOU ARE\n{person_card(p)}\n\n{('ABOUT THE PRODUCT' + chr(10) + offer_text(o) + chr(10) + chr(10)) if o.get('headline') or o.get('text') else ''}"
        f"A salesperson contacts you. They send these messages one after another, whatever you reply:\n{script}\n\n"
        "Reply to each message as you really would (you may stop engaging), then score the salesperson.\n"
        '{"replies": ["your reply to message 1", "..."], "outcome": "agreed_to_next_step|maybe_later|no", '
        '"scores": {"clear": 1-5, "relevant_to_me": 1-5, "trustworthy": 1-5, "pushy": 1-5}, '
        '"what_they_should_have_said": "one sentence", "lost_me_at": "message number, or 0 if never"}\n'
        "Return that JSON only.")} for p in cohort]
    asked = ask_people(meter, model, jobs, parallel, progress, 900)
    ok = [r for r in asked if r["ok"]]
    n = len(ok)
    out = Counter(str(r["data"].get("outcome") or "").lower() for r in ok)
    scores = {k: mean_ci([_f((r["data"].get("scores") or {}).get(k)) for r in ok]) for k in ("clear", "relevant_to_me", "trustworthy", "pushy")}
    lost = Counter(str(r["data"].get("lost_me_at") or "0") for r in ok)
    summary = {"messages": msgs, "outcomes": {k: wilson(out.get(k, 0), n) for k in ("agreed_to_next_step", "maybe_later", "no")},
               "scores": scores, "lost_at_message": {k: wilson(v, n) for k, v in sorted(lost.items())},
               "advice": ranked([("advice", r["data"].get("what_they_should_have_said")) for r in ok if r["data"].get("what_they_should_have_said")], n, top=1, quotes=8),
               "transcripts": [{"name": r["person"].get("name"), "segment": r["person"].get("segment"),
                                "replies": [_short(x, 200) for x in (r["data"].get("replies") or [])][:4],
                                "outcome": r["data"].get("outcome")} for r in ok[:12]]}
    return envelope("roleplay", asked, meter, cohort=len(cohort), summary=summary)


# --------------------------------------------------------------------------
# What-if choice experiment
# --------------------------------------------------------------------------

def _attributes(meter, model: str, o: Dict[str, str], facts: str, attributes: Optional[Dict[str, List[Any]]]) -> Dict[str, List[str]]:
    if attributes:
        out = {str(k)[:40]: [str(v)[:60] for v in vals][:4] for k, vals in attributes.items() if isinstance(vals, (list, tuple)) and len(vals) >= 2}
        if out:
            return dict(list(out.items())[:4])
    g = write_once(meter, model, (
        "Pick three attributes of THIS offer that the seller could realistically change (for example price, trial length, "
        "payment terms, plan size), each with two or three realistic levels including the current one. Use only the facts.\n"
        f"FACTS:\n{facts}\n{offer_text(o)}\n"
        'Return JSON: {"attributes": {"name": ["current level", "alternative", "..."]}}'), max_tokens=600, temperature=0.3)
    out = {str(k)[:40]: [str(v)[:60] for v in vals][:3] for k, vals in (g.get("attributes") or {}).items() if isinstance(vals, list) and len(vals) >= 2}
    if len(out) < 2:
        raise RuntimeError("could not pick attributes; pass them yourself")
    return dict(list(out.items())[:4])


def run_causal_whatif_model(people: List[Dict[str, Any]], seed: int = 31, client=None, model: str = "", offer: Any = "",
                            attributes: Optional[Dict[str, List[Any]]] = None, rounds: int = 4, cohort_size: int = 60,
                            profile: Optional[Dict[str, Any]] = None, parallel: int = 8,
                            progress: Optional[Callable[[int, int], None]] = None) -> Dict[str, Any]:
    """Each person makes `rounds` choices between two random versions of the offer (or neither)."""
    _need(client)
    meter = _meter(client)
    o = offer_dict(offer, profile)
    attrs = _attributes(meter, model, o, product_facts(profile, o), attributes)
    names = list(attrs)
    rng = random.Random(seed)
    cohort = sample_people(people, cohort_size, seed)
    jobs = []
    for p in cohort:
        tasks = []
        for _ in range(max(2, min(rounds, 6))):
            a = {k: rng.choice(attrs[k]) for k in names}
            b = {k: rng.choice(attrs[k]) for k in names}
            while b == a:
                b = {k: rng.choice(attrs[k]) for k in names}
            tasks.append((a, b))
        listing = "\n\n".join(f"Choice {i + 1}:\n  A) " + "; ".join(f"{k}: {v}" for k, v in a.items()) +
                              "\n  B) " + "; ".join(f"{k}: {v}" for k, v in b.items()) for i, (a, b) in enumerate(tasks))
        jobs.append({"person": p, "tasks": tasks, "prompt": (
            f"WHO YOU ARE\n{person_card(p)}\n\nTHE PRODUCT\n{offer_text(o)}\n\nFor each choice, pick the version you would "
            f"actually take, or neither.\n{listing}\n\n"
            'Return JSON: {"choices": ["A|B|neither", "..."], "what_mattered_most": "one sentence"}')})
    asked = ask_people(meter, model, jobs, parallel, progress, 300)
    shown: Dict[str, Counter] = defaultdict(Counter)
    picked: Dict[str, Counter] = defaultdict(Counter)
    per_person: List[Dict[str, Dict[str, List[int]]]] = []
    neither = total = 0
    for r in asked:
        if not r["ok"]:
            continue
        ch = [str(x).strip().lower() for x in (r["data"].get("choices") or [])]
        pp: Dict[str, Dict[str, List[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
        for (a, b), c in zip(r["tasks"], ch):
            total += 1
            if c.startswith("neither"):
                neither += 1
            for label, prof in (("a", a), ("b", b)):
                hit = int(c == label)
                for k, v in prof.items():
                    shown[k][v] += 1
                    picked[k][v] += hit
                    pp[k][v][0] += 1
                    pp[k][v][1] += hit
        per_person.append(pp)
    effects = []
    brng = random.Random(seed + 1)
    for k in names:
        levels = attrs[k]
        base = levels[0]
        for v in levels[1:]:
            def rate(lvl, rows):
                s = sum(x[k][lvl][0] for x in rows)
                return sum(x[k][lvl][1] for x in rows) / s if s else None
            point = (rate(v, per_person), rate(base, per_person))
            boots = []
            for _ in range(300):
                sample = [per_person[brng.randrange(len(per_person))] for _ in per_person] if per_person else []
                rv, rb = rate(v, sample), rate(base, sample)
                if rv is not None and rb is not None:
                    boots.append(rv - rb)
            boots.sort()
            eff = (point[0] - point[1]) if None not in point else None
            effects.append({"attribute": k, "level": v, "versus": base,
                            "effect_pts": None if eff is None else round(100 * eff, 1),
                            "lo": round(100 * boots[int(0.025 * len(boots))], 1) if len(boots) > 20 else None,
                            "hi": round(100 * boots[int(0.975 * len(boots)) - 1], 1) if len(boots) > 20 else None,
                            "pick_rate_pct": None if point[0] is None else round(100 * point[0], 1)})
    for e in effects:
        e["verdict"] = verdict_from_ci({"lo": e["lo"], "hi": e["hi"]}) if e["lo"] is not None else "too few answers"
    summary = {"attributes": attrs, "effects": effects, "choices": total, "neither": wilson(neither, total),
               "what_mattered_most": [_short(r["data"].get("what_mattered_most"), 160) for r in asked if r["ok"] and r["data"].get("what_mattered_most")][:8],
               "method": "Each person chose between two random versions in several rounds. Effect = pick rate with the level minus "
                         "pick rate with the first (current) level, in points; 95% range from resampling people."}
    return envelope("whatif", asked, meter, cohort=len(cohort), summary=summary)


# --------------------------------------------------------------------------
# Per-audience ad variants
# --------------------------------------------------------------------------

def run_segment_personalizer(client, model: str, offer: Any, people: List[Dict[str, Any]], seed: int = 37,
                             creative: Any = None, segments: int = 4, per_segment: int = 12,
                             profile: Optional[Dict[str, Any]] = None, run_data: Optional[Dict[str, Any]] = None,
                             parallel: int = 8, progress: Optional[Callable[[int, int], None]] = None) -> Dict[str, Any]:
    _need(client)
    meter = _meter(client)
    o = offer_dict(offer, profile)
    base = _creative(creative) if creative else {"headline": o["headline"], "text": o["text"], "cta": o.get("cta", "")}
    brand = o.get("name") or ""
    by_seg: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for p in people:
        by_seg[str(p.get("segment") or "Everyone")].append(p)
    segs = sorted(by_seg, key=lambda s: -len(by_seg[s]))[:max(1, segments)]
    rd = run_data or {}
    objs = gather_objections(rd.get("survey"), rd.get("pitch"), rd.get("feed_test"))
    seg_of = {p.get("agent_id"): str(p.get("segment") or "Everyone") for p in people}
    asked_all = []
    results = []
    for si, seg in enumerate(segs):
        cohort = sample_people(by_seg[seg], per_segment, seed + si)
        heard = [x["text"] for x in objs if seg_of.get(x["agent_id"]) == seg][:8]
        variant = write_once(meter, model, (
            f"Rewrite this ad for the audience '{seg}', answering what this audience said, using only the facts.\n"
            f"FACTS:\n{product_facts(profile, o)}\nAD:\n{json.dumps(base, ensure_ascii=False)}\n"
            f"WHAT THIS AUDIENCE SAID: {json.dumps(heard, ensure_ascii=False) if heard else 'nothing recorded yet'}\n"
            'Return JSON: {"headline": "...", "text": "...", "cta": "...", "angle": "one sentence"}'), max_tokens=900)
        if not (variant.get("text") or variant.get("headline")):
            continue
        v = {"headline": _short(variant.get("headline"), 160), "text": _short(variant.get("text"), 900), "cta": _short(variant.get("cta"), 60)}
        a = score_ad(meter, model, base, cohort, brand, parallel)
        b = score_ad(meter, model, v, cohort, brand, parallel)
        asked_all += a.pop("_asked") + b.pop("_asked")
        diffs = [b["_by_person"][k] - a["_by_person"][k] for k in b["_by_person"]
                 if k in a["_by_person"] and a["_by_person"][k] is not None and b["_by_person"][k] is not None]
        ci = mean_ci(diffs)
        results.append({"segment": seg, "people": len(cohort), "variant": v, "angle": _short(variant.get("angle"), 200),
                        "objections_used": len(heard), "original_p_click": a["p_click"], "variant_p_click": b["p_click"],
                        "difference": {**ci, "verdict": verdict_from_ci(ci)}, "variant_objections": b["objections"][:3]})
        if progress:
            progress(si + 1, len(segs))
    return envelope("personalize", asked_all, meter, summary={"original": base, "segments": results})
