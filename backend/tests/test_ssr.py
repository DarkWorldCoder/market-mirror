"""Semantic similarity rating with a mocked embedder: distributions, edge cases and the API route."""

import hashlib
import re

import numpy as np
import pytest

from app.services import ssr


class FakeEmbedder:
    """Bag of words hashed into 256 dims: texts sharing words are similar, an anchor matches itself exactly."""

    model_name = "fake-bow"

    def __init__(self, available=True):
        self.available = available
        self.calls = 0

    def embed(self, texts, *, query=False):
        self.calls += 1
        if not self.available:
            return None
        out = []
        for t in texts:
            v = np.zeros(256, dtype=np.float32)
            for w in re.findall(r"[a-z']+", t.lower()):
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 256] += 1
            n = np.linalg.norm(v)
            out.append(v / n if n else v)
        return out


@pytest.fixture(autouse=True)
def _fresh_anchor_cache():
    ssr._anchor_cache.clear()
    yield
    ssr._anchor_cache.clear()


def test_pmf_from_similarities_math():
    p = ssr.pmf_from_similarities(np.array([[0.1, 0.2, 0.3, 0.4, 0.5]]))
    assert p[0] == 0 and p[-1] == pytest.approx(0.4) and p.sum() == pytest.approx(1)   # min subtracted
    flat = ssr.pmf_from_similarities(np.array([[0.3] * 5]))
    assert list(flat) == pytest.approx([0.2] * 5)                                     # ties -> uniform
    sharp = ssr.pmf_from_similarities(np.array([[0.1, 0.2, 0.3, 0.4, 0.5]]), temperature=0.5)
    assert sharp[-1] > p[-1]                                                          # lower temperature sharpens
    two = ssr.pmf_from_similarities(np.array([[0, 0, 0, 0, 1.0], [1.0, 0, 0, 0, 0]]))
    assert list(two) == pytest.approx([0.5, 0, 0, 0, 0.5])                            # averaged over anchor sets
    d = ssr.describe([0, 0, 0, 0.5, 0.5])
    assert d["mean"] == 4.5 and d["sd"] == 0.5 and d["score10"] == 8.75


def test_every_scale_has_full_anchor_sets():
    for scale, sets in ssr.ANCHORS.items():
        assert len(sets) >= 3, scale
        assert all(len(s) == ssr.POINTS for s in sets), scale


def test_rate_maps_free_text_to_the_right_end_of_the_scale():
    emb = FakeEmbedder()
    res = ssr.rate([("purchase", "I would definitely do it."),
                    ("purchase", "No way, I definitely would not do this."),
                    ("trust", "   "), ("mood", "happy"), ("interest", None),
                    ("trust", "I don't trust this at all, it looks like a scam.")], embedder=emb)
    yes, no, empty, unknown, missing, scam = res
    # the bag-of-words fake only knows shared words, so check direction and peaks, not calibrated means
    assert yes["mean"] > 3 and yes["pmf"][4] == max(yes["pmf"])
    assert no["mean"] < 2.5 and no["pmf"][0] == max(no["pmf"])
    assert empty is None and unknown is None and missing is None
    assert scam["mean"] < 2.5 and scam["pmf"][0] == max(scam["pmf"])
    for r in (yes, no, scam):
        assert sum(r["pmf"]) == pytest.approx(1, abs=1e-3) and 1 <= r["mean"] <= 5 and r["sd"] > 0
    calls = emb.calls
    ssr.rate([("purchase", "maybe")], embedder=emb)
    assert emb.calls == calls + 1                         # anchors are embedded once per model and cached


def test_lead_sentence_keeps_only_the_opening_verdict():
    assert ssr.lead_sentence("Probably not. The auto-renewal worries me.") == "Probably not."
    assert ssr.lead_sentence("  Maybe!  Only if reviews are good.") == "Maybe!"
    assert ssr.lead_sentence("Yes, at 4.5 a month it is cheaper than a gym") == "Yes, at 4.5 a month it is cheaper than a gym"
    assert ssr.lead_sentence("नहीं। मुझे भरोसा नहीं है।") == "नहीं।"                      # Devanagari danda
    assert ssr.lead_sentence("不会。太贵了。") == "不会。"                                  # CJK full stop, no space
    assert ssr.lead_sentence("Honestly? Maybe 20-30% likely.") == "Honestly?"         # joining scored worse
    assert ssr.lead_sentence("No") == "No" and ssr.lead_sentence("   ") == "" and ssr.lead_sentence(None) == ""


def test_rate_embeds_only_the_first_sentence():
    emb = FakeEmbedder()
    text = "I would definitely do it. There is no way I definitely would not, I will certainly not go ahead."
    lead, full = ssr.rate([("purchase", text)], embedder=emb)[0], ssr.rate([("purchase", text)], embedder=emb, lead_only=False)[0]
    assert lead == ssr.rate([("purchase", "I would definitely do it.")], embedder=emb)[0]
    assert lead["mean"] > full["mean"] and lead["pmf"][4] == max(lead["pmf"])   # trailing reasons no longer drag it down
    assert ssr.ANCHORS_VERSION != "2026-10-ssr-v1"                                   # cached ratings are marked stale


def test_rate_raises_when_embeddings_are_unavailable():
    with pytest.raises(ssr.SSRUnavailable):
        ssr.rate([("purchase", "yes")], embedder=FakeEmbedder(available=False))
    assert ssr.rate([("purchase", "")], embedder=FakeEmbedder(available=False)) == [None]   # nothing to embed


def test_ssr_api_route(monkeypatch):
    from app import create_app
    app = create_app()
    app.config.update(TESTING=True)
    c = app.test_client()
    monkeypatch.setattr(ssr, "get_embedder", lambda: FakeEmbedder())
    r = c.post("/api/simulation/ssr", json={"items": [
        {"id": "0:purchase", "scale": "purchase", "text": "I would definitely do it."},
        {"id": "0:trust", "scale": "trust", "text": ""},
        {"id": "1:recommend", "scale": "recommend", "text": "I'd warn my friends against it."}]})
    assert r.status_code == 200
    data = r.get_json()["data"]
    assert data["model"] == "fake-bow" and data["anchors_version"] == ssr.ANCHORS_VERSION
    by_id = {x["id"]: x for x in data["results"]}
    assert set(by_id) == {"0:purchase", "1:recommend"}                    # empty text is skipped
    assert by_id["0:purchase"]["mean"] > by_id["1:recommend"]["mean"]
    assert len(by_id["0:purchase"]["pmf"]) == 5
    assert c.post("/api/simulation/ssr", json={"items": "nope"}).status_code == 400
    monkeypatch.setattr(ssr, "get_embedder", lambda: FakeEmbedder(available=False))
    r = c.post("/api/simulation/ssr", json={"items": [{"id": "x", "scale": "purchase", "text": "yes"}]})
    assert r.status_code == 503 and "unavailable" in r.get_json()["error"]
