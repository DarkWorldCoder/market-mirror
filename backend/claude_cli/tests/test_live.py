"""Tests for `mirofish.py live`: stage labels, page injection, run discovery and the HTTP endpoints."""

import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import mirofish  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "sample_run")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class StageTest(unittest.TestCase):
    def test_stages_in_order(self):
        st = mirofish.live_stage
        self.assertEqual(st({}), "Waiting for the run to start")
        self.assertEqual(st({"project_id": "p"}), "Building the knowledge graph")
        self.assertEqual(st({"project_id": "p", "graph_id": "g"}), "Creating the simulation")
        self.assertEqual(st({"simulation_id": "s"}), "Preparing agents")
        self.assertEqual(st({"simulation_id": "s"}, {"runner_status": "running", "current_round": 3, "total_rounds": 10}),
                         "Simulating round 3/10")
        self.assertEqual(st({"simulation_id": "s", "runner_status": "completed"}), "Simulation finished; writing the report")
        self.assertEqual(st({"report_id": "r"}), "Writing the report")
        self.assertEqual(st({"report_id": "r", "finished_at": "x"}), "Done")
        self.assertTrue(st({"error": "boom"}).startswith("Stopped with error: boom"))


class InjectTest(unittest.TestCase):
    def test_injects_before_body_and_escapes_label(self):
        page = mirofish.inject_live("<html><body><p>x</p></body></html>", "<b>round 2</b>", 7, 5000)
        self.assertIn("&lt;b&gt;round 2&lt;/b&gt;", page)
        self.assertIn("var v=7,ms=5000", page)
        self.assertLess(page.index("/__live/state"), page.index("</body>"))

    def test_page_without_body_tag(self):
        self.assertIn("/__live/state", mirofish.inject_live("<p>x</p>", "Done", 1, 1000))


class LatestRunTest(unittest.TestCase):
    def test_picks_newest_manifest(self):
        root = tempfile.mkdtemp()
        try:
            for i, name in enumerate(["old", "new"]):
                d = os.path.join(root, name)
                os.makedirs(d)
                mp = os.path.join(d, "run_manifest.json")
                with open(mp, "w") as f:
                    json.dump({}, f)
                os.utime(mp, (1000 + i * 100, 1000 + i * 100))
            os.makedirs(os.path.join(root, "empty"))
            self.assertEqual(mirofish.latest_run_dir(root), os.path.join(root, "new"))
            self.assertIsNone(mirofish.latest_run_dir(os.path.join(root, "missing")))
        finally:
            shutil.rmtree(root)


class LiveServerTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        for name in os.listdir(FIXTURE):
            shutil.copy(os.path.join(FIXTURE, name), self.dir)

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_refresh_bumps_version_only_when_content_changes(self):
        live = mirofish.LiveDashboard(None, self.dir)
        build = mirofish.exporter.build_summary
        timestamps = iter(['2030-01-01T00:00:00', '2030-01-01T00:00:01'])
        def summary(*args, **kwargs):
            return {**build(*args, **kwargs), 'generated_at': next(timestamps)}
        with patch.object(mirofish.exporter, 'build_summary', side_effect=summary) as builds:
            live.refresh()
            first = live.state()["version"]
            live.refresh()
            self.assertEqual(builds.call_count, 1)
        self.assertEqual(live.state()["version"], first)
        with open(os.path.join(self.dir, "run_manifest.json"), "w") as f:
            json.dump({"project_id": "p", "simulation_id": "s", "finished_at": "now"}, f)
        live.refresh()
        self.assertEqual(live.state()["label"], "Done")
        self.assertGreater(live.state()["version"], first)

    def test_http_endpoints(self):
        port = free_port()
        live = mirofish.LiveDashboard(None, self.dir)
        t = threading.Thread(target=mirofish.serve_live, args=(live, "127.0.0.1", port, 1), daemon=True)
        t.start()
        base = f"http://127.0.0.1:{port}"
        deadline = time.time() + 10
        state = None
        while time.time() < deadline:
            try:
                state = json.loads(urllib.request.urlopen(base + "/__live/state", timeout=2).read())
                if state["version"] >= 1:
                    break
            except OSError:
                pass
            time.sleep(0.2)
        self.assertIsNotNone(state)
        self.assertGreaterEqual(state["version"], 1)
        html = urllib.request.urlopen(base + "/", timeout=5).read().decode("utf-8")
        self.assertIn("<svg", html)
        self.assertIn("/__live/state", html)
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(base + "/nope", timeout=5)


class ControlRoomTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        def w(name, data):
            with open(os.path.join(self.dir, name), "w", encoding="utf-8") as f:
                json.dump(data, f)
        w("run_manifest.json", {"title": "T", "project_id": "p", "graph_id": "g", "simulation_id": "s"})
        w("config.json", {"persona_index": [{"agent_id": i, "kind": "persona", "name": f"P{i}", "country": "India"} for i in range(3)]})
        w("actions.json", [{"agent_id": 0, "agent_name": "P0", "action_type": "CREATE_POST", "action_args": {"content": "hello"},
                            "round_num": 0, "platform": "reddit", "timestamp": "2026-10-19T10:00:00"},
                           {"agent_id": 1, "agent_name": "P1", "action_type": "DO_NOTHING", "round_num": 1, "timestamp": "2026-10-19T10:01:00"}])
        w("survey.json", {"responses": [{"agent_id": 2, "answer": {"would_convert": "yes"}}]})
        with open(os.path.join(self.dir, "progress.log"), "w") as f:
            f.write("[10:00:00] survey: 1/3 asked\n")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_feed(self):
        d = mirofish.live_view.feed(self.dir, "Simulating")
        states = {s["key"]: s["state"] for s in d["stages"]}
        self.assertEqual(states["simulation_id"], "done")
        self.assertEqual(states["feed_test"], "run")                      # first missing stage is the running one
        self.assertEqual(d["counters"]["posts"], 1)
        self.assertEqual(d["counters"]["yes"], 1)
        self.assertEqual([p["verdict"] for p in d["people"]], [None, None, "yes"])
        self.assertEqual([e["text"] for e in d["stream"]], ["hello"])     # silent scrolls are left out
        self.assertEqual(d["log"], ["[10:00:00] survey: 1/3 asked"])

    def test_endpoints_and_finished_runs_are_not_recollected(self):
        port = free_port()
        live = mirofish.LiveDashboard(None, self.dir)
        threading.Thread(target=mirofish.serve_live, args=(live, "127.0.0.1", port, 1), daemon=True).start()
        base = f"http://127.0.0.1:{port}"
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                page = urllib.request.urlopen(base + "/live", timeout=2).read().decode("utf-8")
                break
            except OSError:
                time.sleep(0.2)
        self.assertIn("/__live/feed", page)
        feed = json.loads(urllib.request.urlopen(base + "/__live/feed", timeout=5).read())
        self.assertEqual(feed["title"], "T")
        with open(os.path.join(self.dir, "run_manifest.json"), "w") as f:
            json.dump({"project_id": "p", "simulation_id": "s", "finished_at": "now"}, f)
        fake = mirofish.LiveDashboard(object(), self.dir)
        with patch.object(mirofish, "collect") as collect:
            fake.refresh()
        collect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
