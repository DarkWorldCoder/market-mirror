"""Bring-your-own questionnaire: parsing, per-person option order, strict reading, summaries, flags and the API."""

import json
import threading
from types import SimpleNamespace

import pytest

from app.services import questionnaire as qn

PEOPLE = [{"agent_id": i, "name": f"Person {i}", "segment": "Nurses" if i % 2 else "Students", "country": "Nepal",
           "persona": f"Person {i} who likes walking."} for i in range(6)]

SPEC = {"title": "Brand tracker", "questions": [
    {"id": "aware", "text": "Have you heard of Fitloop?", "type": "choice", "options": ["Yes", "No", "Not sure"]},
    {"id": "trust", "text": "How much do you trust Fitloop?", "type": "scale", "low": 1, "high": 5},
    {"id": "nps", "text": "How likely are you to recommend Fitloop?", "type": "nps"},
    {"id": "seen", "text": "Where have you seen it?", "type": "multi", "options": ["Instagram", "TV", "A friend"]},
    {"id": "why", "text": "Why?", "type": "open"}]}


class Panel:
    """Odd people trust 4 and say Yes; even people trust 2 and say No. Person 5 gives invalid values."""

    def __init__(self):
        self.calls, self.lock = [], threading.Lock()

    def __call__(self, system, user):
        with self.lock:
            self.calls.append((system, user))
        i = int(system.split("Person ")[1].split()[0])
        if i == 5:
            return json.dumps({"answers": {"aware": "Maybe", "trust": 9, "nps": 7.5, "seen": ["Radio"], "why": ""}}), {}
        return json.dumps({"answers": {"aware": "Yes" if i % 2 else "no", "trust": 4 if i % 2 else 2,
                                       "nps": 10 if i % 2 else 3, "seen": ["Instagram"] if i % 2 else [],
                                       "why": f"Reason {i}", "q1": 3}}), {"input_tokens": 10, "output_tokens": 5}


def test_lines_parse_into_typed_questions():
    spec = qn.normalize("# Brand tracker\n1. How much do you trust us? [1-7]\n- Heard of us? {Yes | No}\n"
                        "Where? {Instagram | TV}+\nRecommend us? [nps]\n3 things you would change?")
    kinds = [(q["type"], q.get("high"), q.get("options")) for q in spec["questions"]]
    assert kinds == [("scale", 7, None), ("choice", None, ["Yes", "No"]), ("multi", None, ["Instagram", "TV"]),
                     ("nps", 10, None), ("open", None, None)]
    assert spec["questions"][4]["text"] == "3 things you would change?"     # a leading number in the text is kept


@pytest.mark.parametrize("bad", [[], [{"text": ""}], [{"text": "x", "type": "slider"}],
                                 [{"text": "x", "type": "choice", "options": ["only"]}],
                                 [{"text": "x", "type": "scale", "low": 5, "high": 1}],
                                 [{"id": "a", "text": "x"}, {"id": "a", "text": "y"}]])
def test_bad_specs_are_refused(bad):
    with pytest.raises(ValueError):
        qn.normalize(bad)


def test_option_order_is_shuffled_per_person_and_stable():
    q = {"id": "brand", "options": [f"Brand {k}" for k in range(6)]}
    orders = {tuple(qn.option_order(q, i, 7)) for i in range(10)}
    assert len(orders) > 1 and qn.option_order(q, 3, 7) == qn.option_order(q, 3, 7)
    assert sorted(qn.option_order(q, 3, 7)) == sorted(q["options"])


def test_invalid_answers_are_missing_never_coerced():
    spec = qn.normalize(SPEC)
    got = qn.read('{"answers": {"aware": "\\"YES\\"", "trust": 6, "nps": true, "seen": ["TV", "Radio"], "why": " ok "}}', spec)
    assert got == {"aware": "Yes", "trust": None, "nps": None, "seen": None, "why": "ok"}
    assert all(v is None for v in qn.read("not json", spec).values())


def test_run_summarises_by_segment_with_flags():
    panel = Panel()
    out = qn.run(PEOPLE, SPEC, panel, parallel=2)
    assert out["people"] == 6 and out["answered"] == 5 and out["usage"]["calls"] == 6
    q = {x["id"]: x for x in out["questions"]}
    assert q["trust"]["all"]["n"] == 5 and q["trust"]["all"]["missing"] == 1          # person 5 gave 9 on a 1-5 scale
    assert q["trust"]["by_segment"]["Students"]["mean"] == 2.0 and q["trust"]["by_segment"]["Nurses"]["mean"] == 4.0
    assert q["nps"]["all"]["nps"] == round(100 * (2 - 3) / 5)                          # 7.5 is not a whole number
    assert q["aware"]["all"]["distribution"] == {"Yes": 2, "No": 3, "Not sure": 0}
    assert q["seen"]["all"]["distribution"]["Instagram"] == 2 and q["seen"]["all"]["missing"] == 1
    assert [x["text"] for x in q["why"]["all"]["quotes"]] == [f"Reason {i}" for i in range(5)]
    assert out["rows"][0]["order"]["aware"] and "Person 0" in panel.calls[0][0]
    assert out["csv_rows"][1] == {"respondent": "sim_1", "segment": "Nurses", "country": "Nepal", "aware": "Yes",
                                  "trust": 4, "nps": 10, "seen": "Instagram", "why": "Reason 1"}
    assert "Brand tracker" in out["markdown"] and "NPS" in out["markdown"]


def test_too_alike_and_position_bias_are_flagged():
    people = [{"agent_id": i, "persona": f"Person {i}", "segment": "All"} for i in range(30)]
    spec = {"questions": [{"id": "pick", "text": "Pick one", "type": "choice", "options": ["A", "B", "C", "D"]},
                          {"id": "score", "text": "Score", "type": "scale"}]}

    def first_shown(system, user):
        first = user.split("Options: ")[1].split(" | ")[0]
        return json.dumps({"answers": {"pick": first, "score": 4}}), {}
    out = qn.run(people, spec, first_shown, parallel=4)
    assert out["position_check"]["first_shown_share"] == 1.0 and out["position_check"]["flag"]
    assert out["too_alike"] == ["score"] or set(out["too_alike"]) == {"pick", "score"}
    assert "too alike" in out["markdown"] and "Position check" in out["markdown"]


def test_no_usable_answers_raises():
    with pytest.raises(RuntimeError):
        qn.run(PEOPLE[:2], SPEC, lambda s, u: ("sorry", {}), parallel=1)


class FakeLLM:
    def __init__(self):
        self.panel = Panel()
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        text, _ = self.panel(kw["messages"][0]["content"], kw["messages"][1]["content"])
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason="stop")],
                               usage=SimpleNamespace(prompt_tokens=4, completion_tokens=2))


def test_api(monkeypatch, tmp_path):
    from app import create_app
    from app.api import market
    monkeypatch.setattr(market, "_client", lambda: FakeLLM())
    monkeypatch.setattr(market, "_sim_dir", lambda sid: str(tmp_path))
    monkeypatch.setattr(market, "_people", lambda sid: ([dict(p) for p in PEOPLE], {}))
    ran = {}

    def start(kind, sid, work, memory_scope=""):
        ran["kind"], ran["result"] = kind, work(lambda d, t: None)
        return "task_1"
    monkeypatch.setattr(market, "_start", start)
    app = create_app()
    app.config.update(TESTING=True)
    c = app.test_client()
    assert c.post("/api/simulation/questionnaire", json={"simulation_id": "s", "questions": []}).status_code == 400
    r = c.post("/api/simulation/questionnaire", json={"simulation_id": "s", "questions": SPEC["questions"],
                                                      "segment": "Nurses", "memory_scope": "off"})
    d = r.get_json()["data"]
    assert r.status_code == 200 and d["people"] == 3 and d["questions"] == 5
    assert ran["kind"] == "questionnaire" and ran["result"]["segments"] == ["Nurses"]
    r = c.post("/api/simulation/questionnaire", json={"simulation_id": "s", "questions": "Trust us? [1-5]", "people": 2,
                                                      "memory_scope": "off"})
    assert r.get_json()["data"]["people"] == 2 and market.RESULT_FILES["questionnaire"] == "questionnaire.json"
