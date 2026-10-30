"""MaxDiff, choice-based conjoint and Gabor-Granger: designs, the analysis (known part-worths recovered), fake
simulated people end to end, the API, the experiment types and the dashboard section."""

import json
import math
import os
import random
import re
import sys
from collections import Counter
from types import SimpleNamespace

from app.services import choice_methods as cm

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "claude_cli"))
import experiments  # noqa: E402
import report_view  # noqa: E402

ITEMS = ["Free trial", "No auto-renew", "7-minute workouts", "Coach chat", "Offline mode", "Family plan"]
ATTRS = {"price": ["$5", "$9", "$15"], "length": ["7 min", "20 min"], "coach": ["none", "chat"]}
PEOPLE = [{"agent_id": i, "name": f"P{i}", "segment": "Nurses" if i % 2 else "Students", "persona": "busy"} for i in range(12)]


def test_maxdiff_design_is_balanced():
    d = cm.maxdiff_design(ITEMS, 4)
    counts = Counter(i for s in d for i in s)
    assert all(len(set(s)) == len(s) == 4 for s in d)
    assert max(counts.values()) - min(counts.values()) <= 1 and set(counts) == set(range(6))
    try:
        cm.maxdiff_design(["a", "b"])
        raise AssertionError
    except ValueError:
        pass


def test_cbc_design_and_mnl_recover_known_part_worths():
    rng = random.Random(1)
    true = {"price": {"$5": 0.0, "$9": -0.8, "$15": -1.8}, "length": {"7 min": 0.0, "20 min": -0.6},
            "coach": {"none": 0.0, "chat": 0.9}}
    obs = []
    for s in range(150):
        for task in cm.cbc_design(ATTRS, tasks=8, alts=3, seed=s):
            us = [sum(true[a][p[a]] for a in ATTRS) + rng.gauss(0, 0) for p in task] + [-1.0]
            es = [math.exp(u) for u in us]
            r, acc = rng.random() * sum(es), 0.0
            for k, e in enumerate(es):
                acc += e
                if r <= acc:
                    break
            obs.append((task, k if k < len(task) else None))
    fit = cm.mnl_fit(obs, ATTRS, steps=600)
    pw = fit["part_worths"]
    assert abs(pw["price"]["$15"] - (-1.8)) < 0.35 and abs(pw["coach"]["chat"] - 0.9) < 0.3
    assert list(fit["importance"])[0] == "price"
    wtp = cm.wtp_direction(fit, "price")
    assert wtp["sign_ok"] and 3 < wtp["levels"]["coach"]["chat"] < 8          # true value ~ 0.9 / 0.18 = 5
    assert cm.wtp_direction(fit, "nope") is None


def test_gabor_granger_curve_and_inconsistency():
    prices = ["$5", "$9", "$15"]
    curve = cm.gg_curve(prices, [[True, True, False], [True, False, False], [True, True, True], [False, True, False]])
    shares = [r["share_buy"] for r in curve["curve"]]
    assert shares == [0.75, 0.75, 0.25] and curve["revenue_max_price"] == "$9" and curve["inconsistent_people"] == 1


def fake_answers(system, user):
    if "matters MOST" in user:
        sets = re.findall(r"^Set \d+: (.*)$", user, re.M)
        out = []
        for s in sets:
            opts = [o.split(") ", 1)[1] for o in s.split(" | ")]
            most = next((k for k, o in enumerate(opts) if o == "No auto-renew"), 0)
            least = next((k for k, o in enumerate(opts) if o == "Family plan"), len(opts) - 1 if most != len(opts) - 1 else 0)
            out.append({"most": most + 1, "least": least + 1})
        return json.dumps({"sets": out}), {"input_tokens": 50}
    if "Task 1" in user:
        tasks = re.split(r"^Task \d+:$", user, flags=re.M)[1:]
        ch = []
        for t in tasks:
            opts = re.findall(r"Option (\d+): (.*)", t)
            best = min(opts, key=lambda o: ("$15" in o[1], "$9" in o[1], "none" in o[1]))
            ch.append(int(best[0]))
        return json.dumps({"choices": ch}), {}
    lines = re.findall(r"^\d+\) (.*)$", user, re.M)
    return json.dumps({"buy": [l != "$15" for l in lines]}), {}


def test_run_all_three_on_fake_people():
    md = cm.run("maxdiff", PEOPLE, {"items": ITEMS, "topic": "Fitloop"}, fake_answers)
    assert md["answered"] == 12 and md["ranking"][0]["item"] == "No auto-renew" and md["ranking"][-1]["item"] == "Family plan"
    assert md["ranking"][0]["ci"][0] > 0 and set(md["by_segment"]) == {"Nurses", "Students"}
    cj = cm.run("conjoint", PEOPLE, {"attributes": ATTRS, "price_attribute": "price", "held_fixed": "same app"}, fake_answers)
    assert cj["answered"] == 12 and list(cj["fit"]["importance"])[0] == "price" and cj["wtp"]["sign_ok"]
    gg = cm.run("gabor_granger", PEOPLE, {"prices": ["$5", "$9", "$15"]}, fake_answers)
    assert [r["share_buy"] for r in gg["curve"]] == [1.0, 1.0, 0.0] and gg["revenue_max_price"] == "$9"
    try:
        cm.run("nope", PEOPLE, {}, fake_answers)
        raise AssertionError
    except ValueError:
        pass


def test_experiment_rows_and_types():
    assert experiments.normalize({"type": "maxdiff", "variants": ITEMS})["metric"] == "best_minus_worst"
    assert experiments.normalize({"type": "gabor_granger", "variants": ["$5", "$9", "$15"]})["metric"] == "share_buy"
    md = cm.run("maxdiff", PEOPLE, {"items": ITEMS}, fake_answers)
    rows = experiments.from_choice("maxdiff", md)
    assert rows[0]["label"] == "No auto-renew" and rows[0]["value"] > 0 and rows[0]["margin"] is not None
    gg = experiments.from_choice("gabor_granger", cm.run("gabor_granger", PEOPLE, {"prices": ["$5", "$9", "$15"]}, fake_answers))
    assert [r["value"] for r in gg] == [100.0, 100.0, 0.0]


def test_experiment_run_dispatches_to_the_choice_engine(tmp_path):
    seen = {}

    def choice(c, sid, kind, spec, run_dir, log):
        seen.update(kind=kind, spec=spec)
        with open(os.path.join(run_dir, f"choice_{kind}.json"), "w") as f:
            json.dump(cm.run(kind, PEOPLE, spec, fake_answers), f)
    exp = experiments.normalize({"type": "conjoint", "attributes": ATTRS, "price_attribute": "price", "offer": "Fitloop"})
    res = experiments.run(None, exp, "sim_x", str(tmp_path), lambda m: None, {"choice": choice})
    assert seen["kind"] == "conjoint" and seen["spec"]["topic"] == "Fitloop" and res["winner"] == "price"


class FakeLLM:
    def __init__(self):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        text, _ = fake_answers(kw["messages"][0]["content"], kw["messages"][1]["content"])
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason="stop")],
                               usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))


def test_api_and_dashboard(monkeypatch, tmp_path):
    from app import create_app
    from app.api import market
    monkeypatch.setattr(market, "_client", lambda: FakeLLM())
    monkeypatch.setattr(market, "_sim_dir", lambda sid: str(tmp_path))
    monkeypatch.setattr(market, "_people", lambda sid: ([dict(p) for p in PEOPLE], {}))
    ran = {}
    monkeypatch.setattr(market, "_start", lambda kind, sid, work, memory_scope="": ran.setdefault("r", work(lambda d, t: None)) and "t1")
    app = create_app()
    app.config.update(TESTING=True)
    c = app.test_client()
    assert c.post("/api/simulation/choice-test", json={"simulation_id": "s", "kind": "nope"}).status_code == 400
    assert c.post("/api/simulation/choice-test", json={"simulation_id": "s", "kind": "maxdiff", "spec": {"items": ["a"]}}).status_code == 400
    r = c.post("/api/simulation/choice-test", json={"simulation_id": "s", "kind": "maxdiff", "segment": "nurses",
                                                    "spec": {"items": ITEMS}})
    assert r.status_code == 200 and r.get_json()["data"]["people"] == 6 and ran["r"]["answered"] == 6
    bundle = {"choice_maxdiff": ran["r"],
              "choice_conjoint": cm.run("conjoint", PEOPLE, {"attributes": ATTRS, "price_attribute": "price"}, fake_answers),
              "choice_gabor_granger": cm.run("gabor_granger", PEOPLE, {"prices": ["$5", "$9", "$15"]}, fake_answers)}
    sec = report_view.choice_section(bundle)
    assert sec[0] == "choice" and "No auto-renew" in sec[2] and "Part-worths" in sec[2] and "Highest revenue" in sec[2]
    assert report_view.choice_section({}) is None
