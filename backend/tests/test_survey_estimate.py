"""Distribution-accurate survey: the segment-level described estimate (both verdict orders), its parsing, the blend
with SSR, the uniform-null flag, shrunk split-test lifts, per-person wording and order, and the API."""

import json
import os
import sys
from types import SimpleNamespace

from app.services import survey_estimate as se

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "claude_cli"))
import marketing  # noqa: E402


def body(reverse, pmf=(0.3, 0.3, 0.2, 0.15, 0.05)):
    levels = list(reversed(se.LEVELS)) if reverse else se.LEVELS
    vals = list(reversed(pmf)) if reverse else list(pmf)
    return json.dumps({k: dict(zip(levels, vals)) for k in se.SCALES} | {"why": "price worries"})


def test_parse_pmf_accepts_any_key_order_and_lists():
    assert se.parse_pmf({"Yes, definitely": 1, "no": 1, "MAYBE": 2, "Probably not": 0, "probably yes": 0}) == [0.25, 0, 0.5, 0, 0.25]
    assert se.parse_pmf([1, 1, 1, 1, 0]) == [0.25, 0.25, 0.25, 0.25, 0.0]
    assert se.parse_pmf({"No": 0}) is None and se.parse_pmf("x") is None and se.parse_pmf([1, 2]) is None


def test_describe_asks_both_orders_and_maps_them_back():
    prompts = []

    def complete(system, user):
        prompts.append(user)
        rev = user.index("Yes, definitely") < user.index("Probably not")
        return body(rev), {"input_tokens": 50, "output_tokens": 20}
    people = [{"age": 30, "gender": "female", "occupation": "nurse", "country": "India",
               "bde": {"background": {"who": "night-shift nurse"}, "evaluation": {"dealbreakers": ["auto-renew"]}}}] * 3
    out = se.run({"Nurses": people, "Students": people[:1]}, "Fitloop app", "sign up", complete)
    assert out["usage"]["calls"] == 4 and len(prompts) == 4
    nurses = out["by_segment"]["Nurses"]
    assert nurses["purchase"]["pmf"] == [0.3, 0.3, 0.2, 0.15, 0.05] and nurses["purchase"]["order_gap"] == 0
    assert nurses["orders"] == 2 and "night-shift nurse" in prompts[0] and "sign up" in prompts[0]


def test_failed_order_and_bad_json_leave_what_they_can():
    calls = {"n": 0}

    def complete(system, user):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("x")
        return "not json", {}
    out, usage = se.describe_segment("S", [{}], "o", "g", complete)
    assert usage["calls"] == 1 and "purchase" not in out


def test_blend_reports_gap_and_margin():
    b = se.blend([0.4, 0.3, 0.2, 0.1, 0.0], [0.2, 0.2, 0.2, 0.2, 0.2])
    assert b["methods"] == 2 and b["method_gap"] == 0.3 and b["mean_margin"] == 0.5 and b["mean"] == 2.5
    assert se.blend(None, [0, 0, 1, 0, 0])["source"] == "described" and se.blend(None, None) is None


def rows_for(seg, pmf, n=6):
    return [{"segment": seg, "ssr": {"purchase": {"pmf": pmf}}} for _ in range(n)]


def test_distribution_check_blends_and_flags_uniform_segments():
    rows = rows_for("Nurses", [0.5, 0.3, 0.1, 0.1, 0.0]) + rows_for("Students", [0.2, 0.2, 0.2, 0.2, 0.2])
    est = {"by_segment": {"Nurses": {"purchase": {"pmf": [0.3, 0.3, 0.2, 0.1, 0.1]}}}}
    dc = marketing.distribution_check(rows, est)
    nurses = next(r for r in dc["rows"] if r["segment"] == "Nurses")
    assert nurses["described_mean"] == 2.4 and nurses["method_gap"] == 0.2 and not nurses["no_better_than_uniform"]
    assert dc["uniform_segments"] == ["Students"] and dc["methods"] == 2
    assert marketing.distribution_check([], None) is None


def test_wording_and_verdict_order_vary_per_person_but_keys_do_not():
    p0 = marketing.survey_prompt("Fitloop", "sign up")
    assert p0 == marketing.survey_prompt("Fitloop", "sign up", variant=0)
    p1 = marketing.survey_prompt("Fitloop", "sign up", variant=1)
    assert "No / Probably not / Maybe / Probably yes / Yes, definitely" in p0
    assert "Yes, definitely / Probably yes / Maybe / Probably not / No" in p1
    assert "does this catch your interest?" in p1 and "are you interested in this?" in p0
    for p in (p0, p1, marketing.survey_prompt("Fitloop", "sign up", variant=2)):
        for key in ('"interest_text"', '"trust_text"', '"purchase_text"', '"recommend_text"', '"would_convert"'):
            assert key in p


def test_split_test_lifts_are_shrunk_toward_the_average():
    bundle = {"survey": {"mode": "split", "messages": ["A", "B"], "responses": [
        {"agent_id": i, "assigned_message": i % 2, "answer": {"would_convert": "yes" if i % 2 == 0 else "no"}}
        for i in range(20)]}, "config": {"persona_index": [{"agent_id": i, "segment": "S"} for i in range(20)]}}
    a = marketing.analyze(bundle)
    top, low = a["messages_ranked"]
    assert top["convert_yes"] == 100 and low["convert_yes"] == 0
    assert top["convert_yes_shrunk"] == 77.5 and low["convert_yes_shrunk"] == 22.5
    assert a["split_shrink"]["factor"] == marketing.SPLIT_SHRINK_PRIOR


class FakeLLM:
    def __init__(self):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        user = kw["messages"][1]["content"]
        rev = user.index("Yes, definitely") < user.index("Probably not")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=body(rev)), finish_reason="stop")],
                               usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))


def test_survey_estimate_api(monkeypatch):
    from app import create_app
    from app.api import market
    people = [{"agent_id": i, "segment": "Nurses" if i < 3 else "Students", "age": 30} for i in range(5)]
    monkeypatch.setattr(market, "_client", lambda: FakeLLM())
    monkeypatch.setattr(market, "_sim_dir", lambda sid: "/tmp")
    monkeypatch.setattr(market, "_people", lambda sid: (people, {}))
    app = create_app()
    app.config.update(TESTING=True)
    r = app.test_client().post("/api/simulation/survey-estimate", json={"simulation_id": "sim_x", "offer": "Fitloop", "goal": "sign up"})
    assert r.status_code == 200, r.get_json()
    d = r.get_json()["data"]
    assert set(d["by_segment"]) == {"Nurses", "Students"} and d["usage"]["calls"] == 4
    assert d["by_segment"]["Students"]["n_people"] == 2
