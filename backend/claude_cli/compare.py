"""
compare.py - the same market test run by different model providers, side by side.

Each run is a full MarketMirror run folder (its own simulated people, written and answered by one provider). The
comparison shows each run's headline results with 95% ranges and marks where the runs agree: the decision, the
top objection, the best message, the best audience, the country order, and whether the would-convert ranges
overlap. Agreement across providers is a robustness check on the simulation, not evidence about real buyers.
Stdlib only.
"""

from __future__ import annotations

import html
import json
import math
import os
from typing import Any, Dict, List, Optional, Tuple

try:  # stdlib only
    import study as _study  # type: ignore
except ImportError:  # pragma: no cover
    from . import study as _study  # type: ignore


def _load(run_dir: str, name: str) -> Any:
    try:
        with open(os.path.join(run_dir, name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _wilson(pct: Optional[float], n: int, z: float = 1.96) -> Dict[str, Any]:
    if pct is None or not n:
        return {"pct": pct, "lo": None, "hi": None, "n": n}
    p = pct / 100.0
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return {"pct": round(pct, 1), "lo": round(100 * max(0.0, c - h), 1), "hi": round(100 * min(1.0, c + h), 1), "n": n}


def _best(rows: List[Dict[str, Any]], key: str, min_n: int = 20) -> Optional[str]:
    rows = [r for r in rows or [] if (r.get("n") or 0) >= min_n and r.get(key) is not None]
    return max(rows, key=lambda r: r[key])["key"] if rows else None


def run_summary(label: str, run_dir: str) -> Dict[str, Any]:
    s = _load(run_dir, "summary.json") or {}
    m = s.get("marketing") or {}
    o = m.get("overall") or {}
    n = int(o.get("n") or 0)
    ssr = o.get("ssr") or {}
    objs = m.get("objections") or []
    msgs = m.get("messages_ranked") or []
    pr = m.get("pricing") or {}
    manifest = _load(run_dir, "run_manifest.json") or {}
    countries = sorted([r for r in m.get("by_country") or [] if (r.get("n") or 0) >= 20], key=lambda r: -(r.get("convert_yes") or 0))
    return {
        "label": label, "run_dir": os.path.abspath(run_dir), "title": manifest.get("title"),
        "people": m.get("people"), "answered": m.get("answered"),
        "decision": (s.get("decision") or {}).get("decision"), "confidence": (s.get("decision") or {}).get("confidence"),
        "convert_yes": _wilson(o.get("convert_yes"), n), "convert_maybe": _wilson(o.get("convert_maybe"), n),
        "convert_no": _wilson(o.get("convert_no"), n), "click_yes": _wilson(o.get("click_yes"), n),
        "intent": ssr.get("purchase"), "trust": ssr.get("trust"),
        "top_objection": {"label": objs[0].get("label"), "share": objs[0].get("share")} if objs else None,
        "best_message": msgs[0].get("label") if msgs else None,
        "best_audience": _best(m.get("by_segment") or [], "convert_yes"),
        "country_order": [r["key"] for r in countries],
        "by_country": {r["key"]: _wilson(r.get("convert_yes"), int(r.get("n") or 0)) for r in countries},
        "price_range": [pr.get("acceptable_low"), pr.get("acceptable_high")] if pr.get("acceptable_low") is not None else None,
        "price_sweet_spot": pr.get("optimal"),
        "retest_agreement": (m.get("retest") or {}).get("agreement_pct"),
    }


def _overlap(a: Dict[str, Any], b: Dict[str, Any]) -> Optional[bool]:
    if None in (a.get("lo"), a.get("hi"), b.get("lo"), b.get("hi")):
        return None
    return not (a["hi"] < b["lo"] or b["hi"] < a["lo"])


def build(runs: List[Tuple[str, str]]) -> Dict[str, Any]:
    rows = [run_summary(label, d) for label, d in runs]
    def same(key):
        vals = [r.get(key) for r in rows if r.get(key) not in (None, [], "")]
        return {"agree": len(set(map(str, vals))) == 1 and len(vals) == len(rows), "values": {r["label"]: r.get(key) for r in rows}}
    pairs = [(a["label"], b["label"], _overlap(a["convert_yes"], b["convert_yes"])) for i, a in enumerate(rows) for b in rows[i + 1:]]
    agree = {
        "decision": same("decision"),
        "top_objection": {"agree": len({(r.get("top_objection") or {}).get("label") for r in rows}) == 1,
                          "values": {r["label"]: (r.get("top_objection") or {}).get("label") for r in rows}},
        "best_message": same("best_message"), "best_audience": same("best_audience"),
        "country_order": same("country_order"),
        "would_convert_ranges_overlap": {"agree": all(p[2] for p in pairs if p[2] is not None) if pairs else None,
                                         "pairs": [{"a": a, "b": b, "overlap": ov} for a, b, ov in pairs]},
    }
    total = sum((r["convert_yes"].get("n") or 0) for r in rows)
    pooled = (sum((r["convert_yes"]["pct"] or 0) * (r["convert_yes"]["n"] or 0) for r in rows) / total) if total else None
    checks = [v["agree"] for v in agree.values() if v.get("agree") is not None]
    return {"runs": rows, "agreement": agree, "agreement_score": f"{sum(checks)} of {len(checks)}",
            "pooled_convert_yes": _wilson(round(pooled, 2) if pooled is not None else None, total),
            "note": "Each run's people were written and answered by one provider. Agreement across providers is a robustness "
                    "check on the simulation, not evidence about real buyers."}


def _w(w: Optional[Dict[str, Any]]) -> str:
    if not w or w.get("pct") is None:
        return "–"
    return f"{w['pct']:g}%" + (f" <small>{w['lo']:g}–{w['hi']:g}</small>" if w.get("lo") is not None else "")


def render_html(comp: Dict[str, Any], title: str = "Provider comparison") -> str:
    e = lambda v: html.escape(str(v if v is not None else "–"), quote=True)  # noqa: E731
    runs = comp["runs"]
    head = "".join(f"<th>{e(r['label'])}</th>" for r in runs)

    def row(label: str, cells: List[str]) -> str:
        return f"<tr><td>{e(label)}</td>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"
    def ssr(x):
        return "–" if not x else f"{x.get('mean'):g} <small>±{x.get('sd'):g}</small>"
    table = "".join([
        row("Simulated people", [e(r.get("people")) for r in runs]),
        row("Answered the survey", [e(r.get("answered")) for r in runs]),
        row("Decision", [f'<span class="pill {dict(go="mint", iterate="accent").get(str(r.get("decision")), "orchid")}">{e(r.get("decision"))}</span>' for r in runs]),
        row("Would start (yes)", [_w(r["convert_yes"]) for r in runs]),
        row("Maybe", [_w(r["convert_maybe"]) for r in runs]),
        row("No", [_w(r["convert_no"]) for r in runs]),
        row("Would click", [_w(r["click_yes"]) for r in runs]),
        row("Purchase intent (1–5)", [ssr(r.get("intent")) for r in runs]),
        row("Trust (1–5)", [ssr(r.get("trust")) for r in runs]),
        row("Top objection", [f"{e((r.get('top_objection') or {}).get('label'))} <small>{e((r.get('top_objection') or {}).get('share'))}%</small>" for r in runs]),
        row("Best message", [e(r.get("best_message")) for r in runs]),
        row("Best audience", [e(r.get("best_audience")) for r in runs]),
        row("Countries, most willing first", [e(", ".join(r.get("country_order") or [])) for r in runs]),
        row("Acceptable price", [e("–" if not r.get("price_range") else f"{r['price_range'][0]}–{r['price_range'][1]}, sweet spot {r.get('price_sweet_spot')}") for r in runs]),
        row("Same answer a week later", [e(f"{r['retest_agreement']}%" if r.get("retest_agreement") is not None else "–") for r in runs]),
    ])
    names = {"decision": "Decision", "top_objection": "Top objection", "best_message": "Best message", "best_audience": "Best audience",
             "country_order": "Country order", "would_convert_ranges_overlap": "Would-start ranges overlap"}
    chips = "".join(f'<span class="chip {"good" if v.get("agree") else "bad" if v.get("agree") is False else ""}">{e(names[k])}: '
                    f'<b>{"agree" if v.get("agree") else "differ" if v.get("agree") is False else "not enough data"}</b></span>'
                    for k, v in comp["agreement"].items())
    pooled = comp.get("pooled_convert_yes") or {}
    body = (f'<p class="eyebrow">Same market test · {len(runs)} providers · each wrote and answered its own simulated people</p>'
            f"<h1>{e(title)}</h1>"
            f'<div class="hero"><div class="k">Agreement across providers</div><div class="big">{e(comp["agreement_score"])} checks agree</div>'
            f'<p>All runs together: {_w(pooled)} would start, out of {e(pooled.get("n"))} answers. {e(comp["note"])}</p></div>'
            f'<h2>Where they agree</h2><div class="chips">{chips}</div>'
            f'<h2>Side by side</h2><div class="card"><div class="study-table"><table><thead><tr><th>Measure</th>{head}</tr></thead>'
            f"<tbody>{table}</tbody></table></div></div>"
            '<p class="note">Percentages show the share of simulated people with a 95% range. Different providers write different '
            "people, so differences reflect both the model and its population.</p>")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{e(title)}</title><style>{_study.STUDY_CSS}</style></head><body><div class=\"wrap\">{body}</div></body></html>")


def write(runs: List[Tuple[str, str]], out_dir: str, title: str = "Provider comparison") -> Dict[str, str]:
    comp = build(runs)
    os.makedirs(out_dir, exist_ok=True)
    jp, hp = os.path.join(out_dir, "comparison.json"), os.path.join(out_dir, "comparison.html")
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(comp, f, ensure_ascii=False, indent=2)
    with open(hp, "w", encoding="utf-8") as f:
        f.write(render_html(comp, title))
    return {"json": os.path.abspath(jp), "html": os.path.abspath(hp), "agreement": comp["agreement_score"]}
