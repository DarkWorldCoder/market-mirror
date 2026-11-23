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


    def test_scalar_messages_wrapped_creatives_and_the_brief_file_text_are_read(self):
        r = fit_check.check({"survey": {"messages": "Try therapy today"}}, US)
        self.assertEqual([w["code"] for w in r["warnings"]], ["sensitive_topic"])
        r = fit_check.check({"creatives": {"creatives": [{"text": "The world's first sleep ring"}]}}, US)
        self.assertEqual([w["code"] for w in r["warnings"]], ["new_category"])
        r = fit_check.check({"requirement": "@question.md"}, US, brief_text="A reminder app for people with diabetes")
        self.assertEqual([w["code"] for w in r["warnings"]], ["sensitive_topic"])

    def test_unread_people_are_not_a_pass(self):
        r = fit_check.check({}, [], audience_available=False)
        self.assertEqual((r["fit"], r["audience_checked"]), ("unknown", False))
        self.assertEqual([w["code"] for w in r["warnings"]], ["audience_unavailable"])
        self.assertIn("could not be read", fit_check.lines(r)[0])
        r = fit_check.check({"targets": {"ctr": 2}}, [], audience_available=False)
        self.assertEqual(r["fit"], "caution")


class BriefTextTests(unittest.TestCase):
    def test_reads_the_requirement_file(self):
        import tempfile
        import mirofish
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "q.md"), "w", encoding="utf-8") as f:
                f.write("How will people with diabetes react?")
            self.assertIn("diabetes", mirofish._brief_text({"requirement": "q.md"}, d))
            self.assertIn("diabetes", mirofish._brief_text({"requirement": "@q.md"}, d))
            self.assertEqual(mirofish._brief_text({"requirement": "Plain question?"}, d), "Plain question?")


if __name__ == "__main__":
    unittest.main()
