"""The questionnaire command: what it sends, and the json / csv / md files it writes."""

import csv
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import market_cli  # noqa: E402
import mirofish  # noqa: E402

RESULT = {"title": "Tracker", "people": 2, "answered": 2, "too_alike": ["trust"], "position_check": {},
          "questions": [{"id": "trust", "text": "Trust?", "type": "scale", "all": {"n": 2}}], "usage": {"calls": 2},
          "markdown": "# Tracker (simulated answers)\n",
          "csv_rows": [{"respondent": "sim_1", "segment": "A", "country": "NP", "trust": 4},
                       {"respondent": "sim_2", "segment": "B", "country": "NP", "trust": ""}]}


class Client:
    def __init__(self):
        self.sent = []

    def data(self, method, path, json=None, timeout=None):
        self.sent.append((method, path, json))
        if method == "POST":
            return {"task_id": "t1", "people": 2, "questions": 1}
        return dict(RESULT)


class QuestionnaireCliTests(unittest.TestCase):
    def test_writes_three_files_and_keeps_helpers_out_of_the_json(self):
        c = Client()
        with tempfile.TemporaryDirectory() as d, mock.patch.object(market_cli, "wait_task"):
            out = market_cli.questionnaire(c, "sim_x", "Trust? [1-5]", d, lambda m: None, segment="A", seed=3)
            saved = json.load(open(out["questionnaire"], encoding="utf-8"))
            rows = list(csv.DictReader(open(out["csv"], encoding="utf-8")))
            md = open(out["markdown"], encoding="utf-8").read()
        body = c.sent[0][2]
        self.assertEqual((c.sent[0][1], body["questions"], body["segment"], body["seed"]),
                         ("/api/simulation/questionnaire", "Trust? [1-5]", "A", 3))
        self.assertNotIn("csv_rows", saved)
        self.assertNotIn("markdown", saved)
        self.assertEqual([r["trust"] for r in rows], ["4", ""])
        self.assertTrue(md.startswith("# Tracker"))
        self.assertEqual(out["too_alike"], ["trust"])

    def test_parser_and_json_questions(self):
        a = mirofish.build_parser().parse_args(["questionnaire", "--simulation", "s", "--questions", "x", "--people", "5"])
        self.assertEqual((a.people, a.seed), (5, 7))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "q.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"questions": [{"text": "Trust?", "type": "scale"}]}, f)
            a = mirofish.build_parser().parse_args(["questionnaire", "--simulation", "s", "--questions", "@" + path,
                                                    "--run-dir", d])
            with mock.patch.object(market_cli, "questionnaire", return_value={"ok": 1}) as q:
                mirofish.cmd_questionnaire(Client(), a)
            self.assertEqual(q.call_args[0][2], [{"text": "Trust?", "type": "scale"}])


if __name__ == "__main__":
    unittest.main()
