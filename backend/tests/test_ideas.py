"""Test ideas: evidence from raw ad rows and a run summary, generation with a mocked LLM, fallback, API."""

import json
from types import SimpleNamespace

from app.services import ideas as isv

ROWS = [
    {"Ad name": "Price angle", "Campaign name": "Launch", "Country": "IN", "Amount spent (USD)": "120.5", "Impressions": "10000", "Link clicks": "250", "Results": "12"},
    {"Ad name": "Proof angle", "Campaign name": "Launch", "Country": "PH", "Amount spent (USD)": "95", "Impressions": "8000", "Link clicks": "80", "Results": "2"},
    {"Ad name": "Fear angle", "Campaign name": "Launch", "Country": "KE", "Amount spent (USD)": "80", "Impressions": "6000", "Link clicks": "30", "Results": "0"},
]
RUN = {"decision": {"decision": "iterate", "confidence": "low", "summary": "Fix the card step.", "fixes": ["Trust / looks like a scam"]},
       "marketing": {"verdicts": ["0% would sign up, 61% maybe."],
                     "objections": [{"label": "Trust / looks like a scam", "share": 64.3, "count": 18}],
                     "by_segment": [{"key": "India young professionals", "n": 5, "convert_yes": 0, "convert_maybe": 80},
                                    {"key": "Philippines parents", "n": 4, "convert_yes": 0, "convert_maybe": 25}],
                     "messages_ranked": [{"label": "#2 Less than one gym visit", "share": 36, "convert_maybe": 89}],
                     "pricing": {"acceptable_low": 3.0, "acceptable_high": 15.0, "optimal": 5.0}}}


class FakeClient:
    def __init__(self, body):
        self.body = body
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        text = self.body if isinstance(self.body, str) else json.dumps(self.body)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason="stop")],
                               usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))


def test_evidence_from_rows_and_run():
    ev = isv.build_evidence(ROWS, {}, RUN, "brief")
    texts = [s["text"] for s in ev["signals"]]
    assert any("best CTR: 'Price angle' at 2.5%" in t for t in texts)
    assert any("'Fear angle' spent 80" in t and "no conversions" in t for t in texts)
    assert any("cheapest conversions: 'IN'" in t for t in texts)
    assert any("Objection 'Trust / looks like a scam' raised by 64.3%" in t for t in texts)
    assert any("Most willing simulated audience: 'India young professionals'" in t for t in texts)
    assert any("optimal 5" in t for t in texts)
    assert ev["sources"] == ["ads", "run"] and "64.3" in ev["numbers"]
    assert isv.build_evidence([], {}, {}, "")["signals"] == []


def test_generate_keeps_only_evidenced_ideas_and_renders():
    ev = isv.build_evidence(ROWS, {}, RUN)
    body = {"ideas": [
        {"title": "Proof-led creative for PH", "type": "ad", "hypothesis": "If proof, then trust.", "evidence_ids": ["S1", "s4"],
         "audience": "Philippines parents", "platform": "facebook", "what_to_make": "testimonial video", "budget": "100 USD",
         "duration": "5 days", "metric": "CPL", "success_looks_like": "CPL under 10 USD", "priority": "high"},
        {"title": "Guess without evidence", "type": "price", "evidence_ids": []},
        {"title": "Weird type", "type": "spaceship", "evidence_ids": ["S2"], "priority": "urgent"}]}
    out = isv.generate(FakeClient(body), "m", ev, brand="Fitloop", n=5)
    assert out["method"] == "llm" and [i["title"] for i in out["ideas"]] == ["Proof-led creative for PH", "Weird type"]
    first = out["ideas"][0]
    assert first["evidence_ids"] == ["S1", "S4"] and len(first["evidence"]) == 2 and first["how_to_test"]["tool"] == "feedtest"
    assert out["ideas"][1]["type"] == "ad" and out["ideas"][1]["priority"] == "medium"
    md = out["markdown"]
    assert md.startswith("# Fitloop: next tests to run") and "## 1. Proof-led creative for PH" in md and "## Evidence list" in md


def test_fallback_when_llm_returns_garbage():
    ev = isv.build_evidence(ROWS, {}, RUN)
    out = isv.generate(FakeClient("nope"), "m", ev, brand="X")
    assert out["method"] == "fallback" and out["ideas"]
    assert all(i["evidence"] for i in out["ideas"])
    assert any(i["type"] == "message" for i in out["ideas"])


def test_ideas_api(monkeypatch):
    from app import create_app
    from app.api import market
    monkeypatch.setattr(market, "_client", lambda: FakeClient({"ideas": [
        {"title": "A", "type": "ad", "evidence_ids": ["S1"], "hypothesis": "h"}]}))
    app = create_app()
    app.config.update(TESTING=True)
    c = app.test_client()
    assert c.post("/api/simulation/ideas", json={}).status_code == 400
    r = c.post("/api/simulation/ideas", json={"ads": ROWS, "brand": "Fitloop"})
    assert r.status_code == 200
    d = r.get_json()["data"]
    assert d["ideas"][0]["title"] == "A" and d["evidence"]["signals"]
