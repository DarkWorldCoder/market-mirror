"""Pause on usage limits and resume: quota.wait_if_paused and quota.guarded against a scripted gateway."""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import quota  # noqa: E402


class FakeGateway:
    def __init__(self, states):
        self.states = list(states)          # each status() call pops the next state; the last one repeats

    def __call__(self, url=None):
        return self.states.pop(0) if len(self.states) > 1 else self.states[0]


def st(paused=False, hits=0, left=0):
    return {"paused": paused, "limit_hits": hits, "resume_in_s": left, "paused_until": "12:45"}


class QuotaTests(unittest.TestCase):
    def test_no_gateway_runs_the_step_once(self):
        with patch.object(quota, "gateway_url", return_value=None):
            self.assertEqual(quota.guarded("x", lambda: 7, print), 7)

    def test_waits_while_paused(self):
        slept, logs = [], []
        with patch.object(quota, "status", FakeGateway([st(True, 1, 600), st(True, 1, 30), st()])):
            waited = quota.wait_if_paused(logs.append, "u", slept.append)
        self.assertEqual(slept, [300, 35])
        self.assertEqual(waited, 335)
        self.assertIn("paused until", logs[0])
        self.assertIn("resuming", logs[-1])

    def test_step_hit_by_a_limit_runs_again(self):
        runs, slept = [], []
        # attempt 1: before=0, limit hit during the step (after=1); attempt 2: paused, then clean (1 -> 1)
        states = [st(), st(hits=0), st(hits=1),            # wait (not paused), before, after
                  st(True, 1, 60), st(hits=1), st(hits=1), st(hits=1)]
        with patch.object(quota, "status", FakeGateway(states)):
            out = quota.guarded("the survey", lambda: runs.append(1) or len(runs), print, url="u", sleep=slept.append)
        self.assertEqual(out, 2)
        self.assertEqual(len(runs), 2)
        self.assertEqual(slept, [65])

    def test_error_without_a_limit_is_raised(self):
        def boom():
            raise RuntimeError("real bug")
        with patch.object(quota, "status", FakeGateway([st()])):
            with self.assertRaises(RuntimeError):
                quota.guarded("x", boom, print, url="u", sleep=lambda s: None)

    def test_gateway_url_from_env(self):
        with patch.dict(os.environ, {"MM_GATEWAY_URL": "", "LLM_BASE_URL": "http://127.0.0.1:5055/v1"}):
            self.assertEqual(quota.gateway_url(), "http://127.0.0.1:5055")
        with patch.dict(os.environ, {"MM_GATEWAY_URL": "", "LLM_BASE_URL": "https://api.anthropic.com/v1/"}):
            self.assertIsNone(quota.gateway_url())


if __name__ == "__main__":
    unittest.main()
