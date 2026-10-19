"""
overview.py - the dashboard top: the coloured KPI strip ("At a glance") and the one-page brief that sits next
to the decision card. Everything is read from the run bundle, the marketing analysis (marketing.analyze) and
market_report.json; nothing is computed twice. Stdlib only.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse
from typing import Any, Dict, List, Optional, Tuple

try:  # stdlib only
    import ui  # type: ignore
    import marketing  # type: ignore
except ImportError:  # pragma: no cover - imported as a package
    from . import ui  # type: ignore
    from . import marketing  # type: ignore

_e, _t = ui.esc, ui.trunc


def _pct(v: Any) -> str:
    return "–" if v is None else f"{float(v):.0f}%"


def _num(v: Any) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"{int(f):,}" if f == int(f) else f"{f:,.2f}"


def feed_best(bundle: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The winning creative of the feed test with its metrics, seed spread and organic baseline."""
    ft = bundle.get("feed_test") or {}
    s = ft.get("summary") or {}
    per = s.get("per_creative") or {}
    if not per:
        return None
    ranked = [c for c in s.get("ranked") or list(per) if c in per]
    cid = ranked[0]
    cr = next((c for c in ft.get("creatives") or [] if c.get("id") == cid), {})
    ms = ft.get("multi_seed") or {}
    seeds = ms.get("n") or 1
    spread = ((ms.get("spread") or {}).get(cid) or {}).get("expected_ctr") if seeds > 1 else None
    return {"id": cid, "platform": cr.get("platform"), "m": per[cid], "spread": spread, "seeds": seeds,
            "base": (s.get("organic_baseline") or {}).get(cr.get("platform")) or {}}


def email_best(bundle: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    et = bundle.get("email_test") or {}
    s = et.get("summary") if isinstance(et.get("summary"), dict) else et
    per = (s or {}).get("per_email") or {}
    if not per:
        return None
    ranked = [c for c in s.get("ranked") or list(per) if c in per]
    return {"id": ranked[0], **per[ranked[0]]}


def kpi_strip(bundle: Dict[str, Any], mk: Dict[str, Any]) -> str:
    """Coloured tiles for whatever exists: people, would convert, expected converts, trust, best ad CTR,
    pitch score, email click rate, cost per lead. Same colour slot for the same kind of number everywhere."""
    tiles: List[str] = []
    people = int(mk.get("people") or 0)
    o = mk.get("overall") or {}
    ssr = o.get("ssr") or {}
    has = bool(mk.get("has_survey"))
    answered = int(mk.get("answered") or 0)
    engaged = int(mk.get("engaged") or 0)
    if people:
        hint = (f"{answered} surveyed · {engaged} joined the conversation" if has else f"{engaged} joined the conversation")
        tiles.append(ui.kpi(f"{people:,}", "Simulated people", hint, color=1, bar=100 * engaged / people))
    goal = marketing._goal_verb(mk.get("goal"))
    if has and o.get("convert_yes") is not None:
        tiles.append(ui.kpi(_pct(o["convert_yes"]), f"Would {goal}",
                            f'+{_pct(o.get("convert_maybe"))} maybe · simulated answers',
                            color=3, bar=o["convert_yes"]))
        fn = mk.get("funnel") or []
        if len(fn) >= 4:
            exp = fn[3][1]
            tiles.append(ui.kpi(_num(exp), "Simulated likely converts", f"of {answered} surveyed: would click, then {goal}",
                                color=6, bar=(100 * float(exp) / answered) if answered else None))
        if ssr.get("trust"):
            tr = ssr["trust"]
            tiles.append(ui.kpi(f'{tr["mean"]:.1f}/5', "Trust", f'±{tr["sd"]:.1f} spread, from free text', color=7,
                                bar=(float(tr["mean"]) - 1) / 4 * 100))
        elif o.get("trust") is not None:
            tiles.append(ui.kpi(f'{o["trust"]}/10', "Trust", "stated, average", color=7, bar=float(o["trust"]) * 10))
    fb = feed_best(bundle)
    if fb and fb["m"].get("expected_ctr") is not None:
        v = fb["spread"]["mean"] if fb["spread"] else fb["m"]["expected_ctr"]
        hint = f'{fb["id"]} · {ui.PLATFORM_LABEL.get(fb["platform"], fb["platform"] or "")}'.rstrip(" ·")
        delta, bar = None, None
        if fb["spread"]:
            delta = f'range {fb["spread"]["min"]}–{fb["spread"]["max"]}% over {fb["seeds"]} seeds'
        elif fb["base"].get("ctr") is not None:
            delta = f'{float(v) - float(fb["base"]["ctr"]):+.1f} pt vs organic posts'
        else:
            bar = min(100.0, float(v) / 5 * 100)
        tiles.append(ui.kpi(f"{v:g}%", "Best ad, simulated CTR", hint, delta, color=2, bar=bar))
    pitch = bundle.get("pitch") or {}
    if pitch.get("pitch_score") is not None:
        before, after = pitch.get("verdict_before") or {}, pitch.get("verdict_after") or {}
        d = float(after.get("yes") or 0) - float(before.get("yes") or 0)
        tiles.append(ui.kpi(f'{pitch["pitch_score"]}/100', "Pitch score",
                            f'{after.get("yes", 0)}% say yes · {len(pitch.get("hot_leads") or [])} hot leads',
                            f"{d:+.0f} pt after rebuttals" if d else None, color=4, bar=float(pitch["pitch_score"])))
    eb = email_best(bundle)
    if eb and eb.get("click_rate") is not None:
        tiles.append(ui.kpi(_pct(eb["click_rate"]), "Email click rate", f'{eb["id"]} · opens {_pct(eb.get("open_rate"))}',
                            color=5, bar=float(eb["click_rate"])))
    if fb:
        pr = fb["m"].get("projection") or {}
        cpl = pr.get("cpl") if pr.get("cpl") is not None else pr.get("cost_per_conversion")
        if cpl is not None:
            cur = pr.get("currency") or ""
            delta = None
            if pr.get("break_even_cpl"):
                be = float(pr["break_even_cpl"])
                delta = (f"+{be - float(cpl):g} {cur} under break-even" if float(cpl) <= be
                         else f"-{float(cpl) - be:g} {cur} over break-even")
            tiles.append(ui.kpi(f"{_num(cpl)} {cur}".strip(), "Cost per lead",
                                f'at a {_num(pr.get("budget"))} {cur} budget'.replace("  ", " "), delta, color=8))
    if not tiles:
        return ""
    return '<div class="kpi-strip">' + "".join(tiles) + "</div>"


_MONEY = re.compile(r"(\d[\d,]*(?:\.\d+)?)")
_CUR = re.compile(r"\b([A-Z]{3})\b|([$€£₹])")


def _budget_total(ads: List[Dict[str, Any]]) -> str:
    total, cur = 0.0, ""
    for ad in ads:
        b = str(ad.get("budget") or "")
        m = _MONEY.search(b)
        if not m:
            continue
        total += float(m.group(1).replace(",", ""))
        if not cur:
            c = _CUR.search(b)
            cur = (c.group(1) or c.group(2)) if c else ""
    if not total:
        return ""
    return f"{cur} {_num(total)}".strip() if len(cur) == 3 else f"{cur}{_num(total)}"


def brief_card(bundle: Dict[str, Any], mk: Dict[str, Any], decision: Optional[Dict[str, Any]]) -> str:
    """The one-page brief: three numbers, three actions, the next test, the budget plan and the 30-day plan
    when the report has them (market_report.json: action_plan, sections.budget_plan, sections.thirty_day_plan)."""
    mr = bundle.get("market_report") or {}
    sec = mr.get("sections") or {}
    ap = mr.get("action_plan") or sec.get("action_plan") or {}
    o = mk.get("overall") or {}
    ssr = o.get("ssr") or {}
    goal = marketing._goal_verb(mk.get("goal"))
    numbers: List[Tuple[str, str]] = []
    if mk.get("has_survey") and o.get("convert_yes") is not None:
        numbers.append((ui.pct_ci(o["convert_yes"], int(mk.get("answered") or 0)), f"would {goal}"))
        if ssr.get("purchase"):
            numbers.append((f'{ssr["purchase"]["mean"]:.1f}/5', "purchase intent"))
        elif o.get("trust") is not None:
            numbers.append((f'{o["trust"]}/10', "trust"))
    fb = feed_best(bundle)
    if fb and fb["m"].get("expected_ctr") is not None:
        numbers.append((f'{fb["m"]["expected_ctr"]:g}%', f'expected CTR, {fb["id"]}'))
    pitch = bundle.get("pitch") or {}
    if len(numbers) < 3 and pitch.get("pitch_score") is not None:
        numbers.append((f'{pitch["pitch_score"]}/100', "pitch score"))
    if len(numbers) < 3 and mk.get("people"):
        numbers.append((_num(mk["people"]), "simulated people"))
    numbers = numbers[:3]

    actions = [_t(f, 150) for f in (ap.get("fixes") or []) if f][:3]
    if not actions and decision:
        actions = [f"Answer the {str(f).lower()} objection before scaling" for f in decision.get("fixes") or []][:3]
    if not actions:
        for p in (mk.get("playbook") or [])[:3]:
            if p.get("lead_with"):
                actions.append(f'{p["segment"]}: lead with “{_t(p["lead_with"], 90)}”')

    rt = ap.get("retest") or {}
    next_test: Optional[Tuple[str, Optional[str], Optional[str]]] = None
    if rt.get("what"):
        next_test = (_t(rt["what"], 240), rt.get("success_looks_like"), rt.get("when"))
    else:
        ideas = (bundle.get("ideas") or {}).get("ideas") or []
        if ideas:
            i0 = ideas[0]
            next_test = (i0.get("title") or "", i0.get("success_looks_like"), i0.get("duration"))

    budget_html = ""
    bp = sec.get("budget_plan") or {}
    if bp.get("lines"):
        rows = [[l.get("where") or "–", f'{l.get("share_pct")}%' if l.get("share_pct") is not None else "–",
                 l.get("amount") or "–", l.get("expected_cpl") or "–"] for l in bp["lines"]]
        budget_html = (f'<h4>Budget plan{" · " + _e(bp.get("total")) if bp.get("total") else ""}</h4>'
                       + ui.table(["Where", "Share", "Amount", "Expected CPL"], rows, sortable=False)
                       + (f'<p class="muted small">Hold back: {_e(bp["hold_back"])}</p>' if bp.get("hold_back") else ""))
    elif ap.get("ads"):
        total = _budget_total(ap["ads"])
        items = "".join(
            f'<li><b>{_e(ad.get("audience") or "–")}</b> · {_e(ad.get("creative_id") or "")} · '
            f'{_e(", ".join(str(p).title() for p in ad.get("platforms") or []))} · {_e(ad.get("budget") or "")}'
            + (f' · {_e(ad.get("duration"))}' if ad.get("duration") else "") + "</li>" for ad in ap["ads"][:6])
        budget_html = f'<h4>Budget plan{" · " + _e(total) if total else ""}</h4><ul>{items}</ul>'

    plan_html = ""
    tp = sec.get("thirty_day_plan") or []
    if tp:
        rows = [[f'Week {w.get("week")}' if w.get("week") is not None else "–", _t(w.get("do"), 140),
                 w.get("owner") or "–", _t(w.get("measure"), 90)] for w in tp if isinstance(w, dict)]
        plan_html = "<h4>The next 30 days</h4>" + ui.table(["Week", "Do", "Owner", "Measure"], rows, sortable=False)

    if not (numbers or actions or next_test or budget_html or plan_html):
        return ""
    html = ['<div class="card brief"><h3>One-page brief</h3>']
    if numbers:
        html.append('<h4>Three numbers</h4><div class="kpis three">' + "".join(ui.kpi(v, k, cls="sm") for v, k in numbers) + "</div>")
    if actions:
        html.append("<h4>Three actions</h4><ol>" + "".join(f"<li>{_e(a)}</li>" for a in actions) + "</ol>")
    if next_test:
        what, success, when = next_test
        html.append(f"<h4>Next test</h4><p>{_e(what)}</p>"
                    + (f'<p class="muted small">Success looks like: {_e(_t(success, 200))}</p>' if success else "")
                    + (f'<p class="muted small">When: {_e(when)}</p>' if when else ""))
    html.append(budget_html + plan_html + "</div>")
    return "".join(html)


def decision_row(decision_html: str, brief_html: str) -> str:
    """Two columns: the decision card and the brief (one column on phones)."""
    return f'<div class="dash-row">{decision_html}{brief_html}</div>'


def evidence_section(research: Dict[str, Any]) -> Optional[Tuple[str, str, str]]:
    """Cited public feedback, with provenance and blocked-source notes visible."""
    if not isinstance(research, dict):
        return None
    quotes = [q for q in research.get("quotes") or [] if isinstance(q, dict) and q.get("url")]
    notes = (research.get("summary") or {}).get("notes") or []
    if not quotes and not notes:
        return None
    rows = []
    for q in quotes[:20]:
        url = str(q["url"])
        link = f'<a href="{_e(url)}" rel="noopener noreferrer" target="_blank">Source</a>' if urlparse(url).scheme in ("http", "https") else _e(url)
        rows.append(f'<tr><td>{_e(_t(q.get("text"), 220))}</td><td>{link}</td>'
                    f'<td>{_e(q.get("date") or "Unknown")}</td><td>{_e(q.get("market") or "Unspecified")}</td>'
                    f'<td>{_e(q.get("quality") or "Unverified")}</td></tr>')
    note_html = "".join(f'<li>{_e(n)}</li>' for n in notes)
    html = ui.section_head("Public-source findings", "Source dates and markets are shown only where the source supplies them; feedback remains unverified.")
    if note_html:
        html += f'<div class="callout"><strong>Source limitations</strong><ul>{note_html}</ul></div>'
    if rows:
        html += '<div class="card tbl"><table><thead><tr><th>Finding</th><th>Link</th><th>Date</th><th>Market</th><th>Quality</th></tr></thead><tbody>' + "".join(rows) + '</tbody></table></div>'
    return ("evidence", "Evidence", html)


def campaign_section(plan: Dict[str, Any]) -> Optional[Tuple[str, str, str]]:
    if not isinstance(plan, dict) or not plan.get("test_specs"):
        return None
    budget = plan.get("budget") or {}
    rows = []
    for spec in plan["test_specs"]:
        amount = (spec.get("budget") or {}).get("amount")
        rows.append([spec.get("type"), spec.get("exposure_context"), spec.get("actual_outcome_metric"),
                     f'{_num(amount)} {budget.get("currency") or ""}' if amount is not None else "–",
                     spec.get("next_real_world_test")])
    html = ui.section_head("Campaign plan", "Draft channel assumptions and next controlled tests. Nothing has been sent or purchased.")
    html += f'<p><strong>Goal:</strong> {_e(plan.get("goal"))} · <strong>Budget:</strong> {_e(_num(budget.get("amount")))} {_e(budget.get("currency"))}</p>'
    html += ui.table(["Test", "Exposure", "Real outcome", "Draft budget", "Next real test"], rows, sortable=False)
    if plan.get("unknowns"):
        html += '<div class="callout"><strong>Evidence gaps</strong><ul>' + "".join(f'<li>{_e(x)}</li>' for x in plan["unknowns"]) + '</ul></div>'
    return ("campaign", "Campaign", html)


def prediction_section(data: Dict[str, Any]) -> Optional[Tuple[str, str, str]]:
    if not isinstance(data, dict) or not data.get("predictions"):
        return None
    rows = [[p.get("what"), p.get("simulated"), p.get("predicted") if p.get("predicted") is not None else "Directional only",
             p.get("basis"), p.get("status")] for p in data["predictions"]]
    return ("predictions", "Predictions", ui.section_head("Prediction evidence", data.get("note"))
            + ui.table(["Outcome", "Simulation", "Calibrated estimate", "Basis", "Status"], rows, sortable=False))


def study_section(study: Dict[str, Any]) -> Optional[Tuple[str, str, str]]:
    scenarios = (study or {}).get("scenarios") or []
    if not scenarios:
        return None
    labels = study.get("metric_labels") or {}
    keys = [key for key in labels if any((s.get("metrics") or {}).get(key) for s in scenarios)]
    rows = []
    for key in keys:
        row = [labels[key]]
        for scenario in scenarios:
            metric = (scenario.get("metrics") or {}).get(key) or {}
            value = metric.get("mean")
            observed = f' (seed range {metric["min"]}–{metric["max"]})' if metric.get("min") is not None and metric.get("max") is not None else ""
            row.append("–" if value is None else str(value) + observed)
        rows.append(row)
    conclusion = study.get("conclusion") or {}
    html = ui.section_head("Scenario comparison", "Same simulated people and seed assignments across scenarios; uncertainty reflects seed-to-seed spread.")
    stability = conclusion.get("stability_pct")
    stability_text = f"{stability}%" if stability is not None else "–"
    html += '<div class="card"><p><strong>Directional winner:</strong> ' + _e(conclusion.get("best_scenario") or "Unclear") + \
            ' · <strong>Stability:</strong> ' + _e(stability_text) + '</p>'
    chart_keys = [key for key in keys if any(isinstance(((s.get("metrics") or {}).get(key) or {}).get("mean"), (int, float)) for s in scenarios)]
    if chart_keys:
        preferred = conclusion.get("headline_metric")
        if preferred in chart_keys:
            chart_keys.remove(preferred)
            chart_keys.insert(0, preferred)
        html += '<p class="muted small">Dots show the mean; whiskers show the observed minimum and maximum across simulated seeds. These ranges describe simulation variation.</p>'
        html += '<div class="seg-tabs" aria-label="Scenario metric">' + ''.join(
            f'<button type="button" data-panel="study-{_e(key)}" aria-pressed="{"true" if i == 0 else "false"}">{_e(labels[key])}</button>'
            for i, key in enumerate(chart_keys)) + '</div>'
        for i, key in enumerate(chart_keys):
            measured = [(s, (s.get("metrics") or {}).get(key) or {}) for s in scenarios]
            measured = [(s, m) for s, m in measured if isinstance(m.get("mean"), (int, float))]
            spec = {"cats": [s.get("name") or "Scenario" for s, _ in measured],
                    "points": [[idx, m["mean"], m.get("min") if m.get("min") is not None else m["mean"],
                                m.get("max") if m.get("max") is not None else m["mean"]] for idx, (_, m) in enumerate(measured)],
                    "metric": labels[key]}
            html += f'<div class="seg-panel" data-panel="study-{_e(key)}"{" hidden" if i else ""}>' + \
                marketing.chart("scenario_ranges", spec, max(180, 55 * len(measured)), f'{labels[key]} by scenario, with observed seed ranges') + '</div>'
    if rows:
        html += ui.table(["Metric"] + [s.get("name") or "Scenario" for s in scenarios], rows, sortable=False)
    html += '</div>'
    return ("scenarios", "Scenarios", html)


def run_health(bundle: Dict[str, Any]) -> Optional[Tuple[str, str, str]]:
    state = bundle.get("run_status") or {}
    manifest = bundle.get("run_manifest") or {}
    if not state and not manifest:
        return None
    status = state.get("runner_status") or manifest.get("runner_status") or "not started"
    completed_platforms = [p for p in ("twitter", "reddit") if state.get(p + "_completed")]
    rounds_complete = bool(completed_platforms) and not any(state.get(p + "_running") for p in ("twitter", "reddit"))
    social_label = "Rounds complete; interviews available" if rounds_complete and status == "running" else str(status).replace("_", " ")
    survey = bundle.get("survey") or {}
    responses = survey.get("responses") or []
    usable = sum(bool(r.get("answer")) for r in responses if isinstance(r, dict))
    ft = bundle.get("feed_test") or {}
    rows = [["Social simulation", social_label, f'{state.get("current_round", 0)}/{state.get("total_rounds", "?")} rounds; {state.get("total_actions_count", 0)} recorded actions'],
            ["Feed test", "Complete" if ft.get("summary") else "No result", f'{ft.get("personas_tested", "–")} simulated people'],
            ["Buyer survey", "Complete" if responses else "No result", f'{usable}/{len(responses)} usable answers' if responses else "Not collected"],
            ["Pipeline artifacts", "Complete" if manifest.get("finished_at") else "In progress" if manifest.get("started_at") else "Not recorded",
             manifest.get("finished_at") or manifest.get("started_at") or "–"]]
    html = ui.section_head("Run health", "Execution status and collected evidence. Completed social rounds can keep an interview environment open.")
    html += '<div class="card">' + ui.table(["Stage", "Status", "Measured evidence"], rows, sortable=False)
    if state.get("error") or manifest.get("error"):
        html += '<p class="callout" role="status">' + _e(state.get("error") or manifest.get("error")) + '</p>'
    html += '</div>'
    return ("run-health", "Run health", html)


OVERVIEW_JS = r"""
window.MM.charts.scenario_ranges=function(s,t){
 return {animation:!matchMedia('(prefers-reduced-motion: reduce)').matches,aria:{enabled:true},
 textStyle:{fontFamily:t.font,color:t.ink},grid:{left:12,right:32,top:16,bottom:30,containLabel:true},
 tooltip:{trigger:'item',renderMode:'richText',formatter:function(p){var d=p.data;return s.cats[d[0]]+'\nMean: '+d[1]+'\nObserved seed range: '+d[2]+'–'+d[3];}},
 xAxis:{type:'value',name:s.metric,nameLocation:'middle',nameGap:26,axisLabel:{color:t.muted},splitLine:{lineStyle:{color:t.grid}}},
 yAxis:{type:'category',inverse:true,data:s.cats,axisTick:{show:false},axisLine:{show:false},axisLabel:{color:t.ink2,width:130,overflow:'truncate'}},
 series:[{type:'custom',data:s.points,encode:{x:[1,2,3],y:0},renderItem:function(p,a){var m=a.coord([a.value(1),a.value(0)]),lo=a.coord([a.value(2),a.value(0)]),hi=a.coord([a.value(3),a.value(0)]);return {type:'group',children:[
 {type:'line',shape:{x1:lo[0],y1:lo[1],x2:hi[0],y2:hi[1]},style:{stroke:t.bar,lineWidth:3}},
 {type:'line',shape:{x1:lo[0],y1:lo[1]-6,x2:lo[0],y2:lo[1]+6},style:{stroke:t.bar,lineWidth:2}},
 {type:'line',shape:{x1:hi[0],y1:hi[1]-6,x2:hi[0],y2:hi[1]+6},style:{stroke:t.bar,lineWidth:2}},
 {type:'circle',shape:{cx:m[0],cy:m[1],r:6},style:{fill:t.ink,stroke:t.card,lineWidth:2}}]};}}]};
};
"""
