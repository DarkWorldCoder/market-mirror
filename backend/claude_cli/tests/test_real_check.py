"""The real-people check kit: questions from what decided the run, who and how many to ask, the answers sheet that
calibrate reads, and the dashboard downloads."""

import csv
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import real_check  # noqa: E402
import report_view  # noqa: E402

MK = {"has_survey": True, "offer": "the Pro plan at $9/month", "goal": "Start a free trial",
      "overall": {"convert_yes": 30.0},
      "messages_ranked": [{"key": "#1", "label": "Save 3 hours a week", "share": 55.0},
                          {"key": "#2", "label": "Built for busy teams", "share": 45.0}],
      "objections": [{"type": "price", "label": "Price", "share": 40.0}],
      "pricing": {"optimal": 9}, "currency": "USD",
      "by_segment": [{"key": "Freelancers", "n": 20}, {"key": "Agencies", "n": 15}, {"key": "Unassigned", "n": 2}],
      "by_country": [{"key": "India", "n": 20}, {"key": "Unknown", "n": 2}]}
FEED = {"creatives": [{"id": "a", "headline": "Stop losing Fridays"}, {"id": "b", "headline": "One inbox"}, {"id": "c"}],
        "summary": {"per_creative": {"a": {"ctr": 2.0, "expected_ctr": 1.1}, "b": {"ctr": 1.0, "expected_ctr": 1.8},
                                     "c": {"ctr": 0.2}}}}


class RealCheckTest(unittest.TestCase):
    def test_people_needed(self):
        self.assertEqual(real_check.people_needed(50), 97)
        self.assertEqual(real_check.people_needed(None), 97)
        self.assertEqual(real_check.people_needed(2), 30)            # floors at 5% and at 30 people
        self.assertEqual(real_check.people_needed(30), 81)

    def test_questions_follow_the_run(self):
        kit = real_check.build({"feed_test": FEED}, MK)
        cols = [q["column"] for q in kit["questions"]]
        self.assertEqual(cols, ["y", "q_message", "q_price", "q_ad", "q_objection"])
        q = {x["column"]: x for x in kit["questions"]}
        self.assertIn("start a free trial for the Pro plan", q["y"]["question"])
        self.assertIn("30.0% of simulated people", q["y"]["simulated"])
        self.assertIn("USD 9", q["q_price"]["question"])
        self.assertIn('A: "One inbox"', q["q_ad"]["question"])     # ranked by expected click rate
        self.assertIn("Price (40.0%)", q["q_objection"]["simulated"])
        self.assertEqual(kit["audience"], {"segments": ["Freelancers", "Agencies"], "countries": ["India"]})
        self.assertEqual(kit["people_needed"], 81)
        md = kit["markdown"]
        self.assertIn("About **81 people**", md)
        self.assertIn("in each of the 2", md)
        self.assertIn("calibrate --run-dir", md)
        header = next(csv.reader(io.StringIO(kit["csv"])))
        self.assertEqual(header[:6], ["respondent", "segment", "country", "gender", "age", "y"])   # what calibrate reads

    def test_calibration_plan_wins_and_empty_runs_get_nothing(self):
        kit = real_check.build({"calibration": {"ppi": {"plan": {"more_with_panel": 140}}}}, MK)
        self.assertEqual(kit["people_needed"], 140)
        self.assertIn("earlier calibration", kit["markdown"])
        self.assertIsNone(real_check.build({}, {}))
        only_feed = real_check.build({"feed_test": FEED}, {})
        self.assertEqual([q["column"] for q in only_feed["questions"]], ["q_ad", "q_objection"])

    def test_gabor_granger_price_is_preferred(self):
        kit = real_check.build({"choice_gabor_granger": {"revenue_max_price": 12}}, MK)
        self.assertIn("at 12?", next(q for q in kit["questions"] if q["column"] == "q_price")["question"])

    def test_download_labels(self):
        bar = report_view.download_bar({"real_check.md": "# x", "real_check.csv": "a,b\n"})
        self.assertIn("Check with real people", bar)
        self.assertIn("Real answers sheet", bar)


if __name__ == "__main__":
    unittest.main()
