"""Marketing layer: survey prompt/parsing, split test, pricing, playbook and dashboard rendering."""

import json
import os
import random
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import exporter  # noqa: E402
import marketing as mk  # noqa: E402
import mirofish  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "sample_run")
SEGMENTS = [("Nepal students", "Nepal"), ("Nepal parents", "Nepal"), ("Bangladesh students", "Bangladesh"),
            ("Indonesia parents", "Indonesia")]
MESSAGES = ["See your score free", "Could you qualify for a discount?", "Parents: plan before you pay an agent"]


def make_survey_bundle(n_per_segment=8, split=True, pricing=True, seed=3):
    """A bundle with a persona index and survey answers whose conversion depends on segment and message."""
    rng = random.Random(seed)
    index, responses = [], []
    aid = 0
    people = []
    for seg, country in SEGMENTS:
        for _ in range(n_per_segment):
            index.append({"agent_id": aid, "name": f"P{aid}", "kind": "persona", "segment": seg, "country": country,
                          "age": rng.randint(17, 55), "gender": rng.choice(["male", "female"]),
                          "communities": [f"{country} group"]})
            people.append(aid)
            aid += 1
    index.append({"agent_id": aid, "name": "Nepal group", "kind": "community"})
    assigned = mk.assign_messages(people, len(MESSAGES)) if split else {}
    for row in index[:-1]:
        a = row["agent_id"]
        msg = assigned.get(a, rng.randrange(3))
        base = {"Bangladesh students": 0.8, "Indonesia parents": 0.6, "Nepal students": 0.35, "Nepal parents": 0.1}[row["segment"]]
        p = base + (0.15 if msg == 0 else -0.1 if msg == 2 else 0)
        conv = "yes" if rng.random() < p else ("maybe" if rng.random() < 0.4 else "no")
        ans = {"noticed": True, "interest": 8 if conv == "yes" else 5 if conv == "maybe" else 2, "trust": 6,
               "would_click": "yes" if conv != "no" else "no", "would_convert": conv, "recommend": 9 if conv == "yes" else 4,
               "main_objection": "" if conv == "yes" else "Looks like an agent scam",
               "objection_type": "none" if conv == "yes" else rng.choice(["trust", "price", "language"]),
               "would_change_mind": "Show it is really free" if conv != "yes" else "", "quote": f"quote {a}"}
        if not split:
            ans["best_message"] = f"{msg + 1}"
        if pricing:
            ans.update({"price_too_cheap": rng.choice([0, 1, 2]), "price_cheap": rng.choice([3, 5]),
                        "price_expensive": rng.choice([8, 10, 12]), "price_too_expensive": rng.choice([15, 20, 25])})
        raw = "Sure! " + json.dumps(ans) + " Thanks."
        responses.append({"agent_id": a, "name": row["name"], "assigned_message": assigned.get(a), "raw": raw,
                          "answer": mk.parse_answer(raw, len(MESSAGES))})
    survey = {"offer": "Free Acme practice test", "goal": "sign up for the free practice test", "messages": MESSAGES,
              "mode": "split" if split else "pick", "currency": "USD" if pricing else None, "responses": responses}
    return {"config": {"persona_index": index}, "survey": survey,
            "actions": [{"agent_id": a, "action_type": "CREATE_POST"} for a in people[::2]]}


class ParseTest(unittest.TestCase):
    def test_parse_answer_variants(self):
        a = mk.parse_answer('```json\n{"interest": "7/10", "would_convert": "Yes, definitely", "would_click": true,'
                            ' "objection_type": "Scam", "best_message": "Message #2", "price_cheap": "$1,200"}\n```', 3)
        self.assertEqual(a["interest"], 7.0)
        self.assertEqual(a["would_convert"], "yes")
        self.assertEqual(a["would_click"], "yes")
        self.assertEqual(a["objection_type"], "other")
        self.assertEqual(a["best_message"], "#2")
        self.assertEqual(a["price_cheap"], 1200.0)
        self.assertIsNone(mk.parse_answer("I don't want to answer that."))
        self.assertEqual(mk.parse_answer('{"would_convert": "probably not"}')["would_convert"], "no")
        self.assertEqual(mk.parse_answer('{"would_convert": "not sure"}')["would_convert"], "maybe")

    def test_survey_prompt_modes(self):
        split = mk.survey_prompt("Offer X", "buy it", MESSAGES, assigned=1, currency="NPR")
        self.assertIn(MESSAGES[1], split)
        self.assertNotIn(MESSAGES[0], split)
        self.assertIn("message_reaction", split)
        self.assertIn("price_too_expensive", split)
        pick = mk.survey_prompt("Offer X", "buy it", MESSAGES)
        self.assertIn("3. " + MESSAGES[2], pick)
        self.assertIn("best_message", pick)
        self.assertNotIn("price_", mk.survey_prompt())

    def test_assign_messages_is_balanced(self):
        counts = {}
        for m in mk.assign_messages(list(range(31)), 3).values():
            counts[m] = counts.get(m, 0) + 1
        self.assertEqual(sorted(counts.values()), [10, 10, 11])

    def test_interview_texts_handles_both_platforms(self):
        res = {"result": {"results": {"twitter_0": {"agent_id": 0, "response": "no json"},
                                      "reddit_0": {"agent_id": 0, "response": '{"interest": 5}'},
                                      "reddit_1": {"agent_id": 1, "response": {"interest": 9}}}}}
        texts = mk.interview_texts(res)
        self.assertIn("interest", texts[0])
        self.assertIn("9", texts[1])

    def test_read_messages_formats(self):
        self.assertEqual(mirofish.read_messages('["a", "b"]'), ["a", "b"])
        self.assertEqual(mirofish.read_messages("1. first ad\n2) second ad\n- third"), ["first ad", "second ad", "third"])
        self.assertEqual(mirofish.read_messages("Headline A\nline 2\n---\nHeadline B"), ["Headline A\nline 2", "Headline B"])


class AnalyzeTest(unittest.TestCase):
    def test_split_test_analysis(self):
        a = mk.analyze(make_survey_bundle())
        self.assertTrue(a["has_survey"] and a["split_test"])
        self.assertEqual(a["people"], 32)
        self.assertEqual(a["answered"], 32)
        self.assertEqual(a["by_segment"][0]["key"], "Bangladesh students")
        self.assertEqual(a["by_segment"][-1]["key"], "Nepal parents")
        self.assertEqual({m["key"] for m in a["messages_ranked"]}, {"#1", "#2", "#3"})
        self.assertEqual(sum(m["votes"] for m in a["messages_ranked"]), 32)
        self.assertEqual(a["funnel"][0], ("Simulated people", 32))
        self.assertEqual(a["funnel"][1], ("Answered the survey", 32))
        self.assertEqual(a["engaged"], 16)
        vals = [v for _, v in a["funnel"]]
        self.assertEqual(vals, sorted(vals, reverse=True))           # a funnel only narrows
        self.assertTrue(a["verdicts"][0].endswith("on the fence."))
        self.assertTrue(any(v.startswith("Split test winner") for v in a["verdicts"]))
        pr = a["pricing"]
        self.assertTrue(pr["acceptable_low"] <= pr["optimal"] <= pr["acceptable_high"])
        self.assertEqual(len(pr["curves"]["prices"]), len(pr["curves"]["too_cheap"]))
        self.assertEqual(a["playbook"][0]["segment"], "Bangladesh students")
        self.assertEqual(a["playbook"][0]["priority"], "high")
        self.assertTrue(a["playbook"][-1]["answer_with"])
        self.assertEqual(len(a["message_grid"]["rows"]), 4)

    def test_pick_mode_and_no_survey(self):
        a = mk.analyze(make_survey_bundle(split=False, pricing=False))
        self.assertFalse(a["split_test"])
        self.assertIsNone(a["pricing"])
        self.assertTrue(a["messages_ranked"])
        empty = mk.analyze({"config": {"persona_index": [{"agent_id": 0, "kind": "persona", "segment": "S"}]}})
        self.assertFalse(empty["has_survey"])
        self.assertEqual(empty["engagement_by_segment"][0]["key"], "S")
        html_ = "".join(h for _, _, h in mk.render_sections(empty))
        self.assertIn("buyer survey", html_)


class DashboardTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        for name in os.listdir(FIXTURE):
            shutil.copy(os.path.join(FIXTURE, name), self.dir)

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_dashboard_has_marketing_sections_and_inlined_charts(self):
        b = make_survey_bundle()
        with open(os.path.join(self.dir, "survey.json"), "w") as f:
            json.dump(b["survey"], f)
        cfg_path = os.path.join(self.dir, "config.json")
        cfg = json.load(open(cfg_path))
        inner = cfg.get("data", cfg)
        inner["persona_index"] = b["config"]["persona_index"]
        json.dump(cfg, open(cfg_path, "w"))
        paths = exporter.export_run_dir(self.dir)
        page = open(paths["html"], encoding="utf-8").read()
        for anchor in ("results", "playbook", "funnel", "audiences", "objections", "messages", "pricing", "voices"):
            self.assertIn(f'id="{anchor}"', page)
        self.assertLess(page.index('id="results"'), page.index('id="graph"'))
        self.assertIn('data-kind="heat"', page)
        self.assertIn('data-kind="price"', page)
        self.assertIn("echarts", page[:2_000_000])
        self.assertEqual(page.count("</script>"), page.count("<script"))
        self.assertIn('id="downloads"', page)
        self.assertIn("survey_answers.csv", page)
        summary = json.load(open(paths["summary_json"]))
        self.assertTrue(summary["marketing"]["split_test"])
        self.assertNotIn("curves", summary["marketing"]["pricing"])

    def test_dashboard_without_survey_still_renders(self):
        paths = exporter.export_run_dir(self.dir)
        page = open(paths["html"], encoding="utf-8").read()
        self.assertIn('id="results"', page)
        self.assertIn("buyer survey", page)


if __name__ == "__main__":
    unittest.main()
