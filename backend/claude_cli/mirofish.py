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
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import exporter  # noqa: E402
import marketing  # noqa: E402
import market_cli  # noqa: E402
import live_view  # noqa: E402
import quota  # noqa: E402

DEFAULT_BASE_URL = os.environ.get("MIROFISH_URL", "http://localhost:5001")
TERMINAL_RUN = {"completed", "stopped", "failed"}


class CLIError(RuntimeError):
    pass


DEFAULT_PARALLEL = max(4, min(16, (os.cpu_count() or 4)))   # LLM calls in flight for profiles / feed test


PROGRESS_PATH: Optional[str] = None   # <run dir>/progress.log while a pipeline runs (the live control room tails it)


def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", file=sys.stderr, flush=True)
    if PROGRESS_PATH:
        try:
            with open(PROGRESS_PATH, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] {msg}\n")
        except OSError:
            pass


def progress_to(run_dir: Optional[str]) -> None:
    """Also write log lines to <run_dir>/progress.log (None stops it)."""
    global PROGRESS_PATH
    PROGRESS_PATH = os.path.join(run_dir, live_view.PROGRESS_FILE) if run_dir else None


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
        self.memory_scope = "default"   # behaviour-memory scope the tests read and write ("off" disables; study cells set their own)

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
                 force: bool = False, persona_spec: Optional[Dict[str, Any]] = None,
                 resume_only: bool = False) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"simulation_id": simulation_id, "use_llm_for_profiles": use_llm,
                               "parallel_profile_count": parallel, "force_regenerate": force,
                               "resume_only": resume_only}
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
                platform: Optional[str] = None, batch: int = 40, wait_s: int = 600,
                limit: Optional[int] = None, ssr: bool = True, retest: int = 0,
                seed: int = 11) -> Dict[str, Any]:
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
    assigned = marketing.assign_messages(people, len(messages), seed=seed) if split else {}
    log(f"survey: asking {len(people)} people on {platform}"
        + (f", split test across {len(messages)} messages" if split else "")
        + (f", with price questions in {currency}" if currency else ""))
    responses: List[Dict[str, Any]] = []
    for start in range(0, len(people), max(1, batch)):
        quota.wait_if_paused(log)          # don't spend batches while the model account is paused
        chunk = people[start:start + batch]
        interviews = [{"agent_id": aid, "platform": platform,
                       "prompt": marketing.survey_prompt(offer, goal, messages, assigned.get(aid), currency)}
                      for aid in chunk]
        try:
            scope = getattr(c, "memory_scope", None)
            res = c.data("POST", "/api/simulation/interview/batch",
                         json={"simulation_id": simulation_id, "interviews": interviews, "platform": platform,
                               "timeout": wait_s, **({"memory_scope": scope} if scope and scope != "off" else {})},
                         timeout=wait_s + 90)
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
    retest_info = None
    if retest:
        # test-retest reliability (the figure the persona papers report): re-ask some people "a week later"
        import random as _random
        answered = [r for r in responses if r.get("answer")]
        sample = _random.Random(seed).sample(answered, min(int(retest), len(answered)))
        again = [{"agent_id": r["agent_id"], "platform": platform,
                  "prompt": "A week has passed since a researcher last asked you about this. They ask again; answer afresh "
                            "as you feel today, without trying to remember what you said.\n\n"
                            + marketing.survey_prompt(offer, goal, messages, assigned.get(r["agent_id"]), currency)} for r in sample]
        agree = interest_close = 0
        if again:
            try:
                res = c.data("POST", "/api/simulation/interview/batch",
                             json={"simulation_id": simulation_id, "interviews": again, "platform": platform, "timeout": wait_s},
                             timeout=wait_s + 90)
                texts = marketing.interview_texts(res)
            except CLIError as e:
                log(f"survey: retest failed: {e}")
                texts = {}
            for r in sample:
                a2 = marketing.parse_answer(texts.get(r["agent_id"]), len(messages)) if texts.get(r["agent_id"]) else None
                if a2:
                    agree += int(a2.get("would_convert") == r["answer"].get("would_convert"))
                    if a2.get("interest") is not None and r["answer"].get("interest") is not None:
                        interest_close += int(abs(a2["interest"] - r["answer"]["interest"]) <= 2)
                    r["retest_answer"] = a2
        retest_info = {"n": len(sample), "agreement_pct": round(100.0 * agree / len(sample), 1) if sample else None,
                       "interest_within_2_pct": round(100.0 * interest_close / len(sample), 1) if sample else None}
        log(f"survey: retest of {len(sample)} people: {retest_info['agreement_pct']}% gave the same verdict")
    scope = getattr(c, "memory_scope", None)
    if scope and scope != "off":
        _try("memory", lambda: c.data("POST", f"/api/simulation/{simulation_id}/memory", json={
            "scope": scope, "survey": {"offer": offer, "responses": [{"agent_id": r["agent_id"], "answer": r.get("answer")}
                                                                    for r in responses if r.get("answer")]}}))
    survey = {"simulation_id": simulation_id, "offer": offer, "goal": goal, "messages": messages,
              "mode": "split" if split else ("pick" if messages else "none"), "currency": currency,
              "platform": platform, "assignment_seed": seed if split else None,
              "asked_at": datetime.now().isoformat(), "ssr": ssr_info, "retest": retest_info,
              "responses": responses}
    save_json(out_dir, "survey", survey)
    answered = sum(1 for r in responses if r["answer"])
    if responses and not answered:
        raise RuntimeError("Survey produced no usable answers. Check provider authentication and the interview environment; diagnostic responses were saved for retry.")
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
        for kind, name in (("feed-test", "feed_test"), ("analyst-panel", "analyst_panel"),
                           ("market-report", "market_report"), ("feed-story", "feed_story"), ("pitch", "pitch"), ("email-test", "email_test")):
            # the feed story grows with every round, so it is always refetched; the others are written once
            if name == "feed_story" or not os.path.exists(os.path.join(out_dir, f"{name}.json")):
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
font:12px/1.4 system-ui,sans-serif;background:rgba(20,20,20,.85);color:#fff;max-width:calc(100vw - 24px)"><span>%s</span>
 · <a href="/live" style="color:#f3d64b;text-decoration:none">Live control room ↗</a></div>
<script>(function(){
var v=%s,ms=%d;
try{var y=sessionStorage.getItem('mf_live_y');if(y){sessionStorage.removeItem('mf_live_y');window.scrollTo(0,+y);}}catch(e){}
function tick(){fetch('/__live/state',{cache:'no-store'}).then(function(r){return r.json();}).then(function(s){
var b=document.querySelector('#mf-live span');if(b)b.textContent=s.label;
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
    if status == "running":             # the live runner wins over what an earlier attempt left in the manifest
        cur, total = rs.get("current_round"), rs.get("total_rounds")
        return f"Simulating round {cur}/{total}" if cur is not None and total else "Simulating"
    if manifest.get("runner_status") or status in TERMINAL_RUN:
        return "Simulation finished; writing the report"
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
        # a finished run is frozen: its simulation may be reused (studies, later tests), and collecting again
        # would overwrite this run's saved actions and status with the newer activity
        if self.c is not None and (pid or sid) and not m.get("finished_at"):
            with _quiet_logs():
                collect(self.c, self.run_dir, pid, sid, m.get("report_id"))
        rs = None
        try:
            with open(os.path.join(self.run_dir, "run_status.json"), encoding="utf-8") as f:
                rs = json.load(f)
        except (OSError, ValueError):
            pass
        os.makedirs(self.run_dir, exist_ok=True)
        bundle = exporter.load_run_dir(self.run_dir)
        label = live_stage(m, rs)
        # Render timestamps also live inside compressed downloads. Hash the
        # saved inputs, not freshly generated HTML, to avoid reload loops.
        stable = json.dumps({"bundle": bundle, "title": self.title}, sort_keys=True, ensure_ascii=False, default=str)
        digest = hashlib.sha1(stable.encode("utf-8")).hexdigest()
        with self.lock:
            if digest == self._digest:
                self.label = label
                return
        page, _md, _summary = exporter.render_dashboard(bundle, title=self.title)
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
            if path == "/__live/feed":
                data = live_view.feed(live.run_dir, live.state().get("label", ""))
                return self._send(json.dumps(data, ensure_ascii=False, default=str).encode("utf-8"), "application/json")
            if path in ("/live", "/live/"):
                return self._send(live_view.CONTROL_HTML.encode("utf-8"), "text/html; charset=utf-8")
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
    log(f"live: serving {os.path.abspath(live.run_dir)} at http://{host}:{port}/ (refresh every {interval:g}s, Ctrl+C to stop); "
        f"live control room at http://{host}:{port}/live")
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
    raw = market_cli._load_json_arg(v)
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
    if a.resume_only and (a.force or a.personas or a.auto_personas):
        raise CLIError("--resume-only uses the saved persona plan; omit --force, --personas and --auto-personas")
    return step_prepare(c, a.simulation, wait=not a.no_wait, timeout=a.timeout, interval=a.interval,
                        parallel=a.parallel, entity_types=a.entity_types, use_llm=not a.no_llm_profiles,
                        force=a.force or bool(a.personas or a.auto_personas),
                        persona_spec=load_persona_spec(a.personas, a.auto_personas, a.personas_lite),
                        resume_only=a.resume_only)


def cmd_start(c: Client, a) -> Any:
    platform = a.platform
    if platform == "auto":
        state = c.data("GET", f"/api/simulation/{a.simulation}")
        twitter, reddit = bool(state.get("enable_twitter")), bool(state.get("enable_reddit"))
        platform = "parallel" if twitter and reddit else "twitter" if twitter else "reddit" if reddit else ""
        if not platform:
            raise CLIError("simulation has no prepared platform")
    return step_start(c, a.simulation, platform, a.max_rounds, graph_memory=not a.no_graph_memory,
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
    if a.engine == "market":
        out_dir = a.run_dir or os.path.join("mirofish_runs", a.simulation)
        if not os.path.exists(os.path.join(out_dir, "summary.json")):
            collect(c, out_dir, simulation_id=a.simulation)
            do_export(out_dir, os.path.join(out_dir, "dashboard.html"), a.title)
        try:
            res = market_cli.report(c, a.simulation, out_dir, log, load_bundle=exporter.load_run_dir, brand=a.brand or "")
        except (ValueError, RuntimeError, OSError) as e:
            raise CLIError(str(e))
        if a.out:
            with open(a.out, "w", encoding="utf-8") as f, open(res["market_report"], encoding="utf-8") as src:
                f.write(src.read())
        return _reexport(c, a, out_dir, res)
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
                      a.split, a.pricing, a.platform, a.batch, a.wait_s, a.limit, not a.no_ssr,
                      retest=a.retest, seed=a.assignment_seed)
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


def cmd_website_test(c: Client, a) -> Any:
    """Drive a real URL with prepared personas and export browser evidence."""
    from app.services import website_test
    from pathlib import Path
    import uuid
    try:
        spec = market_cli._load_json_arg(a.spec) if a.spec else {}
        spec = dict(spec)
        for arg, key in (("url", "url"), ("goal", "goal"), ("task", "task"),
                         ("limit", "max_personas"), ("steps", "max_steps"), ("device", "device"),
                         ("headless", "headless"), ("record_video", "record_video"),
                         ("record_trace", "record_trace"), ("recoveries", "max_recoveries"),
                         ("observation_mode", "observation_mode"), ("observation_text_chars", "observation_text_chars"),
                         ("max_model_calls", "max_model_calls"), ("max_input_tokens", "max_input_tokens"),
                         ("max_elapsed_s", "max_elapsed_s"), ("loop_limit", "loop_limit")):
            value = getattr(a, arg, None)
            if value is not None:
                spec[key] = value
        spec = website_test.normalize(spec)
    except (ValueError, OSError, TypeError) as error:
        raise CLIError(f"website-test: {error}") from error
    started = c.data("POST", "/api/simulation/website-test", json={"simulation_id": a.simulation, "spec": spec})
    try:
        market_cli.wait_task(c, started["task_id"], "website-test", log)
    except RuntimeError as error:
        raise CLIError(str(error)) from error
    result = c.data("GET", f"/api/simulation/{a.simulation}/website-test", params={"run_id": started["run_id"]})
    folder = Path(a.out or os.path.join("mirofish_runs", f"{a.simulation}_website_{uuid.uuid4().hex[:6]}")).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    dashboard = folder / ("website_dashboard.html" if (folder / "dashboard.html").exists() else "dashboard.html")
    dashboard.write_text(website_test.render_report(result), encoding="utf-8")
    result["files"]["exported_dashboard"] = str(dashboard)
    (folder / "website_test.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": result["status"], "run_id": started["run_id"], "summary": result["summary"],
            "milestones": result["milestones"], "dashboard": str(dashboard),
            "result_file": str(folder / "website_test.json"), "interpretation": result["interpretation"]}


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
        if isinstance(actual, dict) and "observations" in actual:
            import actuals as actuals_importer
            actual = actuals_importer.ad_backtest_table(actual)
    except (OSError, ValueError) as e:
        raise CLIError(f"backtest: {e}")
    mapping = dict(m.split("=", 1) for m in (a.map or []) if "=" in m)
    res = market_cli.backtest(feed, actual, mapping)
    save_json(a.run_dir, "backtest", res)
    pairs = [{"sim": p.get("sim_ctr"), "real": p.get("real_ctr"), "label": p.get("creative")} for p in res.get("pairs") or []
             if p.get("sim_ctr") is not None and p.get("real_ctr") is not None]
    if pairs and c is not None:
        try:
            c.data("POST", "/api/simulation/calibration-pairs", json={"brand": a.brand or "", "metric": "ctr", "pairs": pairs, "source": "backtest"}, timeout=60)
            res["stored_pairs"] = len(pairs)
        except CLIError as e:
            log(f"backtest: could not store calibration pairs: {e}")
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
    if cfg.get("memory_scope") is not None:
        c.memory_scope = "off" if cfg["memory_scope"] in (False, "off", "none") else str(cfg["memory_scope"])
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", str(cfg.get("name") or "market_test"))
    out_dir = _cfg_path(base, cfg.get("out")) if cfg.get("out") else os.path.join("mirofish_runs", name)
    os.makedirs(out_dir, exist_ok=True)
    progress_to(out_dir)
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

    state.pop("finished_at", None)
    sid = cfg.get("simulation_id") or state.get("simulation_id")
    research_ref = cfg.get("research")
    if isinstance(research_ref, str):
        research_path = research_ref if os.path.isabs(research_ref) else os.path.join(base, research_ref)
        research_path = research_path if research_path.endswith("research.json") else os.path.join(os.path.dirname(research_path) if research_path.endswith(".json") else research_path, "research.json")
        if os.path.isfile(research_path):
            with open(research_path, encoding="utf-8") as f:
                save_json(out_dir, "research", json.load(f))
    plan_ref = cfg.get("campaign_plan")
    if isinstance(plan_ref, str):
        plan_path = plan_ref if os.path.isabs(plan_ref) else os.path.join(base, plan_ref)
        if os.path.isfile(plan_path):
            with open(plan_path, encoding="utf-8") as f:
                save_json(out_dir, "campaign_plan", json.load(f))
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
        research_dir = cfg.get("research")
        if research_dir and not os.path.isabs(research_dir):
            research_dir = os.path.normpath(os.path.join(base, research_dir))   # relative to the config file
        if research_dir:
            try:
                vpath = research_dir if research_dir.endswith(".json") else os.path.join(research_dir, "voices.json")
                with open(vpath, encoding="utf-8") as f:
                    voices = json.load(f)
                c.data("PUT", f"/api/graph/project/{up['project_id']}/voices", json={"voices": voices}, timeout=60)
                rpath = os.path.join(os.path.dirname(vpath), "research.json")
                if os.path.exists(rpath):
                    with open(rpath, encoding="utf-8") as f:
                        save_json(out_dir, "research", json.load(f))
                log(f"research: {len(voices)} real voices attached to the project")
            except (OSError, ValueError, CLIError) as e:
                log(f"research skipped: {e}")
        if cfg.get("understand", True):
            try:
                prof = step_profile(c, up["project_id"], cfg.get("url"), None, False, cfg.get("brand"))
                save_json(out_dir, "product_profile", prof)
                state["profile"] = {"name": prof.get("name"), "one_liner": prof.get("one_liner"), "method": prof.get("method")}
            except CLIError as e:
                log(f"understand skipped: {e}")
        g = step_build_graph(c, up["project_id"])
        state["graph_id"] = g.get("graph_id")
        sim = step_create_sim(c, up["project_id"], g.get("graph_id"), cfg.get("platform") or "parallel")
        sid = state["simulation_id"] = sim["simulation_id"]
        checkpoint()
        step_prepare(c, sid, parallel=int(cfg.get("parallel") or DEFAULT_PARALLEL), persona_spec=persona_spec)
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
        if cfg.get("resume_steps") and state.get("feed_test") and market_cli.saved_step_usable(out_dir, "feed_test"):
            log("market-test: reusing completed feed test in this study cell")
        else:
            cpath = _cfg_path(base, creatives)
            arg = "@" + cpath if isinstance(cpath, str) and os.path.exists(cpath) else json.dumps(creatives)
            state["feed_test"] = quota.guarded("the feed test", lambda: market_cli.feedtest(
                c, sid, arg, out_dir, log, None, None, int(cfg.get("waves") or 3), int(cfg.get("organic") or 5), None,
                int(cfg.get("parallel") or DEFAULT_PARALLEL), int(cfg.get("exposures") or 2), True,
                int(cfg.get("seeds_n") or 1), int(cfg.get("seed") or 5)), log)
        steps.append("feed_test")
        checkpoint()
    emails = cfg.get("emails")
    if emails:
        epath = _cfg_path(base, emails)
        earg = "@" + epath if isinstance(epath, str) and os.path.exists(epath) else json.dumps(emails)
        try:
            state["email_test"] = quota.guarded("the email test", lambda: market_cli.emailtest(
                c, sid, earg, out_dir, log, int(cfg.get("seed") or 5), int(cfg.get("parallel") or DEFAULT_PARALLEL),
                cfg.get("list_size")), log)
            steps.append("email_test")
        except (ValueError, RuntimeError, CLIError) as e:
            log(f"email test skipped: {e}")
        checkpoint()
    survey = cfg.get("survey")
    rounds = int(cfg.get("rounds") or 0)
    if survey and rounds < 1:
        rounds = 1                      # the survey interviews a live simulation environment
    if rounds:
        live = _try("environment", lambda: c.data("POST", "/api/simulation/env-status", json={"simulation_id": sid})) if cfg.get("resume_steps") else None
        if cfg.get("resume_steps") and state.get("runner_status") in ("completed", "running") and (live or {}).get("env_alive"):
            log("market-test: reusing live interview environment in this study cell")
        else:
            rs = quota.guarded("the social rounds", lambda: step_start(
                c, sid, cfg.get("platform") or "parallel", rounds, graph_memory=bool(cfg.get("graph_memory", True)), force=True), log)
            state["runner_status"] = rs.get("runner_status")
        steps.append(f"{rounds} rounds")
        checkpoint()
    if survey:
        if cfg.get("resume_steps") and state.get("survey") and market_cli.saved_step_usable(out_dir, "survey"):
            log("market-test: reusing completed survey in this study cell")
        else:
            msgs = survey.get("messages")
            if isinstance(msgs, str):
                mp = _cfg_path(base, msgs)
                # Study cells use absolute paths. They still denote files even when
                # _cfg_path returns the same string, so always read an existing file.
                msgs = read_messages("@" + mp) if isinstance(mp, str) and os.path.isfile(mp) else read_messages(msgs)
            state["survey"] = quota.guarded("the survey", lambda: step_survey(
                c, sid, out_dir, survey.get("offer") or "", survey.get("goal") or "", msgs or [], bool(survey.get("split")),
                survey.get("pricing"), ssr=survey.get("ssr", True) is not False, retest=int(survey.get("retest") or 0),
                seed=int(cfg.get("seed", 11))), log)
        steps.append("survey")
        checkpoint()
    pitch_cfg = cfg.get("pitch")
    if pitch_cfg:
        script = pitch_cfg.get("script") or ""
        sp = _cfg_path(base, script)
        script = read_text_arg("@" + sp) if isinstance(sp, str) and os.path.isfile(sp) else read_text_arg(script)
        rb = pitch_cfg.get("rebuttals")
        if isinstance(rb, str):
            rp = _cfg_path(base, rb)
            rb = read_text_arg("@" + rp) if isinstance(rp, str) and os.path.isfile(rp) else read_text_arg(rb)
        try:
            state["pitch"] = quota.guarded("the sales pitch", lambda: market_cli.pitch(
                c, sid, out_dir, log, script or "", rb, str(cfg.get("brand") or ""),
                str(pitch_cfg.get("channel") or "message"), pitch_cfg.get("segment")), log)
            steps.append("pitch")
        except (ValueError, RuntimeError, CLIError) as e:
            log(f"pitch skipped: {e}")
        checkpoint()
    panel_cfg = cfg.get("panel")
    if panel_cfg:
        collect(c, out_dir, state.get("project_id"), sid)
        state["panel"] = quota.guarded("the analyst panel", lambda: market_cli.panel(
            c, sid, out_dir, log, int(panel_cfg.get("analysts") or 5), str(panel_cfg.get("brief") or ""),
            load_bundle=exporter.load_run_dir), log)
        steps.append("panel")
    if cfg.get("report") == "upstream" or cfg.get("engine_report"):
        rep = step_report(c, sid)
        state["report_id"] = rep.get("report_id")
        steps.append("engine report")
    collect(c, out_dir, state.get("project_id"), sid, state.get("report_id"))
    if cfg.get("study_cell"):
        market_cli.prune_unrequested_study_artifacts(out_dir, cfg)
    state["export"] = do_export(out_dir, os.path.join(out_dir, "dashboard.html"), state["title"])
    if cfg.get("report", True) and cfg.get("report") != "upstream":
        state["report"] = quota.guarded("the report", lambda: market_cli.report(
            c, sid, out_dir, log, load_bundle=exporter.load_run_dir, brand=str(cfg.get("brand") or "")), log)
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
    result = {"stage": "done", "steps": steps, "simulation_id": sid, "dashboard": state["export"]["html"],
              "decision": summary.get("decision"), "verdicts": (summary.get("marketing") or {}).get("verdicts")}
    hook = notify_webhook({"event": "market_test.finished", "name": cfg.get("name"), "title": cfg.get("title"), "run_dir": state["out_dir"],
                           "simulation_id": sid, "decision": summary.get("decision"), "steps": steps,
                           "files": {k: v for k, v in (state.get("export") or {}).items() if isinstance(v, str)}},
                          cfg.get("webhook"))
    if hook:
        result["webhook"] = hook
    return result


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


def cmd_pitch(c: Client, a) -> Any:
    out_dir = _run_dir_for(a)
    script = read_text_arg(a.script) or ""
    rebuttals = read_text_arg(a.rebuttals) if a.rebuttals else None
    try:
        res = market_cli.pitch(c, a.simulation, out_dir, log, script, rebuttals, a.product or "", a.channel,
                               a.segment, a.agents, a.batch)
    except (ValueError, RuntimeError, OSError) as e:
        raise CLIError(str(e))
    return _reexport(c, a, out_dir, res)


def cmd_ideas(c: Client, a) -> Any:
    rows = load_json_list(a.rows, "rows") if a.rows else None
    profile = None
    if a.run_dir:
        try:
            with open(os.path.join(a.run_dir, "product_profile.json"), encoding="utf-8") as f:
                profile = json.load(f)
        except (OSError, ValueError):
            profile = None
    try:
        res = market_cli.ideas(c, a.run_dir, log, a.ads, rows, a.brand or "", read_text_arg(a.brief) or "", a.n, a.out,
                               profile=profile)
    except (ValueError, RuntimeError, OSError) as e:
        raise CLIError(str(e))
    if a.run_dir and os.path.exists(os.path.join(a.run_dir, "run_manifest.json")):
        res["export"] = do_export(a.run_dir, os.path.join(a.run_dir, "dashboard.html"), None)
    return res


def cmd_quickstart(c: Optional[Client], a) -> Any:
    import quickstart
    try:
        prefill: Dict[str, Any] = {}
        if (a.from_docs or a.url) and c is not None:
            text = read_docs_text(a.from_docs or [])
            prof = c.data("POST", "/api/graph/profile", json={"text": text, "url": a.url or "", "name": ""}, timeout=300)
            prefill = {k: v for k, v in (prof.get("quickstart_answers") or {}).items() if v}
            log(f"quickstart: understood {prof.get('name') or 'the product'}: {prof.get('one_liner') or ''}"[:160])
            if a.from_docs:
                prefill["docs"] = ", ".join(a.from_docs)
        answers = quickstart.load_answers(a.answers) if a.answers else quickstart.ask(sys.stdin, sys.stderr, prefill)
        answers = {**prefill, **{k: v for k, v in answers.items() if str(v).strip()}}
        root = a.out or os.path.join("scenarios", quickstart.slug(answers.get("brand") or answers.get("product") or "my_test"))
        res = quickstart.build_scenario(answers, root, ads_import=market_cli.ads_import)
    except (ValueError, OSError) as e:
        raise CLIError(f"quickstart: {e}")
    if a.answers is None:
        quickstart.ensure_env(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), sys.stdin, sys.stderr)
    res["next"] = f"python backend/claude_cli/mirofish.py market-test {res['config']}"
    if a.no_run or c is None:
        return res
    try:
        c.get("/health")
    except CLIError:
        res["note"] = "backend not running: start it with backend/claude_cli/start_server.sh, then run the next command"
        return res
    log("quickstart: creating the simulated people (stops before any paid rounds)")
    run_ns = argparse.Namespace(config=res["config"])
    res["stage_one"] = cmd_market_test(c, run_ns)
    return res


def read_docs_text(paths: List[str], limit: int = 60000) -> str:
    """Local documents (md/txt; pdf via the backend's parser is not available offline) -> one text."""
    out = []
    for path in paths:
        if not os.path.isfile(path):
            raise CLIError(f"document not found: {path}")
        if path.lower().endswith(".pdf"):
            raise CLIError(f"{path}: upload PDFs through a project (understand --project) so the backend can parse them")
        with open(path, encoding="utf-8", errors="replace") as f:
            out.append(f"# {os.path.basename(path)}\n" + f.read())
    return "\n\n".join(out)[:limit]


def step_profile(c: Client, project_id: str, url: Optional[str] = None, ads_summary: Optional[Dict[str, Any]] = None,
                 refresh: bool = False, name: Optional[str] = None) -> Dict[str, Any]:
    """Create (or reuse) the project's product profile; before the graph build it also seeds the market map."""
    body: Dict[str, Any] = {"refresh": bool(refresh)}
    if url:
        body["url"] = url
    if ads_summary:
        body["ads_summary"] = ads_summary
    if name:
        body["name"] = name
    prof = c.data("POST", f"/api/graph/project/{project_id}/profile", json=body, timeout=300)
    log(f"understand: {prof.get('name') or '?'} - {prof.get('one_liner') or ''}"[:160]
        + (f" ({prof.get('method')})" if prof.get("method") else ""))
    return prof


def cmd_understand(c: Client, a) -> Any:
    ads_summary = None
    if a.ads:
        try:
            ads_summary = market_cli.summarize_ads(market_cli.read_ads(a.ads))
        except (OSError, ValueError) as e:
            raise CLIError(f"understand: cannot read ads export: {e}")
    if a.project:
        prof = step_profile(c, a.project, a.url, ads_summary, a.refresh, a.name)
    else:
        text = read_docs_text(a.docs or [])
        if not text and not a.url:
            raise CLIError("understand: give --project, --docs or --url")
        prof = c.data("POST", "/api/graph/profile", json={"text": text, "url": a.url or "", "ads_summary": ads_summary,
                                                          "name": a.name or ""}, timeout=300)
    out = a.out or "product_profile.json"
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(prof, f, ensure_ascii=False, indent=2)
    return {"file": os.path.abspath(out), "name": prof.get("name"), "one_liner": prof.get("one_liner"),
            "for_whom": [x.get("segment") for x in prof.get("for_whom") or []], "pricing": prof.get("pricing"),
            "likely_objections": [o.get("text") for o in prof.get("likely_objections") or []],
            "unknowns": prof.get("unknowns"), "method": prof.get("method")}


def cmd_campaign_plan(c: Optional[Client], a) -> Any:
    import campaign_flow
    if a.project:
        if c is None:
            c = Client(a.base_url, lang=a.lang)
        profile = c.data("GET", f"/api/graph/project/{a.project}/profile")
    elif a.profile:
        with open(a.profile, encoding="utf-8") as f:
            profile = json.load(f)
    else:
        raise CLIError("campaign-plan: supply --profile or --project")
    research = None
    if a.research:
        with open(a.research, encoding="utf-8") as f:
            research = json.load(f)
    elif a.project:
        try:
            research = c.data("GET", f"/api/graph/project/{a.project}/voices").get("voices")
        except CLIError:
            pass
    try:
        plan = campaign_flow.build(profile, a.goal, {"amount": a.budget, "currency": a.currency,
                                                      "period": a.period}, a.channels, research, a.project or "")
    except ValueError as e:
        raise CLIError(str(e)) from e
    path = campaign_flow.save(plan, a.out or "campaign_plan.json")
    return {"file": path, "plan": plan}


def cmd_actuals_import(c: Optional[Client], a) -> Any:
    import actuals
    try:
        mapping = dict(pair.split("=", 1) for pair in (a.map or []))
        result = actuals.normalize(a.file, a.source_type, mapping, a.source or "", a.market or "",
                                   a.date or "", a.quality or "")
    except (OSError, ValueError) as e:
        raise CLIError(f"actuals-import: {e}") from e
    path = actuals.save(result, a.out or os.path.splitext(a.file)[0] + ".normalized.json")
    return {"file": path, **result}


def cmd_holdout_backtest(c: Optional[Client], a) -> Any:
    from app.services import predict as prediction
    with open(a.pairs, encoding="utf-8") as f:
        data = json.load(f)
    pairs = data.get("pairs") if isinstance(data, dict) else data
    if not isinstance(pairs, list):
        raise CLIError("holdout-backtest: JSON must be an array or {pairs: [...]} ")
    result = prediction.holdout_backtest(pairs)
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        result["file"] = os.path.abspath(a.out)
    return result


def cmd_calibrate(c: Client, a) -> Any:
    """Check the run's survey against real answers (CSV) and write calibration.json with the verdict + corrected rate."""
    import csv
    out_dir = a.run_dir
    bundle = exporter.load_run_dir(out_dir)
    meta = marketing.agent_meta(bundle)
    field = a.field
    synthetic = []
    for r in (bundle.get("survey") or {}).get("responses") or []:
        ans = r.get("answer") or {}
        if not ans:
            continue
        m = meta.get(int(r.get("agent_id", -1)), {})
        v = ans.get(field)
        y = {"yes": 1.0, "maybe": 0.5, "no": 0.0}.get(v) if isinstance(v, str) else (float(v) / 10 if isinstance(v, (int, float)) else None)
        if y is None:
            continue
        synthetic.append({"segment": m.get("segment"), "country": m.get("country"), "gender": m.get("gender"), "age": m.get("age"), "y": y})
    mapping = dict(x.split("=", 1) for x in (a.map or []) if "=" in x)
    real = []
    try:
        with open(a.real, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                def col(k):
                    return row.get(mapping.get(k, k))
                v = str(col("y") or col(field) or "").strip().lower()
                y = {"yes": 1.0, "maybe": 0.5, "no": 0.0, "1": 1.0, "0": 0.0, "true": 1.0, "false": 0.0}.get(v)
                if y is None:
                    try:
                        y = float(v)
                        y = y / 10 if y > 1 else y
                    except ValueError:
                        continue
                real.append({"segment": col("segment"), "country": col("country"), "gender": col("gender"), "age": col("age"), "y": y})
    except OSError as e:
        raise CLIError(f"calibrate: cannot read {a.real}: {e}")
    if not synthetic or not real:
        raise CLIError("calibrate: need survey answers in the run and rows in the real CSV")
    log(f"calibrate: {len(synthetic)} simulated vs {len(real)} real answers on '{field}'")
    res = c.data("POST", "/api/simulation/calibrate", json={"synthetic": synthetic, "real": real, "key": a.by, "field": field}, timeout=300)
    save_json(out_dir, "calibration", res)
    return {"calibration": os.path.join(os.path.abspath(out_dir), "calibration.json"), "verdict": res.get("verdict"),
            "reading": res.get("reading"), "overlap": res.get("overlap"), "corrected": res.get("corrected"),
            "by_group": {k: v.get("verdict") for k, v in (res.get("calibration") or {}).get("by_group", {}).items()}}


def cmd_emailtest(c: Client, a) -> Any:
    out_dir = _run_dir_for(a)
    try:
        res = market_cli.emailtest(c, a.simulation, a.emails, out_dir, log, a.seed, a.parallel, a.list_size, a.limit)
    except (ValueError, RuntimeError, OSError) as e:
        raise CLIError(str(e))
    return _reexport(c, a, out_dir, res)


def cmd_test(c: Client, a) -> Any:
    """One spec, any test type: ad, message, price, offer, positioning, naming, landing, launch, pitch, email, creator_post, channel_mix."""
    import experiments
    spec = market_cli._load_json_arg(a.spec)
    try:
        exp = experiments.normalize(spec)
    except ValueError as e:
        raise CLIError(f"test: {e}")
    out_dir = a.run_dir or os.path.join("mirofish_runs", f"{a.simulation}_{re.sub(r'[^A-Za-z0-9._-]+', '_', exp['name'])}")
    engines = {
        "feedtest": lambda c_, sid, spec_arg, run_dir, log_, seeds=1: market_cli.feedtest(
            c_, sid, spec_arg, run_dir, log_, None, None, 3, 5, a.limit, a.parallel, 2, True, seeds),
        "survey": lambda c_, sid, run_dir, offer, goal, msgs, split, currency: step_survey(
            c_, sid, run_dir, offer, goal, msgs, split, currency, None, a.batch, 600, a.limit, True),
        "events": step_events,
        "start": lambda c_, sid, max_rounds=6: step_start(c_, sid, "parallel", max_rounds, graph_memory=True, force=True),
        "pitch": lambda c_, sid, run_dir, log_, script, rebuttals, product, channel: market_cli.pitch(
            c_, sid, run_dir, log_, script, rebuttals, product, channel),
        "emailtest": lambda c_, sid, spec_arg, run_dir, log_: market_cli.emailtest(c_, sid, spec_arg, run_dir, log_, 5, a.parallel, None, a.limit),
        "collect": collect, "load_bundle": exporter.load_run_dir,
    }
    try:
        res = experiments.run(c, exp, a.simulation, out_dir, log, engines, brand=a.brand or "")
    except (ValueError, RuntimeError, OSError) as e:
        raise CLIError(f"test: {e}")
    log(f"test: {res['verdict']}")
    notify_webhook({"event": "test.finished", "name": exp["name"], "type": exp["type"], "run_dir": os.path.abspath(out_dir),
                    "winner": res.get("winner"), "lift": res.get("lift"), "clear_winner": res.get("clear_winner"), "verdict": res.get("verdict")},
                   exp["extra"].get("webhook"))
    if not a.no_export and os.path.exists(os.path.join(out_dir, "run_manifest.json")):
        res["export"] = do_export(out_dir, os.path.join(out_dir, "dashboard.html"), None)
    return {k: v for k, v in res.items() if k != "variants"} | {"variants": [{k: r.get(k) for k in ("id", "value", "margin", "n", "unit")} for r in res["variants"]],
                                                              "result_file": os.path.join(os.path.abspath(out_dir), "experiment_result.json")}


def cmd_study(c: Client, a) -> Any:
    """Several scenarios x seeds on the same people -> study_summary.json, study_report.md, study.html."""
    import study as study_mod
    try:
        with open(a.spec, encoding="utf-8") as f:
            spec = json.load(f)
        st = study_mod.normalize(spec, os.path.dirname(os.path.abspath(a.spec)))
    except (OSError, ValueError) as e:
        raise CLIError(f"study: {e}")
    root = a.out or os.path.join("mirofish_runs", st["name"])

    def run_cell(cfg: Dict[str, Any], cfg_path: str) -> Any:
        # keep relative paths (creatives.json, messages.txt...) resolvable: they live next to the base config
        for key in ("creatives", "personas", "requirement", "posts", "events", "emails"):
            v = cfg.get(key)
            if isinstance(v, str) and not os.path.isabs(v) and os.path.exists(os.path.join(st["base_root"], v)):
                cfg[key] = os.path.join(st["base_root"], v)
        sv = cfg.get("survey")
        if isinstance(sv, dict) and isinstance(sv.get("messages"), str) and not os.path.isabs(sv["messages"]):
            cand = os.path.join(st["base_root"], sv["messages"])
            if os.path.exists(cand):
                sv["messages"] = cand
        pt = cfg.get("pitch")
        if isinstance(pt, dict):
            for key in ("script", "rebuttals"):
                v = pt.get(key)
                if isinstance(v, str) and not os.path.isabs(v) and os.path.exists(os.path.join(st["base_root"], v)):
                    pt[key] = os.path.join(st["base_root"], v)
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return cmd_market_test(c, argparse.Namespace(config=cfg_path))

    summary = study_mod.run(st, root, run_cell, log)
    md = None
    if st.get("report") and not a.no_report:
        try:
            data = c.data("POST", "/api/simulation/study-report", json={"summary": summary, "brand": st.get("brand") or ""}, timeout=300)
            md = data.get("markdown")
            if len((md or "").strip()) < 400:          # the guard removed most of it: the data-only report says more
                log("study: the written report came back nearly empty; using the data-only report")
                md = None
            else:
                log(f"study: report written ({data.get('method')})")
        except CLIError as e:
            log(f"study: report call failed, using the data-only report: {e}")
    md = ("**Evidence status: exploratory simulation.** Seed agreement does not establish real-world lift or a success probability.\n\n" + md) \
        if md else study_mod.render_markdown(summary, st.get("brand") or "")
    with open(os.path.join(root, "study_report.md"), "w", encoding="utf-8") as f:
        f.write(md)
    links = {f"{x['scenario']} seed {x['seed']}": os.path.join(os.path.relpath(x["path"], root), "dashboard.html") for x in summary["cells"]}
    with open(os.path.join(root, "study.html"), "w", encoding="utf-8") as f:
        f.write(study_mod.render_html(summary, exporter.markdown_to_html, exporter.CSS, st.get("brand") or "", links))
    conc = summary.get("conclusion") or {}
    notify_webhook({"event": "study.finished", "name": st["name"], "study_dir": os.path.abspath(root), "conclusion": conc,
                    "cells": len(summary.get("cells") or [])}, spec.get("webhook"))
    return {"study": os.path.abspath(root), "summary": os.path.join(os.path.abspath(root), "study_summary.json"),
            "report": os.path.join(os.path.abspath(root), "study_report.md"), "html": os.path.join(os.path.abspath(root), "study.html"),
            "cells": len(summary.get("cells") or []), "conclusion": conc}


def cmd_predict(c: Client, a) -> Any:
    """Predictions with intervals for a run's headline numbers, scaled by the calibration store; plus a 90-day forecast."""
    bundle = exporter.load_run_dir(a.run_dir)
    summary = {}
    try:
        with open(os.path.join(a.run_dir, "summary.json"), encoding="utf-8") as f:
            summary = json.load(f)
    except (OSError, ValueError):
        pass
    targets = dict(x.split("=", 1) for x in (a.target or []) if "=" in x)
    brand = a.brand or (bundle.get("run_manifest") or {}).get("brand") or ""
    res = c.data("POST", "/api/simulation/predict", json={"brand": brand, "summary": summary, "feed_test": bundle.get("feed_test") or {},
                                                        "email_test": bundle.get("email_test") or {}, "targets": targets}, timeout=120)
    save_json(a.run_dir, "predictions", res)
    out = {"predictions": os.path.join(os.path.abspath(a.run_dir), "predictions.json"), "calibrated": res.get("calibrated"),
           "rows": [{k: p.get(k) for k in ("what", "simulated", "predicted", "low", "high", "p_success", "basis")} for p in res.get("predictions") or []][:12]}
    if bundle.get("feed_test"):
        try:
            fc = c.data("POST", "/api/simulation/forecast", json={"feed_test": bundle["feed_test"], "feed_story": bundle.get("feed_story") or {},
                                                                 "spend": a.spend, "days": a.days}, timeout=120)
            save_json(a.run_dir, "forecast", fc)
            out["forecast"] = {k: fc.get(k) for k in ("creative", "customers_total", "active_at_end", "cac", "k_factor", "spend_total", "currency")}
        except CLIError as e:
            out["forecast"] = f"not available: {e}"
    return out


def cmd_research(c: Optional[Client], a) -> Any:
    """What real people say (Hacker News, App Store reviews, Reddit when reachable, pages) -> research.md + voices.json."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    try:
        from app.services import research
    except Exception as e:  # noqa: BLE001
        raise CLIError(f"research needs the backend package importable (run from the repo with its venv): {e}")
    out_dir = a.out or os.path.join("scenarios", re.sub(r"[^A-Za-z0-9._-]+", "_", a.query)[:40], "research")
    res = research.run(a.query, [s.strip().lower() for s in a.sources.split(",")], out_dir, a.country, a.subreddit, a.url, a.limit, log=log)
    summ = res["summary"]
    return {"files": res["files"], "quotes": summ["quotes"], "by_source": summ["by_source"], "sentiment": summ["sentiment"],
            "avg_rating": summ.get("avg_rating"), "themes": [f"{t['theme']} ({t['mentions']})" for t in summ.get("themes") or []],
            "voices": res["voices"], "notes": summ.get("notes"), "next": f"add {res['files']['md']} to the scenario seeds; voices.json grounds the personas and feeds"}


def cmd_context(c: Client, a) -> Any:
    """Push what people are saying today (news, a competitor move, a real thread) into a running simulation."""
    if a.text is None and not a.list:
        raise CLIError("context: give --text or --list")
    if a.list:
        return c.data("GET", f"/api/simulation/{a.simulation}/context")
    body: Dict[str, Any] = {"text": read_text_arg(a.text) or ""}
    if a.round is not None:
        body["round"] = a.round
    if a.source:
        body["source"] = a.source
    res = c.data("PUT", f"/api/simulation/{a.simulation}/context", json=body, timeout=60)
    log(f"context: {len(res.get('context_updates') or [])} update(s) on file; simulation {'running' if res.get('running') else 'not running'}")
    return res


def notify_webhook(payload: Dict[str, Any], url: Optional[str] = None, retries: int = 3) -> Optional[Dict[str, Any]]:
    """POST a JSON summary to MIROFISH_WEBHOOK_URL (or `url`) when a run, study or test finishes; 3 tries, never raises."""
    target = url or os.environ.get("MIROFISH_WEBHOOK_URL")
    if not target:
        return None
    try:
        import requests
    except ImportError:
        return {"url": target, "sent": False, "error": "requests not installed"}
    body = {"event": payload.get("event") or "finished", "sent_at": datetime.now().isoformat(), **payload}
    last = ""
    for attempt in range(retries):
        try:
            r = requests.post(target, json=body, timeout=20, headers={"User-Agent": "MarketMirror/0.3 webhook"})
            if r.status_code < 300:
                log(f"webhook: delivered to {target} ({r.status_code})")
                return {"url": target, "sent": True, "status": r.status_code}
            last = f"HTTP {r.status_code}"
        except Exception as e:  # noqa: BLE001
            last = str(e)[:120]
        time.sleep(1.5 * (attempt + 1))
    log(f"webhook: not delivered to {target}: {last}")
    return {"url": target, "sent": False, "error": last}


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
    p = argparse.ArgumentParser(prog="mirofish", description="MarketMirror: test ads, messages, prices, launches and sales pitches on simulated buyers (MiroFish engine). Start with: quickstart.")
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
    s.add_argument("--parallel", type=int, default=DEFAULT_PARALLEL, help="parallel profile generation (default: CPU count)")
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
    s.add_argument("--parallel", type=int, default=DEFAULT_PARALLEL)
    s.add_argument("--entity-types", nargs="+")
    s.add_argument("--no-llm-profiles", action="store_true", help="rule-based profiles (cheaper, lower quality)")
    s.add_argument("--personas", help="persona spec JSON: audience segments (country, ages, role, count) and "
                                      "communities; see docs/personas.md")
    s.add_argument("--auto-personas", type=int, metavar="N",
                   help="let Claude plan about N personas (and their communities) from the requirement")
    s.add_argument("--personas-lite", action="store_true", help="skip the life interviews (cheaper, shallower people)")
    s.add_argument("--force", action="store_true", help="regenerate even if prepared")
    s.add_argument("--resume-only", action="store_true", help="finish from complete saved profiles; never regenerate profiles")
    waitopts(s)

    s = sub.add_parser("start", help="start the simulation (and wait for it by default)")
    s.add_argument("--simulation", required=True)
    s.add_argument("--platform", choices=["auto", "twitter", "reddit", "parallel"], default="auto")
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

    s = sub.add_parser("report", help="plain-language market report (default) or the engine's narrative report")
    s.add_argument("--simulation", required=True)
    s.add_argument("--engine", choices=["market", "upstream"], default="market",
                   help="market = plain-language report from every test in the run; upstream = MiroFish ReportAgent")
    s.add_argument("--brand", help="brand name for the report title")
    s.add_argument("--run-dir", help="run folder (default mirofish_runs/<simulation>)")
    s.add_argument("--no-export", action="store_true", help="don't re-export the dashboard")
    s.add_argument("--title")
    s.add_argument("--force", action="store_true", help="upstream: regenerate")
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
    s.add_argument("--batch", type=int, default=40, help="people per interview call (default %(default)s)")
    s.add_argument("--wait-s", type=int, default=600, help="server-side timeout per batch (s)")
    s.add_argument("--limit", type=int, help="only ask the first N people (quick, cheap check)")
    s.add_argument("--retest", type=int, default=0, help="re-ask N people a week later (simulated) and report agreement")
    s.add_argument("--assignment-seed", type=int, default=11,
                   help="reproducible split-message assignment and retest sample (default %(default)s)")
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
    s.add_argument("--parallel", type=int, default=DEFAULT_PARALLEL)
    s.add_argument("--run-dir", help="default mirofish_runs/<simulation>")
    s.add_argument("--no-export", action="store_true")
    s.add_argument("--title")

    s = sub.add_parser("website-test", help="prepared personas browse a real product URL; record actions, screenshots and DOM-verified goals")
    s.add_argument("--simulation", required=True)
    s.add_argument("--url", help="real product or landing-page URL")
    s.add_argument("--goal", choices=("explore_product", "add_to_cart", "reach_signup", "complete_signup", "reach_checkout", "custom"))
    s.add_argument("--task", help="the visitor's specific task and constraints")
    s.add_argument("--spec", help="@website_test.json with outcome checks and optional supplied test data")
    s.add_argument("--limit", type=int, help="synthetic visitors, 1–20; default 3")
    s.add_argument("--steps", type=int, help="actions per visitor, 1–30; default 12")
    s.add_argument("--device", choices=("mobile", "desktop"))
    s.add_argument("--headed", action="store_const", const=False, default=None, dest="headless", help="show the Chromium window (requires a graphical session)")
    s.add_argument("--record-video", action="store_true", default=None, help="save visitor tab recordings; use disposable test data")
    s.add_argument("--record-trace", action="store_true", default=None, help="save Playwright traces; traces may contain unredacted test data")
    s.add_argument("--recoveries", type=int, help="fresh-observation recoveries per visitor, 0–5; default 2")
    s.add_argument("--observation-mode", choices=("compact", "full"), help="compact model context (default) or full observations for comparison")
    s.add_argument("--observation-text-chars", type=int, help="compact page text limit, 1000–10000; default 4000")
    s.add_argument("--max-model-calls", type=int, help="whole-run model call limit, including failures")
    s.add_argument("--max-input-tokens", type=int, help="whole-run reported input-token threshold, including cached tokens; checked between calls")
    s.add_argument("--max-elapsed-s", type=float, help="whole-run time threshold; cannot interrupt an in-flight operation")
    s.add_argument("--loop-limit", type=int, help="stop before this repeated action on equivalent state, 2–10; default 3")
    s.add_argument("--out", help="export folder; default a separate website run")

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

    s = sub.add_parser("actuals-import", help="normalize ads, email, website, CRM or survey export with provenance and validation errors")
    s.add_argument("file", help="CSV or JSON export")
    s.add_argument("--source-type", required=True, choices=["ads", "email", "website", "crm", "survey"])
    s.add_argument("--map", nargs="*", help="normalized_field=export_column pairs")
    s.add_argument("--source", help="human-readable export source")
    s.add_argument("--market", help="market when absent in export")
    s.add_argument("--date", help="YYYY-MM-DD when absent in export")
    s.add_argument("--quality", help="quality label, default user_export_unverified")
    s.add_argument("--out", help="normalized JSON output path")

    s = sub.add_parser("campaign-plan", help="turn a product profile and cited research into a saved campaign plan and runnable test specs")
    s.add_argument("--profile", help="product_profile.json")
    s.add_argument("--project", help="existing project id")
    s.add_argument("--research", help="research.json or voices.json")
    s.add_argument("--goal", required=True, help="business conversion goal")
    s.add_argument("--budget", required=True, type=float)
    s.add_argument("--currency", default="USD")
    s.add_argument("--period", default="test period")
    s.add_argument("--channels", nargs="*", help="search organic paid_social email sales referral")
    s.add_argument("--out", help="campaign_plan.json path")

    s = sub.add_parser("holdout-backtest", help="compare persona estimates against a training-mean no-persona baseline on held-out real experiments")
    s.add_argument("--pairs", required=True, help="JSON rows with sim, real and split=train|holdout")
    s.add_argument("--out", help="save backtest JSON")

    s = sub.add_parser("backtest", help="compare simulated creative rankings with real ad results (stores real-vs-simulated CTR pairs for predict)")
    s.add_argument("--brand", help="brand name for the calibration store")
    s.add_argument("--run-dir", required=True, help="run folder with feed_test.json")
    s.add_argument("--actuals", required=True, help="JSON written by actuals-import or ads-import")
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

    s = sub.add_parser("pitch", help="sales rehearsal: pitch every simulated buyer, answer their objections with rebuttals")
    s.add_argument("--simulation", required=True)
    s.add_argument("--script", required=True, help="the pitch text or @file.md")
    s.add_argument("--rebuttals", help="@file.md with '## price' / '## trust' / '## any' sections, or JSON {type: text}")
    s.add_argument("--product", help="what is being sold (one line)")
    s.add_argument("--channel", default="message", choices=["message", "call", "demo", "email", "dm"])
    s.add_argument("--segment", help="only this audience")
    s.add_argument("--agents", type=int, nargs="*", help="only these agent ids")
    s.add_argument("--batch", type=int, default=40, help="people per interview call (default %(default)s)")
    s.add_argument("--run-dir", help="run folder to update (default: mirofish_runs/<simulation>)")
    s.add_argument("--no-export", action="store_true")

    s = sub.add_parser("ideas", help="next test ideas from real ad results (export or connected ads tool rows) and a run")
    s.add_argument("--ads", help="Meta/Google Ads export (CSV/JSON)")
    s.add_argument("--rows", help="@file.json with ad rows (e.g. fetched from an ads API by an agent)")
    s.add_argument("--run-dir", help="run folder with summary.json (objections, audiences, decision)")
    s.add_argument("--brand")
    s.add_argument("--brief", help="text or @file")
    s.add_argument("--n", type=int, default=8)
    s.add_argument("--out", help="ideas.json path (default: <run-dir>/ideas.json)")

    s = sub.add_parser("context", help="push live context (news, what people say today, a competitor move) into a running simulation's persona cards")
    s.add_argument("--simulation", required=True)
    s.add_argument("--text", help="the update, or @file")
    s.add_argument("--round", type=int, help="from which round (default: the next one)")
    s.add_argument("--source", help="where it comes from, e.g. 'r/fitness today'")
    s.add_argument("--list", action="store_true", help="list the updates on file")

    s = sub.add_parser("research", help="what real people say: Hacker News, App Store reviews, Reddit (when reachable), pages -> research.md + voices.json")
    s.add_argument("--query", required=True, help="product, category or competitor, e.g. 'home workout app'")
    s.add_argument("--sources", default="hn,appstore,reddit", help="comma list: hn, appstore, reddit")
    s.add_argument("--country", default="us", help="App Store storefront, e.g. in, ph, ke")
    s.add_argument("--subreddit", nargs="*", help="subreddits to search (default: all)")
    s.add_argument("--url", nargs="*", help="pages to read (landing page, review page, thread)")
    s.add_argument("--limit", type=int, default=30)
    s.add_argument("--out", help="folder (default scenarios/<query>/research)")

    s = sub.add_parser("predict", help="predictions with intervals (scaled by real results seen so far) and a 90-day adoption forecast for a run")
    s.add_argument("--run-dir", required=True)
    s.add_argument("--brand")
    s.add_argument("--target", nargs="*", help="targets to score, e.g. ctr=2 cpl=10 would_convert=15")
    s.add_argument("--spend", type=float, help="monthly spend for the forecast (default: the benchmark budget)")
    s.add_argument("--days", type=int, default=90)

    s = sub.add_parser("study", help="same people, several scenarios x seeds -> one defended conclusion (study_summary.json, study_report.md, study.html)")
    s.add_argument("--spec", required=True, help="study.json: {name, base: market_test.json, simulation_id, scenarios:[{name, overrides}], seeds:[..], steps:[..]}")
    s.add_argument("--out", help="study folder (default mirofish_runs/<name>)")
    s.add_argument("--no-report", action="store_true", help="skip the one-call study report")

    s = sub.add_parser("test", help="test anything from one spec: ad, message, price, offer, positioning, naming, landing, launch, pitch, email, creator_post, channel_mix")
    s.add_argument("--simulation", required=True)
    s.add_argument("--spec", required=True, help="@experiment.json: {type, name, variants[], audience{segments,countries}, metric, budget, rounds, ...}")
    s.add_argument("--brand", help="brand name (poster of launch posts, product in pitches)")
    s.add_argument("--run-dir", help="where results go (default mirofish_runs/<simulation>_<name>)")
    s.add_argument("--parallel", type=int, default=DEFAULT_PARALLEL)
    s.add_argument("--batch", type=int, default=40)
    s.add_argument("--limit", type=int, help="only the first N people")
    s.add_argument("--no-export", action="store_true")

    s = sub.add_parser("emailtest", help="email campaign test: subject lines, senders, send times, sequences in simulated inboxes")
    s.add_argument("--simulation", required=True)
    s.add_argument("--emails", required=True, help="@emails.json: {emails:[{id, from_name, subject, preheader, body, cta, send_time, sequence:[...]}], list_size, benchmarks}")
    s.add_argument("--seed", type=int, default=5)
    s.add_argument("--parallel", type=int, default=DEFAULT_PARALLEL)
    s.add_argument("--list-size", type=int, help="real list size for the projection (opens, clicks, leads)")
    s.add_argument("--limit", type=int, help="only the first N people (quick check)")
    s.add_argument("--run-dir", help="run folder (default mirofish_runs/<simulation>)")
    s.add_argument("--no-export", action="store_true")
    s.add_argument("--title")

    s = sub.add_parser("calibrate", help="compare the run's survey with real answers (CSV): trust / correct / walk-away and a corrected rate")
    s.add_argument("--run-dir", required=True)
    s.add_argument("--real", required=True, help="CSV with columns segment,country,gender,age,y (yes/maybe/no or 0-1)")
    s.add_argument("--map", nargs="*", help="column mapping, e.g. segment=Audience y=Converted")
    s.add_argument("--field", default="would_convert", help="survey field to compare (default %(default)s)")
    s.add_argument("--by", default="segment", help="subgroup key for the per-group verdicts (segment|country)")

    s = sub.add_parser("understand", help="read your documents / landing page / ads export into one product profile")
    s.add_argument("--project", help="an existing project id (uses its uploaded documents)")
    s.add_argument("--docs", nargs="*", help="local .md/.txt files (no project needed)")
    s.add_argument("--url", help="landing page or app-store page")
    s.add_argument("--ads", help="Meta/Google Ads export (CSV/JSON) to fold in")
    s.add_argument("--name", help="brand name hint")
    s.add_argument("--refresh", action="store_true", help="rebuild even if the project already has a profile")
    s.add_argument("--out", help="where to write product_profile.json")

    s = sub.add_parser("quickstart", help="answer a few questions, get a ready scenario folder and the simulated people")
    s.add_argument("--answers", help="@answers.json (for agents; otherwise asks on the terminal)")
    s.add_argument("--from-docs", nargs="*", help="documents to read first; the answers are prefilled from them")
    s.add_argument("--url", help="landing page to read first")
    s.add_argument("--out", help="scenario folder (default: scenarios/<brand>)")
    s.add_argument("--no-run", action="store_true", help="only write the files")

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

    s = sub.add_parser("thoughts", help="simulate or harvest real agent cognitive inner-monologue streams (System 1 gut + System 2 BDE check + Say-vs-Do gap)")
    s.add_argument("--simulation", required=True)
    s.add_argument("--stimulus", help="stimulus text or @stimulus.json ({headline,text,price,channel}); omit to harvest existing run thoughts")
    s.add_argument("--limit", type=int, default=40)
    s.add_argument("--parallel", type=int, default=DEFAULT_PARALLEL)
    s.add_argument("--run-dir", help="run folder (default mirofish_runs/<simulation>)")
    s.add_argument("--no-export", action="store_true")
    s.add_argument("--title")

    s = sub.add_parser("gtm-suite", help="run the 6-in-1 Marketing & Sales GTM Hub (Buying Committee, Auto-Optimizer, Battlecards, 30d Journey/LTV, Pricing Conjoint, Competitor Intelligence)")
    s.add_argument("--simulation", help="simulation ID (or use --run-dir offline)")
    s.add_argument("--run-dir", help="run folder (default mirofish_runs/<simulation>)")
    s.add_argument("--offer", help="offer headline/text or @offer.json")
    s.add_argument("--competitor", default="Status Quo / Free Alternatives")
    s.add_argument("--no-export", action="store_true")
    s.add_argument("--title")

    s = sub.add_parser("competitor-analysis", help="run multi-agent Competitor Bake-Off, Feature Gap Matrix & AI Strategy Suggestions")
    s.add_argument("--simulation", help="simulation ID (or use --run-dir offline)")
    s.add_argument("--run-dir", help="run folder (default mirofish_runs/<simulation>)")
    s.add_argument("--offer", help="offer headline/text or @offer.json")
    s.add_argument("--competitors", nargs="*", help="competitor names or @competitors.json")
    s.add_argument("--no-export", action="store_true")
    s.add_argument("--title")

    s = sub.add_parser("teardown", help="run Wynter + Neurons 5-Second Landing Page Teardown & Scroll-Decay Attention Simulator")
    s.add_argument("--simulation", help="simulation ID (or use --run-dir offline)")
    s.add_argument("--run-dir", help="run folder (default mirofish_runs/<simulation>)")
    s.add_argument("--url", help="live landing page URL or copy text")
    s.add_argument("--no-export", action="store_true")
    s.add_argument("--title")

    s = sub.add_parser("roleplay", help="run Hyperbound / Yoodli AI Buyer Roleplay Sparring Dojo & 5-Rubric Coaching Grader")
    s.add_argument("--simulation", help="simulation ID (or use --run-dir offline)")
    s.add_argument("--run-dir", help="run folder (default mirofish_runs/<simulation>)")
    s.add_argument("--message", nargs="*", help="rep pitch / rebuttal messages to score")
    s.add_argument("--no-export", action="store_true")
    s.add_argument("--title")

    s = sub.add_parser("personalize", help="run Mutiny 1:1 Segment Personalizer & Evidenza Category Entry Points (CEPs)")
    s.add_argument("--simulation", help="simulation ID (or use --run-dir offline)")
    s.add_argument("--run-dir", help="run folder (default mirofish_runs/<simulation>)")
    s.add_argument("--offer", help="offer headline/text")
    s.add_argument("--no-export", action="store_true")
    s.add_argument("--title")
    return p


def cmd_thoughts(c: Client, a) -> Any:
    out_dir = _run_dir_for(a)
    os.makedirs(out_dir, exist_ok=True)
    if a.stimulus:
        raw = read_text_arg(a.stimulus) or a.stimulus
        try:
            stim = json.loads(raw)
        except ValueError:
            stim = raw
        started = c.data("POST", "/api/simulation/thought-stream", json={
            "simulation_id": a.simulation, "stimulus": stim, "max_personas": a.limit, "parallel": a.parallel
        })
        res = market_cli.wait_task(c, started["task_id"], "thought-stream", log)
    else:
        res = c.data("GET", f"/api/simulation/{a.simulation}/thought-stream")
    with open(os.path.join(out_dir, "thought_stream.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    return _reexport(c, a, out_dir, res)


def cmd_gtm_suite(c: Optional[Client], a) -> Any:
    out_dir = a.run_dir or (_run_dir_for(a) if getattr(a, "simulation", None) else "mirofish_runs/fitloop")
    os.makedirs(out_dir, exist_ok=True)
    offer = read_text_arg(a.offer) if getattr(a, "offer", None) else None
    if c is not None and getattr(a, "simulation", None):
        res = c.data("POST", "/api/simulation/gtm-suite", json={
            "simulation_id": a.simulation, "offer": offer, "competitor": a.competitor
        })
    else:
        # Offline execution directly against the run folder
        sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
        from app.services import gtm_suite
        cfg_path = os.path.join(out_dir, "config.json")
        if not os.path.exists(cfg_path):
            cfg_path = os.path.join(out_dir, "simulation_config.json")
        people = []
        if os.path.exists(cfg_path):
            with open(cfg_path, "r", encoding="utf-8") as f:
                d = json.load(f)
                if isinstance(d, dict) and "data" in d and isinstance(d["data"], dict):
                    d = d["data"]
                people = d.get("persona_index") or []
        res = gtm_suite.run_full_gtm_suite(None, "", people, offer=offer, competitor=a.competitor, run_dir=out_dir)
    with open(os.path.join(out_dir, "gtm_suite.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    if not getattr(a, "no_export", False):
        do_export(out_dir, os.path.join(out_dir, "dashboard.html"), getattr(a, "title", None))
    return res


def cmd_competitor_analysis(c: Optional[Client], a) -> Any:
    out_dir = a.run_dir or (_run_dir_for(a) if getattr(a, "simulation", None) else "mirofish_runs/fitloop")
    os.makedirs(out_dir, exist_ok=True)
    offer = read_text_arg(a.offer) if getattr(a, "offer", None) else None
    comps = getattr(a, "competitors", None)
    if c is not None and getattr(a, "simulation", None):
        res = c.data("POST", "/api/simulation/competitor-analysis", json={
            "simulation_id": a.simulation, "offer": offer, "competitors": comps
        })
    else:
        sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
        from app.services import gtm_suite
        cfg_path = os.path.join(out_dir, "config.json")
        if not os.path.exists(cfg_path):
            cfg_path = os.path.join(out_dir, "simulation_config.json")
        people = []
        if os.path.exists(cfg_path):
            with open(cfg_path, "r", encoding="utf-8") as f:
                d = json.load(f)
                if isinstance(d, dict) and "data" in d and isinstance(d["data"], dict):
                    d = d["data"]
                people = d.get("persona_index") or []
        res = gtm_suite.run_competitor_intelligence(None, "", people, offer=offer or "Our Product", competitors=comps)
    with open(os.path.join(out_dir, "competitor_intel.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    if not getattr(a, "no_export", False):
        do_export(out_dir, os.path.join(out_dir, "dashboard.html"), getattr(a, "title", None))
    return res


def _load_offline_people(out_dir: str) -> List[Dict[str, Any]]:
    cfg_path = os.path.join(out_dir, "config.json")
    if not os.path.exists(cfg_path):
        cfg_path = os.path.join(out_dir, "simulation_config.json")
    if os.path.exists(cfg_path):
        with open(cfg_path, "r", encoding="utf-8") as f:
            d = json.load(f)
            if isinstance(d, dict) and "data" in d and isinstance(d["data"], dict):
                d = d["data"]
            return d.get("persona_index") or []
    return []


def cmd_teardown(c: Optional[Client], a) -> Any:
    out_dir = a.run_dir or (_run_dir_for(a) if getattr(a, "simulation", None) else "mirofish_runs/fitloop")
    os.makedirs(out_dir, exist_ok=True)
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from app.services import cro_and_sparring
    res = cro_and_sparring.run_landing_teardown(None, "", getattr(a, "url", None) or "15-Minute Daily Routine App", _load_offline_people(out_dir))
    with open(os.path.join(out_dir, "landing_teardown.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    if not getattr(a, "no_export", False):
        do_export(out_dir, os.path.join(out_dir, "dashboard.html"), getattr(a, "title", None))
    return res


def cmd_roleplay(c: Optional[Client], a) -> Any:
    out_dir = a.run_dir or (_run_dir_for(a) if getattr(a, "simulation", None) else "mirofish_runs/fitloop")
    os.makedirs(out_dir, exist_ok=True)
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from app.services import cro_and_sparring
    res = cro_and_sparring.run_sales_roleplay(None, "", _load_offline_people(out_dir), rep_messages=getattr(a, "message", None))
    with open(os.path.join(out_dir, "sales_roleplay.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    if not getattr(a, "no_export", False):
        do_export(out_dir, os.path.join(out_dir, "dashboard.html"), getattr(a, "title", None))
    return res


def cmd_personalize(c: Optional[Client], a) -> Any:
    out_dir = a.run_dir or (_run_dir_for(a) if getattr(a, "simulation", None) else "mirofish_runs/fitloop")
    os.makedirs(out_dir, exist_ok=True)
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from app.services import cro_and_sparring
    res = cro_and_sparring.run_segment_personalizer(None, "", getattr(a, "offer", None) or "15-Minute Daily Routine", _load_offline_people(out_dir))
    with open(os.path.join(out_dir, "segment_personalization.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    if not getattr(a, "no_export", False):
        do_export(out_dir, os.path.join(out_dir, "dashboard.html"), getattr(a, "title", None))
    return res


COMMANDS = {
    "health": cmd_health, "run": cmd_run, "upload": cmd_upload, "build-graph": cmd_build_graph,
    "create-sim": cmd_create_sim, "prepare": cmd_prepare, "start": cmd_start, "wait": cmd_wait,
    "stop": cmd_stop, "close-env": cmd_close_env, "status": cmd_status, "report": cmd_report,
    "chat": cmd_chat, "interview": cmd_interview, "profiles": cmd_profiles, "list": cmd_list,
    "export": cmd_export, "live": cmd_live, "survey": cmd_survey, "feedtest": cmd_feedtest,
    "panel": cmd_panel, "ads-import": cmd_ads_import, "actuals-import": cmd_actuals_import,
    "campaign-plan": cmd_campaign_plan, "holdout-backtest": cmd_holdout_backtest, "website-test": cmd_website_test,
    "backtest": cmd_backtest, "market-test": cmd_market_test,
    "captions": cmd_captions, "pitch": cmd_pitch, "ideas": cmd_ideas, "quickstart": cmd_quickstart,
    "understand": cmd_understand, "calibrate": cmd_calibrate, "emailtest": cmd_emailtest, "test": cmd_test, "study": cmd_study, "predict": cmd_predict, "research": cmd_research, "context": cmd_context,
    "thoughts": cmd_thoughts, "gtm-suite": cmd_gtm_suite, "competitor-analysis": cmd_competitor_analysis,
    "teardown": cmd_teardown, "roleplay": cmd_roleplay, "personalize": cmd_personalize,
}


def main(argv: Optional[List[str]] = None) -> int:
    a = build_parser().parse_args(argv)
    try:
        offline_export = a.cmd == "export" and a.run_dir and not (a.project or a.simulation or a.report)
        offline_live = a.cmd == "live" and a.offline
        offline = offline_export or offline_live or a.cmd in ("ads-import", "actuals-import", "holdout-backtest", "research") or \
            (a.cmd == "campaign-plan" and not a.project) or (a.cmd == "quickstart" and a.no_run) or \
            (a.cmd in ("gtm-suite", "competitor-analysis", "teardown", "roleplay", "personalize") and not getattr(a, "simulation", None))
        if a.cmd == "backtest":
            try:
                Client(a.base_url, lang=a.lang).get("/health")
            except Exception:  # noqa: BLE001 - backtest works offline; pairs are stored only when the backend is up
                offline = True
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
