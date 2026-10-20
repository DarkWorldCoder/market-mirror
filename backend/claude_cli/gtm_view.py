"""
gtm_view.py - dashboard sections for the marketing and sales tests (backend/app/services/gtm_suite.py and
cro_and_sparring.py) and for what the simulated people thought. Every number shown comes from the people's answers,
with its count and 95% range; a section is left out when its test has not run. Stdlib only.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

try:  # stdlib only
    import ui  # type: ignore
except ImportError:  # pragma: no cover - imported as a package
    from . import ui  # type: ignore

_e = ui.esc
Section = Optional[Tuple[str, str, str]]

GTM_CSS = """
.lab-grid{display:grid;gap:14px}
.lab-card{background:var(--surface);border-radius:24px;padding:18px 20px}
.lab-card h3{margin:0 0 4px;font-size:1.05rem;font-weight:600}
.lab-meta{color:var(--muted);font-size:12px;margin:0 0 12px}
.lab-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:10px 0}
.lab-kpi{background:var(--surface-2);border-radius:16px;padding:12px 14px}
.lab-kpi b{display:block;font-size:1.45rem;font-weight:500;letter-spacing:-.03em;line-height:1.1}
.lab-kpi span{font-size:12.5px;color:var(--text-2)}.lab-kpi small{display:block;font-size:11.5px;color:var(--muted)}
.lab-quote{margin:6px 0;padding:8px 12px;border-radius:12px;background:var(--surface-2);font-size:13px;color:var(--text-2)}
.lab-quote b{color:var(--text);font-weight:600}
.lab-row{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:14px}
.lab-ad{border:1px solid var(--border);border-radius:16px;padding:12px 14px;font-size:13px;white-space:pre-wrap}
.lab-ad .h{font-weight:600;margin-bottom:4px}.lab-ad .c{margin-top:8px;font-weight:600;color:var(--text-2)}
.bar-row{display:grid;grid-template-columns:minmax(120px,32%) minmax(0,1fr) 120px;gap:10px;align-items:center;font-size:13px;margin:5px 0}
.bar-row .tr{height:10px;border-radius:999px;background:var(--surface-2);position:relative;overflow:hidden}
.bar-row .tr i{position:absolute;inset:0 auto 0 0;background:var(--text);border-radius:999px}
.bar-row .tr u{position:absolute;top:0;bottom:0;background:color-mix(in srgb,var(--text) 22%,transparent)}
.bar-row .v{text-align:right;font-variant-numeric:tabular-nums;color:var(--text-2)}
.mm-search-bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:10px 0}
.mm-search-bar input[type="search"]{flex:1 1 260px;padding:9px 14px;border-radius:var(--r-pill);border:1px solid var(--border);background:var(--surface-2);color:var(--text);font:inherit;font-size:13.5px}
.mm-search-bar select{padding:8px 12px;border-radius:var(--r-pill);border:1px solid var(--border);background:var(--surface-2);color:var(--text);font:inherit;font-size:12.5px}
.mm-concept-pills{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0 12px}
.mm-c-pill{font:inherit;font-size:12px;padding:5px 11px;border-radius:var(--r-pill);border:1px solid var(--border);background:var(--surface-2);color:var(--text-2);cursor:pointer}
.mm-c-pill[aria-pressed="true"]{background:var(--text);color:var(--surface);border-color:var(--text)}
.mm-s-item{padding:10px 14px;border-radius:14px;background:var(--surface-2);margin:6px 0;font-size:13px}
.mm-s-item .mm-s-head{display:flex;justify-content:space-between;gap:8px;margin-bottom:3px;font-size:12px;color:var(--muted)}
.mm-s-item .mm-s-title{font-weight:600;color:var(--text)}
.mm-s-item a{color:var(--text);text-decoration:underline;font-weight:500}
@media (max-width:760px){.lab-row{grid-template-columns:1fr}.bar-row{grid-template-columns:1fr 1fr;}.bar-row .tr{grid-column:1/-1;order:3}}
"""


def _w(w: Optional[Dict[str, Any]]) -> str:
    """'34% (22–47)' from a wilson dict."""
    if not w or w.get("pct") is None:
        return "–"
    rng = f" ({w['lo']:g}–{w['hi']:g})" if w.get("lo") is not None else ""
    return f"{w['pct']:g}%{rng}"


def _m(ci: Optional[Dict[str, Any]], scale: float = 1, unit: str = "") -> str:
    if not ci or ci.get("mean") is None:
        return "–"
    m = ci["mean"] * scale
    rng = f" ({ci['lo'] * scale:+.1f} to {ci['hi'] * scale:+.1f})" if ci.get("lo") is not None and scale != 1 else (
        f" ({ci['lo']:.2g}–{ci['hi']:.2g})" if ci.get("lo") is not None else "")
    return f"{m:.1f}{unit}{rng}" if scale != 1 else f"{m:.2g}{unit}{rng}"


def _meta(res: Dict[str, Any]) -> str:
    bits = [f"{res.get('answered', 0)} of {res.get('asked', 0)} simulated people answered"]
    if res.get("failed"):
        bits.append(f"{res['failed']} calls failed")
    if res.get("providers"):
        bits.append("models: " + ", ".join(f"{k} {v}" for k, v in res["providers"].items()))
    return f'<p class="lab-meta">{_e(" · ".join(bits))}</p>'


def _kpi(value: str, label: str, small: str = "") -> str:
    return f'<div class="lab-kpi"><b>{_e(value)}</b><span>{_e(label)}</span>{f"<small>{_e(small)}</small>" if small else ""}</div>'


def _bars(rows: List[Tuple[str, Optional[Dict[str, Any]]]]) -> str:
    out = []
    for label, w in rows:
        if not w or w.get("pct") is None:
            continue
        lo, hi = w.get("lo") or w["pct"], w.get("hi") or w["pct"]
        out.append(f'<div class="bar-row"><span>{_e(label)}</span><span class="tr"><u style="left:{lo:.1f}%;width:{max(0.5, hi - lo):.1f}%"></u>'
                   f'<i style="width:{w["pct"]:.1f}%"></i></span><span class="v">{_e(_w(w))}</span></div>')
    return "".join(out)


def _quotes(qs: List[str], label: str = "") -> str:
    return "".join(f'<div class="lab-quote">{f"<b>{_e(label)}</b> " if label else ""}“{_e(q)}”</div>' for q in qs if q)


def _ranked(rows: List[Dict[str, Any]], title: str, quotes: int = 2) -> str:
    if not rows:
        return ""
    body = "".join(f'<div style="margin:8px 0"><div class="bar-row"><span>{_e(str(r.get("key") or "").replace("_", " "))}'
                   f'</span><span class="tr"><i style="width:{(r.get("share") or {}).get("pct") or 0:.1f}%"></i></span>'
                   f'<span class="v">{r.get("count")} · {_e(_w(r.get("share")))}</span></div>'
                   f'{_quotes((r.get("quotes") or [])[:quotes])}</div>' for r in rows)
    return f"<h4>{_e(title)}</h4>{body}"


def _card(title: str, res: Dict[str, Any], body: str) -> str:
    return f'<div class="lab-card"><h3>{_e(title)}</h3>{_meta(res)}{body}</div>'


def _unavailable(res: Dict[str, Any]) -> Optional[str]:
    s = res.get("summary") or {}
    if s.get("available") is False:
        return f'<p class="muted">{_e(s.get("reason") or "Not run.")}</p>'
    return None


# --------------------------------------------------------------------------
# Marketing and sales lab
# --------------------------------------------------------------------------

def committee_card(res: Dict[str, Any]) -> str:
    s = res.get("summary") or {}
    o = s.get("outcomes") or {}
    body = _bars([("Buy now", o.get("buy")), ("Try first", o.get("try_first")), ("Wait", o.get("wait")), ("No", o.get("no"))])
    ppl = s.get("people_per_decision") or {}
    body += f'<p class="lab-meta">People weighing in per decision: {_e(_m(ppl))}</p>'
    body += _ranked(s.get("blockers") or [], "What blocked the decision")
    body += _ranked(s.get("roles_saying_no") or [], "Who said no", 1)
    if s.get("what_would_unblock"):
        body += "<h4>What would unblock it</h4>" + _quotes(s["what_would_unblock"][:5])
    ex = [r for r in res.get("rows") or [] if r.get("participants")][:2]
    for r in ex:
        parts = "".join(f'<div class="lab-quote"><b>{_e(p.get("role"))}</b> ({_e(p.get("stance"))}): “{_e(p.get("says"))}” '
                        f'<span class="muted">· thinks: {_e(p.get("privately_thinks"))}</span></div>' for p in r["participants"])
        body += f'<details><summary>{_e(r.get("name"))} · {_e(r.get("segment"))} · outcome: {_e(r.get("outcome"))}</summary>{parts}</details>'
    return _card("Buying committee", res, body)


def creative_card(res: Dict[str, Any]) -> str:
    s = res.get("summary") or {}
    gens = s.get("generations") or []
    rows = []
    for g in gens:
        vs = g.get("vs_original") or {}
        rows.append([f"Version {g.get('generation')}", _m(g.get("p_click"), 100, "%").split(" (")[0],
                     _w(g.get("stopped")), _w(g.get("would_click")),
                     "original" if g.get("generation") == 1 else f"{_m(vs, 100, ' pts')} · {vs.get('verdict', '')}"])
    body = f'<p><b>{_e(s.get("conclusion") or "")}</b></p>'
    body += ui.table(["Version", "Chance of tapping", "Stopped scrolling", "Would tap", "Versus the original (same people)"], rows,
                     sortable=False, num=[1])
    ads = "".join(f'<div class="lab-ad"><div class="muted small">Version {g.get("generation")} · {_e(g.get("change_summary"))}</div>'
                  f'{f"<div class=h>{_e(g["ad"].get("headline"))}</div>" if (g.get("ad") or {}).get("headline") else ""}'
                  f'{_e((g.get("ad") or {}).get("text"))}{f"<div class=c>{_e(g["ad"].get("cta"))}</div>" if (g.get("ad") or {}).get("cta") else ""}</div>'
                  for g in gens)
    body += f'<details><summary>See every version and what held people back</summary><div class="lab-grid" style="margin-top:10px">{ads}</div>'
    for g in gens:
        body += _ranked((g.get("objections") or [])[:3], f"Version {g.get('generation')}: what held people back", 1)
    return _card("Creative optimizer", res, body + "</details>")


def battlecard_card(res: Dict[str, Any]) -> str:
    u = _unavailable(res)
    if u:
        return _card("Sales battlecard", res, u)
    s = res.get("summary") or {}
    card = s.get("card") or {}
    eff = {e["type"]: e for e in s.get("rebuttal_test") or []}
    rows = []
    for x in card.get("objections") or []:
        t = str(x.get("type") or "")
        e = eff.get(t) or {}
        rows.append([t.replace("_", " "), x.get("buyer_says") or "", x.get("rebuttal") or "", x.get("discovery_question") or "",
                     f"{_w(e.get('moved_yes'))} yes, {_w(e.get('moved_somewhat'))} somewhat (tested on {e.get('tested_on', 0)})"])
    src = ", ".join(f"{k} {v}" for k, v in (s.get("objection_sources") or {}).items())
    body = f'<p class="lab-meta">Objections from: {_e(src)}</p>' + _ranked(s.get("objections") or [], "Objections people raised", 1)
    body += "<h4>Playbook, with each rebuttal tested on the people who raised the objection</h4>" + ui.table(
        ["Objection", "What they say", "Rebuttal", "Ask first", "Moved by the rebuttal"], rows, sortable=False)
    if card.get("outreach"):
        body += "<h4>Outreach sequence</h4>" + ui.table(["Day", "Channel", "Message"],
                                                       [[str(x.get("day", "")), x.get("channel", ""), x.get("message", "")] for x in card["outreach"]], sortable=False)
    if card.get("qualification_questions"):
        body += "<h4>Qualification questions</h4><ul>" + "".join(f"<li>{_e(q)}</li>" for q in card["qualification_questions"]) + "</ul>"
    return _card("Sales battlecard", res, body)


def journey_card(res: Dict[str, Any]) -> str:
    s = res.get("summary") or {}
    body = _bars([(f.get("stage", ""), f) for f in s.get("funnel") or []])
    if s.get("touches"):
        body += "<details><summary>The messages they saw" + (" (written from your offer)" if s.get("touches_generated") else "") + "</summary>" + \
                "".join(f'<div class="lab-ad"><div class="muted small">{_e(t.get("name"))} · {_e(t.get("channel"))} · day {_e(t.get("day"))}</div>{_e(t.get("text"))}</div>'
                        for t in s["touches"]) + "</details>"
    body += _ranked(s.get("drop_off") or [], "Where and why people dropped off")
    if s.get("first_touch_of_signups"):
        body += '<p class="lab-meta">Signed-up people first clicked on: ' + _e(", ".join(f"{k} {v}" for k, v in s["first_touch_of_signups"].items())) + \
                " · they signed up at: " + _e(", ".join(f"{k} {v}" for k, v in (s.get("converting_touch") or {}).items())) + "</p>"
    if (s.get("would_recommend") or {}).get("n"):
        body += f'<p class="lab-meta">Would recommend it after a week: {_e(_w(s["would_recommend"]))}</p>'
    ec = s.get("economics")
    if ec:
        rng = ec.get("cost_per_signup_range") or [None, None]
        body += '<div class="lab-kpis">' + _kpi(f"{ec.get('currency', '')} {ec.get('cost_per_signup')}", "cost per sign-up",
                                               f"range {rng[0]}–{rng[1]}; {ec.get('basis', '')}") + "</div>"
    return _card("Customer journey", res, body)


def pricing_card(res: Dict[str, Any]) -> str:
    s = res.get("summary") or {}
    cur = s.get("currency") or ""
    opts = s.get("options") or []
    body = _bars([(f"{o.get('name')}" + (f" · {cur} {o['price']:g}" if isinstance(o.get("price"), (int, float)) else ""), o.get("share")) for o in opts]
                 + [("None of these", (s.get("none") or {}).get("share"))])
    if s.get("options_generated"):
        body += '<p class="lab-meta">The options were proposed from your offer; review them before acting on the result.</p>'
    rows = [[o.get("name"), o.get("billing") or "", o.get("includes") or "", _w(o.get("share")),
             "–" if o.get("revenue_per_100_people") is None else f"{cur} {o['revenue_per_100_people']:g}"] for o in opts]
    body += ui.table(["Option", "Billing", "Includes", "Chosen by", "Revenue per 100 people"], rows, sortable=False)
    for o in opts:
        if o.get("reasons"):
            body += _quotes(o["reasons"][:2], o.get("name"))
    if (s.get("none") or {}).get("reasons"):
        body += _quotes(s["none"]["reasons"][:3], "None:")
    return _card("Pricing and packaging", res, body)


def lab_section(bundle: Dict[str, Any], insight: Optional[str] = None) -> Section:
    cards = []
    for key, fn in (("buying_committee", committee_card), ("creative_optimizer", creative_card), ("sales_battlecard", battlecard_card),
                    ("journey_sim", journey_card), ("pricing_conjoint", pricing_card)):
        res = bundle.get(key) or ((bundle.get("gtm_suite") or {}).get("engines") or {}).get(
            {"buying_committee": "committee", "creative_optimizer": "creative", "sales_battlecard": "battlecard",
             "journey_sim": "journey", "pricing_conjoint": "pricing"}[key])
        if isinstance(res, dict) and res.get("engine"):
            try:
                cards.append(fn(res))
            except Exception as e:  # noqa: BLE001 - one bad result never takes the page down
                cards.append(f'<div class="lab-card"><p class="muted">Could not show this result: {_e(str(e)[:120])}</p></div>')
    if not cards:
        return None
    head = ui.section_head("Marketing and sales lab", "Each test asked the simulated people directly. Percentages show the "
                           "share of people with a 95% range; small groups are directions, not results.", insight)
    return ("gtm", "Marketing and sales lab", head + f'<div class="lab-grid">{"".join(cards)}</div>')


# --------------------------------------------------------------------------
# Competitors
# --------------------------------------------------------------------------

def competitor_section(bundle: Dict[str, Any], insight: Optional[str] = None) -> Section:
    res = bundle.get("competitor_intel") or ((bundle.get("gtm_suite") or {}).get("engines") or {}).get("competitors")
    if not isinstance(res, dict) or not res.get("engine"):
        return None
    u = _unavailable(res)
    s = res.get("summary") or {}
    if u:
        body = u
    else:
        body = "<h4>What people chose</h4>" + _bars([(o["name"], o.get("share")) for o in s.get("options") or []])
        for o in s.get("options") or []:
            if o.get("why_people_chose_it"):
                body += _quotes(o["why_people_chose_it"][:2], o["name"] + ":")
        if s.get("what_would_make_them_choose_you"):
            body += f"<h4>What would make them choose {_e(s.get('brand'))}</h4>" + _quotes(s["what_would_make_them_choose_you"][:6])
        if s.get("suggestions"):
            rows = [[x.get("title", ""), x.get("change", ""), x.get("evidence", ""), x.get("kind", ""), x.get("effort", "")] for x in s["suggestions"]]
            body += "<h4>Suggested changes (each tied to what people said)</h4>" + ui.table(["Suggestion", "Change", "Evidence", "Kind", "Effort"], rows, sortable=False)
        for mv in s.get("moves") or []:
            body += (f'<div class="lab-card" style="background:var(--surface-2);margin-top:10px"><b>If: {_e(mv.get("move"))}</b>'
                     f'<p class="lab-meta">{_e(s.get("brand"))} chosen by {_e(_w(mv.get("brand_share_before")))} before, '
                     f'{_e(_w(mv.get("brand_share_after")))} after · {mv.get("switched_away", 0)} switched away, '
                     f'{mv.get("switched_to_brand", 0)} switched to you ({mv.get("people", 0)} people)</p>{_quotes((mv.get("why") or [])[:3])}</div>')
    head = ui.section_head("Competitors", "Each simulated person chose between you, your competitors and doing nothing. "
                           "Competitors come from your input or product profile.", insight)
    return ("competitors", "Competitors", head + _card("Competitor choice", res, body))


# --------------------------------------------------------------------------
# CRO lab
# --------------------------------------------------------------------------

def teardown_card(res: Dict[str, Any]) -> str:
    s = res.get("summary") or {}
    pg = s.get("page") or {}
    body = f'<p class="lab-meta">{_e(pg.get("url") or pg.get("title") or "page text")}</p>'
    if s.get("understood"):
        body += "<h4>Understood what it is after five seconds</h4>" + _bars([("Correct", s["understood"].get("correct")),
                                                                           ("Partly", s["understood"].get("partly")), ("Wrong", s["understood"].get("wrong"))])
        body += f'<p class="lab-meta">{_e(s.get("understood_basis"))}</p>'
    wc = s.get("would_continue") or {}
    body += "<h4>Would continue</h4>" + _bars([("Yes", wc.get("yes")), ("Maybe", wc.get("maybe")), ("No", wc.get("no"))])
    ru = s.get("read_until") or {}
    body += "<h4>How far they would read</h4>" + _bars([("Only the top", ru.get("top")), ("Middle", ru.get("middle")), ("To the end", ru.get("end"))])
    body += _ranked(s.get("confusing") or [], "What confused people")
    mt = (s.get("missing_to_decide") or [{}])[0] if s.get("missing_to_decide") else {}
    if mt.get("quotes"):
        body += "<h4>What they still needed to decide</h4>" + _quotes(mt["quotes"][:5])
    return _card("Landing page: five-second and scroll test", res, body)


def roleplay_card(res: Dict[str, Any]) -> str:
    s = res.get("summary") or {}
    o = s.get("outcomes") or {}
    body = "<h4>The rep's messages</h4>" + "".join(f'<div class="lab-quote"><b>{i + 1}.</b> {_e(m)}</div>' for i, m in enumerate(s.get("messages") or []))
    body += _bars([("Agreed to a next step", o.get("agreed_to_next_step")), ("Maybe later", o.get("maybe_later")), ("No", o.get("no"))])
    sc = s.get("scores") or {}
    body += '<div class="lab-kpis">' + "".join(_kpi(_m(sc.get(k)).split(" (")[0], lbl, "1–5, " + ("lower is better" if k == "pushy" else "higher is better"))
                                               for k, lbl in (("clear", "clear"), ("relevant_to_me", "relevant"), ("trustworthy", "trustworthy"), ("pushy", "pushy"))) + "</div>"
    adv = (s.get("advice") or [{}])[0] if s.get("advice") else {}
    if adv.get("quotes"):
        body += "<h4>What buyers said the rep should have said</h4>" + _quotes(adv["quotes"][:5])
    return _card("Sales roleplay", res, body)


def whatif_card(res: Dict[str, Any]) -> str:
    s = res.get("summary") or {}
    rows = [[e.get("attribute"), e.get("level"), e.get("versus"),
             "–" if e.get("effect_pts") is None else f"{e['effect_pts']:+g} pts", "–" if e.get("lo") is None else f"{e['lo']:+g} to {e['hi']:+g}",
             e.get("verdict", "")] for e in s.get("effects") or []]
    body = ui.table(["Attribute", "Level", "Compared with", "Effect on being picked", "95% range", "Verdict"], rows, sortable=False)
    body += f'<p class="lab-meta">{_e(s.get("method"))} · {s.get("choices", 0)} choices, neither picked {_e(_w(s.get("neither")))}</p>'
    if s.get("what_mattered_most"):
        body += _quotes(s["what_mattered_most"][:4])
    return _card("What-if choice experiment", res, body)


def personalize_card(res: Dict[str, Any]) -> str:
    s = res.get("summary") or {}
    rows = [[x.get("segment"), x.get("people"), _m(x.get("original_p_click"), 100, "%").split(" (")[0],
             _m(x.get("variant_p_click"), 100, "%").split(" (")[0], f"{_m(x.get('difference'), 100, ' pts')} · {(x.get('difference') or {}).get('verdict', '')}"]
            for x in s.get("segments") or []]
    body = ui.table(["Audience", "People", "Original: chance of tapping", "Tailored version", "Difference (same people)"], rows, sortable=False)
    body += "".join(f'<details><summary>{_e(x.get("segment"))}: {_e(x.get("angle"))}</summary><div class="lab-ad">'
                    f'{f"<div class=h>{_e(x["variant"].get("headline"))}</div>" if (x.get("variant") or {}).get("headline") else ""}{_e((x.get("variant") or {}).get("text"))}</div></details>'
                    for x in s.get("segments") or [])
    return _card("Ads tailored per audience", res, body)


def cro_lab_section(bundle: Dict[str, Any], insight: Optional[str] = None) -> Section:
    cards = []
    for key, fn in (("landing_teardown", teardown_card), ("sales_roleplay", roleplay_card), ("causal_whatif", whatif_card),
                    ("segment_personalization", personalize_card)):
        res = bundle.get(key)
        if isinstance(res, dict) and res.get("engine"):
            try:
                cards.append(fn(res))
            except Exception as e:  # noqa: BLE001
                cards.append(f'<div class="lab-card"><p class="muted">Could not show this result: {_e(str(e)[:120])}</p></div>')
    if not cards:
        return None
    head = ui.section_head("Conversion lab", "Landing page, sales conversation, offer what-ifs and tailored ads, each tested on "
                           "the simulated people.", insight)
    return ("cro-lab", "Conversion lab", head + f'<div class="lab-grid">{"".join(cards)}</div>')


# --------------------------------------------------------------------------
# What people thought
# --------------------------------------------------------------------------

def thoughts_section(bundle: Dict[str, Any], insight: Optional[str] = None) -> Section:
    test = bundle.get("thought_stream") if isinstance(bundle.get("thought_stream"), dict) else None
    harvest = bundle.get("thought_harvest") if isinstance(bundle.get("thought_harvest"), dict) else None
    if not ((test and test.get("thought_test")) or (harvest and harvest.get("entries"))):
        return None
    body = ""
    if test and test.get("thought_test"):
        t = test["thought_test"]
        body += f'<div class="lab-card"><h3>Thought test</h3><p class="lab-meta">{_e(test.get("stimulus"))} · {t.get("people")} people'
        body += f' · {test.get("failed", 0)} calls failed</p>' if test.get("failed") else "</p>"
        body += "<h4>First reaction</h4>" + _bars([(k.replace("_", " "), v) for k, v in (t.get("gut") or {}).items()])
        body += "<h4>What stands in the way</h4>" + _bars([(k.replace("_", " "), v) for k, v in (t.get("roadblock") or {}).items() if k != "none"])
        body += "<h4>Privately</h4>" + _bars([(k, v) for k, v in (t.get("private_verdict") or {}).items()])
        body += f'<p class="lab-meta">Privately positive but would not act on it: {_e(_w(t.get("said_yes_but_would_not_act")))}</p>'
        ents = [e for e in test.get("entries") or [] if e.get("text")][:8]
        body += "".join(f'<div class="lab-quote"><b>{_e(e.get("name"))}</b> · {_e(e.get("segment"))}: “{_e(e.get("text"))}” '
                        f'<span class="muted">→ {_e(e.get("would_do"))}</span></div>' for e in ents) + "</div>"
    if harvest and harvest.get("entries"):
        kinds = {"private_thought": "thought", "said": "said", "posted": "posted"}
        rows = [[e.get("name") or "", e.get("segment") or "", e.get("source") or "", kinds.get(e.get("kind"), e.get("kind") or ""),
                 e.get("text") or "", e.get("did") or ""] for e in harvest["entries"][:150]]
        src = ", ".join(f"{k} {v}" for k, v in (harvest.get("by_source") or {}).items())
        body += (f'<div class="lab-card"><h3>Everything people wrote in this run</h3><p class="lab-meta">{_e(src)}</p>'
                 + ui.table(["Person", "Audience", "Where", "Kind", "Text", "What they did"], rows, sortable=True, tall=True) + "</div>")
    head = ui.section_head("What people thought", "Text the simulated people wrote, labelled as a private thought, something "
                           "they said, or something they posted. Nothing is filled in for people who wrote nothing.", insight)
    return ("thoughts", "What people thought", head + f'<div class="lab-grid">{body}</div>')


# --------------------------------------------------------------------------
# Search, AI visibility (GEO), real vs simulated voices (VoC) & cascades
# --------------------------------------------------------------------------

CONCEPT_TERMS: Dict[str, Tuple[str, List[str]]] = {
    "price": ("Price & budget", ["price", "pricing", "cost", "expensive", "cheap", "affordable", "budget", "wallet", "money", "weekly", "monthly", "annual", "subscription", "tier", "plan", "discount", "value", "worth", "fee", "pay", "free", "trial"]),
    "trust": ("Trust & card risk", ["trust", "trustworthy", "credible", "scam", "skeptical", "proof", "review", "reviews", "guarantee", "refund", "cancel", "cancellation", "card", "credit", "debit", "auto-renew", "trap", "charge", "billing", "privacy", "risk", "signup", "sign-up", "hesitate", "checkout", "abandon"]),
    "authority": ("Partner / boss approval", ["spouse", "husband", "wife", "partner", "parents", "family", "household", "shared", "couple", "committee", "boss", "manager", "cfo", "finance", "blocker", "champion", "approval", "ask", "team"]),
    "habit": ("Routine & time", ["habit", "routine", "streak", "quit", "drop", "churn", "retention", "consistent", "busy", "tired", "fatigue", "schedule", "shift", "time", "effort", "easy", "daily"]),
    "competitor": ("Competitors & alternatives", ["competitor", "competitors", "alternative", "alternatives", "already", "switch", "switching", "compare", "comparison", "versus", "vs", "better", "different", "youtube", "free"]),
    "unclear": ("Clarity & missing info", ["unclear", "confusing", "confused", "understand", "what", "how", "explain", "headline", "copy", "landing", "page", "missing", "detail", "vague"]),
}


def _short_txt(x: Any, n: int = 240) -> str:
    s = " ".join(str(x or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _detect_doc_concepts(text: str) -> List[str]:
    low = text.lower()
    words = set(re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)?", low))
    out: List[str] = []
    for cid, (_lbl, kws) in CONCEPT_TERMS.items():
        if any(k in words or (len(k) >= 5 and k in low) for k in kws):
            out.append(cid)
    return out


def build_bundle_search_docs(bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build a compact, stdlib-only searchable list of real quotes, thoughts, posts and people in `bundle`."""
    if not isinstance(bundle, dict):
        return []
    docs: List[Dict[str, Any]] = []
    cfg = bundle.get("config") if isinstance(bundle.get("config"), dict) else {}
    people = [p for p in (cfg.get("persona_index") or []) if isinstance(p, dict)]
    by_id = {p.get("agent_id"): p for p in people if p.get("agent_id") is not None}

    def add(doc_type: str, label: str, title: str, snippet: str, segment: str = "", anchor: str = "#top") -> None:
        s = _short_txt(snippet, 240)
        if not s:
            return
        t = _short_txt(title, 110)
        blob = f"{t} {segment} {s}"
        docs.append({
            "type": doc_type,
            "label": label,
            "title": t,
            "segment": str(segment or ""),
            "snippet": s,
            "anchor": anchor,
            "concepts": _detect_doc_concepts(blob),
        })

    for p in people[:180]:
        aid = p.get("agent_id")
        txt = str(p.get("persona") or p.get("bio") or "").strip()
        bde = p.get("bde") if isinstance(p.get("bde"), dict) else {}
        if bde:
            txt = f"{txt} {json.dumps(bde, ensure_ascii=False)}".strip()
        if txt:
            add("persona", "Person", ", ".join(str(x) for x in (p.get("name") or f"Person {aid}", p.get("occupation"), p.get("country")) if x),
                txt, str(p.get("segment") or ""), "#agents")

    for r in ((bundle.get("survey") or {}).get("responses") or [])[:200]:
        if not isinstance(r, dict):
            continue
        a = r.get("answer") if isinstance(r.get("answer"), dict) else {}
        obj = str(a.get("main_objection") or a.get("reasoning") or "").strip()
        if obj:
            p = by_id.get(r.get("agent_id"), {})
            name = r.get("name") or p.get("name") or f"Person {r.get('agent_id')}"
            seg = r.get("segment") or p.get("segment") or ""
            add("survey", "Survey answer", f"{name} · would convert: {a.get('would_convert', '?')}", obj, seg, "#voices")

    for t_key in ("thought_stream", "thought_harvest"):
        ts = bundle.get(t_key)
        if isinstance(ts, dict):
            for e in (ts.get("entries") or [])[:200]:
                if isinstance(e, dict) and str(e.get("text") or "").strip():
                    did = e.get("would_do") or e.get("did") or ""
                    add("thought", f"Thought ({e.get('source') or 'run'})",
                        str(e.get("name") or f"Person {e.get('agent_id')}"),
                        f"{e['text']}" + (f" → {did}" if did else ""),
                        str(e.get("segment") or ""), "#thoughts")

    ft = bundle.get("feed_test")
    if isinstance(ft, dict):
        first = ft.get("seed")
        for s in (ft.get("sessions") or [])[:150]:
            if not isinstance(s, dict) or (first is not None and s.get("seed") not in (None, first)):
                continue
            ad, land = s.get("ad") or {}, s.get("landing") or {}
            th = str(land.get("thought") or ad.get("thought") or "").strip()
            if th:
                add("feed", "Feed & landing", f"{s.get('name') or 'Person'} on {s.get('creative_id') or 'ad'}",
                    th + (f" (Drop: {land['drop_reason']})" if land.get("drop_reason") else ""),
                    str(s.get("segment") or ""), "#feedtest")

    pitch = bundle.get("pitch")
    if isinstance(pitch, dict):
        for r in (pitch.get("people") or [])[:120]:
            if isinstance(r, dict):
                rep = str((r.get("turn1") or {}).get("reply") or "").strip()
                if rep:
                    add("pitch", "Pitch reply", f"{r.get('name') or 'Buyer'} · {r.get('final_verdict') or '?'}",
                        rep, str(r.get("segment") or ""), "#pitch")

    acts = bundle.get("actions")
    if isinstance(acts, dict):
        acts = acts.get("actions")
    for a in (acts or [])[:120]:
        if isinstance(a, dict):
            args = a.get("action_args") or {}
            txt = str(args.get("content") or args.get("quote_content") or a.get("content") or "").strip()
            if txt:
                p = by_id.get(a.get("agent_id"), {})
                add("post", "Social post", str(a.get("agent_name") or p.get("name") or f"Person {a.get('agent_id')}"),
                    txt, str(p.get("segment") or ""), "#posts")

    return docs[:450]


def search_bundle_docs(
    query: str,
    docs: List[Dict[str, Any]],
    doc_type: Optional[str] = None,
    concept: Optional[str] = None,
    top_k: int = 15,
) -> List[Dict[str, Any]]:
    """Stdlib BM25 + concept-synonym search over `docs`."""
    pool = list(docs)
    if doc_type and doc_type not in ("", "all"):
        pool = [d for d in pool if d.get("type") == doc_type]
    if concept and concept not in ("", "all"):
        pool = [d for d in pool if concept in (d.get("concepts") or [])]
    q = (query or "").strip().lower()
    if not q:
        return pool[:top_k]

    q_toks = [t for t in re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)?", q) if len(t) > 1]
    q_concepts = _detect_doc_concepts(q)
    syn_toks: List[str] = []
    for cid in q_concepts:
        for kw in CONCEPT_TERMS[cid][1][:10]:
            if kw not in q_toks and kw not in syn_toks:
                syn_toks.append(kw)

    n = len(pool)
    if not n:
        return []
    tok_lists = [re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)?", f"{d.get('title', '')} {d.get('snippet', '')} {d.get('segment', '')}".lower()) for d in pool]
    df: Counter = Counter()
    for tl in tok_lists:
        for t in set(tl):
            df[t] += 1
    avgdl = sum(len(tl) for tl in tok_lists) / max(1, n)

    scored: List[Tuple[float, Dict[str, Any]]] = []
    for idx, d in enumerate(pool):
        tl = tok_lists[idx]
        tf = Counter(tl)
        dl = len(tl)
        sc = 0.0
        for qt in q_toks:
            f = tf.get(qt, 0)
            if f > 0:
                idf = math.log(1.0 + (n - df[qt] + 0.5) / (df[qt] + 0.5))
                sc += 2.5 * idf * ((f * 2.5) / (f + 1.5 * (0.25 + 0.75 * (dl / max(1.0, avgdl)))))
            elif any(qt in tok for tok in tf if len(qt) >= 4):
                sc += 0.9
        for st in syn_toks:
            if tf.get(st, 0) > 0:
                sc += 0.45 * math.log(1.0 + (n - df[st] + 0.5) / (df[st] + 0.5))
        overlap = set(q_concepts) & set(d.get("concepts") or [])
        if overlap:
            sc += 1.8 * len(overlap)
        if len(q) >= 3 and (q in d.get("title", "").lower() or q in d.get("snippet", "").lower()):
            sc += 3.0
        if sc > 0:
            scored.append((sc, {**d, "score": round(sc, 2)}))
    scored.sort(key=lambda x: -x[0])
    return [d for _, d in scored[:top_k]]


def geo_card(res: Dict[str, Any]) -> str:
    s = res.get("summary") or {}
    sl = s.get("would_shortlist") or {}
    body = "<h4>Would shortlist after checking with AI / search</h4>" + _bars([
        ("Yes", sl.get("yes")), ("Maybe", sl.get("maybe")), ("No", sl.get("no"))
    ])
    alts = s.get("known_alternatives") or []
    if alts:
        body += "<h4>Alternatives people already knew before seeing your offer</h4>" + _bars([
            (a.get("name", ""), a.get("share")) for a in alts[:6]
        ])
    if s.get("buyer_search_queries"):
        body += "<h4>Exact searches people said they would type into ChatGPT, Perplexity or Google</h4>" + _quotes(s["buyer_search_queries"][:6])
    if s.get("verification_questions"):
        body += "<h4>What they would ask an AI assistant to verify before trusting you</h4>" + _quotes(s["verification_questions"][:6])
    body += _ranked(s.get("missing_facts_for_ai") or [], "Facts missing from the offer that AI answers & FAQs need")
    if s.get("faqs"):
        rows = [[x.get("question", ""), x.get("answer", ""), "yes" if x.get("in_facts") else "gap"] for x in s["faqs"]]
        body += "<h4>Draft FAQ pairs (from your product facts only)</h4>" + ui.table(["Question buyers asked", "Answer from product facts", "In facts"], rows, sortable=False)
    if s.get("llms_txt"):
        body += f'<details><summary>Draft <code>/llms.txt</code> for AI search crawlers</summary><pre class="lab-ad" style="font-family:var(--mono)">{_e(s["llms_txt"])}</pre></details>'
    return _card("AI search visibility (GEO)", res, body)


def voc_card(res: Dict[str, Any]) -> str:
    u = _unavailable(res)
    if u:
        return _card("Real vs simulated voices (VoC)", res, u)
    s = res.get("summary") or {}
    body = f'<p class="lab-meta">Source: {_e(s.get("source") or "real voices")} · {s.get("real_voices_count", 0)} real voices vs {s.get("simulated_objections_count", 0)} simulated objections</p>'
    comp = s.get("comparison") or []
    if comp:
        rows = [[str(c.get("concern") or "").replace("_", " "), _w(c.get("real_share")), _w(c.get("simulated_share"))] for c in comp]
        body += ui.table(["Concern", "In real voices", "In simulated people"], rows, sortable=False)
    body += _ranked(s.get("real_concerns") or [], "Concerns in the real voices", 2)
    phrases = s.get("verbatim_phrases") or []
    if phrases:
        p_rows = [[str(p.get("concern") or "").replace("_", " "), p.get("exact_phrase") or "", p.get("meaning") or ""] for p in phrases[:8]]
        body += "<h4>Exact phrases real people used</h4>" + ui.table(["Concern", "Exact phrase", "Plain meaning"], p_rows, sortable=False)
    return _card("Real vs simulated voices (VoC)", res, body)


def cascade_card(res: Dict[str, Any]) -> str:
    s = res.get("summary") or {}
    ws = s.get("would_share") or {}
    body = "<h4>Wave 1: would privately forward or mention this offer</h4>" + _bars([
        ("Yes", ws.get("yes")), ("Maybe", ws.get("maybe")), ("No", ws.get("no"))
    ])
    chs = s.get("channels") or []
    if chs:
        body += "<h4>Where they would send it</h4>" + _bars([(str(c.get("channel") or "").replace("_", " "), c.get("share")) for c in chs])
    msgs = s.get("forwarded_messages") or []
    if msgs:
        body += "<h4>Exact messages they wrote to forward</h4>" + "".join(
            f'<div class="lab-quote"><b>{_e(m.get("from_name"))}</b> → {_e(m.get("who"))} ({_e(str(m.get("channel") or "").replace("_", " "))}): “{_e(m.get("message"))}”</div>'
            for m in msgs[:6]
        )
    w2 = s.get("wave2_peer_pickup")
    if isinstance(w2, dict):
        ft = w2.get("would_try_from_friend") or {}
        ct = w2.get("would_try_if_cold_ad") or {}
        fa = w2.get("would_forward_again") or {}
        body += f"<h4>Wave 2 ({w2.get('people', 0)} people receiving a friend's forwarded message)</h4>" + _bars([
            ("Would try from friend's forward (yes)", ft.get("yes")),
            ("Would try if seen as cold ad (yes)", ct.get("yes")),
            ("Would forward again to another person (yes)", fa.get("yes")),
        ])
        if w2.get("reactions"):
            body += _quotes(w2["reactions"][:4], "Wave 2 reaction:")
    return _card("Private sharing & word-of-mouth cascade", res, body)


def search_geo_section(bundle: Dict[str, Any], insight: Optional[str] = None) -> Section:
    """'Search, AI visibility & voices': interactive BM25 + concept search across everything the simulated people
    wrote in this run, plus AI search visibility (GEO), real-vs-simulated VoC, and word-of-mouth cascade cards."""
    if not isinstance(bundle, dict):
        return None
    docs = build_bundle_search_docs(bundle)
    cards: List[str] = []

    if docs:
        types = list(dict.fromkeys((d["type"], d["label"]) for d in docs))
        type_opts = '<option value="">All sources (' + str(len(docs)) + ')</option>' + "".join(
            f'<option value="{_e(t)}">{_e(lbl)}</option>' for t, lbl in types
        )
        concept_btns = '<button type="button" class="mm-c-pill" data-mm-concept="" aria-pressed="true">All topics</button>' + "".join(
            f'<button type="button" class="mm-c-pill" data-mm-concept="{_e(cid)}" aria-pressed="false">{_e(lbl)}</button>'
            for cid, (lbl, _kws) in CONCEPT_TERMS.items()
        )
        initial_items = "".join(
            f'<div class="mm-s-item"><div class="mm-s-head"><span>{_e(d["label"])}'
            + (f' · {_e(d["segment"])}' if d.get("segment") else "")
            + f'</span><a href="{_e(d["anchor"])}">Jump to section ↗</a></div>'
            f'<div class="mm-s-title">{_e(d["title"])}</div>'
            f'<div>“{_e(d["snippet"])}”</div></div>'
            for d in docs[:10]
        )
        docs_json = json.dumps(docs, ensure_ascii=False).replace("<", "\\u003c")
        syns_json = json.dumps({cid: kws for cid, (_l, kws) in CONCEPT_TERMS.items()}, ensure_ascii=False).replace("<", "\\u003c")
        search_js = """<script>(function(){
var box=document.getElementById('mm-run-search');if(!box)return;
var dataEl=document.getElementById('mm-search-docs'),synEl=document.getElementById('mm-search-syns');
if(!dataEl||!synEl)return;
var docs=[],syns={};try{docs=JSON.parse(dataEl.textContent||'[]');syns=JSON.parse(synEl.textContent||'{}');}catch(e){return;}
var qIn=document.getElementById('mm-s-q'),tSel=document.getElementById('mm-s-type'),listEl=document.getElementById('mm-s-results'),cntEl=document.getElementById('mm-s-count');
var curConcept='';
function esc(s){return String(s||'').replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
function runSearch(){
  var q=(qIn&&qIn.value||'').trim().toLowerCase();
  var tp=(tSel&&tSel.value||'');
  var pool=docs.filter(function(d){
    if(tp&&d.type!==tp)return false;
    if(curConcept&&(d.concepts||[]).indexOf(curConcept)<0)return false;
    return true;
  });
  if(!q){
    if(cntEl)cntEl.textContent='Showing '+Math.min(12,pool.length)+' of '+pool.length+' records';
    render(pool.slice(0,12));return;
  }
  var toks=q.split(/[^a-z0-9-]+/).filter(function(x){return x.length>1;});
  var expanded=toks.slice();
  Object.keys(syns).forEach(function(cid){
    var kws=syns[cid]||[];
    if(toks.some(function(t){return kws.indexOf(t)>=0;})){
      kws.slice(0,10).forEach(function(k){if(expanded.indexOf(k)<0)expanded.push(k);});
    }
  });
  var scored=[];
  pool.forEach(function(d){
    var hay=(d.title+' '+d.snippet+' '+d.segment).toLowerCase();
    var sc=0;
    if(hay.indexOf(q)>=0)sc+=4;
    toks.forEach(function(t){if(hay.indexOf(t)>=0)sc+=2.5;});
    expanded.forEach(function(t){if(toks.indexOf(t)<0&&hay.indexOf(t)>=0)sc+=0.6;});
    if(sc>0)scored.push({d:d,sc:sc});
  });
  scored.sort(function(a,b){return b.sc-a.sc;});
  if(cntEl)cntEl.textContent=scored.length+' matching records (ranked by relevance & synonym expansion)';
  render(scored.slice(0,15).map(function(x){return x.d;}));
}
function render(items){
  if(!listEl)return;
  if(!items.length){listEl.innerHTML='<p class="muted small">No records matched that filter.</p>';return;}
  listEl.innerHTML=items.map(function(d){
    return '<div class="mm-s-item"><div class="mm-s-head"><span>'+esc(d.label)+(d.segment?' · '+esc(d.segment):'')+'</span><a href="'+esc(d.anchor)+'">Jump to section ↗</a></div><div class="mm-s-title">'+esc(d.title)+'</div><div>“'+esc(d.snippet)+'”</div></div>';
  }).join('');
}
if(qIn)qIn.addEventListener('input',runSearch);
if(tSel)tSel.addEventListener('change',runSearch);
box.querySelectorAll('[data-mm-concept]').forEach(function(btn){
  btn.addEventListener('click',function(){
    box.querySelectorAll('[data-mm-concept]').forEach(function(x){x.setAttribute('aria-pressed','false');});
    btn.setAttribute('aria-pressed','true');
    curConcept=btn.getAttribute('data-mm-concept')||'';
    runSearch();
  });
});
document.addEventListener('keydown',function(ev){
  if((ev.metaKey||ev.ctrlKey)&&ev.key.toLowerCase()==='k'){
    ev.preventDefault();if(qIn){qIn.focus();qIn.scrollIntoView({behavior:'smooth',block:'center'});}
  }
});
})();</script>"""
        cards.append(
            '<div class="lab-card" id="mm-run-search">'
            '<h3>Search everything people said, thought or posted in this run</h3>'
            f'<p class="lab-meta">{len(docs)} records indexed across this run · press <code>Ctrl+K</code> / <code>⌘K</code> to focus · expands buyer-concern synonyms automatically</p>'
            '<div class="mm-search-bar">'
            '<input type="search" id="mm-s-q" placeholder="Search quotes, thoughts, objections, people (e.g. price, card, spouse, routine, alternative)…" aria-label="Search run evidence">'
            f'<select id="mm-s-type" aria-label="Filter by source">{type_opts}</select>'
            '</div>'
            f'<div class="mm-concept-pills" role="group" aria-label="Filter by topic">{concept_btns}</div>'
            f'<p class="lab-meta" id="mm-s-count">Showing {min(10, len(docs))} of {len(docs)} records</p>'
            f'<div id="mm-s-results">{initial_items}</div>'
            f'<script type="application/json" id="mm-search-docs">{docs_json}</script>'
            f'<script type="application/json" id="mm-search-syns">{syns_json}</script>'
            f'{search_js}</div>'
        )

    for key, fn in (("geo_visibility", geo_card), ("voc_grounding", voc_card), ("dark_social", cascade_card)):
        res = bundle.get(key)
        if isinstance(res, dict) and res.get("engine"):
            try:
                cards.append(fn(res))
            except Exception as e:  # noqa: BLE001
                cards.append(f'<div class="lab-card"><p class="muted">Could not show this result: {_e(str(e)[:120])}</p></div>')

    if not cards:
        return None
    head = ui.section_head(
        "Search & discovery",
        "Search across every person, quote, thought and post in this run, plus AI search visibility (GEO), "
        "real-vs-simulated voice comparisons and word-of-mouth cascades when run.",
        insight,
    )
    return ("search-geo", "Search & discovery", head + f'<div class="lab-grid">{"".join(cards)}</div>')

