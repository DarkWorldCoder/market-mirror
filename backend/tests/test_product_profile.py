"""Product understanding: material compaction, generation with a mocked LLM, fallback, prefill, API."""

import json
from types import SimpleNamespace

from app.services import product_profile as pp

BRIEF = """# Fitloop

## What we sell
Fitloop is a 15-minute home workout app with adaptive coaching and a coach voice in your language. 7-day free trial, then USD 4.99 per month.

## Who buys it
Young professionals in India and the Philippines; working parents in Kenya.

## Competitors
Free YouTube workouts; Cult.fit in India.
"""
GOOD = {"name": "Fitloop", "category": "fitness app", "one_liner": "15-minute home workouts that adapt to you.",
        "what_it_does": "Adaptive coaching, offline, coach voice in your language.",
        "for_whom": [{"segment": "young professionals", "country_hint": "India, Philippines", "job_to_be_done": "stay fit without a gym"},
                     {"segment": "working parents", "country_hint": "Kenya", "job_to_be_done": "fit a workout into a full day"}],
        "pricing": {"model": "subscription", "price_points": ["USD 4.99 per month"], "currency": "USD"},
        "offer": "7-day free trial", "proofs": [], "differentiators": ["works offline", "coach voice in your language"],
        "competitors": [{"name": "YouTube workouts", "how_they_win": "free"}, {"name": "Cult.fit", "how_they_win": "brand and gyms"}],
        "channels": ["Instagram", "TikTok", "Facebook"], "likely_objections": [{"type": "trust", "text": "card for a free trial"}, {"type": "weird", "text": "x"}, "plain string"],
        "brand_voice": "friendly, direct", "funnel_goal": "start the 7-day trial", "kpis": ["trial starts", "CPL"], "unknowns": ["retention"]}


class FakeClient:
    def __init__(self, body):
        self.body = body
        self.prompts = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.prompts.append(kw["messages"][1]["content"])
        text = self.body if isinstance(self.body, str) else json.dumps(self.body)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason="stop")],
                               usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))


def test_html_to_text_and_material():
    page = "<html><head><title>Fitloop</title><meta name='description' content='Home workouts'></head><body><nav>menu</nav><h1>Train</h1><script>x()</script><p>15 min &amp; done</p></body></html>"
    t = pp.html_to_text(page)
    assert t.startswith("Fitloop") and "Home workouts" in t and "Train" in t and "15 min & done" in t
    assert "menu" not in t and "x()" not in t
    m = pp.compact_material(BRIEF, t, {"total": {"spend": 100, "ctr": 1.2, "cpa": 8}, "tables": {"ad": [{"key": "A", "spend": 50, "ctr": 2, "conversions": 3, "cpa": 5}]}}, "Should we launch?")
    assert "## What the user wants to learn" in m and "## Documents" in m and "## Web page" in m and "ad 'A'" in m
    assert pp.compact_material("", "", None) == ""


def test_generate_cleans_and_renders():
    client = FakeClient(GOOD)
    prof = pp.generate(client, "m", pp.compact_material(BRIEF))
    assert prof["method"] == "llm" and prof["name"] == "Fitloop" and prof["usage"]["input_tokens"] == 10
    types = [o["type"] for o in prof["likely_objections"]]
    assert types == ["trust", "other", "other"]                       # unknown type and plain string normalised
    assert "MATERIAL" in client.prompts[0] and "Fitloop" in client.prompts[0]
    text = pp.render_text(prof)
    assert text.startswith("PRODUCT PROFILE: Fitloop (fitness app)") and "Pricing: USD 4.99 per month" in text
    assert "Competitors: YouTube workouts (free)" in text
    ep = pp.graph_episode(prof)
    assert "Fitloop competes with Cult.fit." in ep and "Fitloop targets working parents in Kenya." in ep
    qa = pp.quickstart_answers(prof)
    assert qa["brand"] == "Fitloop" and "USD 4.99" in qa["product"] and qa["platforms"] == "Instagram, TikTok, Facebook"
    assert "young professionals in India, Philippines" in qa["buyers"]


def test_fallback_from_headings():
    prof = pp.generate(FakeClient("not json"), "m", BRIEF, name_hint="Fitloop")
    assert prof["method"] == "fallback" and prof["name"] == "Fitloop"
    assert "USD 4.99 per month" in prof["pricing"]["price_points"]
    assert prof["unknowns"] and "headings only" in prof["unknowns"][0]


def test_profile_api(tmp_path, monkeypatch):
    from app import create_app
    from app.api import product
    from app.models.project import ProjectManager
    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(product, "_client", lambda: FakeClient(GOOD))
    app = create_app()
    app.config.update(TESTING=True)
    c = app.test_client()
    # without a project
    r = c.post("/api/graph/profile", json={"text": BRIEF, "name": "Fitloop"})
    assert r.status_code == 200
    d = r.get_json()["data"]
    assert d["name"] == "Fitloop" and d["quickstart_answers"]["brand"] == "Fitloop"
    assert c.post("/api/graph/profile", json={}).status_code == 400
    # with a project: saved next to the project, episode appended to the text before the graph build
    proj = ProjectManager.create_project("Fitloop test")
    ProjectManager.save_extracted_text(proj.project_id, BRIEF)
    assert c.get(f"/api/graph/project/{proj.project_id}/profile").status_code == 404
    r = c.post(f"/api/graph/project/{proj.project_id}/profile", json={})
    assert r.status_code == 200 and r.get_json()["data"]["graph_episode_added"] is True
    text = ProjectManager.get_extracted_text(proj.project_id)
    assert product.MARKER in text and "Fitloop competes with Cult.fit." in text
    assert pp.load(ProjectManager._get_project_dir(proj.project_id))["name"] == "Fitloop"
    r = c.post(f"/api/graph/project/{proj.project_id}/profile", json={})
    assert r.get_json().get("cached") is True                      # reused unless refresh
    assert c.get(f"/api/graph/project/{proj.project_id}/profile").get_json()["data"]["name"] == "Fitloop"
    assert c.get("/api/graph/project/nope/profile").status_code == 404


def test_project_voices_endpoint(tmp_path, monkeypatch):
    from app import create_app
    from app.models.project import ProjectManager
    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(tmp_path), raising=False)
    app = create_app()
    app.config.update(TESTING=True)
    c = app.test_client()
    proj = ProjectManager.create_project("v")
    assert c.get(f"/api/graph/project/{proj.project_id}/voices").status_code == 404
    r = c.put(f"/api/graph/project/{proj.project_id}/voices", json={"voices": [{"text": "works offline", "source": "hn"}, {"nope": 1}]})
    assert r.get_json()["data"]["stored"] == 1
    assert c.get(f"/api/graph/project/{proj.project_id}/voices").get_json()["data"]["voices"][0]["text"] == "works offline"
    assert c.put(f"/api/graph/project/{proj.project_id}/voices", json={"voices": "x"}).status_code == 400
