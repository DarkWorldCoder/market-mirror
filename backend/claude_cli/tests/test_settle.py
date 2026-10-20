"""Settle mode: ask in batches interleaved across cells and stop a cell once its shares are settled."""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mirofish  # noqa: E402
import settle  # noqa: E402


class SettleClient:
    """People 0-299 from provider "steady" all say no; 300-599 from "split" say yes or no alternately."""

    def __init__(self):
        self.asked = []

    def data(self, method, path, json=None, params=None, timeout=None):
        if path.endswith("/config"):
            return {"persona_index": [{"agent_id": i, "name": f"P{i}", "kind": "persona", "segment": "S",
                                       "model_provider": "steady" if i < 300 else "split"} for i in range(600)]}
        if path.endswith("/profiles"):
            return {"profiles": []}
        if path == "/api/simulation/interview/batch":
            out = []
            for it in json["interviews"]:
                aid = it["agent_id"]
                self.asked.append(aid)
                verdict = "no" if aid < 300 else ("yes" if aid % 2 else "no")
                reply = {"purchase_text": "x", "interest": 5, "trust": 5, "would_click": "no",
                         "would_convert": verdict, "objection_type": "price"}
                out.append({"agent_id": aid, "response": mirofish.json.dumps(reply)})
            return {"result": {"results": out}}
        return {}


class SettleTest(unittest.TestCase):
    def test_half_width_and_order(self):
        self.assertEqual(settle.half_width(0, 0), 100.0)
        self.assertLess(settle.half_width(0, 60), 5)
        self.assertGreater(settle.half_width(30, 60), 15)
        order = settle.interleaved_order(list(range(10)), lambda p: "a" if p < 5 else "b", seed=1)
        self.assertEqual(sorted(order), list(range(10)))
        self.assertEqual([p < 5 for p in order[:4]].count(True), 2)       # cells alternate

    def test_survey_stops_asking_a_settled_cell_and_keeps_asking_the_others(self):
        d = tempfile.mkdtemp()
        try:
            c = SettleClient()
            mirofish.step_survey(c, "sim_x", d, "offer", "sign up", [], batch=40, ssr=False,
                                 settle={"margin": 5, "min_n": 60, "cells": "provider"})
            survey = json.load(open(os.path.join(d, "survey.json")))
            s = survey["settle"]
            steady, split = s["cells"]["steady"], s["cells"]["split"]
            self.assertTrue(steady["settled"])
            self.assertLessEqual(steady["asked"], 80)                     # settled after about 60 answers
            self.assertEqual(split["asked"], 300)                         # 50/50 never gets within +/-5 at n=300
            self.assertFalse(split["settled"])
            self.assertEqual(s["asked"], len(survey["responses"]))
            self.assertEqual(s["people"], 600)
            self.assertEqual(len(set(c.asked)), len(c.asked))             # nobody asked twice
        finally:
            shutil.rmtree(d)


if __name__ == "__main__":
    unittest.main()
