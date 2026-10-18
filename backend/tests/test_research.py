"""Research: sources with a fake HTTP getter, Reddit block handling, themes, voices, the run outputs."""

import json
import os

from app.services import research as rs

HN = {"hits": [{"objectID": "1", "comment_text": "I loved the <b>home workout</b> app but it crashed on my old Android phone", "author": "a", "created_at": "2026-01-02T00:00:00Z", "points": 12},
               {"objectID": "2", "title": "Ask HN: best home workout app?", "author": "b", "created_at": "2026-02-02T00:00:00Z", "num_comments": 40}]}
APPS = {"results": [{"trackId": 11, "trackName": "FitThing", "description": "Workouts at home", "trackViewUrl": "https://apps.example/11", "sellerName": "Fit Inc",
                     "averageUserRating": 4.4, "userRatingCount": 1200, "formattedPrice": "Free"}]}
RSS = {"feed": {"entry": [{"content": {"label": "Great app, finally something that works offline"}, "title": {"label": "Love it"}, "im:rating": {"label": "5"},
                            "author": {"name": {"label": "u1"}}, "updated": {"label": "2026-03-01T00:00:00-07:00"}},
                           {"content": {"label": "They charged my card after the free trial, scam"}, "title": {"label": "Refund"}, "im:rating": {"label": "1"},
                            "author": {"name": {"label": "u2"}}, "updated": {"label": "2026-03-02T00:00:00-07:00"}}]}}
REDDIT = {"data": {"children": [{"data": {"title": "Home workout apps that are actually free?", "selftext": "Tired of apps that need a card for a trial",
                                          "permalink": "/r/fitness/comments/x/", "author": "r1", "created_utc": 1700000000, "score": 55, "subreddit": "fitness", "num_comments": 12}}]}}


def fake_get(blocked_reddit=False):
    def get(url, timeout=20, params=None, json_=True):
        if "hn.algolia" in url:
            return HN if params.get("tags") == "comment" else {"hits": HN["hits"][1:]}
        if "itunes.apple.com/search" in url:
            return APPS
        if "rss/customerreviews" in url:
            return RSS
        if "reddit.com" in url:
            if blocked_reddit:
                raise ValueError("not JSON (text/html): the source is blocking this client")
            return REDDIT
        if not json_:
            return "<html><title>Landing</title><body><p>15 minute workouts, no card needed</p></body></html>"
        raise AssertionError(url)
    return get


def test_sources_and_sentiment(monkeypatch):
    monkeypatch.setattr(rs.time, "sleep", lambda s: None)
    hn = rs.hacker_news("home workout app", get=fake_get())
    c = next(q for q in hn if q["url"].endswith("id=1"))
    assert len(hn) >= 2 and c["text"].startswith("I loved the home workout app") and c["sentiment"] in ("pos", "neu", "neg")
    apps = rs.app_store("home workout", "in", get=fake_get())
    kinds = [a.get("kind") for a in apps]
    assert kinds == ["listing", "review", "review"] and apps[2]["sentiment"] == "neg" and apps[2]["score"] == 1
    r = rs.reddit("home workout app", "fitness", get=fake_get())
    assert not r["blocked"] and r["quotes"][0]["subreddit"] == "fitness"
    b = rs.reddit("x", get=fake_get(blocked_reddit=True))
    assert b["blocked"] and "browser" in b["note"]
    page = rs.web_page("https://x.example", get=fake_get())
    assert page["kind"] == "page" and "no card needed" in page["text"]


def test_run_writes_files_and_voices(tmp_path, monkeypatch):
    monkeypatch.setattr(rs.time, "sleep", lambda s: None)
    out = rs.run("home workout app", ["hn", "appstore", "reddit"], str(tmp_path), "in", ["fitness"], ["https://x.example"], get=fake_get(blocked_reddit=True), log=lambda m: None)
    s = out["summary"]
    assert s["quotes"] >= 5 and set(s["by_source"]) >= {"hackernews", "appstore", "web"}
    assert s["avg_rating"] == 3.0 and s["notes"] and "Reddit" in s["notes"][0]
    assert os.path.exists(out["files"]["md"]) and os.path.exists(out["files"]["voices"])
    md = open(out["files"]["md"], encoding="utf-8").read()
    assert md.startswith("# What real people say about: home workout app") and "## Notes" in md and "apps.example/11" in md
    voices = json.load(open(out["files"]["voices"], encoding="utf-8"))
    assert voices and all(v["country"] == "in" for v in voices) and any(v["rating"] == 1 for v in voices)
    picked = rs.pick_voices(voices, n=2, country="in")
    assert len(picked) == 2 and {p["sentiment"] for p in picked} >= {"neg"}
    assert rs.pick_voices([], 3) == []


def test_themes_need_repeats():
    qs = [{"text": "offline works great offline", "sentiment": "pos", "url": "u", "source": "x"},
          {"text": "offline mode saved my data plan", "sentiment": "pos", "url": "u", "source": "x"},
          {"text": "the trial charged my card", "sentiment": "neg", "url": "u", "source": "x"}]
    th = rs.themes(qs)
    assert th and th[0]["theme"] == "offline" and th[0]["mentions"] == 2
