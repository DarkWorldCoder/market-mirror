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
import re
import os
import sys
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import exporter  # noqa: E402
import marketing  # noqa: E402
import market_cli  # noqa: E402

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
                rounds_done,
                lambda s: s.get("runner_status") == "failed",
                describe, "run", interval, timeout)


def rounds_done(s: Dict[str, Any]) -> bool:
    """Finished when the runner says so, or when every platform logged simulation_end and none is running:
    the process stays up afterwards on purpose (interview mode), so runner_status can stay 'running'."""
    if s.get("runner_status") in ("completed", "stopped"):
        return True
    done = [s.get("twitter_completed"), s.get("reddit_completed")]
    return any(done) and not s.get("twitter_running") and not s.get("reddit_running")


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

def read_messages(v: Optional[str]) -> List[str]:
    """Messages/ads to test: text or @file. JSON list, or blocks separated by '---', or one per line."""
    text = read_text_arg(v) if v else None
    if not text:
        return []
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return [str(x).strip() for x in data if str(x).strip()]
    except ValueError:
        pass
    parts = [p.strip() for p in text.split("\n---")] if "\n---" in text else text.splitlines()
    import re as _re
    return [_re.sub(r"^\s*(\d+[.)]|[-*])\s+", "", p).strip() for p in parts if p.strip()]


def step_survey(c: Client, simulation_id: str, out_dir: str, offer: str = "", goal: str = "",
                messages: Optional[List[str]] = None, split: bool = False, currency: Optional[str] = None,
                platform: Optional[str] = None, batch: int = 8, wait_s: int = 240,
                limit: Optional[int] = None, ssr: bool = True) -> Dict[str, Any]:
    """Ask every simulated person the buyer survey through the interview API; save survey.json.

    ssr: map the free-text answers to rating distributions on the backend (falls back to stated numbers)."""
    messages = messages or []
    if split and len(messages) < 2:
        raise CLIError("--split needs at least two messages (--messages @file)")
    cfg = _try("config", lambda: c.data("GET", f"/api/simulation/{simulation_id}/config")) or {}
    sim = _try("simulation", lambda: c.data("GET", f"/api/simulation/{simulation_id}")) or {}
    if not platform:
        platform = "reddit" if sim.get("enable_reddit", True) else "twitter"
    prof = _try("profiles", lambda: c.data("GET", f"/api/simulation/{simulation_id}/profiles",
                                           params={"platform": platform})) or {}
    meta = marketing.agent_meta({"config": cfg, f"profiles_{platform}": prof.get("profiles") or []})
    people = marketing.people_ids(meta)
    if limit:
        people = people[:limit]
    if not people:
        raise CLIError("survey: no simulated people found (prepare the simulation first)")
    assigned = marketing.assign_messages(people, len(messages)) if split else {}
    log(f"survey: asking {len(people)} people on {platform}"
        + (f", split test across {len(messages)} messages" if split else "")
        + (f", with price questions in {currency}" if currency else ""))
    responses: List[Dict[str, Any]] = []
    for start in range(0, len(people), max(1, batch)):
        chunk = people[start:start + batch]
        interviews = [{"agent_id": aid, "platform": platform,
                       "prompt": marketing.survey_prompt(offer, goal, messages, assigned.get(aid), currency)}
                      for aid in chunk]
        try:
            res = c.data("POST", "/api/simulation/interview/batch",
                         json={"simulation_id": simulation_id, "interviews": interviews, "platform": platform,
                               "timeout": wait_s}, timeout=wait_s + 90)
            texts = marketing.interview_texts(res)
        except CLIError as e:
            log(f"survey: batch {start // batch + 1} failed: {e}")
            texts = {}
        for aid in chunk:
            raw = texts.get(aid)
            responses.append({"agent_id": aid, "name": (meta.get(aid) or {}).get("name"),
                              "assigned_message": assigned.get(aid), "raw": raw,
                              "answer": marketing.parse_answer(raw, len(messages)) if raw else None})
        ok = sum(1 for r in responses if r["answer"])
        log(f"survey: {min(start + batch, len(people))}/{len(people)} asked, {ok} usable answers")
    ssr_info = step_ssr(c, responses) if ssr else {"used": False, "reason": "disabled (--no-ssr)"}
    survey = {"simulation_id": simulation_id, "offer": offer, "goal": goal, "messages": messages,
              "mode": "split" if split else ("pick" if messages else "none"), "currency": currency,
              "platform": platform, "asked_at": datetime.now().isoformat(), "ssr": ssr_info, "responses": responses}
    save_json(out_dir, "survey", survey)
    answered = sum(1 for r in responses if r["answer"])
    return {"survey": os.path.join(os.path.abspath(out_dir), "survey.json"), "asked": len(responses),
            "answered": answered, "ssr_rated": ssr_info.get("mapped", 0)}


def step_ssr(c: Client, responses: List[Dict[str, Any]], batch: int = 1000) -> Dict[str, Any]:
    """Semantic similarity rating (arXiv 2510.08338): the backend embeds each free-text answer with the local
    fastembed model and maps it to a 1-5 distribution. Attaches answer["ssr"]; never fails the survey."""
    items = marketing.ssr_items(responses)
    if not items:
        return {"used": False, "reason": "no free-text answers"}
    results: List[Dict[str, Any]] = []
    info: Dict[str, Any] = {}
    try:
        for start in range(0, len(items), batch):
            info = c.data("POST", "/api/simulation/ssr", json={"items": items[start:start + batch]}, timeout=600) or {}
            results += info.get("results") or []
    except CLIError as e:
        log(f"survey: free-text rating (SSR) unavailable, using the stated numbers instead: {e}")
        return {"used": False, "reason": str(e)[:300]}
    mapped = marketing.attach_ssr(responses, results)
    log(f"survey: mapped {len(results)} free-text answers from {mapped} people to rating distributions "
        f"(SSR, {info.get('model') or 'local embeddings'}; no Claude calls)")
    return {"used": True, "method": "semantic similarity rating, arXiv 2510.08338", "model": info.get("model"),
            "anchors_version": info.get("anchors_version"), "temperature": info.get("temperature"), "mapped": mapped}


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
    if simulation_id:
        for kind, name in (("feed-test", "feed_test"), ("analyst-panel", "analyst_panel")):
            if not os.path.exists(os.path.join(out_dir, f"{name}.json")):
                put(name, _try(name, lambda kind=kind: c.data("GET", f"/api/simulation/{simulation_id}/{kind}")))
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
        import re as _re
        stable = _re.sub(r'(generated_at\\?"\s*:\s*\\?")[^"\\]*|Generated [^<]*', "", page)
        digest = hashlib.sha1(stable.encode("utf-8")).hexdigest()
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


def step_events(c: Client, simulation_id: str, posts: Optional[List[Dict[str, Any]]],
                events: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Brand posts at round 0 and scheduled posts in later rounds, inside the simulation."""
    payload: Dict[str, Any] = {"simulation_id": simulation_id}
    if posts is not None:
        payload["posts"] = posts
    if events is not None:
        payload["events"] = events
    data = c.data("PUT", f"/api/simulation/{simulation_id}/events", json=payload, timeout=60)
    log(f"events: {len(data.get('initial_posts') or [])} brand post(s) at round 0, "
        f"{len(data.get('scheduled_events') or [])} scheduled event(s)")
    return data


def load_json_list(v: Optional[str], what: str) -> Optional[List[Dict[str, Any]]]:
    """@file.json or inline JSON list; also accepts {"posts": [...]} / {"events": [...]} wrappers."""
    if not v:
        return None
    raw = _load_json_arg(v)
    if isinstance(raw, dict):
        raw = raw.get(what) or raw.get("captions") or raw.get("items")
    if not isinstance(raw, list):
        raise CLIError(f"--{what} must be a JSON list (or @file with one)")
    out = []
    for i, x in enumerate(raw):
        if isinstance(x, dict) and x.get("text") and not x.get("content"):
            x = {**x, "content": x["text"]}        # captions.json entries
        if not isinstance(x, dict) or not x.get("content"):
            raise CLIError(f"--{what}[{i}] needs 'content' (or 'text')")
        out.append(x)
    return out


def load_persona_spec(path: Optional[str], auto: Optional[int], lite: bool = False) -> Optional[Dict[str, Any]]:
    """--personas FILE (JSON: segments, communities, ...) and/or --auto-personas N; --personas-lite skips interviews."""
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
    if lite and spec is not None:
        spec = {**spec, "personas_lite": True}
    return spec


def cmd_prepare(c: Client, a) -> Any:
    return step_prepare(c, a.simulation, wait=not a.no_wait, timeout=a.timeout, interval=a.interval,
                        parallel=a.parallel, entity_types=a.entity_types, use_llm=not a.no_llm_profiles,
                        force=a.force or bool(a.personas or a.auto_personas),
                        persona_spec=load_persona_spec(a.personas, a.auto_personas, a.personas_lite))


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


def cmd_survey(c: Client, a) -> Any:
    out_dir = a.run_dir or os.path.join("mirofish_runs", a.simulation)
    res = step_survey(c, a.simulation, out_dir, a.offer or "", a.goal or "", read_messages(a.messages),
                      a.split, a.pricing, a.platform, a.batch, a.wait_s, a.limit, not a.no_ssr)
    if not a.no_export:
        collect(c, out_dir, simulation_id=a.simulation)
        res["export"] = do_export(out_dir, os.path.join(out_dir, "dashboard.html"), a.title)
    return res


def _run_dir_for(a) -> str:
    return a.run_dir or os.path.join("mirofish_runs", a.simulation)


def _reexport(c: Optional[Client], a, out_dir: str, res: Dict[str, Any]) -> Dict[str, Any]:
    if not getattr(a, "no_export", False):
        if c is not None:
            collect(c, out_dir, simulation_id=a.simulation)
        res["export"] = do_export(out_dir, os.path.join(out_dir, "dashboard.html"), getattr(a, "title", None))
    return res


def cmd_feedtest(c: Client, a) -> Any:
    out_dir = _run_dir_for(a)
    try:
        res = market_cli.feedtest(c, a.simulation, a.creatives, out_dir, log, a.landing, a.benchmarks, a.waves,
                                  a.organic, a.limit, a.parallel, a.exposures, not a.no_attention_gate, a.seeds)
    except (ValueError, RuntimeError, OSError) as e:
        raise CLIError(str(e))
    return _reexport(c, a, out_dir, res)


def cmd_panel(c: Client, a) -> Any:
    out_dir = _run_dir_for(a)
    try:
        res = market_cli.panel(c, a.simulation, out_dir, log, a.analysts, read_text_arg(a.brief) or "",
                               load_bundle=exporter.load_run_dir)
    except (ValueError, RuntimeError, OSError) as e:
        raise CLIError(str(e))
    return _reexport(c, a, out_dir, res)


def cmd_ads_import(c: Optional[Client], a) -> Any:
    try:
        return market_cli.ads_import(a.file, a.out, a.json, a.title or "Past ad results")
    except (ValueError, OSError) as e:
        raise CLIError(str(e))


def cmd_backtest(c: Optional[Client], a) -> Any:
    try:
        with open(os.path.join(a.run_dir, "feed_test.json"), encoding="utf-8") as f:
            feed = json.load(f)
        with open(a.actuals, encoding="utf-8") as f:
            actual = json.load(f)
    except (OSError, ValueError) as e:
        raise CLIError(f"backtest: {e}")
    mapping = dict(m.split("=", 1) for m in (a.map or []) if "=" in m)
    res = market_cli.backtest(feed, actual, mapping)
    save_json(a.run_dir, "backtest", res)
    res["export"] = do_export(a.run_dir, os.path.join(a.run_dir, "dashboard.html"), None)
    return res


def _cfg_path(base: str, v: Any) -> Any:
    """Resolve a config value: '@path' or 'path.json' relative to the config file, else the value itself."""
    if isinstance(v, str):
        raw = v[1:] if v.startswith("@") else v
        cand = raw if os.path.isabs(raw) else os.path.join(base, raw)
        if (v.startswith("@") or raw.endswith((".json", ".md", ".txt", ".pdf", ".csv"))) and os.path.exists(cand):
            return cand
    return v


def cmd_market_test(c: Client, a) -> Any:
    """All-in-one market test from one JSON config: personas -> feed test -> rounds -> survey -> panel -> dashboard.

    Spend guard: unless the config has "approve_spend": true, it stops after creating the personas and prints
    how to continue (reuse "simulation_id" and set "approve_spend": true)."""
    path = a.config
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError) as e:
        raise CLIError(f"market-test: cannot read {path}: {e}")
    base = os.path.dirname(os.path.abspath(path))
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", str(cfg.get("name") or "market_test"))
    out_dir = _cfg_path(base, cfg.get("out")) if cfg.get("out") else os.path.join("mirofish_runs", name)
    os.makedirs(out_dir, exist_ok=True)
    state: Dict[str, Any] = {"out_dir": os.path.abspath(out_dir), "title": cfg.get("title") or name,
                             "started_at": datetime.now().isoformat()}
    manifest_path = os.path.join(out_dir, "run_manifest.json")
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, encoding="utf-8") as f:
                state = {**json.load(f), **{k: v for k, v in state.items() if k != "started_at"}}
        except (OSError, ValueError):
            pass

    def checkpoint():
        save_json(out_dir, "run_manifest", state)

    sid = cfg.get("simulation_id") or state.get("simulation_id")
    persona_spec = cfg.get("personas")
    if isinstance(persona_spec, str):
        with open(_cfg_path(base, persona_spec), encoding="utf-8") as f:
            persona_spec = json.load(f)
    if cfg.get("auto_personas"):
        persona_spec = {**(persona_spec or {}), "auto": True, "auto_total": int(cfg["auto_personas"])}
    if cfg.get("personas_lite") and persona_spec is not None:
        persona_spec = {**persona_spec, "personas_lite": True}
    if not sid:
        seeds = [_cfg_path(base, s) for s in cfg.get("seeds") or []]
        if not seeds:
            raise CLIError("market-test: config needs 'seeds' (documents) or an existing 'simulation_id'")
        req = cfg.get("requirement") or ""
        req_path = _cfg_path(base, req)
        requirement = read_text_arg("@" + req_path) if req_path != req or str(req).startswith("@") else req
        up = step_upload(c, seeds, requirement, cfg.get("title"), None)
        state["project_id"] = up["project_id"]
        save_json(out_dir, "ontology", up)
        checkpoint()
        g = step_build_graph(c, up["project_id"])
        state["graph_id"] = g.get("graph_id")
        sim = step_create_sim(c, up["project_id"], g.get("graph_id"), cfg.get("platform") or "parallel")
        sid = state["simulation_id"] = sim["simulation_id"]
        checkpoint()
        step_prepare(c, sid, parallel=int(cfg.get("parallel") or 5), persona_spec=persona_spec)
        collect(c, out_dir, state.get("project_id"), sid)
        state["export"] = do_export(out_dir, os.path.join(out_dir, "dashboard.html"), state["title"])
    state["simulation_id"] = sid
    checkpoint()
    if not cfg.get("approve_spend"):
        prof = _try("profiles", lambda: c.data("GET", f"/api/simulation/{sid}/profiles", params={"platform": "reddit"})) or {}
        people = [{"name": p.get("name"), "age": p.get("age"), "country": p.get("country"), "bio": str(p.get("bio") or "")[:120]}
                  for p in (prof.get("profiles") or [])][:60]
        return {"stage": "personas_ready", "simulation_id": sid, "out_dir": state["out_dir"], "people": people,
                "next": f'Review the people, then add "simulation_id": "{sid}" and "approve_spend": true to {path} and run again.'}

    steps = []
    posts = cfg.get("posts")
    events = cfg.get("events")
    if isinstance(posts, str):
        posts = load_json_list("@" + str(_cfg_path(base, posts)), "posts")
    if isinstance(events, str):
        events = load_json_list("@" + str(_cfg_path(base, events)), "events")
    if posts is not None or events is not None:
        step_events(c, sid, posts, events)
        steps.append("events")
    creatives = cfg.get("creatives")
    if creatives:
        cpath = _cfg_path(base, creatives)
        arg = "@" + cpath if isinstance(cpath, str) and os.path.exists(cpath) else json.dumps(creatives)
        state["feed_test"] = market_cli.feedtest(c, sid, arg, out_dir, log, None, None,
                                                 int(cfg.get("waves") or 3), int(cfg.get("organic") or 5), None,
                                                 int(cfg.get("parallel") or 8), int(cfg.get("exposures") or 2), True,
                                                 int(cfg.get("seeds_n") or 1))
        steps.append("feed_test")
        checkpoint()
    survey = cfg.get("survey")
    rounds = int(cfg.get("rounds") or 0)
    if survey and rounds < 1:
        rounds = 1                      # the survey interviews a live simulation environment
    if rounds:
        rs = step_start(c, sid, cfg.get("platform") or "parallel", rounds, graph_memory=True, force=True)
        state["runner_status"] = rs.get("runner_status")
        steps.append(f"{rounds} rounds")
        checkpoint()
    if survey:
        msgs = survey.get("messages")
        if isinstance(msgs, str):
            mp = _cfg_path(base, msgs)
            msgs = read_messages("@" + mp) if mp != msgs or msgs.startswith("@") else read_messages(msgs)
        state["survey"] = step_survey(c, sid, out_dir, survey.get("offer") or "", survey.get("goal") or "",
                                      msgs or [], bool(survey.get("split")), survey.get("pricing"),
                                      ssr=survey.get("ssr", True) is not False)
        steps.append("survey")
        checkpoint()
    panel_cfg = cfg.get("panel")
    if panel_cfg:
        collect(c, out_dir, state.get("project_id"), sid)
        state["panel"] = market_cli.panel(c, sid, out_dir, log, int(panel_cfg.get("analysts") or 5),
                                          str(panel_cfg.get("brief") or ""), load_bundle=exporter.load_run_dir)
        steps.append("panel")
    if cfg.get("report"):
        rep = step_report(c, sid)
        state["report_id"] = rep.get("report_id")
        steps.append("report")
    collect(c, out_dir, state.get("project_id"), sid, state.get("report_id"))
    state["export"] = do_export(out_dir, os.path.join(out_dir, "dashboard.html"), state["title"])
    state["finished_at"] = datetime.now().isoformat()
    checkpoint()
    summary = {}
    try:
        with open(state["export"]["summary_json"], encoding="utf-8") as f:
            summary = json.load(f)
    except (OSError, ValueError, KeyError):
        pass
    return {"stage": "done", "steps": steps, "simulation_id": sid, "dashboard": state["export"]["html"],
            "decision": summary.get("decision"), "verdicts": (summary.get("marketing") or {}).get("verdicts")}


def cmd_captions(c: Client, a) -> Any:
    brief = read_text_arg(a.brief) or ""
    objections: List[str] = []
    if a.run_dir:
        try:
            with open(os.path.join(a.run_dir, "summary.json"), encoding="utf-8") as f:
                mk = (json.load(f).get("marketing") or {})
            objections = [o.get("label") for o in (mk.get("objections") or []) if o.get("label")][:6]
        except (OSError, ValueError):
            log(f"captions: no summary.json in {a.run_dir}; writing without objections")
    data = c.data("POST", "/api/simulation/captions",
                  json={"brief": brief, "platform": a.platform, "n": a.n, "audience": a.audience,
                        "objections": objections, "tone": a.tone, "language": a.language}, timeout=180)
    caps = data.get("captions") or []
    out = a.out or f"captions_{a.platform}.json"
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"platform": a.platform, "captions": caps,
                   "creatives": [{"id": cp["id"], "platform": a.platform, "format": cp.get("format") or "image",
                                  "page": a.page or "Brand", "text": cp["text"], "headline": cp.get("hook"),
                                  "cta": cp.get("cta"), "media": cp.get("media"), "name": cp.get("angle")} for cp in caps],
                   "posts": [{"agent": a.page or 0, "platform": a.platform if a.platform in ("twitter", "reddit") else "both",
                              "content": cp["text"]} for cp in caps]}, f, ensure_ascii=False, indent=2)
    log(f"captions: wrote {len(caps)} to {out} (use as --creatives, --posts or --messages)")
    return {"file": os.path.abspath(out), "captions": [{"angle": cp["angle"], "hook": cp["hook"]} for cp in caps]}


def cmd_run(c: Client, a) -> Any:
    requirement = read_text_arg(a.requirement)
    load_persona_spec(a.personas, a.auto_personas, a.personas_lite)  # fail fast on a bad spec file
    load_json_list(a.posts, "posts"); load_json_list(a.events, "events")
    if a.split and len(read_messages(a.messages)) < 2:
        raise CLIError("--split needs at least two messages (--messages @file)")
    out_dir = a.out or default_run_dir()
    os.makedirs(out_dir, exist_ok=True)
    log(f"run: artifacts -> {os.path.abspath(out_dir)}")
    state: Dict[str, Any] = {"out_dir": os.path.abspath(out_dir), "started_at": datetime.now().isoformat(),
                             **({"title": a.title} if a.title else {})}

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
                     persona_spec=load_persona_spec(a.personas, a.auto_personas, a.personas_lite))
        posts, events = load_json_list(a.posts, "posts"), load_json_list(a.events, "events")
        if posts is not None or events is not None:
            step_events(c, sim["simulation_id"], posts, events)
        if a.stop_after == "prepare":
            log("run: --stop-after prepare; not starting the simulation")
        else:
            rs = step_start(c, sim["simulation_id"], a.platform, a.max_rounds, graph_memory=not a.no_graph_memory,
                            force=True, timeout=a.run_timeout, interval=a.interval)
            state["runner_status"] = rs.get("runner_status")
            checkpoint()
            if a.survey or a.offer or a.goal or a.messages or a.pricing:
                state["survey"] = step_survey(c, sim["simulation_id"], out_dir, a.offer or "", a.goal or "",
                                              read_messages(a.messages), a.split, a.pricing)
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
    s.add_argument("--personas-lite", action="store_true", help="skip the life interviews (cheaper, shallower people)")
    s.add_argument("--no-graph-memory", action="store_true", help="don't write agent activity back into the graph")
    s.add_argument("--no-report", action="store_true", help="skip report generation")
    s.add_argument("--stop-after", choices=["prepare", "simulate"], help="stop the pipeline early")
    s.add_argument("--posts", help="brand posts at round 0: @posts.json [{agent, platform?, content}] (captions.json works)")
    s.add_argument("--events", help="scheduled posts: @events.json [{round, agent, platform?, content, label?}]")
    s.add_argument("--survey", action="store_true", help="after the rounds, ask everyone the buyer survey")
    s.add_argument("--offer", help="what is being sold or promoted, e.g. 'Acme free practice test'")
    s.add_argument("--goal", help="the conversion you care about, e.g. 'sign up for the free practice test'")
    s.add_argument("--messages", help="ads/messages to test: text or @file (JSON list, '---' blocks, or one per line)")
    s.add_argument("--split", action="store_true", help="split test: each person sees one message (needs 2+)")
    s.add_argument("--pricing", metavar="CURRENCY", help="add price-sensitivity questions in this currency")
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
    s.add_argument("--personas-lite", action="store_true", help="skip the life interviews (cheaper, shallower people)")
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

    s = sub.add_parser("survey", help="buyer survey of every simulated person: intent, objections, best message, price")
    s.add_argument("--simulation", required=True)
    s.add_argument("--offer", help="what is being sold or promoted, e.g. 'Acme free practice test'")
    s.add_argument("--goal", help="the conversion you care about, e.g. 'sign up for the free practice test'")
    s.add_argument("--messages", help="ads/messages to test: text or @file (JSON list, '---' blocks, or one per line)")
    s.add_argument("--split", action="store_true", help="split test: each person sees one message (needs 2+)")
    s.add_argument("--pricing", metavar="CURRENCY", help="add price-sensitivity questions in this currency")
    s.add_argument("--platform", choices=["twitter", "reddit"], help="which platform's agents to ask (default reddit)")
    s.add_argument("--batch", type=int, default=8, help="people per interview call (default %(default)s)")
    s.add_argument("--wait-s", type=int, default=240, help="server-side timeout per batch (s)")
    s.add_argument("--limit", type=int, help="only ask the first N people (quick, cheap check)")
    s.add_argument("--no-ssr", action="store_true",
                   help="skip mapping free-text answers to rating distributions (use the stated numbers only)")
    s.add_argument("--run-dir", help="where survey.json and the dashboard go (default mirofish_runs/<simulation>)")
    s.add_argument("--no-export", action="store_true", help="don't re-collect and re-export the dashboard")
    s.add_argument("--title")

    s = sub.add_parser("feedtest", help="put ads into simulated Facebook/Instagram/Reddit/TikTok/LinkedIn/X feeds")
    s.add_argument("--simulation", required=True)
    s.add_argument("--creatives", required=True, help="@ads.json: list of ads, or {creatives, landing, benchmarks}")
    s.add_argument("--landing", help="@landing.json: page model {load_seconds, language, shows, form_fields, price}")
    s.add_argument("--benchmarks", help="@past_ads.json from ads-import, or {platform: {cpm, ctr, budget, currency}}")
    s.add_argument("--waves", type=int, default=3, help="later waves see earlier reactions and comments (default %(default)s)")
    s.add_argument("--organic", type=int, default=5, help="organic posts around each ad (default %(default)s)")
    s.add_argument("--exposures", type=int, default=2, help="times each person scrolls past the ad, with wear-out (default %(default)s)")
    s.add_argument("--no-attention-gate", action="store_true",
                   help="ask about every exposure instead of deciding in code whether the ad is noticed")
    s.add_argument("--limit", type=int, help="only the first N personas (quick, cheap check)")
    s.add_argument("--seeds", type=int, default=1,
                   help="repeat with N different seeds and report each creative's range (N x the cost; default %(default)s)")
    s.add_argument("--parallel", type=int, default=8)
    s.add_argument("--run-dir", help="default mirofish_runs/<simulation>")
    s.add_argument("--no-export", action="store_true")
    s.add_argument("--title")

    s = sub.add_parser("panel", help="independent, anonymized analyst panel over posts, comments, feed test and survey")
    s.add_argument("--simulation", required=True)
    s.add_argument("--analysts", type=int, default=5, help="2-9 analysts, each with a different lens")
    s.add_argument("--brief", help="what you want to decide (text or @file)")
    s.add_argument("--run-dir", help="default mirofish_runs/<simulation>")
    s.add_argument("--no-export", action="store_true")
    s.add_argument("--title")

    s = sub.add_parser("ads-import", help="turn a Meta/Google Ads export (CSV/JSON) into a seed file + benchmarks")
    s.add_argument("file", help="ads export: CSV from Ads Manager / Google Ads, or JSON rows")
    s.add_argument("--out", required=True, help="seed markdown to write, e.g. scenarios/x/past_ads.md")
    s.add_argument("--json", help="summary + benchmarks JSON (default next to --out)")
    s.add_argument("--title")

    s = sub.add_parser("backtest", help="compare simulated creative rankings with real ad results")
    s.add_argument("--run-dir", required=True, help="run folder with feed_test.json")
    s.add_argument("--actuals", required=True, help="JSON written by ads-import")
    s.add_argument("--map", nargs="*", help="creative_id=Real ad name pairs (or set 'real_ad' on each creative)")

    s = sub.add_parser("captions", help="write platform-native post/ad captions from a brief (and a run's objections)")
    s.add_argument("--brief", required=True, help="text or @brief.md")
    s.add_argument("--platform", default="instagram", choices=["instagram", "facebook", "tiktok", "reddit", "linkedin", "x", "twitter"])
    s.add_argument("--n", type=int, default=6)
    s.add_argument("--audience", help="who the captions are for")
    s.add_argument("--language", help="e.g. 'Hinglish', 'Taglish', 'Bahasa Indonesia'")
    s.add_argument("--tone")
    s.add_argument("--page", help="brand/page name used in creatives and posts")
    s.add_argument("--run-dir", help="fold in the top objections from this run's summary.json")
    s.add_argument("--out", help="output JSON (default captions_<platform>.json)")

    s = sub.add_parser("market-test", help="all-in-one: personas -> feed test -> rounds -> survey -> panel -> dashboard")
    s.add_argument("config", help="JSON config: name, title, seeds, requirement, personas, creatives, rounds, seeds_n "
                                  "(feed-test repeats), survey, panel, approve_spend (see README)")

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
    "export": cmd_export, "live": cmd_live, "survey": cmd_survey, "feedtest": cmd_feedtest,
    "panel": cmd_panel, "ads-import": cmd_ads_import, "backtest": cmd_backtest, "market-test": cmd_market_test,
    "captions": cmd_captions,
}


def main(argv: Optional[List[str]] = None) -> int:
    a = build_parser().parse_args(argv)
    try:
        offline_export = a.cmd == "export" and a.run_dir and not (a.project or a.simulation or a.report)
        offline_live = a.cmd == "live" and a.offline
        offline = offline_export or offline_live or a.cmd in ("ads-import", "backtest")
        c = None if offline else Client(a.base_url, lang=a.lang)
        result = COMMANDS[a.cmd](c, a)
    except CLIError as e:
        print(json.dumps({"success": False, "error": str(e)}, ensure_ascii=False), flush=True)
        log(f"error: {e}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2 if a.pretty else None, default=str), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
