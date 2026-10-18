"""Realism upgrades: free-text survey answers mapped by SSR (mocked backend) and multi-seed feed tests."""

import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import exporter  # noqa: E402
import feed_view  # noqa: E402
import market_cli  # noqa: E402
import marketing as mk  # noqa: E402
import mirofish  # noqa: E402
from test_marketing import FIXTURE, make_survey_bundle  # noqa: E402

PMF = {"yes": [0.02, 0.05, 0.13, 0.35, 0.45], "maybe": [0.1, 0.2, 0.4, 0.2, 0.1], "no": [0.5, 0.3, 0.12, 0.05, 0.03]}


def ssr_result(pmf):
    mean = sum((k + 1) * x for k, x in enumerate(pmf))
    sd = sum(((k + 1) - mean) ** 2 * x for k, x in enumerate(pmf)) ** 0.5
    return {"pmf": pmf, "mean": round(mean, 3), "sd": round(sd, 3), "score10": round((mean - 1) * 2.5, 2)}


def with_ssr(bundle):
    """Attach SSR distributions that follow each stated answer, as the backend would."""
    for r in bundle["survey"]["responses"]:
        a = r["answer"]
        a["texts"] = {"purchase": f"stated {a['would_convert']}", "interest": "ok", "trust": "fine", "recommend": "maybe"}
        a["ssr"] = {sc: ssr_result(PMF[a["would_convert"]]) for sc in mk.SSR_SCALES}
    bundle["survey"]["ssr"] = {"used": True, "model": "fake-model", "mapped": len(bundle["survey"]["responses"])}
    return bundle


class StubClient:
    """Answers the endpoints step_survey calls; the SSR endpoint stands in for the embedding model."""

    def __init__(self, ssr_down=False):
        self.ssr_down = ssr_down
        self.ssr_items = []

    def data(self, method, path, json=None, params=None, timeout=None):
        if path.endswith("/config"):
            return {"persona_index": [{"agent_id": i, "name": f"P{i}", "kind": "persona", "segment": "S" + str(i % 2)}
                                      for i in range(4)]}
        if path.endswith("/profiles"):
            return {"profiles": []}
        if path == "/api/simulation/interview/batch":
            out = []
            for it in json["interviews"]:
                assert "purchase_text" in it["prompt"]
                yes = it["agent_id"] % 2 == 0
                reply = {"purchase_text": "Yes, I'd definitely sign up." if yes else "No, not for me.",
                         "interest_text": "Looks useful." if yes else "Not interested.", "trust_text": "",
                         "interest": 9, "trust": 8, "would_click": "yes", "would_convert": "yes", "recommend": 9,
                         "objection_type": "none"}
                out.append({"agent_id": it["agent_id"], "response": "Sure: " + mirofish.json.dumps(reply)})
            return {"result": {"results": out}}
        if path == "/api/simulation/ssr":
            if self.ssr_down:
                raise mirofish.CLIError("POST /api/simulation/ssr: 503 embedding model unavailable")
            self.ssr_items += json["items"]
            res = [{"id": it["id"], "scale": it["scale"],
                    **ssr_result(PMF["yes"] if it["text"].startswith(("Yes", "Looks")) else PMF["no"])}
                   for it in json["items"]]
            return {"model": "fake-model", "anchors_version": "t", "temperature": 1.0, "results": res}
        return {}


class SurveyTextTest(unittest.TestCase):
    def test_prompt_asks_free_text_before_numbers(self):
        p = mk.survey_prompt("Free mock test", "sign up", ["a", "b"], 0)
        for f in ("interest_text", "trust_text", "purchase_text", "recommend_text"):
            self.assertIn(f, p)
        self.assertLess(p.index("purchase_text"), p.index('"interest": 0-10'))
        self.assertIn("would you actually sign up", p)

    def test_parse_answer_keeps_texts_and_accepts_text_only(self):
        a = mk.parse_answer('{"purchase_text": " Probably not. ", "interest_text": "", "interest": 6, "would_convert": "no"}')
        self.assertEqual(a["texts"], {"purchase": "Probably not."})
        b = mk.parse_answer('{"purchase_text": "Yes for sure", "trust_text": "Seems legit"}')
        self.assertIsNotNone(b)
        self.assertEqual(set(b["texts"]), {"purchase", "trust"})
        self.assertIsNone(mk.parse_answer('{"quote": "hi"}'))

    def test_ssr_items_and_attach_roundtrip(self):
        responses = [{"answer": {"texts": {"purchase": "yes", "trust": "ok"}}}, {"answer": None},
                     {"answer": {"texts": {"interest": "meh"}}}]
        items = mk.ssr_items(responses)
        self.assertEqual([i["id"] for i in items], ["0:purchase", "0:trust", "2:interest"])
        n = mk.attach_ssr(responses, [{"id": "0:purchase", **ssr_result(PMF["yes"])}, {"id": "9:purchase", "pmf": [1]},
                                      {"id": "bad"}, {"id": "2:interest", **ssr_result(PMF["no"])}])
        self.assertEqual(n, 2)
        self.assertAlmostEqual(responses[0]["answer"]["ssr"]["purchase"]["mean"], ssr_result(PMF["yes"])["mean"])

    def test_step_survey_maps_free_text_via_backend(self):
        d = tempfile.mkdtemp()
        try:
            c = StubClient()
            res = mirofish.step_survey(c, "sim_x", d, "offer", "sign up", [], batch=2)
            self.assertEqual(res["ssr_rated"], 4)
            survey = json.load(open(os.path.join(d, "survey.json")))
            self.assertTrue(survey["ssr"]["used"])
            self.assertEqual(survey["ssr"]["model"], "fake-model")
            self.assertEqual({i["scale"] for i in c.ssr_items}, {"purchase", "interest"})   # empty trust_text skipped
            a0, a1 = survey["responses"][0]["answer"], survey["responses"][1]["answer"]
            self.assertGreater(a0["ssr"]["purchase"]["mean"], a1["ssr"]["purchase"]["mean"])
            self.assertEqual(a1["would_convert"], "yes")                    # stated number kept as the fallback
            a = mk.analyze({"config": {"persona_index": c.data("GET", "/config")["persona_index"]}, "survey": survey})
            self.assertLess(a["overall"]["convert_yes"], 100)               # SSR, not the over-positive stated "yes"
            self.assertEqual(a["overall"]["stated_convert_yes"], 100)

            down = mirofish.step_survey(StubClient(ssr_down=True), "sim_x", d, "offer", "sign up", [])
            self.assertEqual(down["ssr_rated"], 0)
            survey = json.load(open(os.path.join(d, "survey.json")))
            self.assertFalse(survey["ssr"]["used"])
            self.assertIn("503", survey["ssr"]["reason"])
            self.assertTrue(all("ssr" not in r["answer"] for r in survey["responses"]))
        finally:
            shutil.rmtree(d)


class SSRAnalysisTest(unittest.TestCase):
    def test_segments_report_mean_and_spread(self):
        b = with_ssr(make_survey_bundle())
        a = mk.analyze(b)
        o = a["overall"]
        self.assertEqual(set(o["ssr"]), set(mk.SSR_SCALES))
        pi = o["ssr"]["purchase"]
        self.assertEqual(pi["n"], a["answered"])
        self.assertTrue(1 <= pi["mean"] <= 5 and pi["sd"] > 0)
        self.assertAlmostEqual(pi["top2"], o["convert_yes"], places=0)
        self.assertIsNone(o["nps"])                                          # word of mouth = recommend mean instead
        segs = {s["key"]: s for s in a["by_segment"]}
        # Bangladesh students mostly said yes in the fixture, Nepal parents mostly no
        self.assertGreater(segs["Bangladesh students"]["ssr"]["purchase"]["mean"],
                           segs["Nepal parents"]["ssr"]["purchase"]["mean"])
        self.assertEqual(a["by_segment"][0]["key"], "Bangladesh students")
        self.assertTrue(any("free-text" in v for v in a["verdicts"]))
        self.assertTrue(all("intent" in p for p in a["playbook"]))
        sb = mk.summary_block(a)
        self.assertTrue(sb["ssr"]["used"])

    def test_without_ssr_numbers_are_unchanged(self):
        a = mk.analyze(make_survey_bundle())
        self.assertEqual(a["overall"]["ssr"], {})
        self.assertIsNone(a["ssr"])
        self.assertEqual(a["overall"]["convert_yes"], a["overall"]["stated_convert_yes"])
        self.assertIsNotNone(a["overall"]["nps"])

    def test_dashboard_and_decision_use_ssr(self):
        b = with_ssr(make_survey_bundle())
        a = mk.analyze(b)
        secs = dict((k, h) for k, _, h in mk.render_sections(a))
        self.assertIn("ratings", secs)
        self.assertIn('data-kind="likert"', secs["ratings"])
        self.assertIn("arXiv 2510.08338", secs["ratings"])
        self.assertIn("Intent 1-5", secs["audiences"])
        self.assertRegex(secs["audiences"], r"\d\.\d ±\d\.\d")
        d = feed_view.decision(b, a)
        survey_sig = next(s for s in d["signals"] if s["name"] == "Buyer survey")
        self.assertIn("purchase intent", survey_sig["detail"])
        files = feed_view.export_files(b, a, "")
        self.assertIn("purchase_mean,purchase_sd", files["segments.csv"].splitlines()[0])
        self.assertIn("purchase_text,purchase_ssr_mean", files["survey_answers.csv"].splitlines()[0])

    def test_offline_export_with_ssr(self):
        d = tempfile.mkdtemp()
        try:
            for name in os.listdir(FIXTURE):
                shutil.copy(os.path.join(FIXTURE, name), d)
            b = with_ssr(make_survey_bundle())
            json.dump(b["survey"], open(os.path.join(d, "survey.json"), "w"))
            cfg_path = os.path.join(d, "config.json")
            cfg = json.load(open(cfg_path))
            cfg.get("data", cfg)["persona_index"] = b["config"]["persona_index"]
            json.dump(cfg, open(cfg_path, "w"))
            page = open(exporter.export_run_dir(d)["html"], encoding="utf-8").read()
            self.assertIn('id="ratings"', page)
            self.assertEqual(page.count("</script>"), page.count("<script"))
        finally:
            shutil.rmtree(d)


def multi_seed_feed(min_ctr=2.0, max_ctr=4.5, agreement=67):
    sp = {"expected_ctr": {"mean": 3.2, "min": min_ctr, "max": max_ctr, "sd": 1.0, "values": [min_ctr, 3.2, max_ctr]},
          "thumb_stop": {"mean": 20.0, "min": 15.0, "max": 25.0, "sd": 5.0, "values": [15.0, 20.0, 25.0]},
          "engagement_rate": {"mean": 8.0, "min": 6.0, "max": 10.0, "sd": 2.0, "values": [6.0, 8.0, 10.0]}}
    return {"creatives": [{"id": "a", "platform": "facebook", "text": "x"}, {"id": "b", "platform": "facebook", "text": "y"}],
            "personas_tested": 20, "feeds": 120, "waves": 2,
            "summary": {"ranked": ["a", "b"], "calibration": {}, "organic_baseline": {},
                        "per_creative": {cid: {"impressions": 60, "expected_ctr": 3.2, "ctr": 3.3, "thumb_stop": 20.0,
                                               "engagement_rate": 8.0, "hide_rate": 5.0, "noticed": 40.0}
                                         for cid in ("a", "b")}},
            "multi_seed": {"n": 3, "seeds": [5, 7924, 15843], "spread": {"a": sp, "b": sp},
                           "winner_counts": {"a": 2, "b": 1}, "winner_agreement": agreement,
                           "usage": {"calls": 300, "input_tokens": 450000, "output_tokens": 60000},
                           "per_seed": [{"seed": s, "usage": {"calls": 100, "input_tokens": 150000, "output_tokens": 20000}}
                                        for s in (5, 7924, 15843)]},
            "usage": {"calls": 300, "input_tokens": 450000, "output_tokens": 60000}}


class MultiSeedViewTest(unittest.TestCase):
    def test_feed_section_shows_ranges_and_cost(self):
        _, _, html = feed_view.feed_section(multi_seed_feed(), mk.chart)
        self.assertIn("Across 3 seeds", html)
        self.assertIn("3.2% (2.0–4.5)", html)
        self.assertIn("2.0–4.5% across 3 seeds", html)
        self.assertIn("300 Claude calls", html)
        self.assertIn("2 of 3", html)
        self.assertIn("winner changes between seeds", html)
        self.assertIn("Shown to 20 simulated people", html)          # per seed, not pooled impressions
        single = multi_seed_feed()
        single.pop("multi_seed")
        self.assertIn("--seeds 3", feed_view.feed_section(single, mk.chart)[2])

    def test_decision_needs_a_robust_range(self):
        ft = multi_seed_feed(min_ctr=2.0, max_ctr=4.5)
        sig = next(s for s in feed_view.decision({"feed_test": ft}, {})["signals"] if s["name"] == "Feed test")
        self.assertEqual(sig["vote"], "iterate")                     # mean 3.2 would be "go", but one seed fell to 2.0
        self.assertIn("range 2.0–4.5% across 3 seeds", sig["detail"])
        self.assertEqual(sig["n"], 20)
        ft = multi_seed_feed(min_ctr=3.1, max_ctr=3.4, agreement=100)
        sig = next(s for s in feed_view.decision({"feed_test": ft}, {})["signals"] if s["name"] == "Feed test")
        self.assertEqual(sig["vote"], "go")

    def test_feedtest_cli_sends_seeds_and_logs_cost(self):
        result = multi_seed_feed()

        class C:
            payload = None

            def data(self, method, path, json=None, timeout=None):
                if path == "/api/simulation/feed-test":
                    C.payload = json
                    return {"task_id": "t", "feeds": 40, "personas": 20, "creatives": 2, "seeds": 3}
                if path == "/api/simulation/market-task/status":
                    return {"status": "completed", "progress": 100}
                return result
        lines = []
        d = tempfile.mkdtemp()
        try:
            out = market_cli.feedtest(C(), "sim_x", json.dumps([{"platform": "facebook", "text": "x"}]), d, lines.append,
                                      seeds=3)
        finally:
            shutil.rmtree(d)
        self.assertEqual(C.payload["seeds"], 3)
        self.assertEqual(out["seeds"], [5, 7924, 15843])
        self.assertEqual(out["ranges"]["a"]["expected_ctr"], [2.0, 4.5])
        log = "\n".join(lines)
        self.assertIn("3 seeds", log)
        self.assertEqual(log.count("100 Claude calls"), 3)
        self.assertIn("total cost 300 Claude calls, 450,000 input / 60,000 output tokens", log)
        self.assertIn("a ranked first in 67% of 3 seeds", log)


if __name__ == "__main__":
    unittest.main()
