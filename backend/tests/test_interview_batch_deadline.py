"""Batch interviews in the simulation process: a per-interview deadline, and no stale answers for failed ones."""

import asyncio
import json
import os
import sqlite3
import sys
import time

import pytest

pytest.importorskip("oasis")
pytest.importorskip("camel")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import run_parallel_simulation as rps  # noqa: E402


class FakeGraph:
    def get_agent(self, agent_id):
        return agent_id


class FakeEnv:
    """agent id -> behaviour: "hang" never answers, an Exception is raised, a dict is returned as is, a string
    becomes the reply after a short wait."""

    def __init__(self, plan, delay=0.1):
        self.plan = plan
        self.delay = delay
        self.running = 0
        self.peak = 0

    async def _perform_interview_action(self, agent, prompt):
        self.running += 1
        self.peak = max(self.peak, self.running)
        try:
            what = self.plan[agent]
            if what == "hang":
                await asyncio.sleep(60)
            await asyncio.sleep(self.delay)
            if isinstance(what, Exception):
                raise what
            if isinstance(what, dict):
                return what
            return {"user_id": agent, "content": what, "success": True}
        finally:
            self.running -= 1


def _handler(tmp_path, env):
    return rps.ParallelIPCHandler(str(tmp_path), reddit_env=env, reddit_agent_graph=FakeGraph())


def _response(tmp_path, command_id):
    with open(tmp_path / "ipc_responses" / f"{command_id}.json", encoding="utf-8") as f:
        return json.load(f)


def test_hung_interview_hits_the_deadline_and_the_rest_of_the_batch_returns(tmp_path, monkeypatch):
    monkeypatch.setenv("MM_INTERVIEW_DEADLINE_S", "0.5")
    assert rps.interview_deadline_s() == 0.5
    plan = {1: "hang", **{i: f"answer {i}" for i in range(2, 8)}}
    env = FakeEnv(plan)
    handler = _handler(tmp_path, env)
    started = time.monotonic()
    assert asyncio.run(handler.handle_batch_interview(
        "cmd1", [{"agent_id": a, "prompt": "hi"} for a in plan], platform="reddit")) is True
    elapsed = time.monotonic() - started
    assert elapsed < 3                                  # the hung call was cut at the deadline, not waited out
    assert env.peak == len(plan)                        # every interview of the batch ran at the same time
    resp = _response(tmp_path, "cmd1")
    assert resp["status"] == "completed"
    results = resp["result"]["results"]
    hung = results["reddit_1"]
    assert hung["response"] is None and "timed out" in hung["error"] and hung["platform"] == "reddit"
    assert {results[f"reddit_{i}"]["response"] for i in range(2, 8)} == {f"answer {i}" for i in range(2, 8)}
    assert not any(results[f"reddit_{i}"].get("error") for i in range(2, 8))


def test_deadline_setting_falls_back_on_bad_values(monkeypatch):
    for bad in ("", "abc", "-5", "0"):
        monkeypatch.setenv("MM_INTERVIEW_DEADLINE_S", bad)
        assert rps.interview_deadline_s() == rps.DEFAULT_INTERVIEW_DEADLINE_S == 540.0
    monkeypatch.delenv("MM_INTERVIEW_DEADLINE_S")
    assert rps.interview_deadline_s() == 540.0


def _trace_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE trace (user_id INTEGER, created_at DATETIME, action TEXT, info TEXT, "
                 "PRIMARY KEY(user_id, created_at, action, info))")
    for user_id, created_at, response in rows:
        conn.execute("INSERT INTO trace (user_id, created_at, action, info) VALUES (?, ?, ?, ?)",
                     (user_id, created_at, "interview", json.dumps({"prompt": "q", "response": response})))
    conn.commit()
    conn.close()


def test_errored_interview_returns_no_answer_and_never_the_older_one(tmp_path, monkeypatch):
    monkeypatch.delenv("MM_INTERVIEW_DEADLINE_S", raising=False)
    # every person already answered once; on Twitter all interviews share the same time step
    _trace_db(tmp_path / "reddit_simulation.db", [(2, "7", "old answer of 2"), (3, "7", "old answer of 3"),
                                                  (4, "7", "z older answer of 4"), (4, "7", "a newer answer of 4")])
    plan = {2: RuntimeError("Error code: 502 - bad gateway"), 3: RuntimeError(), 4: {"user_id": 4}, 5: "fresh answer"}
    handler = _handler(tmp_path, FakeEnv(plan, delay=0.01))
    assert asyncio.run(handler.handle_batch_interview(
        "cmd2", [{"agent_id": a, "prompt": "again"} for a in plan], platform="reddit")) is True
    results = _response(tmp_path, "cmd2")["result"]["results"]
    assert results["reddit_2"] == {"agent_id": 2, "response": None, "error": "Error code: 502 - bad gateway",
                                   "platform": "reddit"}
    # an exception without a message still counts as a failure (it used to read as success)
    assert results["reddit_3"]["response"] is None and results["reddit_3"]["error"] == "RuntimeError"
    # no reply text returned by the call: the newest trace row by insertion, not an older one with the same time
    assert results["reddit_4"]["response"] == "a newer answer of 4"
    assert results["reddit_5"]["response"] == "fresh answer"      # the call's own reply


def test_single_interview_uses_the_same_deadline(tmp_path, monkeypatch):
    monkeypatch.setenv("MM_INTERVIEW_DEADLINE_S", "0.2")
    handler = _handler(tmp_path, FakeEnv({1: "hang", 2: "hello"}, delay=0.01))
    out = asyncio.run(handler._interview_single_platform(1, "hi", "reddit"))
    assert out["platform"] == "reddit" and "timed out" in out["error"]
    out = asyncio.run(handler._interview_single_platform(2, "hi", "reddit"))
    assert out["response"] == "hello" and "error" not in out
