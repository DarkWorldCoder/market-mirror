"""Persona chat and focus group without a live simulation: rebuilt personas with their memories, private verdicts
before and after the discussion, the shift and conformity flag, checked theme quotes, picking people, the API and
the dashboard section."""

import json
import os
import sys
import threading
from types import SimpleNamespace

from app.services import focus_group as fg

PEOPLE = [{"agent_id": i, "name": f"Real Name {i}", "segment": "Nurses" if i % 2 else "Students", "age": 20 + i,
           "persona": f"Person {i} who likes walking.", "history": f"You saw the Fitloop ad {i} times.",
           "bde": {"evaluation": {"dealbreakers": ["auto-renew"], "discretionary_budget_num": 10}}} for i in range(6)]


class Script:
    """Private verdicts: Maybe before; after the discussion everyone says Probably yes (they converge)."""

    def __init__(self, converge=True):
        self.calls, self.converge, self.lock = [], converge, threading.Lock()

    def __call__(self, system, user):
        with self.lock:
            self.calls.append((system, user))
        if system == fg.THEMES_SYSTEM:
            return json.dumps({"themes": [{"title": "Price worries", "tone": "negative", "who": ["P1"],
                                           "quote": "Too pricey for a student"},
                                          {"title": "Made up", "tone": "positive", "who": ["P2"], "quote": "I never said this"}]}), {}
        if "Privately" in user:
            if "group discussion" in user and self.converge:
                return "Probably yes, everyone liked it.", {"input_tokens": 5}
            return ("Maybe, not sure." if "Person 0" in system or "Person 2" in system else
                    "No, too expensive." if "Person 1" in system else "Yes, definitely, love it."), {"input_tokens": 5}
        return "Too pricey for a student, honestly.", {"input_tokens": 5, "output_tokens": 3}


def test_rebuild_and_chat_use_card_and_memories():
    sys_prompt = fg.rebuild(PEOPLE[1])
    assert "auto-renew" in sys_prompt and "You saw the Fitloop ad 1 times." in sys_prompt
    assert "discretionary_budget_num" not in sys_prompt
    seen = []
    reply = fg.chat(PEOPLE[1], "Would you pay $9?", lambda s, u: (seen.append(u) or "Not at that price.", {}),
                    [{"role": "user", "text": "Hi"}, {"role": "person", "text": "Hello"}])
    assert reply == "Not at that price." and "Them: Hi\nYou: Hello" in seen[0] and seen[0].endswith("You:")


def test_group_private_first_then_discussion_then_private_again():
    s = Script()
    out = fg.run_group(PEOPLE[:4], ["What do you think of Fitloop?"], s, offer="Fitloop", goal="sign up", parallel=1)
    kinds = ["private" if "Privately" in u else "theme" if sy == fg.THEMES_SYSTEM else "talk" for sy, u in s.calls]
    assert kinds[:4] == ["private"] * 4 and kinds[4:8] == ["talk"] * 4 and kinds[8:12] == ["private"] * 4
    assert kinds[-1] == "theme" and out["usage"]["calls"] == 13
    talk = [u for sy, u in s.calls if "focus group" in u]
    assert "P1" in talk[1] and "Too pricey" in talk[1]                 # the second speaker heard the first
    assert all("Real Name" not in t["text"] and not t["speaker"].startswith("Real") for t in out["transcript"])
    sh = out["shift"]
    assert sh["mean_pre"] == 3.0 and sh["mean_post"] == 4.0 and sh["conformity_flag"] is True
    assert [p["pre"] for p in out["participants"]] == [3, 1, 3, 5] and all(p["post"] == 4 for p in out["participants"])
    assert [t["quote"] for t in out["themes"]] == ["Too pricey for a student", ""]   # invented quote dropped


def test_no_convergence_and_input_checks():
    out = fg.run_group(PEOPLE[:3], ["Q1", "Q2"], Script(converge=False), rounds=2, parallel=1)
    assert out["shift"]["conformity_flag"] is False and out["shift"]["changed"] == 0
    assert len([t for t in out["transcript"] if t["speaker"] == "Moderator"]) == 4
    for bad in ((PEOPLE[:1], ["q"]), (PEOPLE[:3], ["  "])):
        try:
            fg.run_group(bad[0], bad[1], Script())
        except ValueError:
            continue
        raise AssertionError(bad)


def test_pick_group_takes_turns_across_segments():
    from app.api.market import pick_group
    got = pick_group(PEOPLE, 4)
    assert [p["segment"] for p in got] == ["Nurses", "Students", "Nurses", "Students"]
    assert [p["agent_id"] for p in pick_group(PEOPLE, 6, "nurses")] == [1, 3, 5]
    assert [p["agent_id"] for p in pick_group(PEOPLE, 2, ids=[4, 0])] == [0, 4]


class FakeLLM:
    def __init__(self):
        self.s = Script()
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        text, _ = self.s(kw["messages"][0]["content"], kw["messages"][1]["content"])
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason="stop")],
                               usage=SimpleNamespace(prompt_tokens=4, completion_tokens=2))


def test_api_ask_and_focus_group(monkeypatch, tmp_path):
    from app import create_app
    from app.api import market
    monkeypatch.setattr(market, "_client", lambda: FakeLLM())
    monkeypatch.setattr(market, "_sim_dir", lambda sid: str(tmp_path))
    monkeypatch.setattr(market, "_people", lambda sid: ([dict(p) for p in PEOPLE], {}))
    ran = {}

    def start(kind, sid, work, memory_scope=""):
        ran["result"] = work(lambda d, t: None)
        return "task_1"
    monkeypatch.setattr(market, "_start", start)
    app = create_app()
    app.config.update(TESTING=True)
    c = app.test_client()
    r = c.post("/api/simulation/ask", json={"simulation_id": "s", "agent_id": 1, "message": "Would you pay?"})
    assert r.status_code == 200 and "pricey" in r.get_json()["data"]["reply"]
    assert c.post("/api/simulation/ask", json={"simulation_id": "s", "agent_id": 99, "message": "x"}).status_code == 404
    assert c.post("/api/simulation/focus-group", json={"simulation_id": "s", "guide": []}).status_code == 400
    r = c.post("/api/simulation/focus-group", json={"simulation_id": "s", "guide": "What do you think?\nWould you pay?",
                                                    "people": 3, "memory_scope": "off"})
    d = r.get_json()["data"]
    assert r.status_code == 200 and d["people"] == 3 and d["questions"] == 2
    assert len(ran["result"]["participants"]) == 3


def test_dashboard_section():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "claude_cli"))
    import report_view
    out = fg.run_group(PEOPLE[:4], ["What do you think?"], Script(), parallel=1)
    sec = report_view.focus_group_section(out)
    assert sec[0] == "focusgroup" and "converged" in sec[2] and "Price worries" in sec[2] and "Transcript" in sec[2]
    assert "Real Name" not in sec[2]
    assert report_view.focus_group_section({}) is None
