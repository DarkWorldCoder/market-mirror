"""
social_feed.py - the "Social feed" dashboard section: the simulation post by post, as
X-style cards for Twitter and Reddit-style cards for Reddit, with platform tabs, a round
slider, segment and country filters, a "brand posts only" switch, a "most engaged first"
sort, a brand-posts strip (reach proxy, reply sentiment, best and worst reply) and a
per-round strip chart. Input is feed_story.json as written by
backend/app/services/feed_story.py. Stdlib only; every piece of post content is escaped.

Wiring into exporter.py (three lines, done by the exporter's owner, not here):
  1. next to `import feed_view` (and `from . import feed_view` in the except branch):
         import social_feed  # type: ignore
  2. in render_dashboard, right after the feed-test section is inserted:
         sf = social_feed.feed_story_section(bundle.get("feed_story") or {}, marketing.chart)
         if sf: mk_sections.insert(next((i + 1 for i, s in enumerate(mk_sections) if s[0] in ("feedtest", "playbook")), 1), sf)
  3. in the <style> and <script> strings of the page:
         ...{feed_view.FEED_CSS}{social_feed.SOCIAL_CSS}  and  ...{feed_view.FEED_JS}{social_feed.SOCIAL_JS}
  Also add "feed_story" to RUN_FILES so load_run_dir reads <run>/feed_story.json.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

try:  # stdlib only
    from feed_view import _avatar, _comments_html, _e, _t  # type: ignore
except ImportError:  # pragma: no cover - imported as a package
    from .feed_view import _avatar, _comments_html, _e, _t  # type: ignore

MAX_POSTS = 300
PLATFORM_LABEL = {"twitter": "X / Twitter", "reddit": "Reddit"}
ANCHOR = "socialfeed"


def _name(author: Optional[Dict[str, Any]]) -> str:
    return str((author or {}).get("name") or "Someone")


def _hour(p: Dict[str, Any]) -> str:
    rnd = p.get("round")
    if rnd is None:
        return "round ?"
    return f"round {rnd}" + (f" · {p['hour']}" if p.get("hour") else "")


def _who_line(author: Dict[str, Any]) -> str:
    seg = author.get("segment")
    country = author.get("country")
    bits = [f'<b>{_e(_name(author))}</b>']
    if seg:
        bits.append(f'<span class="sf-seg">{_e(seg)}</span>')
    if country:
        bits.append(f'<span class="pm-muted">{_e(country)}</span>')
    if author.get("kind") == "community":
        bits.append('<span class="sf-seg sf-brand">community account</span>')
    return " ".join(bits)


def _quote_box(p: Dict[str, Any]) -> str:
    if not p.get("original"):
        return ""
    o = p["original"] or {}
    return (f'<div class="sf-q"><b>{_e(_name(o.get("author")))}</b> '
            f'<span class="pm-muted">{_e((o.get("author") or {}).get("segment") or "")}</span>'
            f'<div>{_e(_t(p.get("quote_content"), 280))}</div></div>')


def _likers_title(p: Dict[str, Any]) -> str:
    names = [_name(a) for a in p.get("likers") or []][:12]
    if not names:
        return "no likes"
    more = len(p.get("likers") or []) - len(names)
    return "liked by " + ", ".join(names) + (f" and {more} more" if more > 0 else "")


def _engagers_title(p: Dict[str, Any]) -> str:
    seg = p.get("engagement", {}).get("by_segment") or {}
    return "engaged: " + ", ".join(f"{k} {v}" for k, v in seg.items()) if seg else "no reactions yet"


def _comments_block(p: Dict[str, Any], style: str) -> str:
    comments = p.get("comments") or []
    if not comments:
        return ""
    mapped = [{"name": _name(c.get("author")), "segment": (c.get("author") or {}).get("segment") or "",
               "text": (f'[{c.get("sentiment")}] ' if c.get("sentiment") else "") + str(c.get("content") or "")}
              for c in comments]
    rounds = sorted({c.get("round") for c in comments if c.get("round") is not None})
    when = f' · rounds {rounds[0]}–{rounds[-1]}' if len(rounds) > 1 else (f' · round {rounds[0]}' if rounds else "")
    return (f'<details class="sf-cm"><summary>{len(comments)} comment{"s" if len(comments) != 1 else ""}{_e(when)}</summary>'
            f'{_comments_html(mapped, style, limit=min(len(mapped), 20))}</details>')


def _card(p: Dict[str, Any], order: int) -> str:
    a = p.get("author") or {}
    platform = p.get("platform") or "twitter"
    kind = p.get("kind") or "post"
    attrs = (f'data-platform="{_e(platform)}" data-round="{_e("" if p.get("round") is None else p["round"])}" '
             f'data-segment="{_e(a.get("segment") or "")}" data-country="{_e(a.get("country") or "")}" '
             f'data-brand="{1 if p.get("is_brand") else 0}" data-score="{int(p.get("score") or 0)}" '
             f'data-order="{order}" data-id="{_e(p.get("post_id"))}"')
    n_comments = len(p.get("comments") or [])
    n_quotes = len(p.get("quotes") or [])
    text = _e(_t(p.get("content"), 600)).replace("\n", "<br>")
    brand = '<span class="sf-seg sf-brand">brand post</span>' if p.get("is_brand") else ""
    if kind == "repost":
        text = f'<span class="pm-muted">reposted {_e(_name((p.get("original") or {}).get("author")))}</span>'
    if platform == "reddit":
        votes = int(p.get("likes") or 0) - int(p.get("dislikes") or 0)
        return (f'<article class="sf-card pm pm-rd" {attrs}>'
                f'<div class="pm-rdvote" title="{_e(_likers_title(p))}">▲<b>{votes}</b>▼</div>'
                f'<div class="pm-rdbody"><div class="pm-muted">{_who_line(a)} · {_e(_hour(p))} {brand}</div>'
                f'<div class="pm-rdtext sf-text">{text}</div>{_quote_box(p)}'
                f'<div class="pm-muted sf-counts" title="{_e(_engagers_title(p))}"><span>💬 {n_comments}</span>'
                f'<span>👁 reach {int(p.get("reach_proxy") or 0)}</span></div>'
                f'{_comments_block(p, "reddit")}</div></article>')
    return (f'<article class="sf-card pm pm-x" {attrs}>'
            f'<div class="pm-h">{_avatar(_name(a))}<div>{_who_line(a)}<br><span class="pm-muted">{_e(_hour(p))}</span> {brand}</div></div>'
            f'<div class="pm-pad sf-text">{text}</div>{_quote_box(p)}'
            f'<div class="pm-xact sf-counts" title="{_e(_engagers_title(p))}"><span>💬 {n_comments}</span>'
            f'<span>🔁 {int(p.get("reposts") or 0)}</span><span>❝ {n_quotes}</span>'
            f'<span title="{_e(_likers_title(p))}">♥ {int(p.get("likes") or 0)}</span>'
            f'<span>👁 {int(p.get("reach_proxy") or 0)}</span></div>'
            f'{_comments_block(p, "x")}</article>')


def _sent_bar(rs: Dict[str, Any]) -> str:
    pos, neg, neu = int(rs.get("pos") or 0), int(rs.get("neg") or 0), int(rs.get("neu") or 0)
    total = pos + neg + neu
    if not total:
        return '<span class="pm-muted">no replies</span>'
    w = lambda v: f"{100 * v / total:.0f}%"  # noqa: E731
    return (f'<span class="sf-sb" title="{pos} positive, {neu} neutral, {neg} negative replies (lexicon)">'
            f'<i class="pos" style="width:{w(pos)}"></i><i class="neu" style="width:{w(neu)}"></i>'
            f'<i class="neg" style="width:{w(neg)}"></i></span> <span class="small">{pos}/{neu}/{neg}</span>')


def _reply(r: Optional[Dict[str, Any]]) -> str:
    if not r:
        return '<span class="pm-muted">–</span>'
    return f'<span class="pill {_e(r.get("sentiment") or "neu")}">{_e(r.get("sentiment"))}</span> <b>{_e(_name(r.get("author")))}</b>: {_e(_t(r.get("content"), 160))}'


def _brand_strip(brand_posts: List[Dict[str, Any]]) -> str:
    if not brand_posts:
        return ""
    rows = []
    for b in sorted(brand_posts, key=lambda b: (b.get("platform") or "", b.get("round") if b.get("round") is not None else 10 ** 9, b.get("post_id") or 0)):
        rows.append(
            f'<tr><td>{_e(PLATFORM_LABEL.get(b.get("platform"), b.get("platform")))}<br><span class="pm-muted">{_e(_hour(b))} · {_e(b.get("source") or "")}</span></td>'
            f'<td class="sf-bt"><b>{_e(_name(b.get("author")))}</b><br>{_e(_t(b.get("content"), 200))}</td>'
            f'<td class="num">{int(b.get("likes") or 0)}</td><td class="num">{len(b.get("quotes") or [])}</td>'
            f'<td class="num">{int(b.get("reposts") or 0)}</td><td class="num">{len(b.get("comments") or [])}</td>'
            f'<td class="num">{int(b.get("reach_proxy") or 0)}</td><td>{_sent_bar(b.get("reply_sentiment") or {})}</td>'
            f'<td class="sf-bt">{_reply(b.get("best_reply"))}</td><td class="sf-bt">{_reply(b.get("worst_reply"))}</td></tr>')
    return (f'<div class="card sf-brand-card"><h3>Brand posts</h3><p class="muted small">Posts injected into the simulation '
            f'(initial posts, scheduled events and community accounts) and how people answered them. Reach is a proxy: the '
            f'author\'s followers plus everyone who reacted and their followers. Reply sentiment is a word-list heuristic.</p>'
            f'<div class="tbl{" tall" if len(rows) > 6 else ""}"><table class="sf-brand-t"><thead><tr><th>Where</th><th>Post</th><th class="num">Likes</th>'
            f'<th class="num">Quotes</th><th class="num">Reposts</th><th class="num">Comments</th><th class="num">Reach</th>'
            f'<th>Replies +/0/−</th><th>Best reply</th><th>Worst reply</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></div>')


def _rounds_block(platform: str, rounds: List[Dict[str, Any]], chart) -> str:
    rounds = [r for r in rounds if r.get("round") is not None]
    if not rounds:
        return ""
    cats = [f'r{r["round"]}' + (f' · {r["hour"]}' if r.get("hour") else "") for r in rounds]
    spec = {"cats": cats, "posts": [int(r.get("posts") or 0) for r in rounds],
            "comments": [int(r.get("comments") or 0) for r in rounds], "likes": [int(r.get("likes") or 0) for r in rounds]}
    label = f"{PLATFORM_LABEL.get(platform, platform)}: posts, comments and likes per round"
    body = "".join(f'<tr><td>{_e(c)}</td><td class="num">{r.get("posts", 0)}</td><td class="num">{r.get("comments", 0)}</td>'
                   f'<td class="num">{r.get("likes", 0)}</td><td class="num">{_e(", ".join(str(x) for x in r.get("top_posts") or []))}</td>'
                   f'<td>{_sent_bar(r.get("brand_sentiment") or {})}</td></tr>' for c, r in zip(cats, rounds))
    return (f'<div class="card sf-rounds"><h3>Activity per round</h3>{chart("sfrounds", spec, 60 + 24 * max(len(rounds), 3), label)}'
            f'<details class="tv"><summary>Show the numbers</summary><div class="tbl"><table><thead><tr><th>Round</th>'
            f'<th class="num">Posts</th><th class="num">Comments</th><th class="num">Likes</th><th class="num">Top posts</th>'
            f'<th>Brand replies +/0/−</th></tr></thead><tbody>{body}</tbody></table></div></details></div>')


def feed_story_section(fs: Dict[str, Any], chart) -> Optional[Tuple[str, str, str]]:
    """(anchor, label, html) for the Social feed section, or None when there is nothing to show."""
    platforms = (fs or {}).get("platforms") or {}
    shown = {k: v for k, v in platforms.items() if (v or {}).get("posts")}
    if not shown:
        return None
    order = [k for k in ("twitter", "reddit") if k in shown] + [k for k in shown if k not in ("twitter", "reddit")]
    segments: Dict[str, int] = {}
    countries: Dict[str, int] = {}
    max_round = -1
    total_posts = 0
    for k in order:
        for p in shown[k]["posts"]:
            a = p.get("author") or {}
            if a.get("segment"):
                segments[a["segment"]] = segments.get(a["segment"], 0) + 1
            if a.get("country"):
                countries[a["country"]] = countries.get(a["country"], 0) + 1
            if p.get("round") is not None:
                max_round = max(max_round, int(p["round"]))
            for c in p.get("comments") or []:
                if c.get("round") is not None:
                    max_round = max(max_round, int(c["round"]))
        for r in shown[k].get("rounds") or []:
            if r.get("round") is not None:
                max_round = max(max_round, int(r["round"]))
        total_posts += int(shown[k].get("total_posts") or len(shown[k]["posts"]))
    hours = {}
    for k in order:
        for r in shown[k].get("rounds") or []:
            if r.get("round") is not None and r.get("hour"):
                hours.setdefault(int(r["round"]), r["hour"])

    tabs = "".join(f'<button type="button" data-tab="{_e(k)}" aria-pressed="{"true" if i == 0 else "false"}">'
                   f'{_e(PLATFORM_LABEL.get(k, k))} <span class="pm-muted">{len(shown[k]["posts"])}</span></button>'
                   for i, k in enumerate(order))
    seg_opts = "".join(f'<option value="{_e(s)}">{_e(s)} ({n})</option>' for s, n in sorted(segments.items(), key=lambda x: -x[1]))
    cty_opts = "".join(f'<option value="{_e(c)}">{_e(c)} ({n})</option>' for c, n in sorted(countries.items(), key=lambda x: -x[1]))
    slider = ""
    if max_round >= 0:
        slider = (f'<label class="sf-round">Round <input type="range" min="-1" max="{max_round}" value="-1" step="1" data-round '
                  f'aria-label="Round"> <output data-round-out>all rounds</output></label>')
    bar = (f'<div class="sf-bar"><div class="sf-tabs seg-tabs" role="tablist">{tabs}</div>{slider}'
           f'<select data-segment aria-label="Segment"><option value="">All segments</option>{seg_opts}</select>'
           f'<select data-country aria-label="Country"><option value="">All countries</option>{cty_opts}</select>'
           f'<label><input type="checkbox" data-brand> Brand posts only</label>'
           f'<label><input type="checkbox" data-sort> Most engaged first</label>'
           f'<span class="sf-count muted small" data-count aria-live="polite"></span></div>')

    panels = []
    for i, k in enumerate(order):
        posts = shown[k]["posts"][:MAX_POSTS]
        cards = "".join(_card(p, n) for n, p in enumerate(posts))
        note = ""
        tot = int(shown[k].get("total_posts") or len(shown[k]["posts"]))
        if tot > len(posts):
            note = f'<p class="muted small">Showing the first {len(posts)} of {tot} posts; the full list is in feed_story.json.</p>'
        panels.append(f'<div class="sf-panel" data-panel="{_e(k)}"{"" if i == 0 else " hidden"}>'
                      f'{_rounds_block(k, shown[k].get("rounds") or [], chart)}{note}<div class="sf-feed">{cards}</div></div>')
    index = {"hours": {str(r): h for r, h in hours.items()}, "platforms": {k: len(shown[k]["posts"]) for k in order},
             "rounds_known": all(bool(shown[k].get("rounds_known", True)) for k in order)}
    n_brand = len((fs or {}).get("brand_posts") or [])
    head = (f'<h2>Social feed</h2><p class="muted small">Every post of the simulation, who wrote it, from which segment and country, '
            f'in which round, and how people reacted: likes (hover for names), quotes, reposts and comments. '
            f'{total_posts} posts across {len(order)} platform{"s" if len(order) != 1 else ""}'
            + (f', {n_brand} of them brand posts' if n_brand else '') + '. Sentiment labels come from a word list, not a model.</p>')
    html_ = (head + _brand_strip((fs or {}).get("brand_posts") or []) + f'<div class="sf" data-sf-root>{bar}{"".join(panels)}'
             f'<script type="application/json" data-sf-index>{json.dumps(index, ensure_ascii=False).replace("</", "<\\/")}</script></div>')
    return (ANCHOR, "Social feed", html_)


SOCIAL_CSS = """
.sf-bar{display:flex;flex-wrap:wrap;gap:10px 14px;align-items:center;margin:12px 0 14px;font-size:.88rem}
.sf-bar select,.sf-bar input[type=range]{font:inherit;font-size:.86rem;color:var(--text);background:var(--surface);border:1px solid var(--border);border-radius:999px;padding:5px 10px;max-width:100%}
.sf-bar input[type=range]{padding:0;width:140px;vertical-align:middle;border:0;background:transparent}
.sf-bar label{display:inline-flex;gap:6px;align-items:center}
.sf-round output{min-width:120px;display:inline-block;color:var(--text-2)}
.sf-tabs{margin:0}
.sf-panel[hidden]{display:none}
.sf-feed{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,360px),1fr));gap:14px;align-items:start}
.sf-card.pm{max-width:none;min-width:0}
.sf-card[hidden]{display:none}
.sf-text{overflow-wrap:anywhere;white-space:normal}
.sf-seg{display:inline-block;font-size:.72rem;border-radius:999px;padding:1px 8px;background:#eef1f5;color:#3a3f47;margin-left:4px}
.sf-seg.sf-brand{background:#ffe9b8;color:#5a3d00}
.sf-q{margin:4px 12px 8px;border:1px solid #dddfe2;border-radius:12px;padding:8px 10px;font-size:.86rem;background:#f7f8fa}
.pm-rd .sf-q{margin:4px 0 8px}
.sf-counts{display:flex;gap:14px;flex-wrap:wrap}
.pm-rd .sf-counts{padding:4px 0}
.sf-cm{padding:0 12px 10px;font-size:.86rem}.pm-rd .sf-cm{padding:0 0 6px}
.sf-cm summary{cursor:pointer;color:#536471}
.sf-sb{display:inline-flex;width:90px;height:10px;border-radius:5px;overflow:hidden;background:var(--surface-2);vertical-align:middle}
.sf-sb i{display:block;height:100%}.sf-sb .pos{background:var(--mm-yes,#1baf7a)}.sf-sb .neu{background:var(--mm-maybe,#eda100)}.sf-sb .neg{background:var(--mm-no,#e34948)}
.sf-brand-t td,.sf-brand-t th{vertical-align:top}.sf-bt{min-width:180px;max-width:320px;font-size:.84rem}
.sf-rounds{margin-bottom:14px}
.sf-count{margin-left:auto}
@media (max-width:700px){.sf-feed{grid-template-columns:1fr}.sf-count{margin-left:0}}
@media print{.sf-bar{display:none}.sf-card{break-inside:avoid}}
"""

SOCIAL_JS = r"""
(function(){
var root=document.querySelector('[data-sf-root]');if(!root)return;
var index={};try{index=JSON.parse((root.querySelector('[data-sf-index]')||{}).textContent||'{}');}catch(e){}
var hours=index.hours||{};
var tabs=root.querySelector('.sf-tabs'),range=root.querySelector('[data-round]'),out=root.querySelector('[data-round-out]'),
 seg=root.querySelector('[data-segment]'),cty=root.querySelector('[data-country]'),brand=root.querySelector('[data-brand]'),
 sort=root.querySelector('[data-sort]'),count=root.querySelector('[data-count]');
function current(){var b=tabs&&tabs.querySelector('button[aria-pressed="true"]');return b?b.getAttribute('data-tab'):null;}
function apply(){var cur=current(),r=range?parseInt(range.value,10):-1,s=seg?seg.value:'',c=cty?cty.value:'',b=brand&&brand.checked,shown=0,total=0;
 if(out)out.textContent=r<0?'all rounds':('round '+r+(hours[r]?' · '+hours[r]:''));
 root.querySelectorAll('.sf-panel').forEach(function(p){var on=p.getAttribute('data-panel')===cur;p.hidden=!on;if(!on)return;
  var feed=p.querySelector('.sf-feed');var cards=Array.prototype.slice.call(feed.querySelectorAll('.sf-card'));total=cards.length;
  cards.forEach(function(k){var ok=(r<0||k.getAttribute('data-round')===String(r))&&(!s||k.getAttribute('data-segment')===s)&&(!c||k.getAttribute('data-country')===c)&&(!b||k.getAttribute('data-brand')==='1');k.hidden=!ok;if(ok)shown++;});
  var key=sort&&sort.checked?function(k){return -parseInt(k.getAttribute('data-score')||'0',10);}:function(k){return parseInt(k.getAttribute('data-order')||'0',10);};
  cards.sort(function(a,b2){return key(a)-key(b2);}).forEach(function(k){feed.appendChild(k);});
  drawRounds(p);});
 if(count)count.textContent=shown+' of '+total+' posts';}
if(tabs)tabs.addEventListener('click',function(ev){var b=ev.target.closest('button');if(!b)return;tabs.querySelectorAll('button').forEach(function(x){x.setAttribute('aria-pressed',x===b?'true':'false');});apply();});
[range,seg,cty,brand,sort].forEach(function(el){if(el)el.addEventListener(el.tagName==='SELECT'?'change':'input',apply);});
function css(n){return getComputedStyle(document.documentElement).getPropertyValue(n).trim();}
function drawRounds(panel){if(!window.echarts)return;panel.querySelectorAll('.ec[data-kind=sfrounds]').forEach(function(el){
 if(el.__ec||el.offsetWidth===0)return;var s;try{s=JSON.parse(el.getAttribute('data-spec'));}catch(e){return;}
 var t={ink:css('--text'),ink2:css('--text-2'),muted:css('--muted'),grid:css('--grid'),card:css('--surface'),line:css('--border'),
  s:[css('--s1'),css('--s2'),css('--s3')],font:getComputedStyle(document.body).fontFamily};
 var mk=function(name,key,col){return {name:name,type:'bar',barMaxWidth:18,data:s[key],itemStyle:{color:col,borderRadius:[4,4,0,0]}};};
 var c=echarts.init(el,null,{renderer:'svg'});c.setOption({textStyle:{fontFamily:t.font,color:t.muted,fontSize:11},animationDuration:450,
  tooltip:{trigger:'axis',confine:true,backgroundColor:t.card,borderColor:t.line,borderWidth:1,textStyle:{color:t.ink,fontSize:12},axisPointer:{type:'shadow',shadowStyle:{color:'rgba(127,127,127,.08)'}}},
  legend:{top:0,left:0,icon:'roundRect',itemWidth:10,itemHeight:10,textStyle:{color:t.ink2}},
  grid:{left:8,right:12,top:32,bottom:4,containLabel:true},
  xAxis:{type:'category',data:s.cats,axisTick:{show:false},axisLine:{show:false},axisLabel:{color:t.ink2,fontSize:12}},
  yAxis:{type:'value',axisLine:{show:false},axisTick:{show:false},splitLine:{lineStyle:{color:t.grid}},axisLabel:{color:t.muted},minInterval:1},
  series:[mk('Posts','posts',t.s[0]),mk('Comments','comments',t.s[1]),mk('Likes','likes',t.s[2])]});el.__ec=c;});}
function redraw(){root.querySelectorAll('.ec[data-kind=sfrounds]').forEach(function(el){if(el.__ec){el.__ec.dispose();el.__ec=null;}});apply();}
function resize(){root.querySelectorAll('.ec[data-kind=sfrounds]').forEach(function(el){el.__ec&&el.__ec.resize();});
 root.querySelectorAll('.sf-panel:not([hidden])').forEach(drawRounds);}
var rt;window.addEventListener('resize',function(){clearTimeout(rt);rt=setTimeout(resize,120);});
document.addEventListener('visibilitychange',function(){if(!document.hidden)resize();});
try{matchMedia('(prefers-color-scheme: dark)').addEventListener('change',redraw);}catch(e){}
new MutationObserver(redraw).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
apply();
})();
"""
