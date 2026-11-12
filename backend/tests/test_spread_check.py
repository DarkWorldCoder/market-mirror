"""Spread check: are the simulated answers, and the gaps between audiences, as varied as the real ones?"""

import os
import random
import sys

from app.services import calibration as cal
from app.services import evidence

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "claude_cli"))
import report_view  # noqa: E402

RATES = {"students": 0.2, "parents": 0.5, "retirees": 0.8}


def _yes_no(rng, n, rates=RATES, squash=1.0):
    """Yes/no answers; squash < 1 pulls every audience's rate toward 0.5 (simulated audiences too alike)."""
    rows = []
    for _ in range(n):
        seg = rng.choice(sorted(rates))
        p = 0.5 + (rates[seg] - 0.5) * squash
        rows.append({"segment": seg, "y": 1.0 if rng.random() < p else 0.0, "weight": rng.choice([0.5, 1.0, 1.5])})
    return rows


def _three(rng, n, levels):
    return [{"segment": rng.choice(["a", "b"]), "y": rng.choice(levels)} for _ in range(n)]


def test_audiences_too_close_together_are_flagged():
    rng = random.Random(1)
    out = cal.spread_check(_yes_no(rng, 300, squash=0.2), _yes_no(rng, 150))
    aud = out["audiences"]
    assert out["verdict"] == "too alike" and out["flag"] is True
    assert aud["verdict"] == "too alike" and aud["sd_ratio"] < cal.SPREAD_LOW and aud["ratio_interval"][1] < 1
    assert aud["range_simulated"] < aud["range_real"] and {g["group"] for g in aud["groups"]} == set(RATES)
    assert out["answers"]["verdict"] == "not checked" and "yes/no" in out["answers"]["reason"]
    assert "closer together" in out["reading"] and "understated" in out["reading"]


def test_audiences_too_far_apart_are_flagged():
    rng = random.Random(2)
    wide = {"students": 0.02, "parents": 0.5, "retirees": 0.98}
    out = cal.spread_check(_yes_no(rng, 300, rates=wide), _yes_no(rng, 150))
    assert out["verdict"] == "too spread out" and out["flag"] is False and "further apart" in out["reading"]


def test_middle_heavy_answers_are_too_alike():
    rng = random.Random(3)
    real = _three(rng, 120, [0.0, 1.0, 1.0, 0.0, 0.5])            # real people mostly pick a side
    syn = _three(rng, 300, [0.5, 0.5, 0.5, 1.0, 0.0])             # simulated people mostly say maybe
    ans = cal.spread_check(syn, real)["answers"]
    assert ans["scale_simulated"] == ans["scale_real"] == "yes/maybe/no"
    assert ans["verdict"] == "too alike" and ans["sd_ratio"] < cal.SPREAD_LOW and ans["ratio_interval"][1] < 1
    assert ans["shares_simulated"]["0.5"] > 0.45 and ans["shares_real"]["0.5"] < 0.3
    assert 0 < ans["total_variation"] <= 1 and ans["wasserstein"] > 0.1
    assert "said maybe" in cal.spread_check(syn, real)["reading"]


def test_same_process_is_not_flagged():
    rng = random.Random(4)
    out = cal.spread_check(_yes_no(rng, 600), _yes_no(rng, 600))
    assert out["verdict"] in ("similar", "unclear") and not out["flag"]
    rng = random.Random(5)
    levels = [0.0, 0.5, 1.0, 1.0]
    assert cal.spread_check(_three(rng, 300, levels), _three(rng, 200, levels))["answers"]["verdict"] == "similar"


def test_not_checked_when_scales_differ_or_data_is_thin():
    rng = random.Random(6)
    syn = _three(rng, 200, [0.0, 0.5, 1.0])
    mixed = cal.spread_check(syn, _yes_no(rng, 100))
    assert mixed["answers"]["verdict"] == "not checked" and "different answer scales" in mixed["answers"]["reason"]
    thin = cal.spread_check(syn, _three(rng, 6, [0.0, 1.0]))
    assert thin["verdict"] == "not checked" and not thin["flag"] and thin["reading"].startswith("Spread not checked")
    flat_real = cal.spread_check(_yes_no(rng, 300), [{"segment": s, "y": 1.0} for s in RATES for _ in range(20)])
    assert flat_real["audiences"]["verdict"] == "unclear" and "sampling noise" in flat_real["audiences"]["reason"]


def test_helpers():
    assert cal._w1([0.0, 1.0], [1, 1], [0.0, 1.0], [1, 1]) == 0
    assert abs(cal._w1([0.0], [1], [1.0], [1]) - 1.0) < 1e-9
    assert abs(cal._w1([0.0, 1.0], [3, 1], [0.0, 1.0], [1, 3]) - 0.5) < 1e-9
    assert cal._scale([0, 1, 1]) == "yes/no" and cal._scale([0, 0.5]) == "yes/maybe/no" and cal._scale([0.3, 0.7]) == "scale"
    # two audiences 0.2 apart, each average known almost exactly: the between-audience SD is the gap's SD
    groups = [[(0.4, 1.0)] * 5000 + [(0.6, 1.0)] * 5000, [(0.6, 1.0)] * 5000 + [(0.8, 1.0)] * 5000]
    assert abs(cal._between_sd(groups) - 0.2 / 2 ** 0.5) < 0.01
    assert cal._between_sd(groups[:1]) is None


def test_diagnose_dashboard_and_evidence_carry_the_spread():
    rng = random.Random(7)
    d = cal.diagnose(_yes_no(rng, 300, squash=0.2), _yes_no(rng, 150))
    assert d["spread"]["verdict"] == "too alike"
    sec = report_view.calibration_section(d)
    assert "Answers too alike" in sec[2] and "closer together" in sec[2]
    three = {"verdict": "too alike", "reading": "r", "answers": {"shares_simulated": {"0": 0.2, "0.5": 0.6, "1": 0.2},
                                                                   "shares_real": {"0": 0.3, "0.5": 0.2, "1": 0.5}}}
    assert "maybe 60% vs 20%" in report_view._spread_html(three)
    assert report_view._spread_html(None) == ""
    survey = {"responses": [{"agent_id": i, "answer": {"would_convert": "yes"}} for i in range(60)]}
    base = {"feed_test": {"sessions": [{"agent_id": i} for i in range(60)]}, "survey": survey}
    ok = evidence.grade({**base, "calibration": {"n_real": 150, "spread": {"verdict": "similar"}}})
    alike = evidence.grade({**base, "calibration": {"n_real": 150, "spread": {"verdict": "too alike"}}})
    assert alike["points"] == ok["points"] - 1 and any("too alike" in r for r in alike["reasons"])
