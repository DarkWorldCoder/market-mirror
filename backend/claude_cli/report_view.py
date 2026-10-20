"""
report_view.py - the plain-language report section (with the download bar in its header) and the
People cards for the dashboard. Stdlib only.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

try:  # stdlib only
    import ui  # type: ignore
except ImportError:  # pragma: no cover - imported as a package
    from . import ui  # type: ignore

_e, _t, _pill = ui.esc, ui.trunc, ui.pill

DL_LABELS = {
    "market_report.md": "Report (Markdown)", "action_plan.json": "Action plan (JSON)",
    "report.md": "Engine report (Markdown)", "survey_answers.csv": "Survey answers (CSV)",
    "segments.csv": "Results by audience (CSV)", "feed_test_sessions.csv": "Feed sessions (CSV)",
    "feed_test_creatives.csv": "Creatives + ROI (CSV)", "leads.csv": "Lead scores (CSV)",
    "analyst_panel.json": "Analyst panel (JSON)", "feed_story.json": "Social feed (JSON)",
    "summary.json": "All numbers (JSON)",
}


def download_bar(files: Dict[str, str]) -> str:
    btns = ['<button type="button" data-dl="__page__">This page (HTML)</button>',
            '<button type="button" data-print-report>Print report / PDF</button>']
    btns += [f'<button type="button" data-dl="{_e(n)}">{_e(DL_LABELS.get(n, n))}</button>' for n in files]
    # packed (zlib + base64, see ui.deflate_b64): the files are a third of the page otherwise
    payload = json.dumps({"enc": "deflate+base64", "files": {n: ui.deflate_b64(t) for n, t in files.items()}}).replace("<", "\\u003c")
    return (f'<div class="dl" role="group" aria-label="Downloads">{"".join(btns)}</div>'
            f'<script type="application/json" id="mm-files">{payload}</script>')


def report_section(mr: Optional[Dict[str, Any]], files: Dict[str, str], markdown_to_html,
                   insight: Optional[str] = None) -> Tuple[str, str, str]:
    """The report, download bar first. Without a generated report it still shows the downloads and a hint."""
    downloads = '<details class="report-downloads"><summary>Export report and data</summary>' + download_bar(files) + '</details>'
    head = ui.section_head("Report", "Findings from this run's saved artifacts. Simulated people, not real customers.",
                           insight, aside=ui.Raw(downloads))
    if not mr or not (mr.get("markdown") or "").strip():
        return ("report", "Report", head + '<div class="callout">No report yet. Run <code>mirofish.py report --simulation '
                '&lt;id&gt;</code> (or let <code>market-test</code> finish) to get the plain-language report here.</div>')
    body, toc = enhance_report(markdown_to_html(mr["markdown"]))
    method = mr.get("method")
    note = ('<p class="muted small">Data-only report: the writing step failed, so this is the facts without narrative.</p>'
            if method == "fallback" else "")
    contents = ""
    if len(toc) >= 3:
        contents = ('<nav class="rp-toc" aria-label="Report contents"><p>Contents</p>'
                    + "".join(f'<a href="#{rid}"><span>{i + 1:02d}</span>{label}</a>' for i, (rid, label) in enumerate(toc))
                    + "</nav>")
    return ("report", "Report", head + note
            + f'<div class="rp-doc{" has-toc" if contents else ""}">{contents}<article class="report mm-report">'
            '<p class="report-basis">Exploratory simulation · validate with a real experiment</p>'
            f'{body}</article></div>')


_H2 = re.compile(r"<h2>(.*?)</h2>", re.S)
_EXAMPLES = re.compile(r"<ul>\s*((?:<li>\s*Example:.*?</li>\s*){2,})</ul>", re.S)
_EXAMPLE = re.compile(r"<li>\s*Example:\s*(.*?)</li>", re.S)
_LEAD = re.compile(r"<p>\s*<strong>\s*Decision:\s*([A-Za-z\- ]+?)\.?\s*</strong>\s*(.*?)</p>", re.S)


def enhance_report(html: str) -> Tuple[str, List[Tuple[str, str]]]:
    """Report HTML -> (html, contents): ids on <h2>, the decision paragraph as a lead block with a verdict pill,
    runs of "Example: Name, age, ..." bullets as small person cards."""
    toc: List[Tuple[str, str]] = []

    def h2(m):
        label = m.group(1)
        rid = "rp-" + (re.sub(r"[^a-z0-9]+", "-", re.sub(r"<[^>]+>", "", label).lower()).strip("-") or str(len(toc)))
        toc.append((rid, label))
        return f'<h2 id="{rid}">{label}</h2>'
    html = _H2.sub(h2, html)

    def lead(m):
        verdict = m.group(1).strip()
        tone = {"GO": "mint", "ITERATE": "accent", "NO-GO": "orchid", "NO GO": "orchid", "STOP": "orchid"}.get(verdict.upper(), "accent")
        return (f'<div class="rp-lead"><span class="pill {tone}">{verdict.upper()}</span><p>{m.group(2).strip()}</p></div>')
    html = _LEAD.sub(lead, html, count=1)

    def people(m):
        cards = []
        for item in _EXAMPLE.findall(m.group(1)):
            text = item.strip()
            name, _, rest = text.partition(",")
            cards.append(f'<div class="rp-person"><span class="pm-av">{name.strip()[:1]}</span>'
                         f'<div><b>{name.strip()}</b><p>{rest.strip().lstrip(", ")}</p></div></div>')
        return '<div class="rp-people">' + "".join(cards) + "</div>"
    html = _EXAMPLES.sub(people, html)
    return html, toc


def _bde_inspector_drawer(r: Dict[str, Any], st: Optional[Dict[str, Any]] = None) -> str:
    """Expandable BDE decision profile & stateful episodic memory drawer for a persona."""
    bde = r.get("bde") if isinstance(r.get("bde"), dict) else {}
    loss = r.get("loss_aversion") or bde.get("loss_aversion")
    proof = r.get("social_proof_sensitivity") or bde.get("social_proof_sensitivity")
    loyalty = r.get("brand_loyalty") or bde.get("brand_loyalty")
    skep = r.get("skepticism") or bde.get("skepticism")
    budget = r.get("discretionary_budget") or bde.get("discretionary_budget")
    deals = r.get("dealbreakers") or bde.get("dealbreakers") or []
    constraints = r.get("hidden_constraints") or bde.get("hidden_constraints") or []
    payday = r.get("payday_status")
    life_stage = r.get("life_stage")
    st = st or {}
    mood = st.get("mood")
    energy = st.get("energy")
    trust_d = st.get("brand_trust_delta")
    fatigue = st.get("ad_fatigue")
    memory = st.get("episodic_memory") or []
    traj = st.get("trajectory") or []
    if not any([loss, proof, loyalty, skep, budget, deals, constraints, payday, life_stage, mood, memory, traj]):
        return ""
    rows = []
    if life_stage or payday:
        rows.append(("Life stage / wallet", " · ".join(str(x).replace("_", " ") for x in (life_stage, payday) if x)))
    if budget:
        rows.append(("Discretionary budget", str(budget)))
    psych = [f"{k}: {v}" for k, v in (("loss aversion", loss), ("social proof", proof), ("loyalty", loyalty), ("skepticism", skep)) if v]
    if psych:
        rows.append(("Decision profile", " · ".join(psych)))
    if deals:
        rows.append(("Dealbreakers", "; ".join(str(x) for x in deals[:4])))
    if constraints:
        rows.append(("Hidden constraints", "; ".join(str(x) for x in constraints[:3])))
    if mood or energy is not None or trust_d is not None:
        state_bits = []
        if mood:
            state_bits.append(f"mood: {mood}")
        if energy is not None:
            state_bits.append(f"energy: {float(energy):.0%}")
        if trust_d is not None:
            state_bits.append(f"trust Δ: {float(trust_d):+.2f}")
        if fatigue:
            state_bits.append(f"ad fatigue: {float(fatigue):.2f}")
        rows.append(("Live state", " · ".join(state_bits)))
    dl = '<dl class="person-d">' + "".join(f"<dt>{_e(k)}</dt><dd>{_e(v)}</dd>" for k, v in rows) + "</dl>"
    mem_html = ""
    if memory:
        mem_items = "".join(f"<li>{_e(_t(m, 140))}</li>" for m in memory[-4:])
        mem_html = f'<div class="bde-mem"><strong>Episodic memory</strong><ul>{mem_items}</ul></div>'
    return f'<details class="bde-drawer"><summary>Inspect BDE &amp; memory</summary>{dl}{mem_html}</details>'


def people_cards(index: List[Dict[str, Any]], activity: Dict[Any, int], survey_by_agent: Dict[Any, Dict[str, Any]],
                 leads: Dict[Any, int], limit: int = 150,
                 states_by_agent: Optional[Dict[Any, Dict[str, Any]]] = None) -> str:
    everyone = [r for r in index if r.get("kind") == "persona"]
    if len(everyone) > limit:            # big runs: the strongest leads first, the rest are in leads.csv
        everyone = sorted(everyone, key=lambda r: -(leads.get(r.get("agent_id")) if leads.get(r.get("agent_id")) is not None else -1))
    people = everyone[:limit]
    if not people:
        return ""
    states_by_agent = states_by_agent or {}
    cards = []
    crm_rows = []
    segments: Counter = Counter()
    countries: Counter = Counter()
    providers: Counter = Counter()
    has_grounded = False
    for i, r in enumerate(people):
        aid = r.get("agent_id")
        sv = survey_by_agent.get(aid) or {}
        st = states_by_agent.get(str(aid)) or states_by_agent.get(aid) or {}
        verdict = sv.get("would_convert")
        vcls = {"yes": "mint", "maybe": "accent", "no": "orchid"}.get(verdict, "")
        who = ", ".join(str(x) for x in (r.get("age"), r.get("city"), r.get("country")) if x)
        traits = [r.get("upbringing"), r.get("education"), r.get("income_level") or r.get("income"), r.get("thinking_style")]
        prov = str(r.get("model_provider") or "").strip().lower()
        provenance = "grounded" if r.get("provenance") == "real_intake" else "synthetic"
        if provenance == "grounded":
            has_grounded = True
        if r.get("segment"):
            segments[str(r["segment"])] += 1
        if r.get("country"):
            countries[str(r["country"])] += 1
        if prov:
            providers[prov] += 1
        extra_attrs = ""
        if prov:
            extra_attrs += f' data-provider="{_e(prov)}"'
        if provenance == "grounded":
            extra_attrs += ' data-provenance="grounded"'
        attrs = (f'data-item data-order="{i}" data-segment="{_e(r.get("segment") or "")}" data-country="{_e(r.get("country") or "")}" '
                 f'data-verdict="{_e(verdict or "none")}" data-lead="{leads[aid] if aid in leads else ""}"{extra_attrs}')
        prov_badge = (f'<span class="mm-provider-badge" data-prov="{_e(prov)}" title="{_e(r.get("model_name") or prov)}">{_e(prov)}</span>'
                      if prov else "")
        prov_pill = ('<span class="pill prov-pill-real" title="Grounded from real customer profile">Grounded</span>'
                     if provenance == "grounded" else "")
        life_pill = _pill(str(r["life_stage"]).replace("_", " ")) if r.get("life_stage") else ""
        drawer = _bde_inspector_drawer(r, st)
        cards.append(
            f'<div class="person" {attrs}><div class="person-h"><span class="pm-av">{_e(str(r.get("name") or "?")[:1])}</span>'
            f'<div><b>{_e(r.get("name"))}</b><div class="muted small">{_e(who)} · {_e(r.get("occupation") or "")}</div></div>'
            + prov_badge
            + (f'<span class="lead" title="Lead score 0-100">{leads[aid]}</span>' if aid in leads else "") + '</div>'
            f'<div class="person-pills">{_pill(r.get("segment"))}{prov_pill}{life_pill}'
            + "".join(_pill(l) for l in (r.get("languages") or [])[:2])
            + (_pill(f"would {verdict}", vcls) if verdict else "") + "</div>"
            + (f'<p class="person-q">“{_e(_t(r.get("interview_summary"), 320))}”</p>' if r.get("interview_summary") else "")
            + '<dl class="person-d">'
            + (f'<dt>Background</dt><dd>{_e("; ".join(str(t) for t in traits if t))}</dd>' if any(traits) else "")
            + (f'<dt>Phone</dt><dd>{_e(r.get("phone"))}{" · " + _e(r.get("data_plan")) if r.get("data_plan") else ""}</dd>' if r.get("phone") or r.get("data_plan") else "")
            + (f'<dt>Groups</dt><dd>{_e(", ".join(map(str, r.get("communities") or [])))}</dd>' if r.get("communities") else "")
            + (f'<dt>In the run</dt><dd>{activity.get(aid, 0)} actions</dd>' if activity else "")
            + (f'<dt>Objection</dt><dd>{_e(_t(sv.get("main_objection"), 140))}</dd>' if sv.get("main_objection") else "")
            + f'</dl>{drawer}</div>')
        crm_rows.append(
            f'<tr {attrs}>'
            f'<td><b>{_e(r.get("name"))}</b><div class="muted small">{_e(r.get("occupation") or "")}</div></td>'
            f'<td>{_pill(r.get("segment"))}{" " + prov_pill if prov_pill else ""}</td>'
            f'<td>{_e(who)}</td>'
            f'<td>{prov_badge or "–"}</td>'
            f'<td class="num">{leads[aid] if aid in leads else "–"}</td>'
            f'<td>{_pill(f"would {verdict}", vcls) if verdict else "–"}</td>'
            f'<td>{_e(r.get("discretionary_budget") or r.get("income_level") or "–")}</td>'
            f'<td class="small">{_e(_t(sv.get("main_objection") or r.get("interview_summary") or "", 110))}</td>'
            f'</tr>'
        )
    total = len([r for r in index if r.get("kind") == "persona"])
    note = (f'<p class="muted small">Showing the {len(people)} people with the highest lead scores of {total:,}. '
            'Everyone is in the leads.csv download.</p>' if total > len(people) else "")
    crm_table = (
        '<div data-panel="crm" data-panel-for="view" hidden>'
        '<div class="tbl tall"><table class="sortable crm-table"><thead><tr>'
        '<th data-sort="text" aria-sort="none" scope="col">Buyer</th>'
        '<th data-sort="text" aria-sort="none" scope="col">Segment</th>'
        '<th data-sort="text" aria-sort="none" scope="col">Location &amp; Age</th>'
        '<th data-sort="text" aria-sort="none" scope="col">Model</th>'
        '<th class="num" data-sort="num" aria-sort="none" scope="col">Lead score</th>'
        '<th data-sort="text" aria-sort="none" scope="col">Verdict</th>'
        '<th data-sort="text" aria-sort="none" scope="col">Budget / Income</th>'
        '<th data-sort="text" aria-sort="none" scope="col">Key Objection / Note</th>'
        f'</tr></thead><tbody>{"".join(crm_rows)}</tbody></table></div></div>'
    )
    return (people_filter_bar(segments, countries, bool(leads), any(survey_by_agent.values()), providers, has_grounded) + note
            + f'<div data-panel="cards" data-panel-for="view"><div class="people">{"".join(cards)}</div></div>'
            + crm_table + '</div>')


def people_filter_bar(segments: Dict[str, int], countries: Dict[str, int], has_leads: bool, has_survey: bool,
                      providers: Optional[Dict[str, int]] = None, has_grounded: bool = False) -> str:
    """Opens the people filter root (closed by people_cards): view switcher, text search, segment, country, provider, verdict, lead score."""
    def opts(c: Dict[str, int]) -> str:
        return "".join(f'<option value="{_e(k)}">{_e(k)} ({n})</option>' for k, n in sorted(c.items(), key=lambda x: (-x[1], x[0])))
    bar = [
        '<div class="filter-bar" role="group" aria-label="Filter people">',
        '<div class="crm-view-switch" role="group" aria-label="People view mode">'
        '<button type="button" data-view-tab="cards" aria-pressed="true">Cards</button>'
        '<button type="button" data-view-tab="crm" aria-pressed="false">CRM Table</button></div>',
        '<input type="text" data-filter="q" data-filter-op="contains" placeholder="Search buyer, city, objection…" aria-label="Search people">',
    ]
    if segments:
        bar.append(f'<select data-filter="segment" aria-label="Segment"><option value="">All segments</option>{opts(segments)}</select>')
    if countries:
        bar.append(f'<select data-filter="country" aria-label="Country"><option value="">All countries</option>{opts(countries)}</select>')
    if providers and len(providers) >= 1:
        bar.append(f'<select data-filter="provider" aria-label="Model provider"><option value="">All AI models</option>{opts(providers)}</select>')
    if has_grounded:
        bar.append('<select data-filter="provenance" aria-label="Provenance"><option value="">All provenance</option>'
                   '<option value="grounded">Grounded intake</option><option value="synthetic">Synthetic seeded</option></select>')
    if has_survey:
        bar.append('<select data-filter="verdict" aria-label="Survey verdict"><option value="">Any verdict</option>'
                   '<option value="yes">Would say yes</option><option value="maybe">Maybe</option><option value="no">Would say no</option>'
                   '<option value="none">No answer</option></select>')
    if has_leads:
        bar.append('<label>Lead score ≥ <input type="range" min="0" max="100" step="5" value="0" data-filter="lead" data-filter-op="min" '
                   'aria-label="Minimum lead score"> <output data-filter-out="lead">0</output></label>')
    bar.append('<span data-filter-count aria-live="polite"></span></div>')
    return '<div class="people-root" data-filter-root data-filter-noun="people">' + "".join(bar)


def leads_csv(index: List[Dict[str, Any]], survey_by_agent: Dict[Any, Dict[str, Any]], leads: Dict[Any, int]) -> str:
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["agent_id", "name", "segment", "country", "city", "age", "occupation", "model_provider", "provenance",
                "lead_score", "would_convert", "interest", "trust", "main_objection", "languages", "communities"])
    for r in index:
        if r.get("kind") != "persona":
            continue
        aid = r.get("agent_id")
        sv = survey_by_agent.get(aid) or {}
        w.writerow([aid, r.get("name"), r.get("segment"), r.get("country"), r.get("city"), r.get("age"), r.get("occupation"),
                    r.get("model_provider", ""), r.get("provenance", "llm_seeded"),
                    leads.get(aid, ""), sv.get("would_convert", ""), sv.get("interest", ""), sv.get("trust", ""),
                    sv.get("main_objection", ""), " / ".join(r.get("languages") or []), " / ".join(map(str, r.get("communities") or []))])
    return buf.getvalue()


def person_lead_score(sv: Dict[str, Any]) -> Optional[int]:
    """Per-person lead score from their own survey answer (SSR purchase mean if present, else yes/maybe/no)."""
    if not sv:
        return None
    ssr = ((sv.get("ssr") or {}).get("purchase") or {})
    if ssr.get("mean") is not None:
        intent = (float(ssr["mean"]) - 1) / 4 * 60
    else:
        intent = {"yes": 60, "maybe": 30, "no": 0}.get(sv.get("would_convert"), 15)
    trust = sv.get("trust")
    trust_pts = float(trust) / 10 * 25 if isinstance(trust, (int, float)) else 10
    click = {"yes": 15, "maybe": 7}.get(sv.get("would_click"), 0)
    return int(round(max(0, min(100, intent + trust_pts + click))))


REPORT_CSS = """
#report{background:transparent;border:0;border-radius:0;padding:22px 0}
#report .section-head .dl{justify-content:flex-end;max-width:620px}
.report-downloads{max-width:100%;font-size:13px}
.report-downloads summary{cursor:pointer;font-weight:500;list-style:none;display:inline-flex;align-items:center;gap:8px;height:40px;padding:0 18px;
border-radius:999px;background:var(--text);color:var(--surface)}
.report-downloads summary::-webkit-details-marker{display:none}
.report-downloads summary::after{content:"↓";font-size:12px}
.report-downloads[open] summary{margin-bottom:12px}
.rp-doc{display:block;background:var(--surface);border-radius:28px;padding:36px 40px 40px}
.rp-doc.has-toc{display:grid;grid-template-columns:220px minmax(0,1fr);gap:40px;align-items:start}
.rp-toc{position:sticky;top:96px;display:flex;flex-direction:column;gap:2px;font-size:13px}
.rp-toc p{margin:0 0 8px;color:var(--muted);font-size:12px}
.rp-toc a{display:flex;gap:10px;align-items:baseline;padding:7px 12px;border-radius:999px;color:var(--text-2);text-decoration:none;line-height:1.3}
.rp-toc a span{font-variant-numeric:tabular-nums;color:var(--muted);font-size:11px}
.rp-toc a:hover{background:var(--surface-2);color:var(--text)}
.report-basis{font-size:12px;color:var(--muted);margin:0 0 14px}
.mm-report{background:transparent;border:0;border-radius:0;padding:0;max-width:none;font-size:15px;line-height:1.7;overflow-wrap:anywhere;color:var(--text-2)}
.mm-report h1{font-size:clamp(1.8rem,3.2vw,2.6rem);font-weight:500;line-height:1.05;letter-spacing:-.04em;margin:0 0 22px;max-width:24ch;color:var(--text)}
.mm-report h2{font-size:1.35rem;font-weight:500;line-height:1.3;letter-spacing:-.025em;margin:44px 0 14px;padding:24px 0 0;border:0;
border-top:1px solid var(--grid);color:var(--text);scroll-margin-top:96px}
.mm-report h3{font-size:1rem;font-weight:600;margin:26px 0 10px;color:var(--text)}
.mm-report p,.mm-report ul,.mm-report ol,.mm-report blockquote{max-width:74ch}
.mm-report p{margin:0 0 16px}.mm-report li{margin:6px 0}.mm-report strong{font-weight:600;color:var(--text)}
.mm-report ul{padding-left:20px}.mm-report li::marker{color:var(--muted)}
.rp-lead{display:flex;gap:14px;align-items:flex-start;background:var(--mm-accent-wash);border-radius:20px;padding:18px 20px;margin:0 0 22px;max-width:none}
.rp-lead .pill{flex:none;margin-top:2px}
.rp-lead p{margin:0;font-size:16px;line-height:1.55;color:var(--text);max-width:none}
.mm-report table{font-size:13.5px;line-height:1.5;width:100%;border-collapse:separate;border-spacing:0;margin:20px 0;
border:1px solid var(--grid);border-radius:18px;overflow:hidden}
.mm-report th{background:var(--surface-2);text-align:left;font-weight:500;font-size:12px;color:var(--muted);white-space:nowrap;border-bottom:1px solid var(--grid)}
.mm-report td,.mm-report th{padding:11px 16px;vertical-align:top}
.mm-report td{border-bottom:1px solid var(--grid);color:var(--text-2)}
.mm-report tr:last-child td{border-bottom:0}
.mm-report td:first-child{color:var(--text);font-weight:500}
.mm-report blockquote{border:0;border-radius:16px;background:var(--surface-2);padding:14px 18px;margin:22px 0;color:var(--text-2);font-style:normal}
.mm-report pre{max-width:100%;overflow:auto}.mm-report hr{border:0;border-top:1px solid var(--grid);margin:32px 0}
.rp-people{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:10px;margin:18px 0 8px}
.rp-person{display:flex;gap:12px;align-items:flex-start;background:var(--surface-2);border-radius:18px;padding:12px 14px}
.rp-person .pm-av{flex:none;display:grid;place-items:center;width:34px;height:34px;border-radius:50%;background:var(--surface);color:var(--text);font-weight:600;font-size:13px}
.rp-person b{display:block;font-size:13.5px;color:var(--text)}
.rp-person p{margin:2px 0 0;font-size:12.5px;line-height:1.45;color:var(--text-2);max-width:none}
@media(max-width:1000px){.rp-doc.has-toc{display:block}.rp-toc{display:none}}
@media(max-width:700px){.rp-doc{padding:22px 18px;border-radius:22px}}
@media(max-width:700px){#report .section-head .dl{justify-content:flex-start}.report-downloads summary{text-align:left}.mm-report{padding:4px 0}.mm-report table{display:block;overflow-x:auto}.mm-report td,.mm-report th{min-width:110px}}
@media print{body.print-report{background:#fff;color:#111}body.print-report .wrap>*:not(#report){display:none!important}body.print-report #report{display:block;break-inside:auto;margin:0;padding:0;--text:#111;--text-2:#333;--muted:#555;--border:#bbb;--grid:#ddd}#report .report-downloads{display:none}.mm-report{color:#111;background:transparent}.mm-report h2,.mm-report h3{break-after:avoid}.mm-report tr,.mm-report blockquote{break-inside:avoid}.mm-report table{display:table;font-size:9pt}}
.people{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:12px}
.person{background:var(--surface-2);border:1px solid var(--border);border-radius:var(--r-lg);padding:14px 16px}
.person-h{display:flex;gap:10px;align-items:center}.person-h>div{flex:1;min-width:0}
.person .pm-av{width:38px;height:38px;flex-basis:38px;background:var(--surface);border:1px solid var(--border);color:var(--text)}
.lead{font-weight:600;background:var(--mm-accent);color:var(--mm-accent-ink);border-radius:999px;padding:3px 10px;font-size:.85rem}
.person-pills{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}
.person-q{font-size:.9rem;color:var(--text-2);margin:6px 0 8px;line-height:1.45}
.person-d{display:grid;grid-template-columns:auto 1fr;gap:3px 10px;font-size:.82rem;margin:0}
.person-d dt{color:var(--muted)}.person-d dd{margin:0}
.crm-view-switch{display:inline-flex;background:var(--surface-2);border:1px solid var(--border);border-radius:var(--r-pill);padding:2px}
.crm-view-switch button{font:inherit;font-size:.78rem;font-weight:550;border:0;background:transparent;color:var(--text-2);padding:4px 10px;border-radius:var(--r-pill);cursor:pointer}
.crm-view-switch button[aria-pressed="true"]{background:var(--text);color:var(--surface)}
.crm-table td{vertical-align:middle}
.bde-drawer{margin-top:8px;padding-top:8px;border-top:1px dashed var(--border)}
.bde-drawer summary{font-size:.78rem;font-weight:600;color:var(--text-2);cursor:pointer}
.bde-drawer .person-d{margin-top:6px}
.bde-mem{margin-top:6px;font-size:.78rem;color:var(--text-2)}
.bde-mem ul{margin:3px 0 0;padding-left:16px}
"""


# --------------------------------------------------------------------------
# Sales rehearsal (pitch.json) and test ideas (ideas.json)
# --------------------------------------------------------------------------

DL_LABELS.update({"pitch.json": "Sales rehearsal (JSON)", "ideas.md": "Test ideas (Markdown)",
                  "ideas.json": "Test ideas (JSON)", "thought_stream.json": "Agent mindstream (JSON)",
                  "gtm_suite.json": "Marketing & Sales GTM Suite (JSON)",
                  "competitor_intel.json": "Competitor Intelligence & AI Suggestions (JSON)",
                  "cro_lab.json": "CRO, What-If & Roleplay Lab (JSON)"})


def _mix_bar(m: Dict[str, Any]) -> str:
    y, mb, n = (float(m.get(k) or 0) for k in ("yes", "maybe", "no"))
    return (f'<div class="mixbar" role="img" aria-label="yes {y}%, maybe {mb}%, no {n}%" title="yes {y}% · maybe {mb}% · no {n}%">'
            f'<span class="yes" style="width:{y}%"></span><span class="maybe" style="width:{mb}%"></span>'
            f'<span class="no" style="width:{n}%"></span></div>')


def pitch_section(p: Optional[Dict[str, Any]], chart=None, insight: Optional[str] = None) -> Optional[Tuple[str, str, str]]:
    """'Sales rehearsal': how simulated buyers answered the pitch, which objections the rebuttals handled."""
    if not p or not p.get("answered"):
        return None
    before, after = p.get("verdict_before") or {}, p.get("verdict_after") or {}
    tiles = [("People pitched", p.get("answered")), ("Pitch score", f'{p.get("pitch_score")}/100'),
             ("Yes after rebuttals", f'{after.get("yes", 0)}%'), ("Maybe", f'{after.get("maybe", 0)}%'),
             ("Hot leads (55+)", len(p.get("hot_leads") or []))]
    tiles_html = "".join(ui.kpi(v, k, hl=(k == "Pitch score")) for k, v in tiles)
    obj_rows = "".join(
        f'<tr><td><b>{_e(o["type"])}</b><div class="small muted">{_e(_t("; ".join(x["text"] for x in o.get("examples") or []), 220))}</div></td>'
        f'<td class="num">{o["share"]}%<div class="small muted">{o["count"]}</div></td>'
        f'<td class="small">{_e(_t(o.get("rebuttal") or "no rebuttal given", 160))}</td>'
        f'<td class="num">{"–" if o.get("rebuttal_success") is None else str(o["rebuttal_success"]) + "%"}'
        f'<div class="small muted">{o.get("moved_yes", 0)} yes · {o.get("moved_partly", 0)} partly · {o.get("moved_no", 0)} no</div></td>'
        f'<td class="small">{_e(_t("; ".join(o.get("questions") or []), 180))}</td></tr>'
        for o in p.get("objections") or [] if o.get("type") != "none")
    seg_rows = "".join(
        f'<tr><td>{_e(s["segment"])}</td><td class="num">{s["n"]}</td><td>{_mix_bar(s)}</td>'
        f'<td class="num">{s["lead_score"]}</td><td>{_e(s.get("top_objection") or "–")}</td></tr>' for s in p.get("by_segment") or [])
    hot = "".join(f'<tr><td><b>{_e(h["name"])}</b><div class="small muted">{_e(h.get("segment"))}</div></td><td class="num">{h["lead_score"]}</td>'
                  f'<td>{_e(h.get("verdict"))}</td><td class="small">{_e(_t(h.get("next_step") or "", 80))}</td>'
                  f'<td class="small">{_e(_t(h.get("reach") or "", 100))}</td></tr>' for h in p.get("hot_leads") or [])
    quotes = "".join(f'<blockquote class="voice"><p>{_e(q["text"])}</p><footer>{_e(q["name"])} · {_e(q.get("segment"))}</footer></blockquote>'
                     for q in (p.get("best_replies") or [])[:2] + (p.get("worst_replies") or [])[:2])
    fixes = "".join(f"<li>{_e(f)}</li>" for f in p.get("fixes") or [])
    intro = ('Every simulated buyer heard the pitch' + (f" (as a {p.get('channel')})" if p.get("channel") else "")
             + f'; those who hesitated heard the rebuttal written for their objection. {p.get("rebuttals_given", 0)} rebuttals given. '
             'Scores are directions, not measurements.')
    html = (ui.section_head("Sales rehearsal", intro, insight)
            + f'<div class="kpis auto">{tiles_html}</div>'
            f'<div class="card"><h3>Before and after the rebuttals</h3><div class="mixbars"><div><div class="small muted">After the pitch</div>{_mix_bar(before)}</div>'
            f'<div><div class="small muted">After the rebuttals</div>{_mix_bar(after)}</div></div>'
            '<div class="legend"><span><i class="i-yes"></i>yes</span><span><i class="i-maybe"></i>maybe</span><span><i class="i-no"></i>no</span></div></div>'
            + (f'<div class="card"><h3>Fix in the pitch first</h3><ul>{fixes}</ul></div>' if fixes else "")
            + (f'<div class="card"><h3>Objections and how the rebuttals did</h3><div class="tbl"><table class="sortable"><thead><tr><th>Objection</th><th class="num">Share</th>'
               f'<th>Rebuttal used</th><th class="num">Moved them</th><th>Questions they asked back</th></tr></thead><tbody>{obj_rows}</tbody></table></div></div>' if obj_rows else "")
            + (f'<div class="card"><h3>By audience</h3><div class="tbl"><table class="sortable"><thead><tr><th>Audience</th><th class="num">n</th><th>Yes / maybe / no</th>'
               f'<th class="num">Lead score</th><th>Top objection</th></tr></thead><tbody>{seg_rows}</tbody></table></div></div>' if seg_rows else "")
            + (f'<div class="card"><h3>Call these first</h3><div class="tbl"><table class="sortable"><thead><tr><th>Who</th><th class="num">Lead score</th><th>Verdict</th>'
               f'<th>Agreed to</th><th>Reach them</th></tr></thead><tbody>{hot}</tbody></table></div></div>' if hot else "")
            + (f'<div class="card"><h3>In their words</h3><div class="voices">{quotes}</div></div>' if quotes else "")
            + f'<details class="card"><summary>The pitch that was tested</summary><pre class="script">{_e(p.get("script") or "")}</pre></details>')
    return ("pitch", "Sales rehearsal", html)


def ideas_section(ideas: Optional[Dict[str, Any]], insight: Optional[str] = None) -> Optional[Tuple[str, str, str]]:
    """'Test ideas': the next experiments proposed from real ads and the run, each citing its evidence."""
    if not ideas or not ideas.get("ideas"):
        return None
    cards = []
    for i, idea in enumerate(ideas["ideas"], 1):
        how = idea.get("how_to_test") or {}
        cards.append(
            f'<div class="play idea"><div class="play-h"><strong>{i}. {_e(idea["title"])}</strong>'
            f'<span class="pill {"mint" if idea.get("priority") == "high" else ""}">{_e(idea.get("priority"))}</span><span class="pill">{_e(idea.get("type"))}</span></div>'
            f'<p><b>If</b> {_e(idea.get("hypothesis"))}</p><dl>'
            f'<dt>Make</dt><dd>{_e(idea.get("what_to_make"))}</dd>'
            f'<dt>Where</dt><dd>{_e(idea.get("audience") or "–")} · {_e(idea.get("platform") or "–")} · {_e(idea.get("budget") or "small budget")} · {_e(idea.get("duration") or "")}</dd>'
            f'<dt>Decide by</dt><dd>{_e(idea.get("metric") or "–")}: {_e(idea.get("success_looks_like") or "–")}</dd>'
            f'<dt>Evidence</dt><dd><ul class="small">{"".join(f"<li>{_e(e)}</li>" for e in idea.get("evidence") or [])}</ul></dd>'
            + (f'<dt>Simulate first</dt><dd class="small"><code>{_e(how.get("tool"))}</code> {_e(_t(json.dumps(how.get("config") or {}, ensure_ascii=False), 200))}</dd>' if how else "")
            + '</dl></div>')
    ev = ideas.get("evidence") or {}
    src = ", ".join(ev.get("sources") or [])
    intro = (f'{len(cards)} next tests proposed from {len(ev.get("signals") or [])} pieces of evidence'
             + (f' ({src})' if src else "") + '. Every idea cites the evidence it comes from; run the cheap simulation first, then spend.')
    html = ui.section_head("Test ideas", intro, insight) + f'<div class="plays">{"".join(cards)}</div>'
    return ("ideas", "Test ideas", html)


def _gut_tag(text: str) -> str:
    low = text.lower()
    if any(w in low for w in ("scam", "fake", "catch", "trap", "doubt", "suspicious", "skeptic", "sceptic")):
        return "skeptical"
    if any(w in low for w in ("expensive", "price", "cost", "afford", "tight", "budget", "paisa", "rupees", "npr", "$")):
        return "price_shock"
    if any(w in low for w in ("again", "spam", "tired", "annoying", "hide")):
        return "ad_fatigue"
    if any(w in low for w in ("friend", "comments", "reviews", "sister", "wife", "husband", "group")):
        return "social_proof"
    if any(w in low for w in ("no card", "offline", "verified", "legit", "safe")):
        return "trust_signal"
    if any(w in low for w in ("interesting", "useful", "try", "check", "nice", "good", "helpful")):
        return "curious"
    return "habitual_ignore"


def _roadblock_tag(text: str, gate: str = "") -> str:
    low = f"{text} {gate}".lower()
    if gate == "wallet_limit" or any(w in low for w in ("exceeds", "budget", "afford", "expensive", "price", "paisa", "tight")):
        return "price_vs_wallet"
    if any(w in low for w in ("card", "auto-renew", "autorenew", "subscription", "charged")):
        return "card_trap_fear"
    if any(w in low for w in ("scam", "fake", "trust", "spam", "agent")):
        return "scam_skepticism"
    if any(w in low for w in ("ask my", "wife", "husband", "parents", "sister", "family")):
        return "family_approval_needed"
    if gate in ("network_timeout", "form_abandon") or any(w in low for w in ("phone", "slow", "load", "form")):
        return "page_or_form_friction"
    return "none"


def thoughts_section(bundle: Dict[str, Any], insight: Optional[str] = None) -> Optional[Tuple[str, str, str]]:
    """'Agent thoughts & mindstream': System 1 gut monologue, System 2 BDE/wallet deliberation,
    and private-thought vs public-action divergence across touchpoints."""
    if not isinstance(bundle, dict):
        return None
    cfg = bundle.get("config") if isinstance(bundle.get("config"), dict) else {}
    index = {
        int(r["agent_id"]): r
        for r in (cfg.get("persona_index") or [])
        if isinstance(r, dict) and r.get("agent_id") is not None
    }
    entries: List[Dict[str, Any]] = []

    def _meta(aid: Any, name: str = "", seg: str = "", country: str = "", prov: str = "") -> Dict[str, Any]:
        try:
            aid_i = int(aid) if aid is not None else -1
        except (TypeError, ValueError):
            aid_i = -1
        p = index.get(aid_i) or {}
        bde = p.get("bde") if isinstance(p.get("bde"), dict) else {}
        return {
            "agent_id": aid_i,
            "name": p.get("name") or name or f"Agent {aid}",
            "segment": p.get("segment") or seg or "",
            "country": p.get("country") or country or "",
            "model_provider": str(prov or p.get("model_provider") or "claude").lower(),
            "bde": bde,
        }

    # 1. Dedicated thought_stream.json
    ts = bundle.get("thought_stream")
    if isinstance(ts, dict):
        for r in ts.get("entries") or []:
            if not isinstance(r, dict) or not r.get("thought"):
                continue
            m = _meta(r.get("agent_id"), r.get("name", ""), r.get("segment", ""), r.get("country", ""), r.get("model_provider", ""))
            th = str(r.get("thought") or "").strip()
            s2 = str(r.get("system2_deliberation") or "").strip()
            pub = str(r.get("public_action") or "Evaluated stimulus").strip()
            gut = str(r.get("system1_gut") or _gut_tag(th))
            rb = str(r.get("mental_roadblock") or _roadblock_tag(th + " " + s2))
            entries.append({
                **m, "touchpoint": "thought_lab", "stimulus": str(r.get("stimulus") or ts.get("stimulus") or "Stimulus"),
                "thought": th, "system2": s2, "public_action": pub, "gut": gut, "roadblock": rb,
                "diverged": bool(r.get("diverged")),
            })

    # 2. Feed test scroll & landing thoughts
    ft = bundle.get("feed_test")
    if isinstance(ft, dict):
        for s in (ft.get("sessions") or [])[:120]:
            if not isinstance(s, dict):
                continue
            ad = s.get("ad") or {}
            th = str(ad.get("thought") or "").strip()
            cid = str(s.get("creative_id") or "ad")
            m = _meta(s.get("agent_id"), s.get("name", ""), s.get("segment", ""), s.get("country", ""), s.get("model_provider", ""))
            ev = (m["bde"].get("evaluation") or {}) if isinstance(m.get("bde"), dict) else {}
            if th and th.lower() != "scroll":
                clicked = bool(ad.get("click"))
                stopped = bool(ad.get("stopped"))
                pub = f"Clicked {cid}" if clicked else (f"Paused {ad.get('dwell', 2)}s, scrolled past" if stopped else "Scrolled past")
                gut = _gut_tag(th + " " + pub)
                rb = _roadblock_tag(th)
                entries.append({
                    **m, "touchpoint": "ad_scroll", "stimulus": f"{s.get('platform', 'Feed').title()} · {cid}",
                    "thought": th,
                    "system2": f"Discretionary budget: {ev.get('monthly_discretionary', 'standard')} · Dealbreakers: {', '.join(ev.get('dealbreakers') or ['none'])}",
                    "public_action": pub, "gut": gut, "roadblock": rb,
                    "diverged": (gut == "curious" and not clicked) or (clicked and not bool((s.get("landing") or {}).get("completed", True))),
                })
            land = s.get("landing") or {}
            lth = str(land.get("thought") or land.get("drop_reason") or "").strip()
            if lth:
                conv = bool(land.get("completed"))
                gate = str(land.get("friction_gate") or ("completed" if conv else "form_abandon"))
                drop = str(land.get("drop_reason") or "")
                entries.append({
                    **m, "touchpoint": "landing_page", "stimulus": f"Landing page · {cid}",
                    "thought": lth, "system2": drop or f"Gate: {gate}",
                    "public_action": "Completed form (Converted)" if conv else f"Dropped ({gate})",
                    "gut": "trust_signal" if conv else _gut_tag(lth + " " + drop),
                    "roadblock": "none" if conv else _roadblock_tag(lth + " " + drop, gate),
                    "diverged": not conv,
                })

    # 3. Pitch thoughts
    pitch = bundle.get("pitch")
    if isinstance(pitch, dict):
        for p in (pitch.get("people") or [])[:80]:
            if not isinstance(p, dict):
                continue
            t1 = p.get("turn1") or {}
            t2 = p.get("turn2") or {}
            th = str(t2.get("thought") or t1.get("thought") or t1.get("objection") or "").strip()
            rep = str(t2.get("reply") or t1.get("reply") or "").strip()
            if not th and not rep:
                continue
            m = _meta(p.get("agent_id"), p.get("name", ""), p.get("segment", ""), p.get("country", ""), p.get("model_provider", ""))
            verdict = str(p.get("final_verdict") or "maybe").lower()
            inner = th or f"Weighing offer: {rep[:120]}"
            entries.append({
                **m, "touchpoint": "sales_pitch", "stimulus": "1-on-1 Sales Pitch",
                "thought": inner, "system2": str(t1.get("objection") or "Evaluated rebuttal"),
                "public_action": f'Verdict {verdict.upper()}: "{_t(rep, 80)}"',
                "gut": _gut_tag(inner + " " + rep),
                "roadblock": _roadblock_tag(inner + " " + str(t1.get("objection") or "")),
                "diverged": verdict == "maybe",
            })

    # 4. Social actions with explicit recorded thoughts
    for act in (bundle.get("actions") or [])[:80]:
        if not isinstance(act, dict) or not act.get("thought"):
            continue
        m = _meta(act.get("agent_id"), act.get("agent_name", ""))
        th = str(act.get("thought") or "").strip()
        atype = str(act.get("action_type") or "ACTION")
        entries.append({
            **m, "touchpoint": "social_feed", "stimulus": f"Round {act.get('round', '?')}",
            "thought": th, "system2": f"Mood: {act.get('mood', 'neutral')}",
            "public_action": atype, "gut": _gut_tag(th), "roadblock": _roadblock_tag(th),
            "diverged": atype == "DO_NOTHING" and "curious" in th.lower(),
        })

    if not entries:
        return None

    from collections import Counter
    guts = Counter(e["gut"] for e in entries)
    rbs = Counter(e["roadblock"] for e in entries if e["roadblock"] != "none")
    div_cnt = sum(1 for e in entries if e["diverged"])
    div_pct = round(100.0 * div_cnt / len(entries), 1)
    top_gut = (guts.most_common(1)[0][0] if guts else "neutral").replace("_", " ")
    top_rb = (rbs.most_common(1)[0][0] if rbs else "none").replace("_", " ")

    kpis_html = '<div class="kpis auto">' + "".join([
        ui.kpi(str(len(entries)), "Thoughts captured", f'{len({e["name"] for e in entries})} agents across touchpoints'),
        ui.kpi(f"{div_pct:g}%", "Say-vs-Do divergence", f"{div_cnt} thought privately vs acted differently", hl=True),
        ui.kpi(top_gut.title(), "Dominant System-1 gut", "Fast emotional/attentional impulse"),
        ui.kpi(top_rb.title(), "Top System-2 roadblock", "Primary BDE / wallet / trust blocker"),
    ]) + "</div>"

    touchpoints = list(dict.fromkeys(e["touchpoint"] for e in entries))
    segs = list(dict.fromkeys(e["segment"] for e in entries if e["segment"]))
    provs = list(dict.fromkeys(e["model_provider"] for e in entries if e["model_provider"]))

    bar = [
        '<div class="filter-bar" role="group" aria-label="Filter thoughts">',
        '<input type="text" data-filter="q" data-filter-op="contains" placeholder="Filter monologue, blocker, name…" aria-label="Search thoughts">',
        '<select data-filter="touchpoint" aria-label="Touchpoint"><option value="">All touchpoints</option>'
        + "".join(f'<option value="{_e(t)}">{_e(t.replace("_", " ").title())}</option>' for t in touchpoints)
        + '</select>',
    ]
    if len(segs) > 1:
        bar.append('<select data-filter="segment" aria-label="Segment"><option value="">All segments</option>'
                   + "".join(f'<option value="{_e(s)}">{_e(s)}</option>' for s in segs) + '</select>')
    bar.append('<select data-filter="diverged" aria-label="Say-vs-Do"><option value="">Any alignment</option>'
               '<option value="yes">Diverged only</option><option value="no">Aligned</option></select>')
    if len(provs) > 1:
        bar.append('<select data-filter="provider" aria-label="AI Model"><option value="">All AI models</option>'
                   + "".join(f'<option value="{_e(p)}">{_e(p.upper())}</option>' for p in provs) + '</select>')
    bar.append('<span data-filter-count aria-live="polite"></span></div>')

    cards = []
    for idx, e in enumerate(entries[:120]):
        q_blob = f"{e['name']} {e['segment']} {e['thought']} {e['system2']} {e['public_action']} {e['gut']} {e['roadblock']}".lower()
        div_flag = "yes" if e["diverged"] else "no"
        prov_badge = f'<span class="mm-provider-badge" data-prov="{_e(e["model_provider"])}">{_e(e["model_provider"])}</span>'
        div_pill = '<span class="pill stop">Say-vs-Do gap</span>' if e["diverged"] else ""
        rb_pill = f'<span class="pill iterate">Blocker: {_e(e["roadblock"].replace("_", " "))}</span>' if e["roadblock"] != "none" else ""
        cards.append(
            f'<div class="thought-card" data-item data-order="{idx}" data-touchpoint="{_e(e["touchpoint"])}" '
            f'data-segment="{_e(e["segment"])}" data-diverged="{div_flag}" data-provider="{_e(e["model_provider"])}" '
            f'data-q="{_e(q_blob)}">'
            f'<div class="person-h"><span class="pm-av">{_e(str(e["name"] or "?")[:1])}</span><div><b>{_e(e["name"])}</b>'
            f'<div class="small muted">{_e(" · ".join(x for x in (e["segment"], e["country"], e["stimulus"]) if x))}</div></div>'
            f'{prov_badge}</div>'
            f'<div class="person-pills">'
            f'<span class="pill">{_e(e["touchpoint"].replace("_", " "))}</span>'
            f'<span class="pill">System 1: {_e(e["gut"].replace("_", " "))}</span>'
            f'{rb_pill}{div_pill}</div>'
            f'<div class="th-box"><span class="th-lbl">💭 Private Inner Monologue</span><p>“{_e(_t(e["thought"], 260))}”</p></div>'
            + (f'<div class="th-sys2"><b>🧠 System 2 BDE Check:</b> {_e(_t(e["system2"], 180))}</div>' if e["system2"] else "")
            + f'<div class="th-act"><b>⚡ Public Action:</b> {_e(_t(e["public_action"], 140))}</div>'
            f'</div>'
        )

    intro = (
        "Real first-person cognitive stream of simulated buyers across ad feeds, landing pages, sales pitches, and social feeds: "
        "comparing their fast System-1 gut reaction and System-2 BDE wallet/dealbreaker check against what they publicly did."
    )
    body = (
        ui.section_head("Agent thoughts & mindstream", intro, insight)
        + kpis_html
        + f'<div data-filter-root data-filter-noun="thoughts">'
        + "".join(bar)
        + f'<div class="people">{"".join(cards)}</div></div>'
    )
    return ("thoughts", "Agent thoughts", body)


def gtm_section(bundle: Dict[str, Any], insight: Optional[str] = None) -> Optional[Tuple[str, str, str]]:
    """'Marketing & Sales GTM Hub': Buying Committee Simulator, Auto-Iteration Creative Optimizer,
    Pricing & Packaging Conjoint, 30-Day Multi-Touch Journey/LTV, and Sales Battlecards & Outbound Sequences."""
    if not isinstance(bundle, dict):
        return None
    suite = bundle.get("gtm_suite") if isinstance(bundle.get("gtm_suite"), dict) else {}
    bc = suite.get("buying_committee") or bundle.get("buying_committee")
    co = suite.get("creative_optimizer") or bundle.get("creative_optimizer")
    sb = suite.get("sales_battlecard") or bundle.get("sales_battlecard")
    js = suite.get("journey_simulation") or bundle.get("journey_sim")
    pc = suite.get("pricing_conjoint") or bundle.get("pricing_conjoint")
    if not any(isinstance(x, dict) and x for x in (bc, co, sb, js, pc)):
        return None

    kpis = []
    if isinstance(bc, dict):
        kpis.append(ui.kpi(f"{bc.get('win_rate_pct', 0):g}%", "Buying unit win rate",
                           f"{bc.get('committee_count', 0)} {bc.get('mode', 'group')} committees simulated", hl=True))
    if isinstance(co, dict) and isinstance(co.get("lift"), dict):
        lift = co["lift"]
        kpis.append(ui.kpi(f"+{lift.get('ctr_delta_pts', 0):g} pts", "Auto-optimized CTR lift",
                           f"Conv +{lift.get('conversion_delta_pts', 0):g} pts · Say-vs-Do −{lift.get('say_do_gap_reduction_pts', 0):g} pts"))
    if isinstance(js, dict) and isinstance(js.get("unit_economics"), dict):
        ue = js["unit_economics"]
        kpis.append(ui.kpi(f"{ue.get('ltv_cac_ratio', 0):g}x", "30-Day LTV : CAC",
                           f"Retained {ue.get('day30_retention_pct', 0):g}% · Viral K={ue.get('viral_k_factor', 0):g}"))
    if isinstance(pc, dict):
        kpis.append(ui.kpi(str(pc.get("revenue_maximizing_tier") or "Starter"), "Top LTV package",
                           f"Best adoption: {pc.get('adoption_maximizing_tier') or 'No-Card Pass'}"))
    kpis_html = f'<div class="kpis auto">{"".join(kpis)}</div>' if kpis else ""

    parts: List[str] = []

    # 1. Auto-Iteration Creative Optimizer
    if isinstance(co, dict) and co.get("generations"):
        gen_rows = "".join(
            f"<tr><td><b>Gen {g.get('generation')}</b></td>"
            f"<td><b>{_e((g.get('creative') or {}).get('headline'))}</b>"
            f"<div class='small muted'>{_e(_t((g.get('creative') or {}).get('text'), 130))}</div>"
            + (f"<div class='small'><i>Fix: {_e((g.get('creative') or {}).get('fix_applied'))}</i></div>" if (g.get("creative") or {}).get("fix_applied") else "")
            + f"</td><td>{_pill((g.get('creative') or {}).get('cta'))}</td>"
            f"<td class='num'>{g.get('thumb_stop_pct', 0)}%</td>"
            f"<td class='num'><b>{g.get('ctr_pct', 0)}%</b></td>"
            f"<td class='num'><b>{g.get('conversion_pct', 0)}%</b></td>"
            f"<td class='num'>{g.get('say_do_gap_pct', 0)}%</td>"
            f"<td>{_pill(str(g.get('top_roadblock') or 'none').replace('_', ' '))}</td></tr>"
            for g in co.get("generations") or []
        )
        parts.append(
            '<div class="card"><h3>1. Closed-Loop Creative &amp; Copy Auto-Optimizer</h3>'
            '<p class="small muted">Automatically diagnoses System-1 gut failures and System-2 BDE roadblocks from Gen 1, rewrites challenger copy, and re-tests on the same buyer cohort.</p>'
            '<div class="tbl"><table class="sortable"><thead><tr>'
            '<th>Gen</th><th>Headline &amp; Copy</th><th>CTA</th><th class="num">Thumb-Stop</th>'
            '<th class="num">CTR</th><th class="num">Conversion</th><th class="num">Say-vs-Do Gap</th><th>Primary Blocker</th>'
            f'</tr></thead><tbody>{gen_rows}</tbody></table></div></div>'
        )

    # 2. Pricing & Packaging Conjoint
    if isinstance(pc, dict) and pc.get("tiers"):
        cur = str(pc.get("currency") or "USD")
        t_rows = "".join(
            f"<tr><td><b>{_e(t.get('name'))}</b><div class='small muted'>{_e(t.get('description'))}</div></td>"
            f"<td class='num'>{_e(cur)} {t.get('price', 0):g}</td>"
            f"<td>{_pill('Card upfront', 'stop') if t.get('requires_card_upfront') else _pill('No card upfront', 'mint')}</td>"
            f"<td class='num'>{t.get('signup_rate_pct', 0)}%</td>"
            f"<td class='num'>{t.get('card_drop_off_pct', 0)}%</td>"
            f"<td class='num'><b>{t.get('paid_take_rate_pct', 0)}%</b></td>"
            f"<td class='num'>{t.get('day30_retained_pct', 0)}%</td>"
            f"<td class='num'><b>{_e(cur)} {t.get('90d_ltv_per_1000_visitors', 0):,.0f}</b></td></tr>"
            for t in pc.get("tiers") or []
        )
        rec = pc.get("packaging_recommendation")
        parts.append(
            '<div class="card"><h3>2. Pricing &amp; Packaging Conjoint Simulator</h3>'
            + (f'<div class="callout">{_e(rec)}</div>' if rec else "")
            + '<div class="tbl"><table class="sortable"><thead><tr>'
            '<th>Package / Tier</th><th class="num">Price</th><th>Card Gate</th><th class="num">Signup %</th>'
            '<th class="num">Card Drop-off</th><th class="num">Paid Take Rate</th><th class="num">Day-30 Retained</th><th class="num">90d LTV / 1k Visitors</th>'
            f'</tr></thead><tbody>{t_rows}</tbody></table></div></div>'
        )

    # 3. 30-Day Longitudinal Journey, Attribution & Unit Economics
    if isinstance(js, dict) and js.get("funnel_stages"):
        f_rows = "".join(
            f"<tr><td><b>{_e(st.get('stage'))}</b></td><td class='num'>{st.get('count', 0)}</td><td class='num'><b>{st.get('rate_pct', 0)}%</b></td></tr>"
            for st in js.get("funnel_stages") or []
        )
        a_rows = "".join(
            f"<tr><td><b>{_e(a.get('channel'))}</b></td><td class='num'>{a.get('first_touch_pct', 0)}%</td>"
            f"<td class='num'>{a.get('last_touch_pct', 0)}%</td><td class='num'><b>{a.get('multi_touch_share_pct', 0)}%</b></td></tr>"
            for a in js.get("attribution") or []
        )
        ue = js.get("unit_economics") or {}
        cur = str(ue.get("currency") or "USD")
        parts.append(
            '<div class="card"><h3>3. Full-Funnel 30-Day Customer Journey, LTV/CAC &amp; Attribution</h3>'
            f'<p class="small muted">Tracks {js.get("cohort_size", 0)} simulated buyers from cold ad scroll through retargeting, WhatsApp/email nurture, checkout, Day-30 retention, and referral. '
            f'Estimated CAC: <b>{_e(cur)} {ue.get("cac", 0)}</b> · LTV: <b>{_e(cur)} {ue.get("ltv", 0)}</b> · Payback: <b>{ue.get("payback_months", 0)} mo</b>.</p>'
            '<div class="mixbars">'
            '<div><h4>6-Stage Longitudinal Funnel</h4><div class="tbl"><table><thead><tr><th>Lifecycle Stage</th><th class="num">Buyers</th><th class="num">Share</th></tr></thead>'
            f'<tbody>{f_rows}</tbody></table></div></div>'
            '<div><h4>Multi-Touch Revenue Attribution</h4><div class="tbl"><table><thead><tr><th>Channel</th><th class="num">First-Touch</th><th class="num">Last-Touch</th><th class="num">Multi-Touch</th></tr></thead>'
            f'<tbody>{a_rows}</tbody></table></div></div>'
            '</div></div>'
        )

    # 4. Buying Committee & Multi-Stakeholder Deal Simulator
    if isinstance(bc, dict) and bc.get("committees"):
        c_cards = []
        for c in (bc.get("committees") or [])[:6]:
            out = str(c.get("outcome") or "stalled").upper()
            p_cls = "mint" if "APPROV" in out else ("accent" if "PILOT" in out else "stop")
            lines = "".join(
                f"<div class='th-sys2'><b>{_e(t.get('role'))} ({_e(t.get('speaker'))}):</b> “{_e(_t(t.get('text'), 150))}” "
                f"<span class='muted small'>[Private: {_e(_t(t.get('private_thought'), 100))}]</span></div>"
                for t in (c.get("room_transcript") or [])
            )
            c_cards.append(
                f'<div class="thought-card">'
                f'<div class="person-h"><div><b>{_e(c.get("unit_label"))}</b>'
                f'<div class="small muted">Consensus: {c.get("consensus_score", 0)}/10 · Blocker: {_e(c.get("primary_blocker"))}</div></div>'
                f'<span class="pill {p_cls}">{_e(out)}</span></div>'
                f'{lines}'
                f'<div class="th-act"><b>🎯 How to win unit:</b> {_e(c.get("how_to_win_unit"))}</div>'
                f'</div>'
            )
        parts.append(
            '<div class="card"><h3>4. Buying Committee &amp; Household Decision Simulator</h3>'
            '<p class="small muted">Simulates what happens behind closed doors when the Champion, Wallet Holder / Economic Buyer, Peer Evaluator, and Skeptical Blocker debate the purchase together.</p>'
            f'<div class="people">{"".join(c_cards)}</div></div>'
        )

    # 5. Sales Battlecards, Objection Matrix & Outbound Sequences
    if isinstance(sb, dict):
        obj_rows = "".join(
            f"<tr><td><b>{_e(str(o.get('objection_type') or '').replace('_', ' ').title())}</b></td>"
            f"<td class='small'>{_e(o.get('what_buyer_says'))}</td>"
            f"<td class='small muted'>{_e(o.get('private_system2_thought'))}</td>"
            f"<td class='small'>{_e(o.get('worst_seller_response'))}</td>"
            f"<td class='small'><b>{_e(o.get('winning_rebuttal'))}</b></td></tr>"
            for o in (sb.get("objection_playbook") or [])
        )
        seq_cards = []
        for seq in (sb.get("outbound_sequences") or [])[:2]:
            steps_html = "".join(
                f"<div class='th-sys2'><b>Step {s.get('step')} (Day {s.get('day')} · {_e(s.get('channel'))}):</b> {_e(s.get('message'))}</div>"
                for s in (seq.get("steps") or [])
            )
            seq_cards.append(
                f'<div class="thought-card"><b>Outbound Sequence · {_e(seq.get("segment"))}</b>'
                f'<div class="small muted">Channels: {_e(" → ".join(seq.get("best_channel_order") or []))}</div>'
                f'{steps_html}</div>'
            )
        parts.append(
            '<div class="card"><h3>5. Sales Battlecard, Objection Matrix &amp; Multi-Channel Outbound Kit</h3>'
            '<div class="tbl"><table><thead><tr><th>Objection</th><th>What Buyer Says</th><th>Private System-2 Thought</th>'
            '<th>Worst Response (Avoid)</th><th>Winning Word-for-Word Rebuttal</th></tr></thead>'
            f'<tbody>{obj_rows}</tbody></table></div>'
            + (f'<div class="people" style="margin-top:12px">{"".join(seq_cards)}</div>' if seq_cards else "")
            + '</div>'
        )

    intro = (
        "Full-funnel Marketing & Sales Go-To-Market (GTM) simulation suite: closed-loop creative optimization, "
        "pricing & packaging conjoint, 30-day journey attribution & LTV/CAC, multi-stakeholder buying committees, and sales battlecards."
    )
    body = ui.section_head("Marketing & sales GTM hub", intro, insight) + kpis_html + "".join(parts)
    return ("gtm", "GTM & sales hub", body)


def competitor_section(bundle: Dict[str, Any], insight: Optional[str] = None) -> Optional[Tuple[str, str, str]]:
    """'Competitor & AI strategy': Multi-agent competitor bake-off, 'What Competitors Have vs What We Have'
    feature gap matrix, AI strategic product/pricing/marketing suggestions, and war-game counter-moves."""
    if not isinstance(bundle, dict):
        return None
    suite = bundle.get("gtm_suite") if isinstance(bundle.get("gtm_suite"), dict) else {}
    ci = bundle.get("competitor_intel") or suite.get("competitor_intelligence")
    if not isinstance(ci, dict) or not ci:
        return None

    cur_win = ci.get("current_brand_win_share_pct", 0)
    upg_win = ci.get("projected_win_share_after_ai_adds_pct", 0)
    lift = ci.get("win_share_lift_pts", 0)
    top_comp = str(ci.get("top_competitor_threat") or "Status Quo")
    sugs = ci.get("ai_suggestions") or []
    top_sug = sugs[0]["title"] if sugs else "No-Card 7-Day Pass"

    kpis_html = '<div class="kpis auto">' + "".join([
        ui.kpi(f"{cur_win:g}% → {upg_win:g}%", "Simulated brand win share", f"+{lift:g} pts after adding AI recommendations", hl=True),
        ui.kpi(_t(top_comp, 28), "#1 Competitor threat", f"{ci.get('top_competitor_share_pct', 0):g}% current buyer preference"),
        ui.kpi(str(len(sugs)), "AI strategic suggestions", f"Top add: {_t(top_sug, 40)}"),
        ui.kpi(str(len(ci.get("feature_gap_matrix") or [])), "Capabilities benchmarked", "Scored by simulated buyer importance (0–10)"),
    ]) + "</div>"

    parts: List[str] = []

    # 1. AI Strategic Suggestions ("What Competitors Have vs What You Should Add Next")
    if sugs:
        sug_cards = []
        for s in sugs:
            pri = str(s.get("priority") or "high").upper()
            p_cls = "stop" if pri == "CRITICAL" else "accent"
            sug_cards.append(
                f'<div class="thought-card">'
                f'<div class="person-h"><div><b>{_e(s.get("title"))}</b>'
                f'<div class="small muted">{_e(s.get("category"))} · Effort: {_e(s.get("effort"))} · Priority Score: {s.get("priority_score", 90)}/100</div></div>'
                f'<span class="pill mint">+{s.get("simulated_win_share_lift_pts", 0):g} pts win share</span>'
                f'<span class="pill {p_cls}">{_e(pri)}</span></div>'
                f'<div class="th-sys2"><b>🏢 What Competitor Has:</b> {_e(s.get("what_competitor_has"))}</div>'
                f'<div class="th-box"><span class="th-lbl">✨ AI Suggestion: What You Should Add</span><p>{_e(s.get("what_you_should_add"))}</p></div>'
                f'<div class="th-sys2"><b>🧠 Why Simulated Buyers Care:</b> {_e(s.get("why_buyers_care"))}</div>'
                f'<div class="th-act"><b>🚀 Ready-to-Ship Spec / Copy:</b> <code>{_e(s.get("ready_to_ship_spec"))}</code></div>'
                f'</div>'
            )
        parts.append(
            '<div class="card"><h3>1. AI Strategic Suggestions: What Competitors Have &amp; What You Should Add Next</h3>'
            '<p class="small muted">Ranked by simulated Win-Share Lift (+pts) when re-tested against the persona cohort’s BDE wallets and dealbreakers.</p>'
            f'<div class="people">{"".join(sug_cards)}</div></div>'
        )

    # 2. Feature Gap & Whitespace Matrix ("What Competitor Has vs What We Have")
    fgm = ci.get("feature_gap_matrix") or []
    if fgm:
        def _status_pill(val: Any) -> str:
            s_val = str(val or "")
            if s_val.startswith("Has"):
                return _pill(s_val, "mint")
            if "Missing" in s_val:
                return _pill(s_val, "stop")
            return _pill(s_val, "accent")

        fg_rows = "".join(
            f"<tr><td><b>{_e(r.get('capability'))}</b><div class='small muted'>{_e(r.get('category'))}</div></td>"
            f"<td class='num'><b>{r.get('buyer_importance', 0)}/10</b></td>"
            f"<td>{_status_pill(r.get('our_current_status'))}</td>"
            f"<td>{_e(r.get('free_alternatives'))}</td>"
            f"<td>{_e(r.get('global_incumbent'))}</td>"
            f"<td>{_e(r.get('local_challenger'))}</td>"
            f"<td class='small'>{_e(r.get('strategic_verdict'))}</td></tr>"
            for r in fgm
        )
        parts.append(
            '<div class="card"><h3>2. Feature Parity &amp; Competitive Whitespace Matrix</h3>'
            '<div class="tbl"><table class="sortable"><thead><tr>'
            '<th>Capability / Feature</th><th class="num">Buyer Importance</th><th>Our Current Status</th>'
            '<th>Free Alternatives</th><th>Global Incumbent</th><th>Local Challenger</th><th>Strategic Whitespace Verdict</th>'
            f'</tr></thead><tbody>{fg_rows}</tbody></table></div></div>'
        )

    # 3. Competitor Breakdown Cards ("What Each Competitor Has vs Where They Fail")
    comps = ci.get("competitors") or []
    if comps:
        comp_cards = []
        for c in comps:
            has_li = "".join(f"<li>{_e(x)}</li>" for x in (c.get("what_they_have") or []))
            fail_li = "".join(f"<li>{_e(x)}</li>" for x in (c.get("where_they_fail") or []))
            comp_cards.append(
                f'<div class="thought-card">'
                f'<div class="person-h"><div><b>{_e(c.get("name"))}</b>'
                f'<div class="small muted">Price: {_e(c.get("price"))}</div></div>'
                f'<span class="pill">{c.get("current_preference_share_pct", 0):g}% → {c.get("share_after_our_ai_upgrades_pct", 0):g}% share</span></div>'
                f'<div class="th-sys2"><b>✅ What They Have (Why buyers defect to them):</b><ul class="small" style="margin:4px 0 0;padding-left:18px">{has_li}</ul></div>'
                f'<div class="th-sys2"><b>❌ Where They Fail Buyers (Our wedge):</b><ul class="small" style="margin:4px 0 0;padding-left:18px">{fail_li}</ul></div>'
                f'<div class="th-act"><b>🎯 Stealable Share:</b> +{c.get("stealable_share_pts", 0):g} pts recaptured when AI suggestions are shipped</div>'
                f'</div>'
            )
        parts.append(
            '<div class="card"><h3>3. Competitor Deep-Dive: What Each Competitor Has vs. Where They Fail</h3>'
            f'<div class="people">{"".join(comp_cards)}</div></div>'
        )

    # 4. Head-to-Head Buyer Bake-Off & Switching Triggers
    bakeoff = ci.get("head_to_head_bakeoff") or []
    if bakeoff:
        b_rows = "".join(
            f"<tr><td><b>{_e(b.get('name'))}</b><div class='small muted'>{_e(b.get('segment'))} · {_e(b.get('country'))}</div></td>"
            f"<td><span class='mm-provider-badge' data-prov='{_e(b.get('model_provider'))}'>{_e(b.get('model_provider'))}</span></td>"
            f"<td>{_pill(b.get('current_choice'), 'mint' if b.get('current_choice') == 'Our Brand' else 'stop')}</td>"
            f"<td>{_pill(b.get('choice_after_ai_adds'), 'mint' if b.get('choice_after_ai_adds') == 'Our Brand' else '')}</td>"
            f"<td class='small'>{_e(b.get('what_makes_them_switch'))}</td>"
            f"<td class='small muted'>{_e(b.get('thought'))}</td></tr>"
            for b in bakeoff
        )
        parts.append(
            '<div class="card"><h3>4. Head-to-Head Agent Bake-Off &amp; Switching Triggers</h3>'
            '<div class="tbl"><table class="sortable"><thead><tr>'
            '<th>Simulated Buyer</th><th>Model</th><th>Current Choice</th><th>After AI Suggestions</th>'
            '<th>Exact Switching Trigger</th><th>First-Person Buyer Quote</th>'
            f'</tr></thead><tbody>{b_rows}</tbody></table></div></div>'
        )

    # 5. Competitive War-Game Counter-Move Simulator
    wg = ci.get("wargame_scenarios") or []
    if wg:
        wg_rows = "".join(
            f"<tr><td><b>{_e(w.get('scenario'))}</b><div class='small muted'>{_e(w.get('competitor_move'))}</div></td>"
            f"<td class='num'>{w.get('our_retention_without_response_pct', 0)}%</td>"
            f"<td class='num'><b>{w.get('our_retention_with_ai_counter_pct', 0)}%</b></td>"
            f"<td class='small'>{_e(w.get('ai_counter_strategy'))}</td></tr>"
            for w in wg
        )
        parts.append(
            '<div class="card"><h3>5. Competitive War-Game &amp; Counter-Move Simulator</h3>'
            '<div class="tbl"><table><thead><tr>'
            '<th>Competitor Attack Scenario</th><th class="num">Share If Unanswered</th>'
            '<th class="num">Share With AI Counter</th><th>Recommended AI Counter-Play</th>'
            f'</tr></thead><tbody>{wg_rows}</tbody></table></div></div>'
        )

    intro = (
        "Simulated head-to-head buyer bake-off against competitors: see what competitors have, where they fail your buyers, "
        "which missing features cost you deals, and the highest-lift AI product & marketing additions to steal back market share."
    )
    body = ui.section_head("Competitor intelligence & AI strategy", intro, insight) + kpis_html + "".join(parts)
    return ("competitors", "Competitor & AI strategy", body)


def cro_lab_section(bundle: Dict[str, Any], insight: Optional[str] = None) -> Optional[Tuple[str, str, str]]:
    """'CRO, What-If & Roleplay Lab': Subconscious-style interactive What-If Conjoint Sliders,
    Wynter + Neurons 5-Second Landing Page Teardown & Scroll Decay, Hyperbound/Yoodli Interactive AI Buyer
    Roleplay Sparring Dojo, and Mutiny 1:1 Segment Personalization + Evidenza CEPs."""
    if not isinstance(bundle, dict):
        return None
    suite = bundle.get("gtm_suite") if isinstance(bundle.get("gtm_suite"), dict) else {}
    lab = bundle.get("cro_lab") or suite.get("cro_lab") or {}
    td = lab.get("landing_teardown") or bundle.get("landing_teardown")
    rp = lab.get("sales_roleplay") or bundle.get("sales_roleplay")
    wi = lab.get("causal_whatif") or bundle.get("causal_whatif")
    sp = lab.get("segment_personalization") or bundle.get("segment_personalization")
    if not any(isinstance(x, dict) and x for x in (td, rp, wi, sp)):
        return None

    kpis = []
    if isinstance(td, dict):
        p = td.get("pillars") or {}
        kpis.append(ui.kpi(f"{td.get('overall_5s_score', 0):g}/100", "5-Second Clarity Score",
                           f"Clarity {p.get('clarity', 0)} · Trust {p.get('credibility', 0)}", hl=True))
    if isinstance(rp, dict):
        kpis.append(ui.kpi(f"{rp.get('overall_score', 0)}/100", "Roleplay Coaching Score",
                           str(rp.get("certification_grade") or "Ready")))
    if isinstance(sp, dict):
        kpis.append(ui.kpi(f"+{sp.get('avg_personalization_lift_pts', 0):g} pts", "1:1 Personalization Lift",
                           f"{len(sp.get('segment_playbooks') or [])} segment micro-pages"))
    if isinstance(wi, dict):
        kpis.append(ui.kpi(str(len(wi.get("attributes") or [])), "Interactive What-If Levers",
                           "Toggle features & price live below"))
    kpis_html = f'<div class="kpis auto">{"".join(kpis)}</div>' if kpis else ""

    parts: List[str] = []

    # 1. Interactive Subconscious.ai-Style What-If Feature & Price Simulator
    if isinstance(wi, dict) and wi.get("attributes"):
        cur = str(wi.get("currency") or "USD")
        base_p = float(wi.get("base_price") or 12.0)
        min_p = float(wi.get("min_price") or 3.0)
        max_p = float(wi.get("max_price") or 30.0)
        step_p = float(wi.get("price_step") or 1.0)
        attrs_html = "".join(
            f'<label class="wi-toggle"><input type="checkbox" data-wi-attr="{_e(a["id"])}" '
            f'data-conv="{a.get("marginal_conv_lift_pts", 0)}" data-share="{a.get("marginal_win_share_pts", 0)}" '
            f'data-drop="{a.get("card_dropoff_reduction_pts", 0)}" data-ret="{a.get("retention_lift_pts", 0)}" '
            f'{"checked" if a.get("default_on") else ""}>'
            f'<span><b>{_e(a.get("label"))}</b> <small class="muted">({a.get("category")} · +{a.get("marginal_conv_lift_pts", 0):g} pts conv)</small></span></label>'
            for a in wi.get("attributes") or []
        )
        seg_opts = "".join(
            f'<option value="{i}" data-bconv="{s.get("base_conversion_pct", 15)}" data-bshare="{s.get("base_win_share_pct", 36)}" '
            f'data-bdrop="{s.get("base_card_dropoff_pct", 52)}" data-bret="{s.get("base_retention_pct", 55)}" '
            f'data-elast="{s.get("price_elasticity_per_10pct", -1.8)}">{_e(s.get("segment"))}</option>'
            for i, s in enumerate(wi.get("segments") or [])
        )
        parts.append(
            '<div class="card" id="mm-whatif-box"><h3>1. Interactive What-If Price &amp; Feature Conjoint Simulator (Subconscious.ai Pattern)</h3>'
            '<p class="small muted">Toggle product/offer attributes and drag the price slider to simulate real-time shifts in Conversion Rate, Competitive Win Share, Card Drop-Off, and 90-Day Revenue.</p>'
            '<div class="wi-controls">'
            f'<label><b>Target Segment:</b> <select id="mm-wi-seg">{seg_opts}</select></label>'
            f'<label><b>Monthly Price ({_e(cur)}):</b> <input type="range" id="mm-wi-price" min="{min_p:g}" max="{max_p:g}" step="{step_p:g}" value="{base_p:g}" data-base="{base_p:g}" data-cur="{_e(cur)}"> '
            f'<b id="mm-wi-price-out">{_e(cur)} {base_p:g}</b></label>'
            '</div>'
            f'<div class="wi-grid">{attrs_html}</div>'
            '<div class="kpis auto" style="margin-top:12px">'
            '<div class="kpi hl"><div class="v" id="mm-wi-conv">34.9%</div><div class="k">Predicted Conversion Rate</div><div class="h">From landing visit to signup</div></div>'
            '<div class="kpi"><div class="v" id="mm-wi-share">62.7%</div><div class="k">Brand Win Share vs Competitors</div><div class="h">Head-to-head preference share</div></div>'
            '<div class="kpi"><div class="v" id="mm-wi-drop">12.0%</div><div class="k">Card / Form Drop-Off</div><div class="h">Say-vs-Do abandonment rate</div></div>'
            f'<div class="kpi"><div class="v" id="mm-wi-rev">{_e(cur)} 820,000</div><div class="k">Projected 90d Revenue / 1k Visitors</div><div class="h">Net of Day-30 churn</div></div>'
            '</div></div>'
        )

    # 2. Wynter + Neurons 5-Second Landing Page Teardown & Scroll Decay
    if isinstance(td, dict):
        pil = td.get("pillars") or {}
        z_rows = "".join(
            f"<tr><td><b>{_e(z.get('zone'))}</b><div class='small muted'>{_e(z.get('focal_element'))}</div></td>"
            f"<td class='num'><b>{z.get('attention_retained_pct', 0)}%</b></td>"
            f"<td>{_pill(z.get('cognitive_load'))}</td>"
            f"<td class='small'>{_e(z.get('drop_off_warning'))}</td></tr>"
            for z in (td.get("scroll_zones") or [])
        )
        pin_cards = []
        for pin in (td.get("sentiment_pins") or []):
            p_col = str(pin.get("pin_color") or "yellow")
            p_cls = "mint" if p_col == "green" else ("stop" if p_col == "red" else "accent")
            pin_cards.append(
                f'<div class="thought-card">'
                f'<div class="person-h"><div><b>{_e(pin.get("section"))}</b>'
                f'<div class="small muted">{_e(pin.get("buyer_name"))} · {_e(pin.get("segment"))} · Score: {pin.get("score_0_10", 0)}/10</div></div>'
                f'<span class="pill {p_cls}">{_e(pin.get("pin_label"))}</span></div>'
                f'<div class="th-box"><span class="th-lbl">👀 5-Second Buyer Reaction</span><p>{_e(pin.get("buyer_quote"))}</p></div>'
                f'<div class="th-sys2"><b>Before:</b> {_e(pin.get("before_copy"))}</div>'
                f'<div class="th-act"><b>✨ AI High-Converting Rewrite ({_e(pin.get("expected_lift"))}):</b> {_e(pin.get("after_rewrite"))}</div>'
                f'</div>'
            )
        parts.append(
            '<div class="card"><h3>2. Wynter + Neurons 5-Second Landing Page Teardown &amp; Scroll-Decay Curve</h3>'
            f'<p class="small muted">4-Pillar 5-Second Audit — Clarity: <b>{pil.get("clarity", 0)}/10</b> · Relevance: <b>{pil.get("relevance", 0)}/10</b> · '
            f'Differentiation: <b>{pil.get("differentiation", 0)}/10</b> · Credibility / Anti-BS: <b>{pil.get("credibility", 0)}/10</b>.</p>'
            '<div class="tbl"><table><thead><tr><th>Viewport Scroll Fold</th><th class="num">Attention Retained</th><th>Cognitive Load</th><th>Scroll-Drop Diagnosis</th></tr></thead>'
            f'<tbody>{z_rows}</tbody></table></div>'
            f'<div class="people" style="margin-top:12px">{"".join(pin_cards)}</div></div>'
        )

    # 3. Hyperbound / Yoodli Interactive AI Buyer Roleplay Sparring Dojo
    if isinstance(rp, dict) and rp.get("sparring_personas"):
        rub = rp.get("rubrics") or {}
        sp_json = json.dumps(rp.get("sparring_personas") or [], ensure_ascii=False).replace("<", "\\u003c")
        persona_btns = "".join(
            f'<button type="button" class="dojo-p-btn" data-dojo-p="{i}" aria-pressed="{"true" if i == 0 else "false"}">'
            f'<b>{_e(p.get("name"))}</b> <small>({_e(p.get("difficulty"))})</small></button>'
            for i, p in enumerate(rp.get("sparring_personas") or [])
        )
        p0 = rp["sparring_personas"][0]
        opt0 = (p0.get("response_options") or [{}])[0]
        opt_btns = "".join(
            f'<button type="button" class="dojo-opt-btn" data-dojo-opt="{j}" aria-pressed="{"true" if j == 0 else "false"}">{_e(o.get("approach"))}</button>'
            for j, o in enumerate(p0.get("response_options") or [])
        )
        parts.append(
            '<div class="card" id="mm-dojo-box"><h3>3. Interactive AI Buyer Roleplay Sparring Dojo &amp; Rubric Grader (Hyperbound / Yoodli Pattern)</h3>'
            f'<p class="small muted">Practice handling live buyer objections across difficulty levels. Overall Coaching Rubric: <b>{rp.get("overall_score", 0)}/100 ({_e(rp.get("certification_grade"))})</b> — '
            f'Discovery: {rub.get("discovery_depth", 0)} · Empathy: {rub.get("empathy_and_local_fit", 0)} · BDE Disarming: {rub.get("bde_objection_resolution", 0)} · Clarity: {rub.get("clarity_and_conciseness", 0)}.</p>'
            f'<div class="dojo-bar" role="group" aria-label="Select sparring buyer">{persona_btns}</div>'
            '<div class="thought-card" style="margin-top:10px">'
            f'<div class="th-sys2" id="mm-dojo-obj"><b>🗣️ Buyer Objection:</b> {_e(p0.get("opening_objection"))}</div>'
            f'<div class="th-sys2 muted" id="mm-dojo-sys1"><b>💭 Hidden System-1 Impulse:</b> {_e(p0.get("private_system1_thought"))}</div>'
            f'<div class="dojo-opts" id="mm-dojo-opts">{opt_btns}</div>'
            f'<div class="th-box"><span class="th-lbl">🎙️ Your Sales Response</span><p id="mm-dojo-rep">{_e(opt0.get("rep_line"))}</p></div>'
            f'<div class="th-sys2" id="mm-dojo-reply"><b>⚡ Buyer Spoken Reply:</b> {_e(opt0.get("buyer_reply"))}</div>'
            f'<div class="th-act" id="mm-dojo-score"><b>🏆 Sparring Outcome:</b> <span class="pill mint">{_e(opt0.get("verdict"))}</span> · '
            f'Conviction: <b>{opt0.get("conviction_after", 0)}/100</b> · Rubric Grade: <b>{opt0.get("rubric_score", 0)}/100</b> '
            f'· <i>Private thought: “{_e(opt0.get("buyer_private_thought"))}”</i></div>'
            '</div>'
            f'<script type="application/json" id="mm-dojo-data">{sp_json}</script>'
            '</div>'
        )

    # 4. Mutiny 1:1 Segment Personalization & Evidenza Category Entry Points (CEPs)
    if isinstance(sp, dict):
        pb_cards = []
        for p in (sp.get("segment_playbooks") or []):
            pb_cards.append(
                f'<div class="thought-card">'
                f'<div class="person-h"><div><b>1:1 Micro-Page · {_e(p.get("segment"))} ({_e(p.get("country"))})</b>'
                f'<div class="small muted">Wallet: {_e(p.get("wallet_profile"))} · {p.get("personas_count", 0)} buyers</div></div>'
                f'<span class="pill mint">+{p.get("lift_pts", 0):g} pts lift ({p.get("generic_conversion_pct", 0)}% → {p.get("personalized_conversion_pct", 0)}%)</span></div>'
                f'<div class="th-box"><span class="th-lbl">🎯 Personalized Hero H1</span><p>“{_e(p.get("personalized_h1"))}”</p></div>'
                f'<div class="th-sys2"><b>Subheadline:</b> {_e(p.get("personalized_subhead"))}</div>'
                f'<div class="th-sys2"><b>Proof Banner:</b> {_e(p.get("social_proof_banner"))}</div>'
                f'<div class="th-act"><b>Recommended Package &amp; CTA:</b> {_e(p.get("recommended_package"))} · <code>[{_e(p.get("personalized_cta"))}]</code></div>'
                f'</div>'
            )
        cep_rows = "".join(
            f"<tr><td><b>{_e(c.get('cep_trigger'))}</b></td>"
            f"<td class='num'><b>{c.get('buyer_urgency', 0)}/10</b></td>"
            f"<td>{_e(c.get('current_leader'))}</td>"
            f"<td class='num'>{c.get('our_current_recall_pct', 0)}% → <b>{c.get('target_recall_after_wedge_pct', 0)}%</b></td>"
            f"<td class='small'>{_e(c.get('winning_hook_to_own_cep'))}</td></tr>"
            for c in (sp.get("category_entry_points") or [])
        )
        parts.append(
            '<div class="card"><h3>4. Mutiny 1:1 Segment Personalizer &amp; Evidenza Category Entry Points (CEPs)</h3>'
            f'<div class="people">{"".join(pb_cards)}</div>'
            + ('<h4 style="margin-top:16px">Category Entry Points (CEP) Recall &amp; Trigger Map</h4>'
               '<div class="tbl"><table><thead><tr><th>Real-Life Buyer Trigger Moment (CEP)</th><th class="num">Urgency</th>'
               '<th>Current Category Recall Leader</th><th class="num">Our Recall Share</th><th>Winning Hook to Capture Trigger</th></tr></thead>'
               f'<tbody>{cep_rows}</tbody></table></div>' if cep_rows else "")
            + '</div>'
        )

    # Inline self-contained interactive JS for What-If Simulator and Roleplay Dojo
    interactive_js = """
<script>
(function(){
  var wiBox = document.getElementById('mm-whatif-box');
  if (wiBox) {
    var segSel = document.getElementById('mm-wi-seg');
    var priceIn = document.getElementById('mm-wi-price');
    var priceOut = document.getElementById('mm-wi-price-out');
    var cbs = wiBox.querySelectorAll('input[data-wi-attr]');
    function recalc() {
      var opt = segSel && segSel.options[segSel.selectedIndex];
      var bConv = opt ? parseFloat(opt.getAttribute('data-bconv') || '15') : 15;
      var bShare = opt ? parseFloat(opt.getAttribute('data-bshare') || '36') : 36;
      var bDrop = opt ? parseFloat(opt.getAttribute('data-bdrop') || '52') : 52;
      var bRet = opt ? parseFloat(opt.getAttribute('data-bret') || '55') : 55;
      var elast = opt ? parseFloat(opt.getAttribute('data-elast') || '-1.8') : -1.8;
      var price = priceIn ? parseFloat(priceIn.value || '12') : 12;
      var baseP = priceIn ? parseFloat(priceIn.getAttribute('data-base') || '12') : 12;
      var cur = priceIn ? (priceIn.getAttribute('data-cur') || 'USD') : 'USD';
      if (priceOut) priceOut.textContent = cur + ' ' + price;
      var pctDiff10 = ((price - baseP) / Math.max(1, baseP)) * 10;
      var conv = bConv + pctDiff10 * elast;
      var share = bShare + pctDiff10 * (elast * 1.1);
      var drop = bDrop + Math.max(0, pctDiff10 * 1.5);
      var ret = bRet;
      cbs.forEach(function(cb){
        if (cb.checked) {
          conv += parseFloat(cb.getAttribute('data-conv') || '0');
          share += parseFloat(cb.getAttribute('data-share') || '0');
          drop -= parseFloat(cb.getAttribute('data-drop') || '0');
          ret += parseFloat(cb.getAttribute('data-ret') || '0');
        }
      });
      conv = Math.max(2, Math.min(88, conv));
      share = Math.max(5, Math.min(92, share));
      drop = Math.max(4, Math.min(85, drop));
      ret = Math.max(20, Math.min(95, ret));
      var rev = Math.round((conv / 100) * 1000 * price * (1 + (ret / 100) * 2));
      var elC = document.getElementById('mm-wi-conv'); if (elC) elC.textContent = conv.toFixed(1) + '%';
      var elS = document.getElementById('mm-wi-share'); if (elS) elS.textContent = share.toFixed(1) + '%';
      var elD = document.getElementById('mm-wi-drop'); if (elD) elD.textContent = drop.toFixed(1) + '%';
      var elR = document.getElementById('mm-wi-rev'); if (elR) elR.textContent = cur + ' ' + rev.toLocaleString();
    }
    if (segSel) segSel.addEventListener('change', recalc);
    if (priceIn) priceIn.addEventListener('input', recalc);
    cbs.forEach(function(cb){ cb.addEventListener('change', recalc); });
    recalc();
  }
  var dojoDataEl = document.getElementById('mm-dojo-data');
  var dojoBox = document.getElementById('mm-dojo-box');
  if (dojoDataEl && dojoBox) {
    try {
      var personas = JSON.parse(dojoDataEl.textContent);
      var curP = 0;
      function renderOpt(pIdx, oIdx) {
        var p = personas[pIdx] || personas[0];
        var o = (p.response_options || [])[oIdx] || (p.response_options || [])[0] || {};
        var repEl = document.getElementById('mm-dojo-rep'); if (repEl) repEl.textContent = o.rep_line || '';
        var rplEl = document.getElementById('mm-dojo-reply'); if (rplEl) rplEl.innerHTML = '<b>⚡ Buyer Spoken Reply:</b> ' + (o.buyer_reply || '');
        var scEl = document.getElementById('mm-dojo-score');
        if (scEl) {
          var cls = (o.rubric_score || 0) >= 80 ? 'mint' : ((o.rubric_score || 0) >= 45 ? 'accent' : 'stop');
          scEl.innerHTML = '<b>🏆 Sparring Outcome:</b> <span class="pill ' + cls + '">' + (o.verdict || '') + '</span> · Conviction: <b>' + (o.conviction_after || 0) + '/100</b> · Rubric Grade: <b>' + (o.rubric_score || 0) + '/100</b> · <i>Private thought: “' + (o.buyer_private_thought || '') + '”</i>';
        }
      }
      function renderPersona(pIdx) {
        curP = pIdx;
        var p = personas[pIdx] || personas[0];
        var objEl = document.getElementById('mm-dojo-obj'); if (objEl) objEl.innerHTML = '<b>🗣️ Buyer Objection:</b> ' + (p.opening_objection || '');
        var s1El = document.getElementById('mm-dojo-sys1'); if (s1El) s1El.innerHTML = '<b>💭 Hidden System-1 Impulse:</b> ' + (p.private_system1_thought || '');
        var optsWrap = document.getElementById('mm-dojo-opts');
        if (optsWrap) {
          optsWrap.innerHTML = '';
          (p.response_options || []).forEach(function(o, j){
            var b = document.createElement('button');
            b.type = 'button';
            b.className = 'dojo-opt-btn';
            b.setAttribute('aria-pressed', j === 0 ? 'true' : 'false');
            b.textContent = o.approach || ('Option ' + (j + 1));
            b.addEventListener('click', function(){
              optsWrap.querySelectorAll('.dojo-opt-btn').forEach(function(x){ x.setAttribute('aria-pressed', 'false'); });
              b.setAttribute('aria-pressed', 'true');
              renderOpt(curP, j);
            });
            optsWrap.appendChild(b);
          });
        }
        renderOpt(pIdx, 0);
      }
      dojoBox.querySelectorAll('[data-dojo-p]').forEach(function(btn){
        btn.addEventListener('click', function(){
          dojoBox.querySelectorAll('[data-dojo-p]').forEach(function(x){ x.setAttribute('aria-pressed', 'false'); });
          btn.setAttribute('aria-pressed', 'true');
          renderPersona(parseInt(btn.getAttribute('data-dojo-p') || '0', 10));
        });
      });
      renderPersona(0);
    } catch(e) {}
  }
})();
</script>"""

    intro = (
        "Interactive Conversion Rate Optimization (CRO), What-If Conjoint Simulator, 5-Second Landing Page Teardown, "
        "AI Buyer Roleplay Sparring Dojo, and 1:1 Segment Personalization inspired by Wynter, Neurons, Subconscious.ai, Hyperbound, and Mutiny."
    )
    body = ui.section_head("CRO, What-If & roleplay lab", intro, insight) + kpis_html + "".join(parts) + interactive_js
    return ("cro-lab", "CRO & roleplay lab", body)






REPORT_CSS += """
.mixbar{display:flex;height:14px;border-radius:7px;overflow:hidden;background:var(--line);margin:6px 0}
.mixbar span{display:block;height:100%}.mixbar .yes{background:var(--mm-yes)}.mixbar .maybe{background:var(--mm-maybe)}.mixbar .no{background:var(--mm-no)}
.mixbars{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media(max-width:700px){.mixbars{grid-template-columns:1fr}}
pre.script{white-space:pre-wrap;font:13px/1.5 var(--mono);margin:8px 0 0}
.idea dl{margin:8px 0 0}.idea ul.small{margin:0;padding-left:18px}
.thought-card{background:var(--surface-2);border:1px solid var(--border);border-radius:var(--r-lg);padding:14px 16px;display:flex;flex-direction:column;gap:6px}
.th-box{background:var(--surface);border-left:3px solid var(--accent);border-radius:6px;padding:8px 10px;margin:2px 0}
.th-box .th-lbl{display:block;font-size:.7rem;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin-bottom:2px}
.th-box p{margin:0;font-size:.88rem;line-height:1.45;color:var(--text);font-style:italic}
.th-sys2{font-size:.8rem;color:var(--text-2);line-height:1.4}
.th-act{font-size:.8rem;color:var(--text);padding-top:4px;border-top:1px dashed var(--border)}
.wi-controls{display:flex;flex-wrap:wrap;gap:16px;align-items:center;margin:10px 0;padding:10px 12px;background:var(--surface-2);border:1px solid var(--border);border-radius:var(--r-lg)}
.wi-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:8px;margin-top:8px}
.wi-toggle{display:flex;gap:8px;align-items:flex-start;padding:8px 10px;background:var(--surface-2);border:1px solid var(--border);border-radius:8px;cursor:pointer;font-size:.83rem}
.dojo-bar,.dojo-opts{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0}
.dojo-p-btn,.dojo-opt-btn{font:inherit;font-size:.8rem;padding:6px 12px;border-radius:var(--r-pill);border:1px solid var(--border);background:var(--surface);color:var(--text);cursor:pointer}
.dojo-p-btn[aria-pressed="true"],.dojo-opt-btn[aria-pressed="true"]{background:var(--text);color:var(--surface);border-color:var(--text)}
"""
