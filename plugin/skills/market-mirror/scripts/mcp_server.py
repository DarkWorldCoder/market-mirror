#!/usr/bin/env python3
"""
MarketMirror MCP server (stdio, stdlib only).

Exposes MarketMirror as tools for any MCP client (Claude Code, Claude Desktop, ...). It wraps mm.sh,
so it works before the engine is installed: call `setup` first. Long work (setup, market tests,
surveys, feed tests) runs as background jobs; poll `job_status`.

Register (Claude Code):  claude mcp add market-mirror -- python3 /path/to/mcp_server.py
The plugin registers it automatically.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
MM = os.path.join(HERE, "mm.sh")
PROTOCOL = "2024-11-05"
JOBS: Dict[str, Dict[str, Any]] = {}
LIVE: Dict[str, Any] = {}


def sh(args: List[str], timeout: float = 120) -> Dict[str, Any]:
    try:
        p = subprocess.run(["bash", MM, *args], capture_output=True, text=True, timeout=timeout)
        return {"ok": p.returncode == 0, "stdout": p.stdout[-20000:], "stderr": p.stderr[-6000:]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": f"timed out after {timeout}s"}


def home() -> str:
    return sh(["home"])["stdout"].strip()


def job(args: List[str], label: str) -> Dict[str, Any]:
    jid = uuid.uuid4().hex[:10]
    logdir = os.path.join(os.path.expanduser("~"), ".market-mirror", "jobs")
    os.makedirs(logdir, exist_ok=True)
    log_path = os.path.join(logdir, f"{jid}.log")
    out_path = os.path.join(logdir, f"{jid}.out")
    proc = subprocess.Popen(["bash", MM, *args], stdout=open(out_path, "w"), stderr=open(log_path, "w"), text=True)
    JOBS[jid] = {"id": jid, "label": label, "args": args, "proc": proc, "log": log_path, "out": out_path,
                 "started": time.time()}
    return {"job_id": jid, "label": label, "status": "running",
            "hint": "Poll job_status with this job_id. Progress lines appear in the log tail."}


def job_status(job_id: str, tail: int = 25) -> Dict[str, Any]:
    j = JOBS.get(job_id)
    if not j:
        return {"error": f"unknown job {job_id} (jobs do not survive a server restart; see ~/.market-mirror/jobs)"}
    code = j["proc"].poll()
    log = open(j["log"], encoding="utf-8", errors="replace").read().splitlines()[-tail:]
    res: Dict[str, Any] = {"job_id": job_id, "label": j["label"], "elapsed_s": round(time.time() - j["started"]),
                           "status": "running" if code is None else ("done" if code == 0 else "failed"),
                           "log_tail": log}
    if code is not None:
        out = open(j["out"], encoding="utf-8", errors="replace").read().strip()
        try:
            res["result"] = json.loads(out.splitlines()[-1]) if out else None
        except (ValueError, IndexError):
            res["result"] = out[-4000:]
    return res


def results(run: str) -> Dict[str, Any]:
    run_dir = run if os.path.isabs(run) else os.path.join(home(), "mirofish_runs", run)
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
    return out


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
    {"name": "doctor", "description": "Check MarketMirror: engine installed, Python deps, API key configured (never shown), backend running.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "setup", "description": "Install or update the MarketMirror engine (git clone + uv sync). Background job; poll job_status. Needs git and uv.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "start_backend", "description": "Start the MarketMirror backend (port 5001). Requires an API key in the engine's .env.",
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
    {"name": "results", "description": "Key results of a run: decision, verdicts, segments, objections, messages, pricing, feed-test metrics, ROI projections, files.",
     "inputSchema": {"type": "object", "properties": {"run": {"type": "string", "description": "run name under mirofish_runs or absolute path"}}, "required": ["run"]}},
    {"name": "list_runs", "description": "List previous runs with their decision.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "start_live", "description": "Serve the live dashboard at http://127.0.0.1:5050/ (newest run, or a given run).",
     "inputSchema": {"type": "object", "properties": {"run": {"type": "string"}}}},
    {"name": "ads_import", "description": "Turn a Meta/Google Ads export (CSV or JSON, absolute path) into a seed Markdown file plus benchmarks JSON.",
     "inputSchema": {"type": "object", "properties": {"file": {"type": "string"}, "out": {"type": "string", "description": "absolute path of the seed .md to write"}}, "required": ["file", "out"]}},
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
    {"name": "cli", "description": "Advanced: run any MarketMirror CLI command as a background job, e.g. ['survey','--simulation','sim_x','--offer','...']. See CLAUDE.md in the engine.",
     "inputSchema": {"type": "object", "properties": {"args": {"type": "array", "items": {"type": "string"}}}, "required": ["args"]}},
]


def call(name: str, a: Dict[str, Any]) -> Any:
    if name == "doctor":
        r = sh(["doctor"])
        return (r["stderr"] + r["stdout"]).strip()
    if name == "setup":
        return job(["setup"], "setup")
    if name == "start_backend":
        r = sh(["start"], timeout=300)
        return (r["stdout"] + r["stderr"]).strip()
    if name == "market_test":
        path = write_config(a["config"])
        return {**job(["cli", "market-test", path], "market-test"), "config": path}
    if name == "job_status":
        return job_status(a["job_id"])
    if name == "results":
        return results(a["run"])
    if name == "list_runs":
        return list_runs()
    if name == "start_live":
        return start_live(a.get("run"))
    if name == "ads_import":
        r = sh(["cli", "ads-import", a["file"], "--out", a["out"]], timeout=300)
        return r["stdout"].strip() or r["stderr"].strip()
    if name == "backtest":
        run_dir = a["run"] if os.path.isabs(a["run"]) else os.path.join("mirofish_runs", a["run"])
        r = sh(["cli", "backtest", "--run-dir", run_dir, "--actuals", a["actuals"], *(["--map", *a["map"]] if a.get("map") else [])], timeout=300)
        return r["stdout"].strip() or r["stderr"].strip()
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
        return r["stdout"].strip() or r["stderr"].strip()
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
        return r["stdout"].strip() or r["stderr"].strip()
    if name == "cli":
        return job(["cli", *[str(x) for x in a["args"]]], "cli " + " ".join(map(str, a["args"][:2])))
    raise ValueError(f"unknown tool {name}")


def reply(msg_id: Any, result: Any = None, error: Optional[Dict[str, Any]] = None) -> None:
    out = {"jsonrpc": "2.0", "id": msg_id, **({"error": error} if error else {"result": result})}
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle(msg: Dict[str, Any]) -> None:
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:
        return  # notification
    if method == "initialize":
        reply(mid, {"protocolVersion": PROTOCOL, "capabilities": {"tools": {}},
                    "serverInfo": {"name": "market-mirror", "version": "0.2.0"},
                    "instructions": "MarketMirror tests marketing and sales decisions on simulated buyers. Start with doctor; "
                                    "run setup if the engine is missing; use market_test for everything; show the user the "
                                    "personas before approving spend; report results as simulated directions with their margins."})
    elif method == "ping":
        reply(mid, {})
    elif method == "tools/list":
        reply(mid, {"tools": TOOLS})
    elif method == "tools/call":
        p = msg.get("params") or {}
        try:
            res = call(p.get("name"), p.get("arguments") or {})
            text = res if isinstance(res, str) else json.dumps(res, ensure_ascii=False, indent=2, default=str)
            reply(mid, {"content": [{"type": "text", "text": text}], "isError": False})
        except Exception as e:  # noqa: BLE001 - surfaced to the client as a tool error
            reply(mid, {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True})
    else:
        reply(mid, error={"code": -32601, "message": f"method not found: {method}"})


def main() -> None:
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
