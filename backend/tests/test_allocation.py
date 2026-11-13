"""Where to collect the next real answers: allocation across segments by how much the panel helps each (#180)."""

import os
import random
import sys

from app.services import calibration as cal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "claude_cli"))
import real_check  # noqa: E402
import report_view  # noqa: E402

COUNTRY_RATE = {"IN": 0.15, "PH": 0.5, "KE": 0.85}


def _people(rng, n, segments, real):
    """'predictable': the real answer follows country, as the panel does. 'unpredictable': for real people it is a
    coin flip, so the panel's country pattern predicts nothing there."""
    rows = []
    for _ in range(n):
        seg = rng.choice(segments)
        c = rng.choice(sorted(COUNTRY_RATE))
        p = 0.5 if (real and seg == "unpredictable") else COUNTRY_RATE[c]
        rows.append({"segment": seg, "country": c, "gender": rng.choice(["f", "m"]), "age": rng.randint(18, 64),
                     "y": 1.0 if rng.random() < p else 0.0})
    return rows


def _setup(seed=1, n_real=120):
    rng = random.Random(seed)
    syn = _people(rng, 900, ["predictable", "unpredictable"], real=False)
    real = _people(rng, n_real, ["predictable", "unpredictable"], real=True)
    return syn, real


def test_more_answers_go_where_the_panel_predicts_least():
    syn, real = _setup()
    strat = cal.ppi_stratified(real, syn)
    a = cal.allocate_humans(real, syn, strat, 200)
    by = {r["stratum"]: r for r in a["by_stratum"]}
    assert sum(r["add"] for r in a["by_stratum"]) == 200 == sum(r["add_proportional"] for r in a["by_stratum"])
    assert by["predictable"]["correlation"] > by["unpredictable"]["correlation"]
    assert by["unpredictable"]["add"] > by["predictable"]["add"]
    assert a["halfwidth_planned"] <= a["halfwidth_proportional"] and a["variance_cut_pct"] >= 0
    assert a["reading"].startswith("Collect the next 200 real answers as:")


def test_thin_segments_are_topped_up_first_and_budget_is_respected():
    syn, real = _setup(seed=2)
    rng = random.Random(3)
    syn += [{**r, "segment": "new"} for r in _people(rng, 200, ["x"], real=False)]
    real += [{**r, "segment": "new"} for r in _people(rng, 3, ["x"], real=True)]
    strat = cal.ppi_stratified(real, syn)
    a = cal.allocate_humans(real, syn, strat, 5)
    by = {r["stratum"]: r for r in a["by_stratum"]}
    assert by["new"]["add"] == 5 and not by["new"]["panel_used"]            # 3 + 5 still below 10: all of it goes there
    a = cal.allocate_humans(real, syn, strat, 50)
    by = {r["stratum"]: r for r in a["by_stratum"]}
    assert by["new"]["n_after"] >= 10 and sum(r["add"] for r in a["by_stratum"]) == 50
    assert cal.allocate_humans(real, syn, strat, 0)["reading"] is None


def test_summary_dashboard_and_real_check_carry_the_plan():
    syn, real = _setup(seed=4)
    d = cal.diagnose(syn, real, budget=80)
    alloc = d["ppi"]["allocation"]
    assert alloc["extra"] == 80 and "_parts_by" not in d["ppi"]["stratified"]
    default = cal.ppi_summary(real, syn)["allocation"]                      # default budget: what the target needs
    assert default["extra"] == cal.ppi_summary(real, syn)["plan"]["more_with_panel"]
    sec = report_view.calibration_section(d)
    assert "Where to collect the next 80 real answers" in sec[2] and "If split by share" in sec[2]
    assert report_view._allocation_html(None) == "" and report_view._allocation_html({"extra": 0}) == ""
    d_default = cal.diagnose(syn, real)
    plan_n = d_default["ppi"]["plan"]["more_with_panel"]
    mk = {"has_survey": True, "overall": {"convert_yes": 40}, "by_segment": [{"key": "predictable"}, {"key": "unpredictable"}]}
    kit = real_check.build({"calibration": d_default}, mk)
    assert plan_n and kit["people_needed"] == plan_n
    assert sum(kit["audience"]["quotas"].values()) == plan_n and set(kit["audience"]["quotas"]) <= {"predictable", "unpredictable"}
    assert "as your earlier calibration planned" in kit["markdown"]
    no_plan = real_check.build({}, mk)
    assert "quotas" not in no_plan["audience"] and "as your earlier calibration planned" not in no_plan["markdown"]
