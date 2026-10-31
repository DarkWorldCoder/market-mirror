"""PPI++ in calibrate: coverage on a known truth, the fallback to real-only when the panel is noise, effective
sample size, the sample planner, strata, the API block and the dashboard section."""

import random
import sys
import os

from app.services import calibration as cal

CELLS = [("A", "female", 0.30), ("A", "male", 0.20), ("B", "female", 0.60), ("B", "male", 0.45)]
MIX = [0.25, 0.25, 0.30, 0.20]                                 # the audience's composition
TRUTH = sum(m * p for m, (_, _, p) in zip(MIX, CELLS))


def draw(rng, n, bias=lambda p: p, noise=False):
    rows = []
    for _ in range(n):
        seg, g, p = rng.choices(CELLS, MIX)[0]
        q = rng.random() if noise else bias(p)
        rows.append({"segment": seg, "gender": g, "country": "US", "age": 30, "y": 1.0 if rng.random() < q else 0.0})
    return rows


def test_interval_covers_the_truth_even_with_a_biased_panel():
    rng = random.Random(3)
    hits = narrower = 0
    reps = 200
    for _ in range(reps):
        syn = draw(rng, 400, bias=lambda p: 0.6 * p + 0.25)     # the panel is off in level but tracks the cells
        real = draw(rng, 80)
        r = cal.ppi_mean(real, syn)
        hits += r["ci"][0] <= TRUTH <= r["ci"][1]
        narrower += r["se"] <= r["real_only"]["se"] + 1e-9
    assert hits / reps >= 0.9                                    # nominal 95%, small-sample slack
    assert narrower / reps >= 0.6


def test_noise_panel_falls_back_to_real_only():
    rng = random.Random(5)
    r = cal.ppi_mean(draw(rng, 80), draw(rng, 400, noise=True))
    assert abs(r["se"] - r["real_only"]["se"]) < 0.02          # lambda is noisy here, but it moves nothing
    assert abs(r["estimate"] - r["real_only"]["estimate"]) < 0.03
    assert r["worth_extra_real"] < 25


def test_better_panel_is_worth_more_real_answers():
    rng = random.Random(9)
    real = draw(rng, 100)
    good = cal.ppi_mean(real, draw(rng, 800))
    weak = cal.ppi_mean(real, draw(rng, 800, bias=lambda p: 0.5 + 0.1 * (p - 0.4)))
    assert good["effective_n"] > weak["effective_n"] >= 0
    assert good["correlation"] > 0


def test_plan_needs_more_answers_for_a_tighter_interval():
    rng = random.Random(11)
    r = cal.ppi_mean(draw(rng, 60), draw(rng, 500))
    wide, tight = cal.plan_humans(r, 0.08), cal.plan_humans(r, 0.03)
    assert tight["real_needed_with_panel"] > wide["real_needed_with_panel"]
    assert tight["real_needed_alone"] >= tight["real_needed_with_panel"]
    assert tight["more_alone"] >= tight["more_with_panel"] >= 0
    assert cal.plan_humans({"estimate": None, "reason": "x"})["reason"] == "x"


def test_too_few_answers_and_strata():
    rng = random.Random(2)
    assert cal.ppi_mean(draw(rng, 5), draw(rng, 100))["estimate"] is None
    real = [r for r in draw(rng, 120) if r["segment"] == "A"][:40] + [r for r in draw(rng, 40) if r["segment"] == "B"][:4]
    st = cal.ppi_stratified(real, draw(rng, 400))
    assert set(st["by_stratum"]) == {"A"} and st["skipped"][0]["stratum"] == "B"
    assert 0 < st["audience_covered"] < 1 and st["ci"][0] <= st["estimate"] <= st["ci"][1]


def test_diagnose_carries_the_ppi_block_and_reading():
    rng = random.Random(4)
    out = cal.diagnose(draw(rng, 300), draw(rng, 60), halfwidth=0.04)
    ppi = out["ppi"]
    assert ppi["overall"]["estimate"] is not None and "_parts" not in ppi["overall"]
    assert ppi["plan"]["halfwidth"] == 0.04 and "real answers" in ppi["reading"]
    assert "random sample" in ppi["assumption"]


def test_calibrate_api_and_dashboard_section(monkeypatch, tmp_path):
    from app import create_app
    from app.services import predict
    monkeypatch.setattr(predict, "STORE", str(tmp_path / "store.json"))
    app = create_app()
    app.config.update(TESTING=True)
    rng = random.Random(8)
    r = app.test_client().post("/api/simulation/calibrate", json={"synthetic": draw(rng, 300), "real": draw(rng, 60),
                                                                 "halfwidth": 0.06})
    d = r.get_json()["data"]
    assert r.status_code == 200 and d["ppi"]["plan"]["halfwidth"] == 0.06
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "claude_cli"))
    import report_view
    sec = report_view.calibration_section(d)
    assert sec[0] == "calibration" and "PPI++" in sec[2] and "Panel worth" in sec[2] and "±6 points" in sec[2]
    assert report_view.calibration_section({}) is None
