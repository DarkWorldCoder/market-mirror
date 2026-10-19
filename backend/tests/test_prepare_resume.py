"""A complete saved profile set can finish preparation without regeneration."""

import json
import pytest

from app.services import simulation_manager as sm


def test_resume_saved_profiles_generates_only_config(tmp_path, monkeypatch):
    plan = {"kept_graph_entities": ["Graph actor"], "personas": [
        {"name": "Buyer", "labels": ["Persona"], "segment": "parents", "country": "PH"}]}
    profiles = [{"user_id": 0, "username": "g", "name": "Graph actor", "bio": "actor", "persona": "actor"},
                {"user_id": 1, "username": "b", "name": "Buyer", "bio": "buyer", "persona": "buyer", "age": 32}]
    (tmp_path / "persona_plan.json").write_text(json.dumps(plan))
    (tmp_path / "reddit_profiles.json").write_text(json.dumps(profiles))
    state = sm.SimulationState(simulation_id="sim_x", project_id="proj_x", graph_id="g_x", enable_twitter=False)
    state.profiles_generated = True
    state.profiles_count = 2
    calls = []

    class Params:
        generation_reasoning = "fixture"

        def to_json(self):
            return "{}"

    class Generator:
        def generate_config(self, **kw):
            calls.append(kw)
            return Params()

    monkeypatch.setattr(sm, "SimulationConfigGenerator", Generator)
    manager = sm.SimulationManager()
    monkeypatch.setattr(manager, "_save_simulation_state", lambda *_: None)
    result = manager._resume_profile_preparation(state, str(tmp_path), "test", "brief", None)
    assert result.config_generated and result.status == sm.SimulationStatus.READY
    assert len(calls) == 1 and len(calls[0]["entities"]) == 2
    assert (tmp_path / "simulation_config.json").is_file()


def test_resume_only_refuses_incomplete_profiles_without_regeneration(tmp_path, monkeypatch):
    state = sm.SimulationState(simulation_id="sim_x", project_id="proj_x", graph_id="g_x", enable_twitter=False)
    state.profiles_generated = True
    state.profiles_count = 2
    (tmp_path / "persona_plan.json").write_text(json.dumps({"kept_graph_entities": ["Only one"], "personas": []}))
    (tmp_path / "reddit_profiles.json").write_text(json.dumps([{"user_id": 0}]))
    manager = sm.SimulationManager()
    monkeypatch.setattr(manager, "_load_simulation_state", lambda *_: state)
    monkeypatch.setattr(manager, "_get_simulation_dir", lambda *_: str(tmp_path))

    def must_not_generate(*_args, **_kwargs):
        raise AssertionError("profile generation must not run")

    monkeypatch.setattr(sm, "ZepEntityReader", must_not_generate)
    monkeypatch.setattr(sm, "OasisProfileGenerator", must_not_generate)
    with pytest.raises(ValueError, match="complete saved profile set"):
        manager.prepare_simulation("sim_x", "test", "brief", resume_only=True)


def test_prepared_reddit_only_does_not_require_twitter_profiles(tmp_path, monkeypatch):
    from app.api import simulation as simulation_api

    folder = tmp_path / "sim_x"
    folder.mkdir()
    (folder / "state.json").write_text(json.dumps({"status": "stopped", "config_generated": True,
                                                     "enable_reddit": True, "enable_twitter": False}))
    (folder / "simulation_config.json").write_text("{}")
    (folder / "reddit_profiles.json").write_text("[]")
    monkeypatch.setattr(simulation_api.Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))
    prepared, info = simulation_api._check_simulation_prepared("sim_x")
    assert prepared, info
