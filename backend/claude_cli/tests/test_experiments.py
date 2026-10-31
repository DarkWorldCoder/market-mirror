"""The experiment model: spec normalisation, variant mapping to engines, result shaping and the dispatcher with fake engines."""

import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import experiments as ex  # noqa: E402


class SpecTests(unittest.TestCase):
    def test_normalize_and_defaults(self):
        e = ex.normalize({"type": "AD", "variants": [{"id": "a", "text": "x"}], "audience": {"segments": ["parents"]}})
        self.assertEqual((e["type"], e["metric"], e["seeds"]), ("ad", "expected_ctr", 1))
        with self.assertRaises(ValueError):
            ex.normalize({"type": "spaceship", "variants": [1]})
        with self.assertRaises(ValueError):
            ex.normalize({"type": "message", "variants": ["only one"]})

    def test_mappings(self):
        e = ex.normalize({"type": "ad", "variants": [{"id": "a", "text": "A"}, "B text"], "audience": {"countries": ["India"]},
                          "platform": "instagram", "budget": {"amount": 300, "cpm": 2.0}})
        spec = ex.to_creatives(e)
        self.assertEqual([c["id"] for c in spec["creatives"]], ["a", "v2"])
        self.assertEqual(spec["creatives"][1]["platform"], "instagram")
        self.assertEqual(spec["benchmarks"]["instagram"]["budget"], 300)
        cm = ex.normalize({"type": "channel_mix", "variants": [{"id": "ad", "text": "same"}], "platforms": ["facebook", "tiktok"]})
        self.assertEqual([c["platform"] for c in ex.to_creatives(cm)["creatives"]], ["facebook", "tiktok"])
        pr = ex.normalize({"type": "price", "variants": [{"price": "USD 4.99"}, {"price": "USD 2.99"}], "offer": "Fitloop"})
        self.assertTrue(ex.to_messages(pr)[1].startswith("Fitloop at USD 2.99. Everything else is the same"))
        self.assertIn("only the price differs", ex.to_messages(pr)[1])
        held = ex.normalize({"type": "price", "variants": [{"price": "USD 4.99"}, {"price": "USD 3.99"}], "offer": "Fitloop", "held_fixed": "12 workouts a month"})
        self.assertIn("(12 workouts a month)", ex.to_messages(held)[0])
        nm = ex.normalize({"type": "naming", "variants": [{"name": "Fitloop", "tagline": "15 minutes"}, "Movely"]})
        self.assertTrue(ex.to_messages(nm)[0].startswith('The product is called "Fitloop"'))
        la = ex.normalize({"type": "launch", "variants": [{"content": "teaser"}, {"content": "live", "round": 2}]})
        ev = ex.to_events(la, "Fitloop")
        self.assertEqual((len(ev["posts"]), ev["events"][0]["round"], ev["posts"][0]["agent"]), (1, 2, "Fitloop"))
        em = ex.normalize({"type": "email", "variants": [{"subject": "Hi"}, {"subject": "Yo"}], "list_size": 500})
        self.assertEqual(ex.to_emails(em)["list_size"], 500)
        pt = ex.normalize({"type": "pitch", "variants": ["Hi, I am from Fitloop"], "rebuttals": {"*": "ok"}})
        self.assertEqual(ex.to_pitches(pt)[0]["rebuttals"], {"*": "ok"})


class ResultTests(unittest.TestCase):
    def test_from_engines_and_conclude(self):
        e = ex.normalize({"type": "ad", "variants": [{"id": "a"}, {"id": "b"}]})
        ft = {"creatives": [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}],
              "summary": {"per_creative": {"a": {"impressions": 40, "expected_ctr": 8.0, "ctr": 5.0}, "b": {"impressions": 40, "expected_ctr": 2.0, "ctr": 0.0}}}}
        rows = ex.from_feed_test(e, ft)
        res = ex.conclude(e, rows, {})
        self.assertEqual((res["winner"], res["runner_up"], res["lift"]), ("a", "b", 6.0))
        self.assertIn("leads by", res["verdict"])
        self.assertIsNotNone(rows[0]["margin"])
        m = ex.normalize({"type": "message", "variants": ["one", "two"]})
        rows = ex.from_survey(m, {"messages_ranked": [{"key": "#2", "label": "#2 two", "votes": 20, "convert_yes": 30.0}, {"key": "#1", "votes": 20, "convert_yes": 28.0}]}, ["one", "two"])
        res = ex.conclude(m, rows, {})
        self.assertEqual(res["winner"], "v2")
        self.assertFalse(res["clear_winner"])                     # 2 points on 20 people is inside the margin
        self.assertIn("tie", res["verdict"])
        pr = ex.from_pitch("p1", "script", {"pitch_score": 39, "answered": 28, "verdict_after": {"yes": 7.1}, "hot_leads": [1, 2], "objections": [{"type": "trust"}]})
        self.assertEqual((pr["value"], pr["unit"], pr["top_objection"]), (39, "score", "trust"))
        em = ex.from_email(ex.normalize({"type": "email", "variants": [{"id": "x", "subject": "S"}]}),
                           {"emails": [{"id": "x", "subject": "S"}], "summary": {"per_email": {"x": {"sent": 10, "click_rate": 20.0, "open_rate": 50.0}}}})
        self.assertEqual(em[0]["value"], 20.0)
        story = {"brand_posts": [{"platform": "reddit", "round": 1, "content": "teaser", "likes": 3, "comments": [1, 2], "quotes": [], "reach_proxy": 20, "reply_sentiment": {"pos": 2}}]}
        fs = ex.from_feed_story(ex.normalize({"type": "launch", "variants": [{"content": "teaser"}]}), story)
        self.assertEqual((fs[0]["value"], fs[0]["unit"]), (7, "engagement"))

    def test_dispatcher_with_fake_engines(self):
        d = tempfile.mkdtemp()
        calls = []

        def fake_feedtest(c, sid, spec_arg, run_dir, log, seeds=1):
            calls.append(("feedtest", json.loads(spec_arg)["creatives"][0]["id"]))
            json.dump({"creatives": [{"id": "a"}, {"id": "b"}], "summary": {"per_creative": {"a": {"impressions": 10, "expected_ctr": 4.0}, "b": {"impressions": 10, "expected_ctr": 1.0}}}},
                      open(os.path.join(run_dir, "feed_test.json"), "w"))
        engines = {"feedtest": fake_feedtest, "survey": None, "events": None, "start": None, "pitch": None, "emailtest": None, "collect": None, "load_bundle": None}
        e = ex.normalize({"type": "ad", "name": "two ads", "variants": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}]})
        res = ex.run(None, e, "sim_x", d, lambda m: None, engines, brand="Fitloop")
        self.assertEqual(res["winner"], "a")
        self.assertTrue(os.path.exists(os.path.join(d, "experiment_result.json")))
        self.assertEqual(calls, [("feedtest", "a")])
        with self.assertRaises(ValueError):
            ex.run(None, ex.normalize({"type": "conjoint", "variants": []}), "sim_x", d, lambda m: None, engines)


if __name__ == "__main__":
    unittest.main()
