"""MCP server: tasks (2025-11-25 utility and the 2026-07-28 Tasks extension) and spend approval through elicitation.

Every test drives the real server and the real mm.sh / job_worker over stdio (one test over loopback HTTP). Only the
engine is fake: a temporary MARKET_MIRROR_HOME whose mirofish.py answers instantly, so nothing calls a model.
"""

import http.client
import json
import os
import queue
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
MCP = os.path.abspath(os.path.join(HERE, "..", "..", "..", "plugin", "skills", "market-mirror", "scripts", "mcp_server.py"))
STATELESS = "2026-07-28"
TASKS_EXT = "io.modelcontextprotocol/tasks"

FAKE_CLI = r'''
import json, sys, time
cmd = sys.argv[1]
if cmd == "market-test":
    cfg = json.load(open(sys.argv[2], encoding="utf-8"))
    print(json.dumps({"stage": "done" if cfg.get("approve_spend") else "personas_ready",
                      "approve_spend": bool(cfg.get("approve_spend")), "name": cfg.get("name")}))
elif cmd == "nap":
    print("napping", file=sys.stderr, flush=True)
    time.sleep(float(sys.argv[2]))
    print(json.dumps({"slept": float(sys.argv[2])}))
elif cmd == "fail":
    print("boom", file=sys.stderr)
    sys.exit(3)
'''


def fake_home():
    root = tempfile.mkdtemp()
    engine = os.path.join(root, "engine")
    os.makedirs(os.path.join(engine, "backend", ".venv", "bin"))
    os.makedirs(os.path.join(engine, "backend", "claude_cli"))
    py = os.path.join(engine, "backend", ".venv", "bin", "python")
    with open(py, "w", encoding="utf-8") as f:
        f.write(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    os.chmod(py, 0o755)
    with open(os.path.join(engine, "backend", "claude_cli", "mirofish.py"), "w", encoding="utf-8") as f:
        f.write(FAKE_CLI)
    env = {**os.environ, "HOME": root, "MARKET_MIRROR_HOME": engine, "MARKET_MIRROR_USD_PER_CALL": "0.01"}
    return root, env


def v2_meta(caps):
    return {"io.modelcontextprotocol/protocolVersion": STATELESS,
            "io.modelcontextprotocol/clientInfo": {"name": "test", "version": "0"},
            "io.modelcontextprotocol/clientCapabilities": caps}


class Client:
    """A line-delimited JSON-RPC peer on the server's stdio that can also answer the server's requests."""

    def __init__(self, env):
        self.p = subprocess.Popen([sys.executable, MCP], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, env=env)
        self.inbox = queue.Queue()
        self.ids = iter(range(1, 10_000))
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.p.stdout:
            self.inbox.put(json.loads(line))

    def send(self, msg):
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()

    def request(self, method, params=None):
        mid = next(self.ids)
        self.send({"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}})
        return mid

    def wait(self, pred, timeout=20):
        end, stash, found = time.time() + timeout, [], None
        while found is None and time.time() < end:
            try:
                msg = self.inbox.get(timeout=0.1)
            except queue.Empty:
                continue
            if pred(msg):
                found = msg
            else:
                stash.append(msg)
        for m in stash:
            self.inbox.put(m)
        if found is None:
            raise AssertionError("no matching message from the server")
        return found

    def reply_to(self, mid, timeout=20):
        return self.wait(lambda m: m.get("id") == mid and "method" not in m, timeout)

    def call(self, method, params=None, timeout=20):
        return self.reply_to(self.request(method, params), timeout)

    def server_request(self, method, timeout=20):
        return self.wait(lambda m: m.get("method") == method and "id" in m, timeout)

    def init(self, version="2025-11-25", caps=None):
        out = self.call("initialize", {"protocolVersion": version, "capabilities": caps or {},
                                       "clientInfo": {"name": "test", "version": "0"}})
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return out["result"]

    def close(self):
        if self.p.poll() is None:
            self.p.stdin.close()
            try:
                self.p.wait(10)
            except subprocess.TimeoutExpired:
                self.p.kill()


class Base(unittest.TestCase):
    def setUp(self):
        self.root, self.env = fake_home()
        self.addCleanup(shutil.rmtree, self.root, True)

    def client(self):
        c = Client(self.env)
        self.addCleanup(c.close)
        return c

    def job_done(self, c, job_id, timeout=20):
        end = time.time() + timeout
        while time.time() < end:
            st = c.call("tools/call", {"name": "job_status", "arguments": {"job_id": job_id}})["result"]["structuredContent"]
            if st["status"] != "running":
                return st
            time.sleep(0.2)
        raise AssertionError("job did not finish")


class Capabilities(Base):
    def test_tasks_advertised_only_to_clients_that_negotiate_them(self):
        c = self.client()
        caps = c.init("2025-11-25", {"tasks": {}, "elicitation": {}})["capabilities"]
        self.assertEqual(caps["tasks"], {"cancel": {}, "requests": {"tools": {"call": {}}}})
        tools = {t["name"]: t for t in c.call("tools/list")["result"]["tools"]}
        self.assertEqual(tools["market_test"]["execution"], {"taskSupport": "optional"})
        self.assertEqual(tools["study"]["execution"], {"taskSupport": "optional"})
        self.assertNotIn("execution", tools["results"])

        for version, client_caps in (("2025-11-25", {"elicitation": {}}), ("2025-06-18", {"tasks": {}})):
            plain = self.client()
            caps = plain.init(version, client_caps)["capabilities"]
            self.assertNotIn("tasks", caps, version)
            self.assertEqual(set(caps), {"tools", "resources", "prompts"})
            self.assertFalse(any("execution" in t for t in plain.call("tools/list")["result"]["tools"]))
            err = plain.call("tasks/get", {"taskId": "x"})["error"]
            self.assertEqual(err["code"], -32601)
            # without tasks a task-augmented call is an ordinary call and job_status polling stays
            res = plain.call("tools/call", {"name": "cli", "arguments": {"args": ["nap", "0"]}, "task": {"ttl": 60000}})
            self.assertIn("job_id", res["result"]["structuredContent"])

    def test_stateless_discover_and_per_request_capabilities(self):
        c = self.client()
        disc = c.call("server/discover", {"_meta": v2_meta({})})["result"]
        self.assertIn(STATELESS, disc["supportedVersions"])
        self.assertIn("2025-11-25", disc["supportedVersions"])
        self.assertEqual(disc["capabilities"]["extensions"], {TASKS_EXT: {}})
        self.assertEqual(disc["resultType"], "complete")
        # no extension on this request: the long tool answers the old way (a job handle), never a task
        res = c.call("tools/call", {"name": "cli", "arguments": {"args": ["nap", "0"]}, "_meta": v2_meta({})})["result"]
        self.assertEqual(res["resultType"], "complete")
        self.assertIn("job_id", res["structuredContent"])
        err = c.call("tasks/get", {"taskId": "x", "_meta": v2_meta({})})["error"]
        self.assertEqual(err["code"], -32021)
        self.assertEqual(err["data"]["requiredCapabilities"]["extensions"], {TASKS_EXT: {}})


class Tasks(Base):
    def test_task_round_trip_2025_11_25(self):
        c = self.client()
        c.init("2025-11-25", {"tasks": {}})
        created = c.call("tools/call", {"name": "cli", "arguments": {"args": ["nap", "1"]}, "task": {"ttl": 120000}})["result"]
        task = created["task"]
        self.assertEqual(task["status"], "working")
        self.assertEqual(task["ttl"], 120000)
        self.assertGreaterEqual(len(task["taskId"]), 20)
        self.assertIn("model-immediate-response", json.dumps(created["_meta"]))
        tid = task["taskId"]
        self.assertEqual(c.call("tasks/get", {"taskId": tid})["result"]["status"], "working")
        pending = c.request("tasks/result", {"taskId": tid})
        self.assertEqual(c.call("ping")["result"], {})          # tasks/result blocks only its own request
        result = c.reply_to(pending)["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"]["result"], {"slept": 1.0})
        self.assertEqual(result["_meta"]["io.modelcontextprotocol/related-task"], {"taskId": tid})
        self.assertEqual(c.call("tasks/get", {"taskId": tid})["result"]["status"], "completed")
        self.assertEqual(c.call("tasks/cancel", {"taskId": tid})["error"]["code"], -32602)
        self.assertEqual(c.call("tasks/get", {"taskId": "nope"})["error"]["code"], -32602)
        # a tool without task support is refused as a task
        self.assertEqual(c.call("tools/call", {"name": "results", "arguments": {"run": "x"}, "task": {}})["error"]["code"], -32601)
        # the failed job fails the task (2025-11-25: isError => failed)
        tid = c.call("tools/call", {"name": "cli", "arguments": {"args": ["fail"]}, "task": {}})["result"]["task"]["taskId"]
        res = c.call("tasks/result", {"taskId": tid})["result"]
        self.assertTrue(res["isError"])
        self.assertEqual(c.call("tasks/get", {"taskId": tid})["result"]["status"], "failed")

    def test_task_cancel_stops_the_job(self):
        c = self.client()
        c.init("2025-11-25", {"tasks": {}})
        task = c.call("tools/call", {"name": "cli", "arguments": {"args": ["nap", "30"]}, "task": {}})["result"]["task"]
        time.sleep(0.5)
        cancelled = c.call("tasks/cancel", {"taskId": task["taskId"]})["result"]
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(c.call("tasks/get", {"taskId": task["taskId"]})["result"]["status"], "cancelled")
        res = c.call("tasks/result", {"taskId": task["taskId"]})["result"]
        self.assertTrue(res["isError"])

    def test_task_round_trip_tasks_extension(self):
        c = self.client()
        meta = v2_meta({"extensions": {TASKS_EXT: {}}})
        created = c.call("tools/call", {"name": "cli", "arguments": {"args": ["nap", "0.5"]}, "_meta": meta})["result"]
        self.assertEqual(created["resultType"], "task")
        self.assertEqual(created["status"], "working")
        self.assertEqual(created["pollIntervalMs"], 5000)
        tid = created["taskId"]
        end = time.time() + 20
        while True:
            got = c.call("tasks/get", {"taskId": tid, "_meta": meta})["result"]
            self.assertEqual(got["resultType"], "complete")
            if got["status"] != "working":
                break
            self.assertLess(time.time(), end)
            time.sleep(0.2)
        self.assertEqual(got["status"], "completed")
        self.assertEqual(got["result"]["structuredContent"]["result"], {"slept": 0.5})
        self.assertEqual(c.call("tasks/update", {"taskId": tid, "inputResponses": {}, "_meta": meta})["result"],
                         {"resultType": "complete"})
        self.assertEqual(c.call("tasks/result", {"taskId": tid, "_meta": meta})["error"]["code"], -32601)
        # short tools stay synchronous even for a task-capable client
        res = c.call("tools/call", {"name": "list_runs", "arguments": {}, "_meta": meta})["result"]
        self.assertEqual(res["resultType"], "complete")
        # a tool error is a completed task with isError (failed is for JSON-RPC errors only)
        tid = c.call("tools/call", {"name": "cli", "arguments": {"args": ["fail"]}, "_meta": meta})["result"]["taskId"]
        end = time.time() + 20
        while (got := c.call("tasks/get", {"taskId": tid, "_meta": meta})["result"])["status"] == "working":
            self.assertLess(time.time(), end)
            time.sleep(0.2)
        self.assertEqual(got["status"], "completed")
        self.assertTrue(got["result"]["isError"])
        # cancel is acknowledged with an empty result, and the task ends cancelled
        tid = c.call("tools/call", {"name": "cli", "arguments": {"args": ["nap", "30"]}, "_meta": meta})["result"]["taskId"]
        self.assertEqual(c.call("tasks/cancel", {"taskId": tid, "_meta": meta})["result"], {"resultType": "complete"})
        self.assertEqual(c.call("tasks/get", {"taskId": tid, "_meta": meta})["result"]["status"], "cancelled")

    def test_task_survives_a_server_restart(self):
        c = self.client()
        c.init("2025-11-25", {"tasks": {}})
        tid = c.call("tools/call", {"name": "cli", "arguments": {"args": ["nap", "0"]}, "task": {}})["result"]["task"]["taskId"]
        c.close()
        again = self.client()
        again.init("2025-11-25", {"tasks": {}})
        self.assertEqual(again.call("tasks/result", {"taskId": tid})["result"]["structuredContent"]["result"], {"slept": 0.0})


CONFIG = {"name": "spend_test", "seeds": ["/tmp/brief.md"], "auto_personas": 10, "rounds": 3,
          "survey": {"offer": "x", "goal": "y"}}


class Elicitation(Base):
    def start_market_test(self, c, config=None, task=None):
        params = {"name": "market_test", "arguments": {"config": config or CONFIG}}
        if task is not None:
            params["task"] = task
        return c.request("tools/call", params)

    def test_accepted_runs_with_approved_spend(self):
        c = self.client()
        c.init("2025-11-25", {"elicitation": {"form": {}}})
        mid = self.start_market_test(c)
        ask = c.server_request("elicitation/create")
        params = ask["params"]
        self.assertEqual(params["mode"], "form")
        self.assertIn("10 simulated people", params["message"])
        self.assertIn("$", params["message"])
        options = [o["const"] for o in params["requestedSchema"]["properties"]["decision"]["oneOf"]]
        self.assertEqual(options, ["run", "people_first"])
        self.assertEqual(c.call("ping")["result"], {})       # the loop keeps serving while the user decides
        c.send({"jsonrpc": "2.0", "id": ask["id"], "result": {"action": "accept", "content": {"decision": "run"}}})
        res = c.reply_to(mid)["result"]["structuredContent"]
        self.assertEqual(res["approval"]["decision"], "run")
        # 10 people: 2 planning + 10 interviews + 3 follow-ups, 30 round actions, 10 survey answers, 12 report calls
        self.assertEqual(res["approval"]["plan"]["total_calls"], 67)
        self.assertEqual(res["approval"]["plan"]["usd_estimate"], 0.67)
        self.assertEqual(self.job_done(c, res["job_id"])["result"]["approve_spend"], True)

    def test_people_first_keeps_the_guard(self):
        c = self.client()
        c.init("2025-11-25", {"elicitation": {}})
        mid = self.start_market_test(c)
        ask = c.server_request("elicitation/create")
        c.send({"jsonrpc": "2.0", "id": ask["id"], "result": {"action": "accept", "content": {"decision": "people_first"}}})
        res = c.reply_to(mid)["result"]["structuredContent"]
        self.assertEqual(self.job_done(c, res["job_id"])["result"],
                         {"stage": "personas_ready", "approve_spend": False, "name": "spend_test"})

    def test_declined_and_cancelled_start_nothing(self):
        c = self.client()
        c.init("2025-11-25", {"elicitation": {}})
        for answer in ({"result": {"action": "decline"}}, {"result": {"action": "cancel"}},
                       {"result": {"action": "accept", "content": {"decision": "spend it all"}}},
                       {"error": {"code": -32603, "message": "client could not show the form"}}):
            mid = self.start_market_test(c, {**CONFIG, "simulation_id": "sim_1"})
            ask = c.server_request("elicitation/create")
            options = [o["const"] for o in ask["params"]["requestedSchema"]["properties"]["decision"]["oneOf"]]
            self.assertEqual(options, ["run", "stop"])
            c.send({"jsonrpc": "2.0", "id": ask["id"], **answer})
            res = c.reply_to(mid)["result"]["structuredContent"]
            self.assertEqual(res["stage"], "stopped", answer)
            self.assertNotIn("job_id", res)
        self.assertFalse(os.path.isdir(os.path.join(self.root, ".market-mirror", "jobs")))

    def test_unsupported_client_keeps_todays_flow(self):
        c = self.client()
        c.init("2025-06-18", {})
        res = c.call("tools/call", {"name": "market_test", "arguments": {"config": CONFIG}})["result"]["structuredContent"]
        self.assertNotIn("approval", res)
        self.assertEqual(self.job_done(c, res["job_id"])["result"]["stage"], "personas_ready")
        res = c.call("tools/call", {"name": "market_test", "arguments": {"config": {**CONFIG, "approve_spend": True}}})
        self.assertIn("job_id", res["result"]["structuredContent"])
        self.assertTrue(c.inbox.empty())                     # no request was ever sent to this client

    def test_elicitation_then_task(self):
        c = self.client()
        c.init("2025-11-25", {"elicitation": {}, "tasks": {}})
        mid = self.start_market_test(c, task={})
        ask = c.server_request("elicitation/create")
        c.send({"jsonrpc": "2.0", "id": ask["id"], "result": {"action": "accept", "content": {"decision": "run"}}})
        tid = c.reply_to(mid)["result"]["task"]["taskId"]
        out = c.call("tasks/result", {"taskId": tid})["result"]["structuredContent"]
        self.assertEqual(out["result"]["stage"], "done")

    def test_stateless_multi_round_trip(self):
        c = self.client()
        meta = v2_meta({"elicitation": {}, "extensions": {TASKS_EXT: {}}})
        first = c.call("tools/call", {"name": "market_test", "arguments": {"config": CONFIG}, "_meta": meta})["result"]
        self.assertEqual(first["resultType"], "input_required")
        req = first["inputRequests"]["approve_spend"]
        self.assertEqual(req["method"], "elicitation/create")
        self.assertIn("10 simulated people", req["params"]["message"])
        self.assertTrue(c.inbox.empty())                     # MRTR: no server-initiated request
        declined = c.call("tools/call", {"name": "market_test", "arguments": {"config": CONFIG}, "_meta": meta,
                                         "inputResponses": {"approve_spend": {"action": "decline"}}})["result"]
        self.assertEqual(declined["resultType"], "complete")
        self.assertEqual(declined["structuredContent"]["stage"], "stopped")
        task = c.call("tools/call", {"name": "market_test", "arguments": {"config": CONFIG}, "_meta": meta,
                                     "inputResponses": {"approve_spend": {"action": "accept", "content": {"decision": "run"}}}})["result"]
        self.assertEqual(task["resultType"], "task")
        end = time.time() + 20
        while (got := c.call("tasks/get", {"taskId": task["taskId"], "_meta": meta})["result"])["status"] == "working":
            self.assertLess(time.time(), end)
            time.sleep(0.2)
        self.assertEqual(got["result"]["structuredContent"]["result"]["approve_spend"], True)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class HttpElicitation(Base):
    def test_elicitation_over_loopback_http(self):
        token = "local-test-token-0123456789abcdef"
        tok = os.path.join(self.root, "token")
        with open(tok, "w", encoding="utf-8") as f:
            f.write(token)
        port = free_port()
        proc = subprocess.Popen([sys.executable, MCP, "--http", "--port", str(port), "--token-file", tok],
                                env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(proc.kill)
        headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream"}

        def post(body, extra=None):
            for _ in range(100):
                try:
                    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
                    conn.request("POST", "/mcp", json.dumps(body), {**headers, **(extra or {})})
                    return conn.getresponse()
                except ConnectionRefusedError:
                    time.sleep(0.05)
            raise AssertionError("server did not start")

        init = post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                     "params": {"protocolVersion": "2025-11-25", "capabilities": {"elicitation": {}}}})
        sid = init.getheader("Mcp-Session-Id")
        self.assertTrue(sid)
        self.assertEqual(json.load(init)["result"]["protocolVersion"], "2025-11-25")
        session = {"Mcp-Session-Id": sid, "MCP-Protocol-Version": "2025-11-25"}
        self.assertEqual(post({"jsonrpc": "2.0", "method": "notifications/initialized"}, session).status, 202)

        stream = post({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                       "params": {"name": "market_test", "arguments": {"config": CONFIG}}}, session)
        self.assertEqual(stream.getheader("Content-Type"), "text/event-stream")

        def event():
            data = None
            while True:
                line = stream.fp.readline().decode().rstrip("\n")
                if line.startswith("data: "):
                    data = json.loads(line[6:])
                elif line == "" and data is not None:
                    return data

        ask = event()
        self.assertEqual(ask["method"], "elicitation/create")
        self.assertIn("10 simulated people", ask["params"]["message"])
        # another request is served while this one waits on the user
        self.assertEqual(json.load(post({"jsonrpc": "2.0", "id": 3, "method": "ping"}, session))["result"], {})
        answer = post({"jsonrpc": "2.0", "id": ask["id"], "result": {"action": "accept", "content": {"decision": "run"}}}, session)
        self.assertEqual(answer.status, 202)
        final = event()
        self.assertEqual(final["id"], 2)
        self.assertEqual(final["result"]["structuredContent"]["approval"]["decision"], "run")
        self.assertEqual(post({"jsonrpc": "2.0", "id": 4, "method": "ping"}, {"Mcp-Session-Id": "nope"}).status, 404)
        # a client that never initialized (no session) keeps the old flow: JSON, no elicitation
        plain = post({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                      "params": {"name": "market_test", "arguments": {"config": CONFIG}}})
        self.assertEqual(plain.getheader("Content-Type"), "application/json")
        self.assertIn("job_id", json.load(plain)["result"]["structuredContent"])


if __name__ == "__main__":
    unittest.main()
