"""Real-answer budget: the split planner (interval width at each split, the 20/80 default, too few to split), the
person-level stratified split with hashed ids, and the guard that keeps persona-building answers out of the check."""

import json
import random

from app.services import calibration as cal


def answers(n, seed=3, segments=("Pro", "Free", "Team"), rows_per_person=1):
    rng = random.Random(seed)
    out = []
    for i in range(n):
        seg = segments[i % len(segments)]
        for _ in range(rows_per_person):
            out.append({"email": f"user{i}@example.com", "segment": seg, "would_convert": rng.choice(["yes", "no"])})
    return out


def test_plan_worst_case_and_default_split():
    p = cal.split_plan(200, None, 0.05)
    assert p["basis"].startswith("worst case") and p["assumptions"]["panel_correlation"] == 0
    row = next(r for r in p["table"] if r["conditioning_share"] == 0.2)
    assert (row["conditioning"], row["holdout"]) == (40, 160)
    assert row["halfwidth_alone"] == round(1.96 * (0.25 / 160) ** 0.5, 3) == row["halfwidth_with_panel"]
    rec = p["recommended"]
    assert rec["conditioning_share"] == 0.2 and "no split reaches" in rec["reason"]
    assert rec["holdout_needed"] == 385 and rec["more_real_needed"] == 282          # ceil(385 / 0.8) - 200
    widths = [r["halfwidth_alone"] for r in p["table"]]
    assert widths == sorted(widths)                                                # more to personas, wider check


def test_plan_uses_the_last_calibration_and_shrinks_the_split_when_needed():
    prior = {"correlation": 0.7, "real_only": {"se": 0.035}, "n_real": 200, "n_synthetic_effective": 400}
    p = cal.split_plan(400, prior, 0.05)
    assert p["basis"].startswith("your last calibration") and p["assumptions"]["panel_correlation"] == 0.7
    row = next(r for r in p["table"] if r["conditioning_share"] == 0.2)
    assert row["halfwidth_with_panel"] < row["halfwidth_alone"]
    assert p["recommended"]["conditioning_share"] == 0.2 and "lowest bias" in p["recommended"]["reason"]
    # a tighter target the 20% share misses but 10% meets
    tight = cal.split_plan(400, prior, 0.045)
    w = {r["conditioning_share"]: r["halfwidth_with_panel"] for r in tight["table"]}
    assert w[0.2] > 0.045 >= w[0.1] and tight["recommended"]["conditioning_share"] == 0.1


def test_too_few_answers_are_not_split():
    rec = cal.split_plan(25)["recommended"]
    assert rec["conditioning_share"] == 0.0 and rec["holdout"] == 25 and "too few to split" in rec["reason"]


def test_split_is_by_person_stratified_reproducible_and_hashed():
    rows = answers(90, rows_per_person=2)
    cond, hold, m = cal.split_rows(rows, 0.2, segment_field="segment")
    assert m["id_field"] == "email" and m["people"] == 90 and m["counts"]["conditioning"] == 18
    people = lambda part: {r["email"] for r in part}                               # noqa: E731
    assert not people(cond) & people(hold)                                         # nobody on both sides
    assert len(cond) == 36 and len(hold) == 144                                    # both rows of a person move together
    assert all(v == {"conditioning": 6, "holdout": 24} for v in m["by_segment"].values())
    again = cal.split_rows(rows, 0.2, segment_field="segment")
    assert people(again[0]) == people(cond)                                        # same seed, same people
    assert "example.com" not in json.dumps(m) and len(m["conditioning_ids"]) == 18
    assert set(m["conditioning_ids"]) == {cal.hash_id(e) for e in people(cond)}


def test_every_segment_keeps_someone_in_the_check():
    rows = [{"id": "a", "segment": "Tiny"}, {"id": "b", "segment": "Tiny"}]
    cond, hold, m = cal.split_rows(rows, 0.9, segment_field="segment")
    assert m["by_segment"]["Tiny"] == {"conditioning": 1, "holdout": 1}


def test_guard_drops_the_persona_building_side():
    rows = answers(60)
    cond, hold, m = cal.split_rows(rows, 0.2)
    kept, info = cal.holdout_guard(rows + [{"email": "", "would_convert": "yes"}], m)
    assert info["status"] == "removed" and info["removed"] == len(cond) and info["no_id"] == 1
    assert {r["email"] for r in kept if r["email"]} == {r["email"] for r in hold}
    assert cal.holdout_guard(hold, m)[1]["status"] == "clean"
    assert cal.holdout_guard(rows, None)[1]["status"] == "no split"
    no_ids = cal.split_rows([{"y": 1}, {"y": 0}], 0.5)[2]
    assert no_ids["id_field"] == "" and cal.holdout_guard(rows, no_ids)[1]["status"] == "no ids"
