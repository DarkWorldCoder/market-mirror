#!/usr/bin/env python3
"""
MarketMirror MCP server (stdio or authenticated loopback HTTP, stdlib only).

Exposes MarketMirror as tools for any MCP client. It wraps mm.sh,
so it works before the engine is installed: call `setup` first. Long work (setup, market tests,
surveys, feed tests) runs as background jobs; poll `job_status`.

Register (Claude Code):  claude mcp add market-mirror -- python3 /path/to/mcp_server.py
The plugin registers it automatically.
"""

from __future__ import annotations

import json
import argparse
import hmac
import os
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
MM = os.path.join(HERE, "mm.sh")
PROTOCOL = "2025-03-26"
SUPPORTED_PROTOCOLS = {"2024-11-05", "2025-03-26", "2025-06-18"}
JOBS: Dict[str, Dict[str, Any]] = {}
LIVE: Dict[str, Any] = {}


def sh(args: List[str], timeout: float = 120) -> Dict[str, Any]:
    try:
        p = subprocess.run(["bash", MM, *args], capture_output=True, text=True, timeout=timeout)
        return {"ok": p.returncode == 0, "stdout": p.stdout[-20000:], "stderr": p.stderr[-6000:]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": f"timed out after {timeout}s"}


def _cli_result(result: Dict[str, Any]) -> Dict[str, Any]:
    try:
        data = json.loads(result.get("stdout") or "{}")
    except ValueError:
        data = {"message": (result.get("stdout") or "")[-4000:]}
    if not result["ok"]:
        raise ValueError(data.get("error") or result.get("stderr") or "CLI command failed")
    return data


def home() -> str:
    return sh(["home"])["stdout"].strip()


def job(args: List[str], label: str) -> Dict[str, Any]:
    jid = uuid.uuid4().hex[:10]
    logdir = os.path.join(os.path.expanduser("~"), ".market-mirror", "jobs")
    os.makedirs(logdir, exist_ok=True)
    log_path = os.path.join(logdir, f"{jid}.log")
    out_path = os.path.join(logdir, f"{jid}.out")
    meta_path = os.path.join(logdir, f"{jid}.json")
    started = time.time()
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({"id": jid, "label": label, "args": args, "log": log_path, "out": out_path,
                   "started": started, "status": "running"}, f)
    proc = subprocess.Popen([sys.executable, os.path.join(HERE, "job_worker.py"), MM, meta_path, out_path, log_path, *args],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    JOBS[jid] = {"id": jid, "label": label, "args": args, "proc": proc, "log": log_path, "out": out_path,
                 "started": started, "meta": meta_path}
    return {"job_id": jid, "label": label, "status": "running",
            "log_path": log_path, "result_path": out_path,
            "hint": "Poll job_status with this job_id. Progress lines appear in the log tail."}


def job_status(job_id: str, tail: int = 25) -> Dict[str, Any]:
    j = JOBS.get(job_id)
    if not j:
        meta = os.path.join(os.path.expanduser("~"), ".market-mirror", "jobs", f"{job_id}.json")
        try:
            with open(meta, encoding="utf-8") as f:
                j = json.load(f)
        except (OSError, ValueError):
            return {"error": f"unknown job {job_id}"}
    else:
        try:
            with open(j["meta"], encoding="utf-8") as f:
                j = {**j, **json.load(f)}
        except (OSError, ValueError):
            pass
    status = j.get("status", "running")
    if status == "running" and j.get("proc") is not None and j["proc"].poll() is not None:
        status = "done" if j["proc"].returncode == 0 else "failed"
    try:
        with open(j["log"], encoding="utf-8", errors="replace") as f:
            log = f.read().splitlines()[-tail:]
    except OSError:
        log = []
    res: Dict[str, Any] = {"job_id": job_id, "label": j["label"], "elapsed_s": j.get("elapsed_s", round(time.time() - j["started"])),
                           "status": status, "log_tail": log, "log_path": j["log"], "result_path": j["out"]}
    if status != "running":
        try:
            with open(j["out"], encoding="utf-8", errors="replace") as f:
                out = f.read().strip()
        except OSError:
            out = ""
        try:
            res["result"] = json.loads(out.splitlines()[-1]) if out else None
        except (ValueError, IndexError):
            res["result"] = out[-4000:]
    return res


def results(run: str) -> Dict[str, Any]:
    run_dir = run if os.path.isabs(run) else os.path.join(home(), "mirofish_runs", run)
    website = os.path.join(run_dir, "website_test.json")
    if os.path.exists(website) and not os.path.exists(os.path.join(run_dir, "summary.json")):
        with open(website, encoding="utf-8") as source:
            data = json.load(source)
        return {k: data.get(k) for k in ("status", "url", "goal", "summary", "milestones", "files", "interpretation", "limits")}
    path = os.path.join(run_dir, "summary.json")
    if not os.path.exists(path):
        return {"error": f"no summary.json in {run_dir} yet"}
    s = json.load(open(path, encoding="utf-8"))
    mk = s.get("marketing") or {}
    out = {"dashboard": os.path.join(run_dir, "dashboard.html"), "decision": s.get("decision"),
           "report_md": os.path.join(run_dir, "market_report.md") if os.path.exists(os.path.join(run_dir, "market_report.md")) else None,
           "action_plan": (json.load(open(os.path.join(run_dir, "market_report.json"), encoding="utf-8")).get("action_plan")
                           if os.path.exists(os.path.join(run_dir, "market_report.json")) else None),
           "verdicts": mk.get("verdicts"), "overall": mk.get("overall"), "playbook": mk.get("playbook"),
           "by_segment": mk.get("by_segment"), "objections": mk.get("objections"),
           "messages": mk.get("messages_ranked"), "pricing": mk.get("pricing"),
           "files": sorted(f for f in os.listdir(run_dir) if f.endswith((".csv", ".json", ".md", ".html")))}
    if os.path.exists(website):
        with open(website, encoding="utf-8") as source:
            data = json.load(source)
        out["website_test"] = {k: data.get(k) for k in ("status", "summary", "milestones", "files", "interpretation")}
    ft = os.path.join(run_dir, "feed_test.json")
    if os.path.exists(ft):
        ftj = json.load(open(ft, encoding="utf-8"))
        summ = ftj.get("summary") or {}
        ms = ftj.get("multi_seed") or {}
        if ms:
            out["feed_test_seeds"] = {"n": ms.get("n"), "winner_agreement": ms.get("winner_agreement"),
                                      "usage": ms.get("usage"), "spread": ms.get("spread")}
        out["feed_test"] = {cid: {k: v for k, v in m.items() if k in (
            "impressions", "noticed", "thumb_stop", "ctr", "expected_ctr", "engagement_rate", "hide_rate", "landing", "projection")}
            for cid, m in (summ.get("per_creative") or {}).items()}
        out["feed_test_ranked"] = summ.get("ranked")
    pj = os.path.join(run_dir, "pitch.json")
    if os.path.exists(pj):
        pt = json.load(open(pj, encoding="utf-8"))
        out["pitch"] = {k: pt.get(k) for k in ("answered", "pitch_score", "verdict_before", "verdict_after", "fixes", "hot_leads")}
        out["pitch"]["objections"] = [{k: o.get(k) for k in ("type", "share", "rebuttal_success")} for o in pt.get("objections") or []]
    ij = os.path.join(run_dir, "ideas.json")
    if os.path.exists(ij):
        it = json.load(open(ij, encoding="utf-8"))
        out["ideas"] = [{k: i.get(k) for k in ("title", "type", "priority", "hypothesis", "metric", "how_to_test")} for i in it.get("ideas") or []]
        out["ideas_md"] = os.path.join(run_dir, "ideas.md")
    apj = os.path.join(run_dir, "ad_patterns.json")
    if os.path.exists(apj):
        apd = json.load(open(apj, encoding="utf-8"))
        out["ad_patterns"] = {"counts": apd.get("counts"), "engine": apd.get("engine"),
                              "findings": [{k: f.get(k) for k in ("kind", "dimension", "value", "heading", "observation", "simulated_note", "next_test")}
                                           for f in apd.get("findings") or []],
                              "note": "real_longevity is observational (still running after 60+ days), not performance; simulated is simulated."}
    return out


# --------------------------------------------------------------------------
# resources: run files, and the dashboard as an MCP Apps UI resource
# --------------------------------------------------------------------------

RUN_RESOURCES = {"dashboard.html": "text/html", "summary.json": "application/json", "market_report.md": "text/markdown",
                 "report.md": "text/markdown", "calibration.json": "application/json", "focus_group.json": "application/json",
                 "ideas.md": "text/markdown", "ad_patterns.md": "text/markdown", "intake.md": "text/markdown"}
UI_URI = "ui://market-mirror/dashboard"
UI_MIME = "text/html;profile=mcp-app"          # MCP Apps (ext-apps): hosts render this resource inline
LAST_RUN: Dict[str, str] = {}


def _runs_root() -> str:
    return os.path.join(home(), "mirofish_runs")


def _run_dir(name: str) -> str:
    """A run folder by name; refuses anything that is not a plain folder name under mirofish_runs."""
    if not name or name != os.path.basename(name) or name in (".", "..") or "\\" in name:
        raise ValueError(f"not a run name: {name!r}")
    path = os.path.join(_runs_root(), name)
    if not os.path.isdir(path):
        raise ValueError(f"no run named {name!r}")
    return path


def list_resources() -> List[Dict[str, Any]]:
    out = [{"uri": UI_URI, "name": "MarketMirror dashboard", "mimeType": UI_MIME,
            "description": "The dashboard of the run last opened with `results` (else the newest run), as an MCP App."}]
    root = _runs_root()
    for name in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        for f, mime in RUN_RESOURCES.items():
            if os.path.isfile(os.path.join(root, name, f)):
                out.append({"uri": f"marketmirror://runs/{name}/{f}", "name": f"{name}/{f}", "mimeType": mime,
                            "description": f"{f} of run {name} (simulated results)"})
    return out


def _newest_run() -> Optional[str]:
    root = _runs_root()
    runs = [n for n in os.listdir(root) if os.path.isfile(os.path.join(root, n, "dashboard.html"))] if os.path.isdir(root) else []
    return max(runs, key=lambda n: os.path.getmtime(os.path.join(root, n, "dashboard.html"))) if runs else None


def read_resource(uri: str) -> Dict[str, Any]:
    if uri == UI_URI:
        run = LAST_RUN.get("run") or _newest_run()
        if not run:
            text = "<!doctype html><meta charset=utf-8><p>No MarketMirror run with a dashboard yet.</p>"
        else:
            with open(os.path.join(_run_dir(run), "dashboard.html"), encoding="utf-8") as f:
                text = f.read()
        return {"contents": [{"uri": uri, "mimeType": UI_MIME, "text": text}]}
    prefix = "marketmirror://runs/"
    if not uri.startswith(prefix) or uri.count("/") != 4:
        raise ValueError(f"unknown resource: {uri}")
    run, f = uri[len(prefix):].split("/", 1)
    if f not in RUN_RESOURCES:
        raise ValueError(f"not an exposed run file: {f}")
    path = os.path.join(_run_dir(run), f)
    if not os.path.isfile(path):
        raise ValueError(f"{f} does not exist in run {run}")
    with open(path, encoding="utf-8") as fh:
        return {"contents": [{"uri": uri, "mimeType": RUN_RESOURCES[f], "text": fh.read()}]}


# --------------------------------------------------------------------------
# prompts: recipes an agent (or a user's slash menu) can start from
# --------------------------------------------------------------------------

def _arg(name: str, description: str, required: bool = True) -> Dict[str, Any]:
    return {"name": name, "description": description, "required": required}


PROMPTS: Dict[str, Dict[str, Any]] = {
    "test_an_ad": {
        "description": "Test ad copy (and its image or video) on simulated buyers before spending on media.",
        "arguments": [_arg("product", "what is sold, one line"), _arg("ads", "the ad texts, and image/video paths if any"),
                      _arg("audience", "who should see it", False)],
        "text": ("Use MarketMirror to test these ads for {product}.\nAds: {ads}\nAudience: {audience}\n\nRun `doctor`; "
                 "if needed `quickstart` with these answers. Give each creative its real image or video path so the buyers "
                 "see the picture (`creative_check` first for a pre-flight look). Show me the planned personas and the "
                 "estimated cost before any paid step, then run `market_test` with a feed test (seeds 3) and a survey. "
                 "Report each ad's simulated thumb-stop and CTR as directions with their seed ranges, the top objections, "
                 "and the next small real test to run.")},
    "price_check": {
        "description": "Compare price points on simulated buyers, with what is held fixed stated.",
        "arguments": [_arg("product", "what is sold"), _arg("prices", "the price points, e.g. USD 4.99, 7.99, 9.99"),
                      _arg("held_fixed", "what stays the same across prices", False)],
        "text": ("Run a MarketMirror price test for {product} at {prices} with `run_test` (type price, held_fixed: "
                 "{held_fixed}). Before paying, show me the personas and the cost estimate. Report the share who would "
                 "convert at each price as simulated directions (and the shrunk differences), the price objections, and "
                 "say plainly that stated willingness to pay runs optimistic.")},
    "calibrate_with_real_data": {
        "description": "Check a run against real survey answers and get a valid interval and a sample plan.",
        "arguments": [_arg("run", "run name"), _arg("real_csv", "absolute path to real answers (segment, country, gender, age, y)")],
        "text": ("Calibrate MarketMirror run {run} with the real answers in {real_csv} using the `calibrate` tool. Report "
                 "the verdict (trust / correct / walk-away), the PPI++ interval for the audience rate with its "
                 "assumption, what the panel is worth in real answers, and how many more real answers a +-5 point "
                 "interval needs.")},
    "pull_real_results": {
        "description": "Fetch real campaign results from a connected ads, analytics or CRM server and use them as evidence.",
        "arguments": [_arg("source", "meta_ads | google_ads | ga4 | tiktok_ads | hubspot | klaviyo | shopify"),
                      _arg("run", "the MarketMirror run to compare with", False),
                      _arg("period", "date range, e.g. last 30 days", False)],
        "text": ("Using the {source} tools this host already has connected (do not ask me for keys; if none are "
                 "connected, say so and ask me for an export instead), fetch real results for {period}: per ad or campaign "
                 "the impressions, clicks, conversions, spend and currency, with the date range and market. Save them as a "
                 "CSV and normalise it with MarketMirror `actuals_import`, keeping the source. Then compare with run {run} "
                 "through `backtest` (ads) or `holdout_backtest` (independent experiments). Never change the ad account: "
                 "if a winning variant should go live, prepare it as a paused draft only after I approve it explicitly.")},
    "focus_group_after_run": {
        "description": "Hold a moderated focus group with the simulated buyers of a run.",
        "arguments": [_arg("simulation_id", "the run's simulation id"), _arg("questions", "the discussion guide, one per line"),
                      _arg("segment", "only this segment", False)],
        "text": ("Hold a MarketMirror focus group with `ask_buyers` (action focus_group) on simulation {simulation_id}"
                 "{segment_clause}, guide:\n{questions}\n\nReport the themes with their quotes, each person's private "
                 "verdict before and after, and the conformity flag. Present it as qualitative exploration of simulated "
                 "people, and trust the private first answers over the group's apparent agreement.")},
}


def list_prompts() -> List[Dict[str, Any]]:
    return [{"name": n, "description": p["description"], "arguments": p["arguments"]} for n, p in PROMPTS.items()]


def get_prompt(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    if name not in PROMPTS:
        raise ValueError(f"unknown prompt: {name}")
    p = PROMPTS[name]
    missing = [a["name"] for a in p["arguments"] if a["required"] and not str(args.get(a["name"]) or "").strip()]
    if missing:
        raise ValueError(f"missing arguments: {', '.join(missing)}")
    vals = {a["name"]: str(args.get(a["name"]) or "").strip() for a in p["arguments"]}
    defaults = {"audience": "infer it from the product", "held_fixed": "the product, features, brand and terms",
                "run": "(the newest run)", "period": "the last 30 days", "segment": ""}
    vals = {k: v or defaults.get(k, "") for k, v in vals.items()}
    vals["segment_clause"] = f", segment {vals['segment']}" if vals.get("segment") else ""
    return {"description": p["description"],
            "messages": [{"role": "user", "content": {"type": "text", "text": p["text"].format(**vals)}}]}


def list_runs() -> List[Dict[str, Any]]:
    root = os.path.join(home(), "mirofish_runs")
    out = []
    for name in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        p = os.path.join(root, name, "summary.json")
        if os.path.exists(p):
            s = json.load(open(p, encoding="utf-8"))
            out.append({"run": name, "title": (s.get("project_name") or name), "decision": (s.get("decision") or {}).get("decision"),
                        "agents": s.get("agents"), "generated_at": s.get("generated_at")})
    return out


def start_live(run: Optional[str]) -> Dict[str, Any]:
    p = LIVE.get("proc")
    if p and p.poll() is None:
        return {"url": "http://127.0.0.1:5050/", "status": "already running"}
    args = ["live"] + (["--run-dir", os.path.join("mirofish_runs", run)] if run else [])
    LIVE["proc"] = subprocess.Popen(["bash", MM, *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.5)
    return {"url": "http://127.0.0.1:5050/", "status": "started",
            "hint": "Open the URL in a browser (in the Claude desktop app, the browser pane)."}


def write_config(cfg: Dict[str, Any]) -> str:
    name = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(cfg.get("name") or "market_test"))
    d = os.path.join(home(), "scenarios", name)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "market_test.json")
    json.dump(cfg, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return path


TOOLS = [
    {"name": "website_test", "description": "Run prepared synthetic visitors on a real website URL. Actions and screenshots are observed; only supplied DOM checks verify goals. Cart changes are enabled by cart/checkout goals; signup submission requires explicit test data and opt-in. No payments/orders. Background job: poll job_status.",
     "inputSchema": {"type": "object", "properties": {"simulation_id": {"type": "string"},
        "spec": {"type": "object", "properties": {"url": {"type": "string"}, "goal": {"type": "string"},
                 "task": {"type": "string"}, "checks": {"type": "array", "items": {"type": "object"}},
                 "goal_check": {"type": "string"}, "max_personas": {"type": "integer", "minimum": 1, "maximum": 20},
                 "max_steps": {"type": "integer", "minimum": 1, "maximum": 30},
                 "device": {"type": "string", "enum": ["mobile", "desktop"]},
                 "headless": {"type": "boolean"}, "record_video": {"type": "boolean"},
                 "record_trace": {"type": "boolean", "description": "Opt-in raw trace may contain test credentials and network data"},
                 "max_recoveries": {"type": "integer", "minimum": 0, "maximum": 5},
                 "observation_mode": {"type": "string", "enum": ["compact", "full"]},
                 "observation_text_chars": {"type": "integer", "minimum": 1000, "maximum": 10000},
                 "max_model_calls": {"type": "integer", "minimum": 1, "maximum": 600},
                 "max_input_tokens": {"type": "integer", "minimum": 1, "maximum": 100000000},
                 "max_elapsed_s": {"type": "number", "exclusiveMinimum": 0, "maximum": 86400},
                 "loop_limit": {"type": "integer", "minimum": 2, "maximum": 10},
                 "allow_cart": {"type": "boolean"}, "allow_signup_submit": {"type": "boolean"},
                 "test_data": {"type": "object", "description": "Owned test identity only. Multiple signup visitors need an email template containing {visitor}. Never provider API keys."}}, "required": ["url"]},
        "out": {"type": "string"}}, "required": ["simulation_id", "spec"]}},
    {"name": "provider_setup", "description": "List provider choices and official key guides, inspect masked local settings, configure a local model or an existing key environment variable, or discover available models. Never paste an API key into tool arguments. ChatGPT/CLI login choices return local login commands.",
     "inputSchema": {"type": "object", "properties": {"action": {"type": "string", "enum": ["list", "status", "configure", "check"]},
                       "provider": {"type": "string", "enum": ["ollama", "lmstudio", "anthropic", "openai", "compatible", "siwc", "codex", "claude"]},
                       "model": {"type": "string"}, "base_url": {"type": "string"}, "key_env": {"type": "string", "description": "Environment variable NAME only; never the key itself"}}, "required": ["action"]}},
    {"name": "doctor", "description": "Check MarketMirror: engine installed, Python deps, API key configured (never shown), backend running.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "setup", "description": "Install or update the MarketMirror engine (git clone + uv sync). Background job; poll job_status. Needs git and uv.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "start_backend", "description": "Start the MarketMirror backend (port 5001). Configure an API-key, eligible ChatGPT sign-in, local CLI gateway, or local-model provider first.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "market_test", "description": (
        "All-in-one market test. Config keys: name, title, seeds (absolute paths to documents), requirement (text), "
        "personas (persona spec object or absolute path) or auto_personas (int), creatives (feed-test object with creatives, "
        "landing, benchmarks), seeds_n (int, repeat the feed test with N seeds and report ranges), rounds (int), survey {offer, goal, messages (list), split, pricing}, panel {analysts, brief}, "
        "report (bool), simulation_id (reuse), approve_spend (bool). Without approve_spend it stops after creating the "
        "personas so you can show them to the user; then call again with simulation_id and approve_spend true. Background job."),
     "inputSchema": {"type": "object", "properties": {"config": {"type": "object"}}, "required": ["config"]}},
    {"name": "job_status", "description": "Status, log tail and final result of a background job.",
     "inputSchema": {"type": "object", "properties": {"job_id": {"type": "string"}}, "required": ["job_id"]}},
    {"name": "results", "_meta": {"ui": {"resourceUri": UI_URI}, "ui/resourceUri": UI_URI},
     "description": "Key results of a run: decision, verdicts, segments, objections, messages, pricing, feed-test metrics, ROI projections, files. Hosts with MCP Apps also show the run's dashboard inline (resource ui://market-mirror/dashboard).",
     "inputSchema": {"type": "object", "properties": {"run": {"type": "string", "description": "run name under mirofish_runs or absolute path"}}, "required": ["run"]}},
    {"name": "list_runs", "description": "List previous runs with their decision.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "start_live", "description": "Serve the live dashboard at http://127.0.0.1:5050/ (newest run, or a given run).",
     "inputSchema": {"type": "object", "properties": {"run": {"type": "string"}}}},
    {"name": "ads_import", "description": "Turn a Meta/Google Ads export (CSV or JSON, absolute path) into a seed Markdown file plus benchmarks JSON.",
     "inputSchema": {"type": "object", "properties": {"file": {"type": "string"}, "out": {"type": "string", "description": "absolute path of the seed .md to write"}}, "required": ["file", "out"]}},
    {"name": "campaign_plan", "description": "Save an evidence-led campaign plan and runnable test specs from a profile or existing project. No campaign is sent.",
     "inputSchema": {"type": "object", "properties": {"profile": {"type": "object"}, "profile_file": {"type": "string"},
                     "project": {"type": "string"}, "research": {"type": "object"}, "research_file": {"type": "string"},
                     "goal": {"type": "string"}, "budget": {"type": "object"}, "channels": {"type": "array", "items": {"type": "string"}},
                     "out": {"type": "string"}}, "required": ["goal", "budget"]}},
    {"name": "actuals_import", "description": "Normalize a local ads, email, website, CRM or survey CSV/JSON export, retaining provenance and row-level validation errors.",
     "inputSchema": {"type": "object", "properties": {"file": {"type": "string"}, "source_type": {"type": "string", "enum": ["ads", "email", "website", "crm", "survey"]},
                     "mapping": {"type": "object", "additionalProperties": {"type": "string"}}, "source": {"type": "string"},
                     "market": {"type": "string"}, "date": {"type": "string"}, "quality": {"type": "string"},
                     "out": {"type": "string"}}, "required": ["file", "source_type"]}},
    {"name": "holdout_backtest", "description": "Evaluate independent held-out real experiments against a training-mean no-persona baseline.",
     "inputSchema": {"type": "object", "properties": {"pairs": {"type": "array", "items": {"type": "object"}},
                     "out": {"type": "string"}}, "required": ["pairs"]}},
    {"name": "backtest", "description": "Score a run's feed test against real ad results (from ads_import): rank correlation, winner match, calibration.",
     "inputSchema": {"type": "object", "properties": {"run": {"type": "string"}, "actuals": {"type": "string"}, "map": {"type": "array", "items": {"type": "string"}}}, "required": ["run", "actuals"]}},
    {"name": "understand", "description": (
        "Step one for any product: read the user's documents (absolute paths to .md/.txt), a landing page URL and/or an ads "
        "export into one product profile (what it is, for whom, pricing, offer, proofs, differentiators, competitors, channels, "
        "likely objections, brand voice, KPIs, unknowns). Every later step uses it. Synchronous, one Claude call. Writes "
        "product_profile.json; pass `project` instead of docs to profile an existing project (also seeds the market map before "
        "the graph build)."),
     "inputSchema": {"type": "object", "properties": {"docs": {"type": "array", "items": {"type": "string"}}, "url": {"type": "string"},
                                                      "ads_file": {"type": "string"}, "project": {"type": "string"}, "name": {"type": "string"},
                                                      "out": {"type": "string"}}}},
    {"name": "quickstart", "description": (
        "Easiest start. Answer a few questions and get a ready scenario folder (brief, personas, two template captions per "
        "platform, messages, launch calendar, pitch) plus the simulated people (stops before any paid rounds). Keys: brand, "
        "product (what, for whom, price), buyers (who and where), platforms (comma list), tests (ads, messages, price, launch, "
        "pitch), budget ('300 USD'), size (small|medium|large), past_ads (absolute path, optional), docs (paths, optional). "
        "Background job; poll job_status. The result names the files to edit and the exact next command."),
     "inputSchema": {"type": "object", "properties": {"answers": {"type": "object"}, "no_run": {"type": "boolean"},
                                                      "from_docs": {"type": "array", "items": {"type": "string"}, "description": "documents to understand first; prefills the answers"},
                                                      "url": {"type": "string"}}, "required": ["answers"]}},
    {"name": "pitch", "description": (
        "Sales rehearsal: pitch a script to every simulated buyer of a simulation (its environment must be alive: run market_test "
        "with rounds first, or start it), collect objections and the questions they ask back, then answer with rebuttals "
        "({objection_type: text, '*': generic}). Scores the pitch, each rebuttal, and every person (lead score). Background job."),
     "inputSchema": {"type": "object", "properties": {"simulation_id": {"type": "string"}, "run": {"type": "string"},
                                                      "script": {"type": "string"}, "rebuttals": {"type": "object"},
                                                      "product": {"type": "string"}, "channel": {"type": "string"},
                                                      "segment": {"type": "string"}}, "required": ["simulation_id", "script"]}},
    {"name": "ideas", "description": (
        "Next test ideas from real data: pass ad rows you fetched from a connected ads tool (Meta/Google/TikTok: name, campaign, "
        "spend, impressions, clicks, conversions, country...) and/or an export file path, plus a previous run (its objections, "
        "audiences and decision). Returns prioritised experiments, each citing its evidence, with the MarketMirror config to "
        "simulate it first. Writes ideas.json/.md into the run folder and adds a 'Test ideas' section to the dashboard."),
     "inputSchema": {"type": "object", "properties": {"rows": {"type": "array", "items": {"type": "object"}}, "ads_file": {"type": "string"},
                                                      "run": {"type": "string"}, "brand": {"type": "string"}, "brief": {"type": "string"},
                                                      "n": {"type": "integer"}}}},
    {"name": "ad_patterns", "description": (
        "Label a library of real ads (yours or competitors': Meta Ad Library / scraper JSON, an ad-account export, a sheet, "
        "or rows you fetched) on seven creative dimensions (format, hook, angle, offer, proof, objection, CTA) and find "
        "the patterns: which labels stay in market 60+ days (observational, NOT performance), real CTR/CPA per label when "
        "the rows carry metrics, and, with a run, the run's feed-test creatives on the same labels (marked simulated). "
        "engine: auto (Jev when configured, else the chat model), llm, jev, or supplied (labels already in the rows; "
        "offline, no backend). Writes ad_patterns.json/.md/.csv and adds an 'Ad patterns' dashboard section. Background job. "
        "Use real ad data only with the owner's permission."),
     "inputSchema": {"type": "object", "properties": {"ads_file": {"type": "string", "description": "absolute path to CSV/JSON of ads"},
                                                      "rows": {"type": "array", "items": {"type": "object"}},
                                                      "run": {"type": "string"}, "engine": {"type": "string", "enum": ["auto", "llm", "jev", "supplied"]},
                                                      "brand": {"type": "string"}, "now": {"type": "string", "description": "collection date YYYY-MM-DD"},
                                                      "max_ads": {"type": "integer"}, "out": {"type": "string"},
                                                      "vision": {"type": "boolean", "description": "describe rows' image/video first (backend)"}}}},
    {"name": "creative_check", "description": (
        "Pre-flight look at real ad creatives before any simulated buyer sees them: what each image or video (keyframes via "
        "ffmpeg) shows, the words on it, whether brand and call to action are visible, what a one-second scroller takes away, "
        "platform checks (text density, brand early, legibility, safe zones, captions) and the measured aspect ratio. "
        "creatives: [{id, platform, image|video (absolute path or https URL), text?, headline?, cta?}]. Needs the backend and a "
        "vision-capable model. A model's reading plus measured facts, not an attention or recall score. In market_test, "
        "creatives with image/video are seen by the buyers too ('vision': describe|direct|off). Background job."),
     "inputSchema": {"type": "object", "properties": {"creatives": {"type": "array", "items": {"type": "object"}},
                                                      "out": {"type": "string"}}, "required": ["creatives"]}},
    {"name": "intake", "description": (
        "Turn the owner's own customer material into grounded personas: call or interview transcripts, review exports, NPS / survey "
        "verbatims, CRM or support notes (absolute paths: CSV, TSV, JSON, JSONL, txt, md, vtt, srt), or rows you fetched from a "
        "connected CRM. Emails, phone and card numbers, links, @handles and names from name columns are removed before any model "
        "call; quotes stay verbatim (a quote not in the source is dropped) and nothing unstated is invented. Writes a persona spec "
        "with real_profiles (marked 'Grounded' in the dashboard) that market_test takes as its personas; synthetic people fill the "
        "rest of the audience. engine: llm (backend) or supplied (offline, no model). Use customer data only with the owner's "
        "permission and show them intake.md before running. Background job."),
     "inputSchema": {"type": "object", "properties": {"files": {"type": "array", "items": {"type": "string"}},
                                                      "rows": {"type": "array", "items": {"type": "object"}},
                                                      "out": {"type": "string", "description": "persona spec path to write (absolute)"},
                                                      "base": {"type": "string", "description": "persona spec to start from"},
                                                      "engine": {"type": "string", "enum": ["llm", "supplied"]},
                                                      "context": {"type": "string"}, "segment_field": {"type": "string"},
                                                      "id_field": {"type": "string"}, "text_field": {"type": "string"},
                                                      "segment": {"type": "string"}, "max_people": {"type": "integer"}}}},
    {"name": "ask_buyers", "description": (
        "Talk to the simulated buyers after a run, no live simulation needed. action 'ask': one person (agent_id from "
        "results/profiles) answers a message, with optional history. action 'focus_group': 2-8 saved people (taken in turn "
        "from each segment, or one segment, or agent_ids) give a private verdict, discuss the guide questions with a "
        "moderator, then give a private verdict again; returns themes with checked quotes, the before/after shift and a "
        "conformity flag, saves focus_group.json and adds a dashboard section (background job). Simulated people: "
        "qualitative exploration, not real buyers."),
     "inputSchema": {"type": "object", "properties": {"action": {"type": "string", "enum": ["ask", "focus_group"]},
                                                      "simulation_id": {"type": "string"}, "agent_id": {"type": "integer"},
                                                      "message": {"type": "string"},
                                                      "history": {"type": "array", "items": {"type": "object"}},
                                                      "guide": {"type": "array", "items": {"type": "string"}},
                                                      "people": {"type": "integer"}, "segment": {"type": "string"},
                                                      "offer": {"type": "string"}, "goal": {"type": "string"},
                                                      "run": {"type": "string"}},
                     "required": ["action", "simulation_id"]}},
    {"name": "push_context", "description": (
        "While a simulation is running (or before it starts), push what people are saying today into every persona card from the next "
        "round on: a news item, a competitor's move, a real thread you just read with your browser, a price change. Each update is "
        "one or two sentences; the runner re-reads the file every round. Use it to ground the rounds in live reality."),
     "inputSchema": {"type": "object", "properties": {"simulation_id": {"type": "string"}, "text": {"type": "string"}, "round": {"type": "integer"},
                                                      "source": {"type": "string"}}, "required": ["simulation_id", "text"]}},
    {"name": "research", "description": (
        "What real people say about a product, category or competitor, from public keyless sources: Hacker News stories and "
        "comments, App Store listings and recent reviews for a country storefront (in, ph, ke, us...), Reddit public search when "
        "it answers (it often blocks non-browser clients; the result says so, then use your own browser tools and add what you find "
        "as seed files), and any page URLs. Writes research.md (themes with quotes and links), research.json and voices.json (short "
        "real quotes the personas and feeds draw on) under scenarios/<query>/research. Run it before planning personas."),
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "sources": {"type": "string"}, "country": {"type": "string"},
                                                      "subreddits": {"type": "array", "items": {"type": "string"}}, "urls": {"type": "array", "items": {"type": "string"}},
                                                      "out": {"type": "string"}}, "required": ["query"]}},
    {"name": "predict", "description": (
        "Predictions with intervals for a run: CTR per ad, cost per lead, would-convert overall and per audience, email click rates, "
        "each scaled by the real-vs-simulated results stored so far (from backtest and calibrate) and labelled with its basis "
        "('calibrated on N real results' or 'uncalibrated prior'); optional targets (e.g. {ctr: 2, cpl: 10}) give a probability of "
        "success. Also a 30/60/90-day adoption forecast from the best ad, its landing conversion and the word of mouth seen in the rounds."),
     "inputSchema": {"type": "object", "properties": {"run": {"type": "string"}, "brand": {"type": "string"}, "targets": {"type": "object"},
                                                      "spend": {"type": "number"}, "days": {"type": "integer"}}, "required": ["run"]}},
    {"name": "study", "description": (
        "Several scenarios x several seeds on the same simulated people, one defended conclusion. spec: {name, base (a market_test "
        "config object: creatives, survey, pitch, emails, rounds...), simulation_id (the people to reuse), scenarios: [{name, overrides}], "
        "seeds: [1,2,3], steps: [feed_test, rounds, survey, pitch, email_test]}. Writes study_summary.json (per-scenario mean, spread and "
        "95% interval of every metric, deltas, winner stability, decision agreement matrix, conclusion with confidence), study_report.md "
        "and study.html under mirofish_runs/<name>/. Finished cells are reused on rerun. Background job."),
     "inputSchema": {"type": "object", "properties": {"spec": {"type": "object"}, "out": {"type": "string"}}, "required": ["spec"]}},
    {"name": "run_test", "description": (
        "Test anything from one spec on a prepared simulation: type = ad | message | price | offer | positioning | naming | landing | "
        "launch | pitch | email | creator_post | channel_mix; variants = the things to compare (ad creatives, message lines, prices, "
        "offer wordings, names, landing pages, launch posts with rounds, pitch scripts, emails); audience {segments, countries}; "
        "metric (default per type); budget {amount, cpm, currency}; rounds (launch). Returns one result shape for every type: each "
        "variant's metric with a 95% margin, the winner, the lift, whether it is clear or a tie, and how to read it. Background job."),
     "inputSchema": {"type": "object", "properties": {"simulation_id": {"type": "string"}, "spec": {"type": "object"}, "brand": {"type": "string"},
                                                      "run": {"type": "string"}}, "required": ["simulation_id", "spec"]}},
    {"name": "email_test", "description": (
        "Email campaign test on the simulated people's inboxes: pass emails [{id, from_name, subject, preheader, body, cta, "
        "send_time (morning|midday|evening|night), segments?, sequence?: [{delay_days, subject, body}]}] plus optional list_size and "
        "benchmarks {cost_per_send, lead_value, close_rate, deal_value}. Each person gets a realistic inbox for the day; an "
        "attention gate decides opens, Claude decides skim/read/click/reply/unsubscribe/spam with honest odds. Returns open, click, "
        "click-to-open, unsubscribe and spam rates per variant and audience, subject-line ranking, sequence funnel, projection from "
        "list size to leads and revenue, spam-word warnings. Needs a prepared simulation (simulation_id). Background job."),
     "inputSchema": {"type": "object", "properties": {"simulation_id": {"type": "string"}, "run": {"type": "string"},
                                                      "emails": {"type": "array", "items": {"type": "object"}}, "list_size": {"type": "integer"},
                                                      "benchmarks": {"type": "object"}}, "required": ["simulation_id", "emails"]}},
    {"name": "calibrate", "description": (
        "Check a run's simulated survey against real answers (absolute path to a CSV with segment,country,gender,age,y where y is "
        "yes/maybe/no or 0-1; 50-300 rows is enough): covariate overlap, per-audience calibration, a trust / correct / walk-away "
        "verdict and an AIPW-corrected rate. Writes calibration.json into the run folder."),
     "inputSchema": {"type": "object", "properties": {"run": {"type": "string"}, "real_csv": {"type": "string"},
                                                      "field": {"type": "string"}, "by": {"type": "string"},
                                                      "map": {"type": "array", "items": {"type": "string"}}}, "required": ["run", "real_csv"]}},
    {"name": "cli", "description": "Advanced: run any MarketMirror CLI command as a background job, e.g. ['survey','--simulation','sim_x','--offer','...']. See CLAUDE.md in the engine.",
     "inputSchema": {"type": "object", "properties": {"args": {"type": "array", "items": {"type": "string"}}}, "required": ["args"]}},
]


def call(name: str, a: Dict[str, Any]) -> Any:
    if name == "website_test":
        directory = os.path.join(home(), "scenarios", "_website_tests")
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, uuid.uuid4().hex[:12] + ".json")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(a["spec"], output, ensure_ascii=False)
        args = ["cli", "website-test", "--simulation", a["simulation_id"], "--spec", "@" + path]
        if a.get("out"):
            args += ["--out", str(a["out"])]
        return job(args, "website-test")
    if name == "provider_setup":
        args = ["provider", a["action"]]
        for key in ("provider", "model", "base_url", "key_env"):
            if a.get(key):
                args += ["--" + key.replace("_", "-"), str(a[key])]
        return _cli_result(sh(args, timeout=30))
    if name == "doctor":
        r = sh(["doctor"])
        return {"ok": r["ok"], "diagnostics": (r["stderr"] + r["stdout"]).strip()}
    if name == "setup":
        return job(["setup"], "setup")
    if name == "start_backend":
        r = sh(["start"], timeout=300)
        return _cli_result(r)
    if name == "market_test":
        path = write_config(a["config"])
        return {**job(["cli", "market-test", path], "market-test"), "config": path}
    if name == "job_status":
        return job_status(a["job_id"])
    if name == "results":
        out = results(a["run"])
        run = os.path.basename(os.path.normpath(a["run"]))
        if isinstance(out, dict) and "error" not in out:
            LAST_RUN["run"] = run
            out["resources"] = {f: f"marketmirror://runs/{run}/{f}" for f in RUN_RESOURCES
                                if os.path.isfile(os.path.join(os.path.dirname(out.get("dashboard") or ""), f))}
        return out
    if name == "list_runs":
        return list_runs()
    if name == "start_live":
        return start_live(a.get("run"))
    if name == "ads_import":
        r = sh(["cli", "ads-import", a["file"], "--out", a["out"]], timeout=300)
        return _cli_result(r)
    if name == "campaign_plan":
        if not (a.get("profile") or a.get("profile_file") or a.get("project")):
            raise ValueError("profile, profile_file, or project is required")
        d = os.path.join(home(), "scenarios", "_plans")
        os.makedirs(d, exist_ok=True)
        args = ["cli", "campaign-plan", "--goal", str(a["goal"]), "--budget", str(a["budget"]["amount"]),
                "--currency", str(a["budget"].get("currency") or "USD")]
        if a.get("profile"):
            p = os.path.join(d, f"profile_{uuid.uuid4().hex[:8]}.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump(a["profile"], f, ensure_ascii=False)
            args += ["--profile", p]
        elif a.get("profile_file"):
            args += ["--profile", str(a["profile_file"])]
        else:
            args += ["--project", str(a["project"])]
        if a.get("research"):
            p = os.path.join(d, f"research_{uuid.uuid4().hex[:8]}.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump(a["research"], f, ensure_ascii=False)
            args += ["--research", p]
        elif a.get("research_file"):
            args += ["--research", str(a["research_file"])]
        if a.get("channels"):
            args += ["--channels", *[str(c) for c in a["channels"]]]
        if a["budget"].get("period"):
            args += ["--period", str(a["budget"]["period"])]
        args += ["--out", str(a.get("out") or os.path.join(d, "campaign_plan.json"))]
        r = sh(args, timeout=300)
        return _cli_result(r)
    if name == "actuals_import":
        args = ["cli", "actuals-import", str(a["file"]), "--source-type", str(a["source_type"])]
        if a.get("mapping"):
            args += ["--map", *[f"{k}={v}" for k, v in a["mapping"].items()]]
        for key in ("source", "market", "date", "quality", "out"):
            if a.get(key):
                args += ["--" + key, str(a[key])]
        return _cli_result(sh(args, timeout=300))
    if name == "holdout_backtest":
        d = os.path.join(home(), "scenarios", "_backtests")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"pairs_{uuid.uuid4().hex[:8]}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(a["pairs"], f, ensure_ascii=False)
        args = ["cli", "holdout-backtest", "--pairs", path]
        if a.get("out"):
            args += ["--out", str(a["out"])]
        return _cli_result(sh(args, timeout=60))
    if name == "backtest":
        run_dir = a["run"] if os.path.isabs(a["run"]) else os.path.join("mirofish_runs", a["run"])
        r = sh(["cli", "backtest", "--run-dir", run_dir, "--actuals", a["actuals"], *(["--map", *a["map"]] if a.get("map") else [])], timeout=300)
        return _cli_result(r)
    if name == "understand":
        d = os.path.join(home(), "scenarios", "_profiles")
        os.makedirs(d, exist_ok=True)
        out = a.get("out") or os.path.join(d, f"profile_{uuid.uuid4().hex[:6]}.json")
        args = ["cli", "understand", "--out", out]
        if a.get("project"):
            args += ["--project", a["project"]]
        if a.get("docs"):
            args += ["--docs", *[str(x) for x in a["docs"]]]
        for k in ("url", "name"):
            if a.get(k):
                args += ["--" + k, str(a[k])]
        if a.get("ads_file"):
            args += ["--ads", a["ads_file"]]
        r = sh(args, timeout=400)
        return _cli_result(r)
    if name == "quickstart":
        d = os.path.join(home(), "scenarios", "_quickstart")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"answers_{uuid.uuid4().hex[:6]}.json")
        json.dump(a["answers"], open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        args = ["cli", "quickstart", "--answers", "@" + path] + (["--no-run"] if a.get("no_run") else [])
        if a.get("from_docs"):
            args += ["--from-docs", *[str(x) for x in a["from_docs"]]]
        if a.get("url"):
            args += ["--url", str(a["url"])]
        return {**job(args, "quickstart"), "answers": path}
    if name == "pitch":
        run_dir = a.get("run")
        run_dir = (run_dir if os.path.isabs(run_dir) else os.path.join("mirofish_runs", run_dir)) if run_dir else None
        d = os.path.join(home(), "scenarios", "_pitch")
        os.makedirs(d, exist_ok=True)
        sp = os.path.join(d, f"pitch_{uuid.uuid4().hex[:6]}.md")
        open(sp, "w", encoding="utf-8").write(a["script"])
        args = ["cli", "pitch", "--simulation", a["simulation_id"], "--script", "@" + sp]
        if a.get("rebuttals"):
            rp = sp.replace("pitch_", "rebuttals_").replace(".md", ".json")
            json.dump(a["rebuttals"], open(rp, "w", encoding="utf-8"), ensure_ascii=False)
            args += ["--rebuttals", "@" + rp]
        for k in ("product", "channel", "segment"):
            if a.get(k):
                args += ["--" + k, str(a[k])]
        if run_dir:
            args += ["--run-dir", run_dir]
        return job(args, "pitch")
    if name == "ideas":
        run_dir = a.get("run")
        run_dir = (run_dir if os.path.isabs(run_dir) else os.path.join("mirofish_runs", run_dir)) if run_dir else None
        args = ["cli", "ideas"]
        if a.get("rows"):
            d = os.path.join(home(), "scenarios", "_ideas")
            os.makedirs(d, exist_ok=True)
            rp = os.path.join(d, f"rows_{uuid.uuid4().hex[:6]}.json")
            json.dump(a["rows"], open(rp, "w", encoding="utf-8"), ensure_ascii=False)
            args += ["--rows", "@" + rp]
        if a.get("ads_file"):
            args += ["--ads", a["ads_file"]]
        if run_dir:
            args += ["--run-dir", run_dir]
        for k in ("brand", "brief"):
            if a.get(k):
                args += ["--" + k, str(a[k])]
        if a.get("n"):
            args += ["--n", str(int(a["n"]))]
        r = sh(args, timeout=400)
        return _cli_result(r)
    if name == "ad_patterns":
        if not (a.get("rows") or a.get("ads_file")):
            raise ValueError("ads_file or rows is required")
        run_dir = a.get("run")
        run_dir = (run_dir if os.path.isabs(run_dir) else os.path.join("mirofish_runs", run_dir)) if run_dir else None
        args = ["cli", "ad-patterns", "--engine", str(a.get("engine") or "auto")]
        if a.get("rows"):
            d = os.path.join(home(), "scenarios", "_ad_patterns")
            os.makedirs(d, exist_ok=True)
            rp = os.path.join(d, f"rows_{uuid.uuid4().hex[:6]}.json")
            json.dump(a["rows"], open(rp, "w", encoding="utf-8"), ensure_ascii=False)
            args += ["--rows", "@" + rp]
        if a.get("ads_file"):
            args += ["--ads", a["ads_file"]]
        if run_dir:
            args += ["--run-dir", run_dir]
        elif not a.get("out"):
            args += ["--out", os.path.join(home(), "scenarios", "_ad_patterns", f"ad_patterns_{uuid.uuid4().hex[:6]}.json")]
        for k in ("brand", "now", "out"):
            if a.get(k):
                args += ["--" + k, str(a[k])]
        if a.get("max_ads"):
            args += ["--max-ads", str(int(a["max_ads"]))]
        if a.get("vision"):
            args.append("--vision")
        return job(args, "ad_patterns")
    if name == "ask_buyers":
        if a.get("action") == "ask":
            if a.get("agent_id") is None or not a.get("message"):
                raise ValueError("ask needs agent_id and message")
            d = os.path.join(home(), "scenarios", "_ask")
            os.makedirs(d, exist_ok=True)
            hp = os.path.join(d, f"chat_{a['simulation_id']}_{int(a['agent_id'])}.json")
            if a.get("history") is not None:
                json.dump(a["history"], open(hp, "w", encoding="utf-8"), ensure_ascii=False)
            elif not os.path.exists(hp):
                json.dump([], open(hp, "w", encoding="utf-8"))
            return _cli_result(sh(["cli", "ask", "--simulation", a["simulation_id"], "--person", str(int(a["agent_id"])),
                                   "--history", "@" + hp, a["message"]], timeout=400))
        if not a.get("guide"):
            raise ValueError("focus_group needs guide (a list of questions)")
        d = os.path.join(home(), "scenarios", "_focus_groups")
        os.makedirs(d, exist_ok=True)
        gp = os.path.join(d, f"guide_{uuid.uuid4().hex[:6]}.md")
        open(gp, "w", encoding="utf-8").write("\n".join(str(q) for q in a["guide"]))
        args = ["cli", "focus-group", "--simulation", a["simulation_id"], "--guide", "@" + gp]
        for k in ("people",):
            if a.get(k):
                args += ["--" + k, str(int(a[k]))]
        for k in ("segment", "offer", "goal"):
            if a.get(k):
                args += ["--" + k, str(a[k])]
        if a.get("run"):
            run_dir = a["run"] if os.path.isabs(a["run"]) else os.path.join("mirofish_runs", a["run"])
            args += ["--run-dir", run_dir]
        return job(args, "focus_group")
    if name == "creative_check":
        d = os.path.join(home(), "scenarios", "_creative_check")
        os.makedirs(d, exist_ok=True)
        tag = uuid.uuid4().hex[:6]
        cp = os.path.join(d, f"creatives_{tag}.json")
        json.dump({"creatives": a["creatives"]}, open(cp, "w", encoding="utf-8"), ensure_ascii=False)
        return job(["cli", "creative-check", "--creatives", "@" + cp,
                    "--out", a.get("out") or os.path.join(d, f"creative_check_{tag}.json")], "creative_check")
    if name == "intake":
        if not (a.get("rows") or a.get("files")):
            raise ValueError("files or rows is required")
        d = os.path.join(home(), "scenarios", "_intake")
        os.makedirs(d, exist_ok=True)
        args = ["cli", "intake", "--engine", str(a.get("engine") or "llm"),
                "--out", a.get("out") or os.path.join(d, f"personas_{uuid.uuid4().hex[:6]}.json")]
        if a.get("files"):
            args += ["--files", *[str(f) for f in a["files"]]]
        if a.get("rows"):
            rp = os.path.join(d, f"rows_{uuid.uuid4().hex[:6]}.json")
            json.dump(a["rows"], open(rp, "w", encoding="utf-8"), ensure_ascii=False)
            args += ["--rows", "@" + rp]
        for k in ("base", "context", "segment"):
            if a.get(k):
                args += ["--" + k, str(a[k])]
        for k in ("id_field", "segment_field", "text_field"):
            if a.get(k):
                args += ["--" + k.replace("_", "-"), str(a[k])]
        if a.get("max_people"):
            args += ["--max-people", str(int(a["max_people"]))]
        return job(args, "intake")
    if name == "push_context":
        args = ["cli", "context", "--simulation", a["simulation_id"], "--text", a["text"]]
        if a.get("round") is not None:
            args += ["--round", str(int(a["round"]))]
        if a.get("source"):
            args += ["--source", str(a["source"])]
        r = sh(args, timeout=60)
        return _cli_result(r)
    if name == "research":
        args = ["cli", "research", "--query", a["query"]]
        if a.get("sources"):
            args += ["--sources", str(a["sources"])]
        if a.get("country"):
            args += ["--country", str(a["country"])]
        if a.get("subreddits"):
            args += ["--subreddit", *[str(x) for x in a["subreddits"]]]
        if a.get("urls"):
            args += ["--url", *[str(x) for x in a["urls"]]]
        if a.get("out"):
            args += ["--out", str(a["out"])]
        r = sh(args, timeout=400)
        return _cli_result(r)
    if name == "predict":
        run_dir = a["run"] if os.path.isabs(a["run"]) else os.path.join("mirofish_runs", a["run"])
        args = ["cli", "predict", "--run-dir", run_dir]
        if a.get("brand"):
            args += ["--brand", str(a["brand"])]
        if a.get("targets"):
            args += ["--target", *[f"{k}={v}" for k, v in a["targets"].items()]]
        if a.get("spend"):
            args += ["--spend", str(a["spend"])]
        if a.get("days"):
            args += ["--days", str(int(a["days"]))]
        r = sh(args, timeout=300)
        return _cli_result(r)
    if name == "study":
        d = os.path.join(home(), "scenarios", "_studies")
        os.makedirs(d, exist_ok=True)
        sp = os.path.join(d, f"study_{uuid.uuid4().hex[:6]}.json")
        json.dump(a["spec"], open(sp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        args = ["cli", "study", "--spec", sp]
        if a.get("out"):
            args += ["--out", a["out"]]
        return job(args, "study")
    if name == "run_test":
        run_dir = a.get("run")
        run_dir = (run_dir if os.path.isabs(run_dir) else os.path.join("mirofish_runs", run_dir)) if run_dir else None
        d = os.path.join(home(), "scenarios", "_tests")
        os.makedirs(d, exist_ok=True)
        sp = os.path.join(d, f"test_{uuid.uuid4().hex[:6]}.json")
        json.dump(a["spec"], open(sp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        args = ["cli", "test", "--simulation", a["simulation_id"], "--spec", "@" + sp]
        if a.get("brand"):
            args += ["--brand", str(a["brand"])]
        if run_dir:
            args += ["--run-dir", run_dir]
        return job(args, f"test {a['spec'].get('type', '')}")
    if name == "email_test":
        run_dir = a.get("run")
        run_dir = (run_dir if os.path.isabs(run_dir) else os.path.join("mirofish_runs", run_dir)) if run_dir else None
        d = os.path.join(home(), "scenarios", "_emails")
        os.makedirs(d, exist_ok=True)
        ep = os.path.join(d, f"emails_{uuid.uuid4().hex[:6]}.json")
        json.dump({"emails": a["emails"], "list_size": a.get("list_size"), "benchmarks": a.get("benchmarks")}, open(ep, "w", encoding="utf-8"), ensure_ascii=False)
        args = ["cli", "emailtest", "--simulation", a["simulation_id"], "--emails", "@" + ep]
        if a.get("list_size"):
            args += ["--list-size", str(int(a["list_size"]))]
        if run_dir:
            args += ["--run-dir", run_dir]
        return job(args, "email-test")
    if name == "calibrate":
        run_dir = a["run"] if os.path.isabs(a["run"]) else os.path.join("mirofish_runs", a["run"])
        args = ["cli", "calibrate", "--run-dir", run_dir, "--real", a["real_csv"]]
        for k in ("field", "by"):
            if a.get(k):
                args += ["--" + k, str(a[k])]
        if a.get("map"):
            args += ["--map", *[str(x) for x in a["map"]]]
        r = sh(args, timeout=300)
        return _cli_result(r)
    if name == "cli":
        return job(["cli", *[str(x) for x in a["args"]]], "cli " + " ".join(map(str, a["args"][:2])))
    raise ValueError(f"unknown tool {name}")


def reply(msg_id: Any, result: Any = None, error: Optional[Dict[str, Any]] = None) -> None:
    out = {"jsonrpc": "2.0", "id": msg_id, **({"error": error} if error else {"result": result})}
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def dispatch(msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:
        return None  # notification
    if method == "initialize":
        requested = (msg.get("params") or {}).get("protocolVersion")
        result = {"protocolVersion": requested if requested in SUPPORTED_PROTOCOLS else PROTOCOL,
                    "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                    "serverInfo": {"name": "market-mirror", "version": "0.4.2"},
                    "instructions": "MarketMirror tests marketing and sales decisions on simulated buyers. Start with doctor; "
                                    "run setup if the engine is missing; use market_test for everything; show the user the "
                                    "personas before approving spend; report results as simulated directions with their margins."}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method in ("resources/list", "resources/read", "resources/templates/list", "prompts/list", "prompts/get"):
        p = msg.get("params") or {}
        try:
            if method == "resources/list":
                result = {"resources": list_resources()}
            elif method == "resources/templates/list":
                result = {"resourceTemplates": [{"uriTemplate": "marketmirror://runs/{run}/{file}", "name": "Run file",
                                                 "description": "A file of a MarketMirror run: " + ", ".join(RUN_RESOURCES)}]}
            elif method == "resources/read":
                result = read_resource(str(p.get("uri") or ""))
            elif method == "prompts/list":
                result = {"prompts": list_prompts()}
            else:
                result = get_prompt(str(p.get("name") or ""), p.get("arguments") or {})
        except (ValueError, OSError) as e:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": str(e)}}
    elif method == "tools/call":
        p = msg.get("params") or {}
        try:
            res = call(p.get("name"), p.get("arguments") or {})
            text = res if isinstance(res, str) else json.dumps(res, ensure_ascii=False, indent=2, default=str)
            result = {"content": [{"type": "text", "text": text}], "isError": False}
            if isinstance(res, (dict, list)):
                result["structuredContent"] = res
        except Exception as e:  # noqa: BLE001 - surfaced to the client as a tool error
            result = {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True,
                      "structuredContent": {"error": str(e), "error_type": type(e).__name__}}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def handle(msg: Dict[str, Any]) -> None:
    out = dispatch(msg)
    if out is not None:
        sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def serve_http(port: int, token: str) -> None:
    """Stateless MCP Streamable HTTP on authenticated loopback only."""
    if not token or len(token) < 24:
        raise ValueError("MCP bearer token must contain at least 24 characters")

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != "/mcp":
                self.send_error(404)
                return
            given = self.headers.get("Authorization", "")
            if not hmac.compare_digest(given, "Bearer " + token):
                self.send_response(401)
                self.send_header("WWW-Authenticate", "Bearer")
                self.end_headers()
                return
            origin = self.headers.get("Origin", "")
            if origin and not (origin.startswith("http://127.0.0.1:") or origin.startswith("http://localhost:")):
                self.send_error(403)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size <= 0 or size > 1_000_000:
                    raise ValueError("invalid request size")
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict):
                    raise ValueError("JSON-RPC request must be an object")
                out = dispatch(body)
            except (ValueError, UnicodeDecodeError) as e:
                self.send_error(400, str(e))
                return
            if out is None:
                self.send_response(202)
                self.end_headers()
                return
            payload = json.dumps(out, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            self.send_error(405)

        def log_message(self, fmt, *args):
            print(fmt % args, file=sys.stderr)

    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="MarketMirror MCP server")
    parser.add_argument("--http", action="store_true", help="serve authenticated MCP over loopback HTTP")
    parser.add_argument("--port", type=int, default=5061)
    parser.add_argument("--token-file", help="file containing a bearer token (required for --http)")
    opts = parser.parse_args()
    if opts.http:
        if not opts.token_file:
            parser.error("--http requires --token-file")
        with open(opts.token_file, encoding="utf-8") as f:
            token = f.read().strip()
        serve_http(opts.port, token)
        return
    lock = threading.Lock()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        with lock:
            handle(msg)


if __name__ == "__main__":
    main()
