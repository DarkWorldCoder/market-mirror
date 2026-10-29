"""ad-patterns command offline (--engine supplied), the bundled sample, and the dashboard section."""

import contextlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import exporter  # noqa: E402
import market_cli  # noqa: E402
import mirofish  # noqa: E402
import report_view  # noqa: E402

SAMPLE = os.path.abspath(os.path.join(HERE, "..", "..", "..", "docs", "examples", "ad_patterns_sample.json"))
FEED = {"creatives": [{"id": "mine", "platform": "instagram", "text": "Stop stretching cold.", "page": "Me"}],
        "summary": {"per_creative": {"mine": {"expected_ctr": 1.8}}}}


def run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = mirofish.main(argv)
    return code, out.getvalue(), err.getvalue()


class AdPatternsCLI(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)

    def test_sample_offline_writes_json_md_csv(self):
        out = os.path.join(self.d, "ap", "ad_patterns.json")
        code, stdout, _ = run_cli(["ad-patterns", "--ads", SAMPLE, "--engine", "supplied", "--out", out, "--brand", "Demo"])
        self.assertEqual(code, 0, stdout)
        res = json.loads(stdout)
        self.assertEqual(res["engine"], "supplied")
        self.assertEqual(res["counts"]["labelled"], res["counts"]["ads"])
        self.assertTrue(res["findings"] and all("[real_longevity]" in f for f in res["findings"]))
        data = json.load(open(out, encoding="utf-8"))
        self.assertEqual(data["longevity"]["kind"], "real_longevity")
        self.assertIn("Real-ad patterns, not performance", open(out[:-5] + ".md", encoding="utf-8").read())
        self.assertTrue(open(out[:-5] + ".csv", encoding="utf-8").readline().startswith("id,brand,source"))

    def test_supplied_skips_unlabelled_rows_and_simulated_creatives(self):
        run = os.path.join(self.d, "run")
        os.makedirs(run)
        json.dump(FEED, open(os.path.join(run, "feed_test.json"), "w"))
        rows = json.load(open(SAMPLE, encoding="utf-8"))["ads"][:12] + [{"id": "raw", "text": "no labels here"}]
        logs = []
        res = market_cli.ad_patterns(None, logs.append, ads_rows=rows, run_dir=run, engine="supplied", now="2026-10-27")
        self.assertTrue(any("skipping 1 simulated creatives" in m for m in logs), logs)
        self.assertTrue(any("1 rows have no labels" in m for m in logs), logs)
        data = json.load(open(res["ad_patterns"], encoding="utf-8"))
        self.assertEqual(data["counts"]["unlabelled"], 1)
        self.assertEqual(data["counts"]["simulated_creatives"], 0)
        self.assertIsNone(data["simulated"])

    def test_labelling_without_backend_is_a_clear_error(self):
        with self.assertRaises(ValueError) as e:
            market_cli.ad_patterns(None, lambda m: None, ads_rows=[{"text": "x"}], engine="llm")
        self.assertIn("--engine supplied", str(e.exception))
        code, stdout, _ = run_cli(["ad-patterns", "--rows", '{"oops": 1}', "--engine", "supplied"])
        self.assertEqual(code, 1)
        self.assertIn("--rows must be a JSON list", stdout)

    def test_backend_path_posts_rows_and_feed(self):
        run = os.path.join(self.d, "run")
        os.makedirs(run)
        json.dump(FEED, open(os.path.join(run, "feed_test.json"), "w"))
        ap = market_cli.load_service("ad_patterns")
        sent = {}

        class FakeClient:
            def data(self, method, path, json=None, timeout=None):
                sent.update(method=method, path=path, body=json)
                return ap.analyse(ap.normalize_ads(json["ads"], now="2026-10-27"), "llm", {"usage": {"calls": 1}})

        rows = json.load(open(SAMPLE, encoding="utf-8"))["ads"][:8]
        res = market_cli.ad_patterns(FakeClient(), lambda m: None, ads_rows=rows, run_dir=run, engine="auto")
        self.assertEqual((sent["method"], sent["path"]), ("POST", "/api/simulation/ad-patterns"))
        self.assertEqual(sent["body"]["feed_test"]["creatives"][0]["id"], "mine")
        self.assertEqual(sent["body"]["feed_test"]["summary"]["per_creative"]["mine"]["expected_ctr"], 1.8)
        self.assertEqual(res["usage"], {"calls": 1})
        self.assertTrue(os.path.exists(os.path.join(run, "ad_patterns.csv")))


class AdPatternsMCP(unittest.TestCase):
    def _server(self):
        import importlib.util
        path = os.path.abspath(os.path.join(HERE, "..", "..", "..", "plugin", "skills", "market-mirror", "scripts", "mcp_server.py"))
        spec = importlib.util.spec_from_file_location("mm_mcp_server_test", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_tool_needs_input_and_results_summarise_patterns(self):
        srv = self._server()
        tool = next(t for t in srv.TOOLS if t["name"] == "ad_patterns")
        self.assertIn("NOT performance", tool["description"])
        with self.assertRaises(ValueError):
            srv.call("ad_patterns", {})
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        json.dump({"decision": {"decision": "iterate"}}, open(os.path.join(d, "summary.json"), "w"))
        market_cli.ad_patterns(None, lambda m: None, ads_path=SAMPLE, run_dir=d, engine="supplied", now="2026-10-27")
        res = srv.results(d)
        self.assertEqual(res["ad_patterns"]["engine"], "supplied")
        self.assertEqual(res["ad_patterns"]["findings"][0]["kind"], "real_longevity")
        self.assertIn("not performance", res["ad_patterns"]["note"])


class AdPatternsDashboard(unittest.TestCase):
    def _payload(self):
        ap = market_cli.load_service("ad_patterns")
        ads = ap.normalize_ads(json.load(open(SAMPLE, encoding="utf-8"))["ads"])
        sim = ap.creatives_from_feed_test(FEED)
        sim[0]["labels"] = {d: {"value": "unknown"} for d in ap.DIMENSIONS}
        sim[0]["labels"]["format"] = {"value": "talking_head"}
        sim[0]["status"] = "labelled"
        return ap.analyse(ads + sim, "supplied", {"brand": "Demo"})

    def test_section_marks_real_and_simulated(self):
        anchor, label, html = report_view.ad_patterns_section(self._payload(), insight="Real ads: x")
        self.assertEqual((anchor, label), ("adpatterns", "Ad patterns"))
        self.assertIn("Real ads · longevity", html)
        self.assertIn(">Simulated</span>", html)
        self.assertIn("Your creatives (simulated CTR)", html)
        self.assertIn("mine · 1.8%", html)
        self.assertIn("is not proven profitable", html)
        self.assertIn("ad-pattern-lab", html)
        self.assertIsNone(report_view.ad_patterns_section(None))
        self.assertIsNone(report_view.ad_patterns_section({"findings": []}))

    def test_exporter_wires_section_insight_and_download(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        src = os.path.join(HERE, "fixtures", "sample_run")
        for f in os.listdir(src):
            shutil.copy(os.path.join(src, f), d)
        json.dump(self._payload(), open(os.path.join(d, "ad_patterns.json"), "w"))
        paths = exporter.export_run_dir(d, os.path.join(d, "dash.html"))
        html = open(paths["html"], encoding="utf-8").read()
        sec = re.search(r'<section id="adpatterns">(.*?)</section>', html, re.S).group(1)
        self.assertIn("Real ads: Talking head format has the highest 60+ day share (observational, not performance).", sec)
        self.assertIn('data-dl="ad_patterns.md"', html)
        self.assertTrue(os.path.exists(paths["download:ad_patterns.md"]))


if __name__ == "__main__":
    unittest.main()
