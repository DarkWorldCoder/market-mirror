"""
study.py - several scenarios x several seeds on the same simulated people, one defended conclusion.

    {"name": "fitloop_offer", "base": "market_test.json", "simulation_id": "sim_x",
     "scenarios": [{"name": "current", "overrides": {}},
                   {"name": "no_card", "overrides": {"survey": {"offer": "7-day trial, no card"}}},
                   {"name": "cheaper", "overrides": {"survey": {"offer": "... USD 2.99"}}}],
     "seeds": [1, 2, 3], "steps": ["feed_test", "rounds", "survey", "pitch"]}

Every cell (scenario x seed) is a normal `market-test` run in its own folder under mirofish_runs/<study>/,
reusing the people. Finished cells are skipped on rerun. `study_summary.json` holds, per scenario, the mean,
spread and 95% interval of every metric across seeds, the delta against the first scenario, how often each
scenario won, the decision agreement matrix and an exploratory ranking with seed agreement. Those intervals
describe simulation variation, not real-world uncertainty. `study_report.md` is one Claude call over that summary (number-guarded), with a
deterministic fallback. Stdlib only.
"""

from __future__ import annotations

import copy
import hashlib
import html
import json
import math
import os
import re
import shutil
import market_cli
from collections import Counter
from typing import Any, Callable, Dict, List, Optional

METRICS = [
    ("decision", "Decision", None),
    ("convert_yes", "Would convert (%)", "marketing.overall.convert_yes"),
    ("convert_maybe", "Maybe (%)", "marketing.overall.convert_maybe"),
    ("expected_convert_yes", "Expected convert (%)", "marketing.overall.expected_convert_yes"),
    ("intent", "Purchase intent (1-5)", "marketing.overall.ssr.purchase.mean"),
    ("trust", "Trust (0-10)", "marketing.overall.trust"),
    ("click_yes", "Would click (%)", "marketing.overall.click_yes"),
    ("best_expected_ctr", "Best ad expected CTR (%)", "feed.best_expected_ctr"),
    ("pitch_score", "Pitch score (0-100)", "pitch.pitch_score"),
    ("email_click_rate", "Best email click rate (%)", "email.best_click_rate"),
    ("top_objection_share", "Top objection share (%)", "marketing.objections.0.share"),
]
HIGHER_IS_BETTER = {"top_objection_share": False}


# --------------------------------------------------------------------------
# Spec and cells
# --------------------------------------------------------------------------

def normalize(spec: Dict[str, Any], base_dir: str) -> Dict[str, Any]:
    if not isinstance(spec, dict):
        raise ValueError("study spec must be a JSON object")
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", str(spec.get("name") or "study"))
    base = spec.get("base")
    if isinstance(base, str):
        path = base if os.path.isabs(base) else os.path.join(base_dir, base)
        with open(path, encoding="utf-8") as f:
            base_cfg = json.load(f)
        base_root = os.path.dirname(os.path.abspath(path))
    elif isinstance(base, dict):
        base_cfg, base_root = base, base_dir
    else:
        raise ValueError("study needs 'base': a market_test.json path or object")
    sid = spec.get("simulation_id") or base_cfg.get("simulation_id")
    if not sid:
        raise ValueError("study needs 'simulation_id' (reuse the same simulated people in every cell)")
    scenarios = [s for s in (spec.get("scenarios") or []) if isinstance(s, dict) and s.get("name")]
    if not scenarios:
        scenarios = [{"name": "base", "overrides": {}}]
    seeds = [int(x) for x in (spec.get("seeds") or [1])]
    steps = [str(x) for x in (spec.get("steps") or [])]
    return {"name": name, "base": base_cfg, "base_root": base_root, "simulation_id": sid, "scenarios": scenarios, "seeds": seeds,
            "steps": steps, "brand": spec.get("brand") or base_cfg.get("brand") or "", "report": spec.get("report", True)}


def _merge(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(a)
    for k, v in (b or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def cell_config(study: Dict[str, Any], scenario: Dict[str, Any], seed: int, study_root: str) -> Dict[str, Any]:
    """The market_test.json for one cell: base + scenario overrides, same people, own folder, this seed."""
    cfg = _merge(study["base"], scenario.get("overrides") or {})
    # Cell configs live in the study output folder. Preserve file references
    # relative to the original base config before writing each cell config.
    root = study["base_root"]
    def resolve(value: Any) -> Any:
        if isinstance(value, str):
            raw = value[1:] if value.startswith("@") else value
            path = raw if os.path.isabs(raw) else os.path.join(root, raw)
            return ("@" if value.startswith("@") else "") + os.path.abspath(path) if os.path.isfile(path) else value
        return value
    for key in ("creatives", "emails", "posts", "events", "personas", "research", "campaign_plan", "requirement"):
        if key in cfg:
            cfg[key] = resolve(cfg[key])
    for key in ("survey", "pitch"):
        if isinstance(cfg.get(key), dict):
            for child in (("messages",) if key == "survey" else ("script", "rebuttals")):
                if child in cfg[key]:
                    cfg[key][child] = resolve(cfg[key][child])
    cfg["simulation_id"] = study["simulation_id"]
    # every cell remembers only its own tests: a control cell never reads a treatment cell's memories
    # ("memory": false in the spec keeps behaviour memory off, e.g. to match cells run before it existed)
    cfg["memory_scope"] = ("off" if study.get("memory") is False
                           else f"{study.get('name') or 'study'}:{scenario.get('name') or 'base'}:s{seed}")
    cfg["approve_spend"] = True
    cfg["resume_steps"] = True
    cfg["study_cell"] = True
    cfg["graph_memory"] = False
    cfg["seed"] = seed
    cfg["name"] = f"{scenario['name']}-s{seed}"
    cfg["title"] = f"{study['name']}: {scenario['name']} (seed {seed})"
    cfg["out"] = os.path.abspath(os.path.join(study_root, f"{scenario['name']}-s{seed}"))
    cfg.pop("seeds", None)                      # documents are already uploaded: the people exist
    if study["steps"]:
        for key in ("creatives", "rounds", "survey", "pitch", "panel", "emails", "posts", "events"):
            step = {"creatives": "feed_test", "rounds": "rounds", "survey": "survey", "pitch": "pitch", "panel": "panel",
                    "emails": "email_test", "posts": "launch", "events": "launch"}[key]
            if step not in study["steps"]:
                cfg.pop(key, None)
        if "rounds" in study["steps"] and not cfg.get("rounds"):
            cfg["rounds"] = 3
    cfg["report"] = "report" in study["steps"] if study["steps"] else False
    cfg["understand"] = False                 # profile already exists on the reused simulation
    return cfg


def cell_dir(study_root: str, scenario: str, seed: int) -> str:
    return os.path.join(study_root, f"{scenario}-s{seed}")


def cell_done(path: str) -> bool:
    try:
        with open(os.path.join(path, "run_manifest.json"), encoding="utf-8") as f:
            manifest = json.load(f)
        if not manifest.get("finished_at"):
            return False
        for step in ("feed_test", "survey"):
            if manifest.get(step) and not market_cli.saved_step_usable(path, step):
                return False
        return True
    except (OSError, ValueError):
        return False


def _feed_signature(cfg: Dict[str, Any]) -> Optional[str]:
    creatives = cfg.get("creatives")
    if not creatives:
        return None
    if isinstance(creatives, str) and os.path.isfile(creatives):
        with open(creatives, "rb") as f:
            creatives = hashlib.sha256(f.read()).hexdigest()
    fields = {key: cfg.get(key) for key in ("simulation_id", "seed", "waves", "organic", "parallel", "exposures", "seeds_n")}
    fields["creatives"] = creatives
    return hashlib.sha256(json.dumps(fields, sort_keys=True, default=str).encode()).hexdigest()


def reuse_seed_feed_test(cfg: Dict[str, Any], path: str, prior_cells: List[Dict[str, Any]]) -> bool:
    """Use the same seed's identical feed exposure for paired survey scenarios."""
    signature = _feed_signature(cfg)
    if not signature or os.path.isfile(os.path.join(path, "feed_test.json")):
        return False
    for prior in prior_cells:
        source = prior["path"]
        try:
            with open(os.path.join(source, "market_test.json"), encoding="utf-8") as f:
                previous_cfg = json.load(f)
            with open(os.path.join(source, "run_manifest.json"), encoding="utf-8") as f:
                previous_manifest = json.load(f)
        except (OSError, ValueError):
            continue
        if signature != _feed_signature(previous_cfg) or not isinstance(previous_manifest.get("feed_test"), dict):
            continue
        source_file = os.path.join(source, "feed_test.json")
        if not market_cli.saved_step_usable(source, "feed_test"):
            continue
        os.makedirs(path, exist_ok=True)
        for filename in ("feed_test.json", "feed_test_sessions.csv", "feed_test_creatives.csv"):
            src = os.path.join(source, filename)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(path, filename))
        target_manifest = os.path.join(path, "run_manifest.json")
        try:
            with open(target_manifest, encoding="utf-8") as f:
                manifest = json.load(f)
        except (OSError, ValueError):
            manifest = {}
        manifest["simulation_id"] = cfg["simulation_id"]
        manifest["feed_test"] = {**previous_manifest["feed_test"], "feed_test": os.path.abspath(os.path.join(path, "feed_test.json")),
                                 "reused_from": os.path.abspath(source)}
        with open(target_manifest, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        return True
    return False


# --------------------------------------------------------------------------
# Metrics from a finished cell
# --------------------------------------------------------------------------

def _get(d: Any, dotted: str) -> Any:
    cur = d
    for part in dotted.split("."):
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def cell_metrics(path: str) -> Dict[str, Any]:
    """summary.json (+ feed_test / pitch / email_test) -> flat metrics for one cell."""
    def read(name):
        try:
            with open(os.path.join(path, name), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}
    s = read("summary.json")
    ft = read("feed_test.json")
    per = ((ft.get("summary") or {}).get("per_creative") or {})
    best_ctr = max((m.get("expected_ctr") or 0 for m in per.values()), default=None) if per else None
    et = read("email_test.json")
    pe = ((et.get("summary") or {}).get("per_email") or {})
    best_click = max((m.get("click_rate") or 0 for m in pe.values()), default=None) if pe else None
    source = {**s, "feed": {"best_expected_ctr": best_ctr, "winner": ((ft.get("summary") or {}).get("ranked") or [None])[0]},
              "pitch": read("pitch.json"), "email": {"best_click_rate": best_click}}
    out: Dict[str, Any] = {"decision": (s.get("decision") or {}).get("decision"), "confidence": (s.get("decision") or {}).get("confidence"),
                           "ad_winner": source["feed"]["winner"], "message_winner": _get(s, "marketing.messages_ranked.0.label"),
                           "top_objection": _get(s, "marketing.objections.0.label")}
    for key, _label, dotted in METRICS:
        if dotted:
            v = _get(source, dotted)
            out[key] = float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    return out


# --------------------------------------------------------------------------
# Aggregate
# --------------------------------------------------------------------------

def _stats(xs: List[float]) -> Dict[str, Any]:
    xs = [float(x) for x in xs if x is not None]
    if not xs:
        return {"n": 0, "mean": None, "min": None, "max": None, "sd": None, "ci95": None}
    m = sum(xs) / len(xs)
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) if len(xs) > 1 else 0.0
    return {"n": len(xs), "mean": round(m, 2), "min": round(min(xs), 2), "max": round(max(xs), 2), "sd": round(sd, 2),
            "ci95": round(1.96 * sd / math.sqrt(len(xs)), 2) if len(xs) > 1 else None}


def aggregate(study: Dict[str, Any], cells: List[Dict[str, Any]]) -> Dict[str, Any]:
    """cells: [{scenario, seed, path, metrics}] -> study_summary.json content."""
    by_sc: Dict[str, List[Dict[str, Any]]] = {}
    for c in cells:
        by_sc.setdefault(c["scenario"], []).append(c)
    order = [s["name"] for s in study["scenarios"] if s["name"] in by_sc]
    scenarios = []
    for name in order:
        rows = by_sc[name]
        met = {key: _stats([r["metrics"].get(key) for r in rows]) for key, _l, dotted in METRICS if dotted}
        decisions = Counter(r["metrics"].get("decision") for r in rows if r["metrics"].get("decision"))
        scenarios.append({"name": name, "cells": len(rows), "seeds": [r["seed"] for r in rows], "metrics": met,
                          "decisions": dict(decisions), "decision": decisions.most_common(1)[0][0] if decisions else None,
                          "decision_agreement_pct": round(100.0 * decisions.most_common(1)[0][1] / len(rows), 1) if decisions else None,
                          "ad_winners": dict(Counter(r["metrics"].get("ad_winner") for r in rows if r["metrics"].get("ad_winner"))),
                          "message_winners": dict(Counter(r["metrics"].get("message_winner") for r in rows if r["metrics"].get("message_winner"))),
                          "top_objections": dict(Counter(r["metrics"].get("top_objection") for r in rows if r["metrics"].get("top_objection")))})
    base = scenarios[0] if scenarios else None
    deltas = []
    for sc in scenarios[1:]:
        row = {"scenario": sc["name"], "vs": base["name"], "metrics": {}}
        for key, _l, dotted in METRICS:
            if not dotted:
                continue
            a, b = sc["metrics"][key], base["metrics"][key]
            if a["mean"] is None or b["mean"] is None:
                continue
            d = round(a["mean"] - b["mean"], 2)
            spread = ((a["ci95"] or 0) + (b["ci95"] or 0))
            better = d > 0 if HIGHER_IS_BETTER.get(key, True) else d < 0
            row["metrics"][key] = {"delta": d, "clear": abs(d) > spread and spread > 0, "better": better if d != 0 else None}
        deltas.append(row)
    # wins per seed on the headline metric (intent if available, else convert_yes)
    headline = "intent" if any(c["metrics"].get("intent") is not None for c in cells) else "convert_yes"
    wins: Counter = Counter()
    seeds = sorted({c["seed"] for c in cells})
    for seed in seeds:
        row = [(c["scenario"], c["metrics"].get(headline)) for c in cells if c["seed"] == seed and c["metrics"].get(headline) is not None]
        if row:
            wins[max(row, key=lambda x: x[1])[0]] += 1
    agreement = [{"seed": seed, **{c["scenario"]: c["metrics"].get("decision") for c in cells if c["seed"] == seed}} for seed in seeds]
    best = wins.most_common(1)[0][0] if wins else (base["name"] if base else None)
    best_sc = next((s for s in scenarios if s["name"] == best), None)
    stability = round(100.0 * wins[best] / len(seeds), 1) if wins and seeds else None
    conf = "high" if stability is not None and stability >= 99 and (best_sc or {}).get("decision_agreement_pct", 0) >= 99 and len(seeds) >= 3 \
        else "medium" if stability is not None and stability >= 66 else "low"
    conclusion = {"best_scenario": best, "headline_metric": headline, "wins_by_scenario": dict(wins), "stability_pct": stability,
                  "decision": (best_sc or {}).get("decision"), "confidence": conf,
                  "confidence_basis": "agreement across simulated seeds only",
                  "predictive_claim_supported": False, "evidence_status": "exploratory_simulation",
                  "text": _conclusion_text(scenarios, deltas, best, headline, stability, len(seeds), (best_sc or {}).get("decision"), conf)}
    return {"name": study["name"], "simulation_id": study["simulation_id"], "cells": [{k: v for k, v in c.items() if k != "metrics"} | {"metrics": c["metrics"]} for c in cells],
            "scenarios": scenarios, "deltas": deltas, "agreement": agreement, "conclusion": conclusion,
            "metric_labels": {k: l for k, l, _ in METRICS}}


def _conclusion_text(scenarios, deltas, best, headline, stability, n_seeds, decision, conf) -> str:
    if not scenarios:
        return "No finished cells yet."
    label = {k: l for k, l, _ in METRICS}.get(headline, headline)
    base = scenarios[0]["name"]
    parts = [f"{best} is the best scenario on {label.lower()}: it won in {stability}% of {n_seeds} seeds."]
    for d in deltas:
        if d["scenario"] == best and headline in d["metrics"]:
            m = d["metrics"][headline]
            parts.append(f"Against {base} it moved {label.lower()} by {m['delta']:+} ({'outside' if m['clear'] else 'inside'} the seed-to-seed spread).")
    if decision:
        parts.append(f"The simulated decision for {best} is {decision} ({conf} agreement across seeds).")
    return " ".join(parts)


# --------------------------------------------------------------------------
# Markdown + HTML
# --------------------------------------------------------------------------

def render_markdown(summary: Dict[str, Any], brand: str = "") -> str:
    labels = summary.get("metric_labels") or {}
    c = summary.get("conclusion") or {}
    out = [f"# {brand or summary.get('name')}: study of {len(summary.get('scenarios') or [])} scenarios x {len({x['seed'] for x in summary.get('cells') or []})} seeds", "",
           "**Evidence status: exploratory simulation.** Scenario rankings and seed spreads do not establish real-world lift or success probabilities.", "",
           f"**Scenario ranking: {str(c.get('decision') or '').upper()} with {c.get('best_scenario')}** ({c.get('confidence')} agreement across simulated seeds). {c.get('text')}", ""]
    keys = [k for k in labels if any(((s["metrics"].get(k) or {}).get("mean") is not None) for s in summary.get("scenarios") or [])]
    if keys:
        out += ["## Scenarios side by side", "", "| Metric | " + " | ".join(s["name"] for s in summary["scenarios"]) + " |",
                "|---|" + "---|" * len(summary["scenarios"])]
        for k in keys:
            cells = []
            for s in summary["scenarios"]:
                m = s["metrics"].get(k) or {}
                cells.append("–" if m.get("mean") is None else f"{m['mean']}" + (f" ± {m['ci95']}" if m.get("ci95") is not None else "") + (f" ({m['min']}–{m['max']})" if m.get("n", 0) > 1 else ""))
            out.append(f"| {labels[k]} | " + " | ".join(cells) + " |")
        out += [""]
        out += ["Decisions: " + "; ".join(f"{s['name']}: {s['decision']} ({s['decision_agreement_pct']}% of seeds)" for s in summary["scenarios"]), ""]
    if summary.get("deltas"):
        out += ["## Differences against the first scenario", ""]
        for d in summary["deltas"]:
            bits = [f"{labels.get(k, k)} {v['delta']:+}{' (clear)' if v['clear'] else ''}" for k, v in d["metrics"].items() if v["delta"] != 0]
            out += [f"- **{d['scenario']}** vs {d['vs']}: " + ("; ".join(bits) if bits else "no change")]
        out += [""]
    if summary.get("agreement"):
        names = [s["name"] for s in summary["scenarios"]]
        out += ["## Agreement across seeds", "", "| Seed | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
        out += [f"| {row['seed']} | " + " | ".join(str(row.get(n) or "–") for n in names) + " |" for row in summary["agreement"]] + [""]
    out += ["_Every cell is a separate simulation draw on the same simulated people. Spreads describe variation in these draws, not real-world uncertainty. Validate the preferred option in a controlled live test._", ""]
    return "\n".join(out)


LOWER_IS_BETTER = {"top_objection_share"}
CARD_METRICS = ["convert_yes", "intent", "trust", "click_yes", "top_objection_share"]
_TONE = {"go": "mint", "iterate": "accent", "no-go": "orchid"}

STUDY_CSS = """
:root{color-scheme:light;--bg:#eeeeea;--card:#fff;--sunk:#f6f6f3;--ink:#111;--ink2:#3d3d3a;--mut:#6b6b66;--line:#e8e7e2;
--panel:#121212;--panel-ink:#f2f2ee;--panel-mut:#9a9a93;--acc:#f3d64b;--accink:#2b2005;--mint:#cfefd9;--mintink:#0f3d22;
--orchid:#f1c6ee;--orchidink:#4a1a46;--pos:#184f95;--posbg:#e3effd;--neg:#9e2b2a;--negbg:#fde6e6}
@media (prefers-color-scheme:dark){:root{color-scheme:dark;--bg:#0d0d0c;--card:#171716;--sunk:#1f1f1d;--ink:#f2f2ee;--ink2:#c9c9c2;
--mut:#8f8f88;--line:#2a2a28;--panel:#000;--posbg:#1d3350;--pos:#a9cdf7;--negbg:#3f1d1d;--neg:#f2a5a5}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1240px;margin:0 auto;padding:28px 24px 64px}
.eyebrow{color:var(--mut);font-size:13px;margin:0 0 8px}
h1{font-size:clamp(2rem,4.4vw,3.4rem);line-height:.95;font-weight:500;letter-spacing:-.045em;text-transform:uppercase;margin:0 0 22px}
h2{font-size:1.35rem;font-weight:500;letter-spacing:-.025em;margin:34px 0 12px}
.hero{background:var(--panel);color:var(--panel-ink);border-radius:28px;padding:24px 26px}
.hero .k{color:var(--panel-mut);font-size:12px;letter-spacing:.08em;text-transform:uppercase}
.hero .big{font-size:clamp(1.3rem,2.4vw,1.8rem);font-weight:500;letter-spacing:-.02em;line-height:1.25;margin:10px 0 8px}
.hero p{margin:0;color:#d6d6d0;max-width:90ch}
.pill{display:inline-block;padding:3px 11px;border-radius:999px;font-size:12px;font-weight:600;background:var(--sunk);color:var(--ink2)}
.pill.accent{background:var(--acc);color:var(--accink)}.pill.mint{background:var(--mint);color:var(--mintink)}.pill.orchid{background:var(--orchid);color:var(--orchidink)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;margin-top:14px}
.sc{background:var(--card);border-radius:24px;padding:18px 20px;position:relative}
.sc.best{box-shadow:inset 0 0 0 2px var(--acc)}
.sc .best-tag{position:absolute;top:16px;right:16px;font-size:11px;font-weight:700;background:var(--acc);color:var(--accink);border-radius:999px;padding:2px 9px}
.sc h3{margin:0 0 8px;font-size:1.05rem;font-weight:600}
.sc dl{display:grid;grid-template-columns:1fr auto;gap:6px 12px;margin:14px 0 0;font-size:13px}
.sc dt{color:var(--ink2)}.sc dd{margin:0;text-align:right;font-variant-numeric:tabular-nums}.sc dd small{color:var(--mut)}
.sc dd.top{font-weight:700}
.card{background:var(--card);border-radius:24px;padding:18px 20px}
.study-table{overflow-x:auto;max-width:100%;-webkit-overflow-scrolling:touch}
table{width:100%;min-width:560px;border-collapse:collapse;font-size:13px}
th{text-align:left;font-weight:500;color:var(--mut);font-size:12px;padding:8px 12px;border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:9px 12px;border-bottom:1px solid var(--line);font-variant-numeric:tabular-nums}tr:last-child td{border-bottom:0}
td.top{font-weight:700}td small{color:var(--mut)}
.deltas{display:grid;gap:12px}
.delta h3{margin:0 0 10px;font-size:1rem;font-weight:600}.delta h3 span{color:var(--mut);font-weight:400}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{font-size:12px;padding:5px 10px;border-radius:999px;background:var(--sunk);color:var(--ink2)}
.chip.good{background:var(--posbg);color:var(--pos)}.chip.bad{background:var(--negbg);color:var(--neg)}
.chip b{font-weight:650}
.legend{color:var(--mut);font-size:12px;margin-top:10px}
.cells{display:flex;flex-wrap:wrap;gap:8px}
.cells a{padding:7px 14px;border-radius:999px;background:var(--card);color:var(--ink);text-decoration:none;font-size:13px}
.cells a:hover{background:var(--ink);color:var(--card)}
.note{color:var(--mut);font-size:12.5px;margin-top:28px;max-width:90ch}
@media (max-width:640px){.wrap{padding:16px 14px 40px}.hero{padding:18px}}
"""


def _pretty(name: Any) -> str:
    return str(name or "").replace("_", " ")


def _fmt_metric(m: Optional[Dict[str, Any]]) -> str:
    if not m or m.get("mean") is None:
        return "–"
    rng = f' <small>{m["min"]:g}–{m["max"]:g}</small>' if m.get("n", 0) > 1 and m.get("min") is not None else ""
    return f'{m["mean"]:g}{rng}'


def render_html(summary: Dict[str, Any], markdown_to_html: Callable[[str], str], css: str, brand: str = "", links: Optional[Dict[str, str]] = None) -> str:
    """The study page in the dashboard's look: conclusion, a card per scenario, the side-by-side table, differences
    against the first scenario, agreement across seeds, and links to every cell's dashboard. Self-contained."""
    e = lambda v: html.escape(str(v), quote=True)  # noqa: E731
    scenarios = summary.get("scenarios") or []
    labels = summary.get("metric_labels") or {}
    conc = summary.get("conclusion") or {}
    best = conc.get("best_scenario")
    seeds = sorted({c.get("seed") for c in summary.get("cells") or [] if c.get("seed") is not None})
    title = brand or summary.get("name") or "MarketMirror"
    metrics = [k for k in labels if any(((sc.get("metrics") or {}).get(k) or {}).get("mean") is not None for sc in scenarios)]

    def top_of(k: str) -> Optional[float]:
        vals = [((sc.get("metrics") or {}).get(k) or {}).get("mean") for sc in scenarios]
        vals = [v for v in vals if isinstance(v, (int, float))]
        if len(vals) < 2 or len(set(vals)) == 1:      # nothing to pick when every scenario has the same value
            return None
        return min(vals) if k in LOWER_IS_BETTER else max(vals)

    tops = {k: top_of(k) for k in metrics}
    hero = (f'<div class="hero"><div class="k">Conclusion · {e(conc.get("confidence") or "")} agreement across simulated seeds</div>'
            f'<div class="big">{e(_pretty(best) or "No clear winner")}'
            + (f' <span class="pill {_TONE.get(str(conc.get("decision")), "")}">{e(str(conc.get("decision") or "").upper())}</span>' if conc.get("decision") else "")
            + f'</div><p>{e(conc.get("text") or "")}</p></div>')
    cards = []
    for sc in scenarios:
        m = sc.get("metrics") or {}
        rows = "".join(f'<dt>{e(labels.get(k, k))}</dt><dd class="{"top" if tops.get(k) is not None and (m.get(k) or {}).get("mean") == tops[k] else ""}">'
                       f'{_fmt_metric(m.get(k))}</dd>' for k in CARD_METRICS if k in metrics)
        dec = str(sc.get("decision") or "")
        cards.append(f'<div class="sc{" best" if sc.get("name") == best else ""}">'
                     + ('<span class="best-tag">Best</span>' if sc.get("name") == best else "")
                     + f'<h3>{e(_pretty(sc.get("name")))}</h3><span class="pill {_TONE.get(dec, "")}">{e(dec or "–")}</span>'
                     f' <small style="color:var(--mut)">in {sc.get("decision_agreement_pct", "–")}% of seeds</small><dl>{rows}</dl></div>')
    head = "".join(f"<th>{e(_pretty(sc.get('name')))}</th>" for sc in scenarios)
    body = "".join("<tr><td>" + e(labels.get(k, k)) + "</td>" + "".join(
        f'<td class="{"top" if tops.get(k) is not None and ((sc.get("metrics") or {}).get(k) or {}).get("mean") == tops[k] else ""}">'
        f'{_fmt_metric((sc.get("metrics") or {}).get(k))}</td>' for sc in scenarios) + "</tr>" for k in metrics)
    table = f'<div class="card"><div class="study-table"><table><thead><tr><th>Metric</th>{head}</tr></thead><tbody>{body}</tbody></table></div></div>'
    deltas = []
    for d in summary.get("deltas") or []:
        chips = []
        for k, v in (d.get("metrics") or {}).items():
            if v.get("delta") is None:
                continue
            cls = ("good" if v.get("better") else "bad") if v.get("clear") and v.get("better") is not None else ""
            chips.append(f'<span class="chip {cls}">{e(labels.get(k, k))} <b>{v["delta"]:+g}</b>'
                         + ("" if v.get("clear") else " · within spread") + "</span>")
        deltas.append(f'<div class="card delta"><h3>{e(_pretty(d.get("scenario")))} <span>vs {e(_pretty(d.get("vs")))}</span></h3>'
                      f'<div class="chips">{"".join(chips)}</div></div>')
    agree_rows = "".join("<tr><td>Seed " + e(r.get("seed")) + "</td>" + "".join(
        f'<td><span class="pill {_TONE.get(str(r.get(sc.get("name"))), "")}">{e(r.get(sc.get("name")) or "–")}</span></td>' for sc in scenarios) + "</tr>"
        for r in summary.get("agreement") or [])
    agree = f'<div class="card"><div class="study-table"><table><thead><tr><th>Seed</th>{head}</tr></thead><tbody>{agree_rows}</tbody></table></div></div>'
    cells = "".join(f'<a href="{e(v)}">{e(_pretty(k))}</a>' for k, v in (links or {}).items()
                    if not str(v).lower().startswith(("javascript:", "data:")))
    page = (f'<p class="eyebrow">Study · {len(scenarios)} scenarios × {len(seeds)} seeds on the same simulated people</p>'
            f'<h1>{e(title)}: study</h1>{hero}<h2>The scenarios</h2><div class="cards">{"".join(cards)}</div>'
            f'<h2>Side by side</h2>{table}'
            + (f'<h2>What changed against {e(_pretty(scenarios[0].get("name")))}</h2><div class="deltas">{"".join(deltas)}</div>'
               '<p class="legend">Blue: a clear gain, red: a clear loss (outside the seed-to-seed spread). Grey: within the spread.</p>' if deltas and scenarios else "")
            + f'<h2>Decision in each seed</h2>{agree}'
            + (f'<h2>Every cell</h2><div class="cells">{cells}</div>' if cells else "")
            + '<p class="note"><b>Exploratory simulation.</b> Every cell is a separate simulation draw on the same simulated people. '
              'Means are across seeds with the lowest–highest seed shown small; spreads describe simulation variation, not real-world '
              'uncertainty. Validate the preferred option in a controlled live test.</p>')
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{e(title)}: study</title><style>{STUDY_CSS}</style></head><body><div class="wrap"><section id="study">{page}</section></div></body></html>')


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------

def run(study: Dict[str, Any], study_root: str, run_cell: Callable[[Dict[str, Any], str], Any], log: Callable[[str], None]) -> Dict[str, Any]:
    """run_cell(config, config_path) runs one market-test; finished cells are skipped."""
    os.makedirs(study_root, exist_ok=True)
    cells = []
    total = len(study["scenarios"]) * len(study["seeds"])
    k = 0
    for sc in study["scenarios"]:
        for seed in study["seeds"]:
            k += 1
            path = cell_dir(study_root, sc["name"], seed)
            cfg = cell_config(study, sc, seed, study_root)
            os.makedirs(path, exist_ok=True)
            cfg_path = os.path.join(path, "market_test.json")
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            if cell_done(path):
                log(f"study: cell {k}/{total} {sc['name']} seed {seed}: already done")
            else:
                if reuse_seed_feed_test(cfg, path, cells):
                    log(f"study: reused identical seed {seed} feed test for {sc['name']}")
                log(f"study: cell {k}/{total} {sc['name']} seed {seed}")
                run_cell(cfg, cfg_path)
            cells.append({"scenario": sc["name"], "seed": seed, "path": path, "metrics": cell_metrics(path)})
    summary = aggregate(study, cells)
    with open(os.path.join(study_root, "study_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    return summary
