"""Segment-gap shrinkage, the AI-use disclosure and the run provenance record."""

import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import disclosure  # noqa: E402
import marketing  # noqa: E402
import mirofish  # noqa: E402


class SegmentShrinkTests(unittest.TestCase):
    def test_gaps_shrink_toward_overall_and_close_calls_are_flagged(self):
        rows = [{"key": "Nurses", "n": 40, "convert_yes": 50.0}, {"key": "Students", "n": 40, "convert_yes": 30.0},
                {"key": "Retirees", "n": 40, "convert_yes": 25.0}]
        sh = marketing.segment_shrink(rows, 35.0)
        self.assertEqual([r["convert_yes_shrunk"] for r in rows], [41.0, 33.0, 31.0])
        self.assertEqual((sh["leader"], sh["raw_gap"], sh["shrunk_gap"], sh["close_call"]), ("Nurses", 20.0, 8.0, False))
        close = marketing.segment_shrink([{"key": "A", "n": 40, "convert_yes": 34.0},
                                          {"key": "B", "n": 40, "convert_yes": 30.0}], 32.0)
        self.assertTrue(close["close_call"])            # 4 points raw is 1.6 after shrinking
        thin = marketing.segment_shrink([{"key": "A", "n": 6, "convert_yes": 80.0},
                                         {"key": "B", "n": 40, "convert_yes": 20.0}], 30.0)
        self.assertTrue(thin["close_call"] and thin["thin_segments"] == ["A"] and "Fewer than 10" in thin["note"])
        tie = marketing.segment_shrink([{"key": "A", "n": 20, "convert_yes": 30.0},
                                        {"key": "B", "n": 20, "convert_yes": 30.0}], 30.0)
        self.assertIn("tied", tie["note"])
        self.assertIsNone(marketing.segment_shrink(rows[:1], 35.0))
        self.assertIsNone(marketing.segment_shrink(rows, None))


BUNDLE = {
    "run_manifest": {"started_at": "2026-11-23T10:00:00", "finished_at": "2026-11-23T10:20:00",
                     "emotions": {"mode": "observe"},
                     "provenance": {"models": [{"provider": "claude", "model": "claude-haiku-4-5"}],
                                    "engine": {"commit": "abcdef1234567890", "local_changes": True},
                                    "services_hash": "0123456789abcdef", "seeds": {"seed": 5},
                                    "spend_approved": True, "max_spend_usd": 5}},
    "config": {"persona_index": [{"agent_id": 0, "kind": "persona"},
                                 {"agent_id": 1, "kind": "persona", "model_provider": "grounded"},
                                 {"agent_id": 2, "kind": "community"}]},
    "calibration": {"n_real": 42},
}


class DisclosureTests(unittest.TestCase):
    def test_facts_come_from_saved_files(self):
        facts = dict(disclosure.facts(BUNDLE))
        self.assertIn("42 real answers", facts["Real people compared"])
        self.assertEqual(facts["Simulated people"], "2 invented people, 1 built from real customer records")
        self.assertIn("claude-haiku-4-5 (claude)", facts["Model and access"])
        self.assertIn("abcdef123456 with local changes", facts["Repeat this run"])
        self.assertIn("approved explicitly", facts["Human review"])
        self.assertEqual(facts["Dates"], "23 Nov 2026, 10:00 to 23 Nov 2026, 10:20")
        older = dict(disclosure.facts({"config": {"persona_index": [
            {"kind": "persona", "model_provider": "codex", "model_name": "gpt-5"},
            {"kind": "persona", "model_provider": "grounded"}]}}))
        self.assertEqual(older["Model and access"], "gpt-5 (codex) (read from the saved people; access method not recorded)")
        md = disclosure.markdown(BUNDLE)
        self.assertIn("not a poll or a survey of real people", md)
        self.assertIn("AAPOR", md)

    def test_missing_facts_say_so(self):
        facts = dict(disclosure.facts({"run_manifest": {}}))
        self.assertEqual(facts["Model and access"], "Not recorded for this run")
        self.assertTrue(facts["Real people compared"].startswith("None yet"))
        self.assertIsNone(disclosure.section({}, lambda *a: ""))
        sec = disclosure.section(BUNDLE, lambda title, intro=None: f"<h2>{title}</h2>")
        self.assertEqual(sec[0], "disclosure")
        self.assertIn("<dt>Who answered</dt>", sec[2])


class ProvenanceTests(unittest.TestCase):
    def test_records_models_engine_and_prompt_hash_without_failing(self):
        class Client:
            def data(self, method, path, **kw):
                return {"models": [{"provider": "claude", "model": "m"}], "engine": {"commit": "c1"}, "at": "now"}

        state = {}
        mirofish.record_provenance(Client(), state, {"seed": 3, "approve_spend": True, "max_spend_usd": 2})
        p = state["provenance"]
        self.assertEqual((p["models"][0]["model"], p["engine"]["commit"], p["seeds"], p["spend_approved"]),
                         ("m", "c1", {"seed": 3}, True))
        self.assertEqual(len(p["services_hash"]), 16)

        class Old:
            def data(self, *a, **kw):
                raise mirofish.CLIError("404")
        state = {}
        mirofish.record_provenance(Old(), state)
        self.assertEqual(state["provenance"]["models"], [])


if __name__ == "__main__":
    unittest.main()
