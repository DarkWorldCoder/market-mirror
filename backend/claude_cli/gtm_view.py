"""
gtm_view.py - dashboard sections for the marketing and sales tests (backend/app/services/gtm_suite.py and
cro_and_sparring.py) and for what the simulated people thought. Every number shown comes from the people's answers,
with its count and 95% range; a section is left out when its test has not run. Stdlib only.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

try:  # stdlib only
    import ui  # type: ignore
    import run_search  # type: ignore
except ImportError:  # pragma: no cover - imported as a package
    from . import ui  # type: ignore
    from . import run_search  # type: ignore

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
    bits = [f"{res.get('answered', 0)} of {res.get('asked', 0)} {res.get('unit') or 'simulated people answered'}"]
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
# Search, how buyers would search, real vs simulated concerns, word-of-mouth cascade
# --------------------------------------------------------------------------

def geo_card(res: Dict[str, Any]) -> str:
    s = res.get("summary") or {}
    body = ('<p class="lab-meta">Simulated answers only: this does not measure what any real AI assistant or search '
            'engine says about you.</p>')
    if s.get("need_shown"):
        body += f'<p class="lab-meta">Need shown before the offer ({_e(s.get("need_source") or "")}): “{_e(s["need_shown"])}”</p>'
    look = s.get("would_look_for_help") or {}
    body += "<h4>Before the offer: would ask an AI assistant or a search engine for help</h4>" + _bars([
        ("Yes", look.get("yes")), ("Maybe", look.get("maybe")), ("No", look.get("no"))])
    if s.get("search_queries"):
        body += "<h4>What they would type, in their own words</h4>" + _quotes(s["search_queries"][:6])
    if s.get("known_options"):
        body += "<h4>Options they already knew before seeing the offer</h4>" + _bars(
            [(a.get("name", ""), a.get("share")) for a in s["known_options"][:6]])
    named = [("Your product", s.get("named_the_brand_before"))] if s.get("named_the_brand_before") else []
    named += [(c.get("name", ""), c.get("share")) for c in s.get("named_competitors_before") or []]
    if named:
        body += "<h4>Named before seeing the offer</h4>" + _bars(named)
    sl = s.get("would_shortlist") or {}
    body += "<h4>After seeing the offer: would shortlist it</h4>" + _bars([
        ("Yes", sl.get("yes")), ("Maybe", sl.get("maybe")), ("No", sl.get("no"))])
    if s.get("understood_as"):
        body += "<h4>What they think it is</h4>" + _quotes(s["understood_as"][:5])
    if s.get("verification_questions"):
        body += "<h4>What they would check before trusting it</h4>" + _quotes(s["verification_questions"][:6])
    body += _ranked(s.get("missing_facts") or [], "Facts they missed in the offer")
    if s.get("faqs"):
        body += "<h4>Draft FAQ (written by the model from your product facts only)</h4>" + ui.table(
            ["Question simulated buyers asked", "Draft answer"], [[x.get("question", ""), x.get("answer", "")] for x in s["faqs"]],
            sortable=False)
    if s.get("unanswered_gaps"):
        body += "<h4>Asked for but not in your product facts</h4>" + _quotes(s["unanswered_gaps"][:6])
    if s.get("llms_txt"):
        body += (f'<details><summary>Draft <code>/llms.txt</code> (from your product facts only)</summary>'
                 f'<pre class="lab-ad" style="font-family:var(--mono)">{_e(s["llms_txt"])}</pre></details>')
    if s.get("drafts_error"):
        body += f'<p class="muted">The drafts were not written: {_e(s["drafts_error"])}</p>'
    return _card("How buyers would search (simulated)", res, body)


def _diff(d: Optional[Dict[str, Any]]) -> str:
    if not d or d.get("points") is None:
        return "–"
    return f"{d['points']:+g} pts ({d['lo']:+g} to {d['hi']:+g})"


def voc_card(res: Dict[str, Any]) -> str:
    u = _unavailable(res)
    if u:
        return _card("Real vs simulated concerns", res, u)
    s = res.get("summary") or {}
    real, sim = s.get("real") or {}, s.get("simulated") or {}
    label = s.get("real_label") or "real text"
    body = (f'<p class="lab-meta">Source: {_e(s.get("source") or label)} · {_e(real.get("classified", 0))} of '
            f'{_e(real.get("texts", 0))} texts of {_e(label)} labelled · {_e(sim.get("classified", 0))} of '
            f'{_e(sim.get("texts", 0))} simulated objections labelled</p>')
    if s.get("simulated_note"):
        body += f'<p class="muted">{_e(s["simulated_note"])}</p>'
    comp = s.get("comparison") or []
    if comp:
        rows = [[str(c.get("concern") or "").replace("_", " "), _w(c.get("real")), _w(c.get("simulated")), _diff(c.get("difference"))]
                for c in comp]
        body += ui.table(["Concern", f"In {label}", "In simulated people", "Difference (real minus simulated, 95% range)"],
                         rows, sortable=False)
    if s.get("method"):
        body += f'<p class="lab-meta">{_e(s["method"])}</p>'
    body += _ranked(s.get("real_concerns") or [], f"Concerns in the {label}", 2)
    phrases = s.get("phrases") or []
    if phrases:
        rows = [[str(p.get("concern") or "").replace("_", " "),
                 (p.get("phrase") or "") + ("" if p.get("copied_from_text") else " (whole text: the label's phrase was not in it)"),
                 p.get("meaning") or ""] for p in phrases[:8]]
        title = "Phrases from the page text" if s.get("source_kind") == "page" else "Phrases from the real text"
        body += f"<h4>{_e(title)}</h4>" + ui.table(["Concern", "Words copied from the text", "Plain meaning (model's summary)"],
                                                     rows, sortable=False)
    return _card("Real vs simulated concerns", res, body)


VERDICT_TEXT = {"better": "the friend's forward did better than the cold ad",
                "worse": "the cold ad did better than the friend's forward",
                "no clear difference": "no clear difference between the forward and the cold ad",
                "too few answers": "too few answers to compare"}


def cascade_card(res: Dict[str, Any]) -> str:
    s = res.get("summary") or {}
    ws = s.get("would_share") or {}
    body = "<h4>Wave 1: would privately forward or mention this offer</h4>" + _bars([
        ("Yes", ws.get("yes")), ("Maybe", ws.get("maybe")), ("No", ws.get("no"))])
    if s.get("channels"):
        body += "<h4>Where they would send it</h4>" + _bars([(str(c.get("channel") or "").replace("_", " "), c.get("share"))
                                                             for c in s["channels"]])
    msgs = s.get("forwarded_messages") or []
    if msgs:
        body += "<h4>Messages they wrote to forward</h4>" + "".join(
            f'<div class="lab-quote"><b>{_e(m.get("from_name"))}</b> → {_e(m.get("who"))} '
            f'({_e(str(m.get("channel") or "").replace("_", " "))}): “{_e(m.get("message"))}”</div>' for m in msgs[:6])
    w2 = s.get("wave2_peer_pickup")
    if isinstance(w2, dict) and w2.get("available") is False:
        body += f'<h4>Wave 2</h4><p class="muted">{_e(w2.get("reason") or "Not run.")}</p>'
    elif isinstance(w2, dict) and w2.get("available"):
        d = w2.get("friend_minus_cold") or {}
        body += (f"<h4>Wave 2: {_e(w2.get('paired', 0))} of {_e(w2.get('people', 0))} other people answered both the cold ad "
                 "and a friend's forward (two separate calls)</h4>")
        body += f'<div class="lab-kpis">{_kpi(_m(d), "Friend minus cold (would try, 0 to 1)", VERDICT_TEXT.get(d.get("verdict"), ""))}</div>'
        body += _bars([("Would try, cold ad (yes)", (w2.get("would_try_cold") or {}).get("yes")),
                       ("Would try, friend's forward (yes)", (w2.get("would_try_from_friend") or {}).get("yes")),
                       ("Would forward it again (yes)", (w2.get("would_forward_again") or {}).get("yes"))])
        if w2.get("reactions_to_forward"):
            body += _quotes(w2["reactions_to_forward"][:4], "Reaction to the forward:")
    return _card("Private sharing and word-of-mouth cascade", res, body)


SEARCH_JS = """<script>(function(){
var box=document.getElementById('mm-run-search'),dataEl=document.getElementById('mm-search-docs');if(!box||!dataEl)return;
var docs=[];try{docs=JSON.parse(dataEl.textContent||'[]');}catch(e){return;}
var qIn=document.getElementById('mm-s-q'),tSel=document.getElementById('mm-s-type'),listEl=document.getElementById('mm-s-results'),cntEl=document.getElementById('mm-s-count');
var cur='';
function esc(s){return String(s||'').replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
function words(s){return String(s||'').toLowerCase().match(/[a-z0-9]+(?:-[a-z0-9]+)?/g)||[];}
function render(items){
  if(!listEl)return;
  if(!items.length){listEl.innerHTML='<p class="muted small">No records matched.</p>';return;}
  listEl.innerHTML=items.map(function(d){
    return '<div class="mm-s-item"><div class="mm-s-head"><span>'+esc(d.type_label)+(d.segment?' · '+esc(d.segment):'')+'</span><a href="'+esc(d.anchor)+'">Jump to section ↗</a></div><div class="mm-s-title">'+esc(d.title)+'</div><div>“'+esc(d.snippet)+'”</div></div>';
  }).join('');
}
function run(){
  var q=words(qIn&&qIn.value),tp=(tSel&&tSel.value)||'';
  var pool=docs.filter(function(d){return (!tp||d.type===tp)&&(!cur||(d.concepts||[]).indexOf(cur)>=0);});
  var hits=pool;
  if(q.length){
    hits=[];
    pool.forEach(function(d){var w=words(d.title+' '+d.snippet+' '+d.segment);var n=q.filter(function(t){return w.indexOf(t)>=0;}).length;if(n)hits.push({d:d,n:n});});
    hits.sort(function(a,b){return b.n-a.n;});hits=hits.map(function(x){return x.d;});
    if(cntEl)cntEl.textContent=hits.length+' of '+pool.length+' records contain these words';
  }else if(cntEl){cntEl.textContent='Showing '+Math.min(12,pool.length)+' of '+pool.length+' records';}
  render(hits.slice(0,12));
}
if(qIn)qIn.addEventListener('input',run);
if(tSel)tSel.addEventListener('change',run);
box.querySelectorAll('[data-mm-concept]').forEach(function(btn){
  btn.addEventListener('click',function(){
    box.querySelectorAll('[data-mm-concept]').forEach(function(x){x.setAttribute('aria-pressed','false');});
    btn.setAttribute('aria-pressed','true');cur=btn.getAttribute('data-mm-concept')||'';run();
  });
});
})();</script>"""


def _search_card(bundle: Dict[str, Any]) -> str:
    docs = run_search.build_docs(bundle)[:600]
    if not docs:
        return ""
    types = list(dict.fromkeys(d["type"] for d in docs))
    type_opts = f'<option value="">All sources ({len(docs)})</option>' + "".join(
        f'<option value="{_e(t)}">{_e(run_search.TYPE_LABELS.get(t, t))}</option>' for t in types)
    pills = '<button type="button" class="mm-c-pill" data-mm-concept="" aria-pressed="true">All topics</button>' + "".join(
        f'<button type="button" class="mm-c-pill" data-mm-concept="{_e(cid)}" aria-pressed="false">{_e(label)}</button>'
        for cid, (label, _words) in run_search.CONCEPTS.items())
    first = "".join(
        f'<div class="mm-s-item"><div class="mm-s-head"><span>{_e(d["type_label"])}{" · " + _e(d["segment"]) if d.get("segment") else ""}'
        f'</span><a href="{_e(d["anchor"])}">Jump to section ↗</a></div><div class="mm-s-title">{_e(d["title"])}</div>'
        f'<div>“{_e(d["snippet"])}”</div></div>' for d in docs[:12])
    keep = ("id", "type", "type_label", "title", "segment", "snippet", "anchor", "concepts")
    docs_json = json.dumps([{k: d[k] for k in keep} for d in docs], ensure_ascii=False).replace("<", "\\u003c")
    return ('<div class="lab-card" id="mm-run-search"><h3>Search everything people said, thought or posted in this run</h3>'
            f'<p class="lab-meta">{len(docs)} records from this run · this page matches exact words; '
            '<code>mirofish.py search</code> also ranks related buyer-concern words</p>'
            '<div class="mm-search-bar"><input type="search" id="mm-s-q" placeholder="Words to find in quotes, thoughts, '
            f'objections and people" aria-label="Search this run"><select id="mm-s-type" aria-label="Filter by source">{type_opts}</select></div>'
            f'<div class="mm-concept-pills" role="group" aria-label="Filter by topic">{pills}</div>'
            f'<p class="lab-meta" id="mm-s-count">Showing {min(12, len(docs))} of {len(docs)} records</p>'
            f'<div id="mm-s-results">{first}</div>'
            f'<script type="application/json" id="mm-search-docs">{docs_json}</script>{SEARCH_JS}</div>')


def search_geo_section(bundle: Dict[str, Any], insight: Optional[str] = None) -> Section:
    """'Search & discovery': a filter over every record the run produced, plus the cards for how buyers would search
    (simulated), real vs simulated concerns and the word-of-mouth cascade when those tests ran."""
    if not isinstance(bundle, dict):
        return None
    cards = [c for c in [_search_card(bundle)] if c]
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
        "Find any person, quote, thought or post in this run, plus how buyers would search (simulated), real vs "
        "simulated concerns and the word-of-mouth cascade when those tests ran.",
        insight,
    )
    return ("search-geo", "Search & discovery", head + f'<div class="lab-grid">{"".join(cards)}</div>')
