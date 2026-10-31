"""Emotion layer, part 2: bounded couplings (mode "on" only, same random draws), OASIS round mood, actions keeping
thought and mood, affective SSR, the focus group's private vs in-the-room feelings, and the dashboard table."""

import importlib.util as _ilu
import os as _os
import random

from app.services import emotion as emo
from app.services import email_test as et
from app.services import feed_test as ft
from app.services import focus_group, ssr
from app.services.simulation_runner import AgentAction

_HERE = _os.path.dirname(_os.path.abspath(__file__))


def _load(name, rel):
    spec = _ilu.spec_from_file_location(name, _os.path.join(_HERE, rel))
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_feed = _load("_feed_fakes2", "test_feed_test.py")
_ssr_t = _load("_ssr_fakes", "test_ssr.py")
_email_t = _load("_email_fakes", "test_email_test.py")
_ctx = _load("_agent_context", _os.path.join("..", "scripts", "agent_context.py"))

ANNOYED = {"v": -0.5, "a": 0.4, "d": -0.2, "brand_v": -0.5, "last_emotion": "irritation", "last_intensity": 0.6}
WARM = {"v": 0.5, "a": 0.3, "d": 0.3, "brand_v": 0.5, "last_emotion": "trust", "last_intensity": 0.6}


def test_weights_parse_and_cap():
    assert emo.weights(env={}) == {k: 1.0 for k in emo.COUPLING}
    w = emo.weights(env={"MM_EMOTION_WEIGHT": "0.5,notice=0,wallet=9,bogus=1,patience=x"})
    assert w["notice"] == 0.0 and w["wallet"] == 2.0 and w["email_open"] == 0.5 and w["patience"] == 0.5
    assert emo.weights(0.3, env={})["actions"] == 0.3


def test_multipliers_are_bounded_and_one_unless_on():
    extremes = [ANNOYED, WARM, {k: 0.8 for k in ("v", "a", "d", "brand_v")} | {"last_emotion": "fomo", "last_intensity": 0.85},
                {k: -0.8 for k in ("v", "a", "d", "brand_v")} | {"last_emotion": "regret", "last_intensity": 0.85}]
    for snap in extremes:
        fx = emo.effects(snap, "on", {k: 2.0 for k in emo.COUPLING})
        for k, v in fx.items():
            assert emo.COUPLING[k]["lo"] <= v <= emo.COUPLING[k]["hi"], (k, v)
    assert set(emo.effects(ANNOYED, "observe").values()) == {1.0}
    assert set(emo.effects(ANNOYED, "off").values()) == {1.0}
    assert set(emo.effects({}, "on").values()) == {1.0}
    assert set(emo.effects(ANNOYED, "on", {k: 0.0 for k in emo.COUPLING}).values()) == {1.0}
    on = emo.effects(ANNOYED, "on")
    assert on["notice"] < 1 and on["wear_out"] > 1 and on["email_open"] < 1 and on["patience"] < 1
    warm = emo.effects(WARM, "on")
    assert warm["email_open"] > 1 and warm["wallet"] > 1 and warm["backout"] < 1
    assert emo.applied(on, "notice") == {"notice": on["notice"]} and emo.applied({"notice": 1.0}) == {}


def test_at_next_test_fades_the_mood():
    traits = {"tau_h": 24.0, "brand_tau_h": 168.0}
    state = {"affect": {"v": -0.6, "a": 0.5, "d": 0.0, "brand_v": -0.4, "t_h": 10.0, "last": None}}
    now = emo.at_next_test(state, traits)
    assert -0.6 < now["v"] < -0.1 and now["brand_v"] < -0.3          # mood fades within a day, brand dislike lasts
    assert emo.at_next_test({}, traits) == {} and emo.at_next_test({"affect": "x"}, traits) == {}


def _feed_run(mode, affect=None):
    ppl = _feed.people(12)
    if affect:
        ppl = [{**p, "affect_now": affect} for p in ppl]
    return ft.run_feed_test(_feed.FakeLLM(), "m", ft.normalize_creatives(_feed.CREATIVES), ppl, waves=2, parallel=4,
                            exposures=3, attention_gate=True, seed=9, emotions=mode)


def test_feed_couplings_keep_the_random_draws_and_only_lower_notice_for_an_annoyed_crowd():
    obs, on, on_plain = _feed_run("observe", ANNOYED), _feed_run("on", ANNOYED), _feed_run("on")
    key = lambda r: {(s["agent_id"], s["creative_id"], s["exposure"]): (s["hour"], s["ad"]["noticed"]) for s in r["sessions"]}
    k_obs, k_on, k_plain = key(obs), key(on), key(on_plain)
    assert k_obs.keys() == k_on.keys() == k_plain.keys()
    assert all(k_obs[k][0] == k_on[k][0] for k in k_obs)            # same hours: same random stream
    assert all(k_plain[k] == k_obs[k] for k in k_obs)               # "on" without a stored mood changes nothing
    assert all(k_obs[k][1] or not k_on[k][1] for k in k_obs)        # lower notice odds: never noticed where observe did not
    assert sum(v[1] for v in k_on.values()) <= sum(v[1] for v in k_obs.values())
    assert all(s.get("emotion_effects", {}).get("notice", 1) < 1 for s in on["sessions"])
    assert not any(s.get("emotion_effects") for s in obs["sessions"])
    assert on["emotion"]["mode"] == "on" and on["emotion"]["rows_moved"] == len(on["sessions"]) and "weights" in on["emotion"]
    assert "weights" not in obs["emotion"]


def test_wallet_and_backout_couplings_move_the_friction_gate():
    person = {"agent_id": 1, "name": "R", "bde": {"evaluation": {"discretionary_budget_num": 1000.0}}}
    page = {"price": "NPR 850", "shows": "Pro plan"}                  # ratio 0.85 > 0.80 threshold
    assert ft.check_say_do_friction(person, page, random.Random(1))[0] == "wallet_limit"
    assert ft.check_say_do_friction(person, page, random.Random(1), {"wallet": 1.1}) is None    # confident: spends a bit more
    polite = {"agent_id": 2, "name": "S", "bde": {"background": {"acquiescence": "high"}}}
    card = {"price": "free", "shows": "enter your card"}
    draws = [random.Random(i).random() for i in range(200)]
    i = next(i for i, u in enumerate(draws) if 0.45 <= u < 0.45 * 1.3)
    assert ft.check_say_do_friction(polite, card, random.Random(i)) is None
    assert ft.check_say_do_friction(polite, card, random.Random(i), {"backout": 1.3})[0] == "say_vs_do_gap"


def test_email_open_coupling_is_logged_and_bounded():
    emails, opts = et.normalize_emails(_email_t.EMAILS)
    ppl = [{**p, "affect_now": WARM} for p in _email_t.PEOPLE]
    on = et.run_email_test(_email_t.FakeClient(), "m", emails, ppl, seed=3, parallel=2, emotions="on")
    obs = et.run_email_test(_email_t.FakeClient(), "m", emails, ppl, seed=3, parallel=2, emotions="observe")
    p_on = {(r["agent_id"], r["step"]): r["p_open"] for r in on["sessions"]}
    p_obs = {(r["agent_id"], r["step"]): r["p_open"] for r in obs["sessions"]}
    assert all(p_on[k] >= p_obs[k] for k in p_obs) and any(p_on[k] > p_obs[k] for k in p_obs)
    assert all(0.02 <= v <= 0.9 for v in p_on.values())
    assert all(r.get("emotion_effects", {}).get("email_open", 1) > 1 for r in on["sessions"])
    assert not any(r.get("emotion_effects") for r in obs["sessions"])


def test_oasis_round_mood_comes_from_affect_with_the_same_draws():
    bstate = {"fatigue": 0.1, "trust": 0.5, "affect": {"v": -0.6, "a": 0.6, "d": 0.3, "brand_v": -0.3, "t_h": 0, "last": None},
              "_affect_traits": {"tau_h": 48.0, "base_v": 0, "base_a": 0, "base_d": 0}}
    r_off, r_on = random.Random(4), random.Random(4)
    b_off, m_off = _ctx.round_flavour(1, 1, 20, r_off, {1: 0.8}, bstate=bstate, emotions="observe")
    b_on, m_on = _ctx.round_flavour(1, 1, 20, r_on, {1: 0.8}, bstate=bstate, emotions="on")
    assert r_off.random() == r_on.random()                           # the stream stays aligned
    assert m_on.endswith("annoyed") and m_off in _ctx.MOODS
    assert 1 <= b_on <= 3
    night_off = _ctx.round_flavour(1, 1, 3, random.Random(4), bstate=bstate, emotions="on")[1]
    assert night_off in ("tired", "can't sleep", "bored")              # small hours stay small hours


def test_agent_actions_keep_thought_and_mood():
    a = AgentAction(1, "t", "twitter", 3, "A", "CREATE_POST", {}, thought="too pushy", mood="a little annoyed")
    assert a.to_dict()["thought"] == "too pushy" and a.to_dict()["mood"] == "a little annoyed"
    assert "thought" not in AgentAction(1, "t", "twitter", 3, "A", "LIKE_POST").to_dict()


def test_affective_ssr_and_words_check():
    e = _ssr_t.FakeEmbedder()                       # bag of words: phrases that echo the scale's ends
    good, bad = "I love this, delighted, really good.", "I hate this, upset, awful."
    r = ssr.rate_affect([good, bad], ("valence", "arousal"), embedder=e)
    assert r[0]["valence"]["signed"] > 0 > r[1]["valence"]["signed"] and "arousal" in r[0]
    agree = ssr.affect_agreement([(0.7, good)] * 6 + [(-0.7, bad)] * 6, embedder=e)
    assert agree["n"] == 12 and agree["sign_agreement"] == 1.0 and not agree["low_agreement_flag"]
    flip = ssr.affect_agreement([(-0.7, good)] * 6 + [(0.7, bad)] * 6, embedder=e)
    assert flip["sign_agreement"] == 0.0 and flip["low_agreement_flag"]
    assert ssr.affect_agreement([], embedder=e) == {"n": 0}
    assert "valence" not in ssr.SCALES and ssr.ANCHORS_VERSION == "2026-10-ssr-v4-unicode-punctuation"   # survey untouched


def test_feel_pairs_walks_test_results():
    res = {"sessions": [{"ad": {"feel": {"pleasant": -0.4, "words": "pushy"}}, "landing": {"feel": {"pleasant": 0.2, "words": "ok"}}},
                        {"ad": {"feel": {"pleasant": 0.1}}}],
           "people": [{"turn1": {"feel": {"pleasant": "x", "words": "bad number"}}}]}
    assert sorted(emo.feel_pairs(res)) == [(-0.4, "pushy"), (0.2, "ok")]


def test_focus_group_masking_and_over_convergence():
    parts = [{"id": f"P{i}", "pre_text": f"pre{i}", "post_text": f"post{i}"} for i in range(4)]
    transcript = [{"speaker": f"P{i}", "text": f"room{i}"} for i in range(4)] + [{"speaker": "Moderator", "text": "q"}]
    private = {"post0": -0.8, "post1": -0.4, "post2": 0.0, "post3": 0.4}

    def rater(texts):
        out = []
        for t in texts:
            v = 0.5 if t.startswith("room") else private.get(t, 0.0)
            out.append({"valence": {"signed": v}})
        return out
    split = focus_group.affect_split({"participants": parts, "transcript": transcript}, rater)
    assert split["masking_flag"] and split["over_convergence_flag"] and split["mean_room_minus_private"] > 0.25
    assert split["people"][0]["gap"] == 1.3
    assert focus_group.affect_split({"participants": parts[:1]}, rater) == {}


def test_dashboard_shows_what_the_couplings_moved():
    import sys
    sys.path.insert(0, _os.path.join(_HERE, "..", "claude_cli"))
    import report_view
    feed = {"emotion": {"mode": "on", "words_check": {"n": 12, "sign_agreement": 0.4, "corr": 0.1, "low_agreement_flag": True}},
            "sessions": [{"emotion_effects": {"notice": 0.8}}, {"emotion_effects": {"notice": 0.9, "patience": 0.85}}, {}]}
    fg = {"affect": {"mean_room_minus_private": 0.4, "sd_private": 0.5, "sd_in_the_room": 0.1, "masking_flag": True,
                     "over_convergence_flag": True}}
    sec = report_view.emotion_section(None, feed, None, None, focus_group=fg)
    html = sec[2]
    for frag in ("What moved", "x0.80 to x0.90", "assumed sizes, not validated", "disagree with their own words",
                 "warmer in the room", "flattened"):
        assert frag in html, frag
