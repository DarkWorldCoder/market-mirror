"""
report_view.py - the plain-language report section (with the download bar in its header) and the
People cards for the dashboard. Stdlib only.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from feed_view import _e, _t

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


def report_section(mr: Optional[Dict[str, Any]], files: Dict[str, str], markdown_to_html) -> Tuple[str, str, str]:
    """The report, download bar first. Without a generated report it still shows the downloads and a hint."""
    head = ('<div class="rep-head"><div><h2>Report</h2><p class="muted small">Written in plain words from this run. '
            'Every number comes from the data below. Simulated people, not real customers.</p></div>'
            f'{download_bar(files)}</div>')
    if not mr or not (mr.get("markdown") or "").strip():
        return ("report", "Report", head + '<div class="callout">No report yet. Run <code>mirofish.py report --simulation '
                '&lt;id&gt;</code> (or let <code>market-test</code> finish) to get the plain-language report here.</div>')
    body = markdown_to_html(mr["markdown"])
    method = mr.get("method")
    note = ('<p class="muted small">Data-only report: the writing step failed, so this is the facts without narrative.</p>'
            if method == "fallback" else "")
    return ("report", "Report", head + note + f'<article class="report mm-report">{body}</article>')


def _pill(text: Any, cls: str = "") -> str:
    return f'<span class="pill {cls}">{_e(text)}</span>' if text not in (None, "") else ""


def people_cards(index: List[Dict[str, Any]], activity: Dict[Any, int], survey_by_agent: Dict[Any, Dict[str, Any]],
                 leads: Dict[Any, int], limit: int = 150) -> str:
    people = [r for r in index if r.get("kind") == "persona"][:limit]
    if not people:
        return ""
    cards = []
    for r in people:
        aid = r.get("agent_id")
        sv = survey_by_agent.get(aid) or {}
        verdict = sv.get("would_convert")
        vcls = {"yes": "mint", "maybe": "accent", "no": "orchid"}.get(verdict, "")
        who = ", ".join(str(x) for x in (r.get("age"), r.get("city"), r.get("country")) if x)
        traits = [r.get("upbringing"), r.get("education"), r.get("income_level") or r.get("income"), r.get("thinking_style")]
        cards.append(
            f'<div class="person"><div class="person-h"><span class="pm-av">{_e(str(r.get("name") or "?")[:1])}</span>'
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
    return f'<div class="people">{"".join(cards)}</div>'


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
.rep-head{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap;margin-bottom:12px}
.rep-head h2{margin:0 0 4px}.rep-head .dl{justify-content:flex-end;max-width:620px}
.mm-report{background:var(--surface);border-radius:24px;padding:22px 26px;max-width:none}
.mm-report h1{font-size:1.5rem;font-weight:500;letter-spacing:-.02em;margin-top:0}
.mm-report h2{font-size:1.15rem;font-weight:500;margin-top:26px;padding-top:14px;border-top:1px solid var(--grid)}
.mm-report table{font-size:.9rem}.mm-report blockquote{border-left-color:var(--mm-accent)}
.people{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:12px}
.person{background:var(--surface);border-radius:20px;padding:14px 16px}
.person-h{display:flex;gap:10px;align-items:center}.person-h>div{flex:1;min-width:0}
.person .pm-av{width:38px;height:38px;flex-basis:38px;background:var(--surface-2);color:var(--text)}
.lead{font-weight:600;background:var(--mm-accent);color:var(--mm-accent-ink);border-radius:999px;padding:3px 10px;font-size:.85rem}
.person-pills{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}
.person-q{font-size:.9rem;color:var(--text-2);margin:6px 0 8px;line-height:1.45}
.person-d{display:grid;grid-template-columns:auto 1fr;gap:3px 10px;font-size:.82rem;margin:0}
.person-d dt{color:var(--muted)}.person-d dd{margin:0}
"""
