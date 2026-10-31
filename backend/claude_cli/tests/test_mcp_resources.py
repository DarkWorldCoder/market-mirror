"""MCP server: run files as resources, the dashboard as an MCP Apps UI resource, recipe prompts, and refusals."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
MCP = os.path.abspath(os.path.join(HERE, "..", "..", "..", "plugin", "skills", "market-mirror", "scripts", "mcp_server.py"))


def call(msgs, home):
    p = subprocess.run([sys.executable, MCP], input="\n".join(json.dumps(m) for m in msgs) + "\n",
                       capture_output=True, text=True, timeout=120, env={**os.environ, "MARKET_MIRROR_HOME": home})
    return {m["id"]: m for m in map(json.loads, p.stdout.splitlines()) if "id" in m}


class Resources(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, True)
        run = os.path.join(self.home, "mirofish_runs", "demo")
        os.makedirs(run)
        for f, text in (("dashboard.html", "<html>demo dashboard</html>"), ("summary.json", json.dumps({"decision": {"decision": "iterate"}})),
                        ("market_report.md", "# Report"), ("secret.txt", "nope")):
            with open(os.path.join(run, f), "w", encoding="utf-8") as fh:
                fh.write(text)

    def rpc(self, i, method, params=None):
        return {"jsonrpc": "2.0", "id": i, "method": method, "params": params or {}}

    def test_capabilities_resources_and_ui(self):
        out = call([self.rpc(1, "initialize", {"protocolVersion": "2025-06-18"}), self.rpc(2, "resources/list"),
                    self.rpc(3, "resources/read", {"uri": "marketmirror://runs/demo/summary.json"}),
                    self.rpc(4, "resources/read", {"uri": "ui://market-mirror/dashboard"}),
                    self.rpc(5, "resources/read", {"uri": "marketmirror://runs/demo/secret.txt"}),
                    self.rpc(6, "resources/read", {"uri": "marketmirror://runs/../demo/summary.json"}),
                    self.rpc(7, "resources/templates/list"), self.rpc(8, "tools/list")], self.home)
        self.assertEqual(set(out[1]["result"]["capabilities"]), {"tools", "resources", "prompts"})
        uris = [r["uri"] for r in out[2]["result"]["resources"]]
        self.assertIn("ui://market-mirror/dashboard", uris)
        self.assertIn("marketmirror://runs/demo/dashboard.html", uris)
        self.assertNotIn("marketmirror://runs/demo/secret.txt", uris)
        self.assertIn("iterate", out[3]["result"]["contents"][0]["text"])
        ui = out[4]["result"]["contents"][0]
        self.assertEqual(ui["mimeType"], "text/html;profile=mcp-app")
        self.assertIn("demo dashboard", ui["text"])
        self.assertEqual(out[5]["error"]["code"], -32602)
        self.assertEqual(out[6]["error"]["code"], -32602)
        self.assertIn("{run}", out[7]["result"]["resourceTemplates"][0]["uriTemplate"])
        res_tool = next(t for t in out[8]["result"]["tools"] if t["name"] == "results")
        self.assertEqual(res_tool["_meta"]["ui"]["resourceUri"], "ui://market-mirror/dashboard")

    def test_results_links_resources(self):
        out = call([self.rpc(1, "tools/call", {"name": "results", "arguments": {"run": "demo"}})], self.home)
        res = out[1]["result"]["structuredContent"]
        self.assertEqual(res["resources"]["market_report.md"], "marketmirror://runs/demo/market_report.md")

    def test_prompts(self):
        out = call([self.rpc(1, "prompts/list"),
                    self.rpc(2, "prompts/get", {"name": "pull_real_results", "arguments": {"source": "meta_ads", "run": "demo"}}),
                    self.rpc(3, "prompts/get", {"name": "test_an_ad", "arguments": {"product": "Fitloop"}}),
                    self.rpc(4, "prompts/get", {"name": "nope"}),
                    self.rpc(5, "prompts/get", {"name": "focus_group_after_run",
                                                "arguments": {"simulation_id": "sim_x", "questions": "Why?", "segment": "Nurses"}})],
                   self.home)
        names = {p["name"] for p in out[1]["result"]["prompts"]}
        self.assertEqual(names, {"test_an_ad", "price_check", "calibrate_with_real_data", "pull_real_results", "focus_group_after_run"})
        text = out[2]["result"]["messages"][0]["content"]["text"]
        self.assertIn("meta_ads", text)
        self.assertIn("paused draft", text)
        self.assertIn("actuals_import", text)
        self.assertIn("missing arguments: ads", out[3]["error"]["message"])
        self.assertEqual(out[4]["error"]["code"], -32602)
        self.assertIn("segment Nurses", out[5]["result"]["messages"][0]["content"]["text"])


if __name__ == "__main__":
    unittest.main()
