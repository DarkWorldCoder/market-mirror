"""Dashboard block "Predicted brain response (research)": one small multi-line chart per ad from brain_response.json
(Meta TRIBE v2 via the owner's sidecar). Stdlib only, inline SVG. A research view next to the feed test: it is never
given to the simulated people and changes no simulated number."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

try:  # stdlib only
    import ui  # type: ignore
except ImportError:  # pragma: no cover - imported as a package
    from . import ui  # type: ignore

LABEL = ("Predicted for an average viewer by Meta's TRIBE v2 research model (noncommercial license). It predicts brain "
         "activity, not attention, feelings, memory or buying. Not validated for ads.")
SERIES = (("visual", "var(--s1)", ""), ("hearing", "var(--s2)", ""), ("language", "var(--s3)", ""),
          ("cortex", "var(--muted)", "4 3"))
W, H, PAD_L, PAD_R, PAD_T, PAD_B = 320, 130, 26, 8, 8, 20


def _clock(s: Any) -> str:
    v = max(0, int(round(float(s or 0))))
    return f"{v // 60}:{v % 60:02d}"


def rows(brain: Optional[Dict[str, Any]], feed_test: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Rows from brain_response.json, or from feed-test creatives that carry a `brain_response` summary."""
    out = [r for r in (brain or {}).get("creatives") or [] if isinstance(r, dict)]
    if out:
        return out
    for cr in (feed_test or {}).get("creatives") or []:
        br = cr.get("brain_response") if isinstance(cr, dict) else None
        if isinstance(br, dict) and isinstance(br.get("summary"), dict):
            out.append({"id": cr.get("id"), "name": cr.get("name"), "status": "ok", "kind": br["summary"].get("kind"),
                        "summary": br["summary"], "line": br.get("line") or ""})
    return out


def chart(summary: Dict[str, Any], title: str = "") -> str:
    secs = [float(s) for s in summary.get("seconds") or []]
    groups = summary.get("groups") or {}
    series = [(key, color, dash, [float(v) for v in (groups.get(key) or {}).get("z") or []])
              for key, color, dash in SERIES if (groups.get(key) or {}).get("z")]
    if len(secs) < 2 or not series:
        return '<p class="muted small">Too short to chart.</p>'
    lo = min(min(v) for *_, v in series)
    hi = max(max(v) for *_, v in series)
    lo, hi = min(lo, -1.0), max(hi, 1.0)
    x0, x1 = secs[0], secs[-1]

    def x(t: float) -> float:
        return PAD_L + (t - x0) / ((x1 - x0) or 1) * (W - PAD_L - PAD_R)

    def y(v: float) -> float:
        return PAD_T + (hi - v) / ((hi - lo) or 1) * (H - PAD_T - PAD_B)

    parts = [f'<line class="grid" x1="{PAD_L}" x2="{W - PAD_R}" y1="{y(0):.1f}" y2="{y(0):.1f}"/>',
             f'<text class="tick" x="{PAD_L - 4}" y="{y(0) + 4:.1f}" text-anchor="end">0</text>',
             f'<text class="tick" x="{PAD_L - 4}" y="{y(hi) + 9:.1f}" text-anchor="end">+{hi:.0f}</text>',
             f'<text class="tick" x="{PAD_L - 4}" y="{y(lo):.1f}" text-anchor="end">{lo:.0f}</text>']
    for t in (x0, (x0 + x1) / 2, x1):
        anchor = "start" if t == x0 else "end" if t == x1 else "middle"
        parts.append(f'<text class="tick" x="{x(t):.1f}" y="{H - 5}" text-anchor="{anchor}">{_clock(t)}</text>')
    for key, color, dash, zs in series:
        pts = " ".join(f"{x(t):.1f},{y(v):.1f}" for t, v in zip(secs, zs))
        parts.append(f'<polyline fill="none" stroke="{color}" stroke-width="{1.2 if key == "cortex" else 1.8}"'
                     + (f' stroke-dasharray="{dash}"' if dash else "") + f' points="{pts}"><title>{ui.esc(groups[key].get("label") or key)}</title></polyline>')
    legend = "".join(f'<span style="white-space:nowrap;margin-right:10px"><span aria-hidden="true" style="display:inline-block;'
                     f'width:14px;height:0;vertical-align:middle;border-top:2px {"dashed" if dash else "solid"} {color}"></span> '
                     f'{ui.esc(groups[key].get("label") or key)}</span>'
                     for key, color, dash, _ in series)
    alt = f"Predicted brain response over {_clock(x1)}" + (f" for {title}" if title else "")
    return (f'<svg class="chart" viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="{ui.esc(alt)}" '
            f'preserveAspectRatio="xMidYMid meet">{"".join(parts)}</svg><p class="muted small">{legend}</p>')


def _peaks(summary: Dict[str, Any]) -> str:
    items = []
    for key, *_ in SERIES:
        g = (summary.get("groups") or {}).get(key) or {}
        spans = [(_clock(p["start"]) if _clock(p["start"]) == _clock(p["end"]) else f'{_clock(p["start"])}-{_clock(p["end"])}')
                 for p in (g.get("peaks") or [])[:2]]
        if spans:
            items.append(f'{ui.esc(g.get("label") or key)}: {ui.esc(", ".join(spans))}')
    return " · ".join(items)


def section(brain: Optional[Dict[str, Any]], feed_test: Optional[Dict[str, Any]] = None) -> Optional[Tuple[str, str, str]]:
    rs = rows(brain, feed_test)
    if not rs:
        return None
    cards = []
    for r in rs:
        name = ui.esc(r.get("id") or "") + (f' · {ui.esc(ui.trunc(r.get("name"), 50))}' if r.get("name") else "")
        if r.get("status") == "ok" and isinstance(r.get("summary"), dict):
            s = r["summary"]
            cards.append(f'<div class="card"><h3>{name} <span class="pill">{ui.esc(s.get("kind") or r.get("kind") or "")}</span></h3>'
                         f'{chart(s, str(r.get("id") or ""))}<p class="small">{ui.esc(r.get("line") or "")}</p>'
                         f'<p class="muted small">Peaks (seconds into the ad): {_peaks(s)}</p></div>')
        else:
            cards.append(f'<div class="card"><h3>{name}</h3><p class="muted small">Skipped: '
                         f'{ui.esc(r.get("reason") or "no prediction")}</p></div>')
    tc = (brain or {}).get("timing_check") or {}
    timing = ""
    if tc.get("status") == "ok":
        timing = (f'<p class="muted small">Timing check: {tc.get("near_peak")} of {tc.get("references")} simulated reactions '
                  f'that name a moment in an ad fall within {tc.get("tolerance_s", 2):g} s of a predicted peak. '
                  f'{ui.esc(tc.get("note") or "")}</p>')
    elif tc.get("note"):
        timing = f'<p class="muted small">Timing check: {ui.esc(tc["note"])}</p>'
    lag = next((r["summary"].get("lag_note") for r in rs if isinstance(r.get("summary"), dict) and r["summary"].get("lag_note")), "")
    intro = ("Each line is a group of brain areas, z-scored within the ad (0 is the ad's own average), so compare the "
             "shape over time, not the height between ads. Shown beside the simulated buyers; never given to them.")
    head = ui.section_head("Predicted brain response (research)", intro, LABEL)
    foot = f'<p class="muted small">{ui.esc(lag)} Atlas: Destrieux (nilearn, fsaverage5). Model: facebook/tribev2, CC BY-NC 4.0.</p>'
    return ("brain", "Brain response", head + '<div class="grid2">' + "".join(cards) + "</div>" + timing + foot)
