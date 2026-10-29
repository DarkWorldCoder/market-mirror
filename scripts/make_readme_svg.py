"""Write docs/images/marketmirror-loop.svg: the animated README banner.

One 14-second loop, CSS keyframes only (GitHub shows SVG through <img>, which runs CSS animation but no scripts):
your ad -> six simulated buyers scroll and react -> two of them argue -> survey bars -> a verdict with the fix.
Fitloop is the invented demo app; every number in the picture is illustrative and labelled simulated.
Viewers who ask for reduced motion get the finished frame. Run: python scripts/make_readme_svg.py
"""

from __future__ import annotations

import os
from typing import List, Optional, Tuple

LOOP = 14.0
W, H = 1200, 420
FONT = "Inter, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif"
MONO = "'JetBrains Mono', 'SFMono-Regular', Menlo, Consolas, monospace"
BG, SURFACE, LINE, CREAM, MUTED, YELLOW, INK = "#0d0d0c", "#171715", "#2b2b28", "#f4f1ea", "#a9a89f", "#f3d64b", "#121211"
YES, NO = "#7bd88f", "#ef7b6b"
END, OUT = 13.2, 13.7          # everything holds until END, fades by OUT, then the loop restarts

css: List[str] = []
_n = [0]


def p(t: float) -> str:
    return f"{max(0.0, min(100.0, 100 * t / LOOP)):.2f}%"


def anim(stops: List[Tuple[float, str]], extra: str = "") -> str:
    """A keyframes rule from (seconds, declarations) stops; returns the class name that runs it."""
    _n[0] += 1
    name = f"a{_n[0]}"
    frames = " ".join(f"{p(t)}{{{d}}}" for t, d in stops)
    css.append(f"@keyframes {name}{{{frames}}}.{name}{{animation:{name} {LOOP}s linear infinite;{extra}}}")
    return name


def show(t0: float, frm: str = "translateY(6px)", rise: float = 0.35, overshoot: Optional[str] = None,
         end: float = END) -> str:
    stops = [(0, f"opacity:0;transform:{frm}"), (t0, f"opacity:0;transform:{frm}")]
    if overshoot:
        stops.append((t0 + rise * 0.65, f"opacity:1;transform:{overshoot}"))
    stops += [(t0 + rise, "opacity:1;transform:none"), (end, "opacity:1;transform:none"),
              (OUT, "opacity:0;transform:none"), (LOOP, "opacity:0;transform:none")]
    return anim(stops, "transform-box:fill-box;transform-origin:50% 50%")


def grow(t0: float, dur: float = 0.9) -> str:
    return anim([(0, "opacity:1;transform:scaleX(0)"), (t0, "opacity:1;transform:scaleX(0)"),
                 (t0 + dur, "opacity:1;transform:scaleX(1)"), (END, "opacity:1;transform:scaleX(1)"),
                 (OUT, "opacity:0;transform:scaleX(1)"), (LOOP, "opacity:0;transform:scaleX(1)")],
                "transform-box:fill-box;transform-origin:0 50%")


def flight(t0: float, dx: float, dy: float) -> str:
    """Drawn at its target; starts (dx, dy) away, flies in, then melts into the person."""
    return anim([(0, f"opacity:0;transform:translate({dx}px,{dy}px) scale(.55)"),
                 (t0, f"opacity:1;transform:translate({dx}px,{dy}px) scale(.55)"),
                 (t0 + 0.55, "opacity:1;transform:translate(0,0) scale(1)"),
                 (t0 + 0.8, "opacity:0;transform:translate(0,0) scale(.6)"),
                 (LOOP, "opacity:0;transform:translate(0,0) scale(.6)")],
                "transform-box:fill-box;transform-origin:50% 50%")


def pulse(t0: float) -> str:
    return anim([(0, "opacity:0;transform:scale(1)"), (t0, "opacity:.9;transform:scale(1)"),
                 (t0 + 0.7, "opacity:0;transform:scale(1.7)"), (LOOP, "opacity:0;transform:scale(1.7)")],
                "transform-box:fill-box;transform-origin:50% 50%")


def typing(t0: float, dur: float, steps: int) -> str:
    return anim([(0, "transform:scaleX(0)"), (t0, f"transform:scaleX(0);animation-timing-function:steps({steps},end)"),
                 (t0 + dur, "transform:scaleX(1)"), (LOOP, "transform:scaleX(1)")],
                "transform-box:fill-box;transform-origin:0 50%")


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def text(x: float, y: float, s: str, size: int = 13, fill: str = CREAM, weight: int = 400, mono: bool = False,
         anchor: str = "start", cls: str = "", extra: str = "") -> str:
    c = f' class="{cls}"' if cls else ""
    return (f'<text x="{x}" y="{y}" font-family="{MONO if mono else FONT}" font-size="{size}" fill="{fill}" '
            f'font-weight="{weight}" text-anchor="{anchor}"{c}{extra}>{esc(s)}</text>')


def panel(x: float, title: str, step: str, w: float) -> str:
    return (f'<rect x="{x}" y="88" width="{w}" height="296" rx="14" fill="{SURFACE}" stroke="{LINE}"/>'
            f'<circle cx="{x + 26}" cy="113" r="10" fill="{YELLOW}"/>'
            + text(x + 26, 117, step, 12, INK, 700, anchor="middle") + text(x + 44, 117, title, 11, MUTED, 600, mono=True))


def build() -> str:
    out: List[str] = []
    # backdrop and header
    out.append(f'<rect width="{W}" height="{H}" rx="20" fill="{BG}"/>')
    out.append(f'<rect width="{W}" height="{H}" rx="20" fill="url(#dots)"/>')
    out.append(f'<path d="M40 30 h22 v22 h-22z" fill="{YELLOW}"/><path d="M51 30 v22" stroke="{INK}" stroke-width="2"/>'
               f'<path d="M44 46 l7-11 l7 11" fill="none" stroke="{INK}" stroke-width="2"/>')
    out.append(text(72, 48, "MarketMirror", 22, CREAM, 700))
    out.append(text(222, 48, "Rehearse your launch on simulated buyers before you spend a cent.", 15, MUTED))
    out.append(f'<rect x="1000" y="30" width="160" height="24" rx="12" fill="none" stroke="{YELLOW}"/>'
               + text(1080, 46, "every number simulated", 11, YELLOW, 600, mono=True, anchor="middle"))

    # 1. your ad
    out.append(panel(40, "YOUR AD", "1", 300))
    ad = show(0.2, "translateY(10px)")
    out.append(f'<g class="{ad}">'
               f'<rect x="60" y="132" width="260" height="188" rx="10" fill="{CREAM}"/>'
               f'<circle cx="80" cy="152" r="10" fill="{YELLOW}"/>'
               + text(96, 151, "Fitloop", 13, INK, 700) + text(96, 165, "Sponsored", 10, "#6b6a63")
               + f'<rect x="72" y="174" width="236" height="74" rx="6" fill="{INK}"/>'
               + text(190, 205, "12-minute workouts", 18, YELLOW, 700, anchor="middle")
               + text(190, 228, "at home, no equipment", 12, CREAM, 400, anchor="middle")
               + text(72, 268, "Try 7 days free. Cancel anytime.", 13, INK, 500)
               + f'<rect x="72" y="282" width="236" height="26" rx="6" fill="{INK}"/>'
               + text(190, 299, "Start free trial", 12, CREAM, 600, anchor="middle") + "</g>")
    # the command being typed
    out.append(f'<rect x="60" y="334" width="260" height="32" rx="8" fill="{INK}" stroke="{LINE}"/>')
    out.append(f'<clipPath id="type"><rect x="72" y="338" width="236" height="24" class="{typing(0.7, 1.3, 22)}"/></clipPath>')
    out.append(f'<g clip-path="url(#type)">' + text(74, 355, "$ ./mm cli market-test", 13, YELLOW, 500, mono=True) + "</g>")

    # 2. simulated buyers
    out.append(panel(370, "SIMULATED BUYERS SCROLL, REACT, ARGUE", "2", 460))
    people = [("PR", "Priya", "Pune, 29", "#c792ea", "stopped 3s", CREAM),
              ("JO", "Joseph", "Nairobi, 41", "#82aaff", "scrolled past", MUTED),
              ("AN", "Ana", "Manila, 34", "#ffcb6b", "clicked", YES),
              ("SA", "Sam", "Austin, 52", "#89ddff", "“Really free?”", YELLOW),
              ("ME", "Mei", "Taipei, 26", "#f78c6c", "saved", YES),
              ("LU", "Luca", "Milan, 38", "#c3e88d", "hid the ad", NO)]
    for i, (ini, name, where, col, react, rcol) in enumerate(people):
        cx = 445 + (i % 3) * 150
        cy = 160 + (i // 3) * 92
        t = 2.2 + 0.75 * i
        out.append(f'<g class="{show(0.5 + 0.12 * i, "scale(.6)", overshoot="scale(1.08)")}">'
                   f'<circle cx="{cx}" cy="{cy}" r="20" fill="{col}"/>'
                   + text(cx, cy + 5, ini, 13, INK, 700, anchor="middle")
                   + text(cx, cy + 38, name, 13, CREAM, 600, anchor="middle")
                   + text(cx, cy + 53, where, 11, MUTED, anchor="middle") + "</g>")
        out.append(f'<circle cx="{cx}" cy="{cy}" r="20" fill="none" stroke="{YELLOW}" stroke-width="2" class="{pulse(t + 0.5)}"/>')
        # the ad flies from panel 1 to this person
        out.append(f'<rect x="{cx - 9}" y="{cy - 12}" width="18" height="24" rx="3" fill="{CREAM}" stroke="{YELLOW}" '
                   f'class="{flight(t, 300 - cx, 230 - cy)}"/>')
        bw = 8 + 6.4 * len(react)
        out.append(f'<g class="{show(t + 0.55, "scale(.3)", rise=0.3, overshoot="scale(1.12)")}">'
                   f'<rect x="{cx + 14}" y="{cy - 34}" width="{bw:.0f}" height="20" rx="10" fill="{INK}" stroke="{rcol}"/>'
                   + text(cx + 14 + bw / 2, cy - 20, react, 11, rcol, 600, anchor="middle") + "</g>")
    # the argument (social simulation)
    b1, b2 = show(7.2, "translateX(-10px)"), show(8.0, "translateX(10px)")
    out.append(f'<g class="{b1}"><rect x="392" y="318" width="214" height="28" rx="14" fill="#22221f" stroke="{LINE}"/>'
               + text(404, 336, "Joseph: trials always want my card", 11, CREAM) + "</g>")
    out.append(f'<g class="{b2}"><rect x="596" y="348" width="214" height="28" rx="14" fill="#22221f" stroke="{YELLOW}"/>'
               + text(608, 366, "Ana: this one didn’t ask for it", 11, CREAM) + "</g>")

    # 3. what they'd do
    out.append(panel(860, "WHAT THEY WOULD DO", "3", 300))
    for k, (label, pct, col) in enumerate((("Yes", 31, YES), ("Maybe", 46, YELLOW), ("No", 23, NO))):
        y = 150 + 34 * k
        t = 9.0 + 0.35 * k
        out.append(text(882, y + 11, label, 12, CREAM, 600))
        out.append(f'<rect x="938" y="{y}" width="160" height="14" rx="7" fill="#22221f"/>')
        out.append(f'<rect x="938" y="{y}" width="{1.6 * pct:.0f}" height="14" rx="7" fill="{col}" class="{grow(t)}"/>')
        out.append(text(1138, y + 12, f"{pct}%", 12, col, 700, anchor="end", cls=show(t + 0.8, "none")))
    out.append(f'<g class="{show(10.6)}">' + text(882, 268, "Top objection", 11, MUTED, 600, mono=True)
               + text(882, 286, "“Will the free trial charge me?”", 13, CREAM, 600) + "</g>")
    stamp = show(11.4, "scale(1.8) rotate(-14deg)", rise=0.4, overshoot="scale(.94) rotate(-4deg)")
    out.append(f'<g class="{stamp}"><g transform="rotate(-5 960 322)">'
               f'<rect x="882" y="302" width="150" height="40" rx="6" fill="none" stroke="{YELLOW}" stroke-width="3"/>'
               + text(957, 330, "ITERATE", 22, YELLOW, 800, anchor="middle") + "</g></g>")
    out.append(f'<g class="{show(12.1)}">' + text(882, 366, "Fix: say “no card needed” in line one.", 12, CREAM, 500)
               + "</g>")

    out.append(text(W - 40, 406, "Illustration. Fitloop is an invented app; the numbers are simulated.", 11, MUTED,
                    anchor="end", mono=True))

    style = ("<style>" + "".join(css) +
             "@media (prefers-reduced-motion:reduce){*{animation:none!important}}</style>")
    defs = (f'<defs>{style}<pattern id="dots" width="22" height="22" patternUnits="userSpaceOnUse">'
            f'<circle cx="2" cy="2" r="1" fill="#1d1d1a"/></pattern></defs>')
    label = ("MarketMirror in one loop: a Fitloop ad is tested on six simulated buyers in Pune, Nairobi, Manila, Austin, "
             "Taipei and Milan. They scroll, stop, click, save or hide it, two of them argue about the free trial, the "
             "survey shows 31% yes, 46% maybe and 23% no, and the verdict is iterate: say no card needed in line one. "
             "Illustration with simulated numbers.")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" '
            f'aria-label="{esc(label)}"><title>{esc(label)}</title>{defs}{"".join(out)}</svg>\n')


if __name__ == "__main__":
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "images", "marketmirror-loop.svg")
    with open(path, "w", encoding="utf-8") as f:
        f.write(build())
    print(path, os.path.getsize(path), "bytes")
