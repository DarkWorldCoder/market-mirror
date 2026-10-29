"""Write the animated README scenes in docs/images (marketmirror-loop.svg banner plus one scene per section).

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


def begin(loop: float) -> None:
    """Start a new scene: fresh keyframes, its own loop length; everything holds until 0.8 s before the end."""
    global LOOP, END, OUT
    LOOP, END, OUT = loop, loop - 0.8, loop - 0.3
    css.clear()
    _n[0] = 0


def finish(body: List[str], label: str, w: int = W, h: int = H) -> str:
    style = "<style>" + "".join(css) + "@media (prefers-reduced-motion:reduce){*{animation:none!important}.rm{display:none}}</style>"
    defs = (f'<defs>{style}<pattern id="dots" width="22" height="22" patternUnits="userSpaceOnUse">'
            f'<circle cx="2" cy="2" r="1" fill="#1d1d1a"/></pattern></defs>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" '
            f'aria-label="{esc(label)}"><title>{esc(label)}</title>{defs}{"".join(body)}</svg>\n')


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
         end: Optional[float] = None) -> str:
    end = END if end is None else end
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
    begin(14.0)
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
        out.append(f'<circle cx="{cx}" cy="{cy}" r="20" fill="none" stroke="{YELLOW}" stroke-width="2" class="rm {pulse(t + 0.5)}"/>')
        # the ad flies from panel 1 to this person
        out.append(f'<rect x="{cx - 9}" y="{cy - 12}" width="18" height="24" rx="3" fill="{CREAM}" stroke="{YELLOW}" '
                   f'class="rm {flight(t, 300 - cx, 230 - cy)}"/>')
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

    label = ("MarketMirror in one loop: a Fitloop ad is tested on six simulated buyers in Pune, Nairobi, Manila, Austin, "
             "Taipei and Milan. They scroll, stop, click, save or hide it, two of them argue about the free trial, the "
             "survey shows 31% yes, 46% maybe and 23% no, and the verdict is iterate: say no card needed in line one. "
             "Illustration with simulated numbers.")
    return finish(out, label)

# --------------------------------------------------------------------------
# Section scenes (one per README section). Same palette and helpers; facts and commands come from the README.
# --------------------------------------------------------------------------

def header(title: str, subtitle: str, chip: str = "", w: int = W) -> str:
    out = (f'<path d="M40 30 h22 v22 h-22z" fill="{YELLOW}"/><path d="M51 30 v22" stroke="{INK}" stroke-width="2"/>'
           f'<path d="M44 46 l7-11 l7 11" fill="none" stroke="{INK}" stroke-width="2"/>'
           + text(74, 47, title, 13, YELLOW, 700, mono=True) + text(74, 66, subtitle, 13, MUTED))
    if chip:
        cw = 16 + 6.7 * len(chip)
        out += (f'<rect x="{w - 40 - cw:.0f}" y="30" width="{cw:.0f}" height="24" rx="12" fill="none" stroke="{YELLOW}"/>'
                + text(w - 40 - cw / 2, 46, chip, 11, YELLOW, 600, mono=True, anchor="middle"))
    return out


def wrap(s: str, n: int) -> List[str]:
    lines, cur = [], ""
    for word in s.split():
        if cur and len(cur) + 1 + len(word) > n:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    return lines + ([cur] if cur else [])


def lines(x: float, y: float, rows: List[str], size: int = 12, fill: str = CREAM, weight: int = 400, gap: float = 16,
          mono: bool = False) -> str:
    return "".join(text(x, y + i * gap, r, size, fill, weight, mono=mono) for i, r in enumerate(rows))


def draw(t0: float, dur: float, length: float) -> str:
    """Stroke drawn from nothing to whole (stroke-dasharray set on the element)."""
    return anim([(0, f"stroke-dashoffset:{length:.0f}"), (t0, f"stroke-dashoffset:{length:.0f}"),
                 (t0 + dur, "stroke-dashoffset:0"), (END, "stroke-dashoffset:0;opacity:1"),
                 (OUT, "stroke-dashoffset:0;opacity:0"), (LOOP, f"stroke-dashoffset:{length:.0f};opacity:0")])


def light(t0: float, off: str, on: str) -> str:
    """Outline colour switches on at t0 and stays until the loop fades."""
    return anim([(0, f"stroke:{off}"), (t0, f"stroke:{off}"), (t0 + 0.3, f"stroke:{on}"), (OUT, f"stroke:{on}"),
                 (LOOP, f"stroke:{off}")])


def flow() -> str:
    """Dashes that keep moving along a connector."""
    css.append("@keyframes flow{to{stroke-dashoffset:-20}}.flow{animation:flow 1s linear infinite}")
    return "flow"


def card(x: float, y: float, w: float, h: float, title: str, step: str = "") -> str:
    out = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{SURFACE}" stroke="{LINE}"/>'
    if step:
        out += (f'<circle cx="{x + 24}" cy="{y + 24}" r="10" fill="{YELLOW}"/>'
                + text(x + 24, y + 28, step, 12, INK, 700, anchor="middle"))
    return out + text(x + (42 if step else 20), y + 28, title, 11, MUTED, 600, mono=True)


def scene_buyers() -> str:
    """Meet the simulated buyers: Yash's life interview fills his persona and decision card (README example)."""
    begin(17.0)
    out = [f'<rect width="{W}" height="{H}" rx="20" fill="{BG}"/><rect width="{W}" height="{H}" rx="20" fill="url(#dots)"/>',
           header("MEET THE SIMULATED BUYERS", "Every person is written, interviewed and given a decision card before any test.",
                  "simulated person, not a customer")]
    out.append(card(40, 84, 360, 280, "LIFE INTERVIEW · 12 QUESTIONS", "1"))
    qa = [("What phone do you use, and what is your data plan like?", "Realme 9 Pro, Jio prepaid ₹349, 2 GB a day."),
          ("Tell me about a time you got scammed.", "₹6,000 went on a crypto course. Now I read reviews."),
          ("Who do you ask before spending real money?", "Pooja, my wife, my mother, and Santosh at the stall."),
          ("What annoys you most in ads?", "Over-promising, long unskippable ads, card upfront.")]
    for i, (q, a) in enumerate(qa):
        y, t = 128 + 58 * i, 0.6 + 1.9 * i
        out.append(f'<g class="{show(t)}">' + text(60, y, q, 11, MUTED, 500) + "</g>")
        out.append(f'<g class="{show(t + 0.8, "translateX(-8px)")}"><rect x="60" y="{y + 8}" width="322" height="26" rx="13" '
                   f'fill="#22221f" stroke="{LINE}"/>' + text(74, y + 25, a, 12, CREAM, 500) + "</g>")

    out.append(card(420, 84, 360, 280, "PERSONA", "2"))
    out.append(f'<g class="{show(0.3, "scale(.7)", overshoot="scale(1.06)")}"><circle cx="464" cy="146" r="22" fill="#c792ea"/>'
               + text(464, 151, "YM", 13, INK, 700, anchor="middle") + text(498, 141, "Yash Malhotra, 42, Pune", 15, CREAM, 700)
               + text(498, 160, "App-cab owner-driver · weekend accessories stall", 11, MUTED) + "</g>")
    rows = [("Income", "Lower-middle", 0.6), ("Phone", "Realme 9 Pro · Jio prepaid ₹349", 1.4),
            ("Scam history", "Lost ₹6,000 to a crypto course", 3.3), ("Asks first", "Pooja (wife), his mother, Santosh", 5.2),
            ("Community", "Working Moms & Dads India", 6.4)]
    for i, (k, v, t) in enumerate(rows):
        y = 200 + 30 * i
        out.append(f'<g class="{show(t + 0.9, "translateX(-10px)")}">' + text(440, y, k, 11, MUTED, 600, mono=True)
                   + text(540, y, v, 12, CREAM, 500) + "</g>")
    out.append(f'<circle cx="464" cy="146" r="22" fill="none" stroke="{YELLOW}" stroke-width="2" class="rm {pulse(7.6)}"/>')

    out.append(card(800, 84, 360, 280, "DECISION CARD", "3"))
    dec = [("Says yes to", "free trial, cheap price, family plan, a Hindi coach", YES),
           ("Walks away from", "card needed upfront, hidden charges, over-promising ads", NO),
           ("Trusts", "reviews with 4+ stars, clear prices, family opinion", CREAM),
           ("Says vs does", "says 15 minutes in waiting time; long shifts make it unlikely", YELLOW)]
    for i, (k, v, col) in enumerate(dec):
        y, t = 128 + 58 * i, 8.4 + 0.8 * i
        out.append(f'<g class="{show(t, "translateY(8px)")}"><rect x="818" y="{y - 14}" width="4" height="40" rx="2" fill="{col}"/>'
                   + text(832, y, k, 11, col, 700, mono=True) + lines(832, y + 18, wrap(v, 44), 12, CREAM, gap=15) + "</g>")

    guard = show(12.0, "translateY(6px)")
    out.append(f'<g class="{guard}"><circle cx="52" cy="384" r="9" fill="{YES}"/><path d="M47 384 l4 4 l7-8" fill="none" '
               f'stroke="{INK}" stroke-width="2"/>' + text(70, 389, "Stereotype guard: no two people in an audience share both a "
                                                            "job and a city.", 12, CREAM, 500) + "</g>")
    for i in range(8):
        cx = 640 + 26 * i
        col = ("#82aaff", "#ffcb6b", "#89ddff", "#f78c6c", "#c3e88d", "#c792ea", "#ff9cac", "#b2ccd6")[i]
        out.append(f'<circle cx="{cx}" cy="384" r="10" fill="{col}" class="{show(12.5 + 0.15 * i, "scale(.2)", overshoot="scale(1.2)")}"/>')
    out.append(f'<g class="{show(13.8)}">' + text(860, 389, "next buyers, each interviewed", 12, MUTED) + "</g>")
    out.append(text(W - 40, 410, "Yash is one simulated person from the README's 3,000-person run, abridged.", 11, MUTED,
                    anchor="end", mono=True))
    label = ("Meet the simulated buyers: Yash Malhotra, 42, an app-cab owner-driver in Pune and one simulated person from the "
             "3,000-person run, answers his life interview (Realme 9 Pro on Jio prepaid at 349 rupees, lost 6,000 rupees to a "
             "crypto course, asks his wife, his mother and a stall partner before buying). His persona fills in, then his "
             "decision card: says yes to a free trial, cheap price, family plan and a Hindi coach; walks away from a card "
             "needed upfront, hidden charges and over-promising ads; trusts 4+ star reviews, clear prices and family opinion; "
             "says he would exercise in waiting time but long shifts make it unlikely. The stereotype guard checks that no two "
             "people in an audience share a job and a city, and the next buyers appear.")
    return finish(out, label)


def scene_tests() -> str:
    """What you can test: ten test types ticked off along a path."""
    begin(16.0)
    out = [f'<rect width="{W}" height="{H}" rx="20" fill="{BG}"/><rect width="{W}" height="{H}" rx="20" fill="url(#dots)"/>',
           header("WHAT YOU CAN TEST", "Ten questions, one simulated market. Check what matters with a small real test.",
                  "results are simulated")]
    stops = [("Ads in feeds", "stop, ignore, click, hide"), ("Headlines", "which wording is clearer"),
             ("Price and offer", "where price worries start"), ("Launch talk", "objections in social rounds"),
             ("Emails", "inbox choices; none sent"), ("Sales pitch", "which concerns persist"),
             ("Your website", "where visitors leave"), ("Audiences", "which group to study first"),
             ("Next test", "from the run and your data"), ("Sim vs real", "backtest on real results")]
    xs = [130, 365, 600, 835, 1070]
    pts = [(x, 176) for x in xs] + [(x, 290) for x in reversed(xs)]
    d = "M" + " L".join(f"{x} {y}" for x, y in pts)
    seg = [abs(pts[i + 1][0] - pts[i][0]) + abs(pts[i + 1][1] - pts[i][1]) for i in range(len(pts) - 1)]
    total = sum(seg)
    out.append(f'<path d="{d}" fill="none" stroke="{LINE}" stroke-width="4" stroke-linejoin="round"/>')
    times = [1.0 + 1.15 * i for i in range(len(pts))]
    stops_css = [(0, f"stroke-dashoffset:{total:.0f};opacity:1"), (times[0], f"stroke-dashoffset:{total:.0f};opacity:1")]
    move = [(0, f"opacity:0;transform:translate({pts[0][0]}px,{pts[0][1]}px)"),
            (times[0] - 0.4, f"opacity:1;transform:translate({pts[0][0]}px,{pts[0][1]}px)")]
    done = 0.0
    for i in range(1, len(pts)):
        done += seg[i - 1]
        stops_css.append((times[i], f"stroke-dashoffset:{total - done:.0f};opacity:1"))
        move.append((times[i] - 0.35, f"opacity:1;transform:translate({pts[i][0]}px,{pts[i][1]}px)"))
        move.append((times[i], f"opacity:1;transform:translate({pts[i][0]}px,{pts[i][1]}px)"))
    stops_css += [(END, "stroke-dashoffset:0;opacity:1"), (OUT, "stroke-dashoffset:0;opacity:0"), (LOOP, f"stroke-dashoffset:{total:.0f};opacity:0")]
    move += [(times[-1] + 0.3, f"opacity:0;transform:translate({pts[-1][0]}px,{pts[-1][1]}px)"),
             (LOOP, f"opacity:0;transform:translate({pts[0][0]}px,{pts[0][1]}px)")]
    out.append(f'<path d="{d}" fill="none" stroke="{YELLOW}" stroke-width="4" stroke-linejoin="round" '
               f'stroke-dasharray="{total:.0f}" class="{anim(stops_css)}"/>')
    for i, ((x, y), (title, learn)) in enumerate(zip(pts, stops)):
        t = times[i]
        out.append(f'<circle cx="{x}" cy="{y}" r="17" fill="{SURFACE}" stroke="{LINE}" stroke-width="3"/>')
        out.append(f'<g class="{show(t, "scale(.3)", rise=0.3, overshoot="scale(1.2)")}"><circle cx="{x}" cy="{y}" r="17" '
                   f'fill="{YELLOW}"/><path d="M{x - 7} {y} l5 5 l9-10" fill="none" stroke="{INK}" stroke-width="3" '
                   f'stroke-linecap="round" stroke-linejoin="round"/></g>')
        out.append(text(x, y + 6, str(i + 1), 12, MUTED, 700, anchor="middle", cls="rm " + anim(
            [(0, "opacity:1"), (t, "opacity:1"), (t + 0.1, "opacity:0"), (OUT, "opacity:0"), (LOOP, "opacity:1")])))
        ty1, ty2 = (y - 50, y - 32) if i < 5 else (y + 42, y + 60)       # row one labels above, row two below
        out.append(f'<g class="{show(t + 0.15)}">' + text(x, ty1, title, 14, CREAM, 700, anchor="middle")
                   + text(x, ty2, learn, 12, MUTED, anchor="middle") + "</g>")
    out.append(f'<circle cx="0" cy="0" r="7" fill="{CREAM}" stroke="{YELLOW}" stroke-width="3" class="rm {anim(move)}"/>')
    out.append(f'<g class="{show(times[-1] + 0.6)}">' + text(600, 392, "Repeat a comparison or swap model providers to see "
                                                            "how much a result moves between runs.", 13, CREAM, 500,
                                                            anchor="middle") + "</g>")
    label = ("What you can test, ticked off one by one along a path: ads in simulated Facebook, Instagram, Reddit, TikTok, "
             "LinkedIn or X feeds; headlines and messages; price and offer; the conversation around a launch; emails in "
             "simulated inboxes, with none sent; a sales pitch; your real website; which audience to study first; the next "
             "test to run; and simulated versus real results. Repeat a comparison or swap providers to see how much a "
             "result moves.")
    return finish(out, label)


def scene_pipeline() -> str:
    """How it works: six stages light up in turn; real results feed the next experiment."""
    begin(15.0)
    out = [f'<rect width="{W}" height="{H}" rx="20" fill="{BG}"/><rect width="{W}" height="{H}" rx="20" fill="url(#dots)"/>',
           header("HOW IT WORKS", "One command, market-test, runs the stages from one config. Every output is saved in the run folder.",
                  "./mm cli market-test")]
    stages = [("Your product", ["brief, documents", "or website"]),
              ("Profile + graph", ["product profile,", "local knowledge graph"]),
              ("Simulated buyers", ["interviews and", "decision cards"]),
              ("Feeds + rounds", ["ads in six feeds,", "OASIS social rounds"]),
              ("Survey + pitch", ["free text to 1-5", "(SSR), objections"]),
              ("Report", ["go · iterate · no-go,", "offline dashboard"])]
    bw, gap, y0, bh = 164, 25, 92, 210
    fl = flow()
    for i, (title, sub) in enumerate(stages):
        x = 40 + i * (bw + gap)
        t = 0.6 + 1.5 * i
        out.append(f'<rect x="{x}" y="{y0}" width="{bw}" height="{bh}" rx="14" fill="{SURFACE}" stroke-width="2" '
                   f'class="{light(t, LINE, YELLOW)}"/>')
        out.append(f'<circle cx="{x + 22}" cy="{y0 + 22}" r="10" fill="{YELLOW}"/>' + text(x + 22, y0 + 26, str(i + 1), 12, INK, 700, anchor="middle"))
        out.append(text(x + 40, y0 + 27, title, 13, CREAM, 700))
        out.append(lines(x + 16, y0 + 172, sub, 11, MUTED, gap=15))
        cx, cy = x + bw / 2, y0 + 100
        g = show(t + 0.2, "scale(.8)")
        if i == 0:
            icon = (f'<rect x="{cx - 34}" y="{cy - 44}" width="68" height="84" rx="6" fill="{CREAM}"/>'
                    + "".join(f'<rect x="{cx - 24}" y="{cy - 30 + 12 * k}" width="{48 - 10 * (k % 2)}" height="5" rx="2" fill="#8a887f"/>' for k in range(5)))
        elif i == 1:
            nodes = [(-40, -26), (0, -40), (38, -20), (-28, 20), (16, 12), (42, 34), (-6, 42)]
            edges = [(0, 1), (1, 2), (0, 3), (1, 4), (4, 2), (4, 5), (3, 6), (4, 6)]
            icon = "".join(f'<line x1="{cx + nodes[a][0]}" y1="{cy + nodes[a][1]}" x2="{cx + nodes[b][0]}" y2="{cy + nodes[b][1]}" '
                           f'stroke="#5c5a52" stroke-width="2"/>' for a, b in edges)
            icon += "".join(f'<circle cx="{cx + nx}" cy="{cy + ny}" r="7" fill="{("#82aaff", YELLOW, "#c3e88d")[k % 3]}" '
                            f'class="{show(t + 0.3 + 0.12 * k, "scale(.2)")}"/>' for k, (nx, ny) in enumerate(nodes))
        elif i == 2:
            cols = ("#c792ea", "#82aaff", "#ffcb6b", "#89ddff", "#f78c6c", "#c3e88d")
            icon = "".join(f'<circle cx="{cx - 40 + 40 * (k % 3)}" cy="{cy - 20 + 44 * (k // 3)}" r="15" fill="{cols[k]}" '
                           f'class="{show(t + 0.3 + 0.15 * k, "scale(.2)", overshoot="scale(1.15)")}"/>' for k in range(6))
        elif i == 3:
            icon = "".join(f'<g class="{show(t + 0.3 + 0.25 * k, "translateY(14px)")}"><rect x="{cx - 50}" y="{cy - 46 + 32 * k}" '
                           f'width="100" height="26" rx="5" fill="{"#f4f1ea" if k == 1 else "#22221f"}"/>'
                           f'<circle cx="{cx - 38}" cy="{cy - 33 + 32 * k}" r="6" fill="{("#82aaff", YELLOW, "#c3e88d")[k]}"/>'
                           f'<rect x="{cx - 26}" y="{cy - 36 + 32 * k}" width="{60 - 12 * k}" height="5" rx="2" fill="#8a887f"/></g>'
                           for k in range(3))
        elif i == 4:
            icon = "".join(f'<rect x="{cx - 48 + 20 * k}" y="{cy + 40 - hgt}" width="14" height="{hgt}" rx="3" '
                           f'fill="{YELLOW if k == 3 else "#5c5a52"}" class="{anim([(0, "transform:scaleY(0)"), (t + 0.3 + 0.1 * k, "transform:scaleY(0)"), (t + 0.9 + 0.1 * k, "transform:scaleY(1)"), (OUT, "transform:scaleY(1)"), (LOOP, "transform:scaleY(0)")], "transform-box:fill-box;transform-origin:50% 100%")}"/>'
                           for k, hgt in enumerate((14, 30, 46, 70, 38)))
        else:
            icon = "".join(f'<g class="{show(t + 0.3 + 0.3 * k, "scale(.4)", overshoot="scale(1.1)")}"><rect x="{cx - 52}" y="{cy - 40 + 30 * k}" '
                           f'width="104" height="22" rx="11" fill="none" stroke="{col}" stroke-width="2"/>'
                           + text(cx, cy - 25 + 30 * k, lab, 12, col, 700, anchor="middle") + "</g>"
                           for k, (lab, col) in enumerate((("go", YES), ("iterate", YELLOW), ("no-go", NO))))
        out.append(f'<g class="{g}">{icon}</g>' if i in (0,) else icon)
        if i < len(stages) - 1:
            xa = x + bw + 2
            out.append(f'<line x1="{xa}" y1="{y0 + 100}" x2="{xa + gap - 4}" y2="{y0 + 100}" stroke="{YELLOW}" stroke-width="3" '
                       f'stroke-dasharray="4 6" class="{fl}"/>')
            out.append(f'<circle cx="{xa + gap / 2}" cy="{y0 + 100}" r="5" fill="{CREAM}" class="rm {pulse(t + 1.2)}"/>')
    # check against reality: loop back
    loop_d = f"M{40 + 5 * (bw + gap) + bw / 2} {y0 + bh + 2} V352 H{40 + bw / 2} V{y0 + bh + 6}"
    out.append(f'<path d="{loop_d}" fill="none" stroke="{LINE}" stroke-width="3"/>')
    length = 5 * (bw + gap) + 2 * (352 - y0 - bh)
    out.append(f'<path d="{loop_d}" fill="none" stroke="{YES}" stroke-width="3" stroke-dasharray="{length:.0f}" class="{draw(10.0, 1.6, length)}"/>')
    out.append(f'<path d="M{40 + bw / 2 - 7} {y0 + bh + 16} l7 -10 l7 10" fill="none" stroke="{YES}" stroke-width="3" class="{show(11.5, "none")}"/>')
    out.append(f'<g class="{show(10.4)}"><rect x="360" y="338" width="480" height="28" rx="14" fill="{BG}" stroke="{YES}"/>'
               + text(600, 357, "6. Check against reality: backtest, calibrate, next experiment", 12, YES, 600, anchor="middle") + "</g>")
    out.append(text(W - 40, 404, "A go is a simulation signal, not a sales guarantee.", 11, MUTED, anchor="end", mono=True))
    label = ("How it works, as a moving pipeline: your product brief, documents or website become a product profile and a "
             "local knowledge graph; simulated buyers are interviewed and given decision cards; they see your ads in six "
             "feeds and talk in OASIS social rounds; a survey turns their free text into 1-5 ratings with semantic similarity "
             "rating and a pitch collects objections; the report gives go, iterate or no-go with an offline dashboard. Real "
             "results then come back for backtests and calibration, and feed the next experiment. One command, market-test, "
             "runs the stages from one config.")
    return finish(out, label)


def scene_quickstart() -> str:
    """Quick start: the README's install and agent commands typed, then the dashboard window opens."""
    begin(18.0)
    out = [f'<rect width="{W}" height="{H}" rx="20" fill="{BG}"/><rect width="{W}" height="{H}" rx="20" fill="url(#dots)"/>',
           header("QUICK START", "Clone, install, answer nine questions. Or add the MCP server to the agent you already use.",
                  "Linux, macOS or WSL")]
    tx, ty, tw, th = 40, 84, 720, 300
    out.append(f'<rect x="{tx}" y="{ty}" width="{tw}" height="{th}" rx="12" fill="{INK}" stroke="{LINE}"/>'
               f'<path d="M{tx} {ty + 30} H{tx + tw}" stroke="{LINE}"/>'
               + "".join(f'<circle cx="{tx + 20 + 16 * k}" cy="{ty + 15}" r="5" fill="{c}"/>' for k, c in enumerate((NO, YELLOW, YES)))
               + text(tx + tw / 2, ty + 19, "market-mirror", 11, MUTED, 600, mono=True, anchor="middle"))
    steps = [("$ git clone https://github.com/DarkWorldCoder/market-mirror.git && cd market-mirror", 0.6, True),
             ("$ bash install.sh --configure", 3.0, True),
             ("# installs the engine, then asks which model provider to use", 4.4, False),
             ("$ ./mm start && ./mm cli quickstart --out scenarios/acme", 5.2, True),
             ("# 9 questions; prepares a small simulated market, then stops for review", 7.4, False),
             ("# already in Claude Code, Codex, Gemini CLI or Cursor?", 8.6, False),
             ("$ claude mcp add market-mirror -- uvx marketmirror", 9.2, True),
             ("# then ask your agent to run doctor and setup", 11.2, False)]
    y = ty + 58
    for k, (line, t, typed) in enumerate(steps):
        if k == 5:
            y += 12
        size = 12.5
        width = 0.6 * size * len(line) + 6
        col = YELLOW if typed else MUTED
        if typed:
            dur = max(0.8, len(line) / 40)
            out.append(f'<clipPath id="t{k}"><rect x="{tx + 18}" y="{y - 14}" width="{width:.0f}" height="20" '
                       f'class="{typing(t, dur, len(line))}"/></clipPath>')
            out.append(f'<g clip-path="url(#t{k})" class="{show(t, "none", rise=0.01)}">'
                       + text(tx + 20, y, line, size, CREAM, 500, mono=True).replace(">$ ", f'><tspan fill="{YELLOW}">$</tspan> ', 1) + "</g>")
        else:
            out.append(f'<g class="{show(t, "none", rise=0.2)}">' + text(tx + 20, y, line, size, col, 400, mono=True) + "</g>")
        y += 30
    # the dashboard opens
    dx, dy, dw, dh = 790, 84, 370, 300
    win = show(12.2, "translateY(24px) scale(.96)", rise=0.5)
    secs = ["Decision", "Report", "Feed test", "Social feed", "Audiences", "Objections", "Pricing", "People"]
    chips, cx_, cy_ = [], dx + 18, dy + 214
    for k, sname in enumerate(secs):
        cw = 16 + 7 * len(sname)
        if cx_ + cw > dx + dw - 16:
            cx_, cy_ = dx + 18, cy_ + 30
        chips.append(f'<g class="{show(13.0 + 0.15 * k, "scale(.4)", overshoot="scale(1.1)")}"><rect x="{cx_}" y="{cy_}" '
                     f'width="{cw:.0f}" height="22" rx="11" fill="#22221f" stroke="{LINE}"/>'
                     + text(cx_ + cw / 2, cy_ + 15, sname, 11, CREAM, 500, anchor="middle") + "</g>")
        cx_ += cw + 8
    bars = "".join(f'<rect x="{dx + 88}" y="{dy + 116 + 22 * k}" width="200" height="12" rx="6" fill="#22221f"/>'
                   f'<rect x="{dx + 88}" y="{dy + 116 + 22 * k}" width="{2 * pct}" height="12" rx="6" fill="{col}" class="{grow(12.8 + 0.2 * k, 0.7)}"/>'
                   + text(dx + 20, dy + 126 + 22 * k, lab, 11, CREAM, 600) + text(dx + 300, dy + 126 + 22 * k, f"{pct}%", 11, col, 700)
                   for k, (lab, pct, col) in enumerate((("Yes", 31, YES), ("Maybe", 46, YELLOW), ("No", 23, NO))))
    out.append(f'<g class="{win}"><rect x="{dx}" y="{dy}" width="{dw}" height="{dh}" rx="12" fill="{SURFACE}" stroke="{YELLOW}"/>'
               f'<path d="M{dx} {dy + 30} H{dx + dw}" stroke="{LINE}"/>'
               + text(dx + 16, dy + 19, "dashboard.html · opens offline", 11, MUTED, 600, mono=True)
               + text(dx + 20, dy + 62, "Decision", 11, MUTED, 600, mono=True)
               + f'<rect x="{dx + 20}" y="{dy + 70}" width="110" height="28" rx="6" fill="none" stroke="{YELLOW}" stroke-width="2"/>'
               + text(dx + 75, dy + 89, "ITERATE", 14, YELLOW, 800, anchor="middle")
               + text(dx + 146, dy + 89, "illustrative numbers", 11, MUTED, mono=True)
               + bars + "".join(chips) + "</g>")
    out.append(text(W - 40, 406, "Commands from this README. The dashboard numbers are illustrative.", 11, MUTED, anchor="end", mono=True))
    label = ("Quick start typed in a terminal: git clone https://github.com/DarkWorldCoder/market-mirror.git and cd "
             "market-mirror; bash install.sh --configure, which installs the engine and asks which model provider to use; "
             "./mm start and ./mm cli quickstart --out scenarios/acme, which asks 9 questions, prepares a small simulated "
             "market and stops for review. For an existing agent: claude mcp add market-mirror -- uvx marketmirror, then ask "
             "the agent to run doctor and setup. An offline dashboard.html then opens with a decision, survey bars with "
             "illustrative numbers, and its sections: Decision, Report, Feed test, Social feed, Audiences, Objections, "
             "Pricing and People.")
    return finish(out, label)


def scene_star() -> str:
    """Support the project: a star button gets pressed."""
    w, h = W, 260
    begin(10.0)
    out = [f'<rect width="{w}" height="{h}" rx="20" fill="{BG}"/><rect width="{w}" height="{h}" rx="20" fill="url(#dots)"/>']
    cx, cy, r1, r2 = 190, 130, 78, 34
    import math
    pts = []
    for k in range(10):
        a = -math.pi / 2 + k * math.pi / 5
        r = r1 if k % 2 == 0 else r2
        pts.append(f"{cx + r * math.cos(a):.1f} {cy + r * math.sin(a):.1f}")
    star = "M" + " L".join(pts) + "Z"
    per = 10 * math.dist((cx + r1 * math.cos(-math.pi / 2), cy + r1 * math.sin(-math.pi / 2)),
                         (cx + r2 * math.cos(-math.pi / 2 + math.pi / 5), cy + r2 * math.sin(-math.pi / 2 + math.pi / 5)))
    out.append(f'<path d="{star}" fill="none" stroke="{LINE}" stroke-width="4" stroke-linejoin="round"/>')
    out.append(f'<path d="{star}" fill="none" stroke="{YELLOW}" stroke-width="4" stroke-linejoin="round" '
               f'stroke-dasharray="{per:.0f}" class="{draw(0.4, 1.6, per)}"/>')
    out.append(f'<path d="{star}" fill="{YELLOW}" class="{show(4.3, "scale(.5)", overshoot="scale(1.12)")}"/>')
    for k in range(8):
        a = k * math.pi / 4
        x1, y1 = cx + 96 * math.cos(a), cy + 96 * math.sin(a)
        x2, y2 = cx + 116 * math.cos(a), cy + 116 * math.sin(a)
        out.append(f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" stroke="{YELLOW}" stroke-width="3" '
                   f'stroke-linecap="round" class="rm {anim([(0, "opacity:0"), (4.4, "opacity:0"), (4.6, "opacity:1"), (5.4, "opacity:0"), (LOOP, "opacity:0")])}"/>')
    out.append(text(340, 104, "If MarketMirror saves you one bad launch,", 24, CREAM, 700))
    out.append(text(340, 136, "a star helps other people find it.", 24, CREAM, 700))
    out.append(text(340, 172, "And tell us what you tested: every issue gets an answer.", 15, MUTED))
    bx, by = 960, 104
    out.append(f'<rect x="{bx}" y="{by}" width="170" height="44" rx="10" fill="#22221f" stroke="{LINE}"/>'
               f'<path d="M{bx + 30} {by + 12} l4 8 9 1 -7 6 2 9 -8 -5 -8 5 2 -9 -7 -6 9 -1z" fill="none" stroke="{CREAM}" stroke-width="1.6"/>'
               + text(bx + 56, by + 28, "Star", 16, CREAM, 600))
    out.append(f'<g class="{show(4.2, "scale(.9)", rise=0.25, overshoot="scale(1.05)")}"><rect x="{bx}" y="{by}" width="170" height="44" '
               f'rx="10" fill="{YELLOW}"/><path d="M{bx + 30} {by + 12} l4 8 9 1 -7 6 2 9 -8 -5 -8 5 2 -9 -7 -6 9 -1z" fill="{INK}"/>'
               + text(bx + 56, by + 28, "Starred", 16, INK, 700) + "</g>")
    cursor = anim([(0, "opacity:0;transform:translate(120px,90px)"), (2.2, "opacity:1;transform:translate(120px,90px)"),
                   (3.8, "opacity:1;transform:translate(0,0)"), (4.0, "opacity:1;transform:translate(0,0) scale(.85)"),
                   (4.25, "opacity:1;transform:translate(0,0) scale(1)"), (END, "opacity:1;transform:translate(0,0)"),
                   (OUT, "opacity:0;transform:translate(0,0)"), (LOOP, "opacity:0;transform:translate(120px,90px)")],
                  "transform-box:fill-box;transform-origin:0 0")
    out.append(f'<path d="M{bx + 120} {by + 24} l0 22 6 -6 5 10 4 -2 -5 -10 8 0z" fill="{CREAM}" stroke="{INK}" stroke-width="1.5" class="{cursor}"/>')
    out.append(text(bx + 85, by + 76, "github.com/DarkWorldCoder/market-mirror", 11, MUTED, mono=True, anchor="middle"))
    label = ("Support the project: a star outline draws itself and fills yellow, a cursor presses the Star button and it "
             "turns to Starred. If MarketMirror saves you one bad launch, a star helps other people find it; tell us what "
             "you tested, every issue gets an answer.")
    return finish(out, label, w, h)


def backdrop() -> str:
    return f'<rect width="{W}" height="{H}" rx="20" fill="{BG}"/><rect width="{W}" height="{H}" rx="20" fill="url(#dots)"/>'


def scene_market_map() -> str:
    """Put them in the world: scattered buyers cluster into communities, then pushed-in news spreads as a wave."""
    import math
    import random
    begin(16.0)
    rng = random.Random(7)
    out = [backdrop(), header("SOCIAL ROUNDS", "People join communities, follow each other, then react to what you push in.",
                              "OASIS social simulation")]
    groups = [("Working Moms & Dads India", 230, 236, "#c792ea"), ("a WhatsApp running group", 600, 236, "#82aaff"),
              ("a subreddit", 970, 236, "#c3e88d")]
    per = 22
    dots: List[Tuple[float, float, str, int]] = []
    for g, (_, gx, gy, col) in enumerate(groups):
        for k in range(per):
            a = k * 2.399963                       # golden-angle spiral: an even, natural-looking cluster
            r = 12.5 * math.sqrt(k + 0.6)
            dots.append((gx + 1.15 * r * math.cos(a), gy + 0.85 * r * math.sin(a), col, g))
    # community halos and names
    for g, (name, gx, gy, col) in enumerate(groups):
        out.append(f'<ellipse cx="{gx}" cy="{gy}" rx="98" ry="74" fill="{col}" fill-opacity=".07" stroke="{col}" '
                   f'stroke-opacity=".5" stroke-dasharray="3 5" class="{show(2.6 + 0.2 * g, "scale(.6)")}"/>')
        out.append(f'<g class="{show(2.9 + 0.2 * g)}">' + text(gx, gy + 100, name, 13, col, 600, anchor="middle") + "</g>")
    # follows inside each community, and bridges between neighbouring communities (their facing edges)
    edges = []
    members = {g: [i for i, d in enumerate(dots) if d[3] == g] for g in range(3)}
    for g in range(3):
        idx = members[g]
        for i in idx[1:]:
            j = min((j for j in idx if j < i), key=lambda j: math.dist(dots[i][:2], dots[j][:2]))
            edges.append((i, j))
    bridges = []
    for g in (0, 1):
        right = sorted(members[g], key=lambda i: -dots[i][0])[:2]
        left = sorted(members[g + 1], key=lambda i: dots[i][0])[:2]
        bridges += list(zip(right, left))
    out.append(f'<g stroke="#3a3934" stroke-width="1.2" class="{show(3.2, "none", rise=0.6)}">'
               + "".join(f'<line x1="{dots[i][0]:.0f}" y1="{dots[i][1]:.0f}" x2="{dots[j][0]:.0f}" y2="{dots[j][1]:.0f}"/>'
                         for i, j in edges) + "</g>")
    for i, j in bridges:
        (x1, y1), (x2, y2) = dots[i][:2], dots[j][:2]
        length = math.dist((x1, y1), (x2, y2))
        out.append(f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" stroke="#8a887f" stroke-width="2" '
                   f'stroke-dasharray="{length:.0f}" class="{draw(3.8, 0.6, length)}"/>')
    # the news drops in and lands on one person near the top of the first community
    seed = min(members[0], key=lambda i: dots[i][1] - 0.3 * dots[i][0])
    entry = {0: seed, 1: bridges[0][1], 2: bridges[2][1]}
    sx, sy = dots[seed][:2]
    news = anim([(0, "opacity:0;transform:translateY(-30px)"), (4.4, "opacity:0;transform:translateY(-30px)"),
                 (4.9, "opacity:1;transform:none"), (END, "opacity:1;transform:none"), (OUT, "opacity:0;transform:none"),
                 (LOOP, "opacity:0;transform:none")], "transform-box:fill-box;transform-origin:50% 50%")
    out.append(f'<g class="{news}"><rect x="420" y="84" width="360" height="34" rx="17" fill="{INK}" stroke="{YELLOW}"/>'
               + text(600, 106, "Live news pushed in: “a competitor just cut its price”", 12, YELLOW, 600, anchor="middle") + "</g>")
    out.append(f'<path d="M420 101 Q{(420 + sx) / 2:.0f} 96 {sx:.0f} {sy - 10:.0f}" fill="none" stroke="{YELLOW}" stroke-width="2" '
               f'stroke-dasharray="4 4" class="rm {anim([(0, "opacity:0"), (5.0, "opacity:0"), (5.2, "opacity:1"), (6.2, "opacity:1"), (6.7, "opacity:0"), (LOOP, "opacity:0")])}"/>')
    hops = {0: 0.0, 1: 1.6, 2: 2.9}                # the news reaches each community through a bridge
    # ripples of conversation
    for g in range(3):
        ex, ey = dots[entry[g]][:2]
        for k in range(2):
            t = 5.3 + hops[g] + 0.6 * k
            out.append(f'<circle cx="{ex:.0f}" cy="{ey:.0f}" r="26" fill="none" stroke="{YELLOW}" stroke-width="2" '
                       f'class="rm {anim([(0, "opacity:0;transform:scale(.2)"), (t, "opacity:.9;transform:scale(.2)"), (t + 1.4, "opacity:0;transform:scale(4)"), (LOOP, "opacity:0;transform:scale(4)")], "transform-box:fill-box;transform-origin:50% 50%")}"/>')
    # the people: scattered -> clustered, then the wave turns them to 'talking about it'
    for i, (x, y, col, g) in enumerate(dots):
        x0, y0 = rng.uniform(70, 1130), rng.uniform(120, 360)
        t_in = 0.3 + 0.02 * i
        move = anim([(0, f"transform:translate({x0 - x:.0f}px,{y0 - y:.0f}px)"), (t_in, f"transform:translate({x0 - x:.0f}px,{y0 - y:.0f}px)"),
                     (t_in + 1.6, "transform:none"), (LOOP, "transform:none")])
        t_w = 5.3 + hops[g] + math.dist((x, y), dots[entry[g]][:2]) / 120
        wave = anim([(0, f"fill:{col}"), (t_w, f"fill:{col}"), (t_w + 0.25, f"fill:{YELLOW}"), (OUT, f"fill:{YELLOW}"), (LOOP, f"fill:{col}")])
        out.append(f'<g class="{move}"><circle cx="{x:.0f}" cy="{y:.0f}" r="7" fill="{YELLOW}" class="{wave}"/></g>')
    # what they say
    tops = [min(members[g], key=lambda i: dots[i][1]) for g in range(3)]
    says = [(tops[0], "“still not paying upfront”", 6.2), (tops[1], "“mine just got cheaper”", 7.6), (tops[2], "“price war incoming?”", 8.9)]
    for i, line, t in says:
        x, y = dots[i][:2]
        y -= 8
        bw = 16 + 6.6 * len(line)
        out.append(f'<g class="{show(t, "translateY(8px) scale(.8)", overshoot="scale(1.05)")}"><rect x="{x - bw / 2:.0f}" y="{y - 64:.0f}" '
                   f'width="{bw:.0f}" height="26" rx="13" fill="#22221f" stroke="{LINE}"/>'
                   f'<path d="M{x - 5:.0f} {y - 38:.0f} l5 7 l5 -7z" fill="#22221f"/>'
                   + text(x, y - 46, line, 12, CREAM, 500, anchor="middle") + "</g>")
    out.append(f'<g class="{show(10.2)}"><circle cx="52" cy="390" r="6" fill="{YELLOW}"/>' + text(66, 394, "talking about the news", 12, CREAM)
               + "".join(f'<circle cx="{246 + 22 * k}" cy="390" r="6" fill="{c}"/>' for k, c in enumerate(g[3] for g in groups))
               + text(316, 394, "not yet", 12, MUTED) + "</g>")
    out.append(text(W - 40, 404, "Community names and the news line are the README's examples; replies illustrative.", 11, MUTED,
                    anchor="end", mono=True))
    label = ("Social rounds as a market map: scattered simulated buyers drift into three communities (Working Moms & Dads "
             "India, a WhatsApp running group and a subreddit) and follow each other. Live news is pushed in, “a competitor "
             "just cut its price”, lands on one person, and spreads as a wave through each community and across the bridges "
             "between them, while people reply: still not paying upfront, mine just got cheaper, price war incoming. "
             "Replies are illustrative.")
    return finish(out, label)


def scene_sales_call() -> str:
    """The sales rehearsal: a call with live waveforms; the arguing rebuttal backfires, then the report's fix."""
    import random
    begin(19.0)
    rng = random.Random(3)
    out = [backdrop(), header("SALES REHEARSAL", "Your pitch goes to every buyer. They object, your rebuttal answers, they decide again.",
                              "dialogue illustrative")]
    css.append("@keyframes wig{0%,100%{transform:scaleY(.18)}50%{transform:scaleY(1)}}"
               ".w{animation:wig .9s ease-in-out infinite;transform-box:fill-box;transform-origin:50% 50%}")
    out.append(card(40, 84, 760, 296, "THE CALL"))
    lanes = [("You", 150, YELLOW, [(0.4, 2.6), (5.4, 7.6), (12.6, 15.0)]),
             ("Buyer", 262, "#82aaff", [(2.9, 5.1), (7.9, 10.0), (15.3, 16.8)])]
    for name, y, col, turns in lanes:
        out.append(text(60, y + 5, name, 12, col, 700, mono=True))
        stops = [(0, "opacity:.25")]
        for a, b in turns:
            stops += [(a, "opacity:.25"), (a + 0.2, "opacity:1"), (b, "opacity:1"), (b + 0.2, "opacity:.25")]
        stops += [(LOOP, "opacity:.25")]
        bars = "".join(f'<rect x="{120 + 9 * k}" y="{y - 22}" width="5" height="44" rx="2.5" fill="{col}" class="w" '
                       f'style="animation-duration:{rng.uniform(.5, 1.2):.2f}s;animation-delay:-{rng.uniform(0, 1):.2f}s"/>'
                       for k in range(72))
        out.append(f'<g class="{anim(stops)}">{bars}</g>')
    says = [(0.5, 150, YELLOW, "“12-minute workouts at home. Try 7 days free.”"),
            (3.0, 262, "#82aaff", "“Will it charge me after day 7?”"),
            (5.5, 150, YELLOW, "“It’s worth it, our members love it.”"),
            (8.0, 262, "#82aaff", "“That sounds like a sales line.”"),
            (12.7, 150, YELLOW, "“After day 7: the exact charge, the cancel steps, your local price.”"),
            (15.4, 262, "#82aaff", "“OK. That I can check.”")]
    for k, (t, y, col, line) in enumerate(says):
        t1 = says[k + 2][0] - 0.35 if k + 2 < len(says) else END        # each line gives way to its lane's next line
        cls = anim([(0, "opacity:0;transform:translateY(6px)"), (t, "opacity:0;transform:translateY(6px)"),
                    (t + 0.3, "opacity:1;transform:none"), (t1, "opacity:1;transform:none"), (t1 + 0.25, "opacity:0;transform:none"),
                    (LOOP, "opacity:0;transform:none")], "transform-box:fill-box")
        rm = "rm " if k + 2 < len(says) else ""                         # reduced motion keeps only the last exchange
        out.append(f'<g class="{rm}{cls}">' + text(120, y + 44, line, 13, CREAM, 500) + "</g>")
    # objection and verdict chips
    out.append(f'<g class="{show(3.3, "scale(.3)", overshoot="scale(1.15)")}"><rect x="620" y="218" width="160" height="26" rx="13" '
               f'fill="{INK}" stroke="{NO}"/>' + text(700, 235, "objection: trust", 12, NO, 700, anchor="middle") + "</g>")
    flip = anim([(0, f"opacity:0;fill:{YELLOW}"), (8.5, f"opacity:0;fill:{YELLOW}"), (8.8, f"opacity:1;fill:{YELLOW}"),
                 (9.4, f"opacity:1;fill:{YELLOW}"), (9.8, f"opacity:1;fill:{NO}"), (END, f"opacity:1;fill:{NO}"),
                 (OUT, f"opacity:0;fill:{NO}"), (LOOP, f"opacity:0;fill:{NO}")])
    out.append(f'<rect x="620" y="300" width="160" height="28" rx="14" class="{flip}" fill="{NO}"/>')
    out.append(f'<g class="{anim([(0, "opacity:0"), (8.8, "opacity:0"), (9.0, "opacity:1"), (9.5, "opacity:1"), (9.7, "opacity:0"), (LOOP, "opacity:0")])}">'
               + text(700, 319, "maybe", 13, INK, 800, anchor="middle") + "</g>")
    out.append(f'<g class="{show(9.7, "scale(.5)", overshoot="scale(1.2)", rise=0.25)}">' + text(700, 319, "maybe → no", 13, INK, 800, anchor="middle") + "</g>")
    out.append(f'<rect x="616" y="296" width="168" height="36" rx="18" fill="{SURFACE}" class="{show(12.4, "none", rise=0.3)}"/>')
    out.append(f'<g class="{show(16.0, "scale(.5)", overshoot="scale(1.1)", rise=0.3)}"><rect x="620" y="300" width="160" height="28" '
               f'rx="14" fill="none" stroke="{MUTED}"/>' + text(700, 319, "decides again", 13, CREAM, 700, anchor="middle") + "</g>")
    # the report's fix (README wording)
    out.append(card(820, 84, 340, 296, "WHAT THE REPORT SAID"))
    out.append(f'<g class="{show(10.4, "translateX(16px)")}">' + lines(840, 140, wrap("In the README’s Fitloop run the pitch made things worse: "
                                                                                    "after the rebuttals, about a fifth of the people moved from maybe to no.", 38), 13, CREAM, 500, gap=19) + "</g>")
    out.append(f'<g class="{show(11.4, "translateX(16px)")}"><rect x="840" y="226" width="300" height="104" rx="10" fill="{INK}" stroke="{YELLOW}"/>'
               + text(856, 248, "THE FIX", 11, YELLOW, 700, mono=True)
               + lines(856, 270, wrap("Show the exact charge after day 7, the cancel steps and the local price instead of arguing.", 36), 13, CREAM, 500, gap=18)
               + "</g>")
    out.append(f'<g class="{show(16.9)}">' + text(840, 358, "Then rehearse again with the new rebuttal.", 12, MUTED) + "</g>")
    out.append(text(W - 40, 404, "Result and fix from the README's 3,000-person run; the call lines are illustrative.", 11, MUTED,
                    anchor="end", mono=True))
    label = ("Sales rehearsal as a live call: your pitch, “12-minute workouts at home, try 7 days free”, gets the buyer’s trust "
             "objection, “will it charge me after day 7?”. An arguing rebuttal, “it’s worth it, our members love it”, backfires "
             "and the buyer moves from maybe to no. The report’s fix from the README’s Fitloop run appears: show the exact "
             "charge after day 7, the cancel steps and the local price instead of arguing, and the call is rehearsed again. "
             "Call lines are illustrative.")
    return finish(out, label)


def scene_gauge() -> str:
    """Decide: signals fly into a 1-5 purchase-intent dial with the README's thresholds; the needle settles."""
    import math
    begin(15.0)
    out = [backdrop(), header("THE DECISION", "The decision card puts go, iterate or no-go at the top, with the signals behind it.",
                              "needle position illustrative")]
    cx, cy, r = 600, 316, 190

    def pt(v: float, rad: float) -> Tuple[float, float]:
        th = math.pi * (1 - (v - 1) / 4)
        return cx + rad * math.cos(th), cy - rad * math.sin(th)

    def arc(v1: float, v2: float, rad: float) -> str:
        (x1, y1), (x2, y2) = pt(v1, rad), pt(v2, rad)
        return f"M{x1:.1f} {y1:.1f} A{rad} {rad} 0 0 1 {x2:.1f} {y2:.1f}"
    for v1, v2, col in ((1, 3.1, NO), (3.1, 3.75, YELLOW), (3.75, 5, YES)):
        length = math.pi * r * (v2 - v1) / 4
        out.append(f'<path d="{arc(v1, v2, r)}" fill="none" stroke="#22221f" stroke-width="26"/>')
        out.append(f'<path d="{arc(v1, v2, r)}" fill="none" stroke="{col}" stroke-width="26" stroke-dasharray="{length:.0f}" '
                   f'class="{draw(0.3 + (v1 - 1) * 0.25, 0.6, length)}"/>')
    for v in (1, 2, 3, 4, 5):
        (x1, y1), (x2, y2) = pt(v, r - 20), pt(v, r - 30)
        out.append(f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" stroke="{MUTED}" stroke-width="2"/>')
        tx, ty = pt(v, r - 46)
        out.append(text(tx, ty + 5, str(v), 13, MUTED, 600, anchor="middle"))
    for v, lab in ((3.1, "3.1"), (3.75, "3.75")):
        tx, ty = pt(v, r + 26)
        out.append(text(tx, ty, lab, 12, CREAM, 700, mono=True, anchor="middle"))
    for v, lab, col in ((2.05, "no-go", NO), (3.52, "iterate", YELLOW), (4.38, "go", YES)):
        tx, ty = pt(v, r + 0)
        out.append(text(tx, ty + 4, lab, 11, INK, 800, anchor="middle"))
    out.append(text(cx, cy + 36, "survey purchase intent, mean on 1-5", 12, MUTED, anchor="middle"))
    # needle: drawn pointing at 1, rotated clockwise to the value
    deg = lambda v: 180 * (v - 1) / 4
    swing = [(0, deg(1)), (2.0, deg(1)), (3.2, deg(4.6)), (4.2, deg(2.2)), (5.1, deg(4.0)), (5.9, deg(2.9)), (6.6, deg(3.55)),
             (7.1, deg(3.4)), (7.5, deg(3.25))]
    stops = [(t, f"transform:rotate({a:.1f}deg)") for t, a in swing] + [(OUT, f"transform:rotate({deg(3.25):.1f}deg)"),
                                                                       (LOOP, f"transform:rotate({deg(1):.1f}deg)")]
    needle = anim(stops, f"transform-origin:{cx}px {cy}px")
    out.append(f'<g class="{needle}" style="transform:rotate({deg(3.25):.1f}deg);transform-origin:{cx}px {cy}px">'
               f'<path d="M{cx} {cy - 5} L{cx - r - 6} {cy} L{cx} {cy + 5}z" fill="{CREAM}" stroke="{INK}" stroke-width="1.5"/></g>')
    out.append(f'<circle cx="{cx}" cy="{cy}" r="13" fill="{CREAM}"/><circle cx="{cx}" cy="{cy}" r="5" fill="{INK}"/>')
    # signals flowing in
    sig = [("Survey: purchase intent", 150), ("Feed test: best ad", 196), ("Top objection", 242), ("Analyst panel", 288)]
    for k, (name, y) in enumerate(sig):
        t = 0.6 + 0.5 * k
        out.append(f'<g class="{show(t, "translateX(-14px)")}"><rect x="40" y="{y - 18}" width="220" height="30" rx="15" '
                   f'fill="{SURFACE}" stroke="{LINE}"/><circle cx="58" cy="{y - 3}" r="5" fill="{YELLOW}"/>'
                   + text(72, y + 1, name, 12, CREAM, 600) + "</g>")
        out.append(f'<circle cx="{cx}" cy="{cy}" r="5" fill="{YELLOW}" class="rm {flight(t + 0.6, 262 - cx, y - 3 - cy)}"/>')
    # five analysts, a check not a vote
    acols = (YELLOW, YELLOW, YES, YELLOW, NO)
    for k, col in enumerate(acols):
        ax = 76 + 40 * k
        out.append(f'<circle cx="{ax}" cy="348" r="13" fill="#22221f" stroke="{LINE}"/>')
        out.append(f'<circle cx="{ax}" cy="348" r="13" fill="{col}" class="{show(8.3 + 0.25 * k, "scale(.2)", overshoot="scale(1.2)")}"/>')
    out.append(text(40, 384, "Five analysts read the run on their own:", 12, CREAM, 600))
    out.append(text(40, 401, "a check on the report, not a vote.", 12, MUTED))
    # the verdict
    out.append(card(900, 120, 260, 220, "DECISION CARD"))
    stamp = show(9.8, "scale(1.7) rotate(-12deg)", rise=0.4, overshoot="scale(.95) rotate(-3deg)")
    out.append(f'<g class="{stamp}"><g transform="rotate(-4 1030 200)"><rect x="950" y="176" width="160" height="46" rx="8" fill="none" '
               f'stroke="{YELLOW}" stroke-width="3"/>' + text(1030, 208, "ITERATE", 24, YELLOW, 800, anchor="middle") + "</g></g>")
    out.append(f'<g class="{show(10.6)}">' + lines(920, 256, ["Change the weak parts", "and test again."], 14, CREAM, 600, gap=20)
               + text(920, 314, "A go does not guarantee sales.", 11, MUTED) + "</g>")
    out.append(text(W - 40, 404, "Thresholds from the README: go needs a mean of 3.75, iterate 3.1.", 11, MUTED, anchor="end", mono=True))
    label = ("The decision as a dial: survey purchase intent, the feed test's best ad, the top objection and the analyst panel "
             "flow into a 1 to 5 gauge with the README's thresholds, no-go below 3.1, iterate from 3.1 and go from 3.75. The "
             "needle hunts back and forth and settles in iterate (an illustrative position). Five analysts each give their own "
             "read, a check on the report rather than a vote, and the decision card stamps iterate: change the weak parts and "
             "test again. A go does not guarantee sales.")
    return finish(out, label)


SCENES = {"marketmirror-loop.svg": build, "marketmirror-buyers.svg": scene_buyers, "marketmirror-tests.svg": scene_tests,
          "marketmirror-pipeline.svg": scene_pipeline, "marketmirror-quickstart.svg": scene_quickstart,
          "marketmirror-star.svg": scene_star, "marketmirror-market-map.svg": scene_market_map,
          "marketmirror-sales-call.svg": scene_sales_call, "marketmirror-gauge.svg": scene_gauge}


if __name__ == "__main__":
    folder = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "images")
    for name, make in SCENES.items():
        path = os.path.join(folder, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(make())
        print(f"{name}: {os.path.getsize(path):,} bytes")
