"""
geo_view.py - "Where they are": a world map of the simulated people with a metric switcher (people, would
convert, ad CTR, lead score, pitch yes), a ranked country table and the settlement mix (metro / city / town /
rural) and top cities per country. The map is an ECharts choropleth over the vendored Natural Earth outlines
(vendor/world.geo.json), inlined only when this section renders. Stdlib only.
"""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

try:  # stdlib only
    import ui  # type: ignore
except ImportError:  # pragma: no cover - imported as a package
    from . import ui  # type: ignore

_e = ui.esc
GEO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor", "world.geo.json")

# names and codes people write -> the Natural Earth name in world.geo.json
ALIASES = {
    "us": "United States of America", "usa": "United States of America", "united states": "United States of America",
    "america": "United States of America", "uk": "United Kingdom", "gb": "United Kingdom", "great britain": "United Kingdom",
    "england": "United Kingdom", "britain": "United Kingdom", "in": "India", "ph": "Philippines", "ke": "Kenya",
    "ng": "Nigeria", "za": "South Africa", "pk": "Pakistan", "bd": "Bangladesh", "np": "Nepal", "lk": "Sri Lanka",
    "id": "Indonesia", "my": "Malaysia", "sg": "Malaysia", "singapore": "Malaysia", "th": "Thailand", "vn": "Vietnam",
    "viet nam": "Vietnam", "cn": "China", "jp": "Japan", "kr": "South Korea", "korea": "South Korea",
    "republic of korea": "South Korea", "tw": "Taiwan", "au": "Australia", "nz": "New Zealand", "ca": "Canada",
    "mx": "Mexico", "br": "Brazil", "ar": "Argentina", "co": "Colombia", "cl": "Chile", "pe": "Peru", "de": "Germany",
    "fr": "France", "es": "Spain", "it": "Italy", "nl": "Netherlands", "se": "Sweden", "no": "Norway", "dk": "Denmark",
    "fi": "Finland", "pl": "Poland", "pt": "Portugal", "ie": "Ireland", "ch": "Switzerland", "at": "Austria",
    "be": "Belgium", "tr": "Turkey", "türkiye": "Turkey", "turkiye": "Turkey", "ae": "United Arab Emirates",
    "uae": "United Arab Emirates", "sa": "Saudi Arabia", "eg": "Egypt", "ma": "Morocco", "gh": "Ghana", "et": "Ethiopia",
    "tz": "Tanzania", "ug": "Uganda", "rw": "Rwanda", "ru": "Russia", "russian federation": "Russia", "ua": "Ukraine",
    "il": "Israel", "ir": "Iran", "iq": "Iraq", "czech republic": "Czechia", "cz": "Czechia",
    "ivory coast": "Côte d'Ivoire", "drc": "Dem. Rep. Congo", "dr congo": "Dem. Rep. Congo",
    "democratic republic of the congo": "Dem. Rep. Congo", "dominican republic": "Dominican Rep.",
    "bosnia and herzegovina": "Bosnia and Herz.", "south sudan": "S. Sudan", "eswatini": "eSwatini", "swaziland": "eSwatini",
    "hong kong": "China", "hk": "China", "lao": "Laos", "burma": "Myanmar", "mm": "Myanmar",
}
METRICS = [("people", "People", ""), ("convert", "Would convert", "%"), ("ctr", "Ad CTR", "%"),
           ("lead", "Lead score", ""), ("pitch", "Pitch yes", "%")]


def _geo_names() -> set:
    try:
        with open(GEO_PATH, encoding="utf-8") as f:
            return {ft["properties"]["name"] for ft in json.load(f)["features"]}
    except (OSError, ValueError, KeyError):
        return set()


_NAMES: Optional[set] = None


def geo_name(country: Any) -> Optional[str]:
    """The world.geo.json name for a country string ("IN", "india", "United States") or None."""
    global _NAMES
    if _NAMES is None:
        _NAMES = _geo_names()
    raw = str(country or "").strip()
    if not raw:
        return None
    key = raw.lower()
    if key in ALIASES:
        return ALIASES[key]
    for n in _NAMES:
        if n.lower() == key:
            return n
    return raw if raw in _NAMES else None


def _pct(n: int, d: int) -> Optional[float]:
    return round(100.0 * n / d, 1) if d else None


def country_rows(bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One row per country of the simulated people: counts, settlement mix, top cities, survey/ad/pitch numbers."""
    cfg = bundle.get("config") or {}
    index = [r for r in (cfg.get("persona_index") or []) if isinstance(r, dict) and r.get("country")
             and r.get("kind") in (None, "persona", "person")]
    if not index:
        return []
    by_agent: Dict[Any, Dict[str, Any]] = {}
    acc: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"people": 0, "weight": 0.0, "settlement": Counter(), "cities": Counter(),
                                                          "segments": Counter(), "asked": 0, "yes": 0, "maybe": 0,
                                                          "seen": 0, "clicks": 0, "leads": [], "pitched": 0, "pitch_yes": 0})
    for r in index:
        c = str(r.get("country")).strip()
        a = acc[c]
        a["people"] += 1
        a["weight"] += float(r.get("weight") or 1)
        if r.get("settlement"):
            a["settlement"][str(r["settlement"])] += 1
        if r.get("city"):
            city = str(r["city"]).strip()
            if c and city.lower().endswith(", " + c.lower()):     # "Bengaluru, India" and "Bengaluru" are one city
                city = city[: -len(c) - 2].strip()
            a["cities"][city] += 1
        if r.get("segment"):
            a["segments"][str(r["segment"])] += 1
        try:
            by_agent[int(r.get("agent_id"))] = c
        except (TypeError, ValueError):
            pass
    for r in (bundle.get("survey") or {}).get("responses") or []:
        ans, c = r.get("answer"), by_agent.get(r.get("agent_id"))
        if not ans or c is None:
            continue
        a = acc[c]
        a["asked"] += 1
        v = str(ans.get("would_convert") or "").lower()
        a["yes"] += v == "yes"
        a["maybe"] += v == "maybe"
    ft = bundle.get("feed_test") or {}
    first_seed = ft.get("seed")
    for s in ft.get("sessions") or []:
        if first_seed is not None and s.get("seed") not in (None, first_seed):
            continue
        c = by_agent.get(s.get("agent_id")) or s.get("country")
        if not c or c not in acc:
            continue
        ad = s.get("ad") or {}
        acc[c]["seen"] += 1
        acc[c]["clicks"] += bool(ad.get("click"))
    for p in (bundle.get("pitch") or {}).get("people") or []:
        c = by_agent.get(p.get("agent_id")) or p.get("country")
        if not c or c not in acc:
            continue
        acc[c]["pitched"] += 1
        acc[c]["pitch_yes"] += p.get("final_verdict") == "yes"
        if p.get("lead_score") is not None:
            acc[c]["leads"].append(float(p["lead_score"]))
    rows = []
    for c, a in acc.items():
        rows.append({"country": c, "geo": geo_name(c), "people": a["people"], "weight": round(a["weight"], 2),
                     "settlement": dict(a["settlement"]), "cities": a["cities"].most_common(6),
                     "segments": a["segments"].most_common(3), "asked": a["asked"],
                     "convert": _pct(a["yes"], a["asked"]), "maybe": _pct(a["maybe"], a["asked"]),
                     "ctr": _pct(a["clicks"], a["seen"]), "seen": a["seen"],
                     "lead": round(sum(a["leads"]) / len(a["leads"])) if a["leads"] else None,
                     "pitch": _pct(a["pitch_yes"], a["pitched"]), "pitched": a["pitched"]})
    rows.sort(key=lambda r: -r["people"])
    return rows


SETTLEMENT_ORDER = [("metro", "Metro", 1), ("city", "City", 3), ("town", "Town", 4), ("rural", "Rural", 6)]


def _mix_bar(mix: Dict[str, int]) -> str:
    total = sum(mix.values())
    if not total:
        return '<span class="muted small">–</span>'
    parts = "".join(f'<span style="width:{100 * mix.get(k, 0) / total:.1f}%;background:var(--s{slot})" '
                    f'title="{label}: {mix.get(k, 0)}"></span>' for k, label, slot in SETTLEMENT_ORDER if mix.get(k))
    return f'<span class="geo-mix" role="img" aria-label="settlement mix">{parts}</span>'


def _fmt(v: Any, unit: str = "") -> str:
    return "–" if v is None else (f"{v:g}{unit}" if isinstance(v, (int, float)) else str(v))


def map_section(bundle: Dict[str, Any], insight: Optional[str] = None) -> Optional[Tuple[str, str, str]]:
    """("worldmap", "Where they are", html) or None when nobody has a country."""
    rows = country_rows(bundle)
    if not rows:
        return None
    mapped = [r for r in rows if r["geo"]]
    metrics = [m for m in METRICS if m[0] == "people" or any(r.get(m[0]) is not None for r in rows)]
    spec = {"metrics": [{"key": k, "label": label, "unit": unit} for k, label, unit in metrics],
            "rows": [{"name": r["geo"], "country": r["country"], **{k: r.get(k) for k, _, _ in metrics},
                      "asked": r["asked"], "seen": r["seen"], "pitched": r["pitched"]} for r in mapped]}
    tabs = "".join(f'<button type="button" data-geo-metric="{k}" aria-pressed="{"true" if i == 0 else "false"}">{_e(label)}</button>'
                   for i, (k, label, _) in enumerate(metrics))
    chart = (f'<div class="ec geo-map" style="height:420px" data-kind="worldmap" role="img" '
             f'aria-label="World map of the simulated people by country" data-spec="{_e(json.dumps(spec, ensure_ascii=False))}"></div>')
    total = sum(r["people"] for r in rows)
    top = rows[0]
    best_conv = max((r for r in rows if r.get("convert") is not None and r["asked"] >= 5), key=lambda r: r["convert"], default=None)
    side = [ui.kpi(str(len(rows)), "Countries", f"{len(mapped)} on the map", color=3),
            ui.kpi(f"{100 * top['people'] / total:.0f}%", f"in {top['country']}", f"{top['people']} of {total} people", color=1,
                   bar=100 * top["people"] / total)]
    if best_conv:
        side.append(ui.kpi(f"{best_conv['convert']:g}%", f"would convert in {best_conv['country']}",
                           f"{best_conv['asked']} surveyed · highest of any country", color=6, bar=best_conv["convert"]))
    settle = Counter()
    for r in rows:
        settle.update(r["settlement"])
    if settle:
        side.append('<div class="kpi geo-legend"><div class="k">Where they live</div>' + _mix_bar(dict(settle))
                    + '<div class="geo-keys">' + "".join(f'<span><i style="background:var(--s{slot})"></i>{label} '
                                                          f'{100 * settle.get(k, 0) / sum(settle.values()):.0f}%</span>'
                                                          for k, label, slot in SETTLEMENT_ORDER if settle.get(k)) + "</div></div>")
    cols = [(k, label, unit) for k, label, unit in (("convert", "Would convert", "%"), ("ctr", "Ad CTR", "%"),
                                                    ("pitch", "Pitch yes", "%"), ("lead", "Lead", ""))
            if any(r.get(k) is not None for r in rows)]
    has_mix = any(r["settlement"] for r in rows)
    head = (['<th>Country</th>', '<th class="num">People</th>'] + [f'<th class="num">{label}</th>' for _, label, _ in cols]
            + (["<th>Where they live</th>"] if has_mix else []) + ["<th>Top cities</th>"])
    body = "".join(
        f'<tr><td>{_e(r["country"])}{"" if r["geo"] else " <span class=muted>(off map)</span>"}</td>'
        f'<td class="num">{r["people"]}</td>' + "".join(f'<td class="num">{_fmt(r.get(k), unit)}</td>' for k, _, unit in cols)
        + (f'<td>{_mix_bar(r["settlement"])}</td>' if has_mix else "")
        + f'<td class="small">{_e(", ".join(c for c, _ in r["cities"][:4]))}</td></tr>' for r in rows)
    table = (f'<div class="tbl"><table class="sortable"><thead><tr>{"".join(head)}</tr></thead><tbody>{body}</tbody></table></div>')
    html = (ui.section_head("Where they are", "Every simulated person by country. Switch the metric to see where the "
                            "offer lands; small countries (under 5 people) are directions, not results.", insight)
            + f'<div class="geo-grid"><div class="card geo-card"><div class="geo-tabs" role="group" aria-label="Map metric">{tabs}</div>'
            + chart + '</div><div class="geo-side">' + "".join(side) + "</div></div>"
            + f'<div class="card" style="margin-top:14px"><h3>By country</h3>{table}</div>')
    return ("worldmap", "Where they are", html)


def geo_payload() -> str:
    """<script type=application/json id=mm-geo> with the outlines (only when the map section renders)."""
    try:
        with open(GEO_PATH, encoding="utf-8") as f:
            data = f.read()
    except OSError:
        return ""
    return '<script type="application/json" id="mm-geo">' + data.replace("</", "<\\/") + "</script>"


GEO_CSS = """
.geo-grid{display:grid;grid-template-columns:minmax(0,1fr) 260px;gap:14px;align-items:start}
.geo-card{padding:12px 12px 4px}
.geo-side{display:grid;gap:10px}
.geo-tabs{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:6px}
.geo-tabs button{font:inherit;font-size:.8rem;padding:5px 12px;border-radius:var(--r-pill,999px);border:1px solid var(--border);
background:var(--surface);color:var(--text-2);cursor:pointer}
.geo-tabs button[aria-pressed="true"]{background:var(--text);color:var(--surface);border-color:var(--text)}
.geo-mix{display:flex;height:10px;border-radius:5px;overflow:hidden;min-width:90px;background:var(--grid)}
.geo-mix span{display:block;height:100%}
.geo-keys{display:flex;flex-wrap:wrap;gap:4px 10px;margin-top:8px;font-size:.78rem;color:var(--text-2)}
.geo-keys i{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:4px;vertical-align:-1px}
.geo-legend .k{margin-bottom:8px}
@media (max-width:560px){.geo-map{height:280px!important}}
@media (max-width:900px){.geo-grid{grid-template-columns:1fr}.geo-side{grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}}
"""

GEO_JS = r"""
(function(){if(!window.MM)return;var geo=null;
function load(){if(geo!==null)return geo;var el=document.getElementById('mm-geo');geo=false;
 if(el&&window.echarts){try{echarts.registerMap('world',JSON.parse(el.textContent));geo=true;}catch(e){}}return geo;}
window.MM.charts.worldmap=function(s,t){if(!load())return {title:{text:'Map outlines not included',textStyle:{color:t.muted,fontSize:12}}};
 var el=document.querySelector('.geo-map'),key=(el&&el.getAttribute('data-metric'))||s.metrics[0].key;
 var m=s.metrics.filter(function(x){return x.key===key;})[0]||s.metrics[0];
 var data=s.rows.map(function(r){return {name:r.name,value:r[m.key],row:r};}).filter(function(d){return d.value!=null;});
 var vals=data.map(function(d){return d.value;}),mx=vals.length?Math.max.apply(null,vals):1;
 var dark=t.dark;
 return {backgroundColor:'transparent',
  tooltip:{trigger:'item',confine:true,backgroundColor:t.card,borderColor:t.line,textStyle:{color:t.ink,fontSize:12},extraCssText:'border-radius:12px',
   formatter:function(p){var r=p.data&&p.data.row;if(!r)return p.name;var u=function(v,x){return v==null?'–':v+(x||'');};
    return '<b>'+r.country+'</b><br>'+r.people+' people'+(r.convert!=null?'<br>Would convert '+u(r.convert,'%')+' ('+r.asked+' asked)':'')
     +(r.ctr!=null?'<br>Ad CTR '+u(r.ctr,'%')+' ('+r.seen+' ad views)':'')+(r.pitch!=null?'<br>Pitch yes '+u(r.pitch,'%'):'')
     +(r.lead!=null?'<br>Lead score '+r.lead:'');}},
  visualMap:{min:0,max:mx||1,left:8,bottom:8,itemWidth:10,itemHeight:90,calculable:false,text:[(mx||0)+(m.unit||''),'0'],
   textStyle:{color:t.muted,fontSize:11},inRange:{color:dark?['#1d3350','#3987e5','#a9cdf7']:['#dbe9fb','#5d9be3','#1c5cab']}},
  series:[{type:'map',map:'world',roam:true,zoom:1.15,center:[20,15],scaleLimit:{min:1,max:8},data:data,
   itemStyle:{areaColor:dark?'#2a2a28':'#e8e7e2',borderColor:t.card,borderWidth:.6},
   emphasis:{label:{show:false},itemStyle:{areaColor:t.dark?'#f3d64b':'#eda100'}},select:{disabled:true}}]};};
document.querySelectorAll('.geo-tabs').forEach(function(tabs){tabs.addEventListener('click',function(ev){
 var b=ev.target.closest('button[data-geo-metric]');if(!b)return;ev.stopPropagation();
 tabs.querySelectorAll('button').forEach(function(x){x.setAttribute('aria-pressed',x===b?'true':'false');});
 var el=tabs.parentElement.querySelector('.geo-map');if(!el)return;el.setAttribute('data-metric',b.getAttribute('data-geo-metric'));
 if(el.__ec){var s=JSON.parse(el.getAttribute('data-spec'));el.__ec.setOption(window.MM.charts.worldmap(s,window.MM.theme()),true);}});});
})();
"""
