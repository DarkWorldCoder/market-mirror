"""Feed test and analyst panel with a mocked LLM: assignment, social proof, landing page, metrics, API."""

import json
import re
import threading
from types import SimpleNamespace

import pytest

from app.services import analyst_panel as ap
from app.services import feed_test as ft


class FakeLLM:
    """Students click Instagram ads; parents comment on Facebook; Reddit downvotes; slow pages lose people."""

    def __init__(self):
        self.prompts = []
        self.lock = threading.Lock()
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        system, user = kw["messages"][0]["content"], kw["messages"][1]["content"]
        with self.lock:
            self.prompts.append((system, user))
        if system == ft.ORGANIC_SYSTEM:
            body = {"posts": [{"kind": "friend", "author": f"Friend {i}", "text": f"post {i}", "media": ""} for i in range(8)]}
        elif system == ft.LANDING_SYSTEM:
            body = {"read": True, "started_form": True, "completed": "phone" not in user.lower(),
                    "drop_reason": "did not want to give my phone number", "thought": "ok"}
        elif system == ft.SYSTEM_PROMPT:
            ids = re.findall(r"^\[(i\d+)\]", user, re.M)
            ad_line = next(l for l in user.splitlines() if "· Sponsored" in l or "· Promoted" in l)
            ad_id = re.match(r"\[(i\d+)\]", ad_line).group(1)
            student = "Student" in user
            platform = "Instagram" if "Instagram" in user else "Reddit" if "Reddit" in user else "Facebook"
            items = []
            for i in ids:
                a = {"id": i, "stopped": False, "dwell_seconds": 0.4, "reaction": "none", "comment": "", "share": "none",
                     "click": False, "hide": False, "thought": "scroll"}
                if i == ad_id:
                    if platform == "Instagram" and student:
                        a.update(stopped=True, dwell_seconds=4, reaction="like", click=True, thought="nice")
                    elif platform == "Facebook" and not student:
                        a.update(stopped=True, dwell_seconds=6, reaction="love", comment="Is it really free?", share="send")
                    elif platform == "Reddit":
                        a.update(stopped=True, dwell_seconds=2, reaction="downvote", comment="ad spam", hide=True)
                items.append(a)
            body = {"items": items}
        else:  # analyst panel
            lens = re.search(r"Your lens: ([^.]+)\.", user).group(1)
            body = {"headline": f"{lens} view", "sentiment": 20 if "Sceptical" not in lens else -10,
                    "purchase_intent_signal": 6, "best_audience": "Students" if "Copywriter" not in lens else "Parents",
                    "best_message": "#1", "themes": [{"theme": "free mock test", "weight": 8, "evidence": "Is it really free?"},
                                                     {"theme": lens.split()[0] + " angle", "weight": 3, "evidence": ""}],
                    "objections": ["scam fears"], "opportunities": ["parents"], "risks": [], "recommendation": "test more",
                    "confidence": 6, "evidence_gaps": "small sample"}
        msg = SimpleNamespace(content=json.dumps(body))
        return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")])


def people(n=12):
    out = []
    for i in range(n):
        student = i % 2 == 0
        out.append({"agent_id": i, "name": f"Name{i} Last", "persona": "Student who loves exams" if student else "Parent paying fees",
                    "age": 18 if student else 45, "gender": "female", "country": "Nepal",
                    "segment": "Students" if student else "Parents", "communities": [],
                    "income": "low" if i % 3 == 0 else "high", "thinking_style": "busy and distracted" if i == 4 else ""})
    return out


CREATIVES = [
    {"id": "ig1", "platform": "instagram", "text": "Free mock test", "headline": "See your score", "cta": "Sign up", "page": "CSCA.ai"},
    {"id": "ig2", "platform": "instagram", "text": "Scholarship readiness", "cta": "Learn more", "page": "CSCA.ai"},
    {"id": "fb1", "platform": "facebook", "text": "Parents: plan before you pay an agent", "page": "CSCA.ai", "segments": ["Parents"]},
    {"id": "rd1", "platform": "reddit", "text": "We built a free CSCA practice site", "page": "u/csca_ai"},
]


def test_normalize_and_validation():
    cs = ft.normalize_creatives(CREATIVES + [{"platform": "Twitter", "headline": "x"}])
    assert cs[-1]["platform"] == "x" and cs[-1]["id"] == "ad5"
    with pytest.raises(ValueError):
        ft.normalize_creatives([{"platform": "myspace", "text": "x"}])
    with pytest.raises(ValueError):
        ft.normalize_creatives([{"platform": "facebook"}])
    with pytest.raises(ValueError):
        ft.normalize_creatives([{"id": "a", "text": "x"}, {"id": "a", "text": "y"}])
    assert ft.normalize_landing(None) is None
    assert ft.normalize_landing({"load_seconds": 500})["load_seconds"] == 60.0


def test_assignment_is_balanced_and_respects_targeting():
    cs = ft.normalize_creatives(CREATIVES)
    plan = ft.assign(cs, people(12))
    ig = [c["id"] for (aid, p), c in plan.items() if p == "instagram"]
    assert sorted((ig.count("ig1"), ig.count("ig2"))) == [6, 6]
    fb = [(aid, c["id"]) for (aid, p), c in plan.items() if p == "facebook"]
    assert len(fb) == 6 and all(aid % 2 == 1 for aid, _ in fb)          # parents only
    assert len([1 for (_, p) in plan if p == "reddit"]) == 12


def test_run_feed_test_metrics_social_proof_landing_projection():
    llm = FakeLLM()
    cs = ft.normalize_creatives(CREATIVES)
    landing = ft.normalize_landing({"load_seconds": 2.5, "language": "English", "form_fields": ["name", "email", "phone"]})
    res = ft.run_feed_test(llm, "m", cs, people(12), waves=3, landing=landing, parallel=4,
                           benchmarks={"instagram": {"cpm": 2.0, "budget": 100, "ctr": 1.5, "currency": "USD"}})
    per = res["summary"]["per_creative"]
    assert res["failed"] == 0 and res["personas_tested"] == 12
    # instagram: students click, parents do not -> about half CTR
    ig = per["ig1"]
    assert ig["impressions"] == 6 and 0 < ig["ctr"] < 100
    assert ig["reactions"].get("like")
    # facebook: parents comment and send to family
    fb = per["fb1"]
    assert fb["comments"] == 6 and fb["share_rate"] == 100.0 and fb["ctr"] == 0.0
    assert fb["comments_list"][0]["text"] == "Is it really free?"
    # reddit: downvotes and hides
    assert per["rd1"]["reactions"] == {"downvote": 12} and per["rd1"]["hide_rate"] == 100.0
    # social proof: later waves saw earlier comments in their feed
    assert any("Is it really free?" in u for s, u in llm.prompts if s == ft.SYSTEM_PROMPT and "· Sponsored" in u and "comments" in u)
    assert fb["proof_effect"] is not None
    # landing: phone field -> nobody completes; some lose the page on slow networks
    lf = ig["landing"]
    assert lf["clicks"] >= 1 and lf["converted"] == 0
    assert lf["page_loaded"] <= lf["clicks"]
    # projection uses real CPM and calibrates CTR to the real platform CTR
    pr = ig["projection"]
    assert pr["impressions"] == 50000 and pr["calibrated"] is True
    assert res["summary"]["calibration"]["instagram"] is not None
    assert res["summary"]["organic_baseline"]["instagram"]["thumb_stop"] == 0.0
    assert set(res["summary"]["ranked"]) == {"ig1", "ig2", "fb1", "rd1"}


def test_people_from_simulation_keeps_personas_only():
    profiles = [{"user_id": 0, "name": "CSCA.ai", "gender": "other", "persona": "brand"},
                {"user_id": 1, "name": "Asha", "gender": "female", "persona": "student", "age": 18},
                {"user_id": 2, "name": "Group", "gender": "other", "persona": "group"}]
    index = [{"agent_id": 0, "kind": "graph"}, {"agent_id": 1, "kind": "persona", "segment": "Students", "income": "low"},
             {"agent_id": 2, "kind": "community"}]
    ps = ft.people_from_simulation(profiles, index)
    assert [p["name"] for p in ps] == ["Asha"] and ps[0]["income"] == "low"


def test_analyst_panel_independent_and_consensus():
    llm = FakeLLM()
    material = ap.normalize_material({"comments": [{"segment": "Parents", "text": "Is it really free?"}],
                                      "survey": ["Looks useful", {"segment": "Students", "quote": "Signed up!"}],
                                      "context": "CSCA mock test"})
    res = ap.run_panel(llm, "m", material, "Which audience?", n=5)
    assert len(res["analysts"]) == 5 and all(a["result"] for a in res["analysts"])
    # each analyst got its own call and never saw another analyst's output
    users = [u for s, u in llm.prompts if s == ap.SYSTEM]
    assert len(users) == 5 and not any("view" in u for u in users)
    c = res["consensus"]
    assert c["best_audience"]["winner"] == "Students" and c["best_audience"]["agreement"] == 100
    assert c["themes"][0]["theme"] == "free mock test" and c["themes"][0]["analysts"] == 5
    assert c["consensus"] in ("strong", "partial")
    with pytest.raises(ValueError):
        ap.normalize_material({"posts": []})


def test_market_api_routes(tmp_path, monkeypatch):
    from app import create_app
    from app.config import Config
    from app.services.simulation_manager import SimulationManager
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path))
    app = create_app()
    app.config.update(TESTING=True)
    c = app.test_client()
    r = c.post("/api/simulation/feed-test", json={"simulation_id": "sim_missing", "creatives": CREATIVES})
    assert r.status_code == 404
    r = c.get("/api/simulation/sim_missing/feed-test")
    assert r.status_code == 404
    r = c.post("/api/simulation/market-task/status", json={"task_id": "nope"})
    assert r.status_code == 404


def test_economics_roi_cpl_cac():
    e = ft.economics(1000, 50, {"close_rate": 20, "deal_value": 300, "gross_margin": 0.8, "monthly_value": 25})
    assert e["cpl"] == 20.0 and e["customers"] == 10.0 and e["cac"] == 100.0
    assert e["revenue"] == 3000.0 and e["roas"] == 3.0
    assert e["roi_pct"] == 140.0 and e["break_even_cpl"] == 48.0 and e["payback_months"] == 5.0
    simple = ft.economics(100, 4, {"lead_value": 30})
    assert simple["cpl"] == 25.0 and simple["roi_pct"] == 20.0
    assert ft.economics(100, None, {}) == {}
