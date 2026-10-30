"""
shell.py - the dashboard's app frame, in the HYVE admin pattern: a borderless sidebar on the page canvas
(wordmark, quiet section labels, round icon chips, one black pill for the section you are reading), a black
rounded "live bar" on top (run name, the decision as a yellow pill, count chips, round tool buttons) and a page
header with a small eyebrow, a large uppercase title and the headline figures on the right. On phones the
sidebar becomes a sticky strip of section pills. Only markup and CSS; the sections are unchanged. Stdlib only.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

try:  # stdlib only
    import ui  # type: ignore
    import tokens  # type: ignore
except ImportError:  # pragma: no cover - imported as a package
    from . import ui  # type: ignore
    from . import tokens  # type: ignore

_e = ui.esc

# the MarketMirror mark (docs/brand), traced: two dark wedges + the yellow facet; dark parts follow the theme
MARK_SVG = ('<svg class="mm-mark" viewBox="0 0 200 190" aria-hidden="true"><g stroke-linejoin="round" stroke-width="8">'
            '<path fill="currentColor" stroke="currentColor" d="M14 14 95 62 58 99 95 127 14 176Z"/>'
            '<path fill="#f3d64b" stroke="#f3d64b" d="M107 70 186 16V72L146 96Z"/>'
            '<path fill="currentColor" stroke="currentColor" d="M146 99 186 75V176L108 128Z"/></g></svg>')
FAVICON = ("data:image/svg+xml," + MARK_SVG.replace('class="mm-mark" ', 'xmlns="http://www.w3.org/2000/svg" ')
           .replace("currentColor", "%23111").replace("#f3d64b", "%23f3d64b").replace('"', "'").replace("<", "%3C").replace(">", "%3E"))

GROUPS: List[Tuple[str, Sequence[str]]] = [
    ("Overview", ("kpis", "decision", "worldmap", "report", "brief")),
    ("Buyers", ("results", "ratings", "funnel", "audiences", "objections", "messages", "pricing", "voices", "models")),
    # thoughts and the lab sections are placed after the playbook on the page, so they sit with the tests here too
    ("Tests", ("feedtest", "socialfeed", "posts", "email", "emailtest", "pitch", "website", "playbook", "ideas", "gtm",
               "competitors", "cro-lab", "search-geo", "thoughts")),
    ("Evidence", ("scenarios", "study", "campaign", "research", "evidence", "predictions", "prediction", "analysts", "backtest", "run-health")),
    ("Behind the run", ("agents", "timeline", "graph", "overview", "engine-report")),
]

# simple 24px line icons (stroke = currentColor), so every system font draws them the same
_P = {
    "grid": '<rect x="4" y="4" width="7" height="7" rx="2"/><rect x="13" y="4" width="7" height="7" rx="2"/><rect x="4" y="13" width="7" height="7" rx="2"/><rect x="13" y="13" width="7" height="7" rx="2"/>',
    "target": '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r="0.8"/>',
    "globe": '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.6 2.4 3.8 5.2 3.8 8.5s-1.2 6.1-3.8 8.5c-2.6-2.4-3.8-5.2-3.8-8.5s1.2-6.1 3.8-8.5z"/>',
    "doc": '<path d="M7 3.5h7l4 4V20a.5.5 0 0 1-.5.5h-10.5a.5.5 0 0 1-.5-.5V4a.5.5 0 0 1 .5-.5z"/><path d="M14 3.5V8h4M9 12h6M9 15.5h6"/>',
    "bars": '<path d="M5 20V11M10 20V5M15 20v-7M20 20V9"/>',
    "funnel": '<path d="M4 5h16l-6 7.5V19l-4 1.5v-8z"/>',
    "users": '<circle cx="9" cy="9" r="3.2"/><path d="M3.5 19c.6-3 2.8-4.6 5.5-4.6s4.9 1.6 5.5 4.6"/><circle cx="16.5" cy="8" r="2.6"/><path d="M15.8 13.4c2.4 0 4.2 1.3 4.7 4.1"/>',
    "flag": '<path d="M6 21V4M6 4.5h11l-2.5 4 2.5 4H6"/>',
    "chat": '<path d="M4.5 6.5a2 2 0 0 1 2-2h11a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H10l-4.5 3.5v-3.5h0a1 1 0 0 1-1-1z"/>',
    "tag": '<path d="M3.5 12.3V4.5a1 1 0 0 1 1-1h7.8l8.2 8.2-8.8 8.8z"/><circle cx="8" cy="8" r="1.3"/>',
    "quote": '<path d="M9.5 7.5H6a1.5 1.5 0 0 0-1.5 1.5v3A1.5 1.5 0 0 0 6 13.5h2.5c0 2-1 3-2.5 3.5M19 7.5h-3.5A1.5 1.5 0 0 0 14 9v3a1.5 1.5 0 0 0 1.5 1.5H18c0 2-1 3-2.5 3.5"/>',
    "image": '<rect x="3.5" y="4.5" width="17" height="15" rx="2.5"/><circle cx="9" cy="10" r="1.6"/><path d="M4 17.5l5-4.5 4 3.5 3-2.5 4.5 3.5"/>',
    "feed": '<rect x="4" y="3.5" width="16" height="17" rx="2.5"/><path d="M8 8h8M8 12h8M8 16h5"/>',
    "mail": '<rect x="3.5" y="5.5" width="17" height="13" rx="2"/><path d="M4 7l8 6 8-6"/>',
    "phone": '<path d="M6.5 3.5h3l1.5 4-2 1.3a10 10 0 0 0 6.2 6.2l1.3-2 4 1.5v3a2 2 0 0 1-2 2A16.5 16.5 0 0 1 4.5 5.5a2 2 0 0 1 2-2z"/>',
    "play": '<circle cx="12" cy="12" r="8.5"/><path d="M10 8.8v6.4l5.2-3.2z"/>',
    "bulb": '<path d="M9 17.5h6M10 20.5h4M12 3.5a5.5 5.5 0 0 0-3.3 9.9c.6.5 1 1.2 1 2V15.5h4.6v-.1c0-.8.4-1.5 1-2A5.5 5.5 0 0 0 12 3.5z"/>',
    "layers": '<path d="M12 4l8.5 4.5L12 13 3.5 8.5z"/><path d="M3.5 12.5L12 17l8.5-4.5M3.5 16.5L12 21l8.5-4.5"/>',
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/>',
    "trend": '<path d="M3.5 17l5.5-5.5 4 4 7.5-7.5"/><path d="M15 8h5.5v5.5"/>',
    "check": '<circle cx="12" cy="12" r="8.5"/><path d="M8.5 12.2l2.4 2.4 4.8-5"/>',
    "rewind": '<path d="M4 12a8 8 0 1 0 2.4-5.7M4 4.5v4h4"/><path d="M12 8v4.5l3 1.8"/>',
    "pulse": '<path d="M3 12h4l2.5-6 4 12 2.5-6h5"/>',
    "user": '<circle cx="12" cy="8.5" r="3.8"/><path d="M5 20c.8-3.8 3.6-5.8 7-5.8s6.2 2 7 5.8"/>',
    "clock": '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    "nodes": '<circle cx="6" cy="12" r="2.3"/><circle cx="18" cy="6" r="2.3"/><circle cx="18" cy="18" r="2.3"/><path d="M8.1 11l7.8-4M8.1 13l7.8 4"/>',
    "gear": '<circle cx="12" cy="12" r="3"/><path d="M12 3.5v2.3M12 18.2v2.3M3.5 12h2.3M18.2 12h2.3M6 6l1.6 1.6M16.4 16.4L18 18M6 18l1.6-1.6M16.4 7.6L18 6"/>',
    "rocket": '<path d="M14.5 4.5c2.7-.8 4.5-.8 5-.5.3.5.3 2.3-.5 5L13 15.5 8.5 11z"/><path d="M8.5 11l-3.5.5-1.5 2.5 3.5.5M13 15.5l-.5 3.5-2.5 1.5-.5-3.5M8 16l-3 3"/>',
    "print": '<path d="M7 9V3.5h10V9"/><rect x="3.5" y="9" width="17" height="7.5" rx="2"/><path d="M7 14h10v6.5H7z"/>',
    "moon": '<path d="M19.5 14.5A7.5 7.5 0 0 1 9.5 4.5a7.5 7.5 0 1 0 10 10z"/>',
    "dot": '<circle cx="12" cy="12" r="2.5"/>',
}
ICON_OF = {"kpis": "grid", "decision": "target", "worldmap": "globe", "report": "doc", "brief": "doc", "results": "bars",
           "ratings": "bars", "funnel": "funnel", "audiences": "users", "objections": "flag", "messages": "chat",
           "pricing": "tag", "voices": "quote", "models": "layers", "thoughts": "bulb", "gtm": "rocket", "competitors": "target", "cro-lab": "pulse", "search-geo": "search", "feedtest": "image", "socialfeed": "feed", "posts": "feed", "email": "mail",
           "emailtest": "mail", "pitch": "phone", "website": "globe", "playbook": "play", "ideas": "bulb", "scenarios": "layers",
           "study": "layers", "campaign": "rocket", "research": "search", "evidence": "search", "predictions": "trend",
           "prediction": "trend", "analysts": "check", "backtest": "rewind", "choice": "bars", "run-health": "pulse", "agents": "user",
           "timeline": "clock", "graph": "nodes", "overview": "gear", "engine-report": "doc"}


def icon(name: str, size: int = 17) -> str:
    return (f'<svg viewBox="0 0 24 24" width="{size}" height="{size}" fill="none" stroke="currentColor" stroke-width="1.6" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{_P.get(name, _P["dot"])}</svg>')


def _glyph(anchor: str) -> str:
    return icon(ICON_OF.get(anchor, "dot"))


def sidebar(nav: List[Tuple[str, str]], title: str = "", subtitle: str = "", status: Optional[str] = None) -> str:
    """The left rail. ``nav`` is [(anchor, label)] in page order; anchors are grouped by GROUPS, unknown ones
    under "Results". ``title``/``subtitle``/``status`` are kept for callers; the run lives in the live bar now."""
    placed = set()
    blocks = []
    for name, anchors in GROUPS:
        items = [(a, b) for a, b in nav if a in anchors and a not in placed]
        placed.update(a for a, _ in items)
        if items:
            blocks.append((name, items))
    rest = [(a, b) for a, b in nav if a not in placed]
    if rest:
        blocks.insert(1 if blocks else 0, ("Results", rest))
    links = "".join(
        f'<div class="nav-group"><p class="nav-h">{_e(name)}</p>'
        + "".join(f'<a href="#{_e(a)}"><i>{_glyph(a)}</i><span>{_e(b)}</span></a>' for a, b in items)
        + "</div>" for name, items in blocks)
    return (
        '<aside class="side" aria-label="Dashboard">'
        '<a class="side-brand" href="#top" aria-label="MarketMirror, back to top">' + MARK_SVG
        + '<span class="word">MarketMirror</span></a>'
        f'<nav class="toc" data-scrollspy aria-label="Sections">{links}</nav>'
        '<p class="side-foot">Simulated people, simulated answers: directions with margins, not measurements.</p>'
        "</aside>")


def live_bar(run: str, decision: str = "", tone: Optional[str] = None, decision_note: str = "",
             counts: Sequence[Tuple[str, str]] = ()) -> str:
    """The black rounded bar: run name, the decision pill (links to the decision card), count chips, tools."""
    pill = ""
    if decision:
        pill = (f'<a class="lb-alert {tone or ""}" href="#decision"><span class="dot" aria-hidden="true"></span>'
                f'<span class="t"><b>{_e(decision)}</b>{(" · " + _e(decision_note)) if decision_note else ""}</span>'
                '<span aria-hidden="true">↗</span></a>')
    chips_html = "".join(f'<span class="lb-chip"><b>{_e(v)}</b>{_e(label)}</span>' for v, label in counts if v)
    return (
        '<div class="livebar"><div class="lb">'
        f'<span class="lb-run" title="{_e(run)}"><span class="lb-ico">{icon("doc", 15)}</span><span class="t">{_e(run)}</span></span>'
        f'<div class="lb-right">{pill}{chips_html}</div></div>'
        '<button type="button" class="theme-btn" data-theme-toggle aria-pressed="false" aria-label="Switch to dark theme">☾ Dark</button>'
        f'<button type="button" class="round-btn" onclick="window.print()" aria-label="Print or save as PDF" title="Print or save as PDF">{icon("print", 18)}</button>'
        "</div>")


def page_header(title: str, eyebrow: str = "", figures: str = "", note: str = "") -> str:
    return (
        '<header class="top phead"><div class="ph-left">'
        + (f'<p class="eyebrow">{_e(eyebrow)}</p>' if eyebrow else "")
        + f'<h1>{_e(title)}</h1>' + (f'<p class="req">{_e(note)}</p>' if note else "")
        + f'</div><div class="ph-figs">{figures}</div></header>')


def chips(items: List[Tuple[str, str, Optional[str]]]) -> str:
    """Status chips: [(value, label, tone)] with tone in go / iterate / stop / None."""
    return '<div class="chips">' + "".join(
        f'<span class="chip{" " + tone if tone else ""}"><b>{_e(v)}</b> {_e(label)}</span>' for v, label, tone in items if v) + "</div>"


WORKSPACE_VIEWS: List[Tuple[str, str, Sequence[str]]] = [   # the sidebar groups as views; people sit with the buyers
    ("all", "All", ()),
    ("overview", "Overview", tuple(GROUPS[0][1])),
    ("buyers", "Buyers", tuple(GROUPS[1][1]) + ("agents",)),
    ("campaigns", "Tests", tuple(GROUPS[2][1])),
    ("evidence", "Evidence", tuple(GROUPS[3][1])),
    ("system", "Behind the run", tuple(a for a in GROUPS[4][1] if a != "agents")),
]


def workspace_bar(nav: List[Tuple[str, str]], providers: Sequence[str] = ()) -> str:
    """View tabs, the providers that answered, and a search over sections and buyers; sticks to the top."""
    present = {a for a, _ in nav}
    tabs = []
    for vid, label, anchors in WORKSPACE_VIEWS:
        if vid != "all" and not any(a in present for a in anchors):
            continue
        cnt = len(present) if vid == "all" else sum(1 for a in anchors if a in present)
        tabs.append(
            f'<button type="button" class="ws-tab" data-ws-tab="{_e(vid)}" '
            f'data-ws-anchors="{_e(",".join(anchors))}" aria-pressed="{"true" if vid == "all" else "false"}">'
            f'<span>{_e(label)}</span><small>{cnt}</small></button>'
        )
    prov_badges = "".join(
        f'<span class="mm-provider-badge" data-prov="{_e(str(p).lower())}" title="Active model provider">{_e(p)}</span>'
        for p in providers if p
    )
    prov_wrap = f'<div class="ws-provs" aria-label="Model ensemble">{prov_badges}</div>' if prov_badges else ""
    return (
        '<div class="ws-bar" role="toolbar" aria-label="Workspace views">'
        f'<div class="ws-tabs" role="tablist">{"".join(tabs)}</div>'
        '<div class="ws-tools">'
        f'{prov_wrap}'
        '<label class="ws-search-wrap">'
        f'{icon("search", 14)}'
        '<input type="search" class="ws-search" data-ws-search placeholder="Filter sections or buyers…" aria-label="Filter sections or buyers">'
        '</label></div></div>'
    )


SHELL_CSS = """
body{margin:0}
.app{display:grid;grid-template-columns:256px minmax(0,1fr);min-height:100vh;background:var(--bg)}
/* sidebar: same canvas as the page, no border, no coloured edges */
.side{position:sticky;top:0;height:100vh;overflow-y:auto;scrollbar-width:none;display:flex;flex-direction:column;gap:22px;
padding:24px 12px 20px 20px;background:var(--bg);color:var(--text);border:0}
.side::-webkit-scrollbar{display:none}
.side-brand{display:flex;align-items:center;gap:10px;height:52px;flex:none;padding:0 8px;text-decoration:none;color:var(--text)}
.side-brand .mm-mark{width:30px;height:29px;flex:none;color:var(--text)}
.side-brand .word{font-size:1.18rem;letter-spacing:-.035em;font-weight:750}
.side nav.toc{position:static;display:flex;flex-direction:column;gap:18px;margin:0;padding:0;background:transparent;overflow:visible}
.side .nav-group{display:flex;flex-direction:column;gap:2px}
.side .nav-h{margin:0 0 6px;padding:0 12px;font-size:12px;font-weight:400;color:var(--muted);text-transform:none;letter-spacing:0}
.side nav.toc a{display:flex;align-items:center;gap:12px;height:44px;padding:0 10px 0 6px;border:0;border-radius:999px;
background:transparent;color:var(--text-2);font-size:13px;font-weight:500;text-decoration:none;white-space:nowrap;box-shadow:none;
transition:background var(--dur,.15s) ease,color var(--dur,.15s) ease}
.side nav.toc a i{display:grid;place-items:center;width:32px;height:32px;flex:none;border-radius:50%;font-style:normal;font-size:13px;
background:color-mix(in srgb,var(--text) 7%,transparent);color:var(--text)}
.side nav.toc a span{overflow:hidden;text-overflow:ellipsis}
.side nav.toc a:hover{background:var(--surface);color:var(--text)}
.side nav.toc a[aria-current="true"]{background:var(--text);color:var(--surface);box-shadow:none;border:0;border-radius:999px}
.side nav.toc a[aria-current="true"] i{background:color-mix(in srgb,var(--surface) 14%,transparent);color:var(--surface)}
.side-foot{margin:auto 0 0;padding:0 12px;color:var(--muted);font-size:11.5px;line-height:1.45}
/* main column */
.main{min-width:0}
.main .wrap{max-width:1320px;padding:24px 32px 72px}
.livebar{position:sticky;top:12px;z-index:6;display:flex;align-items:center;gap:10px;margin:0 0 12px}
.lb{flex:1;min-width:0;display:flex;align-items:center;gap:12px;padding:6px;border-radius:999px;background:var(--mm-panel);color:var(--mm-panel-ink);
box-shadow:0 8px 28px rgba(17,17,17,.10)}
.lb-run{display:inline-flex;align-items:center;gap:10px;height:40px;min-width:0;max-width:340px;padding:0 16px 0 6px;border-radius:999px;
background:var(--mm-panel-2);color:var(--mm-panel-muted);font-size:13px}
.lb-run .lb-ico{display:grid;place-items:center;width:28px;height:28px;border-radius:50%;background:#ffffff14;color:var(--mm-panel-ink);flex:none}
.lb-run .t,.lb-alert .t{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.lb-right{flex:1;min-width:0;display:flex;align-items:center;justify-content:flex-end;gap:8px;overflow:hidden}
.lb-alert{display:inline-flex;align-items:center;gap:8px;height:40px;min-width:0;padding:0 16px;border-radius:999px;font-size:13px;
font-weight:500;text-decoration:none;background:var(--mm-panel-2);color:var(--mm-panel-ink)}
.lb-alert .dot{width:8px;height:8px;border-radius:50%;background:currentColor;flex:none}
.lb-alert b{font-weight:650}
.lb-alert.iterate{background:var(--mm-accent);color:var(--mm-accent-ink)}
.lb-alert.go{background:var(--mm-mint);color:var(--mm-mint-ink)}
.lb-alert.stop{background:var(--mm-orchid);color:var(--mm-orchid-ink)}
.lb-chip{display:inline-flex;align-items:center;gap:8px;height:40px;flex:none;padding:0 14px 0 8px;border-radius:999px;background:var(--mm-panel-2);
color:var(--mm-panel-muted);font-size:12px;white-space:nowrap}
.lb-chip b{display:inline-grid;place-items:center;min-width:22px;height:22px;padding:0 7px;border-radius:999px;background:var(--mm-panel-ink);
color:var(--mm-panel);font-size:11px;font-weight:650}
.round-btn,.livebar>.theme-btn{flex:none;height:52px;min-width:52px;padding:0 16px;border-radius:999px;border:0;background:var(--surface);color:var(--text);
font:inherit;font-size:13px;font-weight:500;cursor:pointer;box-shadow:0 4px 18px rgba(17,17,17,.06)}
.round-btn:hover,.livebar>.theme-btn:hover{background:var(--surface-2)}
/* workspace bar: view tabs (the sidebar groups), recorded model providers and a section/buyer search.
   Sticky right under the live bar (12px + 52px + 8px), so the views stay one click away while reading. */
.ws-bar{position:sticky;top:72px;z-index:5;display:flex;align-items:center;gap:10px;min-width:0;margin:0 0 30px;padding:6px;
border-radius:999px;background:var(--surface);box-shadow:0 4px 18px rgba(17,17,17,.06)}
.ws-tabs{display:flex;align-items:center;gap:2px;flex:1 1 auto;min-width:0;overflow-x:auto;scrollbar-width:none}
.ws-tabs::-webkit-scrollbar{display:none}
.ws-tab{display:inline-flex;align-items:center;gap:6px;flex:none;height:36px;font:inherit;font-size:13px;font-weight:500;color:var(--text-2);
background:transparent;border:0;border-radius:999px;padding:0 12px;cursor:pointer;white-space:nowrap;transition:background var(--dur) ease,color var(--dur) ease}
.ws-tab small{font-size:11px;color:var(--muted);font-variant-numeric:tabular-nums}
.ws-tab:hover{background:var(--surface-2);color:var(--text)}
.ws-tab[aria-pressed="true"]{background:var(--text);color:var(--surface)}
.ws-tab[aria-pressed="true"] small{color:color-mix(in srgb,var(--surface) 70%,transparent)}
.ws-tools{display:flex;align-items:center;gap:8px;flex:none;min-width:0}
.ws-provs{display:flex;align-items:center;gap:5px}
.ws-search-wrap{display:inline-flex;align-items:center;gap:6px;height:36px;background:var(--surface-2);border:0;border-radius:999px;padding:0 14px;color:var(--muted)}
.ws-search-wrap svg{width:14px!important;height:14px!important;flex:none}
.ws-search{border:0;background:transparent;color:var(--text);font:inherit;font-size:13px;width:180px;min-width:0;outline:0}
/* page header: eyebrow, large uppercase title, figures on the right */
.phead{display:flex!important;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:20px 40px;margin:0 0 22px!important}
.phead .ph-left{flex:1 1 420px;min-width:0}
.phead .eyebrow{margin:0 0 8px;font-size:13px;color:var(--muted)}
.phead h1{margin:0!important;max-width:none!important;font-size:clamp(2.2rem,4.6vw,3.6rem)!important;line-height:.95!important;
font-weight:500!important;letter-spacing:-.045em!important;text-transform:uppercase!important;overflow-wrap:anywhere}
.phead .req{margin:14px 0 0;max-width:72ch;color:var(--text-2);font-size:13.5px;line-height:1.5;display:-webkit-box;-webkit-line-clamp:3;
-webkit-box-orient:vertical;overflow:hidden}
.phead .ph-figs .kpis.hero{display:flex;flex-wrap:wrap;gap:20px 40px;margin:0}
.phead .ph-figs .kpis.hero .kpi{background:transparent;padding:0;min-width:0;box-shadow:none;border:0}
.phead .ph-figs .kpis.hero .kpi .v{font-size:2.6rem;letter-spacing:-.04em;line-height:1}
.phead .ph-figs .kpis.hero .kpi .k{margin-top:6px;font-size:13px;color:var(--text-2)}
.main section{scroll-margin-top:136px}
.main .section-head .sh-text::before{display:none!important}
.main .section-head h2{font-size:1.45rem;font-weight:500;letter-spacing:-.025em;color:var(--text)}
.round-btn svg{display:block;margin:auto;width:18px!important;height:18px!important}
.side nav.toc a i svg{width:17px!important;height:17px!important}.lb-ico svg{width:15px!important;height:15px!important}
.main .callout.disclaimer{background:transparent;border:0;padding:0;margin:0 0 26px;font-size:12.5px;color:var(--muted)}
.main .callout.disclaimer strong{color:var(--text-2)}
@media (max-width:1100px){.lb-chip{display:none}.ws-provs{display:none}}
@media (max-width:900px){
.app{display:block}
.side{position:sticky;top:0;z-index:7;height:auto;flex-direction:row;align-items:center;gap:8px;padding:8px 12px;
background:color-mix(in srgb,var(--bg) 92%,transparent);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px)}
.side-brand{height:36px;padding:0}.side-brand .word,.side-foot,.side .nav-h{display:none}
.side nav.toc{flex-direction:row;overflow-x:auto;scrollbar-width:none;flex:1;min-width:0;gap:4px}
.side .nav-group{display:contents}
.side nav.toc a{flex:none;height:34px;padding:0 12px}.side nav.toc a i{display:none}
.main .wrap{padding:14px 16px 48px}
.livebar{position:static;margin-bottom:12px}.lb-run{max-width:none;flex:1}.lb-right{flex:none}
.lb-alert .t{max-width:120px}.round-btn,.livebar>.theme-btn{height:46px;min-width:46px;padding:0 12px}
.ws-bar{top:60px;margin-bottom:20px}
.main section{scroll-margin-top:118px}}
@media (max-width:560px){.lb-run{display:none}.lb-right{flex:1;justify-content:flex-start}.lb-alert .t{max-width:none}
.phead .ph-figs .kpis.hero{gap:18px;flex-wrap:nowrap}.phead .ph-figs .kpis.hero .kpi .v{font-size:1.9rem}.phead .ph-figs .kpis.hero .kpi .k{font-size:12px}
.ws-tab{padding:0 10px}.ws-tab small{display:none}.ws-search-wrap{padding:0 10px}.ws-search{width:72px}}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .lb{box-shadow:inset 0 0 0 1px #ffffff14}
:root:not([data-theme="light"]) .ws-bar{box-shadow:inset 0 0 0 1px #ffffff10}}
:root[data-theme="dark"] .lb{box-shadow:inset 0 0 0 1px #ffffff14}
:root[data-theme="dark"] .ws-bar{box-shadow:inset 0 0 0 1px #ffffff10}
@media print{.side,.livebar,.ws-bar{display:none!important}.app{display:block}}
"""
