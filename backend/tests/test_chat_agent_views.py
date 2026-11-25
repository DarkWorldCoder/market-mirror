"""open_view: everything the app shows can be opened inline in the chat. Read-only, free, validated, never spends.
A fake model and a fake tool layer: no model calls, no network."""
import pytest

from app.services.chat_agent import state, tools as T
from app.services.chat_agent.bridge import Executor
from chat_agent_fakes import FakeAdapter, FakeExecutor, ask, executed_spend, run, say, tool


@pytest.fixture(autouse=True)
def _clean_state():
    state.reset()
    yield
    state.reset()


EVERY_VIEW = [
    {"view": "results", "run": "fitloop_v2"}, {"view": "reports", "run": "fitloop_v2"},
    {"view": "audience", "run": "fitloop_v2"}, {"view": "world_map", "run": "fitloop_v2"},
    {"view": "people", "run": "fitloop_v2", "filters": {"country": "Kenya"}},
    {"view": "buyer_responses", "run": "fitloop_v2", "filters": {"verdict": "no", "objection": "price"}},
    {"view": "activity", "run": "fitloop_v2"}, {"view": "social_feed", "run": "fitloop_v2"},
    {"view": "landing", "run": "fitloop_v2"}, {"view": "brain_response", "run": "fitloop_v2"},
    {"view": "compare", "runs": ["fitloop_v2", "fitloop_v1"]},
    {"view": "dashboard_map"}, {"view": "insights", "panel": "objections"}, {"view": "insights"},
    {"view": "projects"}, {"view": "skills"}, {"view": "connectors"}, {"view": "settings_summary"}, {"view": "spend"},
]


def test_the_view_list_covers_every_page_and_panel():
    assert set(T.VIEWS) == {"results", "reports", "audience", "world_map", "people", "buyer_responses", "activity",
                            "social_feed", "landing", "brain_response", "compare", "dashboard_map", "insights",
                            "projects", "skills", "connectors", "settings_summary", "spend"}
    assert set(T.INSIGHT_PANELS) == {"activity_calendar", "intent", "objections", "audiences", "trust", "spend", "live_runs"}
    schema = T.APP_TOOLS["open_view"]["parameters"]
    assert schema["properties"]["view"]["enum"] == list(T.VIEWS)
    assert schema["properties"]["panel"]["enum"] == list(T.INSIGHT_PANELS)
    assert schema["required"] == ["view"]
    # every view is in the covered set exactly once
    assert {a["view"] for a in EVERY_VIEW} == set(T.VIEWS)


def test_open_view_is_offered_in_every_phase():
    assert all("open_view" in T.phase_tools(p) for p in T.PHASES)


@pytest.mark.parametrize("args", EVERY_VIEW, ids=lambda a: a["view"] + ("_" + a["panel"] if a.get("panel") else ""))
def test_every_view_is_free(args):
    assert T.classify("open_view", args) == {"cost": T.FREE, "notes": []}
    assert T.normalize_view(args)["view"] == args["view"]


@pytest.mark.parametrize("args", EVERY_VIEW, ids=lambda a: a["view"] + ("_" + a["panel"] if a.get("panel") else ""))
def test_no_view_spends_or_asks_for_approval(args):
    ex, events = FakeExecutor(results={"open_view": lambda a: {**a, "shown": True}}), []
    out = run(ask("show it"), ex, FakeAdapter([tool("open_view", args), say("Here it is.")]), events)
    assert out["status"] == "complete"
    assert not [e for e, _ in events if e == "approval_request"]
    assert executed_spend(ex) == []
    assert [c[0] for c in ex.calls] == ["open_view"]
    artifact = next(d for e, d in events if e == "artifact")
    assert artifact["kind"] == "view" and artifact["view"] == args["view"]
    assert artifact["simulated"] is (args["view"] in T.SIMULATED_VIEWS)
    for key in ("panel", "filters", "runs"):
        assert artifact.get(key) == args.get(key)


def test_settings_like_views_are_not_marked_simulated_but_run_views_are():
    for view in ("projects", "skills", "connectors", "settings_summary", "spend"):
        assert view not in T.SIMULATED_VIEWS
    for view in (*T.RUN_VIEWS, "compare", "dashboard_map", "insights"):
        assert view in T.SIMULATED_VIEWS


@pytest.mark.parametrize("args,reason", [
    ({"view": "nope"}, "Choose a view"),
    ({}, "Choose a view"),
    ({"view": "activity", "run": "x", "panel": "intent"}, "Only the insights view takes a panel"),
    ({"view": "insights", "panel": "weather"}, "Choose a panel"),
    ({"view": "activity", "run": "x", "filters": {"verdict": "no"}}, "takes no filters"),
    ({"view": "people", "run": "x", "filters": {"objection": "price"}}, "people filters are"),
    ({"view": "buyer_responses", "run": "x", "filters": {"verdict": "perhaps"}}, "verdict filter is one of"),
    ({"view": "buyer_responses", "run": "x", "filters": {"objection": "vibes"}}, "objection filter is one of"),
    ({"view": "people", "run": "x", "filters": {"country": "K" * 81}}, "short line"),
    ({"view": "people", "run": "x", "filters": {"country": 3}}, "short line"),
    ({"view": "people", "run": "x", "filters": "Kenya"}, "filters must be an object"),
    ({"view": "spend", "run": "x"}, "workspace view"),
    ({"view": "compare", "runs": ["a", "a"]}, "two different runs"),
    ({"view": "compare", "runs": ["a"]}, "two saved run names"),
    ({"view": "people", "run": 7}, "saved run name"),
])
def test_bad_view_arguments_are_refused_with_a_reason(args, reason):
    with pytest.raises(ValueError, match=reason):
        T.normalize_view(args)


def test_filters_are_trimmed_and_lowercased_where_they_are_choices():
    got = T.normalize_view({"view": "buyer_responses", "run": " r ", "filters": {"verdict": "NO", "segment": " Students ", "query": ""}})
    assert got == {"view": "buyer_responses", "run": "r", "filters": {"verdict": "no", "segment": "Students"}}
    # run + other is accepted for compare
    assert T.normalize_view({"view": "compare", "run": "a", "other": "b"})["runs"] == ["a", "b"]


def test_a_bad_view_comes_back_to_the_model_as_a_tool_error_and_nothing_runs():
    ex, events = FakeExecutor(), []
    run(ask("show it"), ex, FakeAdapter([tool("open_view", {"view": "spend", "panel": "intent"}), say("Sorry.")]), events)
    assert ex.calls == []
    result = next(d for e, d in events if e == "tool_result")
    assert result["status"] == "failed" and "panel" in str(result)


def test_a_run_view_without_a_run_asks_which_run_but_workspace_views_do_not():
    assert [f["name"] for f in T.missing_slots("open_view", {"view": "people"})] == ["run"]
    assert [f["name"] for f in T.missing_slots("open_view", {"view": "compare"})] == ["runs.0", "runs.1"]
    for view in T.WORKSPACE_VIEWS:
        assert T.missing_slots("open_view", {"view": view}) == []


def test_workspace_views_carry_no_workspace_data_to_the_model():
    """Settings, connectors, spend, projects and skills are read by the browser with the user's own session; the
    executor returns only the view spec, so the agent never widens what a caller can read."""
    ex = Executor()
    for view in T.WORKSPACE_VIEWS:
        got = ex.open_view({"view": view, **({"panel": "spend"} if view == "insights" else {})})
        assert set(got) <= {"view", "panel", "shown", "simulated", "note"}, got


def test_run_views_check_the_run_exists(monkeypatch):
    from app.api import runs

    def missing(name):
        raise LookupError("unknown run")
    monkeypatch.setattr(runs, "_run_dir", missing)
    with pytest.raises(ValueError, match="no saved run"):
        Executor().open_view({"view": "people", "run": "ghost"})
    with pytest.raises(ValueError, match="no saved run"):
        Executor().open_view({"view": "compare", "runs": ["ghost", "other"]})
