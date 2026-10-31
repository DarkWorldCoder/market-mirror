"""The 'How people felt' dashboard section and the feelings rows in each person's drawer (simulated, v2 state)."""

import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
FIXTURE = os.path.join(HERE, "fixtures", "sample_run")

import exporter  # noqa: E402
import report_view  # noqa: E402


def _state(i, emo="irritation", pleasant=-0.5):
    feel = {"emotion": emo, "pleasant": pleasant, "intensity": 0.4 if emo != "neutral" else 0.0, "words": "pushy again",
            "by": "self_report", "mismatch": False}
    return {"state": {"trust": 0.4, "familiarity": 0.2, "fatigue": 0.1, "mood": "a little annoyed",
                      "affect": {"v": pleasant * 0.4, "a": 0.3, "d": 0.1, "brand_v": -0.1, "t_h": 30,
                                 "last": {"emotion": emo, "intensity": 0.4, "words": "pushy again", "test": "feed_test"}}},
            "memory": [{"test": "feed_test", "kind": "stopped_on_ad", "text": "You stopped on the ad.", "feel": feel}],
            "trajectory": [{"valence": 0.0, "trust": 0.5}, {"valence": pleasant * 0.4, "trust": 0.4}]}


DOC = {"version": 2, "scopes": {"default": {str(i): _state(i, *(("neutral", 0.0) if i % 2 else ("irritation", -0.5)))
                                            for i in range(12)}}}


class EmotionViewTest(unittest.TestCase):
    def test_section_renders_from_v2_state_and_is_absent_without_data(self):
        feed = {"summary": {"per_creative": {"ad1": {"feelings": {"n": 6, "neutral_share": 0.5,
                                                                  "emotions": {"neutral": 0.5, "irritation": 0.5},
                                                                  "words": ["pushy again"]}}}}}
        pitch = {"resistance": {"resistance_pct": 12.0, "low_resistance_flag": True}}
        sec = report_view.emotion_section(DOC, feed, pitch, "Half the people felt irritated.")
        self.assertIsNotNone(sec)
        anchor, title, html = sec
        self.assertEqual(anchor, "feelings")
        for frag in ("How people felt", "Felt nothing much", "irritation", "1-9 scale", "not validated", "low for real buyers",
                     "pushy again", "not measured emotion"):
            self.assertIn(frag, html)
        self.assertIsNone(report_view.emotion_section({"scopes": {}}, {}, {}))
        self.assertIsNone(report_view.emotion_section(None))

    def test_drawer_shows_feelings(self):
        html = report_view._bde_inspector_drawer({"agent_id": 1}, _state(1))
        self.assertIn("Feels now", html)
        self.assertIn("Last feeling", html)
        self.assertIn("Feeling over time", html)
        self.assertIn("pushy again", html)
        old = {"state": {"trust": 0.5, "mood": "neutral"}, "memory": [{"test": "survey", "text": "said maybe"}], "trajectory": []}
        self.assertNotIn("Feels now", report_view._bde_inspector_drawer({"agent_id": 2}, old))   # v1 state still renders

    def test_dashboard_has_the_section_and_survives_bad_affect(self):
        bundle = exporter.load_run_dir(FIXTURE)
        bundle["behavior_state"] = json.loads(json.dumps(DOC))
        html, _, _ = exporter.render_dashboard(bundle)
        self.assertIn('<section id="feelings">', html)
        bundle["behavior_state"]["scopes"]["default"]["0"]["state"]["affect"] = "broken"
        html, _, _ = exporter.render_dashboard(bundle)
        self.assertIn("</html>", html)


if __name__ == "__main__":
    unittest.main()
