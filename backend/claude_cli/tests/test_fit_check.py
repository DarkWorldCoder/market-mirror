"""The when-not-to-use check: each weak spot, the fit level, and that a clean test passes quietly."""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import fit_check  # noqa: E402

US = [{"segment": "Parents" if i % 2 else "Students", "country": "United States"} for i in range(40)]


class FitCheckTests(unittest.TestCase):
    def test_clean_test_has_no_warnings(self):
        r = fit_check.check({"requirement": "Which of two headlines makes busy parents start a free trial?"}, US)
        self.assertEqual((r["fit"], r["warnings"]), ("good", []))
        self.assertEqual(fit_check.lines(r), ["fit check: no known weak spots for this test"])

    def test_each_weak_spot(self):
        people = [{"segment": "Nurses", "country": "Nepal"}] * 12 + [{"segment": "Farmers", "country": "NP"}] * 4 + \
                 [{"segment": "Teachers", "country": "GB"}] * 4
        cfg = {"requirement": "The world's first insulin reminder app for people with diabetes",
               "survey": {"messages": ["Vote for us"]}, "targets": {"ctr": 2}}
        r = fit_check.check(cfg, people)
        codes = [w["code"] for w in r["warnings"]]
        self.assertEqual(codes, ["small_segments", "less_covered_markets", "sensitive_topic", "new_category",
                                 "absolute_numbers"])
        self.assertEqual(r["fit"], "poor")
        self.assertIn("Farmers", r["warnings"][0]["text"])
        self.assertIn("80%", r["warnings"][1]["text"])            # GB counts as well covered
        self.assertIn("diabetes", r["warnings"][2]["text"])
        self.assertTrue(all(w["do_instead"] for w in r["warnings"]))

    def test_one_warning_is_caution_and_one_segment_is_not_small(self):
        r = fit_check.check({}, [{"segment": "Only", "country": "Kenya"}] * 3)
        self.assertEqual(r["fit"], "caution")
        self.assertEqual([w["code"] for w in r["warnings"]], ["less_covered_markets"])

    def test_words_inside_other_words_do_not_match(self):
        r = fit_check.check({"requirement": "A racing game with a votive candle theme and a gayety festival"}, US)
        self.assertEqual(r["warnings"], [])


if __name__ == "__main__":
    unittest.main()
