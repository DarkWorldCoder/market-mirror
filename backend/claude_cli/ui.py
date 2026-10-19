"""
ui.py - shared HTML helpers and the one page script for the MarketMirror dashboard.

Helpers (stdlib only, every value escaped unless wrapped in ``Raw``):
  esc, trunc, pct_ci, ci, low_n_pill, pill, kpi, section_head, table, PLATFORM_LABEL.

Scripts:
  HEAD_JS  - tiny pre-paint script for <head>: applies the saved theme before first paint.
  UI_JS    - appended once by the exporter, *before* the module scripts, and exposes
             ``window.MM`` (``css``, ``theme``, ``applyFilters``). It implements the sticky
             nav scrollspy, the theme switcher, delegated sortable tables, the generic
             filter root and the print behaviour for "Show the numbers" details. It also exposes
             ``MM.inflate(b64)`` (a Promise of the text packed by ``deflate_b64``) and ``MM.charts``, a
             registry other modules extend with chart builders (``kind`` -> function(spec, theme)).
"""

from __future__ import annotations

import base64
import html as _html
import math
import re
import zlib
from typing import Any, Dict, List, Optional, Sequence


class Raw(str):
    """A string that ``esc`` leaves untouched (already-safe HTML)."""


def esc(v: Any) -> str:
    if isinstance(v, Raw):
        return str(v)
    return _html.escape("" if v is None else str(v), quote=True)


def trunc(s: Any, n: int, collapse: bool = False) -> str:
    """Cut to n chars with an ellipsis. ``collapse`` folds whitespace runs (for tooltips)."""
    s = "" if s is None else str(s)
    if collapse:
        s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def ci(p_pct: Optional[float], n: int) -> Optional[float]:
    """95% margin of error (percentage points) for a proportion, Wilson-style floor for tiny n."""
    if p_pct is None or not n:
        return None
    p = max(min(p_pct / 100, 1), 0)
    return round(100 * 1.96 * math.sqrt(max(p * (1 - p), 0.25 / n) / n), 1)


def pct_ci(p: Optional[float], n: int, *, calibration_basis: Optional[str] = None) -> str:
    """A percentage; only show an interval where its calibration basis is supplied.

    Synthetic responses are correlated model outputs, so a binomial sample
    margin alone does not quantify real-world predictive uncertainty.
    """
    if p is None:
        return "–"
    m = ci(p, n) if calibration_basis else None
    return f"{p:.0f}%" + (f" ±{m:.0f}" if m is not None else "")


def low_n_pill(n: int, threshold: int = 10) -> str:
    return (f' <span class="pill orchid" title="Small sample: a direction, not a result">low n={n}</span>'
            if n < threshold else "")


def pill(text: Any, cls: str = "") -> str:
    """A rounded label; '' when the text is empty. cls: mint | accent | orchid | sky | neutral | pos | neg | neu."""
    if text in (None, ""):
        return ""
    return f'<span class="pill{" " + cls if cls else ""}">{esc(text)}</span>'


def kpi(value: Any, label: Any, hint: Any = None, delta: Any = None, hl: bool = False, cls: str = "",
        bar: Any = None, color: Any = None) -> str:
    """One KPI tile: big value, label, optional hint line and optional delta ('+3 pt' / '-2%').
    ``color`` (a palette slot 1-8 or a css value) tints the tile; ``bar`` (0-100) draws a small bar under it."""
    classes = "kpi" + (" hl" if hl else "") + (" c" if color is not None else "") + (f" {cls}" if cls else "")
    kc = f"var(--s{int(color)})" if isinstance(color, int) and not isinstance(color, bool) else color
    style = f' style="--kc:{esc(kc)}"' if kc else ""
    out = [f'<div class="{classes}"{style}><div class="v">{esc(value)}</div><div class="k">{esc(label)}</div>']
    if hint not in (None, ""):
        out.append(f'<div class="h">{esc(hint)}</div>')
    if delta not in (None, ""):
        d = str(delta).strip()
        direction = "down" if d.startswith(("-", "−", "↓")) else "up" if d.startswith(("+", "↑")) else ""
        out.append(f'<div class="d{" " + direction if direction else ""}">{esc(delta)}</div>')
    if bar is not None:
        try:
            w = max(0.0, min(100.0, float(bar)))
        except (TypeError, ValueError):
            w = 0.0
        out.append(f'<div class="bar" aria-hidden="true"><i style="width:{w:.1f}%"></i></div>')
    out.append("</div>")
    return "".join(out)


def deflate_b64(text: str) -> str:
    """zlib-compress text and base64 it: the page inflates it with ``window.MM.inflate`` (DecompressionStream)."""
    return base64.b64encode(zlib.compress(text.encode("utf-8"), 9)).decode("ascii")


def inflate_b64(data: str) -> str:
    return zlib.decompress(base64.b64decode(data)).decode("utf-8")


def section_head(title: Any, intro: Any = None, insight: Any = None, aside: Any = None) -> str:
    """<h2> plus optional intro line, the insight callout under it, and an optional aside (e.g. a button bar)."""
    text = f"<h2>{esc(title)}</h2>" + (f'<p class="intro muted small">{esc(intro)}</p>' if intro not in (None, "") else "")
    row = f'<div class="sh-row"><div class="sh-text">{text}</div>' + (f"{esc(aside)}" if aside not in (None, "") else "") + "</div>"
    call = f'<div class="callout insight" role="note">{esc(insight)}</div>' if insight not in (None, "") else ""
    return f'<div class="section-head">{row}{call}</div>'


_NUMERIC = re.compile(r"^\s*[+\-−–]?\s*(\d|\.\d)")


def _is_num(v: Any) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return True
    if v in (None, "", "–", "-"):
        return True
    return isinstance(v, str) and bool(_NUMERIC.match(v))


def table(head: Sequence[Any], rows: Sequence[Sequence[Any]], sortable: bool = True, summary: Optional[str] = None,
          num: Optional[Sequence[int]] = None, cls: str = "", tall: bool = False) -> str:
    """A table in a scrolling .tbl wrapper. Numeric columns (auto-detected, or given by index in ``num``) get
    ``td.num`` / ``th.num``. ``sortable`` adds class and the th attributes UI_JS uses. ``summary`` wraps it in a
    <details class="tv"> with that summary text ("Show the numbers"). Cells are escaped unless they are ``Raw``."""
    ncol = len(head)
    if num is None:
        num_cols = {i for i in range(ncol) if i > 0 and rows and all(_is_num(r[i]) if i < len(r) else True for r in rows)}
    else:
        num_cols = set(num)
    ths = []
    for i, h in enumerate(head):
        attrs = ' class="num"' if i in num_cols else ""
        if sortable:
            attrs += f' data-sort="{"num" if i in num_cols else "text"}" aria-sort="none" scope="col"'
        ths.append(f"<th{attrs}>{esc(h)}</th>")
    body = []
    for r in rows:
        cells = "".join(f'<td{" class=num" if i in num_cols else ""}>{esc(c)}</td>' for i, c in enumerate(r))
        body.append(f"<tr>{cells}</tr>")
    tcls = " ".join(c for c in (("sortable" if sortable else ""), cls) if c)
    out = (f'<div class="tbl{" tall" if tall else ""}"><table{" class=" + chr(34) + tcls + chr(34) if tcls else ""}>'
           f'<thead><tr>{"".join(ths)}</tr></thead><tbody>{"".join(body)}</tbody></table></div>')
    if summary:
        return f'<details class="tv"><summary>{esc(summary)}</summary>{out}</details>'
    return out


PLATFORM_LABEL: Dict[str, str] = {
    "facebook": "Facebook", "instagram": "Instagram", "reddit": "Reddit", "tiktok": "TikTok",
    "linkedin": "LinkedIn", "x": "X", "twitter": "X / Twitter",
}


# --------------------------------------------------------------------------
# Scripts
# --------------------------------------------------------------------------

# Runs in <head> before first paint: no flash when a theme was saved.
HEAD_JS = ("try{var t=localStorage.getItem('mm-theme');if(t==='dark'||t==='light')"
           "document.documentElement.setAttribute('data-theme',t);}catch(e){}")

UI_JS = r"""
(function(){
var doc=document.documentElement;
function css(n){return getComputedStyle(doc).getPropertyValue(n).trim();}
function isDark(){var t=doc.getAttribute('data-theme');if(t==='dark')return true;if(t==='light')return false;
 try{return matchMedia('(prefers-color-scheme: dark)').matches;}catch(e){return false;}}
function theme(){return {ink:css('--text'),ink2:css('--text-2'),muted:css('--muted'),grid:css('--grid'),axis:css('--axis'),
 card:css('--surface'),line:css('--border'),bar:css('--mm-ink-bar'),accent:css('--mm-accent'),accentInk:css('--mm-accent-ink'),
 yes:css('--mm-yes'),maybe:css('--mm-maybe'),no:css('--mm-no'),s:[css('--s1'),css('--s2'),css('--s3'),css('--s4')],
 seq:css('--mm-seq').split(',').map(function(x){return x.trim();}),font:getComputedStyle(document.body).fontFamily,dark:isDark()};}
/* theme switcher */
var tb=document.querySelector('[data-theme-toggle]');
function paintBtn(){if(!tb)return;var d=isDark();tb.textContent=d?'☀ Light':'☾ Dark';tb.setAttribute('aria-pressed',d?'true':'false');
 tb.setAttribute('aria-label',d?'Switch to light theme':'Switch to dark theme');}
if(tb){tb.addEventListener('click',function(){var next=isDark()?'light':'dark';doc.setAttribute('data-theme',next);
 try{localStorage.setItem('mm-theme',next);}catch(e){}paintBtn();});
 try{matchMedia('(prefers-color-scheme: dark)').addEventListener('change',paintBtn);}catch(e){}paintBtn();}
/* sticky nav scrollspy */
var nav=document.querySelector('nav[data-scrollspy]');
if(nav){var links=[],secs=[];nav.querySelectorAll('a[href^="#"]').forEach(function(a){var s=document.getElementById(a.getAttribute('href').slice(1));
  if(s){links.push(a);secs.push(s);}});
 var cur=null,ticking=false;
 function vertical(){return nav.offsetHeight>innerHeight*0.45;}
 function spy(){ticking=false;var line=vertical()?110:nav.getBoundingClientRect().bottom+24,best=0;
  for(var i=0;i<secs.length;i++){if(secs[i].getBoundingClientRect().top<=line)best=i;}
  if(innerHeight+scrollY>=doc.scrollHeight-2)best=secs.length-1;
  var a=links[best];if(!a||a===cur)return;links.forEach(function(x){x.removeAttribute('aria-current');});a.setAttribute('aria-current','true');cur=a;
  var r=a.getBoundingClientRect(),n=nav.getBoundingClientRect();
  if(vertical()){var box=nav.closest('aside')||nav,b=box.getBoundingClientRect();
   if(r.top<b.top+60||r.bottom>b.bottom-20)box.scrollTo({top:box.scrollTop+r.top-b.top-b.height/2,behavior:'smooth'});}
  else if(r.left<n.left||r.right>n.right)nav.scrollTo({left:nav.scrollLeft+r.left-n.left-16,behavior:'smooth'});}
 function onScroll(){if(!ticking){ticking=true;requestAnimationFrame(spy);}}
 if(secs.length){addEventListener('scroll',onScroll,{passive:true});addEventListener('resize',onScroll);spy();}}
/* delegated sortable tables */
function cellText(td){return td?td.textContent.trim():'';}
function cellNum(td){var t=cellText(td).replace(/[,\s]/g,'').replace('−','-').replace('–','-');var m=t.match(/^[-+]?\d*\.?\d+/);return m?parseFloat(m[0]):NaN;}
function sortTable(th){var table=th.closest('table'),tbody=table&&table.tBodies[0];if(!tbody)return;var idx=th.cellIndex;
 var rows=Array.prototype.slice.call(tbody.rows);
 var numeric=th.classList.contains('num')||th.getAttribute('data-sort')==='num'||rows.every(function(r){return !isNaN(cellNum(r.cells[idx]))||cellText(r.cells[idx])==='–';});
 var was=th.getAttribute('aria-sort'),dir=was==='ascending'?'descending':was==='descending'?'ascending':(numeric?'descending':'ascending');
 rows.forEach(function(r,i){r.__i=i;});
 rows.sort(function(a,b){var x,y;if(numeric){x=cellNum(a.cells[idx]);y=cellNum(b.cells[idx]);if(isNaN(x)&&isNaN(y))return a.__i-b.__i;if(isNaN(x))return 1;if(isNaN(y))return -1;}
  else{x=cellText(a.cells[idx]).toLowerCase();y=cellText(b.cells[idx]).toLowerCase();}
  var c=x<y?-1:x>y?1:a.__i-b.__i;return dir==='ascending'?c:-c;});
 rows.forEach(function(r){tbody.appendChild(r);});
 Array.prototype.forEach.call(table.querySelectorAll('thead th'),function(h){h.setAttribute('aria-sort','none');});th.setAttribute('aria-sort',dir);}
document.querySelectorAll('table.sortable thead th').forEach(function(th){th.tabIndex=0;th.setAttribute('role','button');
 if(!th.hasAttribute('aria-sort'))th.setAttribute('aria-sort','none');});
document.addEventListener('click',function(e){var th=e.target.closest&&e.target.closest('table.sortable thead th');if(th)sortTable(th);});
document.addEventListener('keydown',function(e){if(e.key!=='Enter'&&e.key!==' ')return;var th=e.target.closest&&e.target.closest('table.sortable thead th');if(th){e.preventDefault();sortTable(th);}});
/* generic filter root: [data-filter-root] > [data-filter=attr] controls, [data-item] children, [data-filter-count] */
function ctrlValue(c){if(c.tagName==='BUTTON')return null;if(c.type==='checkbox')return c.checked?'1':'';return c.value;}
function pressed(root,attr){var b=root.querySelector('button[data-filter="'+attr+'"][aria-pressed="true"]');return b?b.getAttribute('data-value'):null;}
function applyFilters(root){var ctrls=Array.prototype.slice.call(root.querySelectorAll('[data-filter]')),rules=[],seen={};
 ctrls.forEach(function(c){var attr=c.getAttribute('data-filter');if(c.tagName==='BUTTON'){if(seen[attr])return;seen[attr]=1;var v=pressed(root,attr);if(v!=null&&v!=='')rules.push({attr:attr,op:'eq',v:v});return;}
  var v=ctrlValue(c),any=c.getAttribute('data-filter-any');if(v===''||v==null||(any!=null&&v===any))return;
  if(c.type==='range'&&c.getAttribute('data-filter-op')==='min'&&c.min!==''&&parseFloat(v)<=parseFloat(c.min))return;
  rules.push({attr:attr,op:c.getAttribute('data-filter-op')||(c.type==='checkbox'?'truthy':'eq'),v:v});});
 var items=Array.prototype.slice.call(root.querySelectorAll('[data-item]')),shown=0,total=0;
 items.forEach(function(it){if(it.closest('[data-panel][hidden]'))return;total++;
  var ok=rules.every(function(r){var a=it.getAttribute('data-'+r.attr);if(a==null)a='';
   if(r.op==='eq')return a===r.v;if(r.op==='truthy')return a==='1'||a==='true';
   if(r.op==='min')return parseFloat(a)>=parseFloat(r.v);if(r.op==='max')return parseFloat(a)<=parseFloat(r.v);
   if(r.op==='has')return (' '+a+' ').indexOf(' '+r.v+' ')>=0;return true;});
  it.hidden=!ok;if(ok)shown++;});
 var sortC=root.querySelector('[data-filter-sort]');var key=sortC&&(sortC.type!=='checkbox'||sortC.checked)?sortC.getAttribute('data-filter-sort'):null;
 var parents=[];items.forEach(function(it){if(parents.indexOf(it.parentNode)<0)parents.push(it.parentNode);});
 parents.forEach(function(p){var kids=items.filter(function(it){return it.parentNode===p;});
  kids.sort(function(a,b){if(key){var d=parseFloat(b.getAttribute('data-'+key)||'0')-parseFloat(a.getAttribute('data-'+key)||'0');if(d)return d;}
   return parseFloat(a.getAttribute('data-order')||'0')-parseFloat(b.getAttribute('data-order')||'0');});kids.forEach(function(k){p.appendChild(k);});});
 var cnt=root.querySelector('[data-filter-count]');if(cnt)cnt.textContent=shown+' of '+total+' '+(root.getAttribute('data-filter-noun')||'items');
 root.querySelectorAll('[data-filter-out]').forEach(function(o){var c=root.querySelector('[data-filter="'+o.getAttribute('data-filter-out')+'"]');if(c)o.textContent=c.value;});
 try{root.dispatchEvent(new CustomEvent('mm:filter',{detail:{shown:shown,total:total}}));}catch(e){}return {shown:shown,total:total};}
document.querySelectorAll('[data-filter-root]').forEach(function(root){
 root.addEventListener('input',function(e){if(e.target.closest('[data-filter],[data-filter-sort]'))applyFilters(root);});
 root.addEventListener('change',function(e){if(e.target.closest('[data-filter],[data-filter-sort]'))applyFilters(root);});
 root.addEventListener('click',function(e){var b=e.target.closest('button[data-filter]');if(!b||!root.contains(b))return;
  var attr=b.getAttribute('data-filter');root.querySelectorAll('button[data-filter="'+attr+'"]').forEach(function(x){x.setAttribute('aria-pressed',x===b?'true':'false');});
  root.querySelectorAll('[data-panel]').forEach(function(p){if(p.getAttribute('data-panel-for')===attr||!p.hasAttribute('data-panel-for'))p.hidden=p.getAttribute('data-panel')!==b.getAttribute('data-value');});
  applyFilters(root);});
 applyFilters(root);});
/* print: open the "Show the numbers" details */
var opened=[];function beforePrint(){opened=[];document.querySelectorAll('details.tv:not([open])').forEach(function(d){d.open=true;opened.push(d);});}
function afterPrint(){opened.forEach(function(d){d.open=false;});opened=[];document.body.classList.remove('print-report');}
addEventListener('beforeprint',beforePrint);addEventListener('afterprint',afterPrint);
document.querySelectorAll('[data-print-report]').forEach(function(b){b.addEventListener('click',function(){document.body.classList.add('print-report');window.print();});});
/* packed payloads (downloads, replay events): zlib + base64 from ui.deflate_b64 */
function inflate(b64){return new Promise(function(res,rej){try{if(!window.DecompressionStream)return rej(new Error('no DecompressionStream'));
 var bin=atob(b64||''),u=new Uint8Array(bin.length);for(var i=0;i<bin.length;i++)u[i]=bin.charCodeAt(i);
 var ds=new DecompressionStream('deflate'),w=ds.writable.getWriter();w.write(u);w.close();
 new Response(ds.readable).text().then(res,rej);}catch(e){rej(e);}});}
window.MM={css:css,theme:theme,isDark:isDark,applyFilters:applyFilters,sortTable:sortTable,inflate:inflate,charts:{}};
})();
"""
