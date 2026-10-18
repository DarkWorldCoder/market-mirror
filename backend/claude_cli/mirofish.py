#!/usr/bin/env python3
"""
mirofish.py - headless CLI for the MiroFish backend (Flask API on :5001).

Designed for an AI agent (Claude) with a shell: every command prints JSON to
stdout (use --pretty for indentation); progress and logs go to stderr.

Pipeline (mirrors the web UI):
  1. POST /api/graph/ontology/generate   (multipart: files, simulation_requirement, project_name)
  2. POST /api/graph/build               -> task_id; poll GET /api/graph/task/<task_id>
  3. POST /api/simulation/create         {project_id, graph_id, enable_twitter, enable_reddit}
  4. POST /api/simulation/prepare        -> task_id; poll POST /api/simulation/prepare/status
  5. POST /api/simulation/start          {simulation_id, platform, max_rounds, enable_graph_memory_update, force}
     poll GET /api/simulation/<id>/run-status until runner_status in completed|stopped|failed
  6. POST /api/report/generate           -> report_id, task_id; poll POST /api/report/generate/status
     then GET /api/report/<report_id>
  7. POST /api/report/chat / POST /api/simulation/interview (after the run)

Run `python backend/claude_cli/mirofish.py --help` for all commands.
Only the stdlib and `requests` are used (requests is imported lazily, so
`export --run-dir` works on any Python 3.9+).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import exporter  # noqa: E402

DEFAULT_BASE_URL = os.environ.get("MIROFISH_URL", "http://localhost:5001")
TERMINAL_RUN = {"completed", "stopped", "failed"}


class CLIError(RuntimeError):
    pass


def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", file=sys.stderr, flush=True)


# --------------------------------------------------------------------------
# HTTP client
# --------------------------------------------------------------------------

class Client:
    def __init__(self, base_url: str, timeout: float = 60, lang: str = "en"):
        try:
            import requests  # noqa: F401
        except ImportError as e:  # pragma: no cover
            raise CLIError("The 'requests' package is required (run via `cd backend && uv run --no-sync python ...`)") from e
        import requests
        self.requests = requests
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["Accept-Language"] = lang

    def _handle(self, resp, method: str, path: str) -> Any:
        try:
            body = resp.json()
        except ValueError:
            raise CLIError(f"{method} {path} -> HTTP {resp.status_code}: {resp.text[:500]}")
        if resp.status_code >= 400 or (isinstance(body, dict) and body.get("success") is False):
            err = body.get("error") or body.get("message") if isinstance(body, dict) else body
            raise CLIError(f"{method} {path} -> HTTP {resp.status_code}: {err}")
        return body

    def request(self, method: str, path: str, *, retries: int = 3, timeout: Optional[float] = None, **kw) -> Any:
        url = self.base + path
        last: Optional[Exception] = None
        for attempt in range(retries):
            try:
                resp = self.session.request(method, url, timeout=timeout or self.timeout, **kw)
                return self._handle(resp, method, path)
            except (self.requests.ConnectionError, self.requests.Timeout) as e:
                last = e
                if attempt < retries - 1:
                    time.sleep(2 * (attempt + 1))
        raise CLIError(f"{method} {path}: cannot reach MiroFish backend at {self.base} ({last}). "
                       "Start it with backend/claude_cli/start_server.sh")

    def get(self, path: str, params: Optional[dict] = None, **kw) -> Any:
        return self.request("GET", path, params=params, **kw)

    def post(self, path: str, payload: Optional[dict] = None, **kw) -> Any:
        return self.request("POST", path, json=payload or {}, **kw)

    def data(self, method: str, path: str, **kw) -> Any:
        body = self.request(method, path, **kw)
        return body.get("data") if isinstance(body, dict) else body


def poll(fetch: Callable[[], Dict[str, Any]], is_done: Callable[[Dict[str, Any]], bool],
         is_failed: Callable[[Dict[str, Any]], bool], describe: Callable[[Dict[str, Any]], str],
         label: str, interval: float, timeout: float, max_errors: int = 10) -> Dict[str, Any]:
    start = time.time()
    last_msg = None
    errors = 0
    while True:
        try:
            state = fetch()
            errors = 0
        except CLIError as e:
            errors += 1
            log(f"{label}: poll error ({errors}/{max_errors}): {e}")
            if errors >= max_errors:
                raise
            time.sleep(interval)
            continue
        msg = describe(state)
        if msg != last_msg:
            log(f"{label}: {msg}")
            last_msg = msg
        if is_failed(state):
            raise CLIError(f"{label} failed: {state.get('error') or state.get('message') or state}")
        if is_done(state):
            return state
        if time.time() - start > timeout:
            raise CLIError(f"{label} timed out after {int(timeout)}s (last state: {msg}). "
                           "Re-run the step command to keep waiting; work continues server-side.")
        time.sleep(interval)


# --------------------------------------------------------------------------
# Steps
# --------------------------------------------------------------------------

def read_text_arg(v: Optional[str]) -> Optional[str]:
    if v and v.startswith("@"):
        with open(v[1:], "r", encoding="utf-8") as f:
            return f.read().strip()
    return v


def step_upload(c: Client, seeds: List[str], requirement: str, name: Optional[str],
                context: Optional[str] = None) -> Dict[str, Any]:
    files = []
    handles = []
    try:
        for p in seeds:
            if not os.path.isfile(p):
                raise CLIError(f"seed file not found: {p}")
            ext = os.path.splitext(p)[1].lower().lstrip(".")
            if ext not in {"pdf", "md", "txt", "markdown"}:
                raise CLIError(f"unsupported seed type '{p}' (allowed: pdf, md, txt, markdown)")
            fh = open(p, "rb")
            handles.append(fh)
            files.append(("files", (os.path.basename(p), fh)))
        form = {"simulation_requirement": requirement,
                "project_name": name or os.path.splitext(os.path.basename(seeds[0]))[0]}
        if context:
            form["additional_context"] = context
        log(f"upload: sending {len(files)} file(s); generating ontology with the LLM (can take 1-3 min)")
        data = c.data("POST", "/api/graph/ontology/generate", files=files, data=form, timeout=900, retries=1)
    finally:
        for fh in handles:
            fh.close()
    log(f"upload: project {data.get('project_id')} - {len((data.get('ontology') or {}).get('entity_types', []))} "
        f"entity types, {len((data.get('ontology') or {}).get('edge_types', []))} relation types")
    return data


def step_build_graph(c: Client, project_id: str, wait: bool = True, timeout: float = 3600,
                     interval: float = 5, force: bool = False, chunk_size: Optional[int] = None,
                     chunk_overlap: Optional[int] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"project_id": project_id}
    if force:
        payload["force"] = True
    if chunk_size:
        payload["chunk_size"] = chunk_size
    if chunk_overlap is not None:
        payload["chunk_overlap"] = chunk_overlap
    data = c.data("POST", "/api/graph/build", json=payload, timeout=120)
    task_id = data.get("task_id")
    if data.get("reused") and data.get("graph_id") and not _project_building(c, project_id):
        log(f"build-graph: reusing existing graph {data.get('graph_id')}")
        return {"project_id": project_id, "graph_id": data.get("graph_id"), "task_id": task_id, "reused": True}
    log(f"build-graph: task {task_id} started")
    if not wait:
        return data
    task = poll(lambda: c.data("GET", f"/api/graph/task/{task_id}"),
                lambda s: s.get("status") == "completed",
                lambda s: s.get("status") == "failed",
                lambda s: f"{s.get('status')} {s.get('progress', 0)}% {s.get('message', '')}",
                "build-graph", interval, timeout)
    result = task.get("result") or {}
    project = c.data("GET", f"/api/graph/project/{project_id}")
    return {"project_id": project_id, "graph_id": result.get("graph_id") or project.get("graph_id"),
            "task_id": task_id, "node_count": result.get("node_count"), "edge_count": result.get("edge_count")}


def _project_building(c: Client, project_id: str) -> bool:
    try:
        return c.data("GET", f"/api/graph/project/{project_id}").get("status") == "graph_building"
    except CLIError:
        return False


def platform_flags(platform: str) -> Dict[str, bool]:
    return {"enable_twitter": platform in ("twitter", "parallel"),
            "enable_reddit": platform in ("reddit", "parallel")}


def step_create_sim(c: Client, project_id: str, graph_id: Optional[str], platform: str) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"project_id": project_id, **platform_flags(platform)}
    if graph_id:
        payload["graph_id"] = graph_id
    data = c.data("POST", "/api/simulation/create", json=payload)
    log(f"create-sim: simulation {data.get('simulation_id')} created ({platform})")
    return data


def step_prepare(c: Client, simulation_id: str, wait: bool = True, timeout: float = 3600, interval: float = 5,
                 parallel: int = 5, entity_types: Optional[List[str]] = None, use_llm: bool = True,
                 force: bool = False, persona_spec: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"simulation_id": simulation_id, "use_llm_for_profiles": use_llm,
                               "parallel_profile_count": parallel, "force_regenerate": force}
    if entity_types:
        payload["entity_types"] = entity_types
    if persona_spec:
        payload["persona_spec"] = persona_spec
    data = c.data("POST", "/api/simulation/prepare", json=payload, timeout=300)
    if data.get("already_prepared"):
        log("prepare: already prepared")
        return data
    task_id = data.get("task_id")
    log(f"prepare: task {task_id} started, expecting {data.get('expected_entities_count')} agents "
        f"(types: {', '.join(data.get('entity_types') or [])})")
    if not wait:
        return data

    def describe(s):
        d = s.get("progress_detail") or {}
        extra = f" [{d.get('current_stage_name') or d.get('stage') or ''}]" if d else ""
        return f"{s.get('status')} {s.get('progress', 0)}%{extra} {s.get('message', '')}".strip()

    st = poll(lambda: c.data("POST", "/api/simulation/prepare/status", json={"task_id": task_id, "simulation_id": simulation_id}),
              lambda s: s.get("status") in ("completed", "ready") or bool(s.get("already_prepared")),
              lambda s: s.get("status") == "failed",
              describe, "prepare", interval, timeout)
    return {"simulation_id": simulation_id, "task_id": task_id, "status": "ready", "result": st.get("result")}


def step_start(c: Client, simulation_id: str, platform: str = "parallel", max_rounds: Optional[int] = None,
               graph_memory: bool = True, force: bool = True, wait: bool = True,
               timeout: float = 4 * 3600, interval: float = 5) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"simulation_id": simulation_id, "platform": platform,
                               "enable_graph_memory_update": graph_memory, "force": force}
    if max_rounds:
        payload["max_rounds"] = max_rounds
    data = c.data("POST", "/api/simulation/start", json=payload, timeout=180)
    log(f"start: runner {data.get('runner_status')} pid={data.get('process_pid')} "
        f"max_rounds={data.get('max_rounds_applied')} graph_memory={data.get('graph_memory_update_enabled')}")
    if not wait:
        return data
    return wait_run(c, simulation_id, timeout, interval)


def wait_run(c: Client, simulation_id: str, timeout: float, interval: float) -> Dict[str, Any]:
    def describe(s):
        return (f"{s.get('runner_status')} round {s.get('current_round', 0)}/{s.get('total_rounds', 0)} "
                f"({s.get('progress_percent', 0)}%) actions={s.get('total_actions_count', 0)} "
                f"[tw r{s.get('twitter_current_round', 0)} / rd r{s.get('reddit_current_round', 0)}]")
    return poll(lambda: c.data("GET", f"/api/simulation/{simulation_id}/run-status"),
                lambda s: s.get("runner_status") in ("completed", "stopped"),
                lambda s: s.get("runner_status") == "failed",
                describe, "run", interval, timeout)


def step_report(c: Client, simulation_id: str, force: bool = False, wait: bool = True,
                timeout: float = 3600, interval: float = 5) -> Dict[str, Any]:
    data = c.data("POST", "/api/report/generate", json={"simulation_id": simulation_id, "force_regenerate": force},
                  timeout=180)
    report_id = data.get("report_id")
    if data.get("already_generated"):
        log(f"report: reusing existing report {report_id} (use --force to regenerate)")
    else:
        task_id = data.get("task_id")
        log(f"report: generating {report_id} (task {task_id})")
        if not wait:
            return data
        # Poll by task_id only: passing simulation_id would short-circuit on an older completed report.
        poll(lambda: c.data("POST", "/api/report/generate/status", json={"task_id": task_id}),
             lambda s: s.get("status") == "completed",
             lambda s: s.get("status") == "failed",
             lambda s: f"{s.get('status')} {s.get('progress', 0)}% {s.get('message', '')}",
             "report", interval, timeout)
    return c.data("GET", f"/api/report/{report_id}")


# --------------------------------------------------------------------------
# Collecting artifacts for export
# --------------------------------------------------------------------------

def save_json(out_dir: str, name: str, data: Any) -> None:
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, f"{name}.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _try(label: str, fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except CLIError as e:
        log(f"collect: skipped {label}: {e}")
        return None


def collect(c: Client, out_dir: str, project_id: Optional[str] = None, simulation_id: Optional[str] = None,
            report_id: Optional[str] = None) -> Dict[str, str]:
    """Fetch everything the dashboard needs and save it into out_dir."""
    saved: Dict[str, str] = {}

    def put(name, data):
        if data is not None:
            save_json(out_dir, name, data)
            saved[name] = os.path.join(out_dir, f"{name}.json")

    sim = None
    if simulation_id:
        sim = _try("simulation", lambda: c.data("GET", f"/api/simulation/{simulation_id}"))
        put("simulation", sim)
        if sim and not project_id:
            project_id = sim.get("project_id")
    project = None
    if project_id:
        project = _try("project", lambda: c.data("GET", f"/api/graph/project/{project_id}"))
        put("project", project)
        if project and not simulation_id:
            sims = _try("simulations", lambda: c.data("GET", "/api/simulation/list", params={"project_id": project_id})) or []
            if sims:
                simulation_id = sorted(sims, key=lambda s: s.get("created_at") or "")[-1]["simulation_id"]
                log(f"collect: using latest simulation {simulation_id} of project {project_id}")
                sim = _try("simulation", lambda: c.data("GET", f"/api/simulation/{simulation_id}"))
                put("simulation", sim)
    graph_id = (project or {}).get("graph_id") or (sim or {}).get("graph_id")
    if graph_id:
        log(f"collect: graph {graph_id}")
        put("graph", _try("graph", lambda: c.data("GET", f"/api/graph/data/{graph_id}", timeout=300)))

    if simulation_id:
        sid = simulation_id
        log(f"collect: simulation {sid} config, profiles, actions, posts")
        put("config", _try("config", lambda: c.data("GET", f"/api/simulation/{sid}/config")))
        platforms = [p for p, flag in (("twitter", (sim or {}).get("enable_twitter", True)),
                                       ("reddit", (sim or {}).get("enable_reddit", True))) if flag]
        for plat in platforms:
            prof = _try(f"profiles_{plat}", lambda: c.data("GET", f"/api/simulation/{sid}/profiles", params={"platform": plat}))
            if prof is not None:
                put(f"profiles_{plat}", prof.get("profiles"))
            posts = _try(f"posts_{plat}", lambda: c.data("GET", f"/api/simulation/{sid}/posts",
                                                           params={"platform": plat, "limit": 1000}))
            if posts is not None:
                put(f"posts_{plat}", posts.get("posts"))
            com = _try(f"comments_{plat}", lambda: c.data("GET", f"/api/simulation/{sid}/comments",
                                                            params={"platform": plat, "limit": 2000}))
            if com is not None and com.get("comments"):
                put(f"comments_{plat}", com.get("comments"))
        put("run_status", _try("run_status", lambda: c.data("GET", f"/api/simulation/{sid}/run-status")))
        tl = _try("timeline", lambda: c.data("GET", f"/api/simulation/{sid}/timeline"))
        if tl is not None:
            put("timeline", tl.get("timeline"))
        actions: List[Dict[str, Any]] = []
        offset, page = 0, 1000
        while True:
            chunk = _try("actions", lambda: c.data("GET", f"/api/simulation/{sid}/actions",
                                                     params={"limit": page, "offset": offset}))
            if not chunk:
                break
            acts = chunk.get("actions") or []
            actions.extend(acts)
            if len(acts) < page or offset > 200_000:
                break
            offset += page
        put("actions", actions)
        stats = _try("agent_stats", lambda: c.data("GET", f"/api/simulation/{sid}/agent-stats"))
        if stats is not None:
            put("agent_stats", stats.get("stats"))
        if not report_id:
            rep = _try("report", lambda: c.data("GET", f"/api/report/by-simulation/{sid}"))
            if rep:
                put("report", rep)
    if report_id:
        put("report", _try("report", lambda: c.data("GET", f"/api/report/{report_id}")))
    return saved


def do_export(run_dir: str, out: Optional[str], title: Optional[str] = None) -> Dict[str, str]:
    paths = exporter.export_run_dir(run_dir, out, title=title)
    log(f"export: wrote {paths['html']}")
    return paths


# --------------------------------------------------------------------------
# Live dashboard (served on localhost so an in-app browser can show it)
# --------------------------------------------------------------------------

LIVE_SCRIPT = """
<div id="mf-live" style="position:fixed;right:12px;bottom:12px;z-index:9999;padding:6px 12px;border-radius:999px;
font:12px/1.4 system-ui,sans-serif;background:rgba(20,20,20,.85);color:#fff;max-width:calc(100vw - 24px)">%s</div>
<script>(function(){
var v=%s,ms=%d;
try{var y=sessionStorage.getItem('mf_live_y');if(y){sessionStorage.removeItem('mf_live_y');window.scrollTo(0,+y);}}catch(e){}
function tick(){fetch('/__live/state',{cache:'no-store'}).then(function(r){return r.json();}).then(function(s){
var b=document.getElementById('mf-live');if(b)b.textContent=s.label;
if(s.version!==v){try{sessionStorage.setItem('mf_live_y',String(window.scrollY));}catch(e){}location.reload();return;}
setTimeout(tick,ms);}).catch(function(){setTimeout(tick,ms);});}
setTimeout(tick,ms);})();</script>
"""


def read_manifest(run_dir: str) -> Dict[str, Any]:
    try:
        with open(os.path.join(run_dir, "run_manifest.json"), encoding="utf-8") as f:
            return json.load(f) or {}
    except (OSError, ValueError):
        return {}


def live_stage(manifest: Dict[str, Any], run_status: Optional[Dict[str, Any]] = None) -> str:
    """One-line description of where a run is, from its manifest and run status."""
    if manifest.get("error"):
        return f"Stopped with error: {str(manifest['error'])[:120]}"
    if manifest.get("finished_at"):
        return "Done"
    if manifest.get("report_id"):
        return "Writing the report"
    rs = run_status or {}
    status = rs.get("runner_status")
    if manifest.get("runner_status") or status in TERMINAL_RUN:
        return "Simulation finished; writing the report"
    if status == "running":
        cur, total = rs.get("current_round"), rs.get("total_rounds")
        return f"Simulating round {cur}/{total}" if cur is not None and total else "Simulating"
    if manifest.get("simulation_id"):
        return "Preparing agents"
    if manifest.get("graph_id"):
        return "Creating the simulation"
    if manifest.get("project_id"):
        return "Building the knowledge graph"
    return "Waiting for the run to start"


def inject_live(page: str, label: str, version: int, interval_ms: int) -> str:
    snippet = LIVE_SCRIPT % (exporter.esc(label), json.dumps(version), interval_ms)
    i = page.rfind("</body>")
    return page[:i] + snippet + page[i:] if i >= 0 else page + snippet


class LiveDashboard:
    """Re-collects a run from the backend and re-renders its dashboard on a timer."""

    def __init__(self, c: Optional[Client], run_dir: str, title: Optional[str] = None,
                 project_id: Optional[str] = None, simulation_id: Optional[str] = None):
        import threading
        self.c, self.run_dir, self.title = c, run_dir, title
        self.project_id, self.simulation_id = project_id, simulation_id
        self.lock = threading.Lock()
        self.version = 0
        self.label = "Starting"
        self.html = "<!doctype html><html><body><p>Loading the MiroFish dashboard...</p></body></html>"
        self._digest: Optional[str] = None

    def refresh(self) -> None:
        import hashlib
        m = read_manifest(self.run_dir)
        pid = self.project_id or m.get("project_id")
        sid = self.simulation_id or m.get("simulation_id")
        if self.c is not None and (pid or sid):
            with _quiet_logs():
                collect(self.c, self.run_dir, pid, sid, m.get("report_id"))
        rs = None
        try:
            with open(os.path.join(self.run_dir, "run_status.json"), encoding="utf-8") as f:
                rs = json.load(f)
        except (OSError, ValueError):
            pass
        os.makedirs(self.run_dir, exist_ok=True)
        page, _md, _summary = exporter.render_dashboard(exporter.load_run_dir(self.run_dir), title=self.title)
        label = live_stage(m, rs)
        digest = hashlib.sha1(page.encode("utf-8")).hexdigest()
        with self.lock:
            if digest != self._digest:
                self._digest = digest
                self.version += 1
                self.html = page
            self.label = label

    def state(self) -> Dict[str, Any]:
        with self.lock:
            return {"version": self.version, "label": self.label}

    def page(self, interval_ms: int) -> str:
        with self.lock:
            return inject_live(self.html, self.label, self.version, interval_ms)


class _quiet_logs:
    """Silence `log` while the live loop polls, so the terminal isn't flooded."""

    def __enter__(self):
        global log
        self._orig = log
        log = lambda msg: None  # noqa: E731
        return self

    def __exit__(self, *exc):
        global log
        log = self._orig
        return False


def serve_live(live: LiveDashboard, host: str, port: int, interval: float) -> None:
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    interval_ms = max(1000, int(interval * 1000))

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, body: bytes, ctype: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/__live/state":
                return self._send(json.dumps(live.state()).encode(), "application/json")
            if path in ("/", "/index.html", "/dashboard.html"):
                return self._send(live.page(interval_ms).encode("utf-8"), "text/html; charset=utf-8")
            self.send_error(404)

    stop = threading.Event()

    def loop():
        while not stop.is_set():
            try:
                live.refresh()
            except Exception as e:  # keep serving the last good page
                with live.lock:
                    live.label = f"Refresh failed: {str(e)[:120]}"
            stop.wait(interval)

    threading.Thread(target=loop, daemon=True).start()
    srv = ThreadingHTTPServer((host, port), H)
    log(f"live: serving {os.path.abspath(live.run_dir)} at http://{host}:{port}/ (refresh every {interval:g}s, Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        srv.server_close()


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

def cmd_health(c: Client, a) -> Any:
    return c.get("/health", retries=1, timeout=10)


def cmd_upload(c: Client, a) -> Any:
    return step_upload(c, a.seed, read_text_arg(a.requirement), a.name, read_text_arg(a.context))


def cmd_build_graph(c: Client, a) -> Any:
    return step_build_graph(c, a.project, wait=not a.no_wait, timeout=a.timeout, interval=a.interval,
                            force=a.force, chunk_size=a.chunk_size, chunk_overlap=a.chunk_overlap)


def cmd_create_sim(c: Client, a) -> Any:
    return step_create_sim(c, a.project, a.graph, a.platform)


def load_persona_spec(path: Optional[str], auto: Optional[int]) -> Optional[Dict[str, Any]]:
    """--personas FILE (JSON: segments, communities, ...) and/or --auto-personas N."""
    spec: Optional[Dict[str, Any]] = None
    if path:
        try:
            with open(path, encoding="utf-8") as f:
                spec = json.load(f)
        except (OSError, ValueError) as e:
            raise CLIError(f"cannot read persona spec {path}: {e}")
        if not isinstance(spec, dict):
            raise CLIError(f"persona spec {path} must be a JSON object")
    if auto:
        spec = dict(spec or {})
        spec.setdefault("auto", True)
        spec["auto_total"] = auto
    return spec


def cmd_prepare(c: Client, a) -> Any:
    return step_prepare(c, a.simulation, wait=not a.no_wait, timeout=a.timeout, interval=a.interval,
                        parallel=a.parallel, entity_types=a.entity_types, use_llm=not a.no_llm_profiles,
                        force=a.force or bool(a.personas or a.auto_personas),
                        persona_spec=load_persona_spec(a.personas, a.auto_personas))


def cmd_start(c: Client, a) -> Any:
    return step_start(c, a.simulation, a.platform, a.max_rounds, graph_memory=not a.no_graph_memory,
                      force=not a.no_force, wait=not a.no_wait, timeout=a.timeout, interval=a.interval)


def cmd_wait(c: Client, a) -> Any:
    return wait_run(c, a.simulation, a.timeout, a.interval)


def cmd_stop(c: Client, a) -> Any:
    return c.data("POST", "/api/simulation/stop", json={"simulation_id": a.simulation}, timeout=180)


def cmd_close_env(c: Client, a) -> Any:
    return c.data("POST", "/api/simulation/close-env", json={"simulation_id": a.simulation, "timeout": a.wait_s},
                  timeout=a.wait_s + 30)


def cmd_status(c: Client, a) -> Any:
    out: Dict[str, Any] = {}
    if a.simulation:
        out["simulation"] = c.data("GET", f"/api/simulation/{a.simulation}")
        out["run_status"] = c.data("GET", f"/api/simulation/{a.simulation}/run-status")
        out["env"] = _try("env", lambda: c.data("POST", "/api/simulation/env-status", json={"simulation_id": a.simulation}))
        rep = _try("report", lambda: c.data("GET", f"/api/report/check/{a.simulation}"))
        if rep is not None:
            out["report"] = rep
    if a.project:
        out["project"] = c.data("GET", f"/api/graph/project/{a.project}")
    if a.task:
        out["task"] = c.data("GET", f"/api/graph/task/{a.task}")
    if not out:
        raise CLIError("status needs --simulation, --project or --task")
    return out


def cmd_report(c: Client, a) -> Any:
    rep = step_report(c, a.simulation, force=a.force, wait=not a.no_wait, timeout=a.timeout, interval=a.interval)
    if a.out and isinstance(rep, dict) and rep.get("markdown_content"):
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(rep["markdown_content"])
        log(f"report: markdown saved to {a.out}")
    if a.markdown_only and isinstance(rep, dict):
        return {"report_id": rep.get("report_id"), "status": rep.get("status"),
                "markdown_content": rep.get("markdown_content")}
    return rep


def cmd_chat(c: Client, a) -> Any:
    history = []
    if a.history and os.path.exists(a.history):
        with open(a.history, "r", encoding="utf-8") as f:
            history = json.load(f)
    msg = read_text_arg(a.message)
    data = c.data("POST", "/api/report/chat", json={"simulation_id": a.simulation, "message": msg,
                                                     "chat_history": history}, timeout=600)
    if a.history:
        history += [{"role": "user", "content": msg}, {"role": "assistant", "content": data.get("response", "")}]
        with open(a.history, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    return data


def cmd_interview(c: Client, a) -> Any:
    prompt = read_text_arg(a.prompt)
    if a.all:
        payload = {"simulation_id": a.simulation, "prompt": prompt, "timeout": a.wait_s}
        if a.platform:
            payload["platform"] = a.platform
        return c.data("POST", "/api/simulation/interview/all", json=payload, timeout=a.wait_s + 60)
    if a.agent is None:
        raise CLIError("interview needs --agent ID (see `profiles`) or --all")
    agents = a.agent
    if len(agents) == 1:
        payload = {"simulation_id": a.simulation, "agent_id": agents[0], "prompt": prompt, "timeout": a.wait_s}
        if a.platform:
            payload["platform"] = a.platform
        return c.data("POST", "/api/simulation/interview", json=payload, timeout=a.wait_s + 60)
    interviews = [{"agent_id": x, "prompt": prompt, **({"platform": a.platform} if a.platform else {})} for x in agents]
    return c.data("POST", "/api/simulation/interview/batch",
                  json={"simulation_id": a.simulation, "interviews": interviews, "timeout": a.wait_s},
                  timeout=a.wait_s + 60)


def cmd_profiles(c: Client, a) -> Any:
    params = {"platform": a.platform} if a.platform else None
    data = c.data("GET", f"/api/simulation/{a.simulation}/profiles", params=params)
    if a.brief:
        return [{"agent_id": p.get("user_id", i), "name": p.get("name"), "username": p.get("username"),
                 "profession": p.get("profession"), "bio": exporter.trunc(p.get("bio"), 120)}
                for i, p in enumerate(data.get("profiles") or [])]
    return data


def cmd_list(c: Client, a) -> Any:
    out: Dict[str, Any] = {}
    what = a.what
    if what in ("all", "projects"):
        projects = c.data("GET", "/api/graph/project/list", params={"limit": a.limit}) or []
        out["projects"] = [{k: p.get(k) for k in ("project_id", "name", "status", "graph_id", "created_at",
                                                     "simulation_requirement")} for p in projects] if not a.full else projects
    if what in ("all", "simulations"):
        sims = c.data("GET", "/api/simulation/history", params={"limit": a.limit}) or []
        keys = ("simulation_id", "project_id", "status", "runner_status", "current_round", "total_rounds",
                "profiles_count", "report_id", "created_at")
        out["simulations"] = sims if a.full else [{k: s.get(k) for k in keys} for s in sims]
    if what in ("all", "reports"):
        reps = c.data("GET", "/api/report/list", params={"limit": a.limit}) or []
        out["reports"] = reps if a.full else [{k: r.get(k) for k in ("report_id", "simulation_id", "status",
                                                                        "created_at", "completed_at")} for r in reps]
    return out


def default_run_dir(prefix: str = "") -> str:
    return os.path.join("mirofish_runs", (prefix + "_" if prefix else "") + datetime.now().strftime("%Y%m%d_%H%M%S"))


def cmd_export(c: Optional[Client], a) -> Any:
    if a.run_dir and not (a.project or a.simulation or a.report):
        run_dir = a.run_dir
    else:
        if c is None:
            raise CLIError("export needs --run-dir, or --project/--simulation/--report with a reachable backend")
        run_dir = a.run_dir or default_run_dir(a.simulation or a.project or a.report or "export")
        saved = collect(c, run_dir, a.project, a.simulation, a.report)
        log(f"export: collected {len(saved)} files into {run_dir}")
    out = a.out or os.path.join(run_dir, "dashboard.html")
    return do_export(run_dir, out, a.title)


def latest_run_dir(root: str = "mirofish_runs") -> Optional[str]:
    """The most recently started run directory under root (by run_manifest.json, else dir mtime)."""
    try:
        dirs = [os.path.join(root, d) for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))]
    except OSError:
        return None

    def started(d):
        mp = os.path.join(d, "run_manifest.json")
        return os.path.getmtime(mp) if os.path.exists(mp) else os.path.getmtime(d)

    dirs = [d for d in dirs if os.path.exists(os.path.join(d, "run_manifest.json")) or os.listdir(d)]
    return max(dirs, key=started) if dirs else None


def cmd_live(c: Optional[Client], a) -> Any:
    run_dir = a.run_dir or latest_run_dir(a.runs_root)
    if not run_dir:
        if not (a.project or a.simulation):
            raise CLIError(f"live: no runs under {a.runs_root}/; pass --run-dir, --project or --simulation")
        run_dir = default_run_dir(a.simulation or a.project)
    live = LiveDashboard(c, run_dir, a.title, a.project, a.simulation)
    serve_live(live, a.host, a.port, a.interval)
    return {"run_dir": os.path.abspath(run_dir), "stopped": True}


def cmd_run(c: Client, a) -> Any:
    requirement = read_text_arg(a.requirement)
    load_persona_spec(a.personas, a.auto_personas)  # fail fast on a bad spec file
    out_dir = a.out or default_run_dir()
    os.makedirs(out_dir, exist_ok=True)
    log(f"run: artifacts -> {os.path.abspath(out_dir)}")
    state: Dict[str, Any] = {"out_dir": os.path.abspath(out_dir), "started_at": datetime.now().isoformat()}

    def checkpoint():
        save_json(out_dir, "run_manifest", state)

    try:
        c.get("/health", retries=2, timeout=10)
        up = step_upload(c, a.seed, requirement, a.name, read_text_arg(a.context))
        state["project_id"] = up["project_id"]
        save_json(out_dir, "ontology", up)
        checkpoint()

        g = step_build_graph(c, up["project_id"], timeout=a.timeout, interval=a.interval)
        state["graph_id"] = g.get("graph_id")
        checkpoint()

        sim = step_create_sim(c, up["project_id"], g.get("graph_id"), a.platform)
        state["simulation_id"] = sim["simulation_id"]
        checkpoint()

        step_prepare(c, sim["simulation_id"], timeout=a.timeout, interval=a.interval, parallel=a.parallel,
                     entity_types=a.entity_types,
                     persona_spec=load_persona_spec(a.personas, a.auto_personas))
        if a.stop_after == "prepare":
            log("run: --stop-after prepare; not starting the simulation")
        else:
            rs = step_start(c, sim["simulation_id"], a.platform, a.max_rounds, graph_memory=not a.no_graph_memory,
                            force=True, timeout=a.run_timeout, interval=a.interval)
            state["runner_status"] = rs.get("runner_status")
            checkpoint()
            if a.stop_after != "simulate" and not a.no_report:
                rep = step_report(c, sim["simulation_id"], timeout=a.timeout, interval=a.interval)
                state["report_id"] = rep.get("report_id")
                checkpoint()
    except (CLIError, KeyboardInterrupt) as e:
        state["error"] = str(e) or type(e).__name__
        checkpoint()
        log(f"run: stopped with error: {state['error']}")
        log("run: collecting whatever exists so far")
        if state.get("project_id") or state.get("simulation_id"):
            try:
                collect(c, out_dir, state.get("project_id"), state.get("simulation_id"), state.get("report_id"))
                state["export"] = do_export(out_dir, os.path.join(out_dir, "dashboard.html"), a.title)
            except Exception as ex:  # pragma: no cover
                log(f"run: partial export failed: {ex}")
        checkpoint()
        raise CLIError(state["error"])

    collect(c, out_dir, state.get("project_id"), state.get("simulation_id"), state.get("report_id"))
    state["export"] = do_export(out_dir, os.path.join(out_dir, "dashboard.html"), a.title)
    state["finished_at"] = datetime.now().isoformat()
    checkpoint()
    if a.close_env and state.get("simulation_id"):
        _try("close-env", lambda: c.data("POST", "/api/simulation/close-env",
                                          json={"simulation_id": state["simulation_id"], "timeout": 30}, timeout=60))
    return state


# --------------------------------------------------------------------------
# argparse
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mirofish", description="Headless CLI for the MiroFish swarm-simulation backend.")
    p.add_argument("--base-url", default=DEFAULT_BASE_URL, help="backend URL (default %(default)s, env MIROFISH_URL)")
    p.add_argument("--pretty", action="store_true", help="indent JSON output")
    p.add_argument("--lang", default="en", help="Accept-Language sent to the backend (en/zh), default en")
    # Same global flags accepted after the subcommand too (e.g. `list --pretty`).
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--base-url", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    common.add_argument("--pretty", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    common.add_argument("--lang", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    sub = p.add_subparsers(dest="cmd", required=True)
    _add = sub.add_parser
    sub.add_parser = lambda *a, **k: _add(*a, parents=[common], **k)  # type: ignore[assignment]

    def waitopts(sp, timeout=3600):
        sp.add_argument("--no-wait", action="store_true", help="return right after starting the async task")
        sp.add_argument("--timeout", type=float, default=timeout, help="max seconds to wait (default %(default)s)")
        sp.add_argument("--interval", type=float, default=5, help="poll interval seconds")

    sub.add_parser("health", help="check the backend is up")

    s = sub.add_parser("run", help="whole pipeline: upload -> graph -> simulate -> report -> export")
    s.add_argument("--seed", nargs="+", required=True, help="seed files (pdf/md/txt)")
    s.add_argument("--requirement", required=True, help="prediction question; text or @file")
    s.add_argument("--context", help="optional additional context; text or @file")
    s.add_argument("--platform", choices=["twitter", "reddit", "parallel"], default="parallel")
    s.add_argument("--max-rounds", type=int, default=10, help="cap simulation rounds (default %(default)s; cost!)")
    s.add_argument("--name", help="project name")
    s.add_argument("--out", help="output dir (default ./mirofish_runs/<timestamp>)")
    s.add_argument("--title", help="dashboard title")
    s.add_argument("--parallel", type=int, default=5, help="parallel profile generation")
    s.add_argument("--entity-types", nargs="+", help="only turn these entity types into agents (fewer agents = cheaper)")
    s.add_argument("--personas", help="persona spec JSON: audience segments (country, ages, role, count) and "
                                      "communities; see docs/personas.md")
    s.add_argument("--auto-personas", type=int, metavar="N",
                   help="let Claude plan about N personas (and their communities) from the requirement")
    s.add_argument("--no-graph-memory", action="store_true", help="don't write agent activity back into the graph")
    s.add_argument("--no-report", action="store_true", help="skip report generation")
    s.add_argument("--stop-after", choices=["prepare", "simulate"], help="stop the pipeline early")
    s.add_argument("--close-env", action="store_true", help="close the simulation env at the end (disables interviews)")
    s.add_argument("--timeout", type=float, default=3600, help="timeout per async step (s)")
    s.add_argument("--run-timeout", type=float, default=4 * 3600, help="timeout for the simulation run (s)")
    s.add_argument("--interval", type=float, default=5)

    s = sub.add_parser("upload", help="upload seed files + requirement; generates the ontology (creates a project)")
    s.add_argument("--seed", nargs="+", required=True)
    s.add_argument("--requirement", required=True, help="text or @file")
    s.add_argument("--context", help="text or @file")
    s.add_argument("--name")

    s = sub.add_parser("build-graph", help="build the knowledge graph for a project")
    s.add_argument("--project", required=True)
    s.add_argument("--force", action="store_true", help="rebuild even if a graph exists")
    s.add_argument("--chunk-size", type=int)
    s.add_argument("--chunk-overlap", type=int)
    waitopts(s)

    s = sub.add_parser("create-sim", help="create a simulation for a project")
    s.add_argument("--project", required=True)
    s.add_argument("--graph", help="graph id (default: the project's)")
    s.add_argument("--platform", choices=["twitter", "reddit", "parallel"], default="parallel")

    s = sub.add_parser("prepare", help="generate agent profiles + simulation config")
    s.add_argument("--simulation", required=True)
    s.add_argument("--parallel", type=int, default=5)
    s.add_argument("--entity-types", nargs="+")
    s.add_argument("--no-llm-profiles", action="store_true", help="rule-based profiles (cheaper, lower quality)")
    s.add_argument("--personas", help="persona spec JSON: audience segments (country, ages, role, count) and "
                                      "communities; see docs/personas.md")
    s.add_argument("--auto-personas", type=int, metavar="N",
                   help="let Claude plan about N personas (and their communities) from the requirement")
    s.add_argument("--force", action="store_true", help="regenerate even if prepared")
    waitopts(s)

    s = sub.add_parser("start", help="start the simulation (and wait for it by default)")
    s.add_argument("--simulation", required=True)
    s.add_argument("--platform", choices=["twitter", "reddit", "parallel"], default="parallel")
    s.add_argument("--max-rounds", type=int)
    s.add_argument("--no-graph-memory", action="store_true")
    s.add_argument("--no-force", action="store_true", help="don't restart/clean an already-run simulation")
    waitopts(s, 4 * 3600)

    s = sub.add_parser("wait", help="wait for a running simulation to finish")
    s.add_argument("--simulation", required=True)
    s.add_argument("--timeout", type=float, default=4 * 3600)
    s.add_argument("--interval", type=float, default=5)

    s = sub.add_parser("stop", help="force-stop a running simulation")
    s.add_argument("--simulation", required=True)

    s = sub.add_parser("close-env", help="gracefully close the simulation env (ends interview mode)")
    s.add_argument("--simulation", required=True)
    s.add_argument("--wait-s", type=int, default=30)

    s = sub.add_parser("status", help="show simulation / project / task status")
    s.add_argument("--simulation")
    s.add_argument("--project")
    s.add_argument("--task")

    s = sub.add_parser("report", help="generate (or reuse) the ReportAgent report and print it")
    s.add_argument("--simulation", required=True)
    s.add_argument("--force", action="store_true", help="regenerate")
    s.add_argument("--out", help="also write markdown here")
    s.add_argument("--markdown-only", action="store_true")
    waitopts(s)

    s = sub.add_parser("chat", help="ask the ReportAgent a question about a simulation")
    s.add_argument("--simulation", required=True)
    s.add_argument("--message", required=True, help="text or @file")
    s.add_argument("--history", help="JSON file to load/save chat history (multi-turn)")

    s = sub.add_parser("interview", help="interview one/several/all simulated agents (env must still be alive)")
    s.add_argument("--simulation", required=True)
    s.add_argument("--agent", type=int, nargs="+", help="agent id(s) (user_id from `profiles`)")
    s.add_argument("--all", action="store_true", help="ask every agent")
    s.add_argument("--prompt", required=True, help="text or @file")
    s.add_argument("--platform", choices=["twitter", "reddit"])
    s.add_argument("--wait-s", type=int, default=120, help="server-side interview timeout (s)")

    s = sub.add_parser("profiles", help="list agent profiles of a simulation")
    s.add_argument("--simulation", required=True)
    s.add_argument("--platform", choices=["twitter", "reddit"])
    s.add_argument("--brief", action="store_true")

    s = sub.add_parser("list", help="list projects / simulations / reports")
    s.add_argument("what", nargs="?", default="all", choices=["all", "projects", "simulations", "reports"])
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--full", action="store_true")

    s = sub.add_parser("export", help="build the self-contained HTML dashboard (+ report.md, summary.json)")
    s.add_argument("--run-dir", help="existing run dir to render offline, or where to save fetched JSON")
    s.add_argument("--project")
    s.add_argument("--simulation")
    s.add_argument("--report")
    s.add_argument("--out", help="output HTML path (default <run-dir>/dashboard.html)")
    s.add_argument("--title")

    s = sub.add_parser("live", help="serve a self-refreshing dashboard on localhost while a run progresses")
    s.add_argument("--run-dir", help="run dir to watch (default: the newest run under --runs-root)")
    s.add_argument("--runs-root", default="mirofish_runs", help="where runs live (default %(default)s)")
    s.add_argument("--project", help="watch this project instead of the run dir's manifest")
    s.add_argument("--simulation", help="watch this simulation instead of the run dir's manifest")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=int(os.environ.get("MIROFISH_LIVE_PORT", "5050")))
    s.add_argument("--interval", type=float, default=10, help="seconds between refreshes (default %(default)s)")
    s.add_argument("--offline", action="store_true", help="only re-render the saved JSON; never call the backend")
    s.add_argument("--title")
    return p


COMMANDS = {
    "health": cmd_health, "run": cmd_run, "upload": cmd_upload, "build-graph": cmd_build_graph,
    "create-sim": cmd_create_sim, "prepare": cmd_prepare, "start": cmd_start, "wait": cmd_wait,
    "stop": cmd_stop, "close-env": cmd_close_env, "status": cmd_status, "report": cmd_report,
    "chat": cmd_chat, "interview": cmd_interview, "profiles": cmd_profiles, "list": cmd_list,
    "export": cmd_export, "live": cmd_live,
}


def main(argv: Optional[List[str]] = None) -> int:
    a = build_parser().parse_args(argv)
    try:
        offline_export = a.cmd == "export" and a.run_dir and not (a.project or a.simulation or a.report)
        offline_live = a.cmd == "live" and a.offline
        c = None if (offline_export or offline_live) else Client(a.base_url, lang=a.lang)
        result = COMMANDS[a.cmd](c, a)
    except CLIError as e:
        print(json.dumps({"success": False, "error": str(e)}, ensure_ascii=False), flush=True)
        log(f"error: {e}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2 if a.pretty else None, default=str), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
