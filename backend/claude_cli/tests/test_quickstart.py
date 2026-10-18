"""Quickstart wizard (no backend), pitch and ideas dashboard sections, CLI offline path."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CLI_DIR = os.path.dirname(HERE)
sys.path.insert(0, CLI_DIR)

import exporter  # noqa: E402
import quickstart  # noqa: E402
import report_view  # noqa: E402

ANSWERS = {"brand": "Fitloop", "product": "A 15-minute home workout app for 4.99 USD per month.",
           "buyers": "young professionals in India; parents in Kenya", "platforms": "Instagram, Twitter, nope",
           "tests": "ads, price, launch, pitch", "budget": "1,200 EUR", "size": "large"}


class JsonListTests(unittest.TestCase):
    def test_load_json_list_reads_files_and_wrappers(self):
        import mirofish
        d = tempfile.mkdtemp()
        f = os.path.join(d, "posts.json")
        json.dump({"posts": [{"agent": "Brand", "text": "hello"}]}, open(f, "w"))
        rows = mirofish.load_json_list("@" + f, "posts")
        self.assertEqual(rows[0]["content"], "hello")
        self.assertEqual(mirofish.load_json_list('[{"agent": 1, "content": "x"}]', "events")[0]["agent"], 1)
        with self.assertRaises(mirofish.CLIError):
            mirofish.load_json_list('[{"agent": 1}]', "events")


class QuickstartTests(unittest.TestCase):
    def test_build_scenario_writes_everything(self):
        d = tempfile.mkdtemp()
        r = quickstart.build_scenario(ANSWERS, os.path.join(d, "fit"))
        self.assertEqual(r["people"], 150)
        self.assertEqual(r["platforms"], ["instagram", "x"])
        for f in ("brief.md", "question.txt", "personas.json", "creatives.json", "messages.txt", "posts.json", "events.json",
                  "pitch.md", "rebuttals.md", "market_test.json"):
            self.assertIn(f, r["files"])
        cfg = json.load(open(r["config"], encoding="utf-8"))
        self.assertEqual(cfg["rounds"], 6)                                   # launch calendar needs rounds
        self.assertEqual(cfg["survey"]["pricing"], "EUR")
        self.assertNotIn("messages", cfg["survey"])                          # messages test not asked for
        self.assertEqual(cfg["pitch"]["script"], "pitch.md")
        self.assertFalse(cfg["approve_spend"])                               # stops before paid rounds
        cr = json.load(open(os.path.join(d, "fit", "creatives.json"), encoding="utf-8"))
        self.assertEqual(len(cr["creatives"]), 4)                            # two per platform
        self.assertEqual(cr["currency"], "EUR")
        ev = json.load(open(os.path.join(d, "fit", "events.json"), encoding="utf-8"))
        self.assertEqual([e["round"] for e in ev], [1, 3, 5, 7])
        self.assertIn("4.99", open(os.path.join(d, "fit", "events.json"), encoding="utf-8").read())
        self.assertIn("## price", open(os.path.join(d, "fit", "rebuttals.md"), encoding="utf-8").read())

    def test_required_answers(self):
        with self.assertRaises(ValueError):
            quickstart.build_scenario({"brand": "X"}, tempfile.mkdtemp())

    def test_past_ads_import_is_called(self):
        d = tempfile.mkdtemp()
        ads = os.path.join(d, "ads.csv")
        open(ads, "w").write("Ad name,Impressions,Link clicks,Amount spent\nA,1000,50,10\n")
        calls = []

        def fake_import(path, md, js, title):
            calls.append(path)
            open(md, "w").write("# ads")
            json.dump({"benchmarks": {"default": {"ctr": 5.0}}}, open(js, "w"))
            return {"benchmarks": {"default": {"ctr": 5.0}}}

        r = quickstart.build_scenario({**ANSWERS, "past_ads": ads, "tests": "ads"}, os.path.join(d, "s"), ads_import=fake_import)
        self.assertEqual(calls, [ads])
        cfg = json.load(open(r["config"]))
        self.assertIn("past_ads.md", cfg["seeds"])
        cr = json.load(open(os.path.join(d, "s", "creatives.json")))
        self.assertEqual(cr["benchmarks"]["default"]["ctr"], 5.0)

    def test_key_configured_never_reads_value_into_result(self):
        d = tempfile.mkdtemp()
        open(os.path.join(d, ".env"), "w").write("LLM_API_KEY=your_api_key_here\n")
        env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "LLM_API_KEY")}
        old = dict(os.environ)
        os.environ.clear()
        os.environ.update(env)
        try:
            self.assertFalse(quickstart.key_configured(d))
            open(os.path.join(d, ".env"), "w").write("LLM_API_KEY=abc\n")
            self.assertTrue(quickstart.key_configured(d))
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_cli_no_run_is_offline(self):
        d = tempfile.mkdtemp()
        ans = os.path.join(d, "a.json")
        json.dump(ANSWERS, open(ans, "w"))
        proc = subprocess.run([sys.executable, os.path.join(CLI_DIR, "mirofish.py"), "--base-url", "http://127.0.0.1:9",
                               "quickstart", "--answers", "@" + ans, "--out", os.path.join(d, "out"), "--no-run"],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertTrue(out["next"].endswith("market_test.json"))
        self.assertTrue(os.path.exists(os.path.join(d, "out", "market_test.json")))


PITCH = {"answered": 3, "people_pitched": 3, "pitch_score": 83, "channel": "call", "rebuttals_given": 2,
         "verdict_before": {"yes": 33.3, "maybe": 33.3, "no": 33.3}, "verdict_after": {"yes": 66.7, "maybe": 33.3, "no": 0},
         "objections": [{"type": "price", "count": 1, "share": 33.3, "examples": [{"text": "Too pricey"}], "questions": ["Student plan?"],
                         "rebuttal": "Cheap.", "rebuttal_success": 100.0, "moved_yes": 1, "moved_partly": 0, "moved_no": 0},
                        {"type": "none", "count": 1, "share": 33.3, "examples": [], "questions": [], "rebuttal": None, "rebuttal_success": None}],
         "by_segment": [{"segment": "Kenya students", "n": 1, "yes": 100, "maybe": 0, "no": 0, "lead_score": 88, "top_objection": "none"}],
         "hot_leads": [{"name": "Amani", "segment": "Kenya students", "lead_score": 88, "verdict": "yes", "reach": "WhatsApp", "next_step": "a trial"}],
         "fixes": ["Write a better answer for 'trust' objections"], "best_replies": [{"name": "Amani", "segment": "K", "text": "<b>in</b>"}],
         "worst_replies": [], "script": "Hi <there>", "people": [{"agent_id": 3, "lead_score": 88}]}
IDEAS = {"ideas": [{"title": "Proof <ad>", "type": "ad", "priority": "high", "hypothesis": "If proof then trust", "evidence": ["S1 text"],
                    "audience": "PH parents", "platform": "facebook", "what_to_make": "video", "budget": "100 USD", "duration": "5 days",
                    "metric": "CPL", "success_looks_like": "under 10", "how_to_test": {"tool": "feedtest", "config": {"creatives": []}}}],
         "evidence": {"signals": [{"id": "S1", "source": "ads", "text": "S1 text"}], "sources": ["ads"]}, "markdown": "# ideas"}


class SectionTests(unittest.TestCase):
    def test_pitch_section(self):
        a, label, html = report_view.pitch_section(PITCH)
        self.assertEqual((a, label), ("pitch", "Sales rehearsal"))
        for frag in ("83/100", "Cheap.", "100.0%", "Student plan?", "Amani", "WhatsApp", "Hi &lt;there&gt;", "&lt;b&gt;in&lt;/b&gt;",
                     "Write a better answer"):
            self.assertIn(frag, html)
        self.assertNotIn("<b>in</b>", html)
        self.assertIsNone(report_view.pitch_section({}))

    def test_ideas_section(self):
        a, label, html = report_view.ideas_section(IDEAS)
        self.assertEqual((a, label), ("ideas", "Test ideas"))
        self.assertIn("Proof &lt;ad&gt;", html)
        self.assertIn("S1 text", html)
        self.assertIn("feedtest", html)
        self.assertIsNone(report_view.ideas_section({"ideas": []}))

    def test_exporter_wires_pitch_and_ideas(self):
        d = tempfile.mkdtemp()
        src = os.path.join(HERE, "fixtures", "sample_run")
        for f in os.listdir(src):
            with open(os.path.join(src, f), "rb") as i, open(os.path.join(d, f), "wb") as o:
                o.write(i.read())
        json.dump(PITCH, open(os.path.join(d, "pitch.json"), "w"))
        json.dump(IDEAS, open(os.path.join(d, "ideas.json"), "w"))
        paths = exporter.export_run_dir(d, os.path.join(d, "dash.html"))
        html = open(paths["html"], encoding="utf-8").read()
        self.assertIn('<section id="pitch"', html)
        self.assertIn('<section id="ideas"', html)
        self.assertLess(html.index('<section id="pitch"'), html.index('<section id="feedtest"') if '<section id="feedtest"' in html else len(html))
        self.assertIn('data-dl="pitch.json"', html)
        self.assertIn('data-dl="ideas.md"', html)
        self.assertTrue(os.path.exists(paths["download:pitch.json"]))


if __name__ == "__main__":
    unittest.main()
