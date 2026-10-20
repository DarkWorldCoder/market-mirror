"""Provider comparison: agreement checks and the page."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import compare  # noqa: E402


def run(folder, yes, n, decision, objection, message, countries):
    os.makedirs(folder, exist_ok=True)
    m = {"people": n, "answered": n, "overall": {"n": n, "convert_yes": yes, "convert_maybe": 50, "convert_no": 50 - yes, "click_yes": 5,
                                                 "ssr": {"purchase": {"mean": 3.1, "sd": 1.1}}},
         "objections": [{"label": objection, "share": 60}], "messages_ranked": [{"label": message}],
         "by_segment": [{"key": "A", "n": 50, "convert_yes": yes}], "by_country": [{"key": c, "n": 40, "convert_yes": v} for c, v in countries],
         "pricing": {"acceptable_low": 2, "acceptable_high": 8, "optimal": 3}}
    with open(os.path.join(folder, "summary.json"), "w") as f:
        json.dump({"marketing": m, "decision": {"decision": decision}}, f)
    return folder


class CompareTests(unittest.TestCase):
    def test_agreement_and_page(self):
        d = tempfile.mkdtemp()
        a = run(os.path.join(d, "a"), 2.0, 1000, "iterate", "Trust", "#2", [("Kenya", 3), ("India", 1)])
        b = run(os.path.join(d, "b"), 2.5, 1000, "iterate", "Trust", "#3", [("Kenya", 4), ("India", 2)])
        c = run(os.path.join(d, "c"), 15.0, 1000, "go", "Price", "#2", [("India", 9), ("Kenya", 1)])
        comp = compare.build([("Claude", a), ("Codex", b), ("Gemini", c)])
        ag = comp["agreement"]
        self.assertFalse(ag["decision"]["agree"])
        self.assertFalse(ag["would_convert_ranges_overlap"]["agree"])
        self.assertTrue(compare.build([("Claude", a), ("Codex", b)])["agreement"]["would_convert_ranges_overlap"]["agree"])
        out = compare.write([("Claude", a), ("Codex", b)], os.path.join(d, "out"))
        page = open(out["html"]).read()
        self.assertIn("Claude", page) and self.assertIn("checks agree", page)


if __name__ == "__main__":
    unittest.main()
