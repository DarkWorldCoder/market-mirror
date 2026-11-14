"""Say vs do (stated yeses next to the say-do rules) and the A-D evidence grade, in the report and the dashboard."""

import json
import os
import random
import sys

from app.services import evidence, market_report as mr, persona_planner, pitch, say_do
from app.services import feed_test as ft

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "claude_cli"))
import report_view  # noqa: E402

CARDS = {
    1: {"agent_id": 1, "bde": {"evaluation": {"discretionary_budget_num": 10.0}}},               # $9 is 90% of budget
    2: {"agent_id": 2, "bde": {"evaluation": {"discretionary_budget_num": 100.0, "dealbreakers": ["auto-renew"]}}},
    3: {"agent_id": 3, "bde": {"evaluation": {"discretionary_budget_num": 100.0}}},
    4: {"agent_id": 4},
}


def test_parse_amount_matches_the_planner_and_prices_are_found():
    for t in ("NPR 2,000", "$120/mo", "1.5k", "", None, 30, "free", "Rs 99.50"):
        assert say_do.parse_amount(t) == persona_planner.parse_discretionary_amount(t)
    assert say_do.price_in("Pro plan, $9/month with auto-renew") == "$9"
    assert say_do.price_in("NPR 1,200 per year") == "NPR 1,200"
    assert say_do.price_in("Free forever") == ""


def test_feed_friction_is_the_shared_rule():
    person = {"bde": {"background": {"acquiescence": "high"}, "evaluation": {"discretionary_budget_num": 500.0}}}
    page = {"price": "NPR 200", "shows": "enter your card"}
    for i in range(20):
        assert ft.check_say_do_friction(person, page, random.Random(i)) == say_do.friction(person, page, random.Random(i))


def test_split_counts_each_rule_and_labels_the_assumption():
    rows = [{"agent_id": i, "stated": v} for i, v in ((1, "yes"), (2, "yes"), (3, "yes"), (4, "yes"), (5, "no"), (6, "maybe"))]
    sd = say_do.split(rows, CARDS, offer="Pro plan, $9/month with auto-renew")
    assert sd["n"] == 6 and sd["stated_yes_pct"] == 66.7 and sd["after_rules_yes_pct"] == 33.3
    assert sd["dropped"] == {"wallet_limit": 1, "dealbreaker": 1} and sd["price_used"] == "$9"
    assert sd["yes_with_a_decision_card"] == 3 and "assumption" in sd["basis"]
    assert say_do.split(rows, CARDS, offer="x") == say_do.split(rows, CARDS, offer="x")       # deterministic
    assert say_do.split([], CARDS) == {}


def test_pitch_carries_the_split():
    def batch(items):
        return {it["agent_id"]: json.dumps({"reply": "ok", "verdict": "yes", "objection_type": "none", "moved": "yes"})
                for it in items}
    ppl = [{**CARDS[i], "name": f"P{i}", "segment": "S"} for i in (1, 2, 3)]
    out = pitch.run(batch, ppl, "Pro plan, $9/month, auto-renew.", {}, emotions="off")
    assert out["say_do"]["stated_yes_pct"] == 100.0 and out["say_do"]["after_rules_yes_pct"] < 100.0


def _bundle(n=20, seeds=None, retest=None, calibration=None, providers=1):
    feed = {"sessions": [{"agent_id": i} for i in range(n)],
            "usage_by_provider": {f"p{k}": {"calls": 5} for k in range(providers)}}
    if seeds:
        feed["multi_seed"] = {"n": seeds[0], "winner_agreement": seeds[1]}
    survey = {"responses": [{"agent_id": i, "answer": {"would_convert": "yes"}} for i in range(n)], "ssr": {"used": True}}
    if retest is not None:
        survey["retest"] = {"agreement_pct": retest}
    return {"feed_test": feed, "survey": survey, **({"calibration": calibration} if calibration else {})}


def test_grades_from_sketch_to_firm():
    d = evidence.grade(_bundle(20))
    assert d["grade"] == "D" and any("only 20" in r for r in d["reasons"])
    c = evidence.grade(_bundle(60, seeds=(3, 67)))
    assert c["grade"] == "C" and c["points"] == 3
    capped = evidence.grade(_bundle(250, seeds=(3, 100), retest=80, providers=2))
    assert capped["grade"] == "B" and any("capped at B" in r for r in capped["reasons"])
    a = evidence.grade(_bundle(250, seeds=(3, 100), retest=80, calibration={"overlap": {"n": 40}}))
    assert a["grade"] == "A"
    flagged = evidence.grade(_bundle(60, seeds=(3, 67)), {"uniform": True, "caricature": True, "positive_skew": True})
    assert flagged["points"] == 1 and flagged["grade"] == "D"
    assert evidence.grade({})["grade"] == "D"


def test_report_caps_confidence_and_shows_grade_and_split():
    bundle = {**_bundle(20), "summary": {"marketing": {}}, "config": {}}
    bundle["survey"]["say_do"] = {"n": 20, "stated_yes_pct": 60.0, "after_rules_yes_pct": 35.0}
    m = mr.compact_material(bundle)
    assert m["evidence"]["grade"] == "D" and m["say_do"]["survey"]["after_rules_yes_pct"] == 35.0
    sec = {"limits": {"confidence": "high", "caveats": []}}
    mr.cap_confidence(sec, m)
    assert sec["limits"]["confidence"] == "low"
    md = mr.render_markdown({"limits": {"confidence": "high"}}, m)
    assert "Evidence grade: **D**" in md and "Model assessment: **low**" in md and "35.0% after the" in md


def test_dashboard_section():
    bundle = _bundle(60, seeds=(3, 67))
    bundle["pitch"] = {"say_do": {"n": 10, "stated_yes_pct": 70.0, "after_rules_yes_pct": 40.0, "dropped": {"wallet_limit": 3}}}
    anchor, title, html = report_view.evidence_section(bundle)
    assert anchor == "how-sure" and "Evidence C" in html and "wallet limit 3" in html and "assumption" in html
    assert report_view.evidence_section({}) is None


def _with_countries(bundle, countries, grounded=0):
    bundle["profiles_reddit"] = [{"agent_id": i, "country": c,
                                  **({"provenance": {"profile": "real_intake: reviews"}} if i < grounded else {})}
                                 for i, c in enumerate(countries)]
    return bundle


def test_market_coverage_flags_less_represented_markets():
    assert evidence.market_coverage(_bundle(10)) is None                      # no country recorded
    us = evidence.market_coverage(_with_countries(_bundle(10), ["United States"] * 8 + ["UK", "Canada"]))
    assert us["less_covered"] == 0 and not us["flagged"] and "note" not in us
    gh = evidence.market_coverage(_with_countries(_bundle(10), ["Ghana"] * 6 + ["Nigeria"] * 2 + ["USA"] * 2, grounded=3))
    assert gh["flagged"] and gh["less_covered_pct"] == 80 and gh["markets"] == ["Ghana", "Nigeria"]
    assert gh["grounded_less_covered"] == 3 and "Ghana, Nigeria" in gh["note"]
    few = evidence.market_coverage(_with_countries(_bundle(10), ["Nepal"] * 2 + ["usa"] * 8))
    assert not few["flagged"] and "20%" in few["note"]


def test_grade_drops_one_step_unless_real_answers_checked_it():
    base = evidence.grade(_bundle(60, seeds=(3, 67)))
    ghana = evidence.grade(_with_countries(_bundle(60, seeds=(3, 67)), ["Ghana"] * 60))
    assert base["grade"] == "C" and ghana["grade"] == "D"
    assert any("one grade lower" in r and "Ghana" in r for r in ghana["reasons"])
    checked = evidence.grade(_with_countries(_bundle(250, seeds=(3, 100), retest=80, calibration={"overlap": {"n": 40}}),
                                             ["Ghana"] * 250))
    assert checked["grade"] == "A"                                              # real answers already checked it
    sketch = evidence.grade(_with_countries(_bundle(20), ["Ghana"] * 20))
    assert sketch["grade"] == "D"                                               # D stays D


def test_report_and_dashboard_show_the_market_note():
    bundle = _with_countries({**_bundle(60, seeds=(3, 67)), "summary": {"marketing": {}}, "config": {}}, ["Ghana"] * 60)
    md = mr.render_markdown({"limits": {}}, mr.compact_material(bundle))
    assert "Markets: 100% of the simulated people" in md
    _, _, html = report_view.evidence_section(bundle)
    assert "Market coverage" in html and "Ghana" in html
