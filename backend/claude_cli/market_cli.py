"""
market_cli.py - MarketMirror commands for mirofish.py (stdlib + requests only).

    feedtest    put ads into simulated Facebook/Instagram/Reddit/TikTok/LinkedIn/X feeds
    panel       independent, anonymized analyst panel over everything a run produced
    ads-import  turn a Meta / Google Ads export (CSV or JSON) into a seed file + real benchmarks
    backtest    compare simulated creative rankings with real ad results
"""

from __future__ import annotations

import base64
import csv
import io
import json
import math
import mimetypes
import os
import re
import time
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Tuple

import marketing


def saved_step_usable(path: str, step: str) -> bool:
    """Reject failed saved outputs when resuming a study or copying a seed."""
    try:
        with open(os.path.join(path, step + ".json"), encoding="utf-8") as f:
            data = json.load(f)
        if step == "survey":
            return any(r.get("answer") for r in data.get("responses") or [])
        live = (data.get("realism") or {}).get("llm_feed_calls") or 0
        return not (live and (data.get("failed") or 0) >= live)
    except (OSError, ValueError, TypeError):
        return False


def prune_unrequested_study_artifacts(path: str, config: Dict[str, Any]) -> None:
    """A reused simulation may have results from a different earlier campaign.

    Remove those snapshots from this cell, preserving backend originals and
    the evidence/inputs. Only requested steps can contribute to its report.
    """
    for name, requested in {"analyst_panel": config.get("panel"), "pitch": config.get("pitch"),
                            "email_test": config.get("emails"), "market_report": config.get("report"),
                            "report": config.get("engine_report") or config.get("report") == "upstream",
                            "feed_test": config.get("creatives"), "survey": config.get("survey")}.items():
        artifact = os.path.join(path, name + ".json")
        if not requested and os.path.isfile(artifact):
            os.remove(artifact)


def _load_json_arg(v: Optional[str]) -> Any:
    if not v:
        return None
    text = v
    if v.startswith("@"):
        with open(v[1:], encoding="utf-8") as f:
            text = f.read()
    return json.loads(text)


def _scope(c) -> Dict[str, Any]:
    """The client's behaviour-memory scope as a request field ({} = server default)."""
    scope = getattr(c, "memory_scope", None)
    return {"memory_scope": scope} if scope else {}


def _image_data_uri(path: str, base_dir: str) -> Optional[str]:
    full = path if os.path.isabs(path) else os.path.join(base_dir, path)
    if not os.path.isfile(full) or os.path.getsize(full) > 4_000_000:
        return None
    mime = mimetypes.guess_type(full)[0] or "image/png"
    if not mime.startswith("image/"):
        return None
    with open(full, "rb") as f:
        return f"data:{mime};base64,{base64.b64encode(f.read()).decode()}"


def wait_task(c, task_id: str, label: str, log: Callable[[str], None], interval: float = 5,
              timeout: float = 3600) -> Dict[str, Any]:
    start, last = time.time(), None
    while True:
        st = c.data("POST", "/api/simulation/market-task/status", json={"task_id": task_id})
        msg = f"{st.get('status')} {st.get('progress', 0)}% {st.get('message') or ''}".strip()
        if msg != last:
            log(f"{label}: {msg}")
            last = msg
        if st.get("status") == "completed":
            return st
        if st.get("status") == "failed":
            raise RuntimeError(f"{label} failed: {st.get('error') or st.get('message')}")
        if time.time() - start > timeout:
            raise RuntimeError(f"{label} timed out; the task keeps running server-side ({task_id})")
        time.sleep(interval)


# --------------------------------------------------------------------------
# feedtest
# --------------------------------------------------------------------------

def feedtest(c, simulation_id: str, spec_arg: str, out_dir: str, log, landing_arg: Optional[str] = None,
             bench_arg: Optional[str] = None, waves: int = 3, organic: int = 5, limit: Optional[int] = None,
             parallel: int = 8, exposures: int = 2, attention_gate: bool = True, seeds: int = 1, seed: int = 5) -> Dict[str, Any]:
    """seeds > 1 repeats the test with different seeds and reports each creative's mean and min-max range; seed = the base seed."""
    spec = _load_json_arg(spec_arg)
    base_dir = os.path.dirname(os.path.abspath(spec_arg[1:])) if spec_arg.startswith("@") else os.getcwd()
    if isinstance(spec, list):
        spec = {"creatives": spec}
    if not isinstance(spec, dict) or not spec.get("creatives"):
        raise ValueError("--creatives must be a JSON list of ads or {creatives, landing?, benchmarks?}")
    images = {}
    creatives = []
    for i, cr in enumerate(spec["creatives"]):
        cr = dict(cr)
        img = cr.pop("image", None)
        cr.setdefault("id", f"ad{i + 1}")
        if img:
            uri = img if str(img).startswith("data:image/") else _image_data_uri(str(img), base_dir)
            if uri:
                images[cr["id"]] = uri
            else:
                log(f"feedtest: image for {cr['id']} not found or too large, using the text description")
        creatives.append(cr)
    landing = _load_json_arg(landing_arg) if landing_arg else spec.get("landing")
    bench = _load_json_arg(bench_arg) if bench_arg else spec.get("benchmarks")
    if isinstance(bench, dict) and "benchmarks" in bench:
        bench = bench["benchmarks"]
    payload = {"simulation_id": simulation_id, "creatives": creatives, "waves": waves, "organic_per_feed": organic,
               "exposures": exposures, "attention_gate": attention_gate, "seeds": max(1, int(seeds or 1)), "seed": int(seed or 5),
               "parallel": parallel, **({"landing": landing} if landing else {}),
               **({"benchmarks": bench} if bench else {}), **({"max_personas": limit} if limit else {})}
    started = c.data("POST", "/api/simulation/feed-test", json={**payload, **_scope(c)}, timeout=120)
    log(f"feedtest: {started.get('feeds')} person-platform pairs x {exposures} exposures, {started.get('personas')} personas, "
        f"{started.get('creatives')} creatives, {waves} waves. Only exposures that catch the eye call Claude"
        + (", plus one call per click for the landing page" if landing else "")
        + (f". Repeated with {seeds} seeds: about {seeds}x the calls of one run" if seeds > 1 else ""))
    wait_task(c, started["task_id"], "feedtest", log)
    result = c.data("GET", f"/api/simulation/{simulation_id}/feed-test")
    log_cost(result, log)
    for cr in result.get("creatives") or []:
        if cr["id"] in images:
            cr["image"] = images[cr["id"]]
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "feed_test.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    out = {"feed_test": os.path.join(os.path.abspath(out_dir), "feed_test.json"),
           "personas": result.get("personas_tested"), "feeds": result.get("feeds"), "failed": result.get("failed"),
           "ranked": (result.get("summary") or {}).get("ranked"), "usage": result.get("usage")}
    ms = result.get("multi_seed")
    if ms:
        out["seeds"] = ms.get("seeds")
        out["winner_agreement"] = ms.get("winner_agreement")
        out["ranges"] = {cid: {k: [v["min"], v["max"]] for k, v in sp.items()
                               if v and k in ("expected_ctr", "thumb_stop", "engagement_rate")}
                         for cid, sp in (ms.get("spread") or {}).items()}
    return out


def _usage_txt(u: Dict[str, Any]) -> str:
    return (f"{u.get('calls', 0)} Claude calls, {u.get('input_tokens', 0):,} input / "
            f"{u.get('output_tokens', 0):,} output tokens")


def log_cost(result: Dict[str, Any], log) -> None:
    """One log line per seed plus the total, so the spend of a multi-seed run stays visible."""
    ms = result.get("multi_seed") or {}
    for i, ps in enumerate(ms.get("per_seed") or []):
        log(f"feedtest: seed {ps.get('seed')} ({i + 1}/{ms.get('n')}): {_usage_txt(ps.get('usage') or {})}")
    if result.get("usage"):
        log(f"feedtest: total cost {_usage_txt(result['usage'])}")
    if ms.get("winner_agreement") is not None:
        top = ((result.get("summary") or {}).get("ranked") or ["?"])[0]
        log(f"feedtest: {top} ranked first in {ms['winner_agreement']}% of {ms.get('n')} seeds")


# --------------------------------------------------------------------------
# panel
# --------------------------------------------------------------------------

def _rows(bundle: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    v = bundle.get(key)
    return v if isinstance(v, list) else []


def build_material(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """Anonymized: segment labels and text only, never persona names."""
    meta = marketing.agent_meta(bundle)

    def seg(uid) -> str:
        try:
            m = meta.get(int(uid)) or {}
        except (TypeError, ValueError):
            m = {}
        if m.get("kind") in ("graph", "community"):
            return "organisation or group account"
        return m.get("segment") or "unknown"

    material: Dict[str, Any] = {"posts": [], "comments": [], "feed_comments": [], "survey": []}
    for plat in ("reddit", "twitter"):
        for p in _rows(bundle, f"posts_{plat}"):
            if p.get("content"):
                material["posts"].append({"segment": seg(p.get("user_id")), "text": p["content"],
                                          "extra": f"{plat}, {p.get('num_likes', 0)} likes"})
        for cm in _rows(bundle, f"comments_{plat}"):
            if cm.get("content"):
                material["comments"].append({"segment": seg(cm.get("user_id")), "text": cm["content"]})
    ft = bundle.get("feed_test") or {}
    for s in ft.get("sessions") or []:
        ad = s.get("ad") or {}
        if ad.get("comment") or ad.get("thought"):
            material["feed_comments"].append({
                "segment": s.get("segment") or "unknown",
                "text": ad.get("comment") or f"(thought) {ad.get('thought')}",
                "extra": f"{s.get('platform')} ad {s.get('creative_id')}: "
                         + ", ".join(k for k in ("stopped", "click", "hide") if ad.get(k))})
    for r in (bundle.get("survey") or {}).get("responses") or []:
        a = r.get("answer") or {}
        if not a:
            continue
        m = meta.get(int(r.get("agent_id", -1))) or {}
        text = " ".join(t for t in (a.get("quote"), (a.get("texts") or {}).get("purchase")) if t) or a.get("main_objection")
        intent = ((a.get("ssr") or {}).get("purchase") or {}).get("mean")
        if text:
            material["survey"].append({"segment": m.get("segment") or "unknown", "text": text,
                                       "extra": (f"purchase intent {intent:.1f}/5" if intent is not None
                                                 else f"would convert: {a.get('would_convert')}")
                                                + f"; objection: {a.get('objection_type')}"})
    req = (bundle.get("project") or {}).get("simulation_requirement") or ""
    material["context"] = req[:3000]
    return material


def panel(c, simulation_id: str, run_dir: str, log, analysts: int = 5, brief: str = "",
          load_bundle: Callable[[str], Dict[str, Any]] = None) -> Dict[str, Any]:
    bundle = load_bundle(run_dir)
    material = build_material(bundle)
    counts = {k: len(v) for k, v in material.items() if isinstance(v, list)}
    if not sum(counts.values()):
        raise ValueError("nothing to analyse yet: run rounds, a survey or a feed test first")
    log(f"panel: {analysts} independent analysts reading {counts}")
    started = c.data("POST", "/api/simulation/analyst-panel",
                     json={"simulation_id": simulation_id, "material": material, "analysts": analysts, "brief": brief},
                     timeout=120)
    wait_task(c, started["task_id"], "panel", log)
    result = c.data("GET", f"/api/simulation/{simulation_id}/analyst-panel")
    with open(os.path.join(run_dir, "analyst_panel.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return {"analyst_panel": os.path.join(os.path.abspath(run_dir), "analyst_panel.json"),
            "consensus": (result.get("consensus") or {}).get("consensus"),
            "best_audience": ((result.get("consensus") or {}).get("best_audience") or {}).get("winner")}


# --------------------------------------------------------------------------
# report (plain-language, marketing-aware)
# --------------------------------------------------------------------------

def compact_material(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """Stdlib mirror of market_report.compact_material's inputs: the CLI sends the bundle's relevant parts and
    lets the backend compact them, so the two never drift."""
    keep = {}
    for k in ("summary", "project", "config", "feed_test", "survey", "analyst_panel", "feed_story"):
        v = bundle.get(k)
        if v:
            keep[k] = v
    if "summary" not in keep:
        try:
            with open(os.path.join(bundle.get("_run_dir", ""), "summary.json"), encoding="utf-8") as f:
                keep["summary"] = json.load(f)
        except (OSError, ValueError):
            pass
    return keep


def report(c, simulation_id: str, run_dir: str, log, load_bundle: Callable[[str], Dict[str, Any]] = None,
           brand: str = "") -> Dict[str, Any]:
    bundle = load_bundle(run_dir)
    bundle["_run_dir"] = run_dir
    material = compact_material(bundle)
    if "summary" not in material:
        raise ValueError("no summary.json yet: export the run first (or run a survey / feed test)")
    log("report: writing the plain-language report (one Claude call)")
    started = c.data("POST", "/api/simulation/market-report",
                     json={"simulation_id": simulation_id, "material": material, "brand": brand}, timeout=120)
    wait_task(c, started["task_id"], "report", log)
    result = c.data("GET", f"/api/simulation/{simulation_id}/market-report")
    with open(os.path.join(run_dir, "market_report.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    with open(os.path.join(run_dir, "market_report.md"), "w", encoding="utf-8") as f:
        f.write(result.get("markdown") or "")
    return {"market_report": os.path.join(os.path.abspath(run_dir), "market_report.md"),
            "method": result.get("method"), "decision": ((result.get("sections") or {}).get("executive_summary") or {}).get("decision"),
            "action_plan": result.get("action_plan")}


# --------------------------------------------------------------------------
# ads-import
# --------------------------------------------------------------------------

COLUMNS = {  # canonical -> header spellings in Meta Ads Manager / Google Ads exports (lowercased)
    "ad": ["ad name", "ad", "ad_name", "name", "headline"],
    "ad_set": ["ad set name", "ad group", "ad group name", "adset_name", "ad set"],
    "campaign": ["campaign name", "campaign", "campaign_name"],
    "platform": ["platform", "publisher platform", "network", "network (with search partners)"],
    "country": ["country", "region", "location"],
    "age": ["age"], "gender": ["gender"],
    "spend": ["amount spent", "amount spent (usd)", "cost", "spend", "amount_spent"],
    "impressions": ["impressions", "impr.", "impr"],
    "reach": ["reach"],
    "clicks": ["link clicks", "clicks", "link_click", "clicks (all)"],
    "lpv": ["landing page views", "website landing page views", "landing_page_view", "omni_landing_page_view"],
    "conversions": ["results", "conversions", "registrations completed", "omni_complete_registration",
                    "purchases", "leads", "all conv."],
}


def _num(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, dict):
        v = v.get("value")
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[^\d.\-]", "", str(v).replace(",", ""))
    try:
        return float(s) if s not in ("", "-", ".") else 0.0
    except ValueError:
        return 0.0


def _canon(row: Dict[str, Any]) -> Dict[str, Any]:
    low = {str(k).strip().lower(): v for k, v in row.items()}
    out = {}
    for key, names in COLUMNS.items():
        for n in names:
            if n in low and low[n] not in (None, ""):
                out[key] = low[n]
                break
        if key not in out:
            for k, v in low.items():
                if k.startswith(names[0]) and v not in (None, ""):
                    out[key] = v
                    break
    for k in ("spend", "impressions", "reach", "clicks", "lpv", "conversions"):
        out[k] = _num(out.get(k))
    for k in ("ad", "ad_set", "campaign", "platform", "country", "age", "gender"):
        if k in out:
            out[k] = str(out[k]).strip()
    return out


def read_ads(path: str) -> List[Dict[str, Any]]:
    with open(path, encoding="utf-8-sig") as f:
        text = f.read()
    if path.lower().endswith(".json") or text.lstrip().startswith(("[", "{")):
        data = json.loads(text)
        if isinstance(data, dict):
            data = data.get("ad_entities") or data.get("data") or data.get("rows") or []
            if isinstance(data, str):
                data = json.loads(data)
        rows = data
    else:
        sample = text[:4096]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        rows = list(csv.DictReader(io.StringIO(text), dialect=dialect))
    out = [_canon(r) for r in rows if isinstance(r, dict)]
    return [r for r in out if r["impressions"] or r["spend"] or r["clicks"]]


def _agg(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    s = {k: sum(r[k] for r in rows) for k in ("spend", "impressions", "clicks", "lpv", "conversions")}
    s["ctr"] = round(100 * s["clicks"] / s["impressions"], 2) if s["impressions"] else None
    s["cpm"] = round(1000 * s["spend"] / s["impressions"], 2) if s["impressions"] else None
    s["cpc"] = round(s["spend"] / s["clicks"], 3) if s["clicks"] else None
    s["lpv_rate"] = round(100 * s["lpv"] / s["clicks"], 1) if s["clicks"] and s["lpv"] else None
    s["conv_rate"] = round(100 * s["conversions"] / s["clicks"], 2) if s["clicks"] else None
    s["cpa"] = round(s["spend"] / s["conversions"], 2) if s["conversions"] else None
    return s


def summarize_ads(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    by: Dict[str, Dict[str, List[Dict[str, Any]]]] = {k: defaultdict(list) for k in ("ad", "ad_set", "campaign", "country", "platform")}
    for r in rows:
        for k in by:
            if r.get(k):
                by[k][r[k]].append(r)
    tables = {k: sorted([{"key": name, **_agg(rs)} for name, rs in groups.items()],
                        key=lambda x: (-(x["conversions"] or 0), x["cpa"] or 1e9))
              for k, groups in by.items() if groups}
    total = _agg(rows)
    bench = {"default": {"cpm": total["cpm"], "ctr": total["ctr"], "lpv_rate": total["lpv_rate"],
                         "conv_rate": total["conv_rate"]}}
    for p in tables.get("platform", []):
        bench[p["key"].lower()] = {"cpm": p["cpm"], "ctr": p["ctr"], "lpv_rate": p["lpv_rate"], "conv_rate": p["conv_rate"]}
    return {"total": total, "tables": tables, "benchmarks": bench, "rows": len(rows)}


def ads_markdown(summary: Dict[str, Any], title: str = "Past ad results") -> str:
    t = summary["total"]

    def f(v, suffix=""):
        return "–" if v is None else f"{v:,.2f}{suffix}" if isinstance(v, float) else f"{v}{suffix}"

    lines = [f"# {title}", "", "Real results imported from an ads export. Use them as ground truth for how each "
             "audience behaved, and as benchmarks for projections.", "",
             "| Spend | Impressions | Link clicks | CTR | CPM | Landing page views | Conversions | Cost per conversion |",
             "|---|---|---|---|---|---|---|---|",
             f"| {f(t['spend'])} | {int(t['impressions']):,} | {int(t['clicks']):,} | {f(t['ctr'], '%')} | {f(t['cpm'])} | "
             f"{int(t['lpv']):,} | {int(t['conversions'])} | {f(t['cpa'])} |", ""]
    if t.get("lpv_rate") is not None:
        lines += [f"Only {t['lpv_rate']:.0f}% of link clicks became a landing page view.", ""]
    labels = {"ad_set": "By ad set / audience", "ad": "By ad", "country": "By country", "platform": "By platform",
              "campaign": "By campaign"}
    for key in ("ad_set", "ad", "country", "platform", "campaign"):
        rows = summary["tables"].get(key) or []
        if len(rows) < 2 and key != "ad_set":
            continue
        lines += [f"## {labels[key]}", "", "| Name | Spend | Clicks | CTR | Conversions | Cost per conversion | Conv. per click |",
                  "|---|---|---|---|---|---|---|"]
        for r in rows[:25]:
            lines.append(f"| {r['key']} | {f(r['spend'])} | {int(r['clicks']):,} | {f(r['ctr'], '%')} | {int(r['conversions'])} | "
                         f"{f(r['cpa'])} | {f(r['conv_rate'], '%')} |")
        lines.append("")
    rows = [r for r in summary["tables"].get("ad_set") or summary["tables"].get("ad") or [] if r["clicks"] >= 20]
    if rows:
        best = min((r for r in rows if r["cpa"]), key=lambda r: r["cpa"], default=None)
        worst = max(rows, key=lambda r: (r["spend"] if not r["conversions"] else 0))
        lines += ["## What the data says", ""]
        if best:
            lines.append(f"- Cheapest conversions: **{best['key']}** at {f(best['cpa'])} each ({int(best['conversions'])} conversions).")
        if worst and not worst["conversions"]:
            lines.append(f"- Spent {f(worst['spend'])} on **{worst['key']}** with no conversions.")
        lines.append(f"- Total: {int(t['conversions'])} conversions from {int(t['clicks']):,} clicks. Small samples: treat as directions to test.")
    return "\n".join(lines) + "\n"


def ads_import(path: str, out_md: str, out_json: Optional[str] = None, title: str = "Past ad results") -> Dict[str, Any]:
    rows = read_ads(path)
    if not rows:
        raise ValueError(f"no ad rows with impressions, spend or clicks found in {path}")
    summary = summarize_ads(rows)
    os.makedirs(os.path.dirname(os.path.abspath(out_md)), exist_ok=True)
    with open(out_md, "w", encoding="utf-8") as f:
        f.write(ads_markdown(summary, title))
    out_json = out_json or os.path.splitext(out_md)[0] + ".json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    return {"seed": os.path.abspath(out_md), "json": os.path.abspath(out_json), "rows": summary["rows"],
            "benchmarks": summary["benchmarks"]}


# --------------------------------------------------------------------------
# backtest
# --------------------------------------------------------------------------

def _ranks(xs: List[float]) -> List[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(a: List[float], b: List[float]) -> Optional[float]:
    if len(a) < 3:
        return None
    ra, rb = _ranks(a), _ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return round(num / den, 2) if den else None


def kendall(a: List[float], b: List[float]) -> Optional[float]:
    n = len(a)
    if n < 3:
        return None
    conc = disc = 0
    for i in range(n):
        for j in range(i + 1, n):
            s = (a[i] - a[j]) * (b[i] - b[j])
            conc += s > 0
            disc += s < 0
    return round((conc - disc) / (n * (n - 1) / 2), 2)


def backtest(feed: Dict[str, Any], actual: Dict[str, Any], mapping: Dict[str, str]) -> Dict[str, Any]:
    """Compare simulated CTR per creative with the real CTR of the ad each creative mirrors."""
    per = (feed.get("summary") or {}).get("per_creative") or {}
    real_rows = {r["key"]: r for r in (actual.get("tables") or {}).get("ad", []) + (actual.get("tables") or {}).get("ad_set", [])}
    pairs = []
    for cr in feed.get("creatives") or []:
        real_name = mapping.get(cr["id"]) or cr.get("real_ad")
        if not real_name or real_name not in real_rows or cr["id"] not in per:
            continue
        r = real_rows[real_name]
        pairs.append({"creative": cr["id"], "real_ad": real_name, "sim_ctr": per[cr["id"]]["ctr"] or 0,
                      "real_ctr": r["ctr"] or 0, "sim_conv": ((per[cr["id"]].get("landing") or {}).get("conversion_rate")),
                      "real_conv_rate": r.get("conv_rate"), "real_clicks": int(r["clicks"]), "real_conversions": int(r["conversions"]),
                      "sources": r.get("sources") or [], "markets": r.get("markets") or [], "dates": r.get("dates") or [],
                      "quality": actual.get("quality") or "legacy_import_unverified"})
    if len(pairs) < 2:
        return {"pairs": pairs, "note": "need at least 2 creatives mapped to real ads (creative 'real_ad' field or --map id=Ad name)"}
    sim, real = [p["sim_ctr"] for p in pairs], [p["real_ctr"] for p in pairs]
    top_sim = max(pairs, key=lambda p: p["sim_ctr"])["creative"]
    top_real = max(pairs, key=lambda p: p["real_ctr"])["creative"]
    calib = round(sum(real) / sum(sim), 3) if sum(sim) else None
    small = [p["real_ad"] for p in pairs if p["real_clicks"] < 100]
    return {"pairs": pairs, "n": len(pairs), "spearman": spearman(sim, real), "kendall_tau": kendall(sim, real),
            "top1_match": top_sim == top_real, "top_sim": top_sim, "top_real": top_real, "ctr_calibration": calib,
            "warnings": ([f"real ads with under 100 clicks are noisy: {', '.join(small)}"] if small else [])
            + (["fewer than 5 pairs: rank agreement is only indicative"] if len(pairs) < 5 else [])}


# --------------------------------------------------------------------------
# pitch (sales rehearsal) and ideas (next tests from real ads + runs)
# --------------------------------------------------------------------------

def pitch(c, simulation_id: str, run_dir: str, log, script: str, rebuttals: Any = None, product: str = "",
          channel: str = "message", segment: Optional[str] = None, agents: Optional[List[int]] = None,
          batch: int = 40) -> Dict[str, Any]:
    """Pitch every simulated buyer (needs a live simulation environment), then answer their objections."""
    if not str(script or "").strip():
        raise ValueError("pitch: the script is empty")
    body = {"simulation_id": simulation_id, "script": script, "rebuttals": rebuttals, "product": product,
            "channel": channel, "batch": batch}
    if segment:
        body["segment"] = segment
    if agents:
        body["agents"] = agents
    started = c.data("POST", "/api/simulation/pitch", json={**body, **_scope(c)}, timeout=120)
    log(f"pitch: {started.get('people')} people, rebuttals for {started.get('rebuttals') or 'nothing'}")
    wait_task(c, started["task_id"], "pitch", log)
    result = c.data("GET", f"/api/simulation/{simulation_id}/pitch")
    with open(os.path.join(run_dir, "pitch.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return {"pitch": os.path.join(os.path.abspath(run_dir), "pitch.json"), "answered": result.get("answered"),
            "pitch_score": result.get("pitch_score"), "verdict_after": result.get("verdict_after"),
            "fixes": result.get("fixes"), "hot_leads": len(result.get("hot_leads") or [])}


def ideas(c, run_dir: Optional[str], log, ads_path: Optional[str] = None, ads_rows: Optional[List[Dict[str, Any]]] = None,
          brand: str = "", brief: str = "", n: int = 8, out: Optional[str] = None,
          profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Next tests from real ad results (export file or rows from a connected ads tool) and a run's summary."""
    rows = list(ads_rows or [])
    if ads_path:
        rows += read_ads(ads_path)
    run_summary: Dict[str, Any] = {}
    if run_dir:
        try:
            with open(os.path.join(run_dir, "summary.json"), encoding="utf-8") as f:
                run_summary = json.load(f)
        except (OSError, ValueError):
            log(f"ideas: no summary.json in {run_dir}; using the ads only")
        try:
            with open(os.path.join(run_dir, "feed_test.json"), encoding="utf-8") as f:
                ft = json.load(f)
            try:
                with open(os.path.join(run_dir, "research.json"), encoding="utf-8") as f:
                    run_summary["research"] = {"summary": (json.load(f).get("summary") or {})}
            except (OSError, ValueError):
                pass
            run_summary["feed_test"] = {"per_creative": {k: {kk: v.get(kk) for kk in ("expected_ctr", "hide_rate", "projection")}
                                                         for k, v in ((ft.get("summary") or {}).get("per_creative") or {}).items()}}
        except (OSError, ValueError):
            pass
    if not rows and not run_summary:
        raise ValueError("ideas: give --ads (export file), --rows (JSON) or --run-dir with a summary.json")
    log(f"ideas: {len(rows)} ad rows, run summary {'yes' if run_summary else 'no'}")
    data = c.data("POST", "/api/simulation/ideas",
                  json={"brand": brand or (profile or {}).get("name") or "", "brief": brief, "ads": rows[:2000],
                        "run_summary": run_summary, "n": n, "profile": profile}, timeout=300)
    out_json = out or os.path.join(run_dir or ".", "ideas.json")
    os.makedirs(os.path.dirname(os.path.abspath(out_json)), exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    out_md = os.path.splitext(out_json)[0] + ".md"
    with open(out_md, "w", encoding="utf-8") as f:
        f.write(data.get("markdown") or "")
    return {"ideas": os.path.abspath(out_json), "markdown": os.path.abspath(out_md), "method": data.get("method"),
            "count": len(data.get("ideas") or []),
            "titles": [f"{i.get('title')} ({i.get('type')}, {i.get('priority')})" for i in data.get("ideas") or []]}


# --------------------------------------------------------------------------
# emailtest
# --------------------------------------------------------------------------

def emailtest(c, simulation_id: str, spec_arg: str, run_dir: str, log, seed: int = 5, parallel: int = 8,
              list_size: Optional[int] = None, limit: Optional[int] = None) -> Dict[str, Any]:
    """Subject lines, senders, send times and sequences in the simulated people's inboxes."""
    spec = _load_json_arg(spec_arg)
    body: Dict[str, Any] = {"simulation_id": simulation_id, "emails": spec, "seed": seed, "parallel": parallel}
    if list_size:
        body["list_size"] = list_size
    if limit:
        body["max_personas"] = limit
    started = c.data("POST", "/api/simulation/email-test", json={**body, **_scope(c)}, timeout=120)
    log(f"emailtest: {started.get('emails')} emails to {started.get('people')} inboxes; only opened mail calls Claude")
    wait_task(c, started["task_id"], "emailtest", log)
    result = c.data("GET", f"/api/simulation/{simulation_id}/email-test")
    with open(os.path.join(run_dir, "email_test.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    summ = result.get("summary") or {}
    log_cost(result, log)
    return {"email_test": os.path.join(os.path.abspath(run_dir), "email_test.json"), "ranked": summ.get("ranked"),
            "subject_lines": summ.get("subject_lines"), "lost_to_unsubscribe_or_spam": summ.get("lost_to_unsubscribe_or_spam"),
            "warnings": {k: v.get("warnings") for k, v in (summ.get("per_email") or {}).items() if v.get("warnings")}}
