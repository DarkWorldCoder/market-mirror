"""Behaviour state and episodic memory across tests (scopes, transitions, prompt block, events from results)."""

import json
import os
import tempfile
import unittest

from app.services import behavior_state as bs


class BehaviorStateTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_transitions_clamp_and_cap(self):
        events = [{"agent_id": 1, "test": "feed_test", "kind": "hid_ad", "text": f"hid {i}"} for i in range(40)]
        self.assertEqual(bs.record(self.dir, events, "a"), 40)
        st = bs.load(self.dir)["scopes"]["a"]["1"]
        self.assertEqual(st["state"]["trust"], 0.0)
        self.assertEqual(st["state"]["fatigue"], 1.0)
        self.assertEqual(len(st["memory"]), bs.MAX_MEMORIES)
        self.assertEqual(st["memory"][-1]["text"], "hid 39")

    def test_scopes_do_not_leak(self):
        bs.record(self.dir, [{"agent_id": 2, "kind": "clicked_ad", "text": "You tapped the no-card ad."}], "study:no_card:s1")
        self.assertEqual(bs.memories_for(self.dir, 2, "study:current:s1"), [])
        self.assertIn("no-card", bs.prompt_block(self.dir, 2, "study:no_card:s1"))
        self.assertEqual(bs.prompt_block(self.dir, 3, "study:no_card:s1"), "")

    def test_events_from_results(self):
        feed = {"seed": 5, "creatives": [{"id": "a", "headline": "7 days free"}], "sessions": [
            {"agent_id": 1, "creative_id": "a", "platform": "instagram", "exposure": 1, "seed": 5,
             "ad": {"noticed": True, "stopped": True, "click": True, "reaction": "like", "comment": "is it really free?", "thought": "hmm"}},
            {"agent_id": 1, "creative_id": "a", "platform": "instagram", "exposure": 1, "seed": 6, "ad": {"noticed": True, "click": True}},
            {"agent_id": 2, "creative_id": "a", "platform": "instagram", "exposure": 1, "seed": 5, "ad": {}}]}
        kinds = [e["kind"] for e in bs.events_from_feed_test(feed, "Fitloop")]
        self.assertEqual(kinds, ["stopped_on_ad", "clicked_ad", "reacted_to_ad", "commented_on_ad", "saw_ad"])
        mail = {"sessions": [{"agent_id": 1, "email_id": "e", "step": 1, "subject": "Hi", "opened": True, "action": "unsubscribe", "reason": "too many"},
                             {"agent_id": 2, "email_id": "e", "step": 1, "subject": "Hi", "opened": False}]}
        self.assertEqual([e["kind"] for e in bs.events_from_email_test(mail)], ["unsubscribed", "received_email"])
        survey = bs.events_from_survey([{"agent_id": 1, "answer": {"would_convert": "no", "main_objection": "card step"}}], "trial")
        self.assertEqual([e["kind"] for e in survey], ["answered_survey", "objected"])
        pitch = bs.events_from_pitch({"people": [{"agent_id": 1, "turn1": {"reply": "no thanks"}, "final_verdict": "no"}]})
        self.assertEqual([e["kind"] for e in pitch], ["heard_pitch", "declined"])
        n = bs.record(self.dir, survey + pitch)
        summ = bs.summary(self.dir)
        self.assertEqual(n, 4)
        self.assertEqual(summ["people"], 1)
        self.assertLess(summ["avg_trust"], 0.5)
        self.assertIn("moods", summ)
        self.assertIn("trajectories", summ)
        st = bs.load(self.dir)["scopes"]["default"]["1"]
        self.assertIn("mood", st["state"])
        self.assertTrue(len(st.get("trajectory", [])) >= 1)



class MemoryApiTest(unittest.TestCase):
    def test_memory_endpoint_and_feed_history(self):
        from unittest import mock
        from app import create_app
        from app.api import market
        app = create_app()
        d = tempfile.mkdtemp()
        with mock.patch.object(market, "_sim_dir", lambda sid: d):
            cl = app.test_client()
            r = cl.post("/api/simulation/sim_x/memory", json={"scope": "s1", "survey": {"offer": "trial", "responses": [
                {"agent_id": 4, "answer": {"would_convert": "maybe", "main_objection": "price"}}]}})
            self.assertEqual(r.get_json()["data"]["events_recorded"], 2)
            r = cl.get("/api/simulation/sim_x/memory?scope=s1&agent=4")
            self.assertEqual(len(r.get_json()["data"]["person"]["memory"]), 2)
            people = market._with_history([{"agent_id": 4}, {"agent_id": 5}], "sim_x", "s1")
            self.assertIn("price", people[0]["history"])
            self.assertEqual(people[1]["history"], "")
        self.assertEqual(market._memory_scope({"memory_scope": "off"}), "")
        self.assertEqual(market._memory_scope({}), "default")


if __name__ == "__main__":
    unittest.main()


def test_stale_running_status_reads_as_stopped(tmp_path):
    import json as _json
    from app.api import market
    (tmp_path / "run_state.json").write_text(_json.dumps({"runner_status": "running", "process_pid": 999999999}))
    assert market._runner_status(str(tmp_path)) == "stopped"
    (tmp_path / "run_state.json").write_text(_json.dumps({"runner_status": "running", "process_pid": __import__("os").getpid()}))
    assert market._runner_status(str(tmp_path)) == "running"


def test_env_is_not_alive_when_its_process_is_gone(tmp_path, monkeypatch):
    import json as _json
    from app.services.simulation_runner import SimulationRunner
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))
    d = tmp_path / "sim_x"
    d.mkdir()
    (d / "env_status.json").write_text(_json.dumps({"status": "alive", "reddit_available": True}))
    (d / "run_state.json").write_text(_json.dumps({"runner_status": "running", "process_pid": 999999999}))
    assert SimulationRunner.check_env_alive("sim_x") is False
    assert SimulationRunner.get_env_status_detail("sim_x")["status"] == "stopped"
