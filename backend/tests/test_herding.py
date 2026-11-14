"""Herding check on the social feed: reactions that follow a post's visible score are separated from posts that are
simply good or bad (the null shuffles each post's own reactions across its rounds); pile-ons on criticism are flagged."""

import random

from app.services import feed_story as fs


def post(seq):
    """seq: (round, +1 | -1) votes; replies are left out so only votes count."""
    votes = {}
    for r, s in seq:
        votes.setdefault(str(r), [0, 0])[0 if s > 0 else 1] += 1
    return {"votes_by_round": votes, "comments": []}


def panel(follow_down=0.0, follow_up=0.0, n=60, seed=1):
    """n posts, each with its own quality q; after a net-negative (positive) score a reaction copies it with the
    given probability, otherwise it is drawn from q."""
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        q, net, seq = rng.random(), 0, []
        for r in range(1, 6):
            rnd = []
            for _ in range(rng.randint(0, 3)):
                if net < 0 and rng.random() < follow_down:
                    s = -1
                elif net > 0 and rng.random() < follow_up:
                    s = 1
                else:
                    s = 1 if rng.random() < q else -1
                rnd.append((r, s))
            net += sum(s for _, s in rnd)
            seq += rnd
        out.append(post(seq))
    return out


def test_follow_counts_treat_one_round_as_simultaneous():
    # round 1: -1 -1 (score 0 before, nothing counted); round 2 sees -2: one down follows, one up does not
    assert fs._follow_counts([1, 1, 2, 2], [-1, -1, -1, 1]) == (2, 1, 0, 0)
    # round 2 sees +1, round 3 sees 0, round 4 sees -1
    assert fs._follow_counts([1, 2, 3, 4], [1, -1, -1, -1]) == (1, 1, 1, 0)


def test_good_and_bad_posts_alone_are_not_herding():
    res = fs.herding_check({"reddit": panel()})
    assert res["verdict"] == "no clear herding" and res["flag"] is False
    assert abs(res["after_negative"]["excess"]) < 0.05
    assert "did not follow" in res["reading"]


def test_pile_on_on_criticism_is_flagged():
    res = fs.herding_check({"reddit": panel(follow_down=0.85)})
    neg = res["after_negative"]
    assert res["verdict"] == "negative pile-on" and res["flag"] is True
    assert neg["p"] < 0.05 and neg["rate"] - neg["shuffled_rate"] >= 0.05
    assert "piled onto criticism" in res["reading"] and "Observational" in res["reading"]


def test_following_approval_is_positive_herding_not_a_pile_on():
    res = fs.herding_check({"twitter": panel(follow_up=0.85)})
    assert res["verdict"] == "positive herding" and res["flag"] is False


def test_replies_count_by_sentiment_and_small_runs_are_not_checked():
    p = {"votes_by_round": {"1": [1, 0]},
         "comments": [{"round": 2, "sentiment": "neg"}, {"round": 2, "sentiment": "neu"}, {"round": 3, "sentiment": "pos"},
                      {"round": None, "sentiment": "neg"}]}
    assert fs._post_reactions(p) == [(1, 1), (2, -1), (3, 1)]
    res = fs.herding_check({"reddit": [p] * 3})
    assert res["verdict"] == "not checked" and "needs 8" in res["reading"]
