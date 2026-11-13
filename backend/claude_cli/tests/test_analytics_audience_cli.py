"""analytics-audience offline: a GA4 export in, a persona spec (segments + population) and a report out; the owner's
own segments and shares survive; the MCP prompt tells the host to read only and to show the report first."""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import mirofish  # noqa: E402

MCP = os.path.abspath(os.path.join(HERE, "..", "..", "..", "plugin", "skills", "market-mirror", "scripts", "mcp_server.py"))

GA4 = ("# Start date: 20261001\n# End date: 20261031\n"
       "Country,City,Active users,Key events\nUnited States,Austin,600,12\nUnited States,Denver,400,4\nCanada,Toronto,500,5\n\n"
       "Country,Age,Gender,Active users\nUnited States,25-34,female,300\nUnited States,35-44,male,200\n"
       "Canada,25-34,female,100\nCanada,25-34,male,100\n")


def run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = mirofish.main(argv)
    return code, out.getvalue(), err.getvalue()


class AnalyticsAudienceCLI(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        self.csv = os.path.join(self.d, "ga4.csv")
        with open(self.csv, "w", encoding="utf-8") as f:
            f.write(GA4)

    def test_writes_spec_and_report_offline(self):
        base = os.path.join(self.d, "base.json")
        with open(base, "w", encoding="utf-8") as f:
            json.dump({"segments": [{"label": "Teachers", "count": 4, "country": "Canada"}],
                       "population": {"Canada": {"gender": {"female": 0.6, "male": 0.4}}}}, f)
        out = os.path.join(self.d, "scn", "personas.json")
        code, stdout, err = run_cli(["analytics-audience", "--files", self.csv, "--base", base, "--out", out,
                                     "--people", "10", "--role", "shoppers"])
        self.assertEqual(code, 0, err)
        res = json.loads(stdout)
        self.assertEqual(res["source"], "Google Analytics 4")
        self.assertEqual(res["period"], "2026-10-01 to 2026-10-31")
        self.assertEqual([(s["label"], s["count"]) for s in res["segments"]],
                         [("United States shoppers", 7), ("Canada shoppers", 3)])
        spec = json.load(open(out, encoding="utf-8"))
        self.assertEqual([s["label"] for s in spec["segments"]], ["Teachers", "United States shoppers", "Canada shoppers"])
        self.assertEqual(spec["population"]["Canada"], {"gender": {"female": 0.6, "male": 0.4}})   # the owner's shares
        self.assertEqual(spec["population"]["United States"]["age"], {"25-34": 0.6, "35-44": 0.4})
        md = open(os.path.join(self.d, "scn", "analytics_audience.md"), encoding="utf-8").read()
        self.assertIn("# Audience from Google Analytics 4", md)
        self.assertTrue(os.path.isfile(os.path.join(self.d, "scn", "analytics_audience.json")))

    def test_rows_from_an_agent_and_errors(self):
        rows = os.path.join(self.d, "rows.json")
        with open(rows, "w", encoding="utf-8") as f:
            json.dump({"columns": ["country", "count()"], "results": [["Japan", 30], ["Korea", 10]]}, f)
        out = os.path.join(self.d, "p.json")
        code, stdout, err = run_cli(["analytics-audience", "--rows", "@" + rows, "--out", out, "--people", "4",
                                     "--population-only"])
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(stdout)["segments"], [])
        self.assertNotIn("segments", json.load(open(out, encoding="utf-8")))
        code, _, _ = run_cli(["analytics-audience", "--out", out])
        self.assertEqual(code, 1)

    def test_prompt_reads_only_and_shows_the_report_first(self):
        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "prompts/get",
                 "params": {"name": "audience_from_analytics", "arguments": {"source": "ga4"}}},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}]
        p = subprocess.run([sys.executable, MCP], input="\n".join(json.dumps(m) for m in msgs) + "\n", capture_output=True,
                           text=True, timeout=120, env={**os.environ, "MARKET_MIRROR_HOME": self.d})
        out = {m["id"]: m for m in map(json.loads, p.stdout.splitlines()) if "id" in m}
        text = out[1]["result"]["messages"][0]["content"]["text"]
        self.assertIn("the last 30 days", text)
        self.assertIn("never change the property", text)
        self.assertIn("do not ask me for keys", text)
        self.assertLess(text.index("analytics_audience.md"), text.index("market_test"))
        tool = next(t for t in out[2]["result"]["tools"] if t["name"] == "analytics_audience")
        self.assertIn("reports", tool["inputSchema"]["properties"])

if __name__ == "__main__":
    unittest.main()
