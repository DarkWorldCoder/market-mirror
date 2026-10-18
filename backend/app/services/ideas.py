"""Test ideas: read what real ads (an export, or rows pulled from a connected ad-account tool) and previous
simulations showed, and propose the next tests to run, each as a MarketMirror config fragment.

Every idea cites evidence by signal id, so the numbers in the output are the numbers in the input. One Claude
call; a deterministic fallback when the model returns nothing usable.
"""

import json
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional

IDEA_TYPES = ["ad", "message", "price", "audience", "landing", "launch", "pitch", "channel", "offer"]

# column aliases for raw rows (Meta/Google exports or rows an agent fetched from an ads API)
COLS = {
    "ad": ["ad", "ad_name", "ad name", "name", "creative", "creative_name", "headline"],
    "ad_set": ["ad_set", "ad set", "adset", "ad_set_name", "ad set name", "adset_name", "ad group", "ad_group_name"],
    "campaign": ["campaign", "campaign_name", "campaign name"],
    "platform": ["platform", "publisher_platform", "publisher platform", "network", "channel"],
    "country": ["country", "region", "geo"],
    "age": ["age", "age_range"],
    "gender": ["gender"],
    "spend": ["spend", "amount_spent", "amount spent", "amount spent (usd)", "cost", "amount_spent_usd"],
    "impressions": ["impressions", "impr", "impr."],
    "clicks": ["link_clicks", "link clicks", "clicks", "clicks (all)", "outbound_clicks"],
    "conversions": ["conversions", "results", "leads", "purchases", "sign-ups", "signups", "trials", "conv."],
}


def _num(v: Any) -> float:
    if v is None or isinstance(v, bool):
        return 0.0
    if isinstance(v, dict):
        v = v.get("value")
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[^\d.\-]", "", str(v).replace(",", ""))
    try:
        return float(s) if s not in ("", "-", ".") else 0.0
    except ValueError:
        return 0.0


def canon_row(row: Dict[str, Any]) -> Dict[str, Any]:
    low = {str(k).strip().lower(): v for k, v in row.items()}
    out: Dict[str, Any] = {}
    for key, names in COLS.items():
        for n in names:
            if n in low and low[n] not in (None, ""):
                out[key] = low[n]
                break
    for k in ("spend", "impressions", "clicks", "conversions"):
        out[k] = _num(out.get(k))
    for k in ("ad", "ad_set", "campaign", "platform", "country", "age", "gender"):
        if k in out:
            out[k] = str(out[k]).strip()[:120]
    return out


def _agg(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    s = {k: sum(r.get(k, 0.0) for r in rows) for k in ("spend", "impressions", "clicks", "conversions")}
    s["ctr"] = round(100 * s["clicks"] / s["impressions"], 2) if s["impressions"] else None
    s["cpc"] = round(s["spend"] / s["clicks"], 3) if s["clicks"] else None
    s["cpa"] = round(s["spend"] / s["conversions"], 2) if s["conversions"] else None
    s["conv_rate"] = round(100 * s["conversions"] / s["clicks"], 2) if s["clicks"] else None
    return s


def _fmt(v: Any, unit: str = "") -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return f"{v}{unit}"


def build_evidence(ads: List[Dict[str, Any]], ads_summary: Dict[str, Any], run_summary: Dict[str, Any],
                   brief: str = "") -> Dict[str, Any]:
    """-> {"signals": [{"id": "S1", "source": "ads|run", "text": "..."}], "numbers": [...], "brief": ...}"""
    signals: List[Dict[str, Any]] = []

    def add(source: str, text: str) -> None:
        signals.append({"id": f"S{len(signals) + 1}", "source": source, "text": text[:300]})

    rows = [canon_row(r) for r in ads if isinstance(r, dict)]
    rows = [r for r in rows if r["impressions"] or r["spend"] or r["clicks"]]
    if rows:
        total = _agg(rows)
        add("ads", f"Real ads overall: {len(rows)} rows, spend {_fmt(round(total['spend'], 2))}, {_fmt(total['impressions'])} impressions, "
                   f"CTR {_fmt(total['ctr'], '%')}, CPC {_fmt(total['cpc'])}, {_fmt(total['conversions'])} conversions, CPA {_fmt(total['cpa'])}.")
        for dim, label in (("ad", "Ad"), ("ad_set", "Ad set"), ("campaign", "Campaign"), ("country", "Country"), ("platform", "Platform"), ("age", "Age band")):
            groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
            for r in rows:
                if r.get(dim):
                    groups[r[dim]].append(r)
            if len(groups) < 2:
                continue
            table = [{"key": k, **_agg(v)} for k, v in groups.items()]
            with_imp = [t for t in table if t["impressions"] >= 200]
            if with_imp:
                best = max(with_imp, key=lambda t: t["ctr"] or 0)
                worst = min(with_imp, key=lambda t: t["ctr"] or 0)
                if best is not worst:
                    add("ads", f"{label} with the best CTR: '{best['key']}' at {_fmt(best['ctr'], '%')} ({_fmt(best['impressions'])} impressions); "
                               f"worst: '{worst['key']}' at {_fmt(worst['ctr'], '%')}.")
            with_conv = [t for t in table if t["conversions"]]
            if with_conv:
                cheap = min(with_conv, key=lambda t: t["cpa"])
                add("ads", f"{label} with the cheapest conversions: '{cheap['key']}' at CPA {_fmt(cheap['cpa'])} "
                           f"({_fmt(cheap['conversions'])} conversions from spend {_fmt(round(cheap['spend'], 2))}).")
            burners = [t for t in table if t["spend"] >= 50 and not t["conversions"]]
            for t in sorted(burners, key=lambda t: -t["spend"])[:2]:
                add("ads", f"{label} '{t['key']}' spent {_fmt(round(t['spend'], 2))} with {_fmt(t['clicks'])} clicks and no conversions.")
    elif ads_summary:
        tot = ads_summary.get("total") or {}
        if tot:
            add("ads", f"Real ads overall: spend {_fmt(tot.get('spend'))}, CTR {_fmt(tot.get('ctr'), '%')}, CPC {_fmt(tot.get('cpc'))}, "
                       f"{_fmt(tot.get('conversions'))} conversions, CPA {_fmt(tot.get('cpa'))}.")
        for dim, rows_ in (ads_summary.get("tables") or {}).items():
            rows_ = [r for r in rows_ if isinstance(r, dict)]
            if len(rows_) >= 2:
                best = rows_[0]
                add("ads", f"Best {dim} by conversions: '{best.get('key')}' with {_fmt(best.get('conversions'))} conversions at CPA "
                           f"{_fmt(best.get('cpa'))}, CTR {_fmt(best.get('ctr'), '%')}; worst: '{rows_[-1].get('key')}' "
                           f"(CTR {_fmt(rows_[-1].get('ctr'), '%')}, CPA {_fmt(rows_[-1].get('cpa'))}).")

    rs = run_summary or {}
    dec = rs.get("decision") or {}
    if dec.get("decision"):
        add("run", f"Simulation decision: {dec['decision']} ({dec.get('confidence', '?')} confidence). {dec.get('summary') or ''}")
        for fx in (dec.get("fixes") or [])[:3]:
            add("run", f"Simulation says fix first: {fx}")
    mk = rs.get("marketing") or {}
    for v in (mk.get("verdicts") or [])[:4]:
        add("run", f"Survey verdict: {v}")
    for o in (mk.get("objections") or [])[:4]:
        add("run", f"Objection '{o.get('label')}' raised by {_fmt(o.get('share'), '%')} of simulated people ({_fmt(o.get('count'))}).")
    segs = [s for s in (mk.get("by_segment") or []) if isinstance(s, dict)]
    if segs:
        best = max(segs, key=lambda s: (s.get("convert_yes") or 0) + 0.5 * (s.get("convert_maybe") or 0))
        worst = min(segs, key=lambda s: (s.get("convert_yes") or 0) + 0.5 * (s.get("convert_maybe") or 0))
        add("run", f"Most willing simulated audience: '{best.get('key')}' ({_fmt(best.get('convert_yes'), '%')} yes, "
                   f"{_fmt(best.get('convert_maybe'), '%')} maybe, n={_fmt(best.get('n'))}); least: '{worst.get('key')}' "
                   f"({_fmt(worst.get('convert_yes'), '%')} yes, {_fmt(worst.get('convert_maybe'), '%')} maybe).")
    for m in (mk.get("messages_ranked") or [])[:2]:
        add("run", f"Message '{m.get('label')}' ranked {_fmt(m.get('share'), '%')} of votes, {_fmt(m.get('convert_maybe'), '%')} maybe.")
    pr = mk.get("pricing") or {}
    if pr.get("optimal") is not None:
        add("run", f"Price test: acceptable range {_fmt(pr.get('acceptable_low'))} to {_fmt(pr.get('acceptable_high'))}, optimal {_fmt(pr.get('optimal'))}.")
    ft = rs.get("feed_test") or {}
    for cid, m in list((ft.get("per_creative") or {}).items())[:4]:
        add("run", f"Feed test creative '{cid}': expected CTR {_fmt(m.get('expected_ctr'), '%')}, hide rate {_fmt(m.get('hide_rate'), '%')}"
                   + (f", projected CPL {_fmt((m.get('projection') or {}).get('cpl'))}" if m.get("projection") else "") + ".")
    numbers = sorted({n for s in signals for n in re.findall(r"\d+(?:\.\d+)?", s["text"])})
    return {"signals": signals, "numbers": numbers, "brief": brief[:3000],
            "sources": sorted({s["source"] for s in signals})}


SYSTEM = ("You are a performance-marketing and sales test planner. You turn evidence from real ad accounts and "
          "simulated market tests into a short list of concrete, cheap experiments. Plain words. No hype. "
          "Every idea must cite evidence ids; invent no numbers.")

HOW_TO = {
    "ad": {"tool": "feedtest", "config": {"creatives": [{"id": "new_1", "platform": "instagram", "text": "<caption>", "segments": ["<audience>"]}]}},
    "message": {"tool": "survey", "config": {"messages": ["<message A>", "<message B>"], "split": True}},
    "price": {"tool": "survey", "config": {"pricing": "USD", "offer": "<offer with the price to test>"}},
    "audience": {"tool": "market-test", "config": {"personas": {"segments": [{"label": "<audience>", "count": 20, "country": "<country>"}]}}},
    "landing": {"tool": "feedtest", "config": {"landing": {"load_seconds": 2, "form_fields": 3, "asks_card": False}}},
    "launch": {"tool": "market-test", "config": {"events": [{"round": 1, "agent": "<brand>", "content": "<teaser>"}], "rounds": 6}},
    "pitch": {"tool": "pitch", "config": {"script": "<pitch>", "rebuttals": {"price": "<answer>", "*": "<generic answer>"}}},
    "channel": {"tool": "feedtest", "config": {"creatives": [{"id": "same_ad_new_channel", "platform": "<platform>", "text": "<caption>"}]}},
    "offer": {"tool": "survey", "config": {"offer": "<new offer>", "goal": "<action>"}},
}


def _prompt(evidence: Dict[str, Any], brand: str, n: int) -> str:
    sig = "\n".join(f"{s['id']} [{s['source']}]: {s['text']}" for s in evidence["signals"])
    return (
        f"Brand: {brand or 'the brand'}\n" + (f"Brief: {evidence['brief']}\n" if evidence.get("brief") else "")
        + f"\nEVIDENCE (cite by id):\n{sig}\n\n"
        f"Propose {n} test ideas, most valuable first. Mix types: {', '.join(IDEA_TYPES)}. Each idea must follow "
        "from specific evidence ids, be runnable within a week on a small budget, and say exactly what to make and "
        "what number decides it. Do not repeat the evidence as an idea; propose the next step it implies "
        "(e.g. a burner ad -> test a new angle for that audience; a trust objection -> test proof-led creative or a "
        "no-card trial; a best country -> scale there and test the second-best message).\n"
        'Return JSON only: {"ideas": [{"title": "short", "type": "ad|message|price|audience|landing|launch|pitch|channel|offer", '
        '"hypothesis": "If we ..., then ... because ...", "evidence_ids": ["S1"], "audience": "...", "platform": "...", '
        '"what_to_make": "the creative/message/price/pitch to produce, concrete", "budget": "e.g. 150 USD", "duration": "e.g. 5 days", '
        '"metric": "the one number", "success_looks_like": "threshold in plain words", "priority": "high|medium|low", '
        '"simulate_first": true}]}'
    )


def _clean(idea: Dict[str, Any], by_id: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(idea, dict) or not idea.get("title"):
        return None
    t = str(idea.get("type") or "ad").lower().strip()
    if t not in IDEA_TYPES:
        t = "ad"
    ids = [str(i).strip().upper() for i in (idea.get("evidence_ids") or []) if str(i).strip().upper() in by_id]
    if not ids:
        return None                                   # an idea without evidence is a guess; drop it
    pr = str(idea.get("priority") or "medium").lower()
    return {"title": str(idea["title"])[:120], "type": t, "hypothesis": str(idea.get("hypothesis") or "")[:400],
            "evidence_ids": ids[:5], "evidence": [by_id[i]["text"] for i in ids[:5]],
            "audience": str(idea.get("audience") or "")[:120], "platform": str(idea.get("platform") or "")[:60],
            "what_to_make": str(idea.get("what_to_make") or "")[:600], "budget": str(idea.get("budget") or "")[:40],
            "duration": str(idea.get("duration") or "")[:40], "metric": str(idea.get("metric") or "")[:120],
            "success_looks_like": str(idea.get("success_looks_like") or "")[:200],
            "priority": pr if pr in ("high", "medium", "low") else "medium",
            "simulate_first": bool(idea.get("simulate_first", True)), "how_to_test": HOW_TO[t]}


def fallback_ideas(evidence: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for s in evidence["signals"]:
        txt = s["text"].lower()
        if "no conversions" in txt:
            out.append({"title": "New angle for the ad that burned budget", "type": "ad", "evidence_ids": [s["id"]],
                        "hypothesis": "If the burner ad gets a proof-led angle for the same audience, cost per conversion becomes finite.",
                        "what_to_make": "two new captions (proof, price) for the same audience", "metric": "cost per conversion", "priority": "high"})
        elif "best ctr" in txt:
            out.append({"title": "Scale the best-CTR creative to a second audience", "type": "audience", "evidence_ids": [s["id"]],
                        "hypothesis": "If the best creative runs for the next-best audience, CTR holds within 30%.",
                        "what_to_make": "same creative, new audience", "metric": "CTR", "priority": "medium"})
        elif "objection" in txt:
            out.append({"title": "Creative that answers the top objection", "type": "message", "evidence_ids": [s["id"]],
                        "hypothesis": "If the message answers the top objection up front, 'maybe' moves toward 'yes'.",
                        "what_to_make": "two messages: one answering the objection, one current", "metric": "would_convert yes share", "priority": "high"})
        elif "price test" in txt:
            out.append({"title": "Confirm the optimal price with a split", "type": "price", "evidence_ids": [s["id"]],
                        "hypothesis": "If the offer shows the optimal price, intent is higher than at the current price.",
                        "what_to_make": "same offer at two prices", "metric": "purchase intent", "priority": "medium"})
        elif "most willing" in txt:
            out.append({"title": "First real budget on the most willing audience", "type": "ad", "evidence_ids": [s["id"]],
                        "hypothesis": "If the first real spend targets the most willing simulated audience, CPL beats the account average.",
                        "what_to_make": "the winning creative for that audience", "metric": "cost per lead", "priority": "high"})
    return out[:8]


def render_markdown(out: Dict[str, Any], brand: str = "") -> str:
    lines = [f"# {brand or 'Brand'}: next tests to run", "",
             f"{len(out['ideas'])} ideas from {len(out['evidence']['signals'])} pieces of evidence "
             f"({', '.join(out['evidence'].get('sources') or [])}). Each idea cites the evidence it comes from.", ""]
    for i, idea in enumerate(out["ideas"], 1):
        lines += [f"## {i}. {idea['title']}  ({idea['type']}, {idea['priority']} priority)", "",
                  f"**Hypothesis.** {idea['hypothesis']}", "",
                  f"**Make.** {idea['what_to_make']}", "",
                  f"**Where.** {idea['audience'] or '-'} on {idea['platform'] or '-'} · {idea['budget'] or 'small budget'} · {idea['duration'] or 'a few days'}", "",
                  f"**Decide by.** {idea['metric'] or '-'}: {idea['success_looks_like'] or '-'}", "",
                  "**Evidence.**"] + [f"- {e}" for e in idea["evidence"]] + [
                  "", f"**Simulate first.** `{idea['how_to_test']['tool']}` with "
                      f"`{json.dumps(idea['how_to_test']['config'], ensure_ascii=False)}`", ""]
    lines += ["## Evidence list", ""] + [f"- {s['id']} ({s['source']}): {s['text']}" for s in out["evidence"]["signals"]]
    return "\n".join(lines)


def generate(client, model: str, evidence: Dict[str, Any], brand: str = "", n: int = 8) -> Dict[str, Any]:
    from ..utils.openai_chat_compat import create_chat_completion, extract_chat_completion_text
    from .persona_planner import parse_json_block
    n = max(3, min(int(n or 8), 12))
    by_id = {s["id"]: s for s in evidence["signals"]}
    usage = {"input_tokens": 0, "output_tokens": 0}
    ideas: List[Dict[str, Any]] = []
    method = "llm"
    try:
        resp = create_chat_completion(client, model=model, temperature=0.7, max_tokens=6000,
                                      messages=[{"role": "system", "content": SYSTEM},
                                                {"role": "user", "content": _prompt(evidence, brand, n)}])
        u = getattr(resp, "usage", None)
        if u:
            usage = {"input_tokens": getattr(u, "prompt_tokens", 0) or 0, "output_tokens": getattr(u, "completion_tokens", 0) or 0}
        parsed = parse_json_block(extract_chat_completion_text(resp))
        rows = parsed.get("ideas") if isinstance(parsed, dict) else parsed
        ideas = [x for x in (_clean(r, by_id) for r in (rows or [])) if x][:n]
    except Exception:  # noqa: BLE001 - fall back to data-driven ideas
        ideas = []
    if not ideas:
        method = "fallback"
        ideas = [x for x in (_clean(r, by_id) for r in fallback_ideas(evidence)) if x]
    out = {"brand": brand, "method": method, "usage": usage, "ideas": ideas, "evidence": evidence}
    out["markdown"] = render_markdown(out, brand)
    return out
