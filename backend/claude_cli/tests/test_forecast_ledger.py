"""Pre-registered forecasts: lock once, hash check, scoring hits and misses, the published table, the CLI."""

import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import forecast_ledger as fl  # noqa: E402
import mirofish  # noqa: E402

BUNDLE = {
    "summary": {"simulation_id": "sim_x", "decision": {"decision": "iterate"},
                "marketing": {"overall": {"expected_convert_yes": 18.0, "convert_yes": 10.0},
                              "by_segment": [{"key": "Nurses", "expected_convert_yes": 25.0},
                                             {"key": "Students", "expected_convert_yes": 12.0},
                                             {"key": "Retirees", "expected_convert_yes": 15.0}],
                              "messages_ranked": [{"key": "#1", "convert_yes": 20.0}, {"key": "#2", "convert_yes": 30.0}]}},
    "feed_test": {"summary": {"ranked": ["ad_b", "ad_a"], "per_creative": {"ad_a": {"expected_ctr": 1.1}, "ad_b": {"expected_ctr": 2.2}}}},
    "run_manifest": {"provenance": {"engine": {"commit": "abc"}}},
}


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run = os.path.join(self.tmp.name, "run1")
        os.makedirs(self.run)
        self.ledger = os.path.join(self.tmp.name, "ledger.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def test_predictions_cover_what_the_run_measured(self):
        p = fl.predictions(BUNDLE)
        self.assertEqual(p["rate"], 18.0)
        self.assertEqual(p["segment_order"], ["Nurses", "Retirees", "Students"])
        self.assertEqual(p["message_order"], ["#2", "#1"])
        self.assertEqual(p["creative_order"], ["ad_b", "ad_a"])
        self.assertEqual(p["decision"], "iterate")
        self.assertEqual(fl.predictions({}), {})

    def test_lock_once_then_score_hits_and_misses(self):
        entry = fl.lock(BUNDLE, self.run, self.ledger, "launch test", "2026-12-15")
        self.assertEqual(len(entry["id"]), 12)
        with self.assertRaises(ValueError):
            fl.lock(BUNDLE, self.run, self.ledger)
        scored = fl.score(self.run, {"rate": 6.0, "segment_rates": {"Nurses": 9, "Students": 4, "Retirees": 5},
                                     "message_rates": {"#1": 3, "#2": 2}, "decision_held": True}, self.ledger, "Meta export")
        r = scored["result"]
        self.assertEqual(r["rate"]["error_points"], 12.0)
        self.assertEqual(r["rate"]["ratio"], 3.0)
        self.assertTrue(r["segment_order"]["top_hit"])
        self.assertEqual(r["segment_order"]["spearman"], 1.0)
        self.assertFalse(r["message_order"]["top_hit"])
        self.assertEqual((r["hits"], r["total"]), (2, 4))      # rate miss, segment hit, message miss, decision held
        md = fl.table(self.ledger)
        self.assertIn(entry["id"], md)
        self.assertIn("2 of 4", md)
        self.assertIn("1 of 1 forecasts scored", md)

    def test_a_changed_lock_cannot_be_scored(self):
        fl.lock(BUNDLE, self.run, self.ledger)
        path = os.path.join(self.run, "forecast_lock.json")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        data["prediction"]["rate"] = 6.0
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        with self.assertRaises(ValueError):
            fl.score(self.run, {"rate": 6.0}, self.ledger)

    def test_unscored_locks_show_as_pending(self):
        fl.lock(BUNDLE, self.run, self.ledger, outcome_due="2026-12-15")
        self.assertIn("not scored yet (due 2026-12-15)", fl.table(self.ledger))

    def test_cli_lock_and_table(self):
        with open(os.path.join(self.run, "summary.json"), "w", encoding="utf-8") as f:
            json.dump(BUNDLE["summary"], f)
        out = mirofish.main(["forecast", "lock", "--run-dir", self.run, "--ledger", self.ledger])
        self.assertEqual(out, 0)
        self.assertTrue(os.path.exists(os.path.join(self.run, "forecast_lock.json")))
        self.assertEqual(mirofish.main(["forecast", "table", "--ledger", self.ledger]), 0)
        self.assertTrue(os.path.exists(os.path.splitext(self.ledger)[0] + ".md"))
        self.assertEqual(mirofish.main(["forecast", "score", "--run-dir", self.run, "--ledger", self.ledger]), 1)


if __name__ == "__main__":
    unittest.main()
