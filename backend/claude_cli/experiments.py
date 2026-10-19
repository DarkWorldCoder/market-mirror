"""
experiments.py - test anything: one experiment spec, one dispatcher, one result shape.

    {"type": "ad|message|price|offer|positioning|naming|landing|launch|pitch|email|creator_post|channel_mix|conjoint",
     "name": "...", "variants": [...], "audience": {"segments": [...], "countries": [...]}, "metric": "...",
     "budget": {...}, "rounds": 6, ...type-specific keys}

Every type runs on the existing engines (feed test, survey, rounds + events, pitch, email test) and writes
`experiment_result.json`: variants with the chosen metric, a 95% margin, the winner, the lift over the runner-up,
and one line on how to read it, so studies (several scenarios x seeds) and the dashboard treat every test alike.
Stdlib only; the engines are called through the CLI modules passed in by mirofish.py.
"""

from __future__ import annotations

import json
import math
import os
from typing import Any, Callable, Dict, List, Optional

TYPES = ("ad", "message", "price", "offer", "positioning", "naming", "landing", "launch", "pitch", "email",
         "creator_post", "channel_mix", "conjoint", "search_content", "organic_content", "nurture", "retention",
         "referral", "sales_outreach", "sales_followup")
METRIC_DEFAULT = {"ad": "expected_ctr", "message": "convert_yes", "price": "convert_yes", "offer": "convert_yes",
                  "positioning": "convert_yes", "naming": "convert_yes", "landing": "conversion_after_click",
                  "launch": "brand_post_engagement", "pitch": "pitch_score", "email": "click_rate",
                  "creator_post": "brand_post_engagement", "channel_mix": "expected_ctr", "conjoint": "share_of_choice",
                  "search_content": "convert_yes", "organic_content": "convert_yes", "nurture": "click_rate",
                  "retention": "click_rate", "referral": "convert_yes", "sales_outreach": "pitch_score",
                  "sales_followup": "pitch_score"}
PLATFORMS = ("facebook", "instagram", "tiktok", "reddit", "linkedin", "x")


def normalize(spec: Any) -> Dict[str, Any]:
    if not isinstance(spec, dict):
        raise ValueError("experiment spec must be a JSON object")
    t = str(spec.get("type") or "").lower().strip()
    if t not in TYPES:
        raise ValueError(f"experiment type must be one of {', '.join(TYPES)}")
    variants = spec.get("variants") or []
    if t not in ("launch", "landing", "conjoint") and len(variants) < 1:
        raise ValueError("variants are required")
    if t in ("message", "offer", "positioning", "naming", "price", "search_content", "organic_content",
             "nurture", "retention", "referral", "sales_outreach", "sales_followup") and len(variants) < 2:
        raise ValueError(f"a {t} test needs at least two variants")
    out = {"type": t, "name": str(spec.get("name") or t), "variants": variants, "audience": spec.get("audience") or {},
           "metric": str(spec.get("metric") or METRIC_DEFAULT[t]), "budget": spec.get("budget") or {}, "rounds": int(spec.get("rounds") or 0),
           "seeds": max(1, int(spec.get("seeds") or 1)), "extra": {k: v for k, v in spec.items()
                                                                 if k not in ("type", "name", "variants", "audience", "metric", "budget", "rounds", "seeds")}}
    contexts = {"search_content": "search query and result snippet", "organic_content": "unpaid content feed",
                "nurture": "opted-in lifecycle inbox", "retention": "existing-customer inbox",
                "referral": "customer referral invitation", "sales_outreach": "first sales conversation",
                "sales_followup": "follow-up sales conversation"}
    out["exposure_context"] = str(spec.get("exposure_context") or contexts.get(t) or t)
    out["next_real_world_test"] = str(spec.get("next_real_world_test") or
                                      f"Randomize the same audience between variants in a real {t} test and measure {out['metric']}.")
    return out


def _vid(v: Any, i: int) -> str:
    if isinstance(v, dict):
        return str(v.get("id") or v.get("name") or f"v{i + 1}")
    return f"v{i + 1}"


def _vtext(v: Any) -> str:
    if isinstance(v, dict):
        return str(v.get("text") or v.get("message") or v.get("body") or v.get("name") or v.get("script") or "")
    return str(v)


# --------------------------------------------------------------------------
# Variant -> engine inputs
# --------------------------------------------------------------------------

def to_creatives(exp: Dict[str, Any]) -> Dict[str, Any]:
    """ad / channel_mix / landing -> feed-test spec."""
    aud = exp["audience"]
    creatives = []
    if exp["type"] == "channel_mix":
        base = exp["variants"][0] if isinstance(exp["variants"][0], dict) else {"text": str(exp["variants"][0])}
        plats = [str(p).lower() for p in (exp["extra"].get("platforms") or [v.get("platform") for v in exp["variants"] if isinstance(v, dict) and v.get("platform")] or ["facebook", "instagram"])]
        for p in plats:
            creatives.append({**base, "id": f"{base.get('id') or 'ad'}_{p}", "platform": p, "page": base.get("page") or "Brand",
                              "segments": aud.get("segments") or [], "countries": aud.get("countries") or []})
    else:
        for i, v in enumerate(exp["variants"]):
            c = dict(v) if isinstance(v, dict) else {"text": str(v)}
            c.setdefault("id", _vid(v, i))
            c.setdefault("platform", exp["extra"].get("platform") or "facebook")
            c.setdefault("page", exp["extra"].get("page") or "Brand")
            c.setdefault("segments", aud.get("segments") or [])
            c.setdefault("countries", aud.get("countries") or [])
            creatives.append(c)
    spec: Dict[str, Any] = {"creatives": creatives}
    if exp["extra"].get("landing"):
        spec["landing"] = exp["extra"]["landing"]
    if exp["extra"].get("benchmarks") or exp["budget"]:
        bench = dict(exp["extra"].get("benchmarks") or {})
        if exp["budget"].get("amount") and exp["budget"].get("cpm"):
            for p in {c["platform"] for c in creatives}:
                bench.setdefault(p, {}).update({"budget": exp["budget"]["amount"], "cpm": exp["budget"]["cpm"],
                                                "currency": exp["budget"].get("currency", "USD")})
        if bench:
            spec["benchmarks"] = bench
    return spec


def to_messages(exp: Dict[str, Any]) -> List[str]:
    """message / offer / positioning / naming / price -> survey messages (split test)."""
    msgs = []
    for v in exp["variants"]:
        text = _vtext(v)
        if exp["type"] == "price":
            price = v.get("price") if isinstance(v, dict) else v
            text = f"{exp['extra'].get('offer') or 'The offer'} at {price}" + (f": {v.get('text')}" if isinstance(v, dict) and v.get("text") else "")
        elif exp["type"] == "naming":
            text = f"The product is called \"{text}\"" + (f". {v.get('tagline')}" if isinstance(v, dict) and v.get("tagline") else "")
        msgs.append(text)
    return msgs


def to_events(exp: Dict[str, Any], brand: str) -> Dict[str, Any]:
    """launch / creator_post -> posts + scheduled events."""
    posts, events = [], []
    for i, v in enumerate(exp["variants"]):
        d = v if isinstance(v, dict) else {"content": str(v)}
        agent = d.get("agent") or (exp["extra"].get("creator") if exp["type"] == "creator_post" else brand) or brand
        row = {"agent": agent, "platform": d.get("platform") or "both", "content": str(d.get("content") or d.get("text") or ""), "label": _vid(v, i)}
        rnd = d.get("round")
        if rnd is None or int(rnd) == 0:
            posts.append(row)
        else:
            events.append({**row, "round": int(rnd)})
    if exp["type"] == "launch" and not events and not posts:
        raise ValueError("a launch test needs variants with content (and optional round)")
    return {"posts": posts, "events": events}


def to_emails(exp: Dict[str, Any]) -> Dict[str, Any]:
    emails = []
    for i, v in enumerate(exp["variants"]):
        d = dict(v) if isinstance(v, dict) else {"subject": str(v)}
        d.setdefault("id", _vid(v, i))
        if d.get("text") and not (d.get("subject") or d.get("body")):
            d["subject"] = str(d["text"])[:90]
            d["body"] = str(d["text"])
        d.setdefault("from_name", exp["extra"].get("brand") or "The brand")
        d.setdefault("segments", exp["audience"].get("segments") or [])
        d.setdefault("countries", exp["audience"].get("countries") or [])
        emails.append(d)
    out = {"emails": emails}
    for k in ("list_size", "benchmarks", "familiarity"):
        if exp["extra"].get(k) is not None:
            out[k] = exp["extra"][k]
    return out


def to_pitches(exp: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for i, v in enumerate(exp["variants"]):
        d = v if isinstance(v, dict) else {"script": str(v)}
        out.append({"id": _vid(v, i), "script": str(d.get("script") or d.get("text") or ""), "rebuttals": d.get("rebuttals") or exp["extra"].get("rebuttals"),
                    "channel": d.get("channel") or exp["extra"].get("channel") or "message"})
    return out


# --------------------------------------------------------------------------
# Results -> one shape
# --------------------------------------------------------------------------

def margin(p: Optional[float], n: int) -> Optional[float]:
    """95% margin in percentage points for a rate p (0-100) on n people."""
    if p is None or not n:
        return None
    q = max(0.0, min(1.0, p / 100))
    return round(100 * 1.96 * math.sqrt(q * (1 - q) / n), 1)


def _row(vid: str, label: str, value: Optional[float], n: int, unit: str = "%", extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"id": vid, "label": label[:120], "value": value, "n": n, "margin": margin(value, n) if unit == "%" else None, "unit": unit, **(extra or {})}


def from_feed_test(exp: Dict[str, Any], ft: Dict[str, Any]) -> List[Dict[str, Any]]:
    summ = ft.get("summary") or {}
    per = summ.get("per_creative") or {}
    names = {c["id"]: c.get("name") or c.get("text", "")[:60] for c in ft.get("creatives") or []}
    metric = exp["metric"]
    rows = []
    for cid, m in per.items():
        if metric == "conversion_after_click":
            lf = m.get("landing") or {}
            val, n = lf.get("conversion_after_click"), lf.get("clicks") or 0
        else:
            val, n = m.get(metric, m.get("expected_ctr")), m.get("impressions") or 0
        rows.append(_row(cid, names.get(cid, cid), val, n, extra={"ctr": m.get("ctr"), "expected_ctr": m.get("expected_ctr"), "hide_rate": m.get("hide_rate"),
                                                                 "projection": {k: v for k, v in (m.get("projection") or {}).items() if k in ("cpl", "conversions", "roas")}}))
    return rows


def from_survey(exp: Dict[str, Any], summary_marketing: Dict[str, Any], messages: List[str]) -> List[Dict[str, Any]]:
    rows = []
    for m in summary_marketing.get("messages_ranked") or []:
        key = str(m.get("key") or "")
        idx = int(key.lstrip("#")) - 1 if key.lstrip("#").isdigit() else None
        vid = _vid(exp["variants"][idx], idx) if idx is not None and idx < len(exp["variants"]) else key
        val = m.get(exp["metric"]) if m.get(exp["metric"]) is not None else m.get("convert_yes")
        rows.append(_row(vid, messages[idx] if idx is not None and idx < len(messages) else str(m.get("label") or key), val, int(m.get("votes") or m.get("n") or 0),
                         extra={"convert_maybe": m.get("convert_maybe"), "reaction": m.get("reaction")}))
    return rows


def from_feed_story(exp: Dict[str, Any], story: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    labels = {str(_vtext(v))[:60]: _vid(v, i) for i, v in enumerate(exp["variants"])}
    for b in story.get("brand_posts") or []:
        content = str(b.get("content") or "")[:60]
        vid = labels.get(content) or f"{b.get('platform')} r{b.get('round')}"
        eng = (b.get("likes") or 0) + 2 * len(b.get("comments") or []) + 2 * len(b.get("quotes") or []) + (b.get("reposts") or 0)
        rs = b.get("reply_sentiment") or {}
        rows.append(_row(f"{vid}@{b.get('platform')}", content, eng, b.get("reach_proxy") or 0, unit="engagement",
                         extra={"platform": b.get("platform"), "round": b.get("round"), "likes": b.get("likes"), "comments": len(b.get("comments") or []),
                                "quotes": len(b.get("quotes") or []), "positive_replies": rs.get("pos"), "negative_replies": rs.get("neg")}))
    return rows


def from_pitch(vid: str, label: str, p: Dict[str, Any]) -> Dict[str, Any]:
    after = p.get("verdict_after") or {}
    return _row(vid, label, p.get("pitch_score"), int(p.get("answered") or 0), unit="score",
                extra={"yes_pct": after.get("yes"), "maybe_pct": after.get("maybe"), "hot_leads": len(p.get("hot_leads") or []),
                       "top_objection": (p.get("objections") or [{}])[0].get("type")})


def from_email(exp: Dict[str, Any], et: Dict[str, Any]) -> List[Dict[str, Any]]:
    summ = et.get("summary") or {}
    subj = {e["id"]: e.get("subject") for e in et.get("emails") or []}
    rows = []
    for eid, m in (summ.get("per_email") or {}).items():
        val = m.get(exp["metric"]) if m.get(exp["metric"]) is not None else m.get("click_rate")
        rows.append(_row(eid, subj.get(eid) or eid, val, int(m.get("sent") or 0),
                         extra={"open_rate": m.get("open_rate"), "click_rate": m.get("click_rate"), "unsubscribe_rate": m.get("unsubscribe_rate"), "warnings": m.get("warnings")}))
    return rows


def conclude(exp: Dict[str, Any], rows: List[Dict[str, Any]], files: Dict[str, str]) -> Dict[str, Any]:
    ranked = sorted([r for r in rows if r.get("value") is not None], key=lambda r: -float(r["value"]))
    winner = ranked[0] if ranked else None
    runner = ranked[1] if len(ranked) > 1 else None
    lift = None
    clear = False
    if winner and runner:
        lift = round(float(winner["value"]) - float(runner["value"]), 2)
        clear = (winner.get("margin") is not None and runner.get("margin") is not None
                 and lift > (winner["margin"] + runner["margin"]) / 2)
    how = {
        "ad": "expected CTR = the mean stated click chance among people who noticed the ad; compare ads on the same platform",
        "channel_mix": "the same ad on each platform; expected CTR tells you where it earns attention, the projection what a click costs",
        "landing": "conversion after click under each landing page; low click counts make this a direction only",
        "message": "share who would convert after seeing one message (true split: each person saw one)",
        "offer": "share who would convert for each offer wording", "positioning": "share who would convert for each positioning line",
        "naming": "share who would convert for each name", "price": "share who would convert at each price point (stated; price answers run optimistic)",
        "launch": "engagement = likes + 2 x comments + 2 x quotes + reposts on each brand post inside the simulation",
        "creator_post": "same as launch, posted by the creator or community account", "pitch": "pitch score 0-100 after rebuttals (yes = 1, maybe = 0.5)",
        "email": "click rate per email among the people it was sent to; opens are decided by the attention gate", "conjoint": "share of choice",
    }.get(exp["type"], "")
    return {"type": exp["type"], "name": exp["name"], "metric": exp["metric"],
            "audience": exp.get("audience") or {}, "exposure_context": exp.get("exposure_context"),
            "next_real_world_test": exp.get("next_real_world_test"), "interpretation": "exploratory simulation",
            "variants": rows, "ranked": [r["id"] for r in ranked],
            "winner": winner["id"] if winner else None, "runner_up": runner["id"] if runner else None, "lift": lift, "clear_winner": clear,
            "unit": (winner or {}).get("unit", "%"), "how_to_read": how, "files": files,
            "verdict": (f"{winner['id']} leads by {lift} {('points' if (winner or {}).get('unit', '%') == '%' else '')} ({'clear' if clear else 'within the margin: treat as a tie'})"
                        if winner and runner else (f"only one variant measured: {winner['id']}" if winner else "no measurable result"))}


# --------------------------------------------------------------------------
# Dispatcher
# --------------------------------------------------------------------------

def run(c, exp: Dict[str, Any], simulation_id: str, run_dir: str, log: Callable[[str], None], engines: Dict[str, Callable[..., Any]],
        brand: str = "") -> Dict[str, Any]:
    """engines: {"feedtest", "survey", "events", "start", "pitch", "emailtest", "collect", "load_bundle"} from mirofish.py."""
    os.makedirs(run_dir, exist_ok=True)
    t = exp["type"]
    files: Dict[str, str] = {}
    rows: List[Dict[str, Any]] = []
    if t in ("ad", "channel_mix", "landing"):
        if t == "landing":
            variants = exp["variants"] or [exp["extra"].get("landing") or {}]
            base_creative = exp["extra"].get("creative") or {"id": "ad", "text": exp["extra"].get("text") or "", "platform": exp["extra"].get("platform") or "facebook"}
            for i, lp in enumerate(variants):
                lp = lp if isinstance(lp, dict) else {}
                vid = _vid(lp, i)
                spec = to_creatives({**exp, "variants": [dict(base_creative, id=f"{base_creative.get('id') or 'ad'}_{vid}")], "extra": {**exp["extra"], "landing": lp}})
                sub = os.path.join(run_dir, f"landing_{vid}")
                os.makedirs(sub, exist_ok=True)
                log(f"test: landing variant {vid}")
                engines["feedtest"](c, simulation_id, json.dumps(spec), sub, log, seeds=exp["seeds"])
                ft = _read(os.path.join(sub, "feed_test.json"))
                files[vid] = os.path.join(sub, "feed_test.json")
                for r in from_feed_test({**exp, "metric": "conversion_after_click"}, ft):
                    r["id"] = vid
                    r["label"] = str(lp.get("name") or lp.get("shows") or vid)[:120]
                    rows.append(r)
        else:
            spec = to_creatives(exp)
            engines["feedtest"](c, simulation_id, json.dumps(spec), run_dir, log, seeds=exp["seeds"])
            ft = _read(os.path.join(run_dir, "feed_test.json"))
            files["feed_test"] = os.path.join(run_dir, "feed_test.json")
            rows = from_feed_test(exp, ft)
    elif t in ("message", "offer", "positioning", "naming", "price", "search_content", "organic_content", "referral"):
        msgs = to_messages(exp)
        engines["survey"](c, simulation_id, run_dir, exp["extra"].get("offer") or "", exp["extra"].get("goal") or "", msgs, True,
                          exp["extra"].get("currency") if t == "price" else None)
        engines["collect"](c, run_dir, simulation_id=simulation_id)
        bundle = engines["load_bundle"](run_dir)
        import marketing  # local import: the analysis lives in the CLI package
        mk = marketing.analyze(bundle)
        files["survey"] = os.path.join(run_dir, "survey.json")
        rows = from_survey(exp, mk, msgs)
    elif t in ("launch", "creator_post"):
        ev = to_events(exp, brand or "Brand")
        engines["events"](c, simulation_id, ev["posts"], ev["events"])
        engines["start"](c, simulation_id, max_rounds=exp["rounds"] or 6)
        engines["collect"](c, run_dir, simulation_id=simulation_id)
        story = _read(os.path.join(run_dir, "feed_story.json"))
        files["feed_story"] = os.path.join(run_dir, "feed_story.json")
        rows = from_feed_story(exp, story)
    elif t in ("pitch", "sales_outreach", "sales_followup"):
        for p in to_pitches(exp):
            sub = os.path.join(run_dir, f"pitch_{p['id']}")
            os.makedirs(sub, exist_ok=True)
            res = engines["pitch"](c, simulation_id, sub, log, p["script"], p["rebuttals"], brand, p["channel"])
            pj = _read(os.path.join(sub, "pitch.json"))
            files[p["id"]] = os.path.join(sub, "pitch.json")
            rows.append(from_pitch(p["id"], p["script"][:80], pj))
    elif t in ("email", "nurture", "retention"):
        engines["emailtest"](c, simulation_id, json.dumps(to_emails(exp)), run_dir, log)
        et = _read(os.path.join(run_dir, "email_test.json"))
        files["email_test"] = os.path.join(run_dir, "email_test.json")
        rows = from_email(exp, et)
    elif t == "conjoint":
        raise ValueError("conjoint tests are not available yet")
    result = conclude(exp, rows, files)
    with open(os.path.join(run_dir, "experiment_result.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return result


def _read(path: str) -> Dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}
