"""Large markets on the CLI side: survey batches that fail, provider-mixed batches, patient task waits, pauses on
any gateway of the pool, atomic files, panel material from every group, a lean report request."""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import market_cli  # noqa: E402
import mirofish  # noqa: E402
import quota  # noqa: E402

PROVIDERS = ("claude", "codex", "antigravity")


class SurveyClient:
    """60 people from three providers (20 each, numbered provider by provider); the first batch that reaches the
    backend fails, everything else answers."""

    def __init__(self):
        self.batches = []

    def data(self, method, path, json=None, params=None, timeout=None):
        if path.endswith("/config"):
            return {"persona_index": [{"agent_id": i, "name": f"P{i}", "kind": "persona", "segment": "S",
                                       "model_provider": PROVIDERS[i // 20]} for i in range(60)]}
        if path.endswith("/profiles"):
            return {"profiles": []}
        if path == "/api/simulation/interview/batch":
            ids = [it["agent_id"] for it in json["interviews"]]
            self.batches.append(ids)
            if len(self.batches) == 1:
                raise mirofish.CLIError("POST interview/batch: 504 timed out")
            reply = {"purchase_text": "x", "interest": 5, "trust": 5, "would_click": "no", "would_convert": "no",
                     "objection_type": "price"}
            return {"result": {"results": [{"agent_id": a, "response": mirofish.json.dumps(reply)} for a in ids]}}
        return {}


class ScaleCliTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d)

    def test_a_failed_batch_is_asked_again_and_batches_mix_providers(self):
        c = SurveyClient()
        with mock.patch.object(quota, "wait_if_paused", lambda *a, **k: 0):
            res = mirofish.step_survey(c, "sim_x", self.d, "offer", "sign up", [], batch=12, ssr=False)
        self.assertEqual((res["asked"], res["answered"]), (60, 60))      # the failed batch was asked once more
        first = c.batches[0]
        self.assertEqual({a // 20 for a in first}, {0, 1, 2})               # every provider in every batch
        self.assertTrue(os.path.exists(os.path.join(self.d, "survey_partial.json")))

    def test_wait_task_tolerates_a_few_status_errors(self):
        calls = {"n": 0}

        class C:
            def data(self, method, path, json=None, params=None, timeout=None):
                calls["n"] += 1
                if calls["n"] < 3:
                    raise mirofish.CLIError("503")
                return {"status": "completed", "progress": 100}
        logs = []
        with mock.patch.object(market_cli.time, "sleep", lambda s: None):
            st = market_cli.wait_task(C(), "t1", "feedtest", logs.append)
        self.assertEqual(st["status"], "completed")
        self.assertTrue(any("trying again" in m for m in logs))

    def test_any_paused_pool_gateway_pauses_the_run_unless_it_is_paused_for_days(self):
        states = {"http://a": {"paused": False, "limit_hits": 1},
                  "http://b": {"paused": True, "resume_in_s": 600, "paused_until": "soon", "limit_hits": 2},
                  "http://c": {"paused": True, "resume_in_s": 10 * 24 * 3600, "paused_until": "next week"}}
        with mock.patch.object(quota, "gateway_urls", lambda: list(states)), \
                mock.patch.object(quota, "_one_status", lambda u: states[u]):
            st = quota.status()
        self.assertTrue(st["paused"])
        self.assertEqual(st["resume_in_s"], 600)                            # the week-long pause is left out
        self.assertEqual(st["limit_hits"], 3)

    def test_save_json_is_atomic(self):
        mirofish.save_json(self.d, "x", {"a": 1})
        self.assertEqual(json.load(open(os.path.join(self.d, "x.json"))), {"a": 1})
        self.assertEqual(os.listdir(self.d), ["x.json"])

    def test_panel_material_reaches_every_segment_and_provider_early(self):
        index = [{"agent_id": i, "kind": "persona", "segment": f"S{i // 300}", "model_provider": PROVIDERS[(i // 100) % 3]}
                 for i in range(900)]
        survey = {"responses": [{"agent_id": i, "answer": {"quote": f"q{i}", "would_convert": "no"}} for i in range(900)]}
        material = market_cli.build_material({"config": {"persona_index": index}, "survey": survey})
        first = material["survey"][:18]
        self.assertEqual({r["segment"] for r in first}, {"S0", "S1", "S2"})
        self.assertTrue(all("_by" not in r for r in material["survey"]))
        texts = {int(r["text"][1:]) for r in first}
        self.assertEqual({(t // 100) % 3 for t in texts}, {0, 1, 2})

    def test_the_report_request_carries_a_lean_people_list(self):
        bundle = {"summary": {"x": 1}, "config": {"persona_index": [
            {"agent_id": 1, "segment": "S", "name": "A", "interview": [{"q": "Q1", "a": "long"}] * 12, "bde": {"b": {}}}]}}
        keep = market_cli.compact_material(bundle)
        row = keep["config"]["persona_index"][0]
        self.assertEqual(row, {"agent_id": 1, "segment": "S", "name": "A"})


if __name__ == "__main__":
    unittest.main()
