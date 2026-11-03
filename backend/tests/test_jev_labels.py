"""Jev as an outside labeller: cached labels, reply sentiment in the feed story, research voices, landing drop causes,
ad-comment concerns for the battlecard and the pitch objection check, all with a fake Jev."""

import importlib.util
import os
import sys

import pytest

from app.services import feed_story, gtm_suite, jev, jev_labels, pitch, research

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("_fs_fixture", os.path.join(_HERE, "test_feed_story.py"))
_fs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fs)
sim_dir = _fs.sim_dir          # re-use the feed story fixture

RULES = [  # (substring, kind -> label)
    ("bahut accha", {"sentiment": "pos"}), ("Sulit", {"sentiment": "pos"}), ("shady", {"sentiment": "neg"}),
    ("scam", {"sentiment": "neg", "concern": "trust"}), ("phone", {"drop": "form"}), ("expensive", {"drop": "price", "concern": "price"}),
    ("later", {"drop": "not_now", "concern": "timing"}), ("FAIL", {}),
]


class FakeJev:
    def __init__(self):
        self.sent = []

    def ask_many(self, jobs, parallel=None, usage=None, **kw):
        out = []
        for state, qs in jobs:
            self.sent.append(state)
            crit = list(qs["label"]["criteria"])
            kind = "sentiment" if "pos" in crit else "drop" if "form" in crit else "concern"
            choice = next((m.get(kind) for k, m in RULES if k in state), None)
            if "FAIL" in state:
                out.append({"ok": False, "error": "boom"})
                continue
            choice = choice or ("neu" if kind == "sentiment" else "other")
            out.append({"ok": True, "model": "jev-test", "answers": {"label": {"choice": choice, "confidence": 0.9}}})
        return out


@pytest.fixture
def fake(monkeypatch):
    f = FakeJev()
    monkeypatch.setattr(jev, "ask_many", f.ask_many)
    monkeypatch.setattr(jev, "available", lambda env=None: True)
    return f


def test_mode_and_enabled(monkeypatch):
    monkeypatch.setattr(jev, "available", lambda env=None: False)
    assert not jev_labels.enabled(env={})
    monkeypatch.setattr(jev, "available", lambda env=None: True)
    assert jev_labels.enabled(env={}) and not jev_labels.enabled(env={"MM_JEV_LABELS": "off"})
    assert jev_labels.mode("weird", env={}) == "auto"


def test_labels_are_cached_deduped_and_failures_stay_empty(fake, tmp_path):
    cache = str(tmp_path / "jev_labels.json")
    texts = ["so shady", "so shady", "Sulit talaga", "FAIL here", ""]
    got = jev_labels.label(texts, "sentiment", cache)
    assert [g["label"] if g else None for g in got] == ["neg", "neg", "pos", None, None]
    assert len(fake.sent) == 3                       # duplicate and empty text not sent
    jev_labels.label(texts, "sentiment", cache)
    assert len(fake.sent) == 4                       # only the failed text is retried; the rest come from the cache
    assert os.path.isfile(cache)


def test_feed_story_uses_the_labeler_and_keeps_the_word_list_as_fallback(fake, sim_dir):
    plain = feed_story.build_feed_story(sim_dir, _fs._config())
    lab = jev_labels.sentiment_labeler(os.path.join(sim_dir, jev_labels.CACHE_FILE))
    story = feed_story.build_feed_story(sim_dir, _fs._config(), labeler=lab)
    assert plain["sentiment_method"] == "lexicon" and story["sentiment_method"] == "jev (jev-test)"
    assert story["sentiment_basis"]["labelled"] == story["sentiment_basis"]["texts"]
    asha = _fs.by_id(story, "twitter")[2]
    assert asha["sentiment"] == "pos"                # 'bahut accha' is Hindi; the word list cannot read it
    bp = next(b for b in story["brand_posts"] if b["platform"] == "twitter")
    assert bp["best_reply"]["sentiment"] != "neg" and bp["worst_reply"]["sentiment"] != "pos"   # ranked by the shown label
    brand = _fs.by_id(story, "twitter")[1]
    rs = brand["reply_sentiment"]
    assert rs["neg"] >= 1 and rs["pos"] >= 1


def test_feed_story_without_key_falls_back(monkeypatch, sim_dir):
    monkeypatch.setattr(jev, "available", lambda env=None: False)

    def boom(*a, **k):
        raise jev.JevUnavailable("no key")
    monkeypatch.setattr(jev, "ask_many", boom)
    lab = jev_labels.sentiment_labeler(None)
    story = feed_story.build_feed_story(sim_dir, _fs._config(), labeler=lab)
    plain = feed_story.build_feed_story(sim_dir, _fs._config())
    assert [p["sentiment"] for p in story["platforms"]["twitter"]["posts"]] == \
           [p["sentiment"] for p in plain["platforms"]["twitter"]["posts"]]


def test_research_quotes_get_model_sentiment(fake, tmp_path):
    def get(url, json_=False):
        return "Ang mahal, too expensive, parang scam" if "a.example" in url else "Sulit talaga, recommended"
    res = research.run("fitness app", [], str(tmp_path), urls=["https://a.example", "https://b.example"], get=get,
                       labeler=jev_labels.sentiment_labeler(str(tmp_path / "c.json")))
    s = res["summary"]
    assert s["sentiment_model"]["counts"] == {"neg": 1, "pos": 1} and "jev (jev-test)" in s["sentiment_model"]["method"]
    assert s["sentiment_method"] == "word list, not a model"          # the word list still picks the voices
    assert all("sentiment_model" in q for q in __import__("json").load(open(res["files"]["json"]))["quotes"])
    assert "A model labelled them too" in open(res["files"]["md"]).read()


def test_drop_causes_ranked_overall_and_per_ad(fake, tmp_path):
    sessions = [{"creative_id": "a1", "landing": {"drop_reason": "asked for my phone number"}},
                {"creative_id": "a1", "landing": {"drop_reason": "why do they need my phone"}},
                {"creative_id": "b2", "landing": {"drop_reason": "too expensive for me"}},
                {"creative_id": "b2", "landing": {"drop_reason": "maybe later"}},
                {"creative_id": "b2", "landing": {}}]
    dc = jev_labels.drop_causes({"sessions": sessions}, str(tmp_path / "c.json"))
    assert dc["overall"][0]["cause"] == "form" and dc["overall"][0]["count"] == 2 and dc["reasons"] == 4
    assert {c["cause"] for c in dc["per_creative"]["b2"]} == {"price", "not_now"}
    assert jev_labels.drop_causes({"sessions": [{"landing": {}}]}) is None


def test_ad_comments_get_a_concern_type(fake):
    items = [{"type": "", "text": "looks like a scam", "source": "ad comment"},
             {"type": "", "text": "nice colours", "source": "ad comment"},
             {"type": "price", "text": "too expensive", "source": "survey"}]
    assert jev_labels.label_concerns(items) == 2
    assert items[0]["type"] == "trust" and items[0]["type_by"] == "jev" and items[2]["type"] == "price"
    extra = gtm_suite._ad_comment_concerns([{"type": "", "text": "looks like a scam", "source": "ad comment"},
                                            {"type": "price", "text": "too expensive", "source": "survey"}])
    assert extra["by_type"] == {"trust": 1} and "not used to choose rebuttals" in extra["note"]
    assert [x for x in gtm_suite.gather_objections(None, None, {"sessions": [{"ad": {"comment": "scam?"}}]})][0]["type"] == ""


def test_pitch_objection_check_against_self_tags(fake):
    res = {"people": [{"agent_id": 1, "turn1": {"objection": "feels like a scam", "objection_type": "trust"}},
                      {"agent_id": 2, "turn1": {"objection": "too expensive", "objection_type": "trust"}},
                      {"agent_id": 3, "turn1": {"objection": "", "objection_type": "none"}}]}
    chk = jev_labels.pitch_objection_check(res, pitch.OBJECTION_TYPES)
    assert chk["labelled"] == 2 and chk["agreement"]["n"] == 2 and chk["disagreements"][0]["jev"] == "price"
    assert jev_labels.pitch_objection_check({"people": []}, pitch.OBJECTION_TYPES) is None


def test_dashboard_shows_the_checks():
    sys.path.insert(0, os.path.join(_HERE, "..", "claude_cli"))
    import feed_view
    import report_view
    note = report_view._objection_check_note({"model": "jev-1.14", "agreement": {"n": 10, "pct": 70.0, "lo": 40.0, "hi": 89.0}})
    assert "70%" in note and "own tag chose the rebuttal" in note
    assert report_view._objection_check_note(None) == ""
    html = feed_view._landing_html({"clicks": 10, "page_loaded": 8, "form_started": 4, "converted": 1,
                                    "drop_causes": [{"cause": "form", "count": 3, "share_pct": 60.0, "examples": ["phone?"]}]})
    assert "form" in html and "60" in html and "Jev" in html
    part = feed_view._landing_html({"clicks": 10, "page_loaded": 8, "form_started": 4, "converted": 1,
                                    "drop_reasons": [{"reason": "no idea why", "count": 1}],
                                    "drop_causes": [{"cause": "form", "count": 1, "share_pct": 100.0}],
                                    "drop_causes_basis": {"labelled": 1, "reasons": 2}})
    assert "1 of 2 reasons" in part and "no idea why" in part
