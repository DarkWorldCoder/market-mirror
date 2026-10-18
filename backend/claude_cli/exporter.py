"""
Self-contained HTML dashboard exporter for MiroFish runs (stdlib only).

Input is a *run directory* (as written by ``mirofish.py run`` / ``export``)
containing any subset of these JSON files::

    project.json        GET /api/graph/project/<id>            -> data
    graph.json          GET /api/graph/data/<graph_id>          -> data {nodes, edges}
    simulation.json     GET /api/simulation/<id>                -> data
    config.json         GET /api/simulation/<id>/config         -> data
    profiles_twitter.json / profiles_reddit.json
                        GET /api/simulation/<id>/profiles       -> data.profiles
    run_status.json     GET /api/simulation/<id>/run-status     -> data
    timeline.json       GET /api/simulation/<id>/timeline       -> data.timeline
    actions.json        GET /api/simulation/<id>/actions        -> data.actions (all pages)
    agent_stats.json    GET /api/simulation/<id>/agent-stats    -> data.stats
    posts_twitter.json / posts_reddit.json       -> data.posts
    comments_twitter.json / comments_reddit.json -> data.comments
    report.json         GET /api/report/<report_id>             -> data

Everything is rendered server-side: the knowledge graph layout is computed in
Python and emitted as inline SVG, charts are inline SVG, the report markdown is
converted with a small built-in converter. The only JavaScript is an optional
inline tooltip helper; the page is fully readable without it.

Outputs: dashboard HTML, report.md, summary.json.
"""

from __future__ import annotations

import html
import json
import math
import os
import random
import re
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

try:  # marketing layer (stdlib only)
    import marketing  # type: ignore
    import feed_view  # type: ignore
    import report_view  # type: ignore
except ImportError:  # pragma: no cover - imported as a package
    from . import marketing  # type: ignore
    from . import feed_view  # type: ignore
    from . import report_view  # type: ignore
try:  # social feed section (Phase 2, optional until wired)
    import social_feed  # type: ignore
except ImportError:  # pragma: no cover
    try:
        from . import social_feed  # type: ignore
    except ImportError:
        social_feed = None

VENDOR_ECHARTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor", "echarts.min.js")


def _echarts_inline() -> str:
    """Apache ECharts (Apache-2.0), inlined so the dashboard stays one self-contained, offline file."""
    try:
        with open(VENDOR_ECHARTS, "r", encoding="utf-8") as f:
            return f.read().replace("</script", "<\\/script")
    except OSError:
        return ""


RUN_FILES = [
    "project", "graph", "simulation", "config", "profiles_twitter",
    "profiles_reddit", "run_status", "timeline", "actions", "agent_stats",
    "posts_twitter", "posts_reddit", "comments_twitter", "comments_reddit",
    "report", "survey", "feed_test", "analyst_panel", "backtest", "run_manifest", "market_report", "feed_story",
]


def _unwrap(obj: Any, *keys: str) -> Any:
    """Accept either the raw API envelope ({success, data}) or the payload."""
    if isinstance(obj, dict) and "success" in obj and "data" in obj:
        obj = obj["data"]
    for k in keys:
        if isinstance(obj, dict) and k in obj:
            obj = obj[k]
    return obj


def load_run_dir(run_dir: str) -> Dict[str, Any]:
    bundle: Dict[str, Any] = {}
    for name in RUN_FILES:
        path = os.path.join(run_dir, f"{name}.json")
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                bundle[name] = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
    # Normalise shapes
    for key, inner in [
        ("profiles_twitter", "profiles"), ("profiles_reddit", "profiles"),
        ("timeline", "timeline"), ("actions", "actions"), ("agent_stats", "stats"),
        ("posts_twitter", "posts"), ("posts_reddit", "posts"),
        ("comments_twitter", "comments"), ("comments_reddit", "comments"),
    ]:
        if key in bundle:
            bundle[key] = _unwrap(bundle[key], inner)
    for key in ["project", "graph", "simulation", "config", "run_status", "report"]:
        if key in bundle:
            bundle[key] = _unwrap(bundle[key])
    return bundle


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def esc(v: Any) -> str:
    return html.escape("" if v is None else str(v), quote=True)


def trunc(s: Any, n: int) -> str:
    s = "" if s is None else str(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def as_list(v: Any) -> List[Any]:
    return v if isinstance(v, list) else []


def fmt_num(n: Any) -> str:
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "–"
    if n == int(n):
        return f"{int(n):,}"
    return f"{n:,.2f}"


# Categorical palette: fixed order, light / dark steps (validated reference palette).
SERIES_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
SERIES_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]
MAX_SERIES = len(SERIES_LIGHT)
OTHER = "Other"
DASH = "\u2013"


def assign_slots(keys_by_weight: List[str]) -> Dict[str, int]:
    """Give the top-7 keys slots 0..6; everything else folds into 'Other' (slot -1).
    If there are <= 8 keys every key gets its own slot."""
    if len(keys_by_weight) <= MAX_SERIES:
        return {k: i for i, k in enumerate(keys_by_weight)}
    slots = {k: i for i, k in enumerate(keys_by_weight[: MAX_SERIES - 1])}
    for k in keys_by_weight[MAX_SERIES - 1:]:
        slots[k] = -1
    return slots


def slot_var(slot: int) -> str:
    return "var(--other)" if slot < 0 else f"var(--s{slot + 1})"


# --------------------------------------------------------------------------
# Markdown -> HTML (small, safe subset)
# --------------------------------------------------------------------------

_INLINE_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_ITAL = re.compile(r"(?<![\*\w])\*(?!\s)(.+?)(?<!\s)\*(?!\*)|(?<![_\w])_(?!\s)(.+?)(?<!\s)_(?![_\w])")
_STRIKE = re.compile(r"~~(.+?)~~")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")


def _inline(text: str) -> str:
    codes: List[str] = []

    def _code(m):
        codes.append(m.group(1))
        return f"\x00{len(codes) - 1}\x00"

    text = _INLINE_CODE.sub(_code, text)
    text = esc(text)

    def _link(m):
        label, url = m.group(1), html.unescape(m.group(2))
        if not re.match(r"^(https?:|mailto:|#)", url):
            return label
        return f'<a href="{esc(url)}" rel="noopener">{label}</a>'

    text = _LINK.sub(_link, text)
    text = _BOLD.sub(lambda m: f"<strong>{m.group(1) or m.group(2)}</strong>", text)
    text = _ITAL.sub(lambda m: f"<em>{m.group(1) or m.group(2)}</em>", text)
    text = _STRIKE.sub(lambda m: f"<del>{m.group(1)}</del>", text)
    text = re.sub(r"\x00(\d+)\x00", lambda m: f"<code>{esc(codes[int(m.group(1))])}</code>", text)
    return text


def markdown_to_html(md: str) -> str:
    """Convert a practical Markdown subset: ATX headings, paragraphs, emphasis,
    inline code, fenced code, links, nested ul/ol, blockquotes, hr, tables."""
    if not md:
        return ""
    lines = md.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: List[str] = []
    i = 0
    para: List[str] = []

    def flush_para():
        if para:
            out.append("<p>" + "<br>".join(_inline(p) for p in para) + "</p>")
            para.clear()

    list_re = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```") or stripped.startswith("~~~"):
            flush_para()
            fence = stripped[:3]
            lang = stripped[3:].strip()
            i += 1
            buf = []
            while i < len(lines) and not lines[i].strip().startswith(fence):
                buf.append(lines[i])
                i += 1
            i += 1
            cls = f' class="lang-{esc(lang)}"' if lang else ""
            out.append(f"<pre><code{cls}>{esc(chr(10).join(buf))}</code></pre>")
            continue

        if not stripped:
            flush_para()
            i += 1
            continue

        m = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", stripped)
        if m:
            flush_para()
            level = len(m.group(1))
            out.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
            i += 1
            continue

        if re.match(r"^([-*_])(\s*\1){2,}$", stripped):
            flush_para()
            out.append("<hr>")
            i += 1
            continue

        if stripped.startswith(">"):
            flush_para()
            buf = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                buf.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            out.append(f"<blockquote>{markdown_to_html(chr(10).join(buf))}</blockquote>")
            continue

        if "|" in stripped and i + 1 < len(lines) and re.match(
            r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$", lines[i + 1]
        ):
            flush_para()

            def cells(row: str) -> List[str]:
                row = row.strip()
                if row.startswith("|"):
                    row = row[1:]
                if row.endswith("|"):
                    row = row[:-1]
                return [c.strip() for c in row.split("|")]

            head = cells(lines[i])
            i += 2
            rows = []
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append(cells(lines[i]))
                i += 1
            t = ['<div class="tbl"><table><thead><tr>']
            t += [f"<th>{_inline(c)}</th>" for c in head]
            t.append("</tr></thead><tbody>")
            for r in rows:
                t.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>")
            t.append("</tbody></table></div>")
            out.append("".join(t))
            continue

        if list_re.match(line):
            flush_para()
            items: List[Tuple[int, bool, str]] = []
            while i < len(lines):
                lm = list_re.match(lines[i])
                if lm:
                    indent = len(lm.group(1).replace("\t", "    "))
                    items.append((indent, lm.group(2)[0].isdigit(), lm.group(3)))
                    i += 1
                elif lines[i].strip() and items and lines[i].startswith((" ", "\t")):
                    ind, ordered, txt = items[-1]
                    items[-1] = (ind, ordered, txt + " " + lines[i].strip())
                    i += 1
                else:
                    break
            out.append(_render_list(items))
            continue

        para.append(stripped)
        i += 1

    flush_para()
    return "\n".join(out)


def _render_list(items: List[Tuple[int, bool, str]]) -> str:
    html_parts: List[str] = []
    stack: List[Tuple[int, str]] = []  # (indent, tag)
    for indent, ordered, text in items:
        tag = "ol" if ordered else "ul"
        if not stack or indent > stack[-1][0]:
            html_parts.append(f"<{tag}>")
            stack.append((indent, tag))
        else:
            while len(stack) > 1 and indent < stack[-1][0]:
                html_parts.append(f"</li></{stack.pop()[1]}>")
            html_parts.append("</li>")
        html_parts.append(f"<li>{_inline(text)}")
    while stack:
        html_parts.append(f"</li></{stack.pop()[1]}>")
    return "".join(html_parts)


# --------------------------------------------------------------------------
# Knowledge graph: force layout in pure Python -> inline SVG
# --------------------------------------------------------------------------

GENERIC_LABELS = {"Entity", "Node", "entity", "node"}


def node_type(node: Dict[str, Any]) -> str:
    for lab in as_list(node.get("labels")):
        if lab not in GENERIC_LABELS:
            return str(lab)
    return "Entity"


def force_layout(n: int, edges: List[Tuple[int, int]], groups: List[int],
                 width: float, height: float, seed: int = 7) -> List[Tuple[float, float]]:
    """Fruchterman-Reingold with cooling; deterministic. Nodes of the same
    group start near each other so communities stay readable."""
    if n == 0:
        return []
    rnd = random.Random(seed)
    n_groups = max(groups) + 1 if groups else 1
    pos = []
    for i in range(n):
        g = groups[i]
        ang = 2 * math.pi * g / n_groups
        cx = width / 2 + math.cos(ang) * width * 0.25
        cy = height / 2 + math.sin(ang) * height * 0.25
        pos.append([cx + rnd.uniform(-40, 40), cy + rnd.uniform(-40, 40)])
    if n == 1:
        return [(width / 2, height / 2)]
    area = width * height
    k = math.sqrt(area / n) * 0.75
    iters = int(max(40, min(300, 12_000_000 / (n * n))))
    temp = width / 8
    cool = temp / (iters + 1)
    for _ in range(iters):
        disp = [[0.0, 0.0] for _ in range(n)]
        for a in range(n):
            pa = pos[a]
            da = disp[a]
            for b in range(a + 1, n):
                dx = pa[0] - pos[b][0]
                dy = pa[1] - pos[b][1]
                d2 = dx * dx + dy * dy + 0.01
                f = k * k / d2
                da[0] += dx * f
                da[1] += dy * f
                disp[b][0] -= dx * f
                disp[b][1] -= dy * f
        for a, b in edges:
            dx = pos[a][0] - pos[b][0]
            dy = pos[a][1] - pos[b][1]
            d = math.sqrt(dx * dx + dy * dy) + 0.01
            f = d / k
            disp[a][0] -= dx * f
            disp[a][1] -= dy * f
            disp[b][0] += dx * f
            disp[b][1] += dy * f
        for i in range(n):
            # gentle gravity to centre keeps disconnected parts on canvas
            disp[i][0] += (width / 2 - pos[i][0]) * 0.02 * k / 10
            disp[i][1] += (height / 2 - pos[i][1]) * 0.02 * k / 10
            dx, dy = disp[i]
            d = math.sqrt(dx * dx + dy * dy) + 0.01
            step = min(d, temp)
            pos[i][0] += dx / d * step
            pos[i][1] += dy / d * step
        temp = max(temp - cool, 1.0)
    # fit to box with margin
    mx, my = 90, 36  # room for labels
    xs = [p[0] for p in pos]
    ys = [p[1] for p in pos]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    sx = (width - 2 * mx) / max(maxx - minx, 1e-6)
    sy = (height - 2 * my) / max(maxy - miny, 1e-6)
    s = min(sx, sy)
    ox = (width - (maxx - minx) * s) / 2
    oy = (height - (maxy - miny) * s) / 2
    return [((p[0] - minx) * s + ox, (p[1] - miny) * s + oy) for p in pos]


def render_graph(graph: Dict[str, Any], max_nodes: int = 300) -> Tuple[str, Dict[str, Any]]:
    nodes = as_list(graph.get("nodes"))
    edges = as_list(graph.get("edges"))
    if not nodes:
        return '<p class="empty">No graph data in this run.</p>', {"node_count": 0, "edge_count": 0}

    by_uuid = {n.get("uuid"): n for n in nodes if n.get("uuid")}
    degree: Counter = Counter()
    for e in edges:
        degree[e.get("source_node_uuid")] += 1
        degree[e.get("target_node_uuid")] += 1

    keep = sorted(by_uuid, key=lambda u: (-degree[u], str(by_uuid[u].get("name"))))[:max_nodes]
    keep_set = set(keep)
    type_counts = Counter(node_type(by_uuid[u]) for u in keep)
    types_sorted = [t for t, _ in type_counts.most_common()]
    slots = assign_slots(types_sorted)
    group_ids = {t: i for i, t in enumerate(types_sorted)}

    idx = {u: i for i, u in enumerate(keep)}
    kept_edges = [e for e in edges
                  if e.get("source_node_uuid") in keep_set and e.get("target_node_uuid") in keep_set
                  and e.get("source_node_uuid") != e.get("target_node_uuid")]
    pairs = [(idx[e["source_node_uuid"]], idx[e["target_node_uuid"]]) for e in kept_edges]
    W, H = 1000.0, 680.0
    pos = force_layout(len(keep), pairs, [group_ids[node_type(by_uuid[u])] for u in keep], W, H)

    maxdeg = max([degree[u] for u in keep] + [1])
    label_nodes = set(keep[: 30])
    show_edge_labels = len(kept_edges) <= 60

    parts = [f'<svg class="graph" viewBox="0 0 {int(W)} {int(H)}" role="img" '
             f'aria-label="Knowledge graph with {len(keep)} entities and {len(kept_edges)} relations">',
             '<defs><marker id="arr" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="6" markerHeight="6" '
             'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="arrow"/></marker></defs>',
             '<g class="edges">']
    for e in kept_edges:
        a, b = idx[e["source_node_uuid"]], idx[e["target_node_uuid"]]
        (x1, y1), (x2, y2) = pos[a], pos[b]
        ra = 5 + 7 * math.sqrt(degree[keep[b]] / maxdeg)
        dx, dy = x2 - x1, y2 - y1
        d = math.hypot(dx, dy) or 1
        x2e, y2e = x2 - dx / d * (ra + 2), y2 - dy / d * (ra + 2)
        label = e.get("name") or e.get("fact_type") or ""
        tip = f"{by_uuid[keep[a]].get('name')} → {label} → {by_uuid[keep[b]].get('name')}"
        if e.get("fact"):
            tip += f"\n{trunc(e.get('fact'), 220)}"
        parts.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2e:.1f}" y2="{y2e:.1f}" '
                     f'marker-end="url(#arr)" data-tip="{esc(tip)}"><title>{esc(tip)}</title></line>')
    parts.append("</g>")
    parts.append('<g class="elabels">')
    for e in kept_edges:
        a, b = idx[e["source_node_uuid"]], idx[e["target_node_uuid"]]
        (x1, y1), (x2, y2) = pos[a], pos[b]
        label = e.get("name") or e.get("fact_type") or ""
        if label:
            parts.append(f'<text x="{(x1 + x2) / 2:.1f}" y="{(y1 + y2) / 2:.1f}">{esc(trunc(label, 24))}</text>')
    parts.append("</g><g class=\"nodes\">")
    for i, u in enumerate(keep):
        n = by_uuid[u]
        x, y = pos[i]
        t = node_type(n)
        r = 5 + 7 * math.sqrt(degree[u] / maxdeg)
        tip = f"{n.get('name')} [{t}] · {degree[u]} relations"
        if n.get("summary"):
            tip += f"\n{trunc(n.get('summary'), 260)}"
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" style="fill:{slot_var(slots[t])}" '
                     f'data-tip="{esc(tip)}"><title>{esc(tip)}</title></circle>')
    parts.append('</g><g class="nlabels">')
    for i, u in enumerate(keep):
        if u in label_nodes:
            x, y = pos[i]
            r = 5 + 7 * math.sqrt(degree[u] / maxdeg)
            parts.append(f'<text x="{x:.1f}" y="{y - r - 4:.1f}">{esc(trunc(by_uuid[u].get("name"), 22))}</text>')
    parts.append("</g></svg>")

    legend = ['<ul class="legend">']
    other_count = 0
    for t in types_sorted:
        if slots[t] < 0:
            other_count += type_counts[t]
            continue
        legend.append(f'<li><span class="sw" style="background:{slot_var(slots[t])}"></span>'
                      f'{esc(t)} <span class="muted">{type_counts[t]}</span></li>')
    if other_count:
        legend.append(f'<li><span class="sw" style="background:var(--other)"></span>{OTHER} '
                      f'<span class="muted">{other_count}</span></li>')
    legend.append("</ul>")

    note = ""
    if len(nodes) > len(keep):
        note = f'<p class="muted small">Showing the {len(keep)} most-connected of {len(nodes)} entities.</p>'
    toggle = ('<label class="toggle"><input type="checkbox" id="elab-toggle"'
              f'{" checked" if show_edge_labels else ""}> Show relation labels</label>')
    html_out = (f'<div id="graphbox" class="graph-box{" graph-on" if show_edge_labels else ""}">'
                f'<div class="graph-head">{"".join(legend)}{toggle}</div>'
                f'<div class="graph-wrap">{"".join(parts)}</div>{note}</div>')

    # relations table (top facts)
    rel_rows = []
    for e in edges[:200]:
        rel_rows.append(
            f"<tr><td>{esc(e.get('source_node_name') or by_uuid.get(e.get('source_node_uuid'), {}).get('name'))}</td>"
            f"<td><code>{esc(e.get('name') or e.get('fact_type'))}</code></td>"
            f"<td>{esc(e.get('target_node_name') or by_uuid.get(e.get('target_node_uuid'), {}).get('name'))}</td>"
            f"<td>{esc(trunc(e.get('fact'), 200))}</td></tr>")
    if rel_rows:
        html_out += ('<details><summary>Relations table'
                     f' ({min(len(edges), 200)} of {len(edges)})</summary><div class="tbl"><table>'
                     '<thead><tr><th>Source</th><th>Relation</th><th>Target</th><th>Fact</th></tr></thead><tbody>'
                     + "".join(rel_rows) + "</tbody></table></div></details>")
    stats = {"node_count": len(nodes), "edge_count": len(edges),
             "entity_types": dict(Counter(node_type(n) for n in nodes).most_common())}
    return html_out, stats


# --------------------------------------------------------------------------
# Charts (inline SVG)
# --------------------------------------------------------------------------

def _nice_step(vmax: float, target_ticks: int = 4) -> float:
    raw = max(vmax, 1) / target_ticks
    exp = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 5, 10):
        if raw <= m * exp:
            return max(1.0, m * exp)
    return 10 * exp


def stacked_bar_chart(rounds: List[int], series: List[str], values: Dict[str, List[float]],
                      slots: Dict[str, int], title: str, y_label: str = "actions") -> str:
    if not rounds:
        return '<p class="empty">No timeline data yet.</p>'
    W, H = 760.0, 300.0
    L, R, T, B = 44.0, 12.0, 12.0, 34.0
    pw, ph = W - L - R, H - T - B
    totals = [sum(values[s][i] for s in series) for i in range(len(rounds))]
    step = _nice_step(max(totals + [1]))
    n_ticks = max(1, math.ceil(max(totals + [1]) / step))
    ymax = step * n_ticks
    n = len(rounds)
    band = pw / n
    bw = max(2.0, min(36.0, band * 0.72))
    parts = [f'<svg class="chart" viewBox="0 0 {int(W)} {int(H)}" role="img" aria-label="{esc(title)}">']
    for k in range(n_ticks + 1):
        v = step * k
        y = T + ph - ph * v / ymax
        parts.append(f'<line class="grid" x1="{L}" x2="{W - R}" y1="{y:.1f}" y2="{y:.1f}"/>')
        parts.append(f'<text class="tick" x="{L - 6}" y="{y + 4:.1f}" text-anchor="end">{fmt_num(v)}</text>')
    label_every = max(1, math.ceil(n / 12))
    for i, rnum in enumerate(rounds):
        x = L + band * i + (band - bw) / 2
        y_cursor = T + ph
        segs: List[Tuple[str, float]] = []
        other_v = 0.0
        for s in series:
            if values[s][i] <= 0:
                continue
            if slots.get(s, -1) < 0:
                other_v += values[s][i]
            else:
                segs.append((s, values[s][i]))
        if other_v:
            segs.append((OTHER, other_v))
        for j, (s, v) in enumerate(segs):
            h = ph * v / ymax
            gap = 2.0 if j < len(segs) - 1 and h > 3 else 0.0
            y_top = y_cursor - h
            tip = f"Round {rnum} · {s}: {fmt_num(v)} (total {fmt_num(totals[i])})"
            rx = 3 if j == len(segs) - 1 else 0
            parts.append(f'<rect x="{x:.1f}" y="{y_top:.1f}" width="{bw:.1f}" height="{max(h - gap, 0.5):.1f}" '
                         f'rx="{rx}" style="fill:{slot_var(slots.get(s, -1))}" data-tip="{esc(tip)}">'
                         f'<title>{esc(tip)}</title></rect>')
            y_cursor = y_top
        if i % label_every == 0:
            parts.append(f'<text class="tick" x="{x + bw / 2:.1f}" y="{H - B + 16}" text-anchor="middle">{rnum}</text>')
    parts.append(f'<line class="axis" x1="{L}" x2="{W - R}" y1="{T + ph}" y2="{T + ph}"/>')
    parts.append(f'<text class="tick" x="{L + pw / 2}" y="{H - 2}" text-anchor="middle">round</text>')
    parts.append("</svg>")
    parts.insert(0, '<div class="chart-wrap">')
    parts.append("</div>")
    legend = ['<ul class="legend">']
    seen = set()
    for s in series:
        sl = slots.get(s, -1)
        name = OTHER if sl < 0 else s
        if name in seen:
            continue
        seen.add(name)
        legend.append(f'<li><span class="sw" style="background:{slot_var(sl)}"></span>{esc(name)}</li>')
    legend.append("</ul>")
    return "".join(legend) + "".join(parts)


def hbar_chart(items: List[Tuple[str, float]], color: str = "var(--s1)", unit: str = "") -> str:
    if not items:
        return '<p class="empty">No data.</p>'
    vmax = max(v for _, v in items) or 1
    rows = []
    for label, v in items:
        pct = 100 * v / vmax
        rows.append(f'<div class="hb-row" data-tip="{esc(label)}: {fmt_num(v)}{unit}">'
                    f'<span class="hb-label" title="{esc(label)}">{esc(trunc(label, 28))}</span>'
                    f'<span class="hb-track"><span class="hb-bar" style="width:{pct:.1f}%;background:{color}"></span></span>'
                    f'<span class="hb-val">{fmt_num(v)}{unit}</span></div>')
    return '<div class="hbars">' + "".join(rows) + "</div>"


# --------------------------------------------------------------------------
# Sections
# --------------------------------------------------------------------------

def build_timeline(bundle: Dict[str, Any]) -> Tuple[List[int], Dict[str, List[float]], List[str]]:
    """Prefer timeline.json; fall back to aggregating actions."""
    per_round: Dict[int, Counter] = defaultdict(Counter)
    tl = as_list(bundle.get("timeline"))
    if tl and any(isinstance(r, dict) and r.get("action_types") for r in tl):
        for r in tl:
            per_round[int(r.get("round_num", 0))].update(r.get("action_types") or {})
    else:
        for a in as_list(bundle.get("actions")):
            per_round[int(a.get("round_num", 0) or 0)][a.get("action_type", "UNKNOWN")] += 1
    rounds = sorted(per_round)
    totals = Counter()
    for c in per_round.values():
        totals.update(c)
    series = [s for s, _ in totals.most_common()]
    values = {s: [float(per_round[r].get(s, 0)) for r in rounds] for s in series}
    return rounds, values, series


def collect_profiles(bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
    profs = as_list(bundle.get("profiles_reddit")) or as_list(bundle.get("profiles_twitter"))
    cfg = bundle.get("config") or {}
    agent_cfg = {}
    for ac in as_list(cfg.get("agent_configs")):
        agent_cfg[ac.get("agent_id")] = ac
    rows = []
    for i, p in enumerate(profs):
        aid = p.get("user_id", i)
        ac = agent_cfg.get(aid) or agent_cfg.get(i) or {}
        rows.append({
            "agent_id": aid,
            "name": p.get("name") or p.get("username") or ac.get("entity_name"),
            "username": p.get("username") or p.get("user_name"),
            "entity_type": ac.get("entity_type", ""),
            "profession": p.get("profession", ""),
            "age": p.get("age", ""),
            "gender": p.get("gender", ""),
            "mbti": p.get("mbti", ""),
            "country": p.get("country", ""),
            "stance": ac.get("stance", ""),
            "sentiment_bias": ac.get("sentiment_bias"),
            "activity_level": ac.get("activity_level"),
            "influence_weight": ac.get("influence_weight"),
            "bio": p.get("bio", ""),
            "persona": p.get("persona", ""),
        })
    if not rows and agent_cfg:
        for aid, ac in sorted(agent_cfg.items(), key=lambda kv: (kv[0] is None, kv[0])):
            rows.append({"agent_id": aid, "name": ac.get("entity_name"), "entity_type": ac.get("entity_type"),
                         "stance": ac.get("stance"), "sentiment_bias": ac.get("sentiment_bias"),
                         "activity_level": ac.get("activity_level"), "influence_weight": ac.get("influence_weight")})
    return rows


def render_personas(rows: List[Dict[str, Any]], actions_by_agent: Dict[Any, int]) -> str:
    if not rows:
        return '<p class="empty">No agent profiles in this run.</p>'
    out = ['<div class="tbl tall"><table class="personas"><thead><tr>'
           '<th>#</th><th>Agent</th><th>Type</th><th>Stance</th><th class="num">Sentiment</th>'
           '<th class="num">Activity</th><th class="num">Actions</th><th>Profile</th></tr></thead><tbody>']
    for r in rows:
        meta = " · ".join(str(x) for x in [r.get("profession"), r.get("age"), r.get("gender"),
                                                 r.get("mbti"), r.get("country")] if x not in (None, ""))
        sb = r.get("sentiment_bias")
        sb_html = "" if sb is None else (
            f'<span class="pill {"pos" if sb > 0.15 else "neg" if sb < -0.15 else "neu"}">{sb:+.2f}</span>')
        stance = r.get("stance") or ""
        stance_html = f'<span class="tag">{esc(stance)}</span>' if stance else ""
        al = r.get("activity_level")
        act = "" if not isinstance(al, (int, float)) else f"{float(al):.2f}"
        bio = r.get("bio") or r.get("persona") or ""
        persona = r.get("persona") or ""
        detail = ""
        if persona and persona != bio:
            detail = f'<details><summary>persona</summary><p>{esc(trunc(persona, 1200))}</p></details>'
        out.append(
            f"<tr><td class=\"muted\">{esc(r.get('agent_id'))}</td>"
            f"<td><strong>{esc(r.get('name'))}</strong>"
            + (f"<br><span class=\"muted small\">@{esc(r.get('username'))}</span>" if r.get("username") else "")
            + f"</td><td>{esc(r.get('entity_type'))}</td>"
            f"<td>{stance_html}</td>"
            f"<td class=\"num\">{sb_html}</td>"
            f"<td class=\"num\">{act}</td>"
            f"<td class=\"num\">{actions_by_agent.get(r.get('agent_id'), 0)}</td>"
            f"<td class=\"profile\">{esc(meta)}{'<br>' if meta and bio else ''}"
            f"<span class=\"muted\">{esc(trunc(bio, 220))}</span>{detail}</td></tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


def _post_score(p: Dict[str, Any]) -> float:
    def g(k):
        try:
            return float(p.get(k) or 0)
        except (TypeError, ValueError):
            return 0.0
    return g("num_likes") + 2 * g("num_shares") + 1.5 * g("num_comments") - 0.5 * g("num_dislikes")


def render_top_posts(bundle: Dict[str, Any], name_by_id: Dict[Any, str], limit: int = 10) -> str:
    blocks = []
    for plat in ("twitter", "reddit"):
        posts = as_list(bundle.get(f"posts_{plat}"))
        comments = as_list(bundle.get(f"comments_{plat}"))
        if not posts and not comments:
            continue
        comment_count = Counter(c.get("post_id") for c in comments)
        for p in posts:
            p.setdefault("num_comments", comment_count.get(p.get("post_id"), 0))
        top = sorted([p for p in posts if (p.get("content") or p.get("quote_content"))],
                     key=_post_score, reverse=True)[:limit]
        items = []
        for p in top:
            who = name_by_id.get(p.get("user_id"), f"user {p.get('user_id')}")
            stats = (f"♥ {fmt_num(p.get('num_likes') or 0)} · ↻ {fmt_num(p.get('num_shares') or 0)}"
                     f" · \U0001F5E8 {fmt_num(p.get('num_comments') or 0)}")
            items.append(f'<li class="post"><div class="post-head"><strong>{esc(who)}</strong>'
                         f'<span class="muted small">{esc(stats)}</span></div>'
                         f'<p>{esc(trunc(p.get("content") or p.get("quote_content"), 500))}</p></li>')
        topc = sorted(comments, key=lambda c: float(c.get("num_likes") or 0) - float(c.get("num_dislikes") or 0),
                      reverse=True)[:limit]
        citems = []
        for c in topc:
            who = name_by_id.get(c.get("user_id"), f"user {c.get('user_id')}")
            citems.append(f'<li class="post"><div class="post-head"><strong>{esc(who)}</strong>'
                          f'<span class="muted small">♥ {fmt_num(c.get("num_likes") or 0)} · on post '
                          f'{esc(c.get("post_id"))}</span></div><p>{esc(trunc(c.get("content"), 400))}</p></li>')
        label = "Twitter-style plaza" if plat == "twitter" else "Reddit-style community"
        blk = f'<div class="card"><h3>{label}</h3><p class="muted small">{len(posts)} posts · {len(comments)} comments loaded</p>'
        blk += f'<h4>Top posts</h4><ol class="posts">{"".join(items)}</ol>' if items else '<p class="empty">No posts.</p>'
        if citems:
            blk += f'<h4>Top comments</h4><ol class="posts">{"".join(citems)}</ol>'
        blocks.append(blk + "</div>")
    if not blocks:
        # fall back to CREATE_POST actions
        acts = [a for a in as_list(bundle.get("actions"))
                if a.get("action_type") in ("CREATE_POST", "QUOTE_POST", "CREATE_COMMENT")
                and (a.get("action_args") or {}).get("content")]
        if not acts:
            return '<p class="empty">No posts or comments recorded.</p>'
        items = [f'<li class="post"><div class="post-head"><strong>{esc(a.get("agent_name"))}</strong>'
                 f'<span class="muted small">R{esc(a.get("round_num"))} · {esc(a.get("platform"))} · '
                 f'{esc(a.get("action_type"))}</span></div><p>{esc(trunc(a["action_args"]["content"], 500))}</p></li>'
                 for a in acts[:limit * 2]]
        return f'<div class="card"><h3>Posts &amp; comments (from action log)</h3><ol class="posts">{"".join(items)}</ol></div>'
    return '<div class="grid2">' + "".join(blocks) + "</div>"


def render_stance(rows: List[Dict[str, Any]]) -> str:
    stances = Counter((r.get("stance") or "unknown") for r in rows if r.get("stance") or r.get("sentiment_bias") is not None)
    sentiments = [float(r["sentiment_bias"]) for r in rows if isinstance(r.get("sentiment_bias"), (int, float))]
    if not stances and not sentiments:
        return ""
    out = ['<div class="grid2">']
    if stances:
        out.append('<div class="card"><h3>Stance distribution</h3>'
                   + hbar_chart(stances.most_common(), "var(--s1)") + "</div>")
    if sentiments:
        bins = [(-1.0, -0.6), (-0.6, -0.2), (-0.2, 0.2), (0.2, 0.6), (0.6, 1.01)]
        names = ["very negative", "negative", "neutral", "positive", "very positive"]
        colors = ["var(--div-neg2)", "var(--div-neg1)", "var(--div-mid)", "var(--div-pos1)", "var(--div-pos2)"]
        counts = [sum(1 for s in sentiments if lo <= s < hi) for lo, hi in bins]
        avg = sum(sentiments) / len(sentiments)
        rows_html = []
        vmax = max(counts) or 1
        for nme, c, col in zip(names, counts, colors):
            rows_html.append(f'<div class="hb-row" data-tip="{nme}: {c} agents"><span class="hb-label">{nme}</span>'
                             f'<span class="hb-track"><span class="hb-bar" style="width:{100 * c / vmax:.1f}%;background:{col}"></span></span>'
                             f'<span class="hb-val">{c}</span></div>')
        out.append(f'<div class="card"><h3>Configured sentiment bias</h3><p class="muted small">mean {avg:+.2f} '
                   f'across {len(sentiments)} agents (−1 negative … +1 positive)</p>'
                   f'<div class="hbars">{"".join(rows_html)}</div></div>')
    out.append("</div>")
    return "".join(out)


def render_ontology(project: Dict[str, Any]) -> str:
    onto = (project or {}).get("ontology") or {}
    ets = as_list(onto.get("entity_types"))
    eds = as_list(onto.get("edge_types"))
    if not ets and not eds:
        return ""
    def item(x):
        if isinstance(x, dict):
            return f"<li><strong>{esc(x.get('name'))}</strong> <span class=\"muted\">{esc(trunc(x.get('description'), 160))}</span></li>"
        return f"<li>{esc(x)}</li>"
    return (f'<details class="onto"><summary>Ontology: {len(ets)} entity types, {len(eds)} relation types</summary>'
            '<div class="grid2" style="margin-top:10px"><div class="card"><h3>Entity types</h3><ul class="plain">'
            + "".join(item(x) for x in ets) + '</ul></div><div class="card"><h3>Relation types</h3><ul class="plain">'
            + "".join(item(x) for x in eds) + "</ul></div></div></details>")


def report_markdown(report: Dict[str, Any]) -> str:
    if not report:
        return ""
    md = report.get("markdown_content") or ""
    if not md and report.get("outline"):
        o = report["outline"]
        parts = [f"# {o.get('title', 'Report')}", "", o.get("summary", "")]
        for s in as_list(o.get("sections")):
            parts += ["", f"## {s.get('title', '')}", "", s.get("content", "")]
        md = "\n".join(parts)
    return md


# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------

CSS = """
:root{color-scheme:light;--bg:#f6f6f4;--surface:#fcfcfb;--surface-2:#f0efec;--border:#e2e1dc;
--text:#0b0b0b;--text-2:#52514e;--muted:#77756f;--accent:#2a78d6;--grid:#e6e5e0;--axis:#a9a79f;
--edge:#b9b7ae;--other:#9a988f;--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;--s5:#e87ba4;--s6:#008300;
--s7:#6250d6;--s8:#e34948;--div-neg2:#c43d3c;--div-neg1:#ec9a99;--div-mid:#b9b7ae;--div-pos1:#86b6ef;--div-pos2:#1c5cab;
--pos-bg:#e3effd;--pos-fg:#184f95;--neg-bg:#fde6e6;--neg-fg:#9e2b2a;--neu-bg:#efeee9;--neu-fg:#52514e}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#121211;--surface:#1a1a19;
--surface-2:#242422;--border:#33332f;--text:#f0efec;--text-2:#c3c2b7;--muted:#9a988f;--accent:#3987e5;--grid:#2c2c29;
--axis:#5c5b55;--edge:#55544e;--other:#7d7b74;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;--s6:#008300;
--s7:#9085e9;--s8:#e66767;--div-neg2:#e66767;--div-neg1:#9e4a49;--div-mid:#6b6a63;--div-pos1:#2f5f99;--div-pos2:#6da7ec;
--pos-bg:#1d3350;--pos-fg:#9ec5f4;--neg-bg:#4a2222;--neg-fg:#f3b0af;--neu-bg:#2c2c29;--neu-fg:#c3c2b7}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#121211;--surface:#1a1a19;--surface-2:#242422;--border:#33332f;
--text:#f0efec;--text-2:#c3c2b7;--muted:#9a988f;--accent:#3987e5;--grid:#2c2c29;--axis:#5c5b55;--edge:#55544e;--other:#7d7b74;
--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;--s6:#008300;--s7:#9085e9;--s8:#e66767;
--div-neg2:#e66767;--div-neg1:#9e4a49;--div-mid:#6b6a63;--div-pos1:#2f5f99;--div-pos2:#6da7ec;
--pos-bg:#1d3350;--pos-fg:#9ec5f4;--neg-bg:#4a2222;--neg-fg:#f3b0af;--neu-bg:#2c2c29;--neu-fg:#c3c2b7}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,
"Helvetica Neue",Arial,"Noto Sans","PingFang SC","Microsoft YaHei",sans-serif;overflow-x:hidden}
a{color:var(--accent)}
.wrap{max-width:1180px;margin:0 auto;padding:24px 16px 64px}
header.top{display:flex;flex-wrap:wrap;gap:8px 24px;align-items:flex-end;justify-content:space-between;margin-bottom:8px}
h1{font-size:1.65rem;line-height:1.2;margin:0 0 4px}
h2{font-size:1.2rem;margin:0 0 12px}
h3{font-size:1rem;margin:0 0 8px}
h4{font-size:.9rem;margin:14px 0 6px;color:var(--text-2)}
.muted{color:var(--muted)}.small{font-size:.82rem}
.req{max-width:80ch;color:var(--text-2);margin:4px 0 0}
nav.toc{display:flex;flex-wrap:nowrap;overflow-x:auto;scrollbar-width:none;gap:6px;margin:16px 0 20px;position:sticky;top:0;z-index:5;padding:8px 0;background:var(--bg)}
nav.toc a{flex:none;font-size:.85rem;text-decoration:none;color:var(--text-2);border:1px solid var(--border);
background:var(--surface);padding:4px 10px;border-radius:999px}
nav.toc a:hover{color:var(--text);border-color:var(--axis)}
section{scroll-margin-top:56px;background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:18px;margin:0 0 18px;min-width:0}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin:0 0 18px}
.tile{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:12px 14px}
.tile .v{font-size:1.5rem;font-weight:650;font-variant-numeric:tabular-nums}
.tile .k{font-size:.8rem;color:var(--muted)}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr));gap:14px}
.card{background:var(--surface-2);border-radius:10px;padding:14px;min-width:0}
section>.card+.card{margin-top:14px}
.legend{display:flex;flex-wrap:wrap;gap:4px 14px;list-style:none;padding:0;margin:0 0 8px;font-size:.82rem;color:var(--text-2)}
.legend li{display:flex;align-items:center;gap:6px}
.sw{width:10px;height:10px;border-radius:3px;display:inline-block;flex:none}
.graph-head{display:flex;flex-wrap:wrap;justify-content:space-between;gap:8px;align-items:flex-start}
.toggle{font-size:.82rem;color:var(--text-2);display:flex;gap:6px;align-items:center;white-space:nowrap}
.graph-wrap{background:var(--surface-2);border-radius:10px;overflow-x:auto;-webkit-overflow-scrolling:touch}
.chart-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
.tbl.tall{max-height:70vh;overflow:auto}
svg{display:block;width:100%;height:auto}
svg.graph line{stroke:var(--edge);stroke-width:1.2}
svg.graph line:hover{stroke:var(--text-2);stroke-width:2.5}
svg.graph .arrow{fill:var(--edge)}
svg.graph circle{stroke:var(--surface-2);stroke-width:2}
svg.graph circle:hover{stroke:var(--text);}
svg.graph text{font-size:11px;fill:var(--text);text-anchor:middle;pointer-events:none;paint-order:stroke;
stroke:var(--surface-2);stroke-width:3px;stroke-linejoin:round}
svg.graph .elabels text{font-size:9px;fill:var(--muted)}
svg.graph .elabels{display:none}
.graph-on svg.graph .elabels{display:inline}
svg.chart .grid{stroke:var(--grid);stroke-width:1}
svg.chart .axis{stroke:var(--axis);stroke-width:1}
svg.chart .tick{font-size:11px;fill:var(--muted)}
svg.chart rect:hover{opacity:.82}
.hbars{display:flex;flex-direction:column;gap:6px}
.hb-row{display:grid;grid-template-columns:minmax(80px,34%) 1fr auto;gap:8px;align-items:center;font-size:.85rem}
.hb-label{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--text-2)}
.hb-track{height:12px;background:transparent;border-radius:4px;display:block}
.hb-bar{display:block;height:100%;border-radius:0 4px 4px 0;min-width:2px}
.hb-val{font-variant-numeric:tabular-nums;color:var(--text-2);min-width:2.5em;text-align:right}
.tbl{overflow-x:auto;-webkit-overflow-scrolling:touch;max-width:100%}
table{border-collapse:collapse;width:100%;font-size:.86rem}
th,td{text-align:left;vertical-align:top;padding:7px 8px;border-bottom:1px solid var(--border)}
th{font-weight:600;color:var(--text-2);background:var(--surface);position:sticky;top:0}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
table.personas td.profile{min-width:240px;max-width:460px}
.tag{display:inline-block;font-size:.75rem;padding:1px 8px;border-radius:999px;background:var(--neu-bg);color:var(--neu-fg)}
.pill{display:inline-block;font-size:.75rem;padding:1px 6px;border-radius:6px;font-variant-numeric:tabular-nums}
.pill.pos{background:var(--pos-bg);color:var(--pos-fg)}.pill.neg{background:var(--neg-bg);color:var(--neg-fg)}
.pill.neu{background:var(--neu-bg);color:var(--neu-fg)}
details{margin-top:10px}summary{cursor:pointer;color:var(--text-2);font-size:.88rem}
ol.posts{padding-left:1.3em;margin:0}
li.post{margin:0 0 10px}li.post p{margin:2px 0 0;color:var(--text-2);overflow-wrap:anywhere}
.post-head{display:flex;flex-wrap:wrap;gap:4px 10px;align-items:baseline}
ul.plain{list-style:none;padding:0;margin:0}ul.plain li{margin:0 0 6px}
.report{max-width:78ch;overflow-wrap:anywhere}
.report h1{font-size:1.45rem;margin:.6em 0 .4em}.report h2{font-size:1.2rem;margin:1.4em 0 .5em;
padding-bottom:4px;border-bottom:1px solid var(--border)}.report h3{font-size:1.04rem;margin:1.2em 0 .4em}
.report blockquote{margin:12px 0;padding:6px 14px;border-left:3px solid var(--accent);background:var(--surface-2);
border-radius:0 8px 8px 0;color:var(--text-2)}
.report blockquote p{margin:6px 0}
code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.85em;background:var(--surface-2);
padding:1px 5px;border-radius:4px}
pre{background:var(--surface-2);padding:12px;border-radius:8px;overflow-x:auto}pre code{background:none;padding:0}
hr{border:0;border-top:1px solid var(--border);margin:18px 0}
.empty{color:var(--muted);font-style:italic}
.kv{display:grid;grid-template-columns:max-content 1fr;gap:4px 14px;font-size:.86rem;margin:0}
.kv dt{color:var(--muted)}.kv dd{margin:0;overflow-wrap:anywhere}
#tip{position:fixed;z-index:50;pointer-events:none;max-width:min(360px,80vw);background:var(--text);color:var(--surface);
font-size:.8rem;line-height:1.4;padding:6px 9px;border-radius:6px;white-space:pre-line;opacity:0;transition:opacity .08s}
footer{color:var(--muted);font-size:.8rem;text-align:center;margin-top:24px}
@media (max-width:640px){.wrap{padding:16px 16px 48px}h1{font-size:1.35rem}section{padding:14px;border-radius:10px}
.tile .v{font-size:1.25rem}svg.graph{min-width:680px}svg.graph text{font-size:14px}svg.graph .elabels text{font-size:11px}
nav.toc{position:static}svg.chart{min-width:560px}svg.chart .tick{font-size:15px}}
@media print{nav.toc{display:none}section{break-inside:avoid}}
"""

JS = """
(function(){var t=document.getElementById('tip');if(!t)return;
function show(e,s){t.textContent=s;t.style.opacity=1;var x=e.clientX+14,y=e.clientY+14;
var r=t.getBoundingClientRect();if(x+r.width>innerWidth-8)x=e.clientX-r.width-14;if(y+r.height>innerHeight-8)y=e.clientY-r.height-14;
t.style.left=Math.max(8,x)+'px';t.style.top=Math.max(8,y)+'px'}
document.addEventListener('pointermove',function(e){var el=e.target.closest&&e.target.closest('[data-tip]');
if(el){show(e,el.getAttribute('data-tip'))}else{t.style.opacity=0}});
document.addEventListener('pointerdown',function(e){var el=e.target.closest&&e.target.closest('[data-tip]');if(el)show(e,el.getAttribute('data-tip'))});
document.querySelectorAll('svg title').forEach(function(n){n.remove()});
var cb=document.getElementById('elab-toggle'),g=document.getElementById('graphbox');
function sync(){if(g)g.classList.toggle('graph-on',cb.checked)}if(cb){cb.addEventListener('change',sync);sync()}})();
"""


def build_summary(bundle: Dict[str, Any], graph_stats: Dict[str, Any], rounds: List[int],
                  series_totals: Dict[str, float], profiles: List[Dict[str, Any]]) -> Dict[str, Any]:
    project = bundle.get("project") or {}
    sim = bundle.get("simulation") or {}
    rs = bundle.get("run_status") or {}
    report = bundle.get("report") or {}
    actions = as_list(bundle.get("actions"))
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "project_id": project.get("project_id") or sim.get("project_id"),
        "project_name": project.get("name"),
        "simulation_requirement": project.get("simulation_requirement")
        or (bundle.get("config") or {}).get("simulation_requirement"),
        "simulation_id": sim.get("simulation_id") or rs.get("simulation_id"),
        "simulation_status": sim.get("status"),
        "runner_status": rs.get("runner_status"),
        "graph_id": project.get("graph_id") or sim.get("graph_id"),
        "graph": graph_stats,
        "agents": len(profiles),
        "rounds_with_actions": len(rounds),
        "current_round": rs.get("current_round"),
        "total_rounds": rs.get("total_rounds"),
        "total_actions": rs.get("total_actions_count") if rs.get("total_actions_count") is not None else
        (len(actions) or int(sum(series_totals.values()))),
        "action_types": {k: int(v) for k, v in series_totals.items()},
        "posts": {p: len(as_list(bundle.get(f"posts_{p}"))) for p in ("twitter", "reddit")},
        "comments": {p: len(as_list(bundle.get(f"comments_{p}"))) for p in ("twitter", "reddit")},
        "stances": dict(Counter(r.get("stance") for r in profiles if r.get("stance"))),
        "report_id": report.get("report_id"),
        "report_status": report.get("status"),
        "report_title": ((report.get("outline") or {}).get("title")),
    }


def render_dashboard(bundle: Dict[str, Any], title: Optional[str] = None) -> Tuple[str, str, Dict[str, Any]]:
    """Return (html, report_markdown, summary)."""
    project = bundle.get("project") or {}
    sim = bundle.get("simulation") or {}
    rs = bundle.get("run_status") or {}
    cfg = bundle.get("config") or {}
    report = bundle.get("report") or {}

    graph_html, graph_stats = render_graph(feed_view.augment_graph(bundle.get("graph") or {}, cfg))
    rounds, values, series = build_timeline(bundle)
    series_totals = {s: sum(values[s]) for s in series}
    slots = assign_slots(series)

    profiles = collect_profiles(bundle)
    name_by_id = {r["agent_id"]: r.get("name") for r in profiles}
    actions = as_list(bundle.get("actions"))
    actions_by_agent: Counter = Counter()
    for a in actions:
        actions_by_agent[a.get("agent_id")] += 1
        if a.get("agent_id") not in name_by_id and a.get("agent_name"):
            name_by_id[a.get("agent_id")] = a.get("agent_name")
    if not actions_by_agent:
        for s in as_list(bundle.get("agent_stats")):
            actions_by_agent[s.get("agent_id")] = s.get("total_actions", 0)

    md = report_markdown(report)
    summary = build_summary(bundle, graph_stats, rounds, series_totals, profiles)
    mk = marketing.analyze(bundle)
    summary["marketing"] = marketing.summary_block(mk)
    mk_sections = marketing.render_sections(mk)
    # MarketMirror extras: feed test after the playbook; panel, backtest and downloads after the voices
    fs = feed_view.feed_section(bundle.get("feed_test") or {}, marketing.chart)
    if fs:
        at = next((i + 1 for i, sec in enumerate(mk_sections) if sec[0] == "playbook"), 1)
        mk_sections.insert(at, fs)
    for extra in (feed_view.panel_section(bundle.get("analyst_panel") or {}),
                  feed_view.backtest_section(bundle.get("backtest") or {}, marketing.chart)):
        if extra:
            mk_sections.append(extra)
    decision = feed_view.decision(bundle, mk)
    summary["decision"] = decision
    dec = feed_view.decision_section(decision)
    # social feed (real post view) right after the feed test, when the section module and data exist
    if social_feed is not None and bundle.get("feed_story"):
        try:
            sf = social_feed.feed_story_section(bundle["feed_story"], marketing.chart)
        except Exception as e:  # noqa: BLE001 - never lose the dashboard to one section
            sf = None
            print(f"social feed section failed: {e}")
        if sf:
            at = next((i + 1 for i, sec in enumerate(mk_sections) if sec[0] == "feedtest"), 1)
            mk_sections.insert(at, sf)
    # people: cards with interview summaries, lead scores and survey verdicts
    index = [r for r in (cfg.get("persona_index") or []) if isinstance(r, dict)]
    survey_by_agent = {}
    for r in (bundle.get("survey") or {}).get("responses") or []:
        if r.get("answer"):
            survey_by_agent[r.get("agent_id")] = r["answer"]
    leads = {aid: sc for aid, sc in ((aid, report_view.person_lead_score(a)) for aid, a in survey_by_agent.items())
             if sc is not None}
    people_html = report_view.people_cards(index, dict(actions_by_agent), survey_by_agent, leads)
    files = feed_view.export_files(bundle, mk, md)
    files["summary.json"] = json.dumps(summary, ensure_ascii=False, indent=2, default=str)
    mr = bundle.get("market_report") or {}
    if mr.get("markdown"):
        files = {"market_report.md": mr["markdown"],
                 "action_plan.json": json.dumps(mr.get("action_plan") or {}, ensure_ascii=False, indent=2), **files}
    if leads:
        files["leads.csv"] = report_view.leads_csv(index, survey_by_agent, leads)
    if bundle.get("feed_story"):
        files["feed_story.json"] = json.dumps(bundle["feed_story"], ensure_ascii=False, default=str)
    rep_sec = report_view.report_section(mr, files, markdown_to_html)
    if dec:
        mk_sections.insert(0, dec)
        mk_sections.insert(1, rep_sec)
    else:
        mk_sections.insert(0, rep_sec)

    req = summary.get("simulation_requirement") or ""
    page_title = title or (bundle.get("run_manifest") or {}).get("title") or (
        summary.get("report_title") or project.get("name") or "MarketMirror simulation")
    page_title = trunc(page_title, 70)

    tiles = [
        ("Entities", graph_stats.get("node_count", 0)),
        ("Relations", graph_stats.get("edge_count", 0)),
        ("Agents", len(profiles)),
        ("Rounds", rs.get("current_round") if rs.get("current_round") else len(rounds)),
        ("Actions", summary.get("total_actions") or 0),
        ("Posts", sum(summary["posts"].values())),
    ]
    tiles_html = '<div class="tiles">' + "".join(
        f'<div class="tile"><div class="v">{fmt_num(v)}</div><div class="k">{k}</div></div>' for k, v in tiles) + "</div>"

    # Timeline section
    tl_html = stacked_bar_chart(rounds, series, values, slots, "Actions per round by action type")
    plat_rows = []
    tl = as_list(bundle.get("timeline"))
    if tl:
        tw = sum(int(r.get("twitter_actions") or 0) for r in tl)
        rd = sum(int(r.get("reddit_actions") or 0) for r in tl)
        if tw or rd:
            plat_rows = [("Twitter-style", tw), ("Reddit-style", rd)]
    top_agents = sorted(((name_by_id.get(aid) or f"agent {aid}", c) for aid, c in actions_by_agent.items()),
                        key=lambda x: -x[1])[:12]
    type_items = sorted(series_totals.items(), key=lambda kv: -kv[1])
    type_rows = "".join(
        f'<div class="hb-row" data-tip="{esc(s)}: {fmt_num(v)}"><span class="hb-label">{esc(s)}</span>'
        f'<span class="hb-track"><span class="hb-bar" style="width:{100 * v / max(type_items[0][1], 1):.1f}%;'
        f'background:{slot_var(slots.get(s, -1))}"></span></span><span class="hb-val">{fmt_num(v)}</span></div>'
        for s, v in type_items)
    data_table = ""
    if rounds:
        data_table = ('<details><summary>Timeline data table</summary><div class="tbl"><table><thead><tr><th>Round</th>'
                      + "".join(f'<th class="num">{esc(s)}</th>' for s in series) + '<th class="num">Total</th></tr></thead><tbody>'
                      + "".join("<tr><td>" + str(r) + "</td>" + "".join(f'<td class="num">{fmt_num(values[s][i])}</td>' for s in series)
                                + f'<td class="num">{fmt_num(sum(values[s][i] for s in series))}</td></tr>'
                                for i, r in enumerate(rounds))
                      + "</tbody></table></div></details>")
    timeline_section = (
        f'<div class="card"><h3>Actions per round</h3>{tl_html}{data_table}</div>'
        '<div class="grid2" style="margin-top:14px">'
        f'<div class="card"><h3>Action mix</h3>{"<div class=hbars>" + type_rows + "</div>" if type_rows else "<p class=empty>No actions.</p>"}</div>'
        f'<div class="card"><h3>Most active agents</h3>{hbar_chart(top_agents, "var(--s1)")}'
        + (f'<h4>By platform</h4>{hbar_chart(plat_rows, "var(--s3)")}' if plat_rows else "")
        + "</div></div>")

    stance_html = render_stance(profiles)
    posts_html = render_top_posts(bundle, name_by_id)
    ontology_html = render_ontology(project)

    time_cfg = cfg.get("time_config") or {}
    ev = cfg.get("event_config") or {}
    meta_rows = [
        ("Project", f"{project.get('name') or ''} ({project.get('project_id') or summary.get('project_id') or '–'})"),
        ("Simulation", f"{summary.get('simulation_id') or '–'} · {sim.get('status') or ''} / runner {rs.get('runner_status') or '–'}"),
        ("Graph", summary.get("graph_id") or "–"),
        ("Seed files", ", ".join(f.get("filename", "") for f in as_list(project.get("files"))) or "–"),
        ("Simulated time", f"{time_cfg.get('total_simulation_hours', '–')} h at {time_cfg.get('minutes_per_round', '–')} min/round"
         if time_cfg else "–"),
        ("Hot topics", ", ".join(map(str, as_list(ev.get("hot_topics")))) or "–"),
        ("Report", f"{report.get('report_id') or '–'} · {report.get('status') or ''}"),
    ]
    meta_html = '<dl class="kv">' + "".join(f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>" for k, v in meta_rows) + "</dl>"
    if project.get("analysis_summary"):
        meta_html += f'<details><summary>Ontology analysis</summary><p>{esc(project.get("analysis_summary"))}</p></details>'
    if cfg.get("generation_reasoning"):
        meta_html += f'<details><summary>Config reasoning</summary><p>{esc(trunc(cfg.get("generation_reasoning"), 3000))}</p></details>'

    report_html = markdown_to_html(md) if md else '<p class="empty">No report generated for this run yet.</p>'

    has_social = any(sec[0] == "social" for sec in mk_sections)
    nav = [(a, b) for a, b, _ in mk_sections] + ([] if has_social else [("posts", "Conversations")]) + [
        ("agents", "People"), ("timeline", "Activity"), ("graph", "Market map"), ("overview", "Run details")]
    if md:
        nav.append(("engine-report", "Engine report"))
    body = [
        '<div class="wrap">',
        f'<header class="top"><div><div class="muted small">MarketMirror · simulated market test</div>'
        f'<h1>{esc(page_title)}</h1>' + (f'<p class="req">{esc(trunc(req, 400))}</p>' if req else "") + "</div>"
        + marketing.hero_stats(mk) + "</header>",
        '<nav class="toc">' + "".join(f'<a href="#{a}">{b}</a>' for a, b in nav) + "</nav>",
        *[f'<section id="{a}">{h}</section>' for a, _, h in mk_sections],
        ("" if has_social else f'<section id="posts"><h2>What people posted</h2>{posts_html}</section>'),
        '<h2 class="divider">Behind the simulation</h2>',
        f'<section id="agents"><h2>The simulated people</h2>'
        + (f'<p class="muted small">Everyone is invented, with a life story from a short interview. Lead score 0-100 '
           f'combines purchase intent, trust and click intent from their survey answers.</p>{people_html}'
           f'<details style="margin-top:14px"><summary>Table view and stances</summary>{stance_html}<div style="margin-top:14px">'
           f'{render_personas(profiles, actions_by_agent)}</div></details>' if people_html else
           f'{stance_html}<div style="margin-top:14px">{render_personas(profiles, actions_by_agent)}</div>')
        + "</section>",
        f'<section id="timeline"><h2>Activity over time</h2>{timeline_section}</section>',
        f'<section id="graph"><h2>Market map</h2><p class="muted small">Brand, offers, competitors, segments, '
        f'communities and objections from your documents and the simulated people, and how they connect.</p>{graph_html}'
        + (f'<div style="margin-top:14px">{ontology_html}</div>' if ontology_html else "") + "</section>",
        f'<section id="overview"><h2>Run details</h2>{tiles_html}{meta_html}</section>',
        (f'<section id="engine-report"><h2>Engine report</h2><p class="muted small">The simulation engine\'s own '
         f'narrative report (prediction style). The plain-language report above is the one to act on.</p>'
         f'<article class="report">{report_html}</article></section>' if md else ""),
        f'<footer>Generated {esc(summary["generated_at"])} by MarketMirror</footer>',
        "</div>", '<div id="tip" role="tooltip"></div>',
    ]
    html_out = (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{esc(page_title)}</title>\n<meta name=\"description\" content=\"{esc(trunc(req, 200))}\">\n"
        f"<style>{CSS}{marketing.MARKETING_CSS}{feed_view.FEED_CSS}{report_view.REPORT_CSS}"
        f"{getattr(social_feed, 'SOCIAL_CSS', '') if social_feed else ''}</style>\n</head>\n<body>\n"
        + "\n".join(body)
        + (f"\n<script>{_echarts_inline()}</script>" if 'class="ec"' in "".join(body) else "")
        + f"\n<script>{JS}{marketing.MARKETING_JS}{feed_view.FEED_JS}"
        f"{getattr(social_feed, 'SOCIAL_JS', '') if social_feed else ''}</script>\n</body>\n</html>\n"
    )
    return html_out, md, summary


def export_run_dir(run_dir: str, out_html: Optional[str] = None, title: Optional[str] = None) -> Dict[str, str]:
    bundle = load_run_dir(run_dir)
    page, md, summary = render_dashboard(bundle, title=title)
    out_html = out_html or os.path.join(run_dir, "dashboard.html")
    out_dir = os.path.dirname(os.path.abspath(out_html))
    os.makedirs(out_dir, exist_ok=True)
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(page)
    md_path = os.path.join(out_dir, "report.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md or "")
    summary_path = os.path.join(out_dir, "summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
    # every downloadable file, next to the dashboard (same payload the page embeds)
    import re as _re
    m = _re.search(r'<script type="application/json" id="mm-files">(.*?)</script>', page, _re.S)
    written = {}
    if m:
        try:
            files = json.loads(m.group(1))
        except ValueError:
            files = {}
        for name, text in files.items():
            if name in ("summary.json", "report.md") or not name.endswith((".csv", ".json", ".md")):
                continue
            with open(os.path.join(out_dir, name), "w", encoding="utf-8", newline="") as f:
                f.write(text)
            written["download:" + name] = os.path.abspath(os.path.join(out_dir, name))
    return {"html": os.path.abspath(out_html), "report_md": os.path.abspath(md_path),
            "summary_json": os.path.abspath(summary_path), **written}
