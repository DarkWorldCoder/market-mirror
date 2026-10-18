"""Plain-language market report: fact sheet, generation with a mocked LLM, number guard, fallback, API."""

import json
from types import SimpleNamespace

import pytest

from app.services import market_report as mr

BUNDLE = {
    "summary": {"decision": {"decision": "iterate", "confidence": "low", "summary": "Fix the card step.",
                             "fixes": ["Trust / looks like a scam"]},
                "marketing": {"verdicts": ["0% would sign up, 61% maybe."], "answered": 28,
                              "overall": {"convert_yes": 0.0, "convert_maybe": 61.0, "click_yes": 24.0, "interest": 5.8,
                                          "trust": 3.6, "nps": -96, "ssr": {"purchase": {"mean": 2.4}}},
                              "by_segment": [{"key": "India young professionals", "n": 5, "convert_yes": 0, "convert_maybe": 80,
                                              "click_yes": 40, "interest": 6.6, "trust": 4.0, "top_objection": "trust",
                                              "ssr": {"purchase": {"mean": 3.1}}},
                                             {"key": "Philippines parents", "n": 4, "convert_yes": 0, "convert_maybe": 25,
                                              "click_yes": 0, "interest": 5.0, "trust": 3.0, "top_objection": "trust"}],
                              "objections": [{"label": "Trust / looks like a scam", "share": 64.3, "count": 18,
                                              "examples": [{"segment": "Philippines parents", "text": "Bakit kailangan ng card?",
                                                            "fix": "Show it is really free"}]}],
                              "messages_ranked": [{"key": "#2", "label": "#2 Less than one gym visit", "votes": 10, "share": 36,
                                                   "convert_yes": 0, "convert_maybe": 89, "reaction": 5.4}],
                              "pricing": {"acceptable_low": 3.0, "acceptable_high": 15.0, "optimal": 5.0, "answers": 28,
                                          "by_segment": [{"key": "Students", "n": 6, "cheap": 3.99, "expensive": 9, "too_expensive": 15.5}]},
                              "quotes_yes": [], "quotes_no": [{"text": "Not giving my card for a trial."}],
                              "playbook": [{"segment": "India young professionals", "priority": "medium", "lead_with": "#2",
                                            "preempt": "Trust", "answer_with": "Show it is free", "seed_in": "Bengaluru Fitness Buddies"}]}},
    "project": {"simulation_requirement": "Simulate buyers of Fitloop in India."},
    "config": {"persona_index": [
        {"agent_id": 0, "name": "Fitloop", "kind": "graph"},
        {"agent_id": 1, "name": "Priya Menon", "kind": "persona", "segment": "India young professionals", "country": "India",
         "city": "Pune", "age": 31, "occupation": "marketing coordinator", "interview_summary": "I am Priya. Money is tight."},
        {"agent_id": 2, "name": "Rosario Santos", "kind": "persona", "segment": "Philippines parents", "country": "Philippines"}]},
    "feed_test": {"creatives": [{"id": "ig_price", "name": "Cheaper than a gym visit", "platform": "instagram", "page": "Fitloop",
                                 "text": "A month of Fitloop costs less than one gym visit."}],
                  "summary": {"ranked": ["ig_price"], "per_creative": {"ig_price": {
                      "impressions": 14, "noticed": 28.6, "thumb_stop": 14.3, "ctr": 14.3, "expected_ctr": 8.29, "hide_rate": 0.0,
                      "comments": 1, "comments_list": [{"text": "Is it really free?"}],
                      "landing": {"clicks": 2, "page_loaded": 2, "form_started": 1, "converted": 1},
                      "projection": {"budget": 300.0, "currency": "USD", "clicks": 4320, "cpc": 0.07, "conversions": 12.5, "cpl": 24.0,
                                     "roas": 1.2, "roi_pct": 2.0}}}},
                  "multi_seed": {"winner_agreement": 67}, "landing": {"load_seconds": 2.5}},
    "survey": {"offer": "Fitloop 7-day trial", "goal": "start the 7-day free trial", "currency": "USD"},
    "analyst_panel": {"consensus": {"analysts_ok": 5, "consensus": "weak", "success_probability": 25,
                                    "verdict": {"winner": "iterate"}, "best_audience": {"winner": "India young professionals"},
                                    "themes": [{"theme": "Card requirement = trust barrier", "analysts": 3, "evidence": ["card upfront is a red flag"]}]}},
    "feed_story": {"brand_posts": [{"platform": "twitter", "round": 0, "content": "Fitloop is live!", "likes": 3, "quotes": [1],
                                    "comments": [{"content": "free ba talaga?"}], "reply_sentiment": {"pos": 1, "neg": 1, "neu": 0}}],
                   "platforms": {"reddit": {"posts": [{"author": {"segment": "Students", "country": "India"}, "round": 2,
                                                        "content": "Tried it, meh", "likes": 4, "reach_proxy": 9,
                                                        "comments": [{"content": "same"}]}]}}, "sentiment_method": "lexicon"},
}

GOOD = {
    "executive_summary": {"decision": "iterate", "headline": "Promising, but the card step blocks sign-ups.",
                          "bullets": ["About 6 in 10 simulated people said maybe (61%).", "Trust was the top objection (64.3%).",
                                      "The best ad reached an expected CTR of 8.29%."]},
    "what_we_tested": "We tested the Fitloop 7-day trial with 28 simulated people.",
    "who_we_simulated": [{"segment": "India young professionals", "people": 5, "where": "India", "in_short": "Open but wary.",
                          "example_person": "Priya Menon, 31, Pune"}],
    "social": {"summary": "People asked if it is free.", "themes": ["card worry"], "brand_post_notes": ["Launch post: 3 likes"],
               "best_reaction": "free ba talaga?", "worst_reaction": "Tried it, meh"},
    "ad_results": {"summary": "ig_price did best.", "winner": "ig_price: cheapest clicks", "table_notes": ["ig_price: 14.3% CTR"],
                   "landing_page": "1 of 2 converted; the card step lost one."},
    "survey_results": {"summary": "Nobody committed; 61% maybe.", "best_audience": "India young professionals",
                       "weakest_audience": "Philippines parents", "message_winner": "#2"},
    "objections": [{"objection": "Trust / looks like a scam", "who": "Philippines parents", "share_pct": 64.3,
                    "quote": "Bakit kailangan ng card?", "answer_line": "No card needed for the first 7 days."}],
    "pricing": {"summary": "People accept 3 to 15 dollars.", "recommended_price": "5", "range": "3 to 15"},
    "sales_notes": {"objection_handling": [{"when_they_say": "Why a card?", "you_say": "We removed it."}],
                    "icp": [{"segment": "India young professionals", "lead_score": 48, "why": "highest maybe", "best_channel": "Instagram",
                             "first_message": "Hi Priya..."}], "do_not_chase": "Philippines parents for now"},
    "action_plan": {"ads": [{"creative_id": "ig_price", "audience": "India young professionals", "platforms": ["instagram"],
                             "budget": "300 USD", "duration": "7 days", "why": "best CTR"}],
                    "fixes": ["Remove the card step from the trial"], "messages_to_use": ["Less than one gym visit"],
                    "retest": {"when": "in 2 weeks", "what": "same ads without the card step", "success_looks_like": "a firm yes from 2 in 10"}},
    "limits": {"confidence": "low", "caveats": ["Simulated people"], "what_would_raise_confidence": ["A 300 USD real test"],
               "reliability_note": "ad winner agreed in 67% of seeds"},
    "budget_plan": {"total": "300 USD", "lines": [{"where": "ig_price to India young professionals", "share_pct": 60, "amount": "180 USD",
                                                   "expected_cpl": "24 USD", "why": "cheapest leads"}], "hold_back": "20% for the retest"},
    "thirty_day_plan": [{"week": 1, "do": "Remove the card step", "owner": "product", "measure": "trial starts"}],
    "what_would_change_the_decision": ["A firm yes from 2 in 10 after the card fix"],
    "risks": [{"risk": "Card fix slips", "likelihood": "medium", "mitigation": "Ship email-only trial first"}],
}
GOOD["ad_results"]["so_what"] = "Run ig_price first."
GOOD["ad_results"]["confidence"] = "medium"


class FakeClient:
    def __init__(self, body):
        self.body = body
        self.prompts = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.prompts.append(kw["messages"][1]["content"])
        text = self.body if isinstance(self.body, str) else json.dumps(self.body)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason="stop")],
                               usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50))


def test_compact_material_collects_every_source():
    m = mr.compact_material(BUNDLE)
    assert m["brand"] == "Fitloop" and m["people_total"] == 2
    assert m["decision"]["decision"] == "iterate"
    assert m["ads"][0]["id"] == "ig_price" and m["ads"][0]["projection"]["cpl"] == 24.0
    seg = m["survey"]["by_segment"][0]
    assert seg["segment"] == "India young professionals" and 0 <= seg["lead_score"] <= 100
    assert seg["lead_score"] > m["survey"]["by_segment"][1]["lead_score"]
    assert m["objections"][0]["examples"][0]["quote"].startswith("Bakit")
    assert m["social"]["brand_posts"][0]["comments"] == 1 and m["social"]["top_posts"][0]["platform"] == "reddit"
    assert m["panel"]["verdict"] == "iterate" and m["who"][0]["examples"][0]["summary"].startswith("I am Priya")
    assert m["budget"]["per_ad"][0]["projected_cpl"] == 24.0
    assert m["budget"]["total_benchmark_budget"] == 300.0


def test_generate_renders_markdown_with_all_sections():
    client = FakeClient(GOOD)
    out = mr.generate(client, "m", mr.compact_material(BUNDLE))
    assert out["method"] == "llm" and out["usage"]["input_tokens"] == 100
    md = out["markdown"]
    for h in ("# Fitloop: market test report", "**Decision: ITERATE.**", "## What we tested", "## Who we simulated",
              "## What happened on social media", "## Ad results", "## Survey results", "## Objections and how to answer them",
              "## Pricing", "## Sales notes", "## Action plan", "## Limits and confidence"):
        assert h in md, h
    assert "| ig_price | India young professionals | instagram | 300 USD | 7 days |" in md
    for h in ("## Budget plan", "## The next 30 days", "## What would change the decision", "## Risks", "**So what:** Run ig_price first.",
              "_Confidence: medium_", "Reliability: ad winner agreed in 67% of seeds", "| 1 | Remove the card step | product | trial starts |"):
        assert h in md, h
    assert "Answer with: *No card needed for the first 7 days.*" in md
    assert out["action_plan"]["fixes"] == ["Remove the card step from the trial"]
    assert "FACTS" in client.prompts[0] and "Fitloop" in client.prompts[0]


def test_number_guard_drops_invented_numbers():
    bad = json.loads(json.dumps(GOOD))
    bad["what_we_tested"] = "We tested with 28 simulated people. Sales rose 437% last year. Trust was 64.3%."
    out = mr.generate(FakeClient(bad), "m", mr.compact_material(BUNDLE))
    assert "437%" not in out["markdown"] and "28 simulated people" in out["markdown"] and "64.3%" in out["markdown"]


def test_fallback_on_bad_json():
    out = mr.generate(FakeClient("not json at all"), "m", mr.compact_material(BUNDLE))
    assert out["method"] == "fallback"
    assert "**Decision: ITERATE.**" in out["markdown"] and "## Sales notes" in out["markdown"]
    assert out["action_plan"]["fixes"] == ["Trust / looks like a scam"]
    assert "## The next 30 days" in out["markdown"] and "## Budget plan" in out["markdown"]   # from the projections
    assert out["sections"]["budget_plan"]["lines"][0]["expected_cpl"].startswith("24.0")


def test_market_report_api(tmp_path, monkeypatch):
    from app import create_app
    from app.config import Config
    from app.services.simulation_manager import SimulationManager
    from app.api import market
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path))
    sim = tmp_path / "sim_r"
    sim.mkdir()
    (sim / "state.json").write_text(json.dumps({"simulation_id": "sim_r", "project_id": "p", "graph_id": "g", "status": "ready"}))
    monkeypatch.setattr(market, "_client", lambda: FakeClient(GOOD))
    app = create_app()
    app.config.update(TESTING=True)
    c = app.test_client()
    assert c.post("/api/simulation/market-report", json={"simulation_id": "sim_r"}).status_code == 400
    r = c.post("/api/simulation/market-report", json={"simulation_id": "sim_r", "material": BUNDLE})   # raw bundle: API compacts it
    assert r.status_code == 200
    task_id = r.get_json()["data"]["task_id"]
    import time
    for _ in range(100):
        st = c.post("/api/simulation/market-task/status", json={"task_id": task_id}).get_json()["data"]
        if st["status"] in ("completed", "failed"):
            break
        time.sleep(0.05)
    assert st["status"] == "completed", st
    raw = c.get("/api/simulation/sim_r/market-report").get_json()
    assert raw.get("data"), (raw, st)
    got = raw["data"]
    assert got["method"] == "llm" and "## Action plan" in got["markdown"]
    assert "# Fitloop: market test report" in got["markdown"]          # brand came from the compacted facts
