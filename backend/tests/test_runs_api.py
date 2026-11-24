"""Workspace runs API: token and loopback guard, listing, detail, file reads and path checks."""

import json
import os
from pathlib import Path

import pytest

from app import create_app
from app.api import setup as setup_api


@pytest.fixture
def client(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    (root / "acme").mkdir(parents=True)
    (root / "acme" / "run_manifest.json").write_text(json.dumps({"title": "Acme test", "simulation_id": "sim_1",
                                                                  "finished_at": "2026-11-23T10:00:00"}))
    (root / "acme" / "summary.json").write_text(json.dumps({"decision": {"decision": "iterate", "summary": "Fix price"},
                                                             "marketing": {"people": 40}}))
    (root / "acme" / "disclosure.md").write_text("# How this was made")
    (root / "acme" / "dashboard.html").write_text("<html>dash</html>")
    (root / "acme" / "secret.env").write_text("KEY=1")
    (root / "_preview").mkdir()
    (root / "_preview" / "summary.json").write_text("{}")
    (root / "empty").mkdir()
    monkeypatch.setenv("MIROFISH_RUNS_DIR", str(root))
    monkeypatch.setattr(setup_api, "SETUP_TOKEN", "tok")
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


H = {"X-Setup-Token": "tok"}


def test_needs_the_setup_token(client):
    assert client.get("/api/runs").status_code == 403
    assert client.get("/api/runs", headers={"X-Setup-Token": "nope"}).status_code == 403


def test_lists_runs_with_their_cards(client):
    runs = client.get("/api/runs", headers=H).get_json()["data"]["runs"]
    assert [r["name"] for r in runs] == ["acme"]               # folders starting with _ and empty ones are skipped
    r = runs[0]
    assert (r["title"], r["decision"], r["people"], r["simulation_id"], r["has_dashboard"]) == \
        ("Acme test", "iterate", 40, "sim_1", True)


def test_detail_and_files(client):
    d = client.get("/api/runs/acme", headers=H).get_json()["data"]
    assert d["files"] == ["dashboard.html", "disclosure.md", "run_manifest.json", "summary.json"]
    assert client.get("/api/runs/acme/files/summary.json", headers=H).get_json()["data"]["marketing"]["people"] == 40
    md = client.get("/api/runs/acme/files/disclosure.md", headers=H)
    assert md.status_code == 200 and b"How this was made" in md.data
    html = client.get("/api/runs/acme/files/dashboard.html", headers=H)
    assert "sandbox" in html.headers["Content-Security-Policy"]
    dl = client.get("/api/runs/acme/files/disclosure.md?download=1", headers=H)
    assert "attachment" in dl.headers.get("Content-Disposition", "")


@pytest.mark.parametrize("path", ["/api/runs/..", "/api/runs/missing", "/api/runs/acme/files/secret.env",
                                  "/api/runs/acme/files/..%2Fsummary.json", "/api/runs/acme/files/nope.json",
                                  "/api/runs/_preview/files/summary.json"])
def test_refuses_unknown_or_unsafe_paths(client, path):
    assert client.get(path, headers=H).status_code in (404, 403)


def test_listing_includes_more_than_two_hundred_runs(client):
    root = Path(os.environ["MIROFISH_RUNS_DIR"])
    for i in range(205):
        run = root / f"run-{i:03}"
        run.mkdir()
        (run / "summary.json").write_text("{}")
    runs = client.get("/api/runs", headers=H).get_json()["data"]["runs"]
    assert len(runs) == 206
    assert {r["name"] for r in runs} == {"acme", *(f"run-{i:03}" for i in range(205))}


@pytest.mark.parametrize("summary,manifest", [([], []), ([1], "bad"),
    ({"marketing": [], "decision": "bad", "agents": 4}, {}),
    ({"marketing": {"people": 0}, "decision": [1], "agents": 4}, {})])
def test_malformed_metadata_does_not_break_listing_or_detail(client, summary, manifest):
    run = Path(os.environ["MIROFISH_RUNS_DIR"]) / "acme"
    (run / "summary.json").write_text(json.dumps(summary))
    (run / "run_manifest.json").write_text(json.dumps(manifest))
    (run / "run_status.json").write_text("[]")
    listed = client.get("/api/runs", headers=H)
    detail = client.get("/api/runs/acme", headers=H)
    assert listed.status_code == detail.status_code == 200
    data = detail.get_json()["data"]
    assert isinstance(data["summary"], dict) and isinstance(data["manifest"], dict)
    if isinstance(summary, dict) and summary.get("marketing") == {"people": 0}:
        assert data["people"] == 0


def test_status_and_file_count_are_exposed(client):
    run = Path(os.environ["MIROFISH_RUNS_DIR"]) / "acme"
    (run / "run_status.json").write_text(json.dumps({"runner_status": "running", "progress_percent": 25,
        "current_round": 1, "total_rounds": 4}))
    card = client.get("/api/runs", headers=H).get_json()["data"]["runs"][0]
    assert (card["status"], card["progress_percent"], card["current_round"], card["total_rounds"]) == ("running", 25, 1, 4)
    assert card["file_count"] == 5


def test_symlink_runs_and_files_are_never_exposed(client, tmp_path):
    root = Path(os.environ["MIROFISH_RUNS_DIR"])
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "summary.json").write_text('{"project_name":"private"}')
    (root / "external").symlink_to(outside, target_is_directory=True)
    (root / "alias").symlink_to(root / "acme", target_is_directory=True)
    (root / "acme" / "leak.json").symlink_to(outside / "summary.json")
    (root / "acme" / "leak.md").symlink_to(outside / "summary.json")
    (root / "linked-metadata").mkdir()
    (root / "linked-metadata" / "summary.json").symlink_to(outside / "summary.json")
    runs = client.get("/api/runs", headers=H).get_json()["data"]["runs"]
    assert [r["name"] for r in runs] == ["acme"]
    detail = client.get("/api/runs/acme", headers=H).get_json()["data"]
    assert "leak.json" not in detail["files"] and "leak.md" not in detail["files"]
    for url in ["/api/runs/external", "/api/runs/alias", "/api/runs/acme/files/leak.json", "/api/runs/acme/files/leak.md"]:
        assert client.get(url, headers=H).status_code == 404


def test_invalid_json_metadata_is_tolerated_but_cannot_be_read(client):
    run = Path(os.environ["MIROFISH_RUNS_DIR"]) / "acme"
    (run / "summary.json").write_text("{broken")
    assert client.get("/api/runs", headers=H).status_code == 200
    assert client.get("/api/runs/acme", headers=H).get_json()["data"]["summary"] == {}
    assert client.get("/api/runs/acme/files/summary.json", headers=H).status_code == 404


def test_thoughts_harvest_the_run_folder(client):
    run = Path(os.environ["MIROFISH_RUNS_DIR"]) / "acme"
    (run / "survey.json").write_text(json.dumps({"offer": "Acme", "responses": [
        {"agent_id": 3, "name": "Ana", "answer": {"main_objection": "Too dear for me", "would_convert": "no"}}]}))
    (run / "feed_test.json").write_text(json.dumps({"sessions": [
        {"agent_id": 3, "name": "Ana", "platform": "twitter", "creative_id": "a1", "ad": {"thought": "Looks fun", "click": True}}]}))
    assert client.get("/api/runs/acme/thoughts").status_code == 403
    d = client.get("/api/runs/acme/thoughts", headers=H).get_json()["data"]
    texts = {(e["source"], e["text"], e["did"]) for e in d["entries"]}
    assert ("survey", "Too dear for me", "would no take it") in texts
    assert ("ad in feed", "Looks fun", "clicked") in texts
    assert d["people"] == 1


def test_run_status_from_saved_files(client):
    run = Path(os.environ["MIROFISH_RUNS_DIR"]) / "acme"
    (run / "run_status.json").write_text(json.dumps({"runner_status": "completed", "current_round": 3, "total_rounds": 3}))
    (run / "timeline.json").write_text(json.dumps([{"round_num": 1, "total_actions": 9, "twitter_actions": 4,
                                                    "reddit_actions": 5, "active_agents_count": 6}]))
    d = client.get("/api/runs/acme/status", headers=H).get_json()["data"]
    assert d["live"] is False and d["run"]["runner_status"] == "completed"
    assert d["rounds"] == [{"round": 1, "actions": 9, "twitter": 4, "reddit": 5, "active": 6}]
    assert [s["id"] for s in d["stages"]] == ["graph", "people", "report"]
    assert [s["done"] for s in d["stages"]] == [False, True, False]
    assert client.get("/api/runs/acme", headers=H).get_json()["data"]["simulation_on_backend"] is False
    assert client.get("/api/runs/../status", headers=H).status_code in (403, 404)


def test_status_reads_the_simulation_id_from_summary_too(client):
    run = Path(os.environ["MIROFISH_RUNS_DIR"]) / "acme"
    (run / "run_manifest.json").write_text(json.dumps({"title": "Acme test"}))          # no simulation_id here
    (run / "summary.json").write_text(json.dumps({"simulation_id": "sim_9", "decision": {"decision": "go"}}))
    d = client.get("/api/runs/acme/status", headers=H).get_json()["data"]
    assert d["simulation_id"] == "sim_9"
    assert client.get("/api/runs/acme", headers=H).get_json()["data"]["simulation_id"] == "sim_9"


def _write(run: Path, name: str, data) -> None:
    run.mkdir(parents=True, exist_ok=True)
    (run / name).write_text(data if isinstance(data, str) else json.dumps(data))


def _insights_runs(root: Path) -> None:
    """Runs with the files the overview reads, plus one whose files are broken."""
    people = [{"kind": "persona", "agent_id": i, "country": c, "city": city, "segment": s}
              for i, (c, city, s) in enumerate([("India", "Pune", "Students"), ("India", "Pune, India", "Students"),
                                                 ("Kenya", "Nairobi", "Parents"), ("", None, "Parents")])]
    people.append({"kind": "graph", "agent_id": 9, "country": "India", "city": "Delhi", "name": "Brand"})
    _write(root / "acme", "config.json", {"persona_index": people})
    _write(root / "acme", "summary.json", {"decision": {"decision": "iterate"}, "marketing": {
        "people": 40, "has_survey": True, "answered": 40, "ssr": {"used": True},
        "overall": {"n": 40, "convert_yes": 25.0, "convert_maybe": 50.0, "ssr": {"purchase": {"mean": 3.2, "sd": 1.0}}},
        "objections": [{"type": "price", "label": "Too expensive", "count": 12}, {"label": "Trust", "count": 5}],
        "by_segment": [{"key": "Students", "n": 20, "convert_yes": 30.0}, {"key": "Parents", "n": 20, "convert_yes": 20.0}]}})
    _write(root / "acme", "calibration.json", {"n_real": 60, "overlap": 0.7, "spread": {"verdict": "too alike"}})
    _write(root / "acme", "spend_cap.json", {"limit_usd": 5, "spent_usd": 1.25, "calls": 300, "reached": False})
    _write(root / "beta", "run_manifest.json", {"title": "Beta", "started_at": "2026-11-20T09:00:00",
                                                 "finished_at": "2026-11-20T10:00:00",
                                                 "spend_cap": {"limit_usd": 2, "spent_usd": 0.5},
                                                 "provenance": {"max_spend_usd": 2}})
    _write(root / "beta", "summary.json", {"decision": {"decision": "GO"}, "marketing": {
        "overall": {"n": 12, "convert_yes": 50.0},
        "objections": [{"label": "too  EXPENSIVE", "count": 3}],
        "by_segment": [{"key": "students", "n": 12, "convert_yes": 50.0}]}})
    _write(root / "gamma", "run_manifest.json", {"title": "Gamma", "started_at": "2026-11-22T09:00:00"})
    _write(root / "gamma", "run_status.json", {"runner_status": "running", "progress_percent": 40,
                                                "current_round": 2, "total_rounds": 5})
    _write(root / "broken", "summary.json", "{not json")
    _write(root / "broken", "config.json", "[1, 2")
    _write(root / "broken", "run_manifest.json", ["not", "an", "object"])


def test_insights_aggregate_across_runs(client):
    root = Path(os.environ["MIROFISH_RUNS_DIR"])
    _insights_runs(root)
    assert client.get("/api/runs/insights").status_code == 403
    d = client.get("/api/runs/insights", headers=H).get_json()["data"]
    assert {"activity", "decisions", "intent", "objections", "segments", "geography", "trust", "spend", "forecasts",
            "running", "runs", "total_runs", "root"} <= set(d)
    assert d["total_runs"] == 4                                # acme, beta, gamma, broken; _preview and empty skipped
    assert d["decisions"] == {"go": 1, "iterate": 1, "no_go": 0, "unrecorded": 2}
    assert sum(a["count"] for a in d["activity"]) == 4
    assert {"date": "2026-11-20", "count": 1, "runs": ["beta"]} in d["activity"]

    intent = {r["run"]: r for r in d["intent"]}
    assert set(intent) == {"acme", "beta"}
    assert (intent["acme"]["rate"], intent["acme"]["n"], intent["acme"]["small_sample"]) == (25.0, 40, False)
    assert intent["acme"]["low"] < 25.0 < intent["acme"]["high"] and intent["acme"]["purchase_mean"] == 3.2
    assert intent["beta"]["small_sample"] is True

    top = d["objections"][0]                                 # merged by label, case and spaces ignored
    assert (top["label"], top["runs"], top["people"]) == ("Too expensive", 2, 15)
    students = next(s for s in d["segments"] if s["segment"].lower() == "students")
    assert (students["runs"], students["people"], students["rate"]) == (2, 32, round((30 * 20 + 50 * 12) / 32, 1))

    geo = d["geography"]
    assert [(c["country"], c["people"]) for c in geo["countries"]] == [("India", 2), ("Kenya", 1)]
    assert geo["countries"][0]["segments"] == {"Students": 2}
    assert {"country": "India", "city": "Pune", "people": 2, "runs": 1} in geo["cities"]   # "Pune, India" merged

    trust = {t["run"]: t for t in d["trust"]["runs"]}
    assert d["trust"]["calibrated"] == 1 and trust["acme"]["calibrated"] and trust["acme"]["n_real"] == 60
    assert trust["acme"]["grade"] in "ABCD" and any("real answers" in r for r in trust["acme"]["reasons"])
    assert "gamma" not in trust                               # nothing tested, nothing to grade

    spend = {s["run"]: s for s in d["spend"]["runs"]}
    assert spend["acme"]["spent_usd"] == 1.25 and spend["acme"]["source"] == "spend_cap.json"
    assert spend["beta"]["spent_usd"] == 0.5 and spend["beta"]["limit_usd"] == 2
    assert d["spend"]["total_usd"] == 1.75 and d["spend"]["estimate"] is True

    assert [r["name"] for r in d["running"]] == ["gamma"]
    assert d["running"][0]["progress_percent"] == 40 and d["running"][0]["stale"] is False


def test_insights_forecast_ledger_keeps_hits_and_misses(client):
    root = Path(os.environ["MIROFISH_RUNS_DIR"])
    lines = [{"kind": "lock", "id": "a" * 12, "sha256": "a" * 64, "run": "acme", "locked_at": "2026-11-01T00:00:00+00:00",
              "outcome_due": "2026-12-01", "prediction": {"decision": "iterate", "rate": 25.0, "segment_order": ["Students"]}},
             {"kind": "lock", "id": "b" * 12, "sha256": "b" * 64, "run": "beta", "locked_at": "2026-11-02T00:00:00+00:00",
              "prediction": {"rate": 50.0}},
             {"kind": "lock", "id": "c" * 12, "sha256": "c" * 64, "run": "acme", "locked_at": "2026-11-03T00:00:00+00:00",
              "prediction": {"rate": 10.0}},
             {"kind": "score", "sha256": "a" * 64, "run": "acme", "scored_at": "2026-11-10T00:00:00+00:00",
              "result": {"hits": 1, "total": 2, "checks": [{"check": "rate within 5 points", "hit": True},
                                                          {"check": "segment winner", "hit": False}]}},
             {"kind": "score", "sha256": "b" * 64, "run": "beta", "result": {"hits": 0, "total": 1, "checks": []}}]
    (root / "forecast_ledger.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\nnot json\n")
    _write(root / "acme", "forecast_lock.json", {"sha256": "d" * 64, "locked_at": "2026-11-04T00:00:00+00:00",
                                                  "prediction": {"rate": 25.0}})
    f = client.get("/api/runs/insights", headers=H).get_json()["data"]["forecasts"]
    assert (f["locked"], f["scored"], f["hits"], f["checks"]) == (4, 2, 1, 3)
    by_id = {e["id"]: e for e in f["entries"]}
    assert by_id["a" * 12]["outcome"] == "mixed" and by_id["a" * 12]["predicted"]["top_segment"] == "Students"
    assert by_id["b" * 12]["outcome"] == "miss"
    assert by_id["c" * 12]["outcome"] == "pending" and by_id["c" * 12]["scored"] is False
    assert by_id["d" * 12]["in_ledger"] is False


def test_insights_cache_follows_file_changes_and_survives_empty_roots(client, tmp_path, monkeypatch):
    root = Path(os.environ["MIROFISH_RUNS_DIR"])
    first = client.get("/api/runs/insights", headers=H).get_json()["data"]
    assert first["decisions"]["iterate"] == 1
    summary = root / "acme" / "summary.json"
    summary.write_text(json.dumps({"decision": {"decision": "no_go"}}))
    st = summary.stat()
    os.utime(summary, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))
    again = client.get("/api/runs/insights", headers=H).get_json()["data"]
    assert again["decisions"]["no_go"] == 1 and again["decisions"]["iterate"] == 0
    monkeypatch.setenv("MIROFISH_RUNS_DIR", str(tmp_path / "missing"))
    empty = client.get("/api/runs/insights", headers=H).get_json()["data"]
    assert empty["total_runs"] == 0 and empty["activity"] == [] and empty["forecasts"]["locked"] == 0


def test_insights_marks_a_quiet_running_run_as_stale(tmp_path):
    import time
    from app.services import run_insights
    root = tmp_path / "r"
    _write(root / "slow", "run_manifest.json", {"title": "Slow"})
    _write(root / "slow", "run_status.json", {"runner_status": "running"})
    _write(root / "done", "run_manifest.json", {"finished_at": "2026-11-01T00:00:00"})
    _write(root / "done", "run_status.json", {"runner_status": "running"})
    d = run_insights.collect(root, now=time.time() + 3600)
    assert [(r["name"], r["stale"]) for r in d["running"]] == [("slow", True)]
