"""
report_view.py - the plain-language report section (with the download bar in its header) and the
People cards for the dashboard. Stdlib only.
"""

from __future__ import annotations

import json
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
            '<button type="button" onclick="window.print()">Print / PDF</button>']
    btns += [f'<button type="button" data-dl="{_e(n)}">{_e(DL_LABELS.get(n, n))}</button>' for n in files]
    payload = json.dumps(files, ensure_ascii=False).replace("<", "\\u003c")   # no tag can open or close inside
    return (f'<div class="dl" role="group" aria-label="Downloads">{"".join(btns)}</div>'
            f'<script type="application/json" id="mm-files">{payload}</script>')


def report_section(mr: Optional[Dict[str, Any]], files: Dict[str, str], markdown_to_html,
                   insight: Optional[str] = None) -> Tuple[str, str, str]:
    """The report, download bar first. Without a generated report it still shows the downloads and a hint."""
    head = ui.section_head("Report", "Written in plain words from this run. Every number comes from the data below. "
                           "Simulated people, not real customers.", insight, aside=ui.Raw(download_bar(files)))
    if not mr or not (mr.get("markdown") or "").strip():
        return ("report", "Report", head + '<div class="callout">No report yet. Run <code>mirofish.py report --simulation '
                '&lt;id&gt;</code> (or let <code>market-test</code> finish) to get the plain-language report here.</div>')
    body = markdown_to_html(mr["markdown"])
    method = mr.get("method")
    note = ('<p class="muted small">Data-only report: the writing step failed, so this is the facts without narrative.</p>'
            if method == "fallback" else "")
    return ("report", "Report", head + note + f'<article class="report mm-report">{body}</article>')


def people_cards(index: List[Dict[str, Any]], activity: Dict[Any, int], survey_by_agent: Dict[Any, Dict[str, Any]],
                 leads: Dict[Any, int], limit: int = 150) -> str:
    people = [r for r in index if r.get("kind") == "persona"][:limit]
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
    return people_filter_bar(segments, countries, bool(leads), any(survey_by_agent.values())) + f'<div class="people">{"".join(cards)}</div></div>'


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
#report .section-head .dl{justify-content:flex-end;max-width:620px}
.mm-report{background:var(--surface);border-radius:24px;padding:22px 26px;max-width:none}
.mm-report h1{font-size:1.5rem;font-weight:500;letter-spacing:-.02em;margin-top:0}
.mm-report h2{font-size:1.15rem;font-weight:500;margin-top:26px;padding-top:14px;border-top:1px solid var(--grid)}
.mm-report table{font-size:.9rem}.mm-report blockquote{border-left-color:var(--mm-accent)}
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
