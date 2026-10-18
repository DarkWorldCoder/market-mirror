"""
feed_view.py - dashboard sections for the feed test (platform-styled post mocks with a
scroll replay), ROI projections, the independent analyst panel, the backtest against
real ads, confidence helpers and the downloads bar. Stdlib only.
"""

from __future__ import annotations

import csv
import html
import io
import json
import math
from typing import Any, Dict, List, Optional, Tuple

try:  # stdlib only
    from marketing import SSR_GO_MEAN, SSR_ITERATE_MEAN  # type: ignore
except ImportError:  # pragma: no cover - imported as a package
    from .marketing import SSR_GO_MEAN, SSR_ITERATE_MEAN  # type: ignore

PLATFORM_LABEL = {"facebook": "Facebook", "instagram": "Instagram", "reddit": "Reddit", "tiktok": "TikTok",
                  "linkedin": "LinkedIn", "x": "X"}
REACTION_EMOJI = {"like": "👍", "love": "❤️", "care": "🤗", "haha": "😆", "wow": "😮", "sad": "😢", "angry": "😡",
                  "celebrate": "👏", "support": "🤝", "insightful": "💡", "funny": "😄", "upvote": "⬆", "downvote": "⬇"}


def _e(v: Any) -> str:
    return html.escape("" if v is None else str(v), quote=True)


def _t(s: Any, n: int) -> str:
    s = "" if s is None else str(s)
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def ci(p_pct: Optional[float], n: int) -> Optional[float]:
    """95% margin of error (percentage points) for a proportion, Wilson-style floor for tiny n."""
    if p_pct is None or not n:
        return None
    p = max(min(p_pct / 100, 1), 0)
    return round(100 * 1.96 * math.sqrt(max(p * (1 - p), 0.25 / n) / n), 1)


def pct_ci(p: Optional[float], n: int) -> str:
    if p is None:
        return "–"
    m = ci(p, n)
    return f"{p:.0f}%" + (f" ±{m:.0f}" if m is not None else "")


def low_n_pill(n: int, threshold: int = 10) -> str:
    return f' <span class="pill orchid" title="Small sample: treat as a direction, not a result">low n={n}</span>' \
        if n < threshold else ""


def _money(v: Any, cur: str = "") -> str:
    if v is None:
        return "–"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"{cur} {v:,.2f}".strip() if abs(v) < 1000 else f"{cur} {v:,.0f}".strip()


# --------------------------------------------------------------------------
# Platform mocks
# --------------------------------------------------------------------------

def _media(cr: Dict[str, Any], tall: bool = False) -> str:
    if cr.get("image"):
        return f'<div class="pm-media{" tall" if tall else ""}"><img src="{_e(cr["image"])}" alt="{_e(cr.get("media") or "ad image")}"></div>'
    fmt = (cr.get("format") or "image").lower()
    icon = "▶" if fmt in ("video", "reel", "reels", "story") else "▦" if fmt == "carousel" else "◼"
    return (f'<div class="pm-media ph{" tall" if tall else ""}"><span class="pm-fmt">{icon} {_e(fmt)}</span>'
            f'<span>{_e(_t(cr.get("media") or cr.get("headline") or cr.get("text"), 140))}</span></div>')


def _avatar(name: str, cls: str = "") -> str:
    return f'<span class="pm-av {cls}">{_e((name or "?").strip()[:1].upper())}</span>'


def _comments_html(comments: List[Dict[str, Any]], style: str, limit: int = 4) -> str:
    out = []
    for cm in comments[:limit]:
        name = _e(str(cm.get("name") or "Someone").split(" (")[0])
        if style == "reddit":
            out.append(f'<div class="pm-rc"><span class="pm-rc-h">{name} · {_e(cm.get("segment"))}</span>'
                       f'<div>{_e(_t(cm.get("text"), 220))}</div><span class="pm-muted">⬆ Reply</span></div>')
        elif style == "ig":
            out.append(f'<div class="pm-igc"><b>{name}</b> {_e(_t(cm.get("text"), 200))}</div>')
        else:
            out.append(f'<div class="pm-c">{_avatar(name)}<div class="pm-bubble"><b>{name}</b>'
                       f'<div>{_e(_t(cm.get("text"), 220))}</div></div></div>')
    return f'<div class="pm-comments" data-role="comments">{"".join(out)}</div>'


def _count(role: str, value: int, label: str = "") -> str:
    return f'<span data-count="{role}" data-final="{int(value)}">{int(value)}</span>{label}'


def post_mock(cr: Dict[str, Any], m: Dict[str, Any]) -> str:
    p = cr.get("platform", "facebook")
    page = cr.get("page") or "Brand"
    reactions = m.get("reactions") or {}
    n_react = sum(v for k, v in reactions.items() if k != "downvote")
    comments = m.get("comments_list") or []
    text = _e(_t(cr.get("text"), 420)).replace("\n", "<br>")
    head = _e(cr.get("headline"))
    cta = _e(cr.get("cta") or "Learn more")
    if p == "instagram":
        return (f'<div class="pm pm-ig"><div class="pm-h">{_avatar(page, "ring")}<div><b>{_e(page)}</b>'
                f'<div class="pm-muted">Sponsored</div></div><span class="pm-dots">···</span></div>'
                f'{_media(cr)}<div class="pm-igcta"><span>{cta}</span><span>›</span></div>'
                f'<div class="pm-igicons"><span>♡</span><span>💬</span><span>➤</span><span class="r">🔖</span></div>'
                f'<div class="pm-igl">{_count("react", n_react, " likes")}</div>'
                f'<div class="pm-igcap"><b>{_e(page)}</b> {text}</div>'
                f'<div class="pm-muted pm-pad">View all {_count("comment", m.get("comments", 0), " comments")}</div>'
                f'{_comments_html(comments, "ig")}</div>')
    if p == "reddit":
        up, down = reactions.get("upvote", 0), reactions.get("downvote", 0)
        return (f'<div class="pm pm-rd"><div class="pm-rdvote"><span>▲</span>'
                f'<b data-count="score" data-final="{up - down}">{up - down}</b><span>▼</span></div><div class="pm-rdbody">'
                f'<div class="pm-muted">u/{_e(page.lstrip("u/"))} · <span class="pm-promo">Promoted</span></div>'
                f'<div class="pm-rdt">{head or _e(_t(cr.get("text"), 120))}</div>'
                f'<div class="pm-rdtext">{text if head else ""}</div>{_media(cr)}'
                f'<div class="pm-rdbtn">{cta}</div>'
                f'<div class="pm-muted pm-pad">💬 {_count("comment", m.get("comments", 0), " comments")} · Share</div>'
                f'{_comments_html(comments, "reddit")}</div></div>')
    if p == "tiktok":
        return (f'<div class="pm pm-tt"><div class="pm-ttstage">{_media(cr, tall=True)}<div class="pm-ttrail">'
                f'<span>♥<small>{_count("react", n_react)}</small></span><span>💬<small>{_count("comment", m.get("comments", 0))}</small></span>'
                f'<span>🔖<small>{_count("save", m.get("saves", 0))}</small></span><span>➦<small>{_count("share", m.get("shares", 0))}</small></span></div>'
                f'<div class="pm-ttcap"><b>@{_e(page.replace(" ", "").lower())}</b><div>{_e(_t(cr.get("text"), 150))}</div>'
                f'<div class="pm-ttsp">Sponsored</div><div class="pm-ttbtn">{cta}</div></div></div>'
                f'{_comments_html(comments, "ig", 3)}</div>')
    if p == "x":
        return (f'<div class="pm pm-x"><div class="pm-h">{_avatar(page)}<div><b>{_e(page)}</b> '
                f'<span class="pm-muted">@{_e(page.replace(" ", "").lower())} · Ad</span></div></div>'
                f'<div class="pm-pad">{text}</div>{_media(cr)}'
                f'<div class="pm-xact"><span>💬 {_count("comment", m.get("comments", 0))}</span><span>🔁 {_count("share", m.get("shares", 0))}</span>'
                f'<span>♡ {_count("react", n_react)}</span></div>{_comments_html(comments, "fb", 3)}</div>')
    # facebook + linkedin share the classic card layout
    tag = "Promoted" if p == "linkedin" else "Sponsored · 🌐"
    emojis = "".join(REACTION_EMOJI.get(k, "") for k in list(reactions)[:3] if k in REACTION_EMOJI)
    return (f'<div class="pm pm-fb{" pm-li" if p == "linkedin" else ""}"><div class="pm-h">{_avatar(page)}<div><b>{_e(page)}</b>'
            f'<div class="pm-muted">{tag}</div></div><span class="pm-dots">···</span></div>'
            f'<div class="pm-pad">{text}</div>{_media(cr)}'
            f'<div class="pm-link"><div><div class="pm-muted small">{_e((cr.get("link") or page).replace("https://", "").split("/")[0].upper())}</div>'
            f'<b>{head or _e(_t(cr.get("text"), 60))}</b></div><span class="pm-btn">{cta}</span></div>'
            f'<div class="pm-stats"><span>{emojis} {_count("react", n_react)}</span>'
            f'<span>{_count("comment", m.get("comments", 0), " comments")} · {_count("share", m.get("shares", 0), " shares")}</span></div>'
            f'<div class="pm-actions"><span>Like</span><span>Comment</span><span>Share</span></div>'
            f'{_comments_html(comments, "fb")}</div>')


# --------------------------------------------------------------------------
# Feed test section
# --------------------------------------------------------------------------

def _range_txt(sp: Optional[Dict[str, Any]], n_seeds: int, digits: int = 1) -> str:
    """'2.1-3.4% across 3 seeds' from a multi-seed spread, or empty."""
    if not sp or n_seeds < 2:
        return ""
    return f'{sp["min"]:.{digits}f}–{sp["max"]:.{digits}f}% across {n_seeds} seeds'


def _metric_rows(m: Dict[str, Any], base: Optional[Dict[str, Any]], spread: Optional[Dict[str, Any]] = None,
                 n_seeds: int = 1) -> str:
    # pooled seeds repeat the same people, so margins use the per-seed sample size
    n = (m.get("impressions") or 0) // max(n_seeds, 1)
    sp = spread or {}

    def hint(key: str, default: str) -> str:
        r = _range_txt(sp.get(key), n_seeds)
        return f"{r}; {default}" if r and default else r or default
    rows = [
        ("Noticed the ad", pct_ci(m.get("noticed"), n), "caught their eye at all while scrolling") if m.get("noticed") is not None else None,
        ("Thumb-stop", pct_ci(m.get("thumb_stop"), n), hint("thumb_stop", f'organic posts: {base.get("thumb_stop"):.0f}%' if base and base.get("thumb_stop") is not None else "")),
        ("Avg time when stopped", f'{m["avg_dwell"]}s' if m.get("avg_dwell") is not None else "–", ""),
        ("CTR", pct_ci(m.get("ctr"), n), f'{m.get("clicks", 0)} clicks'),
        ("Expected CTR", f'{m["expected_ctr"]:.1f}%', hint("expected_ctr", "average of each person's stated click chance")) if m.get("expected_ctr") is not None else None,
        ("Engagement rate", pct_ci(m.get("engagement_rate"), n), hint("engagement_rate", "reactions, comments, shares, saves")),
        ("Comments / shares", f'{m.get("comments", 0)} / {m.get("shares", 0)}', ""),
        ("Hid the ad", pct_ci(m.get("hide_rate"), n), ""),
    ]
    return "".join(f'<tr><td>{_e(k)}</td><td class="num"><b>{_e(v)}</b></td><td class="muted small">{_e(h)}</td></tr>'
                   for k, v, h in (r for r in rows if r))


def _seeds_html(ft: Dict[str, Any], ranked: List[str], labels: List[str]) -> str:
    """Per creative: mean and min-max range across seeds, and how often it ranked first."""
    ms = ft.get("multi_seed") or {}
    spread, n = ms.get("spread") or {}, ms.get("n") or 0
    if n < 2 or not spread:
        return ""
    wins = ms.get("winner_counts") or {}

    def cell(sp):
        return "–" if not sp else f'{sp["mean"]:.1f}% ({sp["min"]:.1f}–{sp["max"]:.1f})'
    body = "".join(f'<tr><td>{_e(lbl)}</td>'
                   + "".join(f'<td class="num">{_e(cell((spread.get(cid) or {}).get(k)))}</td>'
                             for k in ("expected_ctr", "thumb_stop", "engagement_rate"))
                   + f'<td class="num">{wins.get(cid, 0)} of {n}</td></tr>' for cid, lbl in zip(ranked, labels))
    u = ms.get("usage") or {}
    cost = (f' Cost of all {n} runs: {u.get("calls", 0):,} Claude calls, {u.get("input_tokens", 0):,} input and '
            f'{u.get("output_tokens", 0):,} output tokens.') if u.get("calls") else ""
    agree = ms.get("winner_agreement")
    verdict = ("The winner is stable across seeds." if agree is not None and agree >= 80 else
               "The winner changes between seeds: treat the ranking as a tie and test both for real." if agree is not None
               else "")
    return (f'<div class="card"><h3>Across {n} seeds</h3><p class="muted small">The same test repeated with different '
            f'random seeds (who sees which ad, feed order, attention, habits). Mean and min–max range per creative. '
            f'{_e(verdict)}{_e(cost)}</p><div class="tbl"><table><thead><tr><th>Creative</th><th class="num">Expected CTR</th>'
            f'<th class="num">Thumb-stop</th><th class="num">Engagement</th><th class="num">Ranked first</th></tr></thead>'
            f'<tbody>{body}</tbody></table></div></div>')


def _landing_html(lf: Optional[Dict[str, Any]]) -> str:
    if not lf:
        return ""
    steps = [("Clicked", lf["clicks"]), ("Page loaded", lf["page_loaded"]), ("Started form", lf["form_started"]),
             ("Converted", lf["converted"])]
    top = max(lf["clicks"], 1)
    bars = "".join(f'<div class="lf-row"><span>{_e(k)}</span><span class="lf-track"><span class="lf-bar" '
                   f'style="width:{100 * v / top:.0f}%"></span></span><b>{v}</b></div>' for k, v in steps)
    reasons = "".join(f'<li>{_e(r["reason"])} <span class="muted">×{r["count"]}</span></li>' for r in lf.get("drop_reasons") or [])
    nets = ", ".join(f"{k} {v}" for k, v in (lf.get("networks") or {}).items())
    return (f'<div class="lf"><h4>After the click</h4>{bars}'
            f'<p class="muted small">Networks of clickers: {_e(nets)}. Page loaded for {lf.get("load_rate") or 0:.0f}% of clicks.</p>'
            + (f'<ul class="small">{reasons}</ul>' if reasons else "") + "</div>")


def _projection_html(pr: Optional[Dict[str, Any]]) -> str:
    if not pr:
        return ""
    cur = pr.get("currency") or ""
    items = [("Budget", _money(pr["budget"], cur)), ("Impressions", f'{pr["impressions"]:,}'),
             ("Clicks", f'{pr["clicks"]:,}'), ("CPC", _money(pr.get("cpc"), cur)),
             ("Conversions", "–" if pr.get("conversions") is None else f'{pr["conversions"]:g}'),
             ("Cost per lead", _money(pr.get("cpl") or pr.get("cost_per_conversion"), cur))]
    if pr.get("cac") is not None:
        items.append(("CAC", _money(pr["cac"], cur)))
    if pr.get("roas") is not None:
        items += [("ROAS", f'{pr["roas"]:.2f}x'), ("ROI", f'{pr["roi_pct"]:+.0f}%'), ("Break-even CPL", _money(pr.get("break_even_cpl"), cur))]
    if pr.get("payback_months") is not None:
        items.append(("Payback", f'{pr["payback_months"]} months'))
    cells = "".join(f'<div><div class="v">{_e(v)}</div><div class="k">{_e(k)}</div></div>' for k, v in items)
    note = f'CTR {pr["ctr_used"]}%' + (" calibrated to your real platform CTR" if pr.get("calibrated") else " as simulated (not calibrated)")
    if pr.get("too_few_clicks") is not None:
        note += (f'. Only {pr["too_few_clicks"]} simulated click(s): too few to estimate conversions, '
                 'so add personas or exposures')
    return f'<div class="proj"><h4>If you spend {_e(_money(pr["budget"], cur))} at CPM {_e(pr["cpm"])}</h4><div class="proj-g">{cells}</div><p class="muted small">{_e(note)}.</p></div>'


def feed_section(ft: Dict[str, Any], chart) -> Optional[Tuple[str, str, str]]:
    summary = (ft or {}).get("summary") or {}
    per = summary.get("per_creative") or {}
    if not per:
        return None
    creatives = {c["id"]: c for c in ft.get("creatives") or []}
    base = summary.get("organic_baseline") or {}
    ranked = [cid for cid in summary.get("ranked") or per if cid in per]
    labels = [f'{cid} · {PLATFORM_LABEL.get(creatives.get(cid, {}).get("platform"), "")}' for cid in ranked]
    charts = ""
    if len(ranked) > 1:
        charts = ('<div class="grid2">'
                  + '<div class="card"><h3>CTR by creative</h3>' + chart("bars", {"cats": labels, "values": [per[c]["ctr"] or 0 for c in ranked],
                                                                                    "unit": "%", "highlight": 0}, 40 + 34 * len(ranked), "CTR by creative") + "</div>"
                  + '<div class="card"><h3>Thumb-stop rate by creative</h3>' + chart("bars", {"cats": labels, "values": [per[c]["thumb_stop"] or 0 for c in ranked],
                                                                                              "unit": "%", "highlight": 0}, 40 + 34 * len(ranked), "Thumb-stop by creative") + "</div></div>")
    ms = ft.get("multi_seed") or {}
    n_seeds = ms.get("n") or 1
    seeds_card = _seeds_html(ft, ranked, labels)
    cards = []
    for i, cid in enumerate(ranked):
        cr, m = creatives.get(cid, {"id": cid, "platform": "facebook", "text": cid}), per[cid]
        n = m.get("impressions") or 0
        events = json.dumps(m.get("events") or [], ensure_ascii=False)
        seg_rows = "".join(f'<tr><td>{_e(s["key"])}{low_n_pill(s["impressions"], 5)}</td><td class="num">{s["impressions"]}</td>'
                           f'<td class="num">{pct_ci(s["thumb_stop"], s["impressions"])}</td><td class="num">{pct_ci(s["ctr"], s["impressions"])}</td>'
                           f'<td class="num">{pct_ci(s["engagement_rate"], s["impressions"])}</td></tr>' for s in m.get("by_segment") or [])
        thoughts = "".join(f'<li><span class="pill">{_e(t["segment"])}</span> {_e(_t(t["text"], 140))}</li>' for t in (m.get("thoughts") or [])[:6])
        pe = m.get("proof_effect")
        proof = (f'<p class="muted small">Social proof: engagement {pe["first_wave_engagement"] or 0:.0f}% for the first viewers vs '
                 f'{pe["later_engagement"] or 0:.0f}% once earlier reactions and comments were visible.</p>') if pe else ""
        cards.append(
            f'<div class="ftc{" winner" if i == 0 and len(ranked) > 1 else ""}"><div class="ftc-l">'
            f'<div class="ftc-top"><span class="pill {"accent" if i == 0 and len(ranked) > 1 else ""}">{_e(PLATFORM_LABEL.get(cr.get("platform"), ""))} · {_e(cid)}'
            f'{" · best" if i == 0 and len(ranked) > 1 else ""}</span>'
            f'<button type="button" class="replay" data-replay>▶ Replay the scroll</button></div>'
            f'<div class="pm-wrap" data-events="{_e(events)}">{post_mock(cr, m)}</div>'
            f'<ol class="scroll-log" data-role="log" aria-live="polite"></ol></div>'
            f'<div class="ftc-r"><h3>{_e(cr.get("name") or cid)}{low_n_pill(n // n_seeds)}</h3>'
            f'<p class="muted small">Shown to {n // n_seeds} simulated people in their own feed among organic posts'
            + (f', in each of {n_seeds} seeded runs ({n} impressions).' if n_seeds > 1 else '.') + '</p>'
            f'<table class="kv-t"><tbody>{_metric_rows(m, base.get(cr.get("platform")), (ms.get("spread") or {}).get(cid), n_seeds)}</tbody></table>'
            f'{_landing_html(m.get("landing"))}{_projection_html(m.get("projection"))}{proof}'
            + (f'<details class="tv"><summary>By audience</summary><div class="tbl"><table><thead><tr><th>Audience</th><th class="num">Saw it</th>'
               f'<th class="num">Thumb-stop</th><th class="num">CTR</th><th class="num">Engagement</th></tr></thead><tbody>{seg_rows}</tbody></table></div></details>'
               if seg_rows else "")
            + (f'<details class="tv"><summary>What went through their heads</summary><ul class="small">{thoughts}</ul></details>' if thoughts else "")
            + "</div></div>")
    head = (f'<h2>Feed test</h2><p class="muted small">{ft.get("personas_tested", 0)} simulated people scrolled realistic feeds '
            f'({ft.get("feeds", 0)} feeds, {ft.get("waves", 1)} waves; later waves saw earlier reactions'
            + (f'; repeated with {n_seeds} seeds' if n_seeds > 1 else '') + '). ± values are 95% '
            'margins of error; small samples are flagged.'
            + ('' if n_seeds > 1 else ' One seed only: run with --seeds 3 to see how much the result moves.') + '</p>')
    return ("feedtest", "Feed test", head + seeds_card + charts + '<div class="ftcs">' + "".join(cards) + "</div>")


# --------------------------------------------------------------------------
# Analyst panel + backtest
# --------------------------------------------------------------------------

def panel_section(p: Dict[str, Any]) -> Optional[Tuple[str, str, str]]:
    if not p or not p.get("analysts"):
        return None
    c = p.get("consensus") or {}
    aud, msg = c.get("best_audience") or {}, c.get("best_message") or {}
    head = (f'<div class="panel"><div class="eyebrow">Independent analyst panel · {c.get("analysts_ok", 0)} analysts, each working alone</div>'
            f'<div class="headline">Consensus is {_e(c.get("consensus"))}.'
            + (f' Best audience: {_e(aud.get("winner"))} ({aud.get("agreement")}% agree).' if aud.get("winner") else "")
            + (f' Best message: {_e(_t(msg.get("winner"), 80))} ({msg.get("agreement")}% agree).' if msg.get("winner") else "")
            + f'</div><ul class="verdicts"><li>Average sentiment {c.get("sentiment_mean")} (spread ±{c.get("sentiment_spread")}), '
            f'purchase-intent signal {c.get("intent_mean")}/10, analyst confidence {c.get("confidence_mean")}/10.</li></ul></div>')
    themes = "".join(f'<tr><td>{_e(t["theme"])}</td><td class="num">{t["analysts"]}/{c.get("analysts_ok", 0)}</td>'
                     f'<td class="num">{t["weight"]}</td><td class="small">{_e(_t("; ".join(t.get("evidence") or []), 200))}</td></tr>'
                     for t in c.get("themes") or [])
    cards = []
    for a in p["analysts"]:
        r = a.get("result")
        if not r:
            cards.append(f'<div class="play"><div class="play-h"><strong>{_e(a["id"])}</strong><span class="pill">{_e(a["lens"])}</span></div>'
                         f'<p class="muted">Did not return a usable analysis.</p></div>')
            continue
        cards.append(f'<div class="play"><div class="play-h"><strong>{_e(a["id"])}</strong><span class="pill">{_e(a["lens"])}</span></div>'
                     f'<p style="margin:0 0 8px"><b>{_e(r["headline"])}</b></p><dl>'
                     f'<dt>Recommend</dt><dd>{_e(r["recommendation"])}</dd>'
                     f'<dt>Audience</dt><dd>{_e(r["best_audience"])}</dd><dt>Message</dt><dd>{_e(_t(r["best_message"], 120))}</dd>'
                     + (f'<dt>Objections</dt><dd>{_e("; ".join(r["objections"][:3]))}</dd>' if r["objections"] else "")
                     + (f'<dt>Risks</dt><dd>{_e("; ".join(r["risks"][:2]))}</dd>' if r["risks"] else "")
                     + f'<dt>Confidence</dt><dd>{_e(r["confidence"])}/10 · {_e(_t(r["evidence_gaps"], 140))}</dd></dl></div>')
    return ("analysts", "Analysts", f'<h2>Independent analyst panel</h2>{head}'
            + (f'<div class="card" style="margin-top:14px"><h3>Themes the analysts found</h3><div class="tbl"><table><thead><tr>'
               f'<th>Theme</th><th class="num">Analysts</th><th class="num">Weight</th><th>Evidence</th></tr></thead><tbody>{themes}</tbody></table></div></div>'
               if themes else "")
            + f'<div class="plays" style="margin-top:14px">{"".join(cards)}</div>')


def backtest_section(b: Dict[str, Any], chart) -> Optional[Tuple[str, str, str]]:
    if not b or not b.get("pairs"):
        return None
    if b.get("note"):
        return ("backtest", "Backtest", f'<h2>Backtest against real ads</h2><div class="callout">{_e(b["note"])}</div>')
    rows = "".join(f'<tr><td>{_e(p["creative"])}</td><td>{_e(p["real_ad"])}</td><td class="num">{p["sim_ctr"]}%</td>'
                   f'<td class="num">{p["real_ctr"]}%</td><td class="num">{p["real_clicks"]}</td><td class="num">{p["real_conversions"]}</td></tr>'
                   for p in b["pairs"])
    sc = chart("scatter", {"points": [[p["real_ctr"], p["sim_ctr"], p["creative"]] for p in b["pairs"]]}, 300,
               "Simulated CTR against real CTR per creative")
    verdict = ("The simulation picked the same winner as the real ads." if b.get("top1_match")
               else f'The simulation picked {b.get("top_sim")}, but the real winner was {b.get("top_real")}.')
    warn = "".join(f"<li>{_e(w)}</li>" for w in b.get("warnings") or [])
    return ("backtest", "Backtest", '<h2>Backtest against real ads</h2><div class="grid2"><div class="card">'
            f'<div class="kpis"><div class="kpi hl"><div class="v">{_e(b.get("spearman"))}</div><div class="k">Rank correlation (Spearman)</div></div>'
            f'<div class="kpi"><div class="v">{_e(b.get("kendall_tau"))}</div><div class="k">Kendall tau</div></div>'
            f'<div class="kpi"><div class="v">{"Yes" if b.get("top1_match") else "No"}</div><div class="k">Same winner</div></div>'
            f'<div class="kpi"><div class="v">{_e(b.get("ctr_calibration"))}×</div><div class="k">Real ÷ simulated CTR</div></div></div>'
            f'<p>{_e(verdict)}</p>' + (f'<ul class="small">{warn}</ul>' if warn else "") + '</div>'
            f'<div class="card"><h3>Simulated vs real CTR</h3>{sc}</div></div>'
            f'<div class="card" style="margin-top:14px"><div class="tbl"><table><thead><tr><th>Creative</th><th>Real ad</th><th class="num">Simulated CTR</th>'
            f'<th class="num">Real CTR</th><th class="num">Real clicks</th><th class="num">Real conversions</th></tr></thead><tbody>{rows}</tbody></table></div></div>')


# --------------------------------------------------------------------------
# Downloads
# --------------------------------------------------------------------------

def _csv(rows: List[Dict[str, Any]], cols: List[str]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v) for k, v in r.items()})
    return buf.getvalue()


def export_files(bundle: Dict[str, Any], mk: Dict[str, Any], report_md: str) -> Dict[str, str]:
    """name -> text content of every downloadable report file."""
    files: Dict[str, str] = {}
    if report_md:
        files["report.md"] = report_md
    survey = bundle.get("survey") or {}
    srows = []
    meta = {int(r["agent_id"]): r for r in ((bundle.get("config") or {}).get("persona_index") or []) if r.get("agent_id") is not None}
    for r in survey.get("responses") or []:
        a = r.get("answer") or {}
        m = meta.get(int(r.get("agent_id", -1)), {})
        srows.append({"agent_id": r.get("agent_id"), "name": r.get("name"), "segment": m.get("segment"), "country": m.get("country"),
                      "age": m.get("age"), "gender": m.get("gender"), "assigned_message": r.get("assigned_message"),
                      **{k: v for k, v in a.items() if k not in ("texts", "ssr")},
                      **{f"{sc}_text": t for sc, t in (a.get("texts") or {}).items()},
                      **{f"{sc}_ssr_mean": (v or {}).get("mean") for sc, v in (a.get("ssr") or {}).items()}})
    if srows:
        cols = ["agent_id", "name", "segment", "country", "age", "gender", "assigned_message", "interest", "trust", "would_click",
                "would_convert", "recommend", "best_message", "message_reaction", "objection_type", "main_objection",
                "would_change_mind", "quote", "price_too_cheap", "price_cheap", "price_expensive", "price_too_expensive"]
        ssr_cols = [f"{sc}_{x}" for sc in ("purchase", "interest", "trust", "recommend") for x in ("text", "ssr_mean")]
        cols += [c for c in ssr_cols if any(c in r for r in srows)]
        files["survey_answers.csv"] = _csv(srows, cols)
    if mk.get("by_segment"):
        seg_rows = [{**r, **{f"{sc}_{x}": ((r.get("ssr") or {}).get(sc) or {}).get(x)
                             for sc in ("purchase", "interest", "trust", "recommend") for x in ("mean", "sd")}}
                    for r in mk["by_segment"]]
        files["segments.csv"] = _csv(seg_rows, ["key", "n", "convert_yes", "convert_maybe", "convert_no", "click_yes",
                                                "interest", "trust", "nps", "top_objection", "top_message"]
                                     + ([f"{sc}_{x}" for sc in ("purchase", "interest", "trust", "recommend") for x in ("mean", "sd")]
                                        if any(r.get("ssr") for r in mk["by_segment"]) else []))
    ft = bundle.get("feed_test") or {}
    if ft.get("sessions"):
        rows = [{"agent_id": s["agent_id"], "name": s["name"], "segment": s["segment"], "country": s["country"],
                 "platform": s["platform"], "creative_id": s["creative_id"], "wave": s.get("wave"), "hour": s.get("hour"),
                 **{f"ad_{k}": v for k, v in s["ad"].items()},
                 **{f"landing_{k}": v for k, v in (s.get("landing") or {}).items()}} for s in ft["sessions"]]
        cols = list(dict.fromkeys(k for r in rows for k in r))
        files["feed_test_sessions.csv"] = _csv(rows, cols)
        per = (ft.get("summary") or {}).get("per_creative") or {}
        crows = [{"creative_id": cid, **{k: v for k, v in m.items() if not isinstance(v, (list, dict))},
                  **{f"proj_{k}": v for k, v in (m.get("projection") or {}).items()}} for cid, m in per.items()]
        files["feed_test_creatives.csv"] = _csv(crows, list(dict.fromkeys(k for r in crows for k in r)))
    if bundle.get("analyst_panel"):
        files["analyst_panel.json"] = json.dumps(bundle["analyst_panel"], ensure_ascii=False, indent=2)
    return files


def downloads_section(files: Dict[str, str]) -> Tuple[str, str, str]:
    labels = {"report.md": "Analyst report (Markdown)", "survey_answers.csv": "Every survey answer (CSV)",
              "segments.csv": "Results by audience (CSV)", "feed_test_sessions.csv": "Every feed session (CSV)",
              "feed_test_creatives.csv": "Creative metrics + ROI (CSV)", "analyst_panel.json": "Analyst panel (JSON)",
              "summary.json": "All key numbers (JSON)"}
    btns = ['<button type="button" data-dl="__page__">This dashboard (HTML)</button>',
            '<button type="button" onclick="window.print()">Print or save as PDF</button>']
    btns += [f'<button type="button" data-dl="{_e(name)}">{_e(labels.get(name, name))}</button>' for name in files]
    payload = json.dumps(files, ensure_ascii=False).replace("</", "<\\/")
    return ("downloads", "Downloads", '<h2>Download the reports</h2><div class="card"><p class="muted small">Everything here '
            'is generated from this run and stays on your machine. The same files are saved next to dashboard.html.</p>'
            f'<div class="dl">{"".join(btns)}</div></div>'
            f'<script type="application/json" id="mm-files">{payload}</script>')


FEED_CSS = """
.ftcs{display:grid;gap:16px}
.ftc{display:grid;grid-template-columns:minmax(0,420px) minmax(0,1fr);gap:18px;background:var(--surface);border-radius:24px;padding:18px}
.ftc.winner{box-shadow:0 0 0 2px var(--mm-accent) inset}
@media (max-width:900px){.ftc{grid-template-columns:1fr}}
.ftc-top{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:10px;flex-wrap:wrap}
.replay{font:inherit;font-size:.82rem;font-weight:500;border-radius:999px;border:0;background:var(--text);color:var(--surface);padding:6px 14px;cursor:pointer}
.ftc-r h3{margin:0 0 4px;font-weight:500}
.kv-t{width:100%;font-size:.9rem;margin:8px 0}.kv-t td{padding:5px 6px;border-bottom:1px solid var(--grid)}
.scroll-log{list-style:none;padding:0;margin:10px 0 0;max-height:220px;overflow:auto;font-size:.8rem;display:grid;gap:4px}
.scroll-log li{background:var(--surface-2);border-radius:10px;padding:5px 9px}
.scroll-log li.act{border-left:3px solid var(--mm-accent)}
.lf{margin-top:12px}.lf h4,.proj h4{margin:0 0 6px;font-size:.92rem;font-weight:500}
.lf-row{display:grid;grid-template-columns:110px 1fr 40px;gap:8px;align-items:center;font-size:.85rem;margin:3px 0}
.lf-track{background:var(--surface-2);border-radius:6px;height:12px;overflow:hidden}.lf-bar{display:block;height:100%;background:var(--mm-ink-bar);border-radius:6px}
.proj{margin-top:12px;background:var(--surface-2);border-radius:18px;padding:12px 14px}
.proj-g{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:8px}
.proj-g .v{font-size:1.15rem;font-weight:500}.proj-g .k{font-size:.75rem;color:var(--muted)}
.dl{display:flex;flex-wrap:wrap;gap:8px}
.dl button{font:inherit;font-size:.86rem;font-weight:500;border:1px solid var(--border);background:var(--surface);color:var(--text);border-radius:999px;padding:8px 16px;cursor:pointer}
.dl button:first-child{background:var(--text);color:var(--surface);border-color:var(--text)}
/* platform mocks: each app keeps its own light look, like a screenshot */
.pm{background:#fff;color:#050505;border:1px solid #dddfe2;border-radius:12px;overflow:hidden;font:14px/1.4 -apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;max-width:420px}
.pm b{font-weight:600}.pm-muted{color:#65676b;font-size:.8rem}.pm-pad{padding:6px 12px}
.pm-h{display:flex;gap:8px;align-items:center;padding:10px 12px}.pm-h>div{flex:1;min-width:0}.pm-dots{color:#65676b}
.pm-av{width:36px;height:36px;border-radius:50%;background:#e4e6eb;display:inline-grid;place-items:center;font-weight:700;color:#050505;flex:0 0 36px}
.pm-av.ring{box-shadow:0 0 0 2px #fff,0 0 0 4px #d62976}
.pm-media{background:#e4e6eb;aspect-ratio:1.91/1;display:grid;place-items:center;overflow:hidden;position:relative}
.pm-media img{width:100%;height:100%;object-fit:cover}
.pm-media.ph{background:linear-gradient(135deg,#1f2937,#4b5563);color:#fff;padding:18px;text-align:center;font-size:.92rem}
.pm-media.tall{aspect-ratio:9/16;max-height:520px}
.pm-fmt{position:absolute;top:8px;left:8px;font-size:.7rem;background:rgba(0,0,0,.5);color:#fff;border-radius:999px;padding:2px 8px}
.pm-link{display:flex;justify-content:space-between;align-items:center;gap:10px;background:#f0f2f5;padding:10px 12px}
.pm-btn{background:#e4e6eb;border-radius:6px;padding:7px 12px;font-weight:600;white-space:nowrap}
.pm-stats{display:flex;justify-content:space-between;padding:8px 12px;color:#65676b;font-size:.85rem;border-bottom:1px solid #ced0d4}
.pm-actions{display:flex;justify-content:space-around;padding:6px 0;color:#65676b;font-weight:600;font-size:.88rem;border-bottom:1px solid #ced0d4}
.pm-comments{padding:6px 12px 10px;display:grid;gap:6px}
.pm-c{display:flex;gap:6px;align-items:flex-start}.pm-c .pm-av{width:28px;height:28px;flex-basis:28px;font-size:.75rem}
.pm-bubble{background:#f0f2f5;border-radius:16px;padding:6px 10px;font-size:.85rem}
.pm-ig .pm-igcta{display:flex;justify-content:space-between;padding:10px 12px;font-weight:600;color:#0095f6;border-bottom:1px solid #efefef}
.pm-igicons{display:flex;gap:14px;padding:8px 12px 2px;font-size:1.2rem}.pm-igicons .r{margin-left:auto}
.pm-igl{padding:0 12px;font-weight:600}.pm-igcap{padding:4px 12px}.pm-igc{font-size:.86rem}
.pm-rd{display:flex;background:#fff}.pm-rdvote{background:#f6f7f8;padding:8px 6px;display:flex;flex-direction:column;align-items:center;gap:2px;color:#878a8c;min-width:44px}
.pm-rdbody{flex:1;min-width:0;padding:8px 10px}.pm-rdt{font-weight:600;font-size:1.02rem;margin:4px 0}.pm-rdtext{font-size:.9rem;margin-bottom:6px}
.pm-promo{color:#0079d3;font-weight:600}.pm-rdbtn{display:inline-block;margin:8px 0;border:1px solid #0079d3;color:#0079d3;border-radius:999px;padding:4px 14px;font-weight:700;font-size:.82rem}
.pm-rc{border-left:2px solid #edeff1;padding:4px 0 4px 10px;font-size:.86rem}.pm-rc-h{color:#7c7c7c;font-size:.76rem}
.pm-tt{background:#000;color:#fff;border:0}.pm-ttstage{position:relative}
.pm-tt .pm-media.tall{aspect-ratio:auto;height:440px;max-height:none;width:100%}
.pm-tt .pm-media.ph{padding:18px 64px 120px 18px}.pm-tt .pm-media.ph{background:linear-gradient(160deg,#111,#3a1c5c 60%,#7a1f4b)}
.pm-ttrail{position:absolute;right:8px;bottom:110px;display:grid;gap:12px;text-align:center;font-size:1.3rem}
.pm-ttrail small{display:block;font-size:.7rem}
.pm-ttcap{position:absolute;left:10px;right:60px;bottom:12px;font-size:.85rem;text-shadow:0 1px 2px rgba(0,0,0,.6)}
.pm-ttsp{font-size:.7rem;opacity:.8}.pm-ttbtn{background:#fe2c55;border-radius:4px;padding:6px 10px;font-weight:700;text-align:center;margin-top:6px}
.pm-tt .pm-comments{background:#fff;color:#111}
.pm-x .pm-xact{display:flex;justify-content:space-between;padding:8px 14px;color:#536471;font-size:.85rem}
.pm-li .pm-btn{border:1px solid #0a66c2;color:#0a66c2;background:#fff;border-radius:999px}
@media print{.replay,.dl,nav.toc{display:none}.ftc{break-inside:avoid}}
"""

FEED_JS = r"""
(function(){
function el(t,c,h){var e=document.createElement(t);if(c)e.className=c;if(h!=null)e.textContent=h;return e;}
function describe(ev){var a=[];if(!ev.stopped)return ev.name+' ('+ev.segment+') scrolled past in '+(ev.dwell||0.5)+'s';
 a.push('stopped '+ev.dwell+'s');if(ev.reaction&&ev.reaction!=='none')a.push(ev.reaction);if(ev.comment)a.push('commented “'+ev.comment.slice(0,90)+'”');
 if(ev.share&&ev.share!=='none')a.push(ev.share==='send'?'sent it to someone':'shared it');if(ev.save)a.push('saved it');
 if(ev.hide)a.push('hid the ad');if(ev.click)a.push('clicked');
 if(ev.landing){var L=ev.landing;a.push(L.loaded?('page loaded in '+L.load_seconds+'s on '+L.network+(L.completed?' → converted':(L.drop_reason?' → left: '+L.drop_reason:' → left'))):('left: page took '+L.load_seconds+'s on '+L.network));}
 return ev.name+' ('+ev.segment+'): '+a.join(' · ');}
document.querySelectorAll('[data-replay]').forEach(function(btn){
 btn.addEventListener('click',function(){var card=btn.closest('.ftc');var wrap=card.querySelector('[data-events]');var log=card.querySelector('[data-role=log]');
  var evs;try{evs=JSON.parse(wrap.getAttribute('data-events'));}catch(e){return;}
  if(btn.__t){clearInterval(btn.__t);}
  var counters={};wrap.querySelectorAll('[data-count]').forEach(function(c){counters[c.getAttribute('data-count')]=counters[c.getAttribute('data-count')]||[];counters[c.getAttribute('data-count')].push(c);c.textContent='0';});
  var cbox=wrap.querySelector('[data-role=comments]');var saved=cbox?cbox.innerHTML:'';if(cbox)cbox.innerHTML='';log.innerHTML='';
  var tot={react:0,comment:0,share:0,save:0,score:0},i=0;btn.textContent='■ Playing…';
  function bump(k,d){tot[k]+=d;(counters[k]||[]).forEach(function(c){c.textContent=tot[k];});}
  btn.__t=setInterval(function(){if(i>=evs.length){clearInterval(btn.__t);btn.__t=null;btn.textContent='▶ Replay the scroll';if(cbox)cbox.innerHTML=saved;return;}
   var ev=evs[i++];var li=el('li',ev.stopped?'act':'',describe(ev));log.insertBefore(li,log.firstChild);
   if(ev.reaction&&ev.reaction!=='none'){if(ev.reaction==='upvote')bump('score',1);else if(ev.reaction==='downvote')bump('score',-1);else bump('react',1);}
   if(ev.comment){bump('comment',1);if(cbox){var d=el('div','pm-c');var b=el('div','pm-bubble');var n=el('b','',ev.name.split(' ')[0]);var t=el('div','',ev.comment);b.appendChild(n);b.appendChild(t);d.appendChild(b);cbox.insertBefore(d,cbox.firstChild);}}
   if(ev.share&&ev.share!=='none')bump('share',1);if(ev.save)bump('save',1);},420);});});
var files={};try{files=JSON.parse((document.getElementById('mm-files')||{}).textContent||'{}');}catch(e){}
function save(name,text,type){var b=new Blob([text],{type:type||'text/plain'});var a=document.createElement('a');a.href=URL.createObjectURL(b);a.download=name;document.body.appendChild(a);a.click();setTimeout(function(){URL.revokeObjectURL(a.href);a.remove();},500);}
document.querySelectorAll('[data-dl]').forEach(function(b){b.addEventListener('click',function(){var n=b.getAttribute('data-dl');
 if(n==='__page__'){save('market-mirror-dashboard.html','<!doctype html>\n'+document.documentElement.outerHTML,'text/html');return;}
 save(n,files[n]||'',n.endsWith('.csv')?'text/csv':n.endsWith('.json')?'application/json':'text/markdown');});});
})();
"""


# --------------------------------------------------------------------------
# Knowledge graph overlay: simulated people and communities, connected
# --------------------------------------------------------------------------

def augment_graph(graph: Dict[str, Any], config: Dict[str, Any], max_people: int = 120) -> Dict[str, Any]:
    """Add personas, segments, communities and countries to the graph so the audience is visibly connected:
    person -> MEMBER_OF -> community, person -> IN_SEGMENT -> segment, segment -> LIVES_IN -> country."""
    index = [r for r in (config or {}).get("persona_index") or [] if r.get("kind") in ("persona", "community")]
    if not index:
        return graph
    nodes = list(graph.get("nodes") or [])
    edges = list(graph.get("edges") or [])
    by_name = {str(n.get("name") or "").strip().lower(): n.get("uuid") for n in nodes}

    def node(key: str, name: str, label: str) -> str:
        found = by_name.get(name.strip().lower())
        if found:
            return found
        uid = f"mm_{key}"
        nodes.append({"uuid": uid, "name": name, "labels": ["Entity", label], "summary": "", "attributes": {}})
        by_name[name.strip().lower()] = uid
        return uid

    def edge(a: str, b: str, name: str, fact: str) -> None:
        edges.append({"uuid": f"mm_e{len(edges)}", "name": name, "fact": fact, "source_node_uuid": a,
                      "target_node_uuid": b})

    people = [r for r in index if r.get("kind") == "persona"][:max_people]
    for r in index:
        if r.get("kind") == "community":
            node(f"c{r['agent_id']}", r.get("name") or "community", "Community")
    for r in people:
        p = node(f"p{r['agent_id']}", r.get("name") or f"person {r['agent_id']}", "Persona")
        if r.get("segment"):
            seg = node("s_" + str(r["segment"]), str(r["segment"]), "Segment")
            edge(p, seg, "IN_SEGMENT", f"{r.get('name')} is in {r['segment']}")
            if r.get("country"):
                c = node("k_" + str(r["country"]), str(r["country"]), "Country")
                if not any(e["source_node_uuid"] == seg and e["target_node_uuid"] == c for e in edges):
                    edge(seg, c, "LIVES_IN", f"{r['segment']} live in {r['country']}")
        for cm in r.get("communities") or []:
            edge(p, node("c_" + cm, cm, "Community"), "MEMBER_OF", f"{r.get('name')} is a member of {cm}")
    return {**graph, "nodes": nodes, "edges": edges, "node_count": len(nodes), "edge_count": len(edges)}



# --------------------------------------------------------------------------
# Decision card: go / iterate / no-go from every signal we have
# --------------------------------------------------------------------------

def decision(bundle: Dict[str, Any], mk: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    signals: List[Dict[str, Any]] = []
    o = mk.get("overall") or {}
    pi = (o.get("ssr") or {}).get("purchase")
    if mk.get("has_survey") and pi:
        # free-text purchase intent mapped to a 1-5 scale (SSR): judge the mean, not the top-box share
        mean = pi["mean"]
        signals.append({"name": "Buyer survey", "vote": "go" if mean >= SSR_GO_MEAN else "iterate" if mean >= SSR_ITERATE_MEAN else "no-go",
                        "detail": f"purchase intent {mean:.1f}/5 ± {pi['sd']:.1f} from free-text answers "
                                  f"({o.get('convert_yes') or 0:.0f}% probably or definitely), n={pi['n']}",
                        "n": pi["n"]})
    elif mk.get("has_survey") and o.get("convert_yes") is not None:
        v = o["convert_yes"]
        score = v + 0.3 * (o.get("convert_maybe") or 0)          # a "maybe" is worth a fraction of a "yes"
        signals.append({"name": "Buyer survey", "vote": "go" if v >= 30 or score >= 40 else "iterate" if score >= 8 else "no-go",
                        "detail": f"{v:.0f}% would convert (+{o.get('convert_maybe') or 0:.0f}% maybe), n={mk.get('answered')}",
                        "n": mk.get("answered") or 0})
    ftj = bundle.get("feed_test") or {}
    ft = ftj.get("summary") or {}
    per, calib = ft.get("per_creative") or {}, ft.get("calibration") or {}
    if per:
        best_id = (ft.get("ranked") or list(per))[0]
        b = per[best_id]
        creatives = {c["id"]: c for c in ftj.get("creatives") or []}
        plat = creatives.get(best_id, {}).get("platform")
        ms = ftj.get("multi_seed") or {}
        n_seeds = ms.get("n") or 1
        sp = ((ms.get("spread") or {}).get(best_id) or {}).get("expected_ctr") if n_seeds > 1 else None
        exp = sp["mean"] if sp else b.get("expected_ctr")
        hide = b.get("hide_rate") or 0
        vote = "iterate"
        detail = f"best creative {best_id}: expected CTR {exp}%"
        if sp:
            detail += (f" (range {sp['min']}–{sp['max']}% across {n_seeds} seeds, ranked first in "
                       f"{ms.get('winner_agreement')}% of them)")
        detail += f", hides {hide:.0f}%"
        if calib.get(plat):
            vs = (exp or 0) * calib[plat]
            detail += f", about {vs:.1f}% after calibrating to your real CTR"
        if exp is not None:
            vote = "go" if exp >= 3 and hide < 15 else "no-go" if exp < 1 or hide >= 30 else "iterate"
            if sp and ((vote == "go" and sp["min"] < 3) or (vote == "no-go" and sp["max"] >= 3)):
                vote = "iterate"                                  # not robust across seeds
        lf = b.get("landing") or {}
        if lf.get("clicks"):
            detail += f"; page loaded for {lf.get('load_rate') or 0:.0f}% of clicks, {lf.get('converted', 0)} of {lf['clicks']} converted"
            if (lf.get("load_rate") or 0) < 60 and vote == "go":
                vote = "iterate"
        signals.append({"name": "Feed test", "vote": vote, "detail": detail,
                        "n": (b.get("impressions") or 0) // n_seeds})
    pc = (bundle.get("analyst_panel") or {}).get("consensus") or {}
    if (pc.get("verdict") or {}).get("winner"):
        v = pc["verdict"]
        signals.append({"name": "Analyst panel", "vote": v["winner"],
                        "detail": f"{v['agreement']}% of {pc.get('analysts_ok')} analysts; success chance {pc.get('success_probability')}%",
                        "n": pc.get("analysts_ok") or 0})
    if not signals:
        return None
    order = {"no-go": 0, "iterate": 1, "go": 2}
    votes = [s["vote"] for s in signals]
    final = min(votes, key=lambda v: order[v]) if "no-go" in votes and votes.count("no-go") * 2 >= len(votes) else \
        max(set(votes), key=lambda v: (votes.count(v), -order[v]))
    agree = votes.count(final) / len(votes)
    small = any(s["n"] < 30 for s in signals if s["name"] != "Analyst panel")
    confidence = "high" if agree == 1 and not small and len(signals) >= 2 else "medium" if agree >= 0.5 and not small else "low"
    why = {"go": "Signals support launching or scaling this, with the fixes below.",
           "iterate": "Promising, but fix the blockers and retest before spending at scale.",
           "no-go": "Do not scale this as is. Rethink the offer, audience or message."}[final]
    return {"decision": final, "confidence": confidence, "summary": why, "signals": signals,
            "fixes": [x["label"] for x in (mk.get("objections") or [])[:3]]}


def decision_section(d: Optional[Dict[str, Any]]) -> Optional[Tuple[str, str, str]]:
    if not d:
        return None
    color = {"go": "mint", "iterate": "accent", "no-go": "orchid"}[d["decision"]]
    rows = "".join(f'<li><span><span class="pill {"mint" if s["vote"] == "go" else "accent" if s["vote"] == "iterate" else "orchid"}">'
                   f'{_e(s["vote"])}</span> <b>{_e(s["name"])}</b>: {_e(s["detail"])}</span></li>' for s in d["signals"])
    fixes = "".join(f"<li>{_e(f)}</li>" for f in d.get("fixes") or [])
    return ("decision", "Decision", f'<div class="panel dec"><div class="eyebrow">Decision · {_e(d["confidence"])} confidence</div>'
            f'<div class="headline"><span class="pill {color}" style="font-size:1.1rem;padding:6px 14px;margin-right:10px">'
            f'{_e(d["decision"].upper())}</span>{_e(d["summary"])}</div><ul class="verdicts">{rows}</ul>'
            + (f'<div class="eyebrow" style="margin-top:14px">Fix first</div><ul class="verdicts">{fixes}</ul>' if fixes else "")
            + '<p class="small" style="color:var(--mm-panel-muted);margin:12px 0 0">Simulated evidence: confirm with a small real budget before scaling.</p></div>')
