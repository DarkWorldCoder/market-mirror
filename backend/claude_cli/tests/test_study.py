"""Studies: spec normalisation, cell configs, metrics from cells, aggregation with deltas and agreement, markdown, runner resume."""

import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import study as st  # noqa: E402

BASE = {"name": "fitloop", "brand": "Fitloop", "seeds": ["brief.md"], "creatives": "creatives.json", "rounds": 3,
        "survey": {"offer": "trial with card", "goal": "start", "messages": "messages.txt", "split": True}, "pitch": {"script": "pitch.md"}}
SPEC = {"name": "fitloop offer", "base": BASE, "simulation_id": "sim_x",
        "scenarios": [{"name": "current", "overrides": {}}, {"name": "no_card", "overrides": {"survey": {"offer": "trial, no card"}}}],
        "seeds": [1, 2, 3], "steps": ["feed_test", "survey"]}


def _write_cell(path, convert_yes, intent, decision, finished=True):
    os.makedirs(path, exist_ok=True)
    json.dump({"decision": {"decision": decision, "confidence": "low"},
               "marketing": {"overall": {"convert_yes": convert_yes, "convert_maybe": 50.0, "trust": 4.0, "click_yes": 10.0,
                                         "ssr": {"purchase": {"mean": intent}}},
                             "objections": [{"label": "trust", "share": 60.0}], "messages_ranked": [{"label": "#2 cheap"}]}},
              open(os.path.join(path, "summary.json"), "w"))
    json.dump({"summary": {"ranked": ["a"], "per_creative": {"a": {"expected_ctr": 5.0}, "b": {"expected_ctr": 2.0}}}}, open(os.path.join(path, "feed_test.json"), "w"))
    if finished:
        json.dump({"finished_at": "now"}, open(os.path.join(path, "run_manifest.json"), "w"))


class StudyTests(unittest.TestCase):
    def test_normalize_and_cell_config(self):
        s = st.normalize(SPEC, "/tmp")
        self.assertEqual((s["name"], s["simulation_id"], s["seeds"]), ("fitloop_offer", "sim_x", [1, 2, 3]))
        cfg = st.cell_config(s, s["scenarios"][1], 2, "/tmp/study")
        self.assertEqual(cfg["survey"]["offer"], "trial, no card")
        self.assertEqual(cfg["survey"]["goal"], "start")                  # deep merge keeps the rest
        self.assertEqual((cfg["simulation_id"], cfg["seed"], cfg["approve_spend"]), ("sim_x", 2, True))
        self.assertNotIn("seeds", cfg)                                     # people already exist: no upload
        self.assertNotIn("pitch", cfg)                                     # not in steps
        self.assertNotIn("rounds", cfg)
        self.assertFalse(cfg["report"])
        self.assertTrue(cfg["out"].endswith("no_card-s2"))
        with self.assertRaises(ValueError):
            st.normalize({"name": "x", "base": BASE}, "/tmp")              # no simulation id

    def test_cell_metrics_aggregate_markdown(self):
        d = tempfile.mkdtemp()
        s = st.normalize(SPEC, d)
        cells = []
        for seed, (cy, iy) in zip([1, 2, 3], [(3.0, 3.1), (4.0, 3.2), (3.5, 3.0)]):
            p = st.cell_dir(d, "current", seed)
            _write_cell(p, cy, iy, "iterate")
            cells.append({"scenario": "current", "seed": seed, "path": p, "metrics": st.cell_metrics(p)})
        for seed, (cy, iy) in zip([1, 2, 3], [(9.0, 3.6), (10.0, 3.7), (11.0, 3.8)]):
            p = st.cell_dir(d, "no_card", seed)
            _write_cell(p, cy, iy, "go")
            cells.append({"scenario": "no_card", "seed": seed, "path": p, "metrics": st.cell_metrics(p)})
        self.assertEqual(cells[0]["metrics"]["best_expected_ctr"], 5.0)
        summ = st.aggregate(s, cells)
        sc = {x["name"]: x for x in summ["scenarios"]}
        self.assertEqual(sc["no_card"]["metrics"]["convert_yes"]["mean"], 10.0)
        self.assertEqual(sc["no_card"]["decision"], "go")
        delta = summ["deltas"][0]["metrics"]["convert_yes"]
        self.assertEqual(delta["delta"], 6.5)
        self.assertTrue(delta["clear"] and delta["better"])
        c = summ["conclusion"]
        self.assertEqual((c["best_scenario"], c["headline_metric"], c["stability_pct"], c["confidence"]), ("no_card", "intent", 100.0, "high"))
        self.assertEqual(len(summ["agreement"]), 3)
        md = st.render_markdown(summ, "Fitloop")
        self.assertIn("# Fitloop: study of 2 scenarios x 3 seeds", md)
        self.assertIn("**Conclusion: GO with no_card** (high confidence)", md)
        self.assertIn("| Would convert (%) |", md)
        html = st.render_html(summ, lambda m: "<p>" + m[:20] + "</p>", "body{}", "Fitloop", {"a": "a/dashboard.html"})
        self.assertIn("<!doctype html>", html) and self.assertIn('href="a/dashboard.html"', html)

    def test_run_skips_finished_cells(self):
        d = tempfile.mkdtemp()
        s = st.normalize({**SPEC, "seeds": [1, 2]}, d)
        _write_cell(st.cell_dir(d, "current", 1), 3.0, 3.1, "iterate")   # already done
        ran = []

        def run_cell(cfg, cfg_path):
            ran.append((cfg["name"], cfg["seed"]))
            _write_cell(cfg["out"], 5.0, 3.3, "iterate")
        summ = st.run(s, d, run_cell, lambda m: None)
        self.assertEqual(ran, [("current-s2", 2), ("no_card-s1", 1), ("no_card-s2", 2)])
        self.assertTrue(os.path.exists(os.path.join(d, "study_summary.json")))
        self.assertEqual(len(summ["cells"]), 4)


if __name__ == "__main__":
    unittest.main()
