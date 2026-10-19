"""
live_view.py - the live control room served by `mirofish.py live` at /live: every stage of the run, live
counters, a grid of every simulated person (lights up when they act, takes their survey/pitch verdict colour),
the stream of what they post and comment, and the run's progress log. The page polls /__live/feed (built
here from the run folder, which the live loop keeps collecting) every two seconds. Stdlib only.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional

PROGRESS_FILE = "progress.log"

STAGES = [  # (key in run_manifest.json, label)
    ("project_id", "Read the brief"), ("graph_id", "Market map"), ("simulation_id", "Simulated people"),
    ("feed_test", "Ads in feeds"), ("runner_status", "Social rounds"), ("survey", "Buyer survey"),
    ("pitch", "Sales pitch"), ("panel", "Analyst panel"), ("report", "Report"), ("finished_at", "Dashboard"),
]
POSTY = {"CREATE_POST": "posted", "CREATE_COMMENT": "commented", "QUOTE_POST": "quoted", "REPOST": "reposted",
         "LIKE_POST": "liked a post", "LIKE_COMMENT": "liked a comment", "DISLIKE_POST": "disliked a post",
         "FOLLOW": "followed someone", "SEARCH_POSTS": "searched", "DO_NOTHING": "scrolled past"}


def _load(run_dir: str, name: str) -> Any:
    try:
        with open(os.path.join(run_dir, name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _tail(path: str, n: int = 30) -> List[str]:
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 24000))
            lines = f.read().decode("utf-8", "replace").splitlines()
        return [l for l in lines if l.strip()][-n:]
    except OSError:
        return []


def _actions(run_dir: str) -> List[Dict[str, Any]]:
    a = _load(run_dir, "actions.json")
    if isinstance(a, dict):
        a = a.get("actions") or []
    rows = [x for x in (a or []) if isinstance(x, dict)]
    return sorted(rows, key=lambda x: (str(x.get("timestamp") or ""), x.get("round_num") or 0))   # platforms are stored one after the other


def feed(run_dir: str, label: str = "") -> Dict[str, Any]:
    """Everything the control room shows, from the run folder."""
    m = _load(run_dir, "run_manifest.json") or {}
    rs = _load(run_dir, "run_status.json") or {}
    cfg = _load(run_dir, "config.json") or {}
    survey = _load(run_dir, "survey.json") or {}
    ft = _load(run_dir, "feed_test.json") or {}
    pitch = _load(run_dir, "pitch.json") or {}
    actions = _actions(run_dir)

    # stages: done when the manifest has the key; the first missing one is running (unless finished or failed)
    stages, running_set = [], False
    for key, label_ in STAGES:
        done = bool(m.get(key))
        state = "done" if done else "wait"
        if not done and not running_set and not m.get("finished_at") and not m.get("error") and m:
            state, running_set = "run", True
        stages.append({"key": key, "label": label_, "state": state})
    if m.get("error"):
        nxt = next((s for s in stages if s["state"] == "wait"), None)
        if nxt:
            nxt["state"] = "fail"

    # people
    index = [r for r in (cfg.get("persona_index") or []) if isinstance(r, dict) and r.get("kind") in ("persona", "person")]
    acts_by: Counter = Counter()
    last_by: Dict[Any, str] = {}
    for x in actions:
        aid = x.get("agent_id")
        if x.get("action_type") != "DO_NOTHING":
            acts_by[aid] += 1
        last_by[aid] = x.get("timestamp") or last_by.get(aid, "")
    verdict = {r.get("agent_id"): (r.get("answer") or {}).get("would_convert")
               for r in survey.get("responses") or [] if r.get("answer")}
    for r in pitch.get("people") or []:
        if r.get("final_verdict"):
            verdict.setdefault(r.get("agent_id"), r["final_verdict"])
    clicked = {s.get("agent_id") for s in ft.get("sessions") or [] if (s.get("ad") or {}).get("click")}
    seen_ad = {s.get("agent_id") for s in ft.get("sessions") or []}
    newest = max(last_by.values(), default="")
    people = []
    for r in index:
        try:
            aid = int(r.get("agent_id"))
        except (TypeError, ValueError):
            continue
        hot = bool(not m.get("finished_at") and newest and last_by.get(aid)
                   and last_by[aid][:16] >= newest[:16])   # acted in the latest minute of activity of a running run
        people.append({"id": aid, "name": r.get("name"), "segment": r.get("segment"), "country": r.get("country"),
                       "acts": acts_by.get(aid, 0), "hot": hot, "verdict": verdict.get(aid),
                       "clicked": aid in clicked, "saw_ad": aid in seen_ad})

    # stream: newest first, skip silent scrolls
    stream = []
    for x in reversed(actions):
        t = x.get("action_type")
        if t == "DO_NOTHING":
            continue
        args = x.get("action_args") or {}
        text = args.get("content") or args.get("quote_content") or args.get("query") or ""
        stream.append({"who": x.get("agent_name") or f"agent {x.get('agent_id')}", "what": POSTY.get(t, (t or "").lower().replace("_", " ")),
                       "text": str(text)[:220], "round": x.get("round_num"), "platform": x.get("platform"),
                       "t": (x.get("timestamp") or "")[11:19]})
        if len(stream) >= 40:
            break

    types = Counter(x.get("action_type") for x in actions)
    answered = [v for v in verdict.values() if v]
    vc = Counter(answered)
    counters = {
        "people": len(people), "actions": sum(v for k, v in types.items() if k != "DO_NOTHING"),
        "posts": types.get("CREATE_POST", 0) + types.get("QUOTE_POST", 0), "comments": types.get("CREATE_COMMENT", 0),
        "likes": types.get("LIKE_POST", 0) + types.get("LIKE_COMMENT", 0),
        "round": rs.get("current_round"), "rounds": rs.get("total_rounds"),
        "surveyed": len(survey.get("responses") or []), "yes": vc.get("yes", 0), "maybe": vc.get("maybe", 0), "no": vc.get("no", 0),
        "ad_views": len(ft.get("sessions") or []), "ad_clicks": sum(1 for s in ft.get("sessions") or [] if (s.get("ad") or {}).get("click")),
        "pitched": len([r for r in pitch.get("people") or [] if r.get("turn1")]),
    }
    per_round = Counter(x.get("round_num") for x in actions if x.get("action_type") != "DO_NOTHING")
    return {"title": m.get("title") or os.path.basename(os.path.abspath(run_dir)), "label": label,
            "error": m.get("error"), "stages": stages, "counters": counters, "people": people, "stream": stream,
            "per_round": [per_round.get(i, 0) for i in range(0, max(per_round.keys(), default=-1) + 1)],
            "log": _tail(os.path.join(run_dir, PROGRESS_FILE), 40), "now": datetime.now().strftime("%H:%M:%S")}


CONTROL_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Live · MarketMirror</title><style>
:root{color-scheme:light;--bg:#eeeeea;--card:#fff;--sunk:#f6f6f3;--ink:#111;--ink2:#3d3d3a;--mut:#6b6b66;--line:#e8e7e2;--panel:#121212;--panel2:#1d1d1c;
--acc:#f3d64b;--accink:#2b2005;--yes:#2a78d6;--maybe:#c9c7bd;--no:#e34948;--hot:#1baf7a}
@media (prefers-color-scheme:dark){:root{color-scheme:dark;--bg:#0d0d0c;--card:#171716;--sunk:#1f1f1d;--ink:#f2f2ee;--ink2:#c9c9c2;--mut:#8f8f88;--line:#2a2a28;--panel:#000;--panel2:#1d1d1c;--maybe:#55554f}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1360px;margin:0 auto;padding:20px 24px 48px}
.bar{display:flex;align-items:center;gap:10px;padding:6px;border-radius:999px;background:var(--panel);color:#f2f2ee;margin-bottom:22px}
.bar .t{flex:1;min-width:0;padding:0 14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:500}
.bar .pill{height:38px;display:inline-flex;align-items:center;gap:8px;padding:0 16px;border-radius:999px;background:var(--panel2);color:#cfcfc8;font-size:13px;white-space:nowrap}
.bar .pill.live{background:var(--acc);color:var(--accink);font-weight:600}.bar a.pill{text-decoration:none}
.dot{width:8px;height:8px;border-radius:50%;background:currentColor;display:inline-block}.live .dot{animation:pulse 1.2s infinite}
@keyframes pulse{50%{opacity:.25}}
h1{font-size:clamp(1.8rem,3.4vw,2.8rem);font-weight:500;letter-spacing:-.045em;text-transform:uppercase;margin:0 0 4px;line-height:1}
.sub{color:var(--mut);margin:0 0 20px;font-size:13px}
.stages{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:18px}
.st{flex:none;display:flex;align-items:center;gap:8px;height:40px;padding:0 14px 0 6px;border-radius:999px;background:var(--card);color:var(--mut);font-size:13px}
.st i{display:grid;place-items:center;width:28px;height:28px;border-radius:50%;background:var(--sunk);font-style:normal;font-size:12px}
.st.done{color:var(--ink)}.st.done i{background:var(--ink);color:var(--card)}
.st.run{background:var(--ink);color:var(--card)}.st.run i{background:var(--acc);color:var(--accink);animation:pulse 1.2s infinite}
.st.fail{background:#fde6e6;color:#9e2b2a}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-bottom:18px}
.k{background:var(--card);border-radius:22px;padding:14px 16px}.k b{display:block;font-size:1.9rem;font-weight:500;letter-spacing:-.04em;line-height:1.1}
.k span{color:var(--ink2);font-size:12.5px}.k small{display:block;color:var(--mut);font-size:11.5px}
.grid{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(0,1fr);gap:14px}
.card{background:var(--card);border-radius:26px;padding:18px 20px;min-width:0}
.card h2{font-size:1.05rem;font-weight:500;letter-spacing:-.02em;margin:0 0 4px}.card .hint{color:var(--mut);font-size:12px;margin:0 0 12px}
.people{display:grid;grid-template-columns:repeat(auto-fill,minmax(18px,1fr));gap:5px}
.p{aspect-ratio:1;border-radius:50%;background:var(--sunk);box-shadow:inset 0 0 0 1px var(--line);transition:transform .3s,background .4s}
.p.a{background:color-mix(in srgb,var(--ink) 35%,transparent)}.p.hot{background:var(--hot);transform:scale(1.25)}
.p.yes{background:var(--yes)}.p.maybe{background:var(--maybe)}.p.no{background:var(--no)}.p.clk{box-shadow:0 0 0 2px var(--acc)}
.legend{display:flex;flex-wrap:wrap;gap:6px 14px;margin-top:12px;font-size:12px;color:var(--ink2)}.legend i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px;vertical-align:-1px}
.stream{display:flex;flex-direction:column;gap:8px;max-height:560px;overflow-y:auto;scrollbar-width:thin}
.ev{display:flex;gap:10px;padding:10px 12px;border-radius:16px;background:var(--sunk);animation:in .5s ease}
@keyframes in{from{opacity:0;transform:translateY(-6px)}}
.ev .av{flex:none;display:grid;place-items:center;width:30px;height:30px;border-radius:50%;background:var(--card);font-weight:600;font-size:12px}
.ev b{font-weight:600}.ev .m{color:var(--mut);font-size:11.5px}.ev p{margin:2px 0 0;color:var(--ink2);font-size:13px;overflow-wrap:anywhere}
.rounds{display:flex;align-items:flex-end;gap:4px;height:60px;margin-top:8px}.rounds div{flex:1;background:var(--ink);border-radius:6px 6px 2px 2px;min-height:3px;opacity:.85}
.log{font:12px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--panel);color:#d6d6d0;border-radius:18px;padding:12px 14px;max-height:300px;overflow:auto;white-space:pre-wrap}
.empty{color:var(--mut);font-size:13px}
@media (max-width:900px){.grid{grid-template-columns:1fr}.wrap{padding:12px 14px 40px}}
</style></head><body><div class="wrap">
<div class="bar"><span class="t" id="title">MarketMirror live</span><span class="pill live" id="label"><span class="dot"></span><span>Connecting</span></span>
<span class="pill" id="clock">–</span><a class="pill" href="/">Full dashboard ↗</a></div>
<p class="sub">Live control room · updates every 2 seconds · simulated people, simulated answers</p>
<h1 id="h1">Live run</h1><p class="sub" id="err"></p>
<div class="stages" id="stages"></div>
<div class="kpis" id="kpis"></div>
<div class="grid"><div style="display:grid;gap:14px;align-content:start">
<div class="card"><h2>Every simulated person</h2><p class="hint">Each dot is one person. Green: acting right now. Then coloured by their answer.</p>
<div class="people" id="people"></div><div class="legend"><span><i style="background:var(--hot)"></i>acting now</span><span><i style="background:color-mix(in srgb,var(--ink) 35%,transparent)"></i>has acted</span>
<span><i style="background:var(--yes)"></i>would convert</span><span><i style="background:var(--maybe)"></i>maybe</span><span><i style="background:var(--no)"></i>no</span><span><i style="box-shadow:0 0 0 2px var(--acc)"></i>clicked the ad</span></div></div>
<div class="card"><h2>Activity per round</h2><p class="hint">Posts, comments, likes and quotes in each social round.</p><div class="rounds" id="rounds"></div></div>
<div class="card"><h2>Progress log</h2><p class="hint">Feed test, survey, pitch and report steps as they happen.</p><div class="log" id="log">Waiting for the run to write progress…</div></div>
</div><div class="card"><h2>What people are saying</h2><p class="hint">Newest first, from the social rounds.</p><div class="stream" id="stream"></div></div></div>
</div><script>
var seen={},$=function(i){return document.getElementById(i);};
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
function k(v,l,s){return '<div class="k"><b>'+esc(v)+'</b><span>'+esc(l)+'</span>'+(s?'<small>'+esc(s)+'</small>':'')+'</div>';}
function render(d){$('title').textContent=d.title;$('h1').textContent=d.title;$('clock').textContent='updated '+d.now;
 $('label').lastChild.textContent=d.label||(d.error?'Stopped':'Running');$('err').textContent=d.error?('Stopped with error: '+d.error):'';
 $('stages').innerHTML=d.stages.map(function(s,i){return '<span class="st '+s.state+'"><i>'+(s.state==='done'?'✓':s.state==='fail'?'!':(i+1))+'</i>'+esc(s.label)+'</span>';}).join('');
 var c=d.counters,sv=c.surveyed?(c.yes+' yes · '+c.maybe+' maybe · '+c.no+' no'):'';
 $('kpis').innerHTML=k(c.people,'simulated people')+k((c.round!=null?c.round:'–')+(c.rounds?' / '+c.rounds:''),(c.rounds===1?'social round':'social rounds'))+k(c.actions,'actions',c.posts+' posts · '+c.comments+' comments · '+c.likes+' likes')
  +k(c.ad_views,'ad views',c.ad_clicks+' clicks')+k(c.surveyed,'surveyed',sv)+k(c.pitched,'pitched');
 $('people').innerHTML=d.people.length?d.people.map(function(p){var cl='p'+(p.acts?' a':'')+(p.verdict?' '+p.verdict:'')+(p.hot?' hot':'')+(p.clicked?' clk':'');
  return '<span class="'+cl+'" title="'+esc(p.name+' · '+(p.segment||'')+' · '+(p.country||'')+' · '+p.acts+' actions'+(p.verdict?' · '+p.verdict:''))+'"></span>';}).join(''):'<p class="empty">People appear once they are created.</p>';
 var mx=Math.max.apply(null,[1].concat(d.per_round));$('rounds').innerHTML=d.per_round.length?d.per_round.map(function(v,i){return '<div title="round '+i+': '+v+'" style="height:'+(100*v/mx)+'%"></div>';}).join(''):'<p class="empty">No rounds yet.</p>';
 if(d.log.length){var L=$('log'),bottom=L.scrollTop+L.clientHeight>=L.scrollHeight-8;L.textContent=d.log.join('\n');if(bottom)L.scrollTop=L.scrollHeight;}
 $('stream').innerHTML=d.stream.length?d.stream.map(function(e){var key=e.t+e.who+e.text,isNew=!seen[key];seen[key]=1;
  return '<div class="ev"'+(isNew?'':' style="animation:none"')+'><span class="av">'+esc((e.who||'?').slice(0,1))+'</span><div><b>'+esc(e.who)+'</b> '+esc(e.what)
   +' <span class="m">· round '+esc(e.round)+' · '+esc(e.platform||'')+' · '+esc(e.t)+'</span>'+(e.text?'<p>'+esc(e.text)+'</p>':'')+'</div></div>';}).join(''):'<p class="empty">Nobody has posted yet.</p>';}
function tick(){fetch('/__live/feed',{cache:'no-store'}).then(function(r){return r.json();}).then(function(d){render(d);setTimeout(tick,2000);})
 .catch(function(){$('label').lastChild.textContent='Reconnecting';setTimeout(tick,3000);});}
tick();
</script></body></html>"""
