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


def people_cards(index: List[Dict[str, Any]], activity: Dict[Any, int], survey_by_agent: Dict[Any, Dict[str, Any]],
                 leads: Dict[Any, int], limit: int = 150) -> str:
    everyone = [r for r in index if r.get("kind") == "persona"]
    if len(everyone) > limit:            # big runs: the strongest leads first, the rest are in leads.csv
        everyone = sorted(everyone, key=lambda r: -(leads.get(r.get("agent_id")) if leads.get(r.get("agent_id")) is not None else -1))
    people = everyone[:limit]
    if not people:
        return ""
    cards = []
    segments: Counter = Counter()
    countries: Counter = Counter()
    for i, r in enumerate(people):
        aid = r.get("agent_id")
        sv = survey_by_agent.get(aid) or {}
        verdict = sv.get("would_convert")
        vcls = {"yes": "mint", "maybe": "accent", "no": "orchid"}.get(verdict, "")
        who = ", ".join(str(x) for x in (r.get("age"), r.get("city"), r.get("country")) if x)
        traits = [r.get("upbringing"), r.get("education"), r.get("income_level") or r.get("income"), r.get("thinking_style")]
        if r.get("segment"):
            segments[str(r["segment"])] += 1
        if r.get("country"):
            countries[str(r["country"])] += 1
        attrs = (f'data-item data-order="{i}" data-segment="{_e(r.get("segment") or "")}" data-country="{_e(r.get("country") or "")}" '
                 f'data-verdict="{_e(verdict or "none")}" data-lead="{leads[aid] if aid in leads else ""}"')
        cards.append(
            f'<div class="person" {attrs}><div class="person-h"><span class="pm-av">{_e(str(r.get("name") or "?")[:1])}</span>'
            f'<div><b>{_e(r.get("name"))}</b><div class="muted small">{_e(who)} · {_e(r.get("occupation") or "")}</div></div>'
            + (f'<span class="lead" title="Lead score 0-100">{leads[aid]}</span>' if aid in leads else "") + '</div>'
            f'<div class="person-pills">{_pill(r.get("segment"))}'
            + "".join(_pill(l) for l in (r.get("languages") or [])[:2])
            + (_pill(f"would {verdict}", vcls) if verdict else "") + "</div>"
            + (f'<p class="person-q">“{_e(_t(r.get("interview_summary"), 320))}”</p>' if r.get("interview_summary") else "")
            + '<dl class="person-d">'
            + (f'<dt>Background</dt><dd>{_e("; ".join(str(t) for t in traits if t))}</dd>' if any(traits) else "")
            + (f'<dt>Phone</dt><dd>{_e(r.get("phone"))}{" · " + _e(r.get("data_plan")) if r.get("data_plan") else ""}</dd>' if r.get("phone") or r.get("data_plan") else "")
            + (f'<dt>Groups</dt><dd>{_e(", ".join(map(str, r.get("communities") or [])))}</dd>' if r.get("communities") else "")
            + (f'<dt>In the run</dt><dd>{activity.get(aid, 0)} actions</dd>' if activity else "")
            + (f'<dt>Objection</dt><dd>{_e(_t(sv.get("main_objection"), 140))}</dd>' if sv.get("main_objection") else "")
            + '</dl></div>')
    total = len([r for r in index if r.get("kind") == "persona"])
    note = (f'<p class="muted small">Showing the {len(people)} people with the highest lead scores of {total:,}. '
            'Everyone is in the leads.csv download.</p>' if total > len(people) else "")
    return (people_filter_bar(segments, countries, bool(leads), any(survey_by_agent.values())) + note
            + f'<div class="people">{"".join(cards)}</div></div>')


def people_filter_bar(segments: Dict[str, int], countries: Dict[str, int], has_leads: bool, has_survey: bool) -> str:
    """Opens the people filter root (closed by people_cards): segment, country, verdict and a minimum lead score."""
    def opts(c: Dict[str, int]) -> str:
        return "".join(f'<option value="{_e(k)}">{_e(k)} ({n})</option>' for k, n in sorted(c.items(), key=lambda x: (-x[1], x[0])))
    bar = ['<div class="filter-bar" role="group" aria-label="Filter people">']
    if segments:
        bar.append(f'<select data-filter="segment" aria-label="Segment"><option value="">All segments</option>{opts(segments)}</select>')
    if countries:
        bar.append(f'<select data-filter="country" aria-label="Country"><option value="">All countries</option>{opts(countries)}</select>')
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
    w.writerow(["agent_id", "name", "segment", "country", "city", "age", "occupation", "lead_score", "would_convert",
                "interest", "trust", "main_objection", "languages", "communities"])
    for r in index:
        if r.get("kind") != "persona":
            continue
        aid = r.get("agent_id")
        sv = survey_by_agent.get(aid) or {}
        w.writerow([aid, r.get("name"), r.get("segment"), r.get("country"), r.get("city"), r.get("age"), r.get("occupation"),
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
.person{background:var(--surface-2);border-radius:20px;padding:14px 16px}
.person-h{display:flex;gap:10px;align-items:center}.person-h>div{flex:1;min-width:0}
.person .pm-av{width:38px;height:38px;flex-basis:38px;background:var(--surface-2);color:var(--text)}
.lead{font-weight:600;background:var(--mm-accent);color:var(--mm-accent-ink);border-radius:999px;padding:3px 10px;font-size:.85rem}
.person-pills{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}
.person-q{font-size:.9rem;color:var(--text-2);margin:6px 0 8px;line-height:1.45}
.person-d{display:grid;grid-template-columns:auto 1fr;gap:3px 10px;font-size:.82rem;margin:0}
.person-d dt{color:var(--muted)}.person-d dd{margin:0}
"""


# --------------------------------------------------------------------------
# Sales rehearsal (pitch.json) and test ideas (ideas.json)
# --------------------------------------------------------------------------

DL_LABELS.update({"pitch.json": "Sales rehearsal (JSON)", "ideas.md": "Test ideas (Markdown)",
                  "ideas.json": "Test ideas (JSON)"})


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


REPORT_CSS += """
.mixbar{display:flex;height:14px;border-radius:7px;overflow:hidden;background:var(--line);margin:6px 0}
.mixbar span{display:block;height:100%}.mixbar .yes{background:var(--mm-yes)}.mixbar .maybe{background:var(--mm-maybe)}.mixbar .no{background:var(--mm-no)}
.mixbars{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media(max-width:700px){.mixbars{grid-template-columns:1fr}}
pre.script{white-space:pre-wrap;font:13px/1.5 var(--mono);margin:8px 0 0}
.idea dl{margin:8px 0 0}.idea ul.small{margin:0;padding-left:18px}
"""
