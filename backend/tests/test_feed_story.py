"""Feed story: OASIS sqlite + actions.jsonl -> post-by-post view with rounds, likers, quotes,
brand flags, lexicon sentiment, mention edges, and the Flask GET with its cache."""

import json
import os
import sqlite3

import pytest

from app.services import feed_story as fs

SCHEMA = """
CREATE TABLE user (user_id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id INTEGER, user_name TEXT, name TEXT, bio TEXT,
    created_at DATETIME, num_followings INTEGER DEFAULT 0, num_followers INTEGER DEFAULT 0);
CREATE TABLE post (post_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, original_post_id INTEGER, content TEXT DEFAULT '',
    quote_content TEXT, created_at DATETIME, num_likes INTEGER DEFAULT 0, num_dislikes INTEGER DEFAULT 0,
    num_shares INTEGER DEFAULT 0, num_reports INTEGER DEFAULT 0);
CREATE TABLE follow (follow_id INTEGER PRIMARY KEY AUTOINCREMENT, follower_id INTEGER, followee_id INTEGER, created_at DATETIME);
CREATE TABLE like (like_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, post_id INTEGER, created_at DATETIME);
CREATE TABLE dislike (dislike_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, post_id INTEGER, created_at DATETIME);
CREATE TABLE trace (user_id INTEGER, created_at DATETIME, action TEXT, info TEXT, PRIMARY KEY(user_id, created_at, action, info));
CREATE TABLE comment (comment_id INTEGER PRIMARY KEY AUTOINCREMENT, post_id INTEGER, user_id INTEGER, content TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP, num_likes INTEGER DEFAULT 0, num_dislikes INTEGER DEFAULT 0);
CREATE TABLE comment_like (comment_like_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, comment_id INTEGER, created_at DATETIME);
"""

# agents: 0 brand (graph entity), 1 Asha (India students), 2 Ben (Kenya parents), 3 Carla (Philippines students),
# 4 community account
PERSONA_INDEX = [
    {"agent_id": 0, "name": "Acme", "kind": "graph", "segment": None, "country": None},
    {"agent_id": 1, "name": "Asha Rao", "kind": "persona", "segment": "India students", "country": "India"},
    {"agent_id": 2, "name": "Ben Otieno", "kind": "persona", "segment": "Kenya parents", "country": "Kenya"},
    {"agent_id": 3, "name": "Carla Reyes", "kind": "persona", "segment": "Philippines students", "country": "Philippines"},
    {"agent_id": 4, "name": "Manila Study Group", "kind": "community", "segment": None, "country": "Philippines"},
]
BRAND_POST = "Try Acme free for 7 days, no card needed"


def _config(scheduled=None):
    return {"persona_index": PERSONA_INDEX,
            "event_config": {"initial_posts": [{"content": BRAND_POST, "poster_type": "Brand", "poster_agent_id": 0}],
                             "scheduled_events": scheduled or []}}


def make_twitter_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    for aid, name in enumerate(["acme_1", "asha_2", "ben_3", "carla_4", "manila_5"]):
        conn.execute("INSERT INTO user (user_id, agent_id, name, created_at) VALUES (?,?,?,0)", (aid, aid, name))
    # twitter created_at is an integer step
    conn.execute("INSERT INTO post VALUES (1, 0, NULL, ?, NULL, 1, 2, 0, 2, 0)", (BRAND_POST,))
    conn.execute("INSERT INTO post VALUES (2, 1, NULL, 'Free trial without card? bahut accha, finally', NULL, 1, 1, 0, 0, 0)")
    conn.execute("INSERT INTO post VALUES (3, 2, 1, ?, 'No card needed but what about hidden charges? scam alert 🚩', 2, 0, 0, 0, 0)", (BRAND_POST,))
    conn.execute("INSERT INTO post VALUES (4, 3, 1, ?, NULL, 2, 0, 0, 0, 0)", (BRAND_POST,))   # repost
    conn.execute("INSERT INTO post VALUES (5, 4, NULL, 'Group announcement: Acme deal thread here', NULL, 3, 0, 0, 0, 0)")
    conn.execute("INSERT INTO post VALUES (6, 3, NULL, 'Posted after logging stopped', NULL, 4, 0, 0, 0, 0)")
    conn.execute("INSERT INTO like VALUES (1, 1, 1, 2)")       # Asha likes brand post in round 1
    conn.execute("INSERT INTO like VALUES (2, 3, 1, 3)")       # Carla likes brand post in round 2
    conn.execute("INSERT INTO like VALUES (3, 2, 2, 2)")       # Ben likes Asha's post
    conn.execute("INSERT INTO dislike VALUES (1, 2, 1, 2)")    # Ben dislikes brand post
    conn.execute("INSERT INTO comment VALUES (1, 1, 2, 'Overpriced and shady, I regret trying it', 2, 0, 0)")
    conn.execute("INSERT INTO comment VALUES (2, 1, 3, 'Sulit! Love it, salamat Acme 🙌', 3, 1, 0)")
    conn.execute("INSERT INTO comment_like VALUES (1, 2, 1, 3)")   # Ben likes comment 1
    conn.execute("INSERT INTO follow VALUES (1, 1, 0, 0)")     # Asha follows Acme
    conn.execute("INSERT INTO follow VALUES (2, 2, 3, 0)")     # Ben follows Carla (so Carla's repost reaches Ben)
    conn.commit()
    conn.close()


def make_reddit_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    for aid, name in enumerate(["acme_1", "asha_2", "ben_3", "carla_4", "manila_5"]):
        conn.execute("INSERT INTO user (user_id, agent_id, name, created_at) VALUES (?,?,?,'2026-10-18 10:00:00')", (aid, aid, name))
    conn.execute("INSERT INTO post VALUES (1, 2, NULL, 'Later post', NULL, '2026-10-18 12:00:00.000001', 0, 0, 0, 0)")
    conn.execute("INSERT INTO post VALUES (2, 1, NULL, 'Earlier post', NULL, '2026-10-18 11:00:00.000001', 0, 0, 0, 0)")
    conn.execute("INSERT INTO comment VALUES (1, 2, 3, 'nice one', '2026-10-18 11:30:00', 0, 0)")
    conn.commit()
    conn.close()


def write_jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def twitter_jsonl():
    act = lambda rnd, aid, kind, args: {"round": rnd, "agent_id": aid, "agent_name": f"a{aid}", "action_type": kind,  # noqa: E731
                                        "action_args": args, "result": None, "success": True}
    return [
        {"event_type": "simulation_start", "platform": "twitter", "total_rounds": 4},
        {"round": 0, "event_type": "round_start", "simulated_hour": 0},
        act(0, 0, "CREATE_POST", {"content": BRAND_POST}),
        act(0, 1, "CREATE_POST", {"content": "Free trial without card? bahut accha, finally"}),
        {"round": 0, "event_type": "round_end", "actions_count": 2},
        {"round": 1, "event_type": "round_start", "simulated_hour": 19},
        # the runner replays round-0 posts in round 1, this time with ids: round 0 must win
        act(1, 0, "CREATE_POST", {"content": BRAND_POST, "post_id": 1}),
        act(1, 1, "CREATE_POST", {"content": "Free trial without card? bahut accha, finally", "post_id": 2}),
        act(1, 2, "QUOTE_POST", {"quoted_id": 1, "new_post_id": 3, "quote_content": "No card needed but what about hidden charges? scam alert 🚩"}),
        act(1, 1, "LIKE_POST", {"post_id": 1, "like_id": 1}),
        act(1, 2, "LIKE_POST", {"post_id": 2, "like_id": 3}),
        act(1, 2, "DISLIKE_POST", {"post_id": 1, "dislike_id": 1}),
        act(1, 2, "CREATE_COMMENT", {"content": "Overpriced and shady, I regret trying it", "comment_id": 1}),
        act(1, 3, "DO_NOTHING", {}),
        {"round": 1, "event_type": "round_end", "actions_count": 8},
        {"round": 2, "event_type": "round_start", "simulated_hour": 20},
        act(2, 3, "REPOST", {"new_post_id": 4}),
        act(2, 3, "LIKE_POST", {"post_id": 1, "like_id": 2}),
        act(2, 3, "CREATE_COMMENT", {"content": "Sulit! Love it, salamat Acme 🙌", "comment_id": 2}),
        act(2, 2, "LIKE_COMMENT", {"comment_id": 1}),
        {"round": 2, "event_type": "round_end", "actions_count": 4},
        {"round": 3, "event_type": "round_start", "simulated_hour": 21},
        act(3, 4, "CREATE_POST", {"content": "Group announcement: Acme deal thread here"}),
        {"round": 3, "event_type": "round_end", "actions_count": 1},
        {"event_type": "simulation_end", "platform": "twitter", "total_rounds": 4},
    ]


@pytest.fixture
def sim_dir(tmp_path):
    d = tmp_path / "sim_feed1"
    d.mkdir()
    make_twitter_db(str(d / "twitter_simulation.db"))
    make_reddit_db(str(d / "reddit_simulation.db"))
    write_jsonl(str(d / "twitter" / "actions.jsonl"), twitter_jsonl())
    return str(d)


def by_id(story, platform):
    return {p["post_id"]: p for p in story["platforms"][platform]["posts"]}


def test_round_index_maps_ids_and_dedupes_round0(sim_dir):
    r = fs.round_index(sim_dir, "twitter")
    assert r["available"] and r["rounds"] == {0: 0, 1: 19, 2: 20, 3: 21}
    assert r["post_keys"][(0, fs._norm_key(BRAND_POST))] == 0        # first row wins
    assert r["posts"] == {1: 0, 2: 0, 3: 1, 4: 2}                     # replayed ids inherit round 0
    assert r["comments"] == {1: 1, 2: 2} and r["likes"] == {1: 1, 3: 1, 2: 2} and r["dislikes"] == {1: 1}
    assert r["comment_likes"] == {1: 2}
    assert fs.round_index(sim_dir, "reddit")["available"] is False


def test_load_platform_reads_tables_read_only(sim_dir):
    data = fs.load_platform(os.path.join(sim_dir, "twitter_simulation.db"))
    assert {k: len(v) for k, v in data.items()} == {"users": 5, "posts": 6, "comments": 2, "likes": 3, "dislikes": 1,
                                                    "follows": 2, "comment_likes": 1}
    assert fs.load_platform(os.path.join(sim_dir, "nope.db"))["posts"] == []


def test_build_joins_rounds_hours_authors(sim_dir):
    story = fs.build_feed_story(sim_dir, _config())
    assert story["sentiment_method"] == "lexicon"
    tw = by_id(story, "twitter")
    assert [p["post_id"] for p in story["platforms"]["twitter"]["posts"]] == [1, 2, 3, 4, 5, 6]
    assert tw[1]["round"] == 0 and tw[1]["hour"] == "00:00"          # round-0 wins over the round-1 replay
    assert tw[3]["round"] == 1 and tw[3]["hour"] == "19:00"
    assert tw[5]["round"] == 3 and tw[5]["hour"] == "21:00"
    assert tw[6]["round"] is None and tw[6]["hour"] is None          # never logged
    assert tw[2]["author"] == {"agent_id": 1, "name": "Asha Rao", "segment": "India students", "country": "India", "kind": "persona"}
    assert tw[1]["author"]["kind"] == "graph"
    # comments joined with round, hour, likes (max of counter and comment_like rows) and sentiment
    cm = {c["comment_id"]: c for c in tw[1]["comments"]}
    assert cm[1]["author"]["name"] == "Ben Otieno" and cm[1]["round"] == 1 and cm[1]["hour"] == "19:00" and cm[1]["likes"] == 1
    assert cm[1]["sentiment"] == "neg" and cm[2]["sentiment"] == "pos" and cm[2]["round"] == 2


def test_dedupe_post_and_comment_ids(sim_dir):
    story = fs.build_feed_story(sim_dir, _config())
    ids = [p["post_id"] for p in story["platforms"]["twitter"]["posts"]]
    assert len(ids) == len(set(ids)) == 6
    cids = [c["comment_id"] for p in story["platforms"]["twitter"]["posts"] for c in p["comments"]]
    assert len(cids) == len(set(cids)) == 2


def test_likers_by_segment_quotes_reposts_reach(sim_dir):
    story = fs.build_feed_story(sim_dir, _config())
    p = by_id(story, "twitter")[1]
    assert p["likes"] == 2 and p["dislikes"] == 1
    assert sorted(l["name"] for l in p["likers"]) == ["Asha Rao", "Carla Reyes"]
    assert p["engagement"]["by_segment"] == {"Kenya parents": 3, "India students": 1, "Philippines students": 3}
    assert p["engagement"]["by_country"] == {"Kenya": 3, "India": 1, "Philippines": 3}   # like + comment + repost
    assert p["quotes"] == [3] and p["reposts"] == 1
    assert p["reply_sentiment"] == {"pos": 1, "neg": 2, "neu": 0}     # 2 comments + 1 quote
    # reach: follower Asha, engagers Asha/Ben/Carla, Carla's follower Ben -> 3 distinct people
    assert p["reach_proxy"] == 3
    assert p["score"] == 2 + 2 * 1 + 1 + 2 * 2 - 1


def test_quote_points_to_original_and_repost_is_compact(sim_dir):
    story = fs.build_feed_story(sim_dir, _config())
    tw = by_id(story, "twitter")
    q = tw[3]
    assert q["kind"] == "quote" and q["content"].startswith("No card needed")
    assert q["quote_content"] == BRAND_POST
    assert q["original"] == {"post_id": 1, "author": tw[1]["author"]}
    assert q["sentiment"] == "neg" and q["is_brand"] is False
    r = tw[4]
    assert r["kind"] == "repost" and r["content"] == "" and r["original"]["post_id"] == 1 and r["quote_content"] == BRAND_POST


def test_brand_flag_from_event_config_and_community(sim_dir):
    story = fs.build_feed_story(sim_dir, _config())
    tw = by_id(story, "twitter")
    assert tw[1]["is_brand"] is True and tw[1]["brand_source"] == "initial_post"
    assert tw[5]["is_brand"] is True and tw[5]["brand_source"] == "community"      # community account
    assert tw[2]["is_brand"] is False and tw[3]["is_brand"] is False
    brand = {(b["platform"], b["post_id"]): b for b in story["brand_posts"]}
    assert set(brand) == {("twitter", 1), ("twitter", 5)}
    b = brand[("twitter", 1)]
    assert b["source"] == "initial_post"
    assert b["best_reply"]["sentiment"] == "pos" and b["best_reply"]["author"]["name"] == "Carla Reyes"
    assert b["worst_reply"]["sentiment"] == "neg"
    # scheduled events by persona name also count
    story2 = fs.build_feed_story(sim_dir, _config(scheduled=[{"round": 3, "agent": "Manila Study Group",
                                                              "content": "Group announcement: Acme deal thread here"}]))
    assert by_id(story2, "twitter")[5]["brand_source"] == "scheduled_event"


def test_rounds_view(sim_dir):
    story = fs.build_feed_story(sim_dir, _config())
    rounds = {r["round"]: r for r in story["platforms"]["twitter"]["rounds"]}
    assert list(rounds) == [0, 1, 2, 3]
    assert rounds[0]["hour"] == "00:00" and rounds[0]["posts"] == 2 and rounds[0]["likes"] == 0
    assert rounds[1]["posts"] == 1 and rounds[1]["comments"] == 1 and rounds[1]["likes"] == 2
    assert rounds[1]["top_posts"] == [3]
    assert rounds[1]["brand_sentiment"] == {"pos": 0, "neg": 2, "neu": 0}   # Ben's comment + Ben's quote
    assert rounds[2]["brand_sentiment"] == {"pos": 1, "neg": 0, "neu": 0}
    assert rounds[0]["top_posts"] == [1, 2]


def test_sentiment_lexicon_and_emoji():
    assert fs.sentiment_label("I love it, bahut accha 🙌") == "pos"
    assert fs.sentiment_label("scam, overpriced, mahal 🚩") == "neg"
    assert fs.sentiment_label("What time does it open?") == "neu"
    assert fs.sentiment_label("not good at all") == "neg"              # negation flips
    assert fs.sentiment_label("") == "neu" and fs.sentiment_label(None) == "neu"
    assert fs.sentiment_score("great great bad") == 1.0


def test_fallback_without_jsonl_orders_by_created_at(sim_dir):
    story = fs.build_feed_story(sim_dir, _config())
    rd = story["platforms"]["reddit"]
    assert rd["rounds_known"] is False
    assert [p["post_id"] for p in rd["posts"]] == [2, 1]              # datetime strings sort correctly
    assert all(p["round"] is None and p["hour"] is None for p in rd["posts"])
    assert rd["posts"][0]["comments"][0]["round"] is None
    assert rd["rounds"] == []
    # twitter integer steps also sort when the jsonl is missing
    os.remove(os.path.join(sim_dir, "twitter", "actions.jsonl"))
    story = fs.build_feed_story(sim_dir, _config())
    tw = story["platforms"]["twitter"]
    assert [p["post_id"] for p in tw["posts"]] == [1, 2, 3, 4, 5, 6] and tw["rounds_known"] is False
    assert all(p["round"] is None for p in tw["posts"])


def test_max_posts_cap_and_people(sim_dir):
    story = fs.build_feed_story(sim_dir, _config(), max_posts=2)
    tw = story["platforms"]["twitter"]
    assert len(tw["posts"]) == 2 and tw["total_posts"] == 6 and tw["truncated"] is True
    assert set(story["people"]) >= {"0", "1", "2", "3", "4"}
    assert story["people"]["2"]["segment"] == "Kenya parents"


def test_mention_edges(sim_dir):
    story = fs.build_feed_story(sim_dir, _config())
    nodes = [{"uuid": "n_acme", "name": "Acme", "labels": ["Entity", "Brand"]},
             {"uuid": "n_card", "name": "card", "labels": ["Entity", "Objection"]},
             {"uuid": "n_asha", "name": "Asha Rao", "labels": ["Entity", "Persona"]},
             {"uuid": "n_ab", "name": "AB", "labels": ["Entity", "Short"]}]
    edges = fs.mention_edges(story, nodes)
    facts = {(e["source_node_uuid"], e["target_node_uuid"]): e for e in edges}
    assert all(e["name"] == "MENTIONS" for e in edges)
    assert ("n_asha", "n_card") in facts                               # persona node reused by name
    assert ("mm_p3", "n_acme") in facts and facts[("mm_p3", "n_acme")]["attributes"]["count"] == 1
    assert ("mm_p2", "n_card") in facts                                # "No card needed..." quote text
    assert not any(t == "n_ab" for _, t in facts)                      # short names skipped
    assert not any(s == "mm_p0" or s == "mm_p4" for s, _ in facts)     # graph and community accounts are not sources
    assert fs.mention_edges({"platforms": {}}, nodes) == []


def test_feed_story_api_builds_caches_and_filters(tmp_path, monkeypatch):
    from app import create_app
    from app.config import Config
    from app.services.simulation_manager import SimulationManager
    from app.api import feed as feed_api
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path))
    sim = tmp_path / "sim_api1"
    sim.mkdir()
    (sim / "state.json").write_text(json.dumps({"project_id": "p", "graph_id": "g", "status": "completed"}), encoding="utf-8")
    (sim / "simulation_config.json").write_text(json.dumps(_config()), encoding="utf-8")
    make_twitter_db(str(sim / "twitter_simulation.db"))
    write_jsonl(str(sim / "twitter" / "actions.jsonl"), twitter_jsonl())
    app = create_app()
    app.config.update(TESTING=True)
    c = app.test_client()

    assert c.get("/api/simulation/sim_missing/feed-story").status_code == 404
    r = c.get("/api/simulation/sim_api1/feed-story")
    assert r.status_code == 200, r.get_json()
    data = r.get_json()["data"]
    assert set(data["platforms"]) == {"twitter"} and len(data["platforms"]["twitter"]["posts"]) == 6
    assert data["brand_posts"][0]["post_id"] == 1
    cache = sim / "feed_story.json"
    assert cache.exists() and json.loads(cache.read_text(encoding="utf-8"))["sentiment_method"] == "lexicon"

    # cached: a second GET does not rebuild
    calls = []
    real_build = feed_api.build_feed_story
    monkeypatch.setattr(feed_api, "build_feed_story", lambda *a, **k: calls.append(1) or {"platforms": {}, "brand_posts": []})
    assert c.get("/api/simulation/sim_api1/feed-story").status_code == 200 and calls == []
    # a newer database invalidates the cache
    os.utime(str(sim / "twitter_simulation.db"), (os.path.getmtime(cache) + 5, os.path.getmtime(cache) + 5))
    assert c.get("/api/simulation/sim_api1/feed-story").status_code == 200 and calls == [1]
    # ?refresh=1 forces a rebuild even with a fresh cache
    monkeypatch.setattr(feed_api, "build_feed_story", real_build)
    r = c.get("/api/simulation/sim_api1/feed-story?refresh=1")
    assert r.status_code == 200 and len(r.get_json()["data"]["platforms"]["twitter"]["posts"]) == 6

    # filters
    r = c.get("/api/simulation/sim_api1/feed-story?platform=twitter&round=1")
    posts = r.get_json()["data"]["platforms"]["twitter"]["posts"]
    assert [p["post_id"] for p in posts] == [3]
    assert r.get_json()["data"]["platforms"]["twitter"]["rounds"][0]["round"] == 1
    assert c.get("/api/simulation/sim_api1/feed-story?platform=myspace").status_code == 400
    assert c.get("/api/simulation/sim_api1/feed-story?round=x").status_code == 400
    r = c.get("/api/simulation/sim_api1/feed-story?platform=reddit")
    assert r.status_code == 200 and r.get_json()["data"]["platforms"] == {}

    # no database at all -> 404
    empty = tmp_path / "sim_empty"
    empty.mkdir()
    (empty / "state.json").write_text(json.dumps({"project_id": "p", "graph_id": "g"}), encoding="utf-8")
    assert c.get("/api/simulation/sim_empty/feed-story").status_code == 404


def test_events_for_both_platforms_are_brand_posts(sim_dir):
    """A scheduled event with platform "both" (the CLI default) must be flagged as a brand post on every platform."""
    cfg = _config(scheduled=[{"round": 1, "agent": 0, "platform": "both", "content": "Launch day!"}])
    story = fs.build_feed_story(sim_dir, cfg)
    inj = [i for i in fs._injected_posts(cfg) if i["source"] == "scheduled_event"]
    assert inj and inj[0]["platform"] == "both" and inj[0]["brand"]
    for plat in story["platforms"].values():
        for p in plat["posts"]:
            if fs._norm_key(p["content"]) == fs._norm_key("Launch day!"):
                assert p["is_brand"]
