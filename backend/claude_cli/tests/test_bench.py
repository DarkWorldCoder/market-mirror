"""MarketMirror-Bench with fake models: the Upworthy loader (clear winners only), Twin-2K-500 items and the
retest ceiling, metrics, dry runs that spend nothing, and the CLI."""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import bench  # noqa: E402
import mirofish  # noqa: E402

CSV = os.path.join(HERE, "fixtures", "bench", "upworthy_mini.csv")
WINNERS = {"This Dad Did Something Simple", "Why Cats Purr"}


def fake(answer):
    calls = []

    def complete(system, user):
        calls.append((system, user))
        return answer(system, user), {"input_tokens": 100, "output_tokens": 10}
    complete.calls = calls
    return complete


def reader(system, user):
    if system == bench.GENERIC_SYSTEM:
        lines = [l for l in user.splitlines() if l[:1].isdigit()]
        return json.dumps({"scores": [90 if any(w in l for w in WINNERS) else 10 for l in lines]})
    lines = [l for l in user.splitlines() if l[:1].isdigit()]
    pick = next((i + 1 for i, l in enumerate(lines) if any(w in l for w in WINNERS)), 0)
    return json.dumps({"click": pick})


def twin_row(pid, buys):
    def block(answers):
        return json.dumps([
            {"BlockName": "Product Preferences - Pricing", "Questions": [
                {"QuestionID": f"Q{k}", "QuestionType": "MC", "QuestionText": f"Buy item {k} at $5?",
                 "Options": ["Yes, I would purchase the product", "No, I would not purchase the product"],
                 "Answers": {"SelectedByPosition": a}} for k, a in enumerate(answers)]},
            {"BlockName": "False consensus", "Questions": [
                {"QuestionID": "M1", "QuestionType": "Matrix", "QuestionText": "Support?", "Rows": ["Tax", "Leave"],
                 "Columns": ["Oppose", "Neutral", "Support"], "Answers": {"SelectedByPosition": [1, 3]}}]}])
    return {"pid": pid, "wave1_3_persona_text": f"Person {pid} is frugal." * 3,
            "wave4_Q_wave4_A": block(buys), "wave4_Q_wave1_3_A": block([buys[0], 2, 2])}


class Upworthy(unittest.TestCase):
    def test_loader_keeps_clear_winners_and_pools_images(self):
        tests = {t["id"]: t for t in bench.load_upworthy(CSV)}
        self.assertEqual(set(tests), {"t1", "t5"})            # t2 no clear winner, t3 too small, t4 one headline
        self.assertEqual(tests["t1"]["arms"][0]["headline"], "This Dad Did Something Simple")
        self.assertEqual(len(tests["t5"]["arms"]), 3)

    def test_dry_run_spends_nothing(self):
        res = bench.run_upworthy(CSV, 10, None, ["generic_reader"])
        self.assertTrue(res["dry_run"])
        self.assertEqual(res["estimate"]["calls"], 2)
        self.assertAlmostEqual(res["methods"]["chance"]["top_choice_accuracy"], round((1 / 2 + 1 / 3) / 2, 3))

    def test_methods_score_against_the_real_winner(self):
        c = fake(reader)
        people = [{"persona": "A busy dad"}, {"persona": "A cat lover"}]
        res = bench.run_upworthy(CSV, 10, c, ["generic_reader", "persona_panel"], people, approve_spend=True)
        g, p = res["methods"]["generic_reader"], res["methods"]["persona_panel"]
        self.assertEqual(g["top_choice_accuracy"], 1.0)
        self.assertEqual(p["top_choice_accuracy"], 1.0)
        self.assertEqual(g["calls"], 2)
        self.assertEqual(p["calls"], 4)
        self.assertGreater(g["spearman"], 0.5)

    def test_panel_without_people_is_skipped(self):
        res = bench.run_upworthy(CSV, 10, fake(reader), ["persona_panel"], [], approve_spend=True)
        self.assertIn("skipped", res["methods"]["persona_panel"])


class Twin(unittest.TestCase):
    def test_items_and_retest(self):
        items = bench.twin_items(twin_row(1, [1, 2, 2]))
        self.assertEqual([i["id"] for i in items], ["Q0", "Q1", "Q2"])
        self.assertEqual([i["retest"] for i in items], [1, 2, 2])
        self.assertEqual(len(bench.twin_items(twin_row(1, [1, 2, 2]), "all")), 5)

    def test_run_scores_methods_and_caches_summaries(self):
        rows = [twin_row(p, [1, 2, 2]) for p in range(4)]

        def answer(system, user):
            if system == bench.SUMMARY_SYSTEM:
                return "Frugal shopper."
            n = user.count("Buy item")
            return json.dumps({"answers": [1, 2, 2][:n]} if "Frugal" in user else {"answers": [2] * n})
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        c = fake(answer)
        res = bench.run_twin(rows, 4, c, ["no_persona", "twin"], items_per_person=3, approve_spend=True, cache_dir=d)
        tw, nop, maj = res["methods"]["twin"], res["methods"]["no_persona"], res["methods"]["majority"]
        self.assertEqual(tw["accuracy"], 1.0)
        self.assertEqual(tw["test_retest"], 1.0)
        self.assertEqual(tw["normalized_accuracy"], 1.0)
        self.assertAlmostEqual(nop["accuracy"], round(2 / 3, 3))
        self.assertEqual(tw["real_purchase_share"], round(1 / 3, 3))
        self.assertEqual(maj["accuracy"], 1.0)
        self.assertEqual(tw["calls"], 8)
        bench.run_twin(rows, 4, c, ["twin"], items_per_person=3, approve_spend=True, cache_dir=d)
        self.assertEqual(sum(1 for s, _ in c.calls if s == bench.SUMMARY_SYSTEM), 4)   # summaries cached
        self.assertTrue(bench.run_twin(rows, 4, None, ["twin"])["dry_run"])

    def test_spearman_and_pick(self):
        self.assertEqual(bench.spearman([1, 2, 3], [10, 20, 30]), 1.0)
        self.assertEqual(bench.spearman([1, 2, 3], [3, 2, 1]), -1.0)
        self.assertIsNone(bench.spearman([1], [1]))
        self.assertEqual(bench.pick(list(range(50)), 5), bench.pick(list(range(50)), 5))


class CLI(unittest.TestCase):
    def test_dry_run_writes_results_without_a_model(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = mirofish.main(["bench", "--suite", "upworthy", "--data", CSV, "--out", d, "--methods", "generic_reader"])
        self.assertEqual(code, 0, out.getvalue())
        res = json.loads(out.getvalue())
        self.assertTrue(res["dry_run"])
        self.assertIn("Dry run", open(os.path.join(d, "bench_upworthy.md")).read())
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(mirofish.main(["bench", "--suite", "twin2k", "--cache", os.path.join(d, "none"), "--out", d]), 1)


if __name__ == "__main__":
    unittest.main()
