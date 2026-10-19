"""
shell.py - the dashboard's app frame: a fixed left sidebar (brand, run, grouped section navigation with
scrollspy, theme switch) and a sticky top bar (breadcrumb, title, status chips, print). On phones the sidebar
becomes a sticky strip of section pills. Only markup and CSS; the sections themselves are unchanged. Stdlib only.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

try:  # stdlib only
    import ui  # type: ignore
    import tokens  # type: ignore
except ImportError:  # pragma: no cover - imported as a package
    from . import ui  # type: ignore
    from . import tokens  # type: ignore

_e = ui.esc

GROUPS: List[Tuple[str, Sequence[str]]] = [
    ("Overview", ("kpis", "decision", "worldmap", "report", "brief")),
    ("Buyers", ("results", "ratings", "funnel", "audiences", "objections", "messages", "pricing", "voices")),
    ("Tests", ("feedtest", "socialfeed", "posts", "email", "emailtest", "pitch", "website", "playbook", "ideas")),
    ("Evidence", ("scenarios", "study", "campaign", "research", "evidence", "predictions", "prediction", "analysts", "backtest", "run-health")),
    ("Behind the run", ("agents", "timeline", "graph", "overview", "engine-report")),
]


def _glyph(anchor: str) -> Tuple[str, int]:
    meta = tokens.SECTION_META.get(anchor)
    return (meta[1], meta[2]) if meta else ("•", 6)


def sidebar(nav: List[Tuple[str, str]], title: str, subtitle: str = "", status: Optional[str] = None) -> str:
    """The left rail. ``nav`` is [(anchor, label)] in page order; anchors are grouped by GROUPS, unknown ones last."""
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
        f'<div class="nav-group"><div class="nav-h">{_e(name)}</div>'
        + "".join(f'<a href="#{_e(a)}" style="--kc:var(--s{_glyph(a)[1]})"><i aria-hidden="true">{_glyph(a)[0]}</i>'
                  f'<span>{_e(b)}</span></a>' for a, b in items) + "</div>"
        for name, items in blocks)
    return (
        '<aside class="side" aria-label="Dashboard">'
        '<div class="side-brand"><span class="logo" aria-hidden="true">◐</span><div><b>MarketMirror</b>'
        '<small>simulated market test</small></div></div>'
        f'<div class="side-run"><div class="side-run-t" title="{_e(title)}">{_e(ui.trunc(title, 60))}</div>'
        + (f'<div class="side-run-s">{_e(subtitle)}</div>' if subtitle else "")
        + (f'<div class="side-status">{status}</div>' if status else "") + "</div>"
        '<div class="side-tools"><button type="button" class="theme-btn" data-theme-toggle aria-pressed="false" '
        'aria-label="Switch to dark theme">☾ Dark</button>'
        '<button type="button" class="theme-btn" onclick="window.print()" aria-label="Print or save as PDF">⎙ PDF</button></div>'
        f'<nav class="toc" data-scrollspy aria-label="Sections">{links}</nav>'
        '<div class="side-foot">Simulated people, simulated answers. Directions with margins, not measurements.</div>'
        "</aside>")


def chips(items: List[Tuple[str, str, Optional[str]]]) -> str:
    """Status chips for the top bar: [(value, label, tone)] with tone in go / iterate / stop / None."""
    return '<div class="chips">' + "".join(
        f'<span class="chip{" " + tone if tone else ""}"><b>{_e(v)}</b> {_e(label)}</span>' for v, label, tone in items if v) + "</div>"


SHELL_CSS = """
body{margin:0}
.app{display:grid;grid-template-columns:248px minmax(0,1fr);min-height:100vh}
.side{position:sticky;top:0;height:100vh;overflow-y:auto;scrollbar-width:thin;display:flex;flex-direction:column;gap:14px;
padding:18px 14px 16px;background:var(--mm-panel);color:var(--mm-panel-ink);border-right:1px solid var(--mm-panel-2)}
.side-brand{display:flex;gap:10px;align-items:center}
.side-brand .logo{display:grid;place-items:center;width:34px;height:34px;border-radius:10px;background:var(--mm-accent);color:var(--mm-accent-ink);font-size:1.15rem}
.side-brand b{display:block;font-size:.98rem;letter-spacing:-.01em}
.side-brand small{color:var(--mm-panel-muted);font-size:.72rem}
.side-run{background:var(--mm-panel-2);border-radius:12px;padding:10px 12px}
.side-run-t{font-weight:600;font-size:.86rem;line-height:1.25}
.side-run-s{color:var(--mm-panel-muted);font-size:.74rem;margin-top:3px}
.side-status{margin-top:8px}
.side-tools{display:flex;gap:6px}
.side .theme-btn{flex:1;background:var(--mm-panel-2);color:var(--mm-panel-ink);border:1px solid #ffffff1a;font-size:.78rem;padding:6px 8px;border-radius:9px;cursor:pointer}
.side .theme-btn:hover{border-color:#ffffff40}
.side nav.toc{position:static;display:block;margin:0;padding:0;background:transparent;overflow:visible}
.side .nav-group{margin-bottom:10px}
.side .nav-h{font-size:.66rem;text-transform:uppercase;letter-spacing:.09em;color:var(--mm-panel-muted);margin:0 8px 4px}
.side nav.toc a{display:flex;align-items:center;gap:9px;border:0;background:transparent;color:#d6d6d0;padding:6px 8px;
border-radius:8px;font-size:.84rem;text-decoration:none;white-space:nowrap}
.side nav.toc a i{display:grid;place-items:center;width:22px;height:22px;border-radius:7px;font-style:normal;font-size:.78rem;
background:color-mix(in srgb,var(--kc) 22%,transparent);color:color-mix(in srgb,var(--kc) 70%,#fff)}
.side nav.toc a:hover{background:#ffffff12;color:#fff}
.side nav.toc a[aria-current="true"]{background:#ffffff1c;color:#fff;box-shadow:inset 3px 0 0 var(--kc)}
.side-foot{margin-top:auto;color:var(--mm-panel-muted);font-size:.7rem;line-height:1.4}
.main{min-width:0}
.main .wrap{max-width:1320px;padding:0 28px 64px}
.topbar{position:sticky;top:0;z-index:6;display:flex;flex-wrap:wrap;gap:10px 18px;align-items:center;justify-content:space-between;
margin:0 -28px 18px;padding:12px 28px;background:color-mix(in srgb,var(--bg) 86%,transparent);backdrop-filter:blur(10px);
-webkit-backdrop-filter:blur(10px);border-bottom:1px solid var(--border)}
.topbar>div:first-child{flex:1 1 320px;min-width:0}.topbar h1{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:none!important}
.topbar .crumb{font-size:.74rem;color:var(--muted)}
.topbar h1{font-size:1.32rem!important;line-height:1.15!important;letter-spacing:-.02em!important;text-transform:none!important;margin:2px 0 0!important;font-weight:650!important}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{font-size:.78rem;padding:5px 10px;border-radius:999px;background:var(--surface);border:1px solid var(--border);color:var(--text-2);white-space:nowrap}
.chip b{color:var(--text);font-weight:650}
.chip.go{background:var(--mm-mint);color:var(--mm-mint-ink);border-color:transparent}
.chip.iterate{background:var(--mm-accent);color:var(--mm-accent-ink);border-color:transparent}
.chip.stop{background:var(--mm-orchid);color:var(--mm-orchid-ink);border-color:transparent}
.chip.go b,.chip.iterate b,.chip.stop b{color:inherit}
.hero-row{display:flex;flex-wrap:wrap;gap:12px 24px;align-items:flex-end;justify-content:space-between;margin:4px 0 6px}
.hero-row .req{color:var(--text-2);max-width:80ch;font-size:.9rem;margin:0}
.hero-row .kpis.hero{margin:0}
.main section{scroll-margin-top:96px}
@media (max-width:900px){
.app{display:block}
.side{position:sticky;top:0;z-index:7;height:auto;flex-direction:row;align-items:center;gap:8px;padding:8px 12px;overflow:visible}
.side-brand small,.side-run,.side-foot,.side .nav-h{display:none}
.side-brand b{font-size:.86rem}.side-brand .logo{width:28px;height:28px}
.side-tools{order:3}.side .theme-btn{padding:5px 8px}
.side nav.toc{display:flex;overflow-x:auto;scrollbar-width:none;flex:1;min-width:0;gap:4px}
.side .nav-group{display:contents}
.side nav.toc a{flex:none;padding:5px 9px}.side nav.toc a i{display:none}
.main .wrap{padding:0 16px 48px}
.topbar{position:static;margin:0 -16px 14px;padding:10px 16px}
.main section{scroll-margin-top:60px}}
@media (max-width:560px){.side-brand div{display:none}.side-tools .theme-btn+.theme-btn{display:none}.hero-row .req{display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;font-size:.85rem}.hero-row .kpis.hero{gap:18px;flex-wrap:nowrap}.hero-row .kpis.hero .kpi{min-width:0}.hero-row .kpis.hero .kpi .v{font-size:1.6rem}.hero-row .kpis.hero .kpi .k{font-size:.72rem}.topbar h1{font-size:1.15rem!important}.chip{font-size:.72rem;padding:4px 8px}}
@media print{.side,.topbar .chips{display:none!important}.app{display:block}.topbar{position:static;background:none;border:0}}
"""
