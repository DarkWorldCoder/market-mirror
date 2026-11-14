"""Randomized herding probe: a neutral account that no model drives gives a seeded share of each round's organic posts
one early vote (scripts/herding_probe.py), and feed_story.probe_check scores the arms against the controls. Runs on
fake environments and hand-built OASIS-shaped databases; no OASIS needed except where a test says so."""

import csv
import json
import os
import random
import sqlite3
import sys
from types import SimpleNamespace

import pytest

from app.services import feed_story as fs

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import herding_probe as hp  # noqa: E402

SCHEMA = """
CREATE TABLE user (user_id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id INTEGER, user_name TEXT, name TEXT, bio TEXT,
    created_at DATETIME, num_followings INTEGER DEFAULT 0, num_followers INTEGER DEFAULT 0);
CREATE TABLE post (post_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, original_post_id INTEGER, content TEXT DEFAULT '',
    quote_content TEXT, created_at DATETIME, num_likes INTEGER DEFAULT 0, num_dislikes INTEGER DEFAULT 0,
    num_shares INTEGER DEFAULT 0, num_reports INTEGER DEFAULT 0);
CREATE TABLE follow (follow_id INTEGER PRIMARY KEY AUTOINCREMENT, follower_id INTEGER, followee_id INTEGER, created_at DATETIME);
CREATE TABLE like (like_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, post_id INTEGER, created_at DATETIME);
CREATE TABLE dislike (dislike_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, post_id INTEGER, created_at DATETIME);
CREATE TABLE comment (comment_id INTEGER PRIMARY KEY AUTOINCREMENT, post_id INTEGER, user_id INTEGER, content TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP, num_likes INTEGER DEFAULT 0, num_dislikes INTEGER DEFAULT 0);
CREATE TABLE comment_like (comment_like_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, comment_id INTEGER, created_at DATETIME);
"""

# agents 0-5 are personas, 6 is a community account, 7 the brand (graph entity); the probe is appended as 8
PERSONAS = 6
PERSONA_INDEX = ([{"agent_id": i, "name": f"Person {i}", "kind": "persona", "segment": "students", "country": "India"}
                  for i in range(PERSONAS)]
                 + [{"agent_id": 6, "name": "Study Group", "kind": "community"},
                    {"agent_id": 7, "name": "Acme", "kind": "graph"}])
PROBE = 8
LAUNCH = "Acme launch day: half price this week"


def config(probe=True, **extra):
    cfg = {"seed": 7, "persona_index": PERSONA_INDEX,
           "agent_configs": [{"agent_id": i, "activity_level": 1.0, "active_hours": list(range(24))} for i in range(8)],
           "event_config": {"initial_posts": [], "scheduled_events": [
               {"round": 1, "poster_agent_id": 7, "content": LAUNCH, "platform": "both"}]}}
    if probe:
        cfg["herding_probe"] = probe if probe is not True else {"share": 0.5, "seed": 3}
    cfg.update(extra)
    return cfg


# --------------------------------------------------------------------------
# config and the probe account
# --------------------------------------------------------------------------

def test_settings_are_off_by_default_and_validated():
    assert hp.settings({}) is None
    assert hp.settings({"herding_probe": False}) is None
    assert hp.settings({"herding_probe": {"share": 0}}) is None
    assert hp.settings({"herding_probe": True, "seed": 11}) == {"share": 0.5, "seed": 11}
    assert hp.settings({"herding_probe": 0.3}) == {"share": 0.3, "seed": 7}
    assert hp.normalize({"share": 0.25, "seed": "4"}) == {"share": 0.25, "seed": 4}
    for bad in (1.0, 1.5, -0.2, {"share": "lots"}, {"seed": "x"}, "yes"):
        with pytest.raises(ValueError):
            hp.normalize(bad)
    assert hp.settings({"herding_probe": 2}) is None          # malformed config: off, never a crash in the runner


def test_probe_is_appended_to_a_copy_of_the_profiles(tmp_path):
    tw = tmp_path / "twitter_profiles.csv"
    with open(tw, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["user_id", "name", "username", "user_char", "description"])
        for i in range(3):
            w.writerow([i, f"P{i}", f"p{i}", "bio", "bio"])
    rd = tmp_path / "reddit_profiles.json"
    rd.write_text(json.dumps([{"user_id": i, "username": f"p{i}", "name": f"P{i}", "bio": "b", "persona": "p",
                               "karma": 1000, "created_at": "2026-01-01", "age": 30, "gender": "female", "mbti": "INTJ",
                               "country": "India"} for i in range(3)]))
    before = (tw.read_text(), rd.read_text())

    assert hp.profiles_with_probe(config(probe=False), "twitter", str(tw)) == (str(tw), None)
    path, pid = hp.profiles_with_probe(config(), "twitter", str(tw))
    assert pid == 3 and path != str(tw)
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    assert len(rows) == 4 and rows[-1]["username"] == hp.PROBE_USERNAME and rows[-1]["user_id"] == "3"
    hp.discard_copy(path, str(tw))
    assert not os.path.exists(path)

    path, pid = hp.profiles_with_probe(config(), "reddit", str(rd))
    data = json.load(open(path, encoding="utf-8"))
    assert pid == 3 and data[-1]["username"] == hp.PROBE_USERNAME and data[-1]["user_id"] == 3
    assert set(data[0]) <= set(data[-1])                     # every field the loader reads is there
    hp.discard_copy(path, str(rd))
    assert (tw.read_text(), rd.read_text()) == before        # the persona files on disk never contain the probe


def test_find_probe_scans_when_the_expected_id_is_someone_else():
    agents = {i: SimpleNamespace(user_info=SimpleNamespace(name=f"p{i}")) for i in range(4)}
    agents[2] = SimpleNamespace(user_info=SimpleNamespace(name=hp.PROBE_USERNAME))
    graph = SimpleNamespace(get_agent=lambda i: agents[i], get_agents=lambda: list(agents.items()))
    assert hp.find_probe(graph, 2) == 2
    assert hp.find_probe(graph, 3) == 2


# --------------------------------------------------------------------------
# assignment
# --------------------------------------------------------------------------

def test_assignment_is_seeded_balanced_and_platform_aware():
    ids = list(range(100, 140))
    a = hp.assign(ids, 0.5, 3, "reddit", 2)
    assert a == hp.assign(list(reversed(ids)), 0.5, 3, "reddit", 2)          # order of discovery does not matter
    assert a != hp.assign(ids, 0.5, 4, "reddit", 2)
    arms = [a[i] for i in ids]
    assert arms.count("control") == 20 and abs(arms.count("up") - arms.count("down")) <= 1
    tw = hp.assign(ids, 0.5, 3, "twitter", 2)
    assert set(tw.values()) == {"up", "control"}                              # the X-like platform has no dislike
    # small rounds round at random, so the share holds on average
    treated = sum(sum(v != "control" for v in hp.assign([1, 2, 3], 0.5, s, "reddit", 1).values()) for s in range(400))
    assert abs(treated / 1200 - 0.5) < 0.05


# --------------------------------------------------------------------------
# a fake environment with an OASIS-shaped database
# --------------------------------------------------------------------------

class LLMAction:
    pass


class Agent:
    """Hashable like an OASIS SocialAgent (the env's action dicts are keyed by agent)."""

    def __init__(self, aid, name=None):
        self.social_agent_id = aid
        self.user_info = SimpleNamespace(name=name or f"u{aid}")


class ManualAction:
    def __init__(self, action_type, action_args):
        self.action_type, self.action_args = action_type, action_args


ActionType = SimpleNamespace(LIKE_POST="like_post", DISLIKE_POST="dislike_post", CREATE_POST="create_post")


class FakeEnv:
    """Applies ManualActions to the database; an LLMAction lets a persona write a post (or the community account a
    group post, or anyone else a repost). Records every step's actions in order."""

    def __init__(self, db_path, n_agents):
        self.db_path = db_path
        self.agents = {i: Agent(i, hp.PROBE_USERNAME if i == PROBE else None) for i in range(n_agents)}
        self.agent_graph = SimpleNamespace(get_agent=lambda i: self.agents[i], get_agents=lambda: list(self.agents.items()))
        self.steps = []
        conn = sqlite3.connect(db_path)
        conn.executescript(SCHEMA)
        for i in range(n_agents):
            conn.execute("INSERT INTO user (user_id, agent_id, user_name, name) VALUES (?,?,?,?)", (i, i, f"u{i}", f"u{i}"))
        conn.commit()
        conn.close()

    def step(self, actions, round_num):
        self.steps.append(list(actions.items()))
        conn = sqlite3.connect(self.db_path)
        for agent, act in actions.items():
            uid = agent.social_agent_id
            for a in act if isinstance(act, list) else [act]:
                if isinstance(a, ManualAction) and a.action_type == "like_post":
                    conn.execute("INSERT INTO like (user_id, post_id) VALUES (?,?)", (uid, a.action_args["post_id"]))
                    conn.execute("UPDATE post SET num_likes = num_likes + 1 WHERE post_id = ?", (a.action_args["post_id"],))
                elif isinstance(a, ManualAction) and a.action_type == "dislike_post":
                    conn.execute("INSERT INTO dislike (user_id, post_id) VALUES (?,?)", (uid, a.action_args["post_id"]))
                elif isinstance(a, ManualAction) and a.action_type == "create_post":
                    conn.execute("INSERT INTO post (user_id, content, created_at) VALUES (?,?,?)",
                                 (uid, a.action_args["content"], round_num))
                elif isinstance(a, LLMAction):
                    if uid == 5:      # person 5 reposts the newest post instead of writing one
                        conn.execute("INSERT INTO post (user_id, original_post_id, content, created_at) "
                                     "SELECT ?, MAX(post_id), '', ? FROM post", (uid, round_num))
                    else:
                        conn.execute("INSERT INTO post (user_id, content, created_at) VALUES (?,?,?)",
                                     (uid, f"post by {uid} in round {round_num}", round_num))
        conn.commit()
        conn.close()


def drive(probe, env, rounds, active, scheduled=None):
    """The runner's loop: enrol after every step, the probe's votes go into the next step."""
    probe.after_step(0, has_next=rounds > 0)
    for r in range(1, rounds + 1):
        actions = {env.agent_graph.get_agent(a): LLMAction() for a in active}
        for ev in (scheduled or {}).get(r, []):
            actions[env.agent_graph.get_agent(ev["poster_agent_id"])] = ManualAction("create_post", {"content": ev["content"]})
        actions = probe.inject(actions, env, r, ManualAction, ActionType)
        env.step(actions, r)
        probe.after_step(r, has_next=r < rounds)


def test_round_loop_enrols_organic_posts_and_delivers_votes_first(tmp_path):
    db = str(tmp_path / "reddit_simulation.db")
    env = FakeEnv(db, PROBE + 1)
    cfg = config()
    probe = hp.HerdingProbe.start(cfg, "reddit", str(tmp_path), db, env.agent_graph, PROBE, lambda m: None)
    scheduled = {1: [{"poster_agent_id": 7, "content": LAUNCH}]}
    drive(probe, env, 3, active=[0, 1, 2, 3, 4, 5, 6], scheduled=scheduled)

    log = json.load(open(tmp_path / hp.LOG_FILE, encoding="utf-8"))["platforms"]["reddit"]
    assert log["probe_agent_id"] == PROBE and log["probe_user_id"] == PROBE and log["share"] == 0.5
    batches = log["batches"]
    assert [b["round"] for b in batches] == [1, 2]                # round 3 was the last: nothing enrolled after it
    conn = sqlite3.connect(db)
    authors = dict(conn.execute("SELECT post_id, user_id FROM post").fetchall())
    contents = dict(conn.execute("SELECT post_id, content FROM post").fetchall())
    for b in batches:
        assert b["vote_round"] == b["round"] + 1 and set(b["marks"]) == {"post", "like", "dislike", "comment"}
        assert len(b["posts"]) == 5                               # persons 0-4: no repost, community or brand post
        for p in b["posts"]:
            assert authors[p["post_id"]] in range(5) and contents[p["post_id"]] != LAUNCH
            if p["arm"] != "control":
                assert p["delivered"] is True
    # the probe voted exactly on its treated posts, and its actions came first in the step
    voted = {pid: "up" for (pid,) in conn.execute("SELECT post_id FROM like WHERE user_id = ?", (PROBE,))}
    voted.update({pid: "down" for (pid,) in conn.execute("SELECT post_id FROM dislike WHERE user_id = ?", (PROBE,))})
    assert voted == {p["post_id"]: p["arm"] for b in batches for p in b["posts"] if p["arm"] != "control"}
    assert {p["arm"] for b in batches for p in b["posts"]} == {"up", "down", "control"}
    for step in env.steps[1:]:
        first_agent, first_action = step[0]
        assert first_agent.social_agent_id == PROBE and all(isinstance(a, ManualAction) for a in first_action)
    # the probe's rows never reach the people's activity log
    trace = [{"agent_id": PROBE, "action_type": "LIKE_POST"}, {"agent_id": 1, "action_type": "LIKE_POST"}]
    assert probe.drop_own(trace) == [{"agent_id": 1, "action_type": "LIKE_POST"}]


def test_probe_never_gets_a_model_driven_action(tmp_path):
    db = str(tmp_path / "twitter_simulation.db")
    env = FakeEnv(db, PROBE + 1)
    probe = hp.HerdingProbe(config(), "twitter", str(tmp_path), db, PROBE, lambda m: None)
    probe.after_step(0, True)
    # a buggy selection hands the probe an LLMAction: inject removes it, also when no vote is pending
    acts = probe.inject({env.agents[1]: LLMAction(), env.agents[PROBE]: LLMAction()}, env, 1, ManualAction, ActionType)
    assert env.agents[PROBE] not in acts and isinstance(acts[env.agents[1]], LLMAction)
    for r in range(1, 6):
        env.step(acts, r)
        probe.after_step(r, True)
        acts = probe.inject({env.agents[a]: LLMAction() for a in (0, 1, 2, PROBE)}, env, r + 1, ManualAction, ActionType)
        probe_acts = acts.get(env.agents[PROBE], [])
        assert all(isinstance(a, ManualAction) and a.action_type == "like_post" for a in probe_acts)
    assert not any(isinstance(a, LLMAction) for step in env.steps for agent, a in step if agent.social_agent_id == PROBE)


def test_active_agents_never_include_the_probe():
    pytest.importorskip("oasis")
    pytest.importorskip("camel")
    import run_parallel_simulation as rps
    from oasis import LLMAction as RealLLMAction, ManualAction as RealManual, ActionType as RealType

    cfg = config()
    agents = {i: Agent(i) for i in range(PROBE + 1)}
    env = SimpleNamespace(agent_graph=SimpleNamespace(get_agent=lambda i: agents[i]), platform_type=None)
    probe = hp.HerdingProbe(cfg, "reddit", "/nonexistent", "/nonexistent/db", PROBE, lambda m: None)
    probe.pending = [{"round": 1, "posts": [{"post_id": 9, "arm": "down"}], "vote_round": None}]
    for r in range(48):
        active = rps.get_active_agents_for_round(env, cfg, r % 24, r)
        assert active and all(aid != PROBE for aid, _ in active)
        actions = probe.inject({agent: RealLLMAction() for _, agent in active}, env, r + 1, RealManual, RealType)
        for agent, act in actions.items():
            if agent.social_agent_id == PROBE:
                assert all(isinstance(a, RealManual) and a.action_type == RealType.DISLIKE_POST for a in act)
            else:
                assert isinstance(act, RealLLMAction)


# --------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------

def scored_platform(n=60, pile_on=0.0, follow_up=0.0, seed=5, probe_id=PROBE):
    """n posts enrolled after round 1 (marks at 0, so every reaction is later), arms in turn. Other people like and
    dislike each post 0-3 times, plus `pile_on` extra dislikes on down-voted posts and `follow_up` extra likes on
    up-voted ones. The probe's own vote is in the tables too and must never count."""
    rng = random.Random(seed)
    posts, likes, dislikes, comments, entries = [], [], [], [], []
    arms = ("up", "down", "control")

    def extra(x):
        return int(x) + (rng.random() < x - int(x))
    for i in range(n):
        pid, arm = i + 1, arms[i % 3]
        posts.append({"post_id": pid, "user_id": 1, "original_post_id": None, "content": f"p{pid}", "quote_content": None})
        entries.append({"post_id": pid, "author_agent_id": 1, "arm": arm, **({"delivered": True} if arm != "control" else {})})
        if arm == "up":
            likes.append({"like_id": len(likes) + 1, "user_id": probe_id, "post_id": pid})
        elif arm == "down":
            dislikes.append({"dislike_id": len(dislikes) + 1, "user_id": probe_id, "post_id": pid})
        k_up = rng.randint(0, 3) + (extra(follow_up) if arm == "up" else 0)
        k_down = rng.randint(0, 3) + (extra(pile_on) if arm == "down" else 0)
        for _ in range(k_up):
            likes.append({"like_id": len(likes) + 1, "user_id": 2 + len(likes) % 4, "post_id": pid})
        for _ in range(k_down):
            dislikes.append({"dislike_id": len(dislikes) + 1, "user_id": 2 + len(dislikes) % 4, "post_id": pid})
        if rng.random() < 0.4:
            comments.append({"comment_id": len(comments) + 1, "post_id": pid, "user_id": 3,
                             "content": "terrible scam, avoid" if arm == "down" and pile_on else "nice, love it"})
    section = {"probe_agent_id": probe_id, "probe_user_id": probe_id, "share": 0.67, "seed": 1,
               "batches": [{"round": 1, "vote_round": 2, "marks": {"post": n, "like": 0, "dislike": 0, "comment": 0},
                            "posts": entries}]}
    return {"posts": posts, "likes": likes, "dislikes": dislikes, "comments": comments}, section


def test_pile_on_after_an_early_downvote_is_measured():
    data, section = scored_platform(pile_on=2.0)
    res = fs.probe_check({"reddit": data}, {"platforms": {"reddit": section}}, boots=500)
    down = res["down_vs_control"]
    assert res["verdict"] == "negative pile-on" and res["flag"] is True
    assert down["final_net"]["hi"] < 0 and down["final_net"]["diff"] < -1
    assert down["later_negative_share"]["lo"] > 0
    assert res["arms"] == {"up": 20, "down": 20, "control": 20} and res["votes_landed"] == 40
    assert "piled onto an early downvote" in res["reading"] and "Randomized" in res["reading"]


def test_no_effect_is_no_clear_herding():
    data, section = scored_platform(seed=9)
    res = fs.probe_check({"reddit": data}, {"platforms": {"reddit": section}}, boots=500)
    assert res["verdict"] == "no clear herding" and res["flag"] is False
    net = res["down_vs_control"]["final_net"]
    assert net["lo"] < 0 < net["hi"]


def test_following_an_upvote_is_positive_herding():
    data, section = scored_platform(follow_up=2.0, seed=4)
    res = fs.probe_check({"reddit": data}, {"platforms": {"reddit": section}}, boots=500)
    assert res["verdict"] == "positive herding" and res["flag"] is False
    assert res["up_vs_control"]["final_net"]["lo"] > 0


def test_outcomes_leave_out_the_probe_and_earlier_reactions():
    section = {"probe_agent_id": PROBE, "probe_user_id": PROBE,
               "batches": [{"round": 1, "vote_round": 2, "marks": {"post": 3, "like": 1, "dislike": 0, "comment": 1},
                            "posts": [{"post_id": 1, "arm": "up", "delivered": True},
                                      {"post_id": 2, "arm": "down", "delivered": True}]},
                           {"round": 4, "vote_round": None, "marks": {}, "posts": [{"post_id": 3, "arm": "control"}]}]}
    data = {"posts": [{"post_id": 4, "user_id": 2, "original_post_id": 2, "quote_content": "what a scam"}],
            "likes": [{"like_id": 1, "user_id": 2, "post_id": 1},                # before assignment
                      {"like_id": 2, "user_id": PROBE, "post_id": 1}],           # the probe's own vote
            "dislikes": [{"dislike_id": 1, "user_id": PROBE, "post_id": 2}],
            "comments": [{"comment_id": 1, "post_id": 2, "user_id": 3, "content": "awful"},       # before
                         {"comment_id": 2, "post_id": 2, "user_id": 3, "content": "love it"}]}
    rows = fs.probe_outcomes("reddit", data, section)
    assert [r["post_id"] for r in rows] == [1, 2]                 # the batch whose votes never went out is left out
    up, down = rows
    assert up["final_net"] == 1 and (up["later_pos"], up["later_neg"]) == (0, 0)
    assert down["final_net"] == 0 and (down["later_pos"], down["later_neg"]) == (1, 1)   # later comment + quote


def test_small_probes_are_not_checked():
    data, section = scored_platform(n=9)
    res = fs.probe_check({"reddit": data}, {"platforms": {"reddit": section}}, boots=100)
    assert res["verdict"] == "not checked" and "needs 5" in res["reading"]


# --------------------------------------------------------------------------
# the feed story with a probe
# --------------------------------------------------------------------------

def test_feed_story_hides_the_probe_and_attaches_the_measurement(tmp_path):
    db = str(tmp_path / "reddit_simulation.db")
    env = FakeEnv(db, PROBE + 1)
    cfg = config()
    probe = hp.HerdingProbe.start(cfg, "reddit", str(tmp_path), db, env.agent_graph, PROBE, lambda m: None)
    drive(probe, env, 4, active=[0, 1, 2, 3, 4])
    story = fs.build_feed_story(str(tmp_path), cfg)
    assert str(PROBE) not in story["people"]
    posts = story["platforms"]["reddit"]["posts"]
    voted = [p for p in posts if p.get("probe_vote")]
    assert voted and all(p["likes"] == 0 and p["dislikes"] == 0 for p in voted)   # the probe's vote is in no count
    assert all(lk["agent_id"] != PROBE for p in posts for lk in p["likers"])
    pr = story["herding"]["probe"]
    assert pr["posts"] == 15 and pr["verdict"] == "not checked"                     # 3 batches of 5 posts, few arms
    assert pr["by_platform"]["reddit"]["control"] + pr["arms"]["up"] + pr["arms"]["down"] == 15

    # a probe-off run never shows an old probe
    hp.reset_log(str(tmp_path))
    assert "probe" not in fs.build_feed_story(str(tmp_path), config(probe=False))["herding"]


# --------------------------------------------------------------------------
# config through the start endpoint
# --------------------------------------------------------------------------

def test_start_endpoint_validates_and_writes_the_probe(tmp_path):
    from flask import Flask
    from app.api import simulation as simulation_api

    app = Flask(__name__)
    with app.test_request_context("/api/simulation/start", method="POST",
                                  json={"simulation_id": "sim-1", "herding_probe": {"share": 1.5}}):
        response, status = simulation_api.start_simulation()
    assert status == 400 and "between 0 and 1" in response.get_json()["error"]

    path = tmp_path / "simulation_config.json"
    path.write_text(json.dumps({"seed": 7, "agent_configs": []}))
    simulation_api._write_herding_probe(str(tmp_path), hp.normalize(True))
    assert json.loads(path.read_text())["herding_probe"] == {"share": 0.5, "seed": 7}
    simulation_api._write_herding_probe(str(tmp_path), None)
    assert "herding_probe" not in json.loads(path.read_text())
