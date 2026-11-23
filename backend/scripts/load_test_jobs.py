#!/usr/bin/env python3
"""Load test for the job queue with a fake LLM: no real model calls, no spend.

    cd backend && uv run --no-sync python scripts/load_test_jobs.py [--runs 24] [--people 8] [--workers 2]

What it does, all in a temporary folder with a clean environment (no API keys from your shell or .env reach the
child processes; the only "model" is a local fake OpenAI-compatible server):

1. starts a fake LLM (POST /v1/chat/completions, fixed latency, counts every request);
2. writes `--sims` small simulations with `--people` personas each;
3. starts the backend (run.py) with MM_JOB_EXTERNAL_WORKERS=1 and `--workers` queue worker processes;
4. fires `--runs` questionnaire runs at once across three workspaces;
5. part-way through, SIGKILLs one worker and the server, then starts them again (crash + restart);
6. waits until every job has an outcome, approves the jobs the crash interrupted after model calls (they are
   never retried on their own), waits again, and prints throughput, queue waits, peak concurrency per provider and
   workspace, and whether any job was lost.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FakeLLM(BaseHTTPRequestHandler):
    latency = 0.25
    count = 0
    lock = threading.Lock()

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(n)
        with FakeLLM.lock:
            FakeLLM.count += 1
        time.sleep(FakeLLM.latency * random.uniform(0.6, 1.4))
        body = {"id": "fake", "object": "chat.completion", "created": int(time.time()), "model": "fake-model",
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": json.dumps({"answers": {"q1": 4, "1": 4}})}}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60}}
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass                                   # the caller was killed on purpose (crash test)


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def write_sims(upload: str, sims: int, people: int) -> list:
    ids = []
    for i in range(sims):
        sid = f"sim_load{i:02d}"
        d = os.path.join(upload, "simulations", sid)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "state.json"), "w") as f:
            json.dump({"simulation_id": sid, "project_id": "proj_load", "graph_id": "g", "status": "ready",
                       "profiles_generated": True, "config_generated": True, "enable_twitter": False}, f)
        profiles = [{"user_id": a, "name": f"Person {i}-{a}", "persona": "A shopper who compares prices.",
                     "age": 30 + a, "gender": "female" if a % 2 else "male", "country": "US",
                     "profession": ["Nurses", "Teachers"][a % 2]} for a in range(people)]
        with open(os.path.join(d, "reddit_profiles.json"), "w") as f:
            json.dump(profiles, f)
        with open(os.path.join(d, "simulation_config.json"), "w") as f:
            json.dump({}, f)
        ids.append(sid)
    return ids


def wait_http(url: str, timeout: float = 60) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            if requests.get(url, timeout=2).ok:
                return
        except requests.RequestException:
            pass
        time.sleep(0.2)
    raise RuntimeError(f"{url} did not come up")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=24)
    ap.add_argument("--sims", type=int, default=6)
    ap.add_argument("--people", type=int, default=8)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--worker-threads", type=int, default=3)
    ap.add_argument("--latency", type=float, default=0.25, help="fake model latency in seconds")
    ap.add_argument("--provider-limit", type=int, default=4)
    ap.add_argument("--workspace-limit", type=int, default=2)
    ap.add_argument("--no-crash", action="store_true")
    ap.add_argument("--json", help="write the results here")
    args = ap.parse_args()

    tmp = tempfile.mkdtemp(prefix="mm_jobs_load_")
    upload = os.path.join(tmp, "uploads")
    os.makedirs(upload)
    FakeLLM.latency = args.latency
    llm = ThreadingHTTPServer(("127.0.0.1", 0), FakeLLM)
    threading.Thread(target=llm.serve_forever, daemon=True).start()
    llm_url = f"http://127.0.0.1:{llm.server_address[1]}/v1"

    env_file = os.path.join(tmp, "fake.env")
    with open(env_file, "w") as f:
        f.write(f"LLM_PROVIDER=openai\nLLM_BASE_URL={llm_url}\nLLM_API_KEY=fake-key\nLLM_MODEL_NAME=fake-model\n"
                "MEMORY_BACKEND=local\nMEMORY_EMBEDDINGS=false\n")
    port = free_port()
    env = {k: os.environ[k] for k in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "USER") if k in os.environ}
    env.update({"MIROFISH_ENV_FILE": env_file, "MIROFISH_UPLOAD_DIR": upload,
                "MM_TASK_DB_PATH": os.path.join(tmp, "tasks.sqlite"), "FLASK_PORT": str(port), "FLASK_HOST": "127.0.0.1",
                "MM_JOB_EXTERNAL_WORKERS": "1", "MM_JOB_WORKERS": "2", "MM_JOB_LEASE_S": "6",
                "MM_JOB_LIMIT_PROVIDER": f"*={args.provider_limit}", "MM_JOB_LIMIT_WORKSPACE": f"*={args.workspace_limit}",
                "MM_EMOTIONS": "off", "MM_JEV_LABELS": "off", "PYTHONUNBUFFERED": "1"})
    py = sys.executable
    logs = open(os.path.join(tmp, "processes.log"), "w")

    def start_server():
        return subprocess.Popen([py, "run.py"], cwd=BACKEND, env=env, stdout=logs, stderr=logs)

    def start_worker():
        return subprocess.Popen([py, "-m", "app.jobs.worker", "--threads", str(args.worker_threads)], cwd=BACKEND,
                                env=env, stdout=logs, stderr=logs)

    base = f"http://127.0.0.1:{port}"
    server = start_server()
    procs = []
    try:
        wait_http(base + "/health")
        workers = [start_worker() for _ in range(args.workers)]
        procs = [server, *workers]
        sims = write_sims(upload, args.sims, args.people)
        time.sleep(2)

        workspaces = ["acme", "beta", "gamma"]
        t0 = time.time()
        submitted = []
        for i in range(args.runs):
            sid = sims[i % len(sims)]
            r = requests.post(base + "/api/simulation/questionnaire", timeout=30,
                              headers={"X-MM-Workspace": workspaces[i % len(workspaces)]},
                              json={"simulation_id": sid, "questions": "How likely are you to buy? [1-5]", "seed": i})
            r.raise_for_status()
            submitted.append(r.json()["data"]["task_id"])
        submit_s = time.time() - t0

        peak = {"provider": {}, "workspace": {}}
        crashed = {}

        def sample():
            try:
                st = requests.get(base + "/api/jobs/stats", timeout=5).json()["data"]
            except Exception:  # noqa: BLE001 - the server may be restarting
                return None
            for k in ("provider", "workspace"):
                for key, n in (st["running"].get(k) or {}).items():
                    peak[k][key] = max(peak[k].get(key, 0), n)
            return st

        def outcomes():
            try:
                rows = requests.get(base + "/api/jobs?limit=1000&kind=market_questionnaire", timeout=5).json()["data"]
            except Exception:  # noqa: BLE001
                return None
            return {j["job_id"]: j for j in rows}

        def wait_all(deadline_s):
            end = time.time() + deadline_s
            while time.time() < end:
                sample()
                jobs = outcomes()
                if jobs and all(jobs.get(t, {}).get("status") in ("succeeded", "failed", "cancelled", "needs_approval")
                                for t in submitted):
                    return jobs
                time.sleep(0.3)
            return outcomes() or {}

        if not args.no_crash:
            end = time.time() + 60
            while time.time() < end:
                st = sample()
                if st and st["counts"]["succeeded"] >= args.runs // 4 and st["counts"]["running"] > 0:
                    break
                time.sleep(0.2)
            victim = procs[1]
            victim.send_signal(signal.SIGKILL)
            server.send_signal(signal.SIGKILL)
            victim.wait()
            server.wait()
            crashed["at_s"] = round(time.time() - t0, 2)
            time.sleep(1.0)
            server = start_server()
            wait_http(base + "/health")
            procs[0], procs[1] = server, start_worker()
            crashed["restarted_at_s"] = round(time.time() - t0, 2)

        jobs = wait_all(240)
        first_pass = {s: sum(1 for j in jobs.values() if j["status"] == s)
                      for s in ("succeeded", "failed", "cancelled", "needs_approval", "queued", "running")}
        approved = []
        for t in submitted:
            if jobs.get(t, {}).get("status") == "needs_approval":
                r = requests.post(f"{base}/api/jobs/{t}/retry", json={"approve_spend": True}, timeout=10)
                if r.ok:
                    approved.append(t)
        if approved:
            jobs = wait_all(240)
        wall = time.time() - t0
        stats = sample() or {}

        statuses = {t: jobs.get(t, {}).get("status", "missing") for t in submitted}
        waits = sorted(j["queue_wait_s"] for t, j in jobs.items() if t in statuses and j.get("queue_wait_s") is not None)

        def pct(p):
            return round(waits[min(len(waits) - 1, int(round(p / 100 * (len(waits) - 1))))], 2) if waits else None
        task_status = {}
        for t in submitted:
            r = requests.post(base + "/api/simulation/market-task/status", json={"task_id": t}, timeout=10)
            task_status[t] = r.json()["data"]["status"] if r.ok else "missing"
        result_files = sum(os.path.exists(os.path.join(upload, "simulations", s, "questionnaire.json")) for s in sims)
        succeeded = sum(1 for s in statuses.values() if s == "succeeded")
        report = {
            "runs_submitted": len(submitted), "submit_seconds": round(submit_s, 2),
            "first_pass": first_pass, "approved_retries": len(approved),
            "final": {s: sum(1 for v in statuses.values() if v == s) for s in sorted(set(statuses.values()))},
            "lost_jobs": sum(1 for v in statuses.values() if v in ("missing", "queued", "running")),
            "tasks_mirror_jobs": all((statuses[t] == "succeeded") == (task_status[t] == "completed") for t in submitted),
            "wall_seconds": round(wall, 2), "throughput_runs_per_min": round(succeeded / wall * 60, 1),
            "queue_wait_s": {"p50": pct(50), "p95": pct(95), "max": waits[-1] if waits else None},
            "peak_running": peak, "limits": {"provider": args.provider_limit, "workspace": args.workspace_limit},
            "fake_llm_requests": FakeLLM.count,
            "model_calls_recorded": sum(j.get("model_calls", 0) for t, j in jobs.items() if t in statuses),
            "attempts_total": sum(j.get("attempts", 0) for t, j in jobs.items() if t in statuses),
            "crash": crashed or None, "result_files_written": result_files, "simulations": len(sims),
            "workers": args.workers, "worker_threads": args.worker_threads, "people_per_run": args.people,
            "fake_latency_s": args.latency, "live_workers_at_end": len(stats.get("workers", [])), "tmp": tmp,
        }
        print(json.dumps(report, indent=2))
        if args.json:
            with open(args.json, "w") as f:
                json.dump(report, f, indent=2)
        ok = report["lost_jobs"] == 0 and report["tasks_mirror_jobs"]
        return 0 if ok else 1
    finally:
        for p in procs or [server]:
            if p.poll() is None:
                p.send_signal(signal.SIGTERM)
        for p in procs or [server]:
            try:
                p.wait(15)
            except subprocess.TimeoutExpired:
                p.kill()
        llm.shutdown()
        logs.close()


if __name__ == "__main__":
    sys.exit(main())
