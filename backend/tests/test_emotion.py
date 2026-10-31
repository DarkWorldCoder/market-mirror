"""The emotion layer: traits, appraisal rules, mood decay, mild prompt wording and summary flags."""

from app.services import emotion as emo
from app.services import persona_planner


def _person(name="Asha Rao", **kw):
    p = {"name": name, "payday_status": "mid_month", "thinking_style": "pragmatic",
         "bde": {"decision_procedure": {"risk": "neutral", "speed": "considered", "patience": "medium"},
                 "background": {"acquiescence": "medium"}}}
    p.update(kw)
    return p


def test_mode_resolution():
    assert emo.mode(env={}) == "observe"
    assert emo.mode("on", env={}) == "on"
    assert emo.mode(None, env={"MM_EMOTIONS": "off"}) == "off"
    assert emo.mode(False, env={}) == "off" and emo.mode(True, env={}) == "on"
    assert emo.mode("weird", env={}) == "observe"


def test_identity_seed_matches_planner():
    for n in ("Asha Rao", "", "José Núñez"):
        assert emo.identity_seed(n, emo.EMO_SALT) == persona_planner.identity_seed(n, emo.EMO_SALT)


def test_traits_are_deterministic_bounded_and_follow_the_card():
    a, b = emo.affect_traits(_person()), emo.affect_traits(_person())
    assert a == b
    assert 0.6 <= a["reactivity"] <= 1.4 and 12 <= a["tau_h"] <= 48 and -0.3 <= a["base_v"] <= 0.4
    tight = emo.affect_traits(_person(payday_status="end_of_month_tight"))
    paid = emo.affect_traits(_person(payday_status="just_paid"))
    assert tight["base_v"] < paid["base_v"]
    averse = emo.affect_traits(_person(bde={"decision_procedure": {"risk": "averse"}}))
    seeking = emo.affect_traits(_person(bde={"decision_procedure": {"risk": "seeking"}}))
    assert averse["neg_weight"] > seeking["neg_weight"] and averse["base_d"] < seeking["base_d"]
    given = {"tau_h": 30, "base_v": 0.1}
    assert emo.affect_traits({"name": "x", "affect_traits": given}) is given


def test_normalize_feel_cleans_junk():
    assert emo.normalize_feel(None) is None and emo.normalize_feel({}) is None and emo.normalize_feel("hi") is None
    f = emo.normalize_feel({"emotion": "Annoyed", "pleasant": -3, "fair": "x", "urgent": 0.7,
                            "words": "  so   pushy " + "x" * 100})
    assert f["emotion"] == "irritation" and f["pleasant"] == -1.0 and f["fair"] == 0.0 and len(f["words"]) <= 60
    assert "emotion" not in emo.normalize_feel({"emotion": "rage-quit", "pleasant": 0.2})


def test_relevance_gate_keeps_neutral_common():
    r = emo.appraise({"pleasant": 0.1, "relevant": 0.1, "novel": 0.9})
    assert r["emotion"] == "neutral" and r["intensity"] == 0.0


def test_appraisal_rules():
    assert emo.appraise({"pleasant": -0.6, "fair": -0.7, "urgent": 0.8, "relevant": 0.7, "control": 0.2})["emotion"] == "pressured"
    assert emo.appraise({"pleasant": -0.6, "relevant": 0.7, "control": 0.8})["emotion"] == "irritation"
    assert emo.appraise({"pleasant": -0.6, "relevant": 0.7, "control": 0.1, "novel": 0.7})["emotion"] == "anxiety"
    assert emo.appraise({"pleasant": 0.7, "relevant": 0.8, "urgent": 0.8, "fair": 0.2})["emotion"] == "fomo"
    assert emo.appraise({"pleasant": 0.6, "relevant": 0.7, "fair": 0.6})["emotion"] == "trust"


def test_mismatched_label_is_overridden_and_flagged():
    r = emo.appraise({"emotion": "joy", "pleasant": -0.7, "relevant": 0.8, "control": 0.8})
    assert r["emotion"] == "irritation" and r["mismatch"] and r["by"] == "rules"
    ok = emo.appraise({"emotion": "interest", "pleasant": 0.5, "relevant": 0.7})
    assert ok["emotion"] == "interest" and not ok["mismatch"] and ok["by"] == "self_report"


def test_intensity_is_capped_even_for_reactive_people():
    r = emo.appraise({"pleasant": -1, "relevant": 1, "novel": 1, "control": 0.9},
                     {"reactivity": 1.4, "neg_weight": 0.25})
    assert r["intensity"] <= emo.MAX_INTENSITY


def test_mood_decays_to_baseline_and_brand_liking_lasts_longer():
    traits = {"base_v": 0.05, "base_a": 0.0, "base_d": 0.0, "tau_h": 24.0, "brand_tau_h": 168.0, "reactivity": 1.0}
    a = emo.new_affect(traits)
    hit = emo.appraise({"pleasant": -0.9, "relevant": 0.9, "control": 0.8})
    a = emo.update(a, hit, traits, now_h=0.0)
    assert a["v"] < 0 and a["brand_v"] < 0
    later = emo.current(a, traits, now_h=5 * 24.0)
    assert abs(later["v"] - traits["base_v"]) <= 0.01 * max(0.1, abs(a["v"] - traits["base_v"])) + 1e-3
    assert later["brand_v"] < -0.01                     # brand irritation still there after five days


def test_mood_is_capped():
    traits = {"tau_h": 24.0, "reactivity": 1.4}
    a = emo.new_affect(traits)
    for _ in range(50):
        a = emo.update(a, {"emotion": "anxiety", "intensity": 0.85, "vad": (-1, 1, -1)}, traits, now_h=0.0)
    assert all(abs(a[d]) <= emo.MOOD_CAP for d in ("v", "a", "d", "brand_v"))


def test_prompt_line_is_mild_and_silent_when_neutral():
    traits = {"tau_h": 24.0}
    assert emo.prompt_line(emo.new_affect(traits), traits, 0.0) == ""
    a = emo.update(emo.new_affect(traits), {"emotion": "irritation", "intensity": 0.8, "vad": emo.VAD["irritation"]},
                   traits, now_h=0.0, words="pushy again")
    a = emo.update(a, {"emotion": "irritation", "intensity": 0.8, "vad": emo.VAD["irritation"]}, traits, now_h=0.0,
                   words="pushy again")
    line = emo.prompt_line(a, traits, 0.0, brand="Fitloop")
    assert line and line.count("\n") <= 1 and "pushy again" in line
    assert "very" not in line.lower() and "extremely" not in line.lower()


def test_snapshot_and_sam9():
    assert emo.snapshot({}) == {}
    s = emo.snapshot({"affect": {"v": -0.4, "a": 0.5, "d": 0.1, "brand_v": -0.2, "t_h": 0, "last": None}})
    assert s["mood"].endswith("annoyed")
    assert emo.sam9(-1) == 1.0 and emo.sam9(1) == 9.0 and emo.sam9(0) == 5.0


def _doc(feelings):
    agents = {}
    for i, f in enumerate(feelings):
        agents[str(i)] = {"state": {"affect": {"v": f.get("pleasant", 0) * 0.3, "a": 0.1, "d": 0, "brand_v": 0, "t_h": 0}},
                          "memory": [{"test": "feed_test", "kind": "stopped_on_ad", "feel": f}],
                          "trajectory": [{"valence": f.get("pleasant", 0) * 0.3}]}
    return {"version": 2, "scopes": {"default": agents}}


def test_summary_flags_uniform_positive_and_caricature():
    happy = [{"emotion": "joy", "pleasant": 0.6, "intensity": 0.7, "by": "self_report"} for _ in range(20)]
    s = emo.summarize(_doc(happy))
    assert s["flags"]["uniform"] and s["flags"]["positive_skew"] and s["flags"]["caricature"]
    assert s["validated"] is False and "Simulated" in s["note"]
    mixed = ([{"emotion": "neutral", "pleasant": 0.0, "intensity": 0.0} for _ in range(12)]
             + [{"emotion": "irritation", "pleasant": -0.6, "intensity": 0.4} for _ in range(4)]
             + [{"emotion": "interest", "pleasant": 0.5, "intensity": 0.3} for _ in range(4)])
    m = emo.summarize(_doc(mixed))
    assert not m["flags"]["caricature"] and not m["flags"]["positive_skew"] and not m["flags"]["uniform"]
    assert m["emotions"]["neutral"] == 0.6 and m["by_test"]["feed_test"]["n"] == 20
    assert emo.summarize({"scopes": {}}) == {"people": 0}
