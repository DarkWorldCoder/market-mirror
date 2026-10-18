"""
tokens.py - the one place the dashboard's design tokens and shared components live.

TOKENS_CSS is appended *last* to the page <style>, so its :root palette wins over any
older per-module palette. It holds:

* the light palette on :root and ONE dark block (``_DARK``) that is emitted twice, under
  ``@media (prefers-color-scheme:dark){:root:not([data-theme="light"])}`` and under
  ``:root[data-theme="dark"]`` (the theme switcher sets ``data-theme``);
* typography (system stack; "Geist" is referenced but not bundled), radius, shadow and
  motion tokens;
* the shared components: ``.kpi`` tile (value + label + optional hint/delta), ``.pill``
  variants (mint = yes/go, accent = maybe/iterate, orchid = no/no-go, sky, neutral, plus
  pos/neg/neu for sentiment), ``.callout`` (insight), ``.section-head``, ``.filter-bar``,
  sortable-table affordances, the theme button, focus rings and reduced-motion rules.

Stdlib only. Every colour the renderers use should be a ``var(--...)`` defined here.
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# Palette
# --------------------------------------------------------------------------

_LIGHT = (
    "color-scheme:light;"
    "--bg:#eeeeea;--surface:#ffffff;--surface-2:#f6f6f3;--border:#dcdbd5;--line:#dcdbd5;"
    "--text:#111111;--text-2:#3d3d3a;--muted:#6b6b66;--grid:#e8e7e2;--axis:#c3c2b7;--accent:#111111;"
    "--edge:#b9b7ae;--other:#9a988f;"
    "--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;--s5:#e87ba4;--s6:#008300;--s7:#6250d6;--s8:#e34948;"
    "--div-neg2:#c43d3c;--div-neg1:#ec9a99;--div-mid:#b9b7ae;--div-pos1:#86b6ef;--div-pos2:#1c5cab;"
    "--pos-bg:#e3effd;--pos-fg:#184f95;--neg-bg:#fde6e6;--neg-fg:#9e2b2a;--neu-bg:#efeee9;--neu-fg:#52514e;"
    "--mm-accent:#f3d64b;--mm-accent-ink:#2b2005;--mm-accent-wash:#fbf1bf;"
    "--mm-panel:#121212;--mm-panel-2:#1d1d1c;--mm-panel-ink:#f2f2ee;--mm-panel-muted:#9a9a93;"
    "--mm-mint:#cfefd9;--mm-mint-ink:#0f3d22;--mm-orchid:#f1c6ee;--mm-orchid-ink:#4a1a46;"
    "--mm-sky:#cde7f6;--mm-sky-ink:#123a55;--mm-lav:#d9d0f5;"
    "--mm-yes:#2a78d6;--mm-maybe:#d6d5ce;--mm-no:#e34948;--mm-ink-bar:#111111;"
    "--mm-seq:#f6f6f3,#cde2fb,#86b6ef,#3987e5,#1c5cab,#0d366b;"
    "--focus:#2a78d6"
)

# One dark block, reused under both selectors below (never edit one copy only).
_DARK = (
    "color-scheme:dark;"
    "--bg:#0d0d0c;--surface:#1a1a19;--surface-2:#242422;--border:#33332f;--line:#33332f;"
    "--text:#f2f2ee;--text-2:#c3c2b7;--muted:#9a9a93;--grid:#2c2c2a;--axis:#383835;--accent:#f2f2ee;"
    "--edge:#55544e;--other:#7d7b74;"
    "--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;--s6:#008300;--s7:#9085e9;--s8:#e66767;"
    "--div-neg2:#e66767;--div-neg1:#9e4a49;--div-mid:#6b6a63;--div-pos1:#2f5f99;--div-pos2:#6da7ec;"
    "--pos-bg:#1d3350;--pos-fg:#9ec5f4;--neg-bg:#4a2222;--neg-fg:#f3b0af;--neu-bg:#2c2c29;--neu-fg:#c3c2b7;"
    "--mm-accent:#f3d64b;--mm-accent-ink:#2b2005;--mm-accent-wash:#3a3210;"
    "--mm-panel:#000000;--mm-panel-2:#161615;--mm-panel-ink:#f2f2ee;--mm-panel-muted:#9a9a93;"
    "--mm-mint:#1f3a28;--mm-mint-ink:#bfe8cc;--mm-orchid:#3d2240;--mm-orchid-ink:#f1c6ee;"
    "--mm-sky:#1d3340;--mm-sky-ink:#bfe0f5;--mm-lav:#2b2546;"
    "--mm-yes:#3987e5;--mm-maybe:#4a4a46;--mm-no:#e66767;--mm-ink-bar:#f2f2ee;"
    "--mm-seq:#242422,#0d366b,#1c5cab,#3987e5,#86b6ef,#cde2fb;"
    "--focus:#86b6ef"
)

# Typography, radius, shadow and motion: the same in both themes.
_SCALE = (
    '--font-sans:"Geist",system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,"Noto Sans",'
    '"PingFang SC","Microsoft YaHei",sans-serif;'
    "--font-mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;"
    "--fs-xs:.74rem;--fs-sm:.82rem;--fs-md:.9rem;--fs-base:14px;--fs-lg:1.02rem;--fs-xl:1.35rem;--fs-2xl:2rem;"
    "--fs-hero:clamp(2.1rem,4.4vw,3.5rem);"
    "--r-sm:6px;--r-md:12px;--r-lg:20px;--r-xl:24px;--r-pill:999px;"
    "--shadow-1:0 1px 2px rgba(17,17,17,.05);--shadow-2:0 10px 26px rgba(17,17,17,.07);"
    "--ease:cubic-bezier(.22,1,.36,1);--dur:.18s"
)

_COMPONENTS = """
html{scroll-behavior:smooth}
body{font-family:var(--font-sans);font-size:var(--fs-base)}
code,pre,kbd{font-family:var(--font-mono)}
/* KPI tile: value + label + optional hint (.h) and delta (.d) */
.kpis{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.kpis.auto{grid-template-columns:repeat(auto-fit,minmax(150px,1fr));margin:0 0 18px}
.kpi{background:var(--surface);border-radius:var(--r-lg);padding:16px 18px;min-width:0}
.kpi .v{font-size:var(--fs-2xl);font-weight:500;letter-spacing:-.04em;line-height:1.05;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
.kpi .k{color:var(--text-2);font-size:.85rem;margin-top:4px}
.kpi .h{color:var(--muted);font-size:var(--fs-xs);margin-top:2px}
.kpi .d{font-size:var(--fs-sm);margin-top:4px;font-variant-numeric:tabular-nums}
.kpi .d.up{color:var(--s3)}.kpi .d.down{color:var(--s8)}
.kpi.hl{background:var(--mm-accent);color:var(--mm-accent-ink)}.kpi.hl .k,.kpi.hl .h,.kpi.hl .d{color:var(--mm-accent-ink)}
.kpi.sm{padding:10px 12px;border-radius:var(--r-md);background:var(--surface)}
.kpi.sm .v{font-size:1.15rem;letter-spacing:-.02em}.kpi.sm .k{font-size:.75rem;color:var(--muted);margin-top:2px}
.kpis.hero{display:flex;gap:28px;flex-wrap:wrap}
.kpis.hero .kpi{background:transparent;padding:0;min-width:90px;border-radius:0}
.kpis.hero .kpi .v{font-size:2.4rem}.kpis.hero .kpi .k{color:var(--muted);font-size:var(--fs-sm)}
#report .kpi,#agents .kpi,#timeline .kpi,#graph .kpi,#overview .kpi,.card .kpi{background:var(--surface-2)}
.card .kpi.hl{background:var(--mm-accent)}
/* pills */
.pill{display:inline-block;font-size:var(--fs-xs);font-weight:500;line-height:1.5;border-radius:var(--r-pill);padding:3px 10px;
background:var(--surface-2);color:var(--text-2);font-variant-numeric:tabular-nums}
.pill.neutral{background:var(--surface-2);color:var(--text-2)}
.pill.mint{background:var(--mm-mint);color:var(--mm-mint-ink)}
.pill.accent{background:var(--mm-accent);color:var(--mm-accent-ink)}
.pill.orchid{background:var(--mm-orchid);color:var(--mm-orchid-ink)}
.pill.sky{background:var(--mm-sky);color:var(--mm-sky-ink)}
.pill.pos{background:var(--pos-bg);color:var(--pos-fg)}.pill.neg{background:var(--neg-bg);color:var(--neg-fg)}
.pill.neu{background:var(--neu-bg);color:var(--neu-fg)}
.pill.lg{font-size:1.1rem;padding:6px 14px}
.panel .pill,.play.p-high .pill{background:var(--mm-panel-2);color:var(--mm-panel-ink)}
.panel .pill.mint,.play.p-high .pill.mint{background:var(--mm-mint);color:var(--mm-mint-ink)}
.panel .pill.accent,.play.p-high .pill.accent{background:var(--mm-accent);color:var(--mm-accent-ink)}
.panel .pill.orchid,.play.p-high .pill.orchid{background:var(--mm-orchid);color:var(--mm-orchid-ink)}
/* section head + insight callout */
.section-head{margin:0 0 14px}
.section-head .sh-row{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap}
.section-head .sh-text{min-width:0;flex:1 1 320px}
.section-head h2{margin:0 0 4px}
.section-head .intro{margin:0;color:var(--muted);font-size:var(--fs-sm);max-width:90ch}
.callout{background:var(--surface);border-radius:var(--r-md);padding:12px 16px;border-left:4px solid var(--mm-accent)}
.callout.insight{margin-top:10px;display:flex;gap:10px;align-items:flex-start;font-size:var(--fs-md)}
.callout.insight::before{content:"Insight";flex:none;font-size:.68rem;font-weight:600;letter-spacing:.08em;text-transform:uppercase;
color:var(--mm-accent-ink);background:var(--mm-accent);border-radius:var(--r-pill);padding:3px 8px;margin-top:1px}
#report .callout,#agents .callout,#timeline .callout,#graph .callout,#overview .callout,#engine-report .callout{background:var(--surface-2)}
/* voices */
.voices{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px}
blockquote.voice{margin:0;background:var(--surface-2);border-left:3px solid var(--mm-accent);border-radius:0 14px 14px 0;padding:10px 14px}
blockquote.voice p{margin:0 0 6px}blockquote.voice footer{color:var(--muted);font-size:var(--fs-sm)}
/* filter bar (social feed, people) */
.filter-bar{display:flex;flex-wrap:wrap;gap:10px 14px;align-items:center;margin:12px 0 14px;font-size:.88rem}
.filter-bar select,.filter-bar input[type=text]{font:inherit;font-size:.86rem;color:var(--text);background:var(--surface);
border:1px solid var(--border);border-radius:var(--r-pill);padding:5px 10px;max-width:100%}
.filter-bar input[type=range]{width:140px;vertical-align:middle;accent-color:var(--text)}
.filter-bar label{display:inline-flex;gap:6px;align-items:center}
.filter-bar output{min-width:3ch;display:inline-block;color:var(--text-2);font-variant-numeric:tabular-nums}
.filter-bar [data-filter-count]{margin-left:auto;color:var(--muted);font-size:var(--fs-sm)}
#agents .filter-bar select{background:var(--surface-2)}
[data-item][hidden]{display:none}
@media (max-width:700px){.filter-bar [data-filter-count]{margin-left:0}}
/* sortable tables */
table.sortable th{cursor:pointer;user-select:none;white-space:nowrap}
table.sortable th::after{content:"";display:inline-block;width:.5em;margin-left:.3em;opacity:.45}
table.sortable th[aria-sort="ascending"]::after{content:"▲";opacity:1}
table.sortable th[aria-sort="descending"]::after{content:"▼";opacity:1}
table.sortable th:hover{color:var(--text)}
/* sticky nav + scrollspy */
nav.toc{position:sticky;top:0;z-index:5;background:var(--bg)}
nav.toc a{transition:background var(--dur) var(--ease),color var(--dur) var(--ease),border-color var(--dur) var(--ease)}
nav.toc a[aria-current="true"]{background:var(--text);border-color:var(--text);color:var(--surface)}
@media (max-width:640px){nav.toc{position:sticky}}
/* theme button */
.theme-btn{font:inherit;font-size:var(--fs-sm);font-weight:500;border:1px solid var(--border);background:var(--surface);color:var(--text);
border-radius:var(--r-pill);padding:6px 12px;cursor:pointer;display:inline-flex;gap:6px;align-items:center;white-space:nowrap}
.theme-btn:hover{border-color:var(--text)}
header.top .hdr-tools{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
/* keyboard focus */
a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible,[tabindex]:focus-visible{
outline:2px solid var(--focus);outline-offset:2px;border-radius:var(--r-sm)}
nav.toc a:focus-visible,.pill:focus-visible,button:focus-visible{border-radius:var(--r-pill)}
/* motion */
@media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}*,*::before,*::after{animation-duration:.01ms!important;
animation-iteration-count:1!important;transition-duration:.01ms!important}}
@media print{.theme-btn,.filter-bar,nav.toc{display:none!important}details.tv{display:block}.callout.insight{break-inside:avoid}}
"""

TOKENS_CSS = (
    f":root{{{_LIGHT};{_SCALE}}}\n"
    f'@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{{_DARK}}}}}\n'
    f':root[data-theme="dark"]{{{_DARK}}}\n'
    + _COMPONENTS
)
