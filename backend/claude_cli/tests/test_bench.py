"""MarketMirror-Bench with fake models: the Upworthy loader (clear winners only), Twin-2K-500 items and the
retest ceiling, metrics, dry runs that spend nothing, and the CLI."""

import contextlib
import io
import json
import math
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


def feel_reader(system, user):
    """reader, plus feelings when asked: the winning headline feels a bit unpleasant (the negativity effect)."""
    if system == bench.PANEL_SYSTEM and '"feel"' in user:
        lines = [l for l in user.splitlines() if l[:1].isdigit()]
        pick = next((i + 1 for i, l in enumerate(lines) if any(w in l for w in WINNERS)), 0)
        feel = [{"emotion": "irritation", "pleasant": -0.5, "relevant": 0.7, "words": "ugh"} if any(w in l for w in WINNERS)
                else {"emotion": "neutral", "pleasant": 0.0, "relevant": 0.1, "words": "meh"} for l in lines]
        return json.dumps({"click": pick, "feel": feel})
    return reader(system, user)


class EmotionAblation(unittest.TestCase):
    def test_feel_and_mood_panels_with_paired_intervals_and_checks(self):
        c = fake(feel_reader)
        people = [{"persona": "A busy dad", "name": "Ravi"}, {"persona": "A cat lover", "name": "Mei"}]
        res = bench.run_upworthy(CSV, 10, c, ["generic_reader", "persona_panel", "persona_panel_feel", "persona_panel_mood"],
                                 people, approve_spend=True)
        m = res["methods"]
        self.assertEqual(m["persona_panel_feel"]["top_choice_accuracy"], 1.0)
        self.assertEqual(m["persona_panel_feel"]["vs_persona_panel"]["diff"], 0.0)
        self.assertEqual(m["persona_panel_mood"]["vs_generic_reader"]["n"], 2)
        self.assertEqual(m["persona_panel"]["unanimity"], 1.0)        # everyone picked the same: herding proxy
        f = m["persona_panel_feel"]["feelings"]
        self.assertTrue(f["negativity_sign_matches"])
        self.assertLess(f["valence_ctr_spearman"], 0)
        self.assertGreater(f["quality"]["n"], 0)
        self.assertEqual(sorted(m["persona_panel"]["per_test"]), ["t1", "t5"])
        self.assertNotIn("per_test", bench.render_markdown(res))     # per-unit detail stays in the JSON
        dry = bench.run_upworthy(CSV, 10, None, ["persona_panel_feel"], people)
        self.assertTrue(dry["dry_run"])
        self.assertEqual(dry["estimate"]["calls"], 4)

    def test_mood_line_is_seeded_and_mild(self):
        p = {"name": "Asha Rao", "persona": "x"}
        self.assertEqual(bench.mood_line(p), bench.mood_line(p))
        lines = [bench.mood_line({"name": f"P{i}"}) for i in range(30)]
        self.assertTrue(any(lines) and not all(lines))               # some people feel nothing much
        self.assertFalse(any("very" in l.lower() or "extremely" in l.lower() for l in lines))

    def test_twin_affect_and_gate(self):
        rows = [twin_row(p, [1, 2, 2]) for p in range(4)]

        def answer(system, user):
            if system == bench.SUMMARY_SYSTEM:
                return "Frugal shopper."
            n = user.count("Buy item")
            return json.dumps({"feel": [0.0] * n, "answers": [1, 2, 2][:n]})
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        twin = bench.run_twin(rows, 4, fake(answer), ["twin", "twin_affect"], items_per_person=3, approve_spend=True, cache_dir=d)
        self.assertEqual(twin["methods"]["twin_affect"]["vs_twin"]["diff"], 0.0)
        self.assertEqual(twin["methods"]["twin"]["ci95"], [1.0, 1.0])
        up = bench.run_upworthy(CSV, 10, fake(feel_reader), ["generic_reader", "persona_panel", "persona_panel_feel"],
                                [{"persona": "A busy dad", "name": "Ravi"}, {"persona": "A cat lover", "name": "Mei"}],
                                approve_spend=True)
        g = bench.flip_gate(up, twin)
        names = {c["check"]: c["pass"] for c in g["checks"]}
        self.assertTrue(names["feelings panel >= persona_panel (Upworthy)"])
        self.assertTrue(names["twin_affect >= twin (Twin-2K-500)"])
        self.assertTrue(names["negativity sign matches"])
        self.assertIn("Result:", bench.render_gate(g))
        none = bench.flip_gate(None, None)
        self.assertFalse(none["pass"])
        self.assertEqual(none["eligible_default"], "observe")
        self.assertIn("stays **observe**", bench.render_gate(none))
        # a feelings panel that skipped tests, or a missing Brier score, does not pass
        thin = json.loads(json.dumps(up))
        thin["methods"]["persona_panel_feel"]["n"] = 1
        self.assertFalse(bench.flip_gate(thin, twin)["checks"][0]["pass"])
        no_brier = json.loads(json.dumps(twin))
        no_brier["methods"]["twin_affect"]["brier_purchase"] = None
        self.assertFalse(next(c for c in bench.flip_gate(up, no_brier)["checks"] if "Twin" in c["check"])["pass"])
        self.assertTrue(all(c["detail"] == "not run" for c in none["checks"]))

    def test_bootstrap_is_reproducible(self):
        xs = [1, 0, 1, 1, 0, 1, 0, 1]
        self.assertEqual(bench.bootstrap_ci(xs), bench.bootstrap_ci(xs))
        lo, hi = bench.bootstrap_ci(xs)
        self.assertTrue(0 <= lo <= 0.625 <= hi <= 1)
        self.assertIsNone(bench.bootstrap_ci([1]))
        self.assertEqual(bench.paired_diff({"a": 1, "b": 0}, {"a": 0, "b": 0})["diff"], 0.5)


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

    def test_rank_correlation_and_sd_ratio_across_people(self):
        opts = ["Yes, I would purchase the product", "No, I would not purchase the product"]
        people = [{"pid": p, "items": [{"id": "Q0", "options": opts, "answer": a0, "retest": None},
                                       {"id": "Q1", "options": opts, "answer": a1, "retest": None},
                                       {"id": "Q2", "options": opts, "answer": 1, "retest": None}]}
                  for p, (a0, a1) in enumerate([(1, 1), (1, 2), (2, 1), (2, 2)])]
        real = {(p["pid"], it["id"]): it["answer"] for p in people for it in p["items"]}
        exact = bench.score_twin(people, real)
        # Q2 has one real answer for everyone, so only Q0 and Q1 count.
        self.assertEqual(exact["rank_correlation"], 1.0)
        self.assertEqual(exact["sd_ratio"], 1.0)
        # Everyone predicted to buy: right on half the answers, but no one told apart and no spread at all.
        flat = bench.score_twin(people, {k: 1 for k in real})
        self.assertIsNone(flat["rank_correlation"])
        self.assertEqual(flat["sd_ratio"], 0.0)
        # Q0 ranked right with less spread (1,1,1,2 against 1,1,2,2); Q1 ranked backwards (2,1,2,1 against 1,2,1,2).
        mixed = {**real, (2, "Q0"): 1, (0, "Q1"): 2, (1, "Q1"): 1, (2, "Q1"): 2, (3, "Q1"): 1}
        got = bench.score_twin(people, mixed)
        rho_q0 = bench.spearman([1, 1, 1, 2], [1, 1, 2, 2])
        self.assertEqual(got["rank_correlation"], round((rho_q0 - 1.0) / 2, 3))
        self.assertEqual(got["sd_ratio"], round((math.sqrt(3) / 2 + 1.0) / 2, 3))
        # An option number the question doesn't have (0, 3) is left out, not read as a wide spread.
        bad = bench.score_twin(people, {**real, (0, "Q0"): 0, (3, "Q0"): 3})
        self.assertEqual(bad["rank_correlation"], 1.0)
        self.assertEqual(bad["sd_ratio"], 1.0)
        # Questions answered by one person only can't rank anyone.
        self.assertIsNone(bench.score_twin(people[:1], real)["rank_correlation"])
        self.assertIsNone(bench.score_twin(people[:1], real)["sd_ratio"])

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
