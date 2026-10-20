"""
gtm_view.py - dashboard sections for the marketing and sales tests (backend/app/services/gtm_suite.py and
cro_and_sparring.py) and for what the simulated people thought. Every number shown comes from the people's answers,
with its count and 95% range; a section is left out when its test has not run. Stdlib only.
"""

from __future__ import annotations

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
