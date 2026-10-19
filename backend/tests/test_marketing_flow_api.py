"""Offline API journey from draft plan through normalized actuals to holdout review."""

from app import create_app
from app.config import Config
from app.models.project import ProjectManager
from app.services import product_profile as pp


def test_plan_actuals_and_holdout_api(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path))
    app = create_app()
    app.config.update(TESTING=True)
    client = app.test_client()
    plan = client.post("/api/graph/campaign-plan", json={
        "profile": {"name": "Fitloop", "what_it_does": "Short home workouts",
                    "for_whom": [{"segment": "students", "country_hint": "PH"}]},
        "goal": "trial signup", "budget": {"amount": 120, "currency": "USD"},
        "channels": ["search", "email"]})
    assert plan.status_code == 200
    body = plan.get_json()["data"]
    assert len(body["plan"]["test_specs"]) == 2
    assert body["plan"]["measurement"]["holdout"]
    assert (tmp_path / "campaign_plans").is_dir()

    export = tmp_path / "ads.csv"
    export.write_text("date,market,variant,impressions,clicks\n2026-10-01,PH,A,100,5\n")
    imported = client.post("/api/simulation/actuals-import", json={"file": str(export), "source_type": "ads"})
    assert imported.status_code == 200
    actuals = imported.get_json()["data"]
    assert actuals["summary"]["rows_valid"] == 1
    assert actuals["observations"][0]["quality"] == "user_export_unverified"

    insufficient = client.post("/api/simulation/holdout-backtest", json={"pairs": []})
    assert insufficient.status_code == 200
    assert insufficient.get_json()["data"]["status"] == "insufficient_holdout"
    assert client.post("/api/simulation/holdout-backtest", json={"pairs": {}}).status_code == 400


def test_project_plan_uses_stored_public_feedback(tmp_path, monkeypatch):
    monkeypatch.setattr(ProjectManager, "get_project", lambda _id: {"id": "proj_x"})
    monkeypatch.setattr(ProjectManager, "_get_project_dir", lambda _id: str(tmp_path))
    monkeypatch.setattr(pp, "load", lambda _path: {"name": "Fitloop", "offer": "Short workouts"})
    (tmp_path / "voices.json").write_text(
        '[{"text":"I need brief workouts","url":"https://example.org/review",'
        '"date":"2026-10-01","market":"PH","quality":"public_review_unverified"}]')
    app = create_app()
    app.config.update(TESTING=True)
    response = app.test_client().post("/api/graph/campaign-plan", json={
        "project_id": "proj_x", "goal": "trial signup", "budget": {"amount": 100}})
    assert response.status_code == 200
    plan = response.get_json()["data"]["plan"]
    assert plan["evidence"][0]["source"] == "https://example.org/review"
    assert plan["evidence"][0]["market"] == "PH"
