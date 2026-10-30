"""Decision card, graph overlay and the MCP server protocol."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import feed_view  # noqa: E402
import marketing  # noqa: E402
from test_marketing import make_survey_bundle  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
MCP = os.path.join(REPO, "plugin", "skills", "market-mirror", "scripts", "mcp_server.py")


class DecisionTest(unittest.TestCase):
    def test_signals_combine_into_a_decision(self):
        b = make_survey_bundle()
        mk = marketing.analyze(b)
        b["feed_test"] = {"creatives": [{"id": "a", "platform": "facebook"}],
                          "summary": {"ranked": ["a"], "calibration": {"facebook": 1.5},
                                      "per_creative": {"a": {"impressions": 40, "expected_ctr": 0.6, "hide_rate": 35,
                                                             "landing": {"clicks": 4, "load_rate": 50, "converted": 1}}}}}
        b["analyst_panel"] = {"consensus": {"analysts_ok": 5, "success_probability": 35,
                                            "verdict": {"winner": "iterate", "agreement": 80}}}
        d = feed_view.decision(b, mk)
        votes = {s["name"]: s["vote"] for s in d["signals"]}
        self.assertEqual(votes["Feed test"], "no-go")          # expected CTR < 1% and many hides
        self.assertEqual(votes["Analyst panel"], "iterate")
        self.assertIn(d["decision"], ("iterate", "no-go"))
        self.assertIn("calibrating", next(s["detail"] for s in d["signals"] if s["name"] == "Feed test"))
        html = feed_view.decision_section(d)[2]
        self.assertIn(d["decision"].upper(), html)
        self.assertIsNone(feed_view.decision({}, {}))


class GraphOverlayTest(unittest.TestCase):
    def test_personas_and_communities_are_connected(self):
        graph = {"nodes": [{"uuid": "n1", "name": "Nepal", "labels": ["Entity", "Country"]}], "edges": []}
        cfg = {"persona_index": [
            {"agent_id": 0, "kind": "persona", "name": "Asha", "segment": "Nepal students", "country": "Nepal",
             "communities": ["MBBS Nepal"]},
            {"agent_id": 1, "kind": "persona", "name": "Ram", "segment": "Nepal students", "country": "Nepal",
             "communities": ["MBBS Nepal"]},
            {"agent_id": 2, "kind": "community", "name": "MBBS Nepal"}]}
        g = feed_view.augment_graph(graph, cfg)
        ids = {n["uuid"] for n in g["nodes"]}
        linked = {e["source_node_uuid"] for e in g["edges"]} | {e["target_node_uuid"] for e in g["edges"]}
        self.assertEqual(ids, linked)                            # nothing left unconnected
        self.assertIn("n1", linked)                              # reuses the existing country node
        self.assertEqual(sum(1 for e in g["edges"] if e["name"] == "LIVES_IN"), 1)
        self.assertEqual(feed_view.augment_graph(graph, {}), graph)


class RoundsDoneTest(unittest.TestCase):
    def test_interview_mode_counts_as_done(self):
        import mirofish
        self.assertTrue(mirofish.rounds_done({"runner_status": "running", "twitter_completed": True,
                                              "reddit_completed": True, "twitter_running": False, "reddit_running": False}))
        self.assertFalse(mirofish.rounds_done({"runner_status": "running", "twitter_completed": True,
                                               "reddit_completed": False, "reddit_running": True}))
        self.assertTrue(mirofish.rounds_done({"runner_status": "completed"}))

    def test_start_auto_uses_only_prepared_platform(self):
        import argparse
        import mirofish
        from unittest.mock import patch

        class Client:
            def data(self, method, path):
                self_call = (method, path)
                assert self_call == ("GET", "/api/simulation/sim_x")
                return {"enable_twitter": False, "enable_reddit": True}

        args = argparse.Namespace(simulation="sim_x", platform="auto", max_rounds=6,
                                  no_graph_memory=True, no_force=True, no_wait=True, timeout=60, interval=5)
        with patch.object(mirofish, "step_start", return_value={"status": "running"}) as start:
            mirofish.cmd_start(Client(), args)
        self.assertEqual(start.call_args.args[1:3], ("sim_x", "reddit"))


class MCPServerTest(unittest.TestCase):
    def test_protocol_and_tools(self):
        home = tempfile.mkdtemp()
        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "list_runs", "arguments": {}}},
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "nope", "arguments": {}}},
                {"jsonrpc": "2.0", "id": 5, "method": "bogus"}]
        p = subprocess.run([sys.executable, MCP], input="\n".join(json.dumps(m) for m in msgs) + "\n",
                           capture_output=True, text=True, timeout=60,
                           env={**os.environ, "MARKET_MIRROR_HOME": home})
        out = {m["id"]: m for m in map(json.loads, p.stdout.splitlines())}
        self.assertEqual(out[1]["result"]["serverInfo"]["name"], "market-mirror")
        names = [t["name"] for t in out[2]["result"]["tools"]]
        for n in ("market_test", "job_status", "results", "ads_import", "backtest", "start_live", "setup", "quickstart", "pitch", "ideas", "understand", "calibrate", "email_test", "run_test", "study", "predict", "research", "push_context", "ad_patterns", "intake"):
            self.assertIn(n, names)
        self.assertEqual(json.loads(out[3]["result"]["content"][0]["text"]), [])
        self.assertTrue(out[4]["result"]["isError"])
        self.assertEqual(out[5]["error"]["code"], -32601)
        self.assertNotIn(2.5, out)                               # notifications get no reply


if __name__ == "__main__":
    unittest.main()
