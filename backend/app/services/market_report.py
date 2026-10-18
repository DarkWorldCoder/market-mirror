"""
MarketMirror plain-language report.

Reads everything a run produced (decision, feed test, survey, analyst panel, social feed story, personas,
benchmarks), compacts it into a fact sheet, and asks Claude once for a report that a non-expert can read:
executive summary, what we tested, who we simulated, what happened on social, ad results, survey results,
objections with answer lines, pricing, sales notes (objection handling, ICP fit, lead scores), a concrete
action plan, and limits. The Markdown is rendered deterministically from the JSON so headings and numbers are
stable; if the model's JSON cannot be parsed, a data-only fallback report is produced instead.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from ..utils.logger import get_logger
from ..utils.openai_chat_compat import create_chat_completion, extract_chat_completion_text
from .persona_planner import parse_json_block

logger = get_logger('mirofish.market_report')

SYSTEM = (
    "You write market-test reports for business owners and marketers who are not researchers. Plain words, short "
    "sentences, no jargon without a two-word explanation. Every number you use must appear in the FACTS you are given; "
    "never invent numbers, names or quotes. The people in the facts are simulated personas, so write 'simulated people' "
    "and treat all rates as directions, not measurements. Return only valid JSON."
)

SECTION_ORDER = [
    ("executive_summary", "Executive summary"), ("what_we_tested", "What we tested"),
    ("who_we_simulated", "Who we simulated"), ("social", "What happened on social media"),
    ("ad_results", "Ad results"), ("survey_results", "Survey results"), ("objections", "Objections and how to answer them"),
    ("pricing", "Pricing"), ("sales_notes", "Sales notes"), ("action_plan", "Action plan"), ("limits", "Limits and confidence"),
]


# --------------------------------------------------------------------------
# Fact sheet
# --------------------------------------------------------------------------

def _n(v: Any, nd: int = 1) -> Any:
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, float):
        return round(v, nd)
    return v


def _top(rows: List[Dict[str, Any]], n: int, keys: List[str]) -> List[Dict[str, Any]]:
    return [{k: _n(r.get(k)) for k in keys if r.get(k) is not None} for r in (rows or [])[:n]]


def lead_score(seg: Dict[str, Any]) -> int:
    """0-100 from the survey row of one segment: intent (SSR purchase mean or convert shares), trust, click."""
    ssr = (seg.get("ssr") or {}).get("purchase") or {}
    intent = ssr.get("mean")
    if intent is not None:
        intent_pts = (float(intent) - 1) / 4 * 60          # 1..5 -> 0..60
    else:
        intent_pts = ((seg.get("convert_yes") or 0) + 0.4 * (seg.get("convert_maybe") or 0)) / 100 * 60
    trust = seg.get("trust")
    trust_pts = (float(trust) / 10 * 25) if trust is not None else 10
    click_pts = (seg.get("click_yes") or 0) / 100 * 15
    return int(round(max(0, min(100, intent_pts + trust_pts + click_pts))))


def compact_material(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """A fact sheet small enough for one call (~8-10k tokens)."""
    summary = bundle.get("summary") or {}
    mk = summary.get("marketing") or {}
    decision = summary.get("decision") or {}
    project = bundle.get("project") or {}
    cfg = bundle.get("config") or {}
    index = [r for r in cfg.get("persona_index") or [] if r.get("kind") == "persona"]
    segments: Dict[str, Dict[str, Any]] = {}
    for r in index:
        s = segments.setdefault(r.get("segment") or "Unassigned", {"people": 0, "countries": set(), "examples": []})
        s["people"] += 1
        if r.get("country"):
            s["countries"].add(r["country"])
        if len(s["examples"]) < 2:
            s["examples"].append({"name": r.get("name"), "age": r.get("age"), "city": r.get("city"),
                                  "occupation": r.get("occupation"), "summary": (r.get("interview_summary") or "")[:240]})
    who = [{"segment": k, "people": v["people"], "countries": sorted(v["countries"]), "examples": v["examples"]}
           for k, v in segments.items()]

    ft = (bundle.get("feed_test") or {})
    fts = ft.get("summary") or {}
    creatives = {c["id"]: c for c in ft.get("creatives") or []}
    ads = []
    for cid in fts.get("ranked") or list(fts.get("per_creative") or {}):
        m = (fts.get("per_creative") or {}).get(cid) or {}
        cr = creatives.get(cid, {})
        lf, pr = m.get("landing") or {}, m.get("projection") or {}
        ads.append({"id": cid, "name": cr.get("name"), "platform": cr.get("platform"), "text": (cr.get("text") or "")[:160],
                    "shown_to": m.get("impressions"), "noticed_pct": _n(m.get("noticed")), "thumb_stop_pct": _n(m.get("thumb_stop")),
                    "ctr_pct": _n(m.get("ctr")), "expected_ctr_pct": _n(m.get("expected_ctr")), "hide_pct": _n(m.get("hide_rate")),
                    "comments": m.get("comments"), "sample_comments": [c.get("text") for c in (m.get("comments_list") or [])[:3]],
                    "landing": {k: lf.get(k) for k in ("clicks", "page_loaded", "form_started", "converted", "drop_reasons") if lf.get(k) is not None},
                    "projection": {k: _n(pr.get(k), 2) for k in ("budget", "currency", "clicks", "cpc", "conversions", "cpl",
                                                                    "cost_per_conversion", "cac", "roas", "roi_pct", "break_even_cpl") if pr.get(k) is not None}})
    seeds = ft.get("multi_seed") or {}

    survey = bundle.get("survey") or {}
    o = mk.get("overall") or {}
    by_seg = []
    for s in mk.get("by_segment") or []:
        row = {"segment": s.get("key"), "people": s.get("n"), "would_convert_pct": _n(s.get("convert_yes")),
               "maybe_pct": _n(s.get("convert_maybe")), "would_click_pct": _n(s.get("click_yes")),
               "interest_0_10": _n(s.get("interest")), "trust_0_10": _n(s.get("trust")),
               "top_objection": s.get("top_objection"), "lead_score": lead_score(s)}
        ssr = (s.get("ssr") or {}).get("purchase") or {}
        if ssr.get("mean") is not None:
            row["purchase_intent_1_5"] = _n(ssr.get("mean"), 2)
        by_seg.append(row)
    objections = [{"objection": x.get("label"), "share_pct": _n(x.get("share")), "count": x.get("count"),
                   "examples": [{"who": e.get("segment"), "quote": (e.get("text") or "")[:200], "would_change_mind": (e.get("fix") or "")[:160]}
                                for e in (x.get("examples") or [])[:2]]} for x in (mk.get("objections") or [])[:6]]
    messages = _top(mk.get("messages_ranked") or [], 6, ["key", "label", "votes", "share", "convert_yes", "convert_maybe", "reaction"])
    pricing = mk.get("pricing") or {}
    panel = ((bundle.get("analyst_panel") or {}).get("consensus") or {})
    fs = bundle.get("feed_story") or {}
    social = {}
    if fs:
        brand = fs.get("brand_posts") or []
        social["brand_posts"] = [{"platform": b.get("platform"), "round": b.get("round"), "content": (b.get("content") or "")[:200],
                                  "likes": b.get("likes"), "quotes": len(b.get("quotes") or []), "comments": len(b.get("comments") or []),
                                  "reply_sentiment": b.get("reply_sentiment"),
                                  "sample_replies": [(c.get("content") or "")[:160] for c in (b.get("comments") or [])[:3]]}
                                 for b in brand[:6]]
        tops = []
        for plat, data in (fs.get("platforms") or {}).items():
            for p in sorted(data.get("posts") or [], key=lambda p: -(p.get("reach_proxy") or 0))[:4]:
                a = p.get("author") or {}
                tops.append({"platform": plat, "author_segment": a.get("segment"), "country": a.get("country"), "round": p.get("round"),
                             "content": (p.get("content") or "")[:200], "likes": p.get("likes"), "comments": len(p.get("comments") or []),
                             "sample_comments": [(c.get("content") or "")[:140] for c in (p.get("comments") or [])[:2]]})
        social["top_posts"] = tops
        social["sentiment_method"] = fs.get("sentiment_method")
    return {
        "brand": _brand_name(bundle), "question": (project.get("simulation_requirement") or summary.get("simulation_requirement") or "")[:1200],
        "decision": {k: decision.get(k) for k in ("decision", "confidence", "summary", "signals", "fixes") if decision.get(k) is not None},
        "verdicts": mk.get("verdicts") or [], "who": who, "people_total": len(index),
        "offer": survey.get("offer"), "goal": survey.get("goal"), "split_test": mk.get("split_test"), "currency": survey.get("currency"),
        "survey": {"answered": mk.get("answered"), "would_convert_pct": _n(o.get("convert_yes")), "maybe_pct": _n(o.get("convert_maybe")),
                   "would_click_pct": _n(o.get("click_yes")), "interest_0_10": _n(o.get("interest")), "trust_0_10": _n(o.get("trust")),
                   "nps": o.get("nps"), "purchase_intent_1_5": _n(((o.get("ssr") or {}).get("purchase") or {}).get("mean"), 2),
                   "by_segment": by_seg, "quotes_yes": [q.get("text") for q in (mk.get("quotes_yes") or [])[:3]],
                   "quotes_no": [q.get("text") for q in (mk.get("quotes_no") or [])[:3]]},
        "objections": objections, "messages": messages,
        "pricing": {k: _n(pricing.get(k)) for k in ("acceptable_low", "acceptable_high", "optimal", "answers") if pricing.get(k) is not None},
        "pricing_by_segment": _top(pricing.get("by_segment") or [], 8, ["key", "n", "cheap", "expensive", "too_expensive"]),
        "ads": ads, "ad_seed_agreement_pct": seeds.get("winner_agreement"), "landing_page": ft.get("landing"),
        "benchmarks": _benchmarks(bundle),
        "panel": {k: panel.get(k) for k in ("analysts_ok", "consensus", "sentiment_mean", "success_probability", "confidence_mean") if panel.get(k) is not None}
        | {"verdict": (panel.get("verdict") or {}).get("winner"), "best_audience": (panel.get("best_audience") or {}).get("winner"),
           "themes": [{"theme": t.get("theme"), "analysts": t.get("analysts"), "evidence": (t.get("evidence") or [""])[0][:160]}
                      for t in (panel.get("themes") or [])[:6]]},
        "social": social, "playbook": _top(mk.get("playbook") or [], 8, ["segment", "priority", "lead_with", "preempt", "answer_with", "seed_in"]),
    }


def _brand_name(bundle: Dict[str, Any]) -> str:
    for c in (bundle.get("feed_test") or {}).get("creatives") or []:
        if c.get("page"):
            return str(c["page"])
    for r in (bundle.get("config") or {}).get("persona_index") or []:
        if r.get("kind") == "graph":
            return str(r.get("name"))
    return "the brand"


def _benchmarks(bundle: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for s in (bundle.get("feed_test") or {}).get("sessions") or []:
        break
    ft = bundle.get("feed_test") or {}
    for cid, m in ((ft.get("summary") or {}).get("per_creative") or {}).items():
        pr = m.get("projection") or {}
        if pr.get("budget"):
            out[cid] = {"budget": pr.get("budget"), "currency": pr.get("currency"), "cpm": pr.get("cpm")}
    return out


# --------------------------------------------------------------------------
# Generation
# --------------------------------------------------------------------------

SCHEMA = '''{
 "executive_summary": {"decision": "go|iterate|no-go", "headline": "one sentence a CEO would read", "bullets": ["3 bullets, each with the key fact"]},
 "what_we_tested": "2-4 sentences: the offer, the ads/messages, prices, how many simulated people, which platforms",
 "who_we_simulated": [{"segment": "...", "people": N, "where": "...", "in_short": "one sentence on how this group reacts", "example_person": "name, age, one line"}],
 "social": {"summary": "2-4 sentences on what happened in the simulated feeds", "themes": ["..."], "brand_post_notes": ["one line per brand post: what it got and how people replied"], "best_reaction": "quote", "worst_reaction": "quote"},
 "ad_results": {"summary": "2-4 sentences", "winner": "creative id and why", "table_notes": ["one line per ad"], "landing_page": "what happened after the click and what to fix"},
 "survey_results": {"summary": "2-4 sentences with the main rates and what they mean", "best_audience": "...", "weakest_audience": "...", "message_winner": "..."},
 "objections": [{"objection": "...", "who": "which segments", "share_pct": N, "quote": "...", "answer_line": "the exact line a salesperson or ad can use to answer it"}],
 "pricing": {"summary": "2-3 sentences", "recommended_price": "...", "range": "..."},
 "sales_notes": {"objection_handling": [{"when_they_say": "...", "you_say": "..."}], "icp": [{"segment": "...", "lead_score": N, "why": "...", "best_channel": "...", "first_message": "..."}], "do_not_chase": "which segments and why"},
 "action_plan": {"ads": [{"creative_id": "...", "audience": "...", "platforms": ["..."], "budget": "...", "duration": "...", "why": "..."}], "fixes": ["ordered, concrete, who does it"], "messages_to_use": ["..."], "retest": {"when": "...", "what": "...", "success_looks_like": "..."}},
 "limits": {"confidence": "low|medium|high", "caveats": ["..."], "what_would_raise_confidence": ["..."]}
}'''


def generate(client, model: str, material: Dict[str, Any], brand: Optional[str] = None) -> Dict[str, Any]:
    facts = json.dumps(material, ensure_ascii=False, default=str)
    if len(facts) > 60000:
        facts = facts[:60000] + "...(truncated)"
    prompt = (f"Write the market-test report for {brand or material.get('brand') or 'the brand'}.\n\n"
              f"FACTS (the only source of numbers, names and quotes):\n{facts}\n\n"
              "Write for a business owner. Short sentences. Explain any term in two words the first time. Where the facts "
              "give a percentage, say it as 'about X in 10 simulated people' as well as the percentage where it helps. "
              "The action plan must be concrete: which ads to which audiences on which platforms, with budgets that add "
              "up to the benchmarks' budgets when they exist, what to fix first (ordered), and when to retest.\n\n"
              f"Return JSON exactly in this shape:\n{SCHEMA}")
    usage = {}
    try:
        resp = create_chat_completion(client, model=model, temperature=0.4, max_tokens=7000,
                                      messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}])
        text = extract_chat_completion_text(resp)
        u = getattr(resp, "usage", None)
        if u is not None:
            usage = {"input_tokens": getattr(u, "prompt_tokens", None), "output_tokens": getattr(u, "completion_tokens", None)}
        data = parse_json_block(text)
        if not isinstance(data, dict) or "executive_summary" not in data:
            raise ValueError("report JSON missing executive_summary")
        sections = clean_sections(data, material)
        method = "llm"
    except Exception as e:  # noqa: BLE001 - fall back to a data-only report
        logger.warning(f"market report generation failed, using data-only fallback: {e}")
        sections, method = fallback_sections(material), "fallback"
    md = render_markdown(sections, material)
    return {"sections": sections, "action_plan": sections.get("action_plan") or {}, "markdown": md,
            "method": method, "usage": usage, "brand": brand or material.get("brand")}


_NUM = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(?![\w.])")


def _fact_numbers(material: Dict[str, Any]) -> set:
    found = set()
    for m in _NUM.finditer(json.dumps(material, ensure_ascii=False, default=str)):
        v = m.group(1)
        found.add(v)
        try:
            f = float(v)
            found.add(str(int(round(f))))
            found.add(f"{f:.1f}".rstrip("0").rstrip("."))
        except ValueError:
            pass
    return found


def _check_numbers(text: str, allowed: set) -> str:
    """Drop sentences that quote numbers absent from the facts (keeps small counting numbers 0-12 and years)."""
    out = []
    for sent in re.split(r"(?<=[.!?])\s+", text or ""):
        nums = _NUM.findall(sent)
        bad = [n for n in nums if n not in allowed and not (n.isdigit() and (int(n) <= 12 or 1990 <= int(n) <= 2100))]
        if not bad:
            out.append(sent)
    return " ".join(out).strip()


def clean_sections(data: Dict[str, Any], material: Dict[str, Any]) -> Dict[str, Any]:
    allowed = _fact_numbers(material)

    def walk(v):
        if isinstance(v, str):
            return _check_numbers(v, allowed)
        if isinstance(v, list):
            return [walk(x) for x in v]
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        return v
    out = {k: walk(data.get(k)) for k, _ in SECTION_ORDER if data.get(k) is not None}
    ex = out.get("executive_summary") or {}
    if isinstance(ex, dict):
        ex["decision"] = str(ex.get("decision") or (material.get("decision") or {}).get("decision") or "iterate").lower()
    return out


def fallback_sections(m: Dict[str, Any]) -> Dict[str, Any]:
    d = m.get("decision") or {}
    sv = m.get("survey") or {}
    segs = sorted(sv.get("by_segment") or [], key=lambda s: -(s.get("lead_score") or 0))
    return {
        "executive_summary": {"decision": d.get("decision") or "iterate", "headline": d.get("summary") or "The test produced a direction, not a measurement.",
                              "bullets": (m.get("verdicts") or [])[:3]},
        "what_we_tested": f"Offer: {m.get('offer') or 'see question'}. Goal: {m.get('goal') or 'conversion'}. "
                          f"{m.get('people_total') or 0} simulated people, {len(m.get('ads') or [])} ads, {len(m.get('messages') or [])} messages.",
        "who_we_simulated": [{"segment": w["segment"], "people": w["people"], "where": ", ".join(w["countries"]), "in_short": "",
                              "example_person": (w["examples"][0]["name"] if w["examples"] else "")} for w in m.get("who") or []],
        "social": {"summary": "", "themes": [t["theme"] for t in (m.get("panel") or {}).get("themes") or []],
                   "brand_post_notes": [f"{b.get('platform')} round {b.get('round')}: {b.get('likes')} likes, {b.get('comments')} comments"
                                        for b in (m.get("social") or {}).get("brand_posts") or []], "best_reaction": "", "worst_reaction": ""},
        "ad_results": {"summary": "", "winner": (m.get("ads") or [{}])[0].get("id", ""), "table_notes": [], "landing_page": ""},
        "survey_results": {"summary": "", "best_audience": segs[0]["segment"] if segs else "", "weakest_audience": segs[-1]["segment"] if segs else "",
                           "message_winner": ((m.get("messages") or [{}])[0].get("label") or "")},
        "objections": [{"objection": o["objection"], "who": ", ".join(e["who"] for e in o["examples"] if e.get("who")), "share_pct": o["share_pct"],
                        "quote": (o["examples"][0]["quote"] if o["examples"] else ""), "answer_line": ""} for o in m.get("objections") or []],
        "pricing": {"summary": "", "recommended_price": str((m.get("pricing") or {}).get("optimal") or ""),
                    "range": f"{(m.get('pricing') or {}).get('acceptable_low')} to {(m.get('pricing') or {}).get('acceptable_high')}" if m.get("pricing") else ""},
        "sales_notes": {"objection_handling": [], "icp": [{"segment": s["segment"], "lead_score": s["lead_score"], "why": "", "best_channel": "", "first_message": ""} for s in segs], "do_not_chase": ""},
        "action_plan": {"ads": [], "fixes": list(d.get("fixes") or []), "messages_to_use": [], "retest": {"when": "", "what": "", "success_looks_like": ""}},
        "limits": {"confidence": d.get("confidence") or "low", "caveats": ["Simulated people, not real customers."], "what_would_raise_confidence": ["A small real-budget test."]},
    }


# --------------------------------------------------------------------------
# Markdown (deterministic)
# --------------------------------------------------------------------------

def _bullets(items: Any) -> str:
    return "\n".join(f"- {x}" for x in (items or []) if x) + ("\n" if items else "")


def render_markdown(sec: Dict[str, Any], material: Dict[str, Any]) -> str:
    brand = material.get("brand") or "the brand"
    ex = sec.get("executive_summary") or {}
    out = [f"# {brand}: market test report", "",
           f"**Decision: {str(ex.get('decision') or '').upper()}.** {ex.get('headline') or ''}", "", _bullets(ex.get("bullets"))]
    out += ["## What we tested", "", str(sec.get("what_we_tested") or ""), ""]
    who = sec.get("who_we_simulated") or []
    if who:
        out += ["## Who we simulated", "", "| Group | People | Where | In short |", "|---|---|---|---|"]
        out += [f"| {w.get('segment')} | {w.get('people')} | {w.get('where')} | {w.get('in_short') or ''} |" for w in who]
        out += [""] + [f"- Example: {w['example_person']}" for w in who if w.get("example_person")] + [""]
    so = sec.get("social") or {}
    if so:
        out += ["## What happened on social media", "", str(so.get("summary") or ""), ""]
        if so.get("themes"):
            out += ["**Themes**", "", _bullets(so.get("themes"))]
        if so.get("brand_post_notes"):
            out += ["**The brand's own posts**", "", _bullets(so.get("brand_post_notes"))]
        if so.get("best_reaction"):
            out += [f"> Best reaction: \"{so['best_reaction']}\"", ""]
        if so.get("worst_reaction"):
            out += [f"> Worst reaction: \"{so['worst_reaction']}\"", ""]
    ad = sec.get("ad_results") or {}
    if ad:
        out += ["## Ad results", "", str(ad.get("summary") or ""), ""]
        if ad.get("winner"):
            out += [f"**Winner:** {ad['winner']}", ""]
        out += [_bullets(ad.get("table_notes"))]
        if ad.get("landing_page"):
            out += [f"**After the click:** {ad['landing_page']}", ""]
    sv = sec.get("survey_results") or {}
    if sv:
        out += ["## Survey results", "", str(sv.get("summary") or ""), ""]
        out += [f"- Best audience: {sv.get('best_audience') or '–'}", f"- Weakest audience: {sv.get('weakest_audience') or '–'}",
                f"- Message that worked best: {sv.get('message_winner') or '–'}", ""]
    obj = sec.get("objections") or []
    if obj:
        out += ["## Objections and how to answer them", ""]
        for o in obj:
            share = f" ({o.get('share_pct')}% of people)" if o.get("share_pct") not in (None, "") else ""
            out += [f"**{o.get('objection')}**{share}: {o.get('who') or ''}", ""]
            if o.get("quote"):
                out += [f"> \"{o['quote']}\"", ""]
            if o.get("answer_line"):
                out += [f"Answer with: *{o['answer_line']}*", ""]
    pr = sec.get("pricing") or {}
    if pr and (pr.get("summary") or pr.get("range")):
        out += ["## Pricing", "", str(pr.get("summary") or ""), ""]
        if pr.get("recommended_price"):
            out += [f"- Recommended price: {pr['recommended_price']}"]
        if pr.get("range"):
            out += [f"- Acceptable range: {pr['range']}"]
        out += [""]
    sn = sec.get("sales_notes") or {}
    if sn:
        out += ["## Sales notes", ""]
        if sn.get("icp"):
            out += ["| Segment | Lead score | Why | Best channel | First message |", "|---|---|---|---|---|"]
            out += [f"| {i.get('segment')} | {i.get('lead_score')} | {i.get('why') or ''} | {i.get('best_channel') or ''} | {i.get('first_message') or ''} |"
                    for i in sn["icp"]] + [""]
        if sn.get("objection_handling"):
            out += ["**When they say / you say**", ""] + [f"- *{x.get('when_they_say')}* → {x.get('you_say')}" for x in sn["objection_handling"]] + [""]
        if sn.get("do_not_chase"):
            out += [f"Do not chase: {sn['do_not_chase']}", ""]
    ap = sec.get("action_plan") or {}
    if ap:
        out += ["## Action plan", ""]
        if ap.get("ads"):
            out += ["| Ad | Audience | Platforms | Budget | Duration | Why |", "|---|---|---|---|---|---|"]
            out += [f"| {a.get('creative_id')} | {a.get('audience')} | {', '.join(a.get('platforms') or [])} | {a.get('budget')} | {a.get('duration')} | {a.get('why') or ''} |"
                    for a in ap["ads"]] + [""]
        if ap.get("fixes"):
            out += ["**Fix first**", ""] + [f"{i + 1}. {f}" for i, f in enumerate(ap["fixes"])] + [""]
        if ap.get("messages_to_use"):
            out += ["**Messages to use**", "", _bullets(ap["messages_to_use"])]
        rt = ap.get("retest") or {}
        if rt.get("when") or rt.get("what"):
            out += [f"**Retest:** {rt.get('when') or ''}. {rt.get('what') or ''} Success looks like: {rt.get('success_looks_like') or ''}", ""]
    lim = sec.get("limits") or {}
    out += ["## Limits and confidence", "", f"Confidence: **{lim.get('confidence') or 'low'}**.", "", _bullets(lim.get("caveats")),
            "What would raise confidence:", "", _bullets(lim.get("what_would_raise_confidence")),
            "_All people in this report are simulated. Use it to rank options and plan a small real test, not as a measurement._", ""]
    return "\n".join(out)
