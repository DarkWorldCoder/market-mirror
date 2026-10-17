"""End-to-end test of `mirofish.py run` against a stdlib fake of the MiroFish API.

The fake mimics the real endpoint shapes and async-task status values
(pending/processing/completed, runner_status running->completed) so the
CLI's call sequence, polling and artifact collection are exercised without
an LLM key.
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(os.path.dirname(HERE), "mirofish.py")
FIXTURE = os.path.join(HERE, "fixtures", "sample_run")


def fixture(name):
    with open(os.path.join(FIXTURE, name + ".json"), encoding="utf-8") as f:
        return json.load(f)["data"]


class Fake:
    def __init__(self):
        self.calls = []
        self.polls = {}

    def tick(self, key, n=2):
        self.polls[key] = self.polls.get(key, 0) + 1
        return self.polls[key] >= n


def make_handler(state: Fake):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, data, code=200):
            body = json.dumps({"success": code < 400, **({"data": data} if code < 400 else {"error": data})}).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b""
            if self.headers.get("Content-Type", "").startswith("application/json"):
                return json.loads(raw or b"{}")
            return {"_raw_len": len(raw), "_ctype": self.headers.get("Content-Type")}

        def do_GET(self):
            u = urlparse(self.path)
            p, q = u.path, parse_qs(u.query)
            state.calls.append(("GET", p))
            if p == "/health":
                return self.send_json_raw({"status": "ok", "service": "MiroFish Backend"})
            if p == "/api/graph/task/task_g":
                done = state.tick("graph")
                return self._send({"task_id": "task_g", "status": "completed" if done else "processing",
                                   "progress": 100 if done else 40, "message": "building",
                                   "result": {"graph_id": "mirofish_demo123", "node_count": 24, "edge_count": 70} if done else None})
            if p == "/api/graph/project/proj_demo123":
                return self._send(fixture("project"))
            if p == "/api/graph/data/mirofish_demo123":
                return self._send(fixture("graph"))
            if p == "/api/simulation/sim_demo123":
                return self._send(fixture("simulation"))
            if p == "/api/simulation/sim_demo123/config":
                return self._send(fixture("config"))
            if p == "/api/simulation/sim_demo123/profiles":
                plat = q.get("platform", ["reddit"])[0]
                return self._send(fixture("profiles_reddit") if plat == "reddit" else {"platform": plat, "count": 0, "profiles": []})
            if p == "/api/simulation/sim_demo123/posts":
                return self._send(fixture("posts_" + q.get("platform", ["reddit"])[0]))
            if p == "/api/simulation/sim_demo123/comments":
                plat = q.get("platform", ["reddit"])[0]
                return self._send(fixture("comments_reddit") if plat == "reddit" else {"count": 0, "comments": []})
            if p == "/api/simulation/sim_demo123/run-status":
                done = state.tick("run", 3)
                rs = dict(fixture("run_status"))
                if not done:
                    rs.update(runner_status="running", current_round=4)
                return self._send(rs)
            if p == "/api/simulation/sim_demo123/timeline":
                return self._send(fixture("timeline"))
            if p == "/api/simulation/sim_demo123/actions":
                acts = fixture("actions")["actions"]
                off, lim = int(q.get("offset", [0])[0]), int(q.get("limit", [100])[0])
                return self._send({"count": len(acts[off:off + lim]), "actions": acts[off:off + lim]})
            if p == "/api/simulation/sim_demo123/agent-stats":
                return self._send({"agents_count": 0, "stats": []})
            if p == "/api/report/report_demo123":
                return self._send(fixture("report"))
            return self._send(f"unknown {p}", 404)

        def send_json_raw(self, obj):
            body = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            p = urlparse(self.path).path
            b = self._body()
            state.calls.append(("POST", p, b))
            if p == "/api/graph/ontology/generate":
                assert b["_ctype"].startswith("multipart/form-data")
                proj = fixture("project")
                return self._send({"project_id": "proj_demo123", "project_name": proj["name"], "ontology": proj["ontology"],
                                   "analysis_summary": "", "files": proj["files"], "total_text_length": 10})
            if p == "/api/graph/build":
                return self._send({"project_id": b["project_id"], "task_id": "task_g", "message": "started"})
            if p == "/api/simulation/create":
                return self._send({**fixture("simulation"), "status": "created",
                                   "enable_twitter": b["enable_twitter"], "enable_reddit": b["enable_reddit"]})
            if p == "/api/simulation/prepare":
                return self._send({"simulation_id": b["simulation_id"], "task_id": "task_p", "status": "preparing",
                                   "already_prepared": False, "expected_entities_count": 24, "entity_types": ["Student"]})
            if p == "/api/simulation/prepare/status":
                done = state.tick("prep")
                return self._send({"task_id": "task_p", "status": "completed" if done else "processing",
                                   "progress": 100 if done else 50, "message": "profiles",
                                   "progress_detail": {"current_stage_name": "Generating profiles"}, "already_prepared": False})
            if p == "/api/simulation/start":
                return self._send({"simulation_id": b["simulation_id"], "runner_status": "running", "process_pid": 1,
                                   "max_rounds_applied": b.get("max_rounds"), "graph_memory_update_enabled": b["enable_graph_memory_update"]})
            if p == "/api/report/generate":
                return self._send({"simulation_id": b["simulation_id"], "report_id": "report_demo123", "task_id": "task_r",
                                   "status": "generating", "already_generated": False})
            if p == "/api/report/generate/status":
                assert "simulation_id" not in b, "must poll by task_id only"
                done = state.tick("rep")
                return self._send({"task_id": "task_r", "status": "completed" if done else "processing", "progress": 60})
            return self._send(f"unknown {p}", 404)
    return H


class PipelineTest(unittest.TestCase):
    def test_run_end_to_end(self):
        try:
            import requests  # noqa: F401
        except ImportError:
            self.skipTest("requests not installed")
        state = Fake()
        srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as d:
                seed = os.path.join(d, "seed.md")
                with open(seed, "w") as f:
                    f.write("# Seed\nRiverside raises tuition.")
                out = os.path.join(d, "run")
                proc = subprocess.run([sys.executable, CLI, "--base-url", f"http://127.0.0.1:{srv.server_port}",
                                       "run", "--seed", seed, "--requirement", "How do students react?",
                                       "--platform", "reddit", "--max-rounds", "3", "--out", out, "--interval", "0.05"],
                                      capture_output=True, text=True, timeout=120)
                self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
                res = json.loads(proc.stdout)
                self.assertEqual(res["simulation_id"], "sim_demo123")
                self.assertEqual(res["report_id"], "report_demo123")
                for name in ["ontology", "project", "graph", "simulation", "config", "profiles_reddit", "timeline",
                             "actions", "run_status", "report", "run_manifest", "summary"]:
                    self.assertTrue(os.path.exists(os.path.join(out, name + ".json")), name)
                self.assertTrue(os.path.exists(os.path.join(out, "dashboard.html")))
                self.assertIn("round 4/12", proc.stderr)  # progress lines on stderr
                posts = {c[1]: c[2] for c in state.calls if c[0] == "POST"}
                self.assertEqual(posts["/api/simulation/create"], {"project_id": "proj_demo123", "enable_twitter": False,
                                                                   "enable_reddit": True, "graph_id": "mirofish_demo123"})
                self.assertEqual(posts["/api/simulation/start"]["max_rounds"], 3)
                self.assertEqual(posts["/api/simulation/start"]["platform"], "reddit")
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
