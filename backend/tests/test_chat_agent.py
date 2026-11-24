"""The in-app chat agent with a fake model and a fake tool layer: no model calls, no network."""
import json
import os

import pytest

from app.services.chat_agent import loop, state, tools as T, triggers
from app.services.chat_agent.bridge import ApprovalNeeded
from chat_agent_fakes import (RUNS, SIM, FakeAdapter, FakeExecutor, answer, ask, executed_spend, run, say, tool)


@pytest.fixture(autouse=True)
def _clean_state():
    state.reset()
    yield
    state.reset()


# ---------------------------------------------------------------------------
# cost classes
# ---------------------------------------------------------------------------

FREE_CALLS = [("doctor", {}), ("list_runs", {}), ("results", {"run": "x"}), ("job_status", {"job_id": "a"}),
              ("provider_setup", {"action": "status"}), ("analytics_audience", {"files": ["/a.csv"]}),
              ("ads_import", {"file": "/a.csv", "out": "/a.md"}), ("actuals_import", {"file": "/a.csv", "source_type": "ads"}),
              ("real_split", {"real_csv": "/a.csv"}), ("calibrate", {"run": "x", "real_csv": "/a.csv"}),
              ("backtest", {"run": "x", "actuals": "/a.json"}), ("cli", {"args": ["forecast", "lock"]}),
              ("intake", {"files": ["/r.csv"], "engine": "supplied"}), ("ad_patterns", {"rows": [{}], "engine": "supplied"}),
              ("open_view", {"view": "reports", "run": "x"}), ("compare_runs", {"runs": ["a", "b"]})]
SPEND_CALLS = [("market_test", {"config": {}}), ("quickstart", {"answers": {}}), ("understand", {"docs": ["/a.md"]}),
               ("intake", {"files": ["/r.csv"]}), ("ideas", {}), ("campaign_plan", {"goal": "g", "budget": {"amount": 1}}),
               ("run_test", {"simulation_id": "s", "spec": {}}), ("study", {"spec": {}}), ("pitch", {"simulation_id": "s", "script": "x"}),
               ("email_test", {"simulation_id": "s", "emails": [{}]}), ("website_test", {"simulation_id": "s", "spec": {"url": "https://x"}}),
               ("ask_buyers", {"action": "ask", "simulation_id": "s"}), ("push_context", {"simulation_id": "s", "text": "t"}),
               ("cli", {"args": ["survey", "--simulation", "s"]}), ("creative_check", {"creatives": [{"image": "/a.png"}]})]
OUTSIDE_CALLS = [("research", {"query": "q"}), ("browse_page", {"url": "https://example.com"}),
                 ("ad_patterns", {"rows": [{}], "engine": "jev"})]


@pytest.mark.parametrize("name,args", FREE_CALLS)
def test_free_tools_run_without_asking(name, args):
    assert T.classify(name, args)["cost"] == T.FREE


@pytest.mark.parametrize("name,args", SPEND_CALLS)
def test_model_calling_tools_are_spend(name, args):
    assert T.classify(name, args)["cost"] == T.SPEND


@pytest.mark.parametrize("name,args", OUTSIDE_CALLS)
def test_outside_contact_is_its_own_class(name, args):
    got = T.classify(name, args)
    assert got["cost"] == T.OUTSIDE and got["notes"]


def test_spend_that_also_contacts_outside_keeps_both():
    for name, args in [("understand", {"url": "https://x.com"}), ("creative_check", {"creatives": [{"image": "https://x/a.png"}]})]:
        got = T.classify(name, args)
        assert got["cost"] == T.SPEND and got["notes"]


def test_every_chat_tool_has_a_class_and_a_phase():
    for name in T.all_tools():
        assert T.classify(name, {})["cost"] in (T.FREE, T.OUTSIDE, T.SPEND)
        assert any(name in T.phase_tools(p) for p in T.PHASES), name
    assert "setup" not in T.all_tools() and "start_backend" not in T.all_tools()


def test_phases_expose_only_relevant_tools():
    assert "compare_runs" in T.phase_tools("review") and "compare_runs" not in T.phase_tools("setup")
    assert "market_test" in T.phase_tools("test") and "market_test" not in T.phase_tools("review")
    assert "analytics_audience" in T.phase_tools("audience")
    assert all("switch_phase" in T.phase_tools(p) for p in T.PHASES)


def test_settings_changes_are_refused_from_chat():
    assert T.refusal("provider_setup", {"action": "configure"})
    assert T.refusal("cli", {"args": ["setup"]})
    assert T.refusal("provider_setup", {"action": "status"}) is None


# ---------------------------------------------------------------------------
# approval for every spend tool
# ---------------------------------------------------------------------------

VALID_SPEND = {
    "market_test": {"config": {"requirement": "Which headline wins?", "auto_personas": 12}},
    "quickstart": {"answers": {"brand": "B", "product": "P", "buyers": "parents in India"}},
    "understand": {"docs": ["/a.md"]},
    "intake": {"files": ["/r.csv"]},
    "ideas": {"run": "fitloop_v2"},
    "campaign_plan": {"goal": "signups", "budget": {"amount": 300}},
    "run_test": {"simulation_id": SIM, "spec": {"type": "message", "variants": ["a", "b"]}},
    "study": {"spec": {"simulation_id": SIM}},
    "pitch": {"simulation_id": SIM, "script": "Hi"},
    "email_test": {"simulation_id": SIM, "emails": [{"subject": "s"}]},
    "ask_buyers": {"action": "ask", "simulation_id": SIM, "agent_id": 2, "message": "Would you pay $9?"},
    "push_context": {"simulation_id": SIM, "text": "A competitor cut prices."},
    "cli": {"args": ["survey", "--simulation", SIM]},
}
PHASE_FOR = {"market_test": "test", "quickstart": "setup", "understand": "setup", "intake": "audience", "ideas": "test",
             "campaign_plan": "test", "run_test": "test", "study": "test", "pitch": "test", "email_test": "test",
             "ask_buyers": "review", "push_context": "test", "cli": "test"}


@pytest.mark.parametrize("name", sorted(VALID_SPEND))
def test_every_spend_tool_waits_for_approval_and_stop_runs_nothing(name):
    ex = FakeExecutor()
    script = [tool("switch_phase", {"phase": PHASE_FOR[name]}), tool(name, VALID_SPEND[name]),
              tool(name, VALID_SPEND[name]), say("Nothing ran.")]
    adapter = FakeAdapter(script)
    first = run(ask("please do it"), ex, adapter)
    assert first["status"] == "waiting" and first["pending"]["kind"] == "spend"
    assert first["pending"]["tool"] == name and first["pending"]["options"]
    assert ex.calls == [] and executed_spend(ex) == []
    second = run(answer(first, {"decision": "stop"}), ex, adapter)
    assert second["status"] == "complete" and ex.calls == []
    # the model asked again after the Stop: refused without a new card or a call
    declined = [m for m in adapter.messages if m.get("role") == "tool" and "declined" in m["content"]]
    assert len(declined) == 2


def test_model_cannot_approve_its_own_spend():
    ex = FakeExecutor()
    cfg = {"requirement": "x", "auto_personas": 10, "approve_spend": True}
    result = run(ask("test it"), ex, FakeAdapter([tool("market_test", {"config": cfg})]))
    assert result["pending"]["kind"] == "spend"
    assert all("approve_spend" not in a[1]["config"] for a in ex.attempts)
    assert ex.calls == []


def test_market_test_card_mirrors_spend_question_and_says_people_first_spends():
    ex = FakeExecutor()
    result = run(ask("test it"), ex, FakeAdapter([tool("market_test", {"config": {"requirement": "x", "auto_personas": 20}})]))
    card = result["pending"]
    assert [o["value"] for o in card["options"]] == ["run", "people_first", "stop"]
    people_first = next(o for o in card["options"] if o["value"] == "people_first")
    assert "persona planner" in people_first["detail"] and "$" in people_first["detail"]
    assert card["people"] == 20 and card["usd_estimate"] == pytest.approx(card["total_calls"] * 0.01)
    assert card["max_spend_usd"]["suggested"] >= 1


def test_need_input_resume_runs_with_the_users_answer_and_cap():
    ex = FakeExecutor(results={"market_test": {"job_id": "abcdef0123", "result_path": "/r", "status": "running"}},
                      jobs=[{"status": "running", "log_tail": [f"line {i}" for i in range(30)], "elapsed_s": 5},
                            {"status": "done", "log_tail": ["done"], "result": {"stage": "personas_ready"}}])
    adapter = FakeAdapter([tool("market_test", {"config": {"requirement": "x", "auto_personas": 12}}), say("People are ready.")])
    events = []
    first = run(ask("make the people"), ex, adapter, events)
    second = run(answer(first, {"decision": "people_first", "max_spend_usd": 4}), ex, adapter, events)
    assert second["status"] == "complete" and second["message"] == "People are ready."
    name, args, answers = ex.calls[0]
    assert name == "market_test" and answers == {"approve_spend": {"action": "accept", "content": {"decision": "people_first"}}}
    assert args["config"]["max_spend_usd"] == 4 and "approve_spend" not in args["config"]
    progress = [d for e, d in events if e == "tool_progress"]
    assert progress and len(progress[0]["log_tail"]) == 15
    assert [e for e, _ in events].count("approval_request") == 1


def test_bad_answer_keeps_the_approval_open():
    ex = FakeExecutor()
    adapter = FakeAdapter([tool("market_test", {"config": {"requirement": "x", "auto_personas": 12}})])
    first = run(ask("go"), ex, adapter)
    with pytest.raises(ValueError):
        run(answer(first, {"decision": "launch-everything"}), ex, adapter)
    assert state.peek_pending(first["pending"]["id"])
    with pytest.raises(ValueError):
        run(answer(first, {"decision": "run", "max_spend_usd": 5000}), ex, adapter)


def test_approval_belongs_to_its_chat():
    ex = FakeExecutor()
    first = run(ask("go"), ex, FakeAdapter([tool("market_test", {"config": {"requirement": "x", "auto_personas": 12}})]))
    other = answer(first, {"decision": "run"})
    other["session_id"] = "another-chat-99"
    with pytest.raises(ValueError):
        run(other, ex, FakeAdapter([]))


def test_real_mcp_market_test_elicits_through_the_chat_context(tmp_path, monkeypatch):
    """The real MCP server's market_test, called in-process: no approval -> NeedInput; the answer starts the job."""
    from app.services.chat_agent import bridge
    monkeypatch.setenv("MARKET_MIRROR_HOME", str(tmp_path))
    m = bridge.mcp()
    started = []
    monkeypatch.setattr(m, "job", lambda args, label: started.append((args, label)) or {"job_id": "abcdef0123", "result_path": "/x"})
    ex = bridge.Executor()
    cfg = {"name": "chat_t", "requirement": "x", "auto_personas": 10}
    with pytest.raises(ApprovalNeeded) as need:
        ex.call("market_test", {"config": cfg})
    assert need.value.key == "approve_spend"
    assert [o["const"] for o in need.value.elicitation["requestedSchema"]["properties"]["decision"]["oneOf"]] == ["run", "people_first"]
    assert started == []
    ex.call("market_test", {"config": cfg}, answers={"approve_spend": {"action": "accept", "content": {"decision": "run"}}})
    written = json.load(open(started[0][0][-1], encoding="utf-8"))
    assert written["approve_spend"] is True and started[0][1] == "market-test"
    assert "compare_runs" in ex.tool_schemas() and "setup" not in ex.tool_schemas()


# ---------------------------------------------------------------------------
# loop limits
# ---------------------------------------------------------------------------

def test_step_limit_pauses_then_answer_now_runs_one_step_without_tools():
    ex = FakeExecutor()
    script = [tool("list_runs", {"page": i}) for i in range(11)] + [say("Here is what I found.")]
    adapter = FakeAdapter(script)
    first = run(ask("look around"), ex, adapter)
    assert first["pending"]["kind"] == "limit" and first["steps_used"] == 11
    assert [o["value"] for o in first["pending"]["options"]] == ["keep_going", "answer_now"]
    final = run(answer(first, {"choice": "answer_now"}), ex, adapter)
    assert final["message"] == "Here is what I found." and adapter.offered[-1] is None


def test_keep_going_gives_a_new_budget():
    ex = FakeExecutor()
    adapter = FakeAdapter([tool("list_runs", {"page": i}) for i in range(13)] + [say("ok")])
    first = run(ask("look around"), ex, adapter)
    again = run(answer(first, {"choice": "keep_going"}), ex, adapter)
    assert again["status"] == "complete" and again["message"] == "ok"


def test_same_call_three_times_breaks_the_loop():
    ex = FakeExecutor()
    adapter = FakeAdapter([tool("list_runs"), tool("list_runs"), tool("list_runs"), say("Stopped and summarised.")])
    result = run(ask("loop"), ex, adapter)
    assert result["status"] == "stopped" and "3 times" in result["break_reason"]
    assert len(ex.calls) == 2 and adapter.offered[-1] is None


def test_three_tool_errors_in_a_row_stop():
    ex = FakeExecutor(results={"results": RuntimeError("boom")})
    adapter = FakeAdapter([tool("results", {"run": f"r{i}"}) for i in range(3)] + [say("Could not read them.")])
    result = run(ask("show results"), ex, adapter)
    assert result["status"] == "stopped" and "errors" in result["break_reason"]


# ---------------------------------------------------------------------------
# missing inputs: one form, asked once
# ---------------------------------------------------------------------------

def test_missing_slots_become_one_form_then_the_spend_card():
    ex = FakeExecutor()
    adapter = FakeAdapter([tool("run_test", {"simulation_id": SIM}), say("Done")])
    first = run(ask("run a test"), ex, adapter)
    card = first["pending"]
    assert card["kind"] == "form" and [f["name"] for f in card["fields"]] == ["spec.type", "spec.variants"]
    assert any(o["value"] == "price" for o in card["fields"][0]["options"])
    second = run(answer(first, {"values": {"spec.type": "message", "spec.variants": "Save time\nSave money"}}), ex, adapter)
    assert second["pending"]["kind"] == "spend" and ex.calls == []
    third = run(answer(second, {"decision": "run"}), ex, adapter)
    assert ex.calls[0][1]["spec"] == {"type": "message", "variants": ["Save time", "Save money"]}
    assert third["status"] == "complete"


def test_form_is_asked_only_once():
    ex = FakeExecutor()
    adapter = FakeAdapter([tool("run_test", {"simulation_id": SIM}), say("Need a second option.")])
    first = run(ask("run a test"), ex, adapter)
    second = run(answer(first, {"values": {"spec.type": "message", "spec.variants": "Only one"}}), ex, adapter)
    assert second["status"] == "complete" and ex.calls == []
    assert any("Still missing" in m["content"] for m in adapter.messages if m.get("role") == "tool")


def test_url_is_read_before_asking():
    ex = FakeExecutor()
    adapter = FakeAdapter([tool("market_test", {"config": {}}), say("Reading the page first.")])
    result = run(ask("test my product https://example.com/product"), ex, adapter)
    assert result["status"] == "complete"
    hint = [m for m in adapter.messages if m.get("role") == "tool"][0]
    assert "understand" in hint["content"]


def test_simulation_slot_offers_saved_simulations():
    fields = T.missing_slots("pitch", {}, runs=RUNS)
    assert fields[0]["type"] == "select" and fields[0]["options"][0]["value"] == SIM


def test_ask_user_returns_the_answers_to_the_model():
    ex = FakeExecutor()
    adapter = FakeAdapter([tool("ask_user", {"fields": [{"name": "price", "label": "Price", "type": "number"}]}), say("Thanks")])
    first = run(ask("price check"), ex, adapter)
    run(answer(first, {"values": {"price": "9.5"}}), ex, adapter)
    assert any('"price": 9.5' in m["content"] for m in adapter.messages if m.get("role") == "tool")


# ---------------------------------------------------------------------------
# automatic triggers
# ---------------------------------------------------------------------------

GA4 = "Country,City,Active users,Key events\nIndia,Mumbai,1200,40\n"
POSTHOG = "properties.$geoip_country_name,count()\nIndia,300\n"
META = "Campaign name,Ad name,Impressions,Clicks,Amount spent (USD)\nSpring,Ad A,1000,20,10\n"
GOOGLE = "Campaign,Ad group,Impressions,Clicks,Cost,Conversions\nBrand,Core,500,10,5,1\n"
REVIEWS = "id,review,purchased\n1,Love it,yes\n"
ANSWERS = "segment,country,gender,age,y\nParents,India,F,31,yes\n"


@pytest.mark.parametrize("name,text,kind", [("ga4.csv", GA4, "analytics"), ("posthog.csv", POSTHOG, "analytics"),
                                            ("meta.csv", META, "ads"), ("google.csv", GOOGLE, "ads"),
                                            ("reviews.csv", REVIEWS, "reviews"), ("answers.csv", ANSWERS, "answers"),
                                            ("ad.png", "", "media"), ("call.vtt", "WEBVTT", "transcript"),
                                            ("notes.csv", "a,b\n1,2\n", "other")])
def test_detects_upload_kind_from_headers(name, text, kind):
    assert triggers.detect_file(name, text)["kind"] == kind


def test_trigger_plan_runs_free_imports_and_offers_the_rest():
    files = [{"name": "ga4.csv", "path": "/u/ga4.csv", "text": GA4}, {"name": "meta.csv", "path": "/u/meta.csv", "text": META},
             {"name": "reviews.csv", "path": "/u/reviews.csv", "text": REVIEWS}]
    got = triggers.plan(files, "before launch, check this", None, "fitloop_v2")
    assert [a["tool"] for a in got["auto"]] == ["analytics_audience", "ads_import"]
    assert got["auto"][1]["args"] == {"file": "/u/meta.csv", "out": "/u/meta_seed.md"}
    assert any("Split reviews.csv" in o for o in got["offers"]) and any("forecast" in o for o in got["offers"])


def test_ga4_upload_sizes_the_audience_before_the_first_model_step():
    ex = FakeExecutor(results={"analytics_audience": {"out": "/fake/personas.json", "segments": 3}})
    adapter = FakeAdapter([lambda m, t: say("Sized." if ex.calls else "too early")])
    result = run(ask("use my GA4 export to size the audience", files=[{"name": "ga4.csv", "text": GA4}]), ex, adapter)
    assert ex.calls[0][0] == "analytics_audience" and ex.calls[0][1] == {"files": ["/fake/uploads/ga4.csv"]}
    assert result["message"] == "Sized." and "analytics_audience" in adapter.offered[0]


def test_answers_with_a_selected_run_calibrate_automatically(tmp_path, monkeypatch):
    (tmp_path / "fitloop_v2").mkdir()
    (tmp_path / "fitloop_v2" / "summary.json").write_text("{}")
    monkeypatch.setenv("MIROFISH_RUNS_DIR", str(tmp_path))
    ex = FakeExecutor()
    run(ask("here are the real answers", run="fitloop_v2", files=[{"name": "answers.csv", "text": ANSWERS}]), ex, FakeAdapter([say("ok")]))
    assert ex.calls[0][0] == "calibrate" and ex.calls[0][1]["run"] == "fitloop_v2"


# ---------------------------------------------------------------------------
# outside contact, audience design, compare
# ---------------------------------------------------------------------------

def test_outside_notice_is_remembered_for_the_session():
    ex = FakeExecutor()
    adapter = FakeAdapter([tool("switch_phase", {"phase": "setup"}), tool("research", {"query": "meal kits"}), say("Read."),
                           tool("switch_phase", {"phase": "setup"}), tool("research", {"query": "meal kits india"}), say("Again.")])
    first = run(ask("what do people say?"), ex, adapter)
    assert first["pending"]["kind"] == "outside"
    run(answer(first, {"decision": "go"}), ex, adapter)
    again = run(ask("and in India?"), ex, adapter)
    assert again["status"] == "complete" and [c[0] for c in ex.calls] == ["research", "research"]


def test_design_audience_flags_and_saves_the_edited_table():
    ex = FakeExecutor()
    segs = [{"label": "Young parents", "count": 6, "country": "India", "platforms": "instagram, whatsapp"},
            {"label": "Dads", "count": 4, "country": "India", "communities": ["Parents of Pune"]}]
    adapter = FakeAdapter([tool("design_audience", {"name": "parents", "segments": segs}), say("Saved.")])
    first = run(ask("design an audience of young parents on Android"), ex, adapter)
    card = first["pending"]
    assert card["kind"] == "audience" and card["estimate"]["people"] == 10
    codes = {w["code"] for w in card["fit_check"]["warnings"]}
    assert {"small_segments", "less_covered_markets"} <= codes
    edited = [{**segs[0], "count": 12}, {**segs[1], "count": 10}]
    done = run(answer(first, {"segments": edited}), ex, adapter)
    spec = ex.audiences["/fake/audiences/parents.json"]
    assert [s["count"] for s in spec["segments"]] == [12, 10]
    assert spec["communities"] == [{"name": "Parents of Pune", "segments": ["Dads"]}]
    assert spec["segments"][0]["platforms"] == ["instagram", "whatsapp"]
    assert done["status"] == "complete"


def test_compare_runs_emits_the_chat_compare_message_shape():
    ex = FakeExecutor(results={"compare_runs": {"a": {}, "b": {}, "gap": {"too_close_to_call": True}}})
    events = []
    result = run(ask("compare my last two experiments"), ex, FakeAdapter([tool("compare_runs", {"runs": ["fitloop_v2", "fitloop_v1"]}),
                                                                           say("v2 leans ahead.")]), events)
    artifact = [d for e, d in events if e == "artifact"][0]
    assert artifact["kind"] == "compare" and artifact["compare"] == {"a": "fitloop_v2", "b": "fitloop_v1"}
    assert result["artifacts"][0]["compare"] == {"a": "fitloop_v2", "b": "fitloop_v1"} and artifact["simulated"]


def _run(root, name, convert_yes, n, segs, feed=None):
    d = root / name
    d.mkdir(parents=True)
    (d / "summary.json").write_text(json.dumps({"project_name": name.title(), "decision": {"decision": "go"},
        "marketing": {"overall": {"n": n, "convert_yes": convert_yes, "convert_maybe": 20},
                      "by_segment": segs, "objections": [{"label": "Price", "share": 30}]}}))
    if feed:
        (d / "feed_test.json").write_text(json.dumps(feed))


def test_mcp_compare_runs_reads_saved_files(tmp_path, monkeypatch):
    from app.services.chat_agent import bridge
    monkeypatch.setenv("MARKET_MIRROR_HOME", str(tmp_path))
    m = bridge.mcp()
    root = tmp_path / "mirofish_runs"
    _run(root, "a_run", 42.0, 60, [{"key": "Parents", "n": 30, "convert_yes": 50}, {"key": "Students", "n": 30, "convert_yes": 30}],
         {"creatives": [{"id": "c1", "name": "Save time"}], "summary": {"per_creative": {"c1": {"expected_ctr": 1.8}}}})
    _run(root, "b_run", 39.0, 50, [{"key": "Parents", "n": 50, "convert_yes": 39}])
    out = m.call("compare_runs", {"runs": ["a_run", "b_run"]})
    assert out["a"]["would_buy"] == 42.0 and out["a"]["strongest_audience"]["segment"] == "Parents"
    assert out["a"]["best_ad"]["name"] == "Save time" and out["higher"]["would_buy"] == "a"
    assert out["gap"]["too_close_to_call"] is True and out["simulated"] is True
    with pytest.raises(ValueError):
        m.call("compare_runs", {"runs": ["a_run"]})
    with pytest.raises(ValueError):
        m.call("compare_runs", {"runs": ["a_run", "../etc"]})


# ---------------------------------------------------------------------------
# provider errors
# ---------------------------------------------------------------------------

class HTTPError(Exception):
    def __init__(self, status, headers=None):
        super().__init__(f"status {status}")
        self.status_code = status
        self.response = type("R", (), {"status_code": status, "headers": headers or {}})()


def test_rejected_key_says_nothing_was_spent():
    ex = FakeExecutor()
    with pytest.raises(loop.AgentError) as err:
        run(ask("hello"), ex, FakeAdapter([HTTPError(401)]))
    assert str(err.value) == "Your Anthropic key was rejected. Nothing was spent."
    assert [a["id"] for a in err.value.actions] == ["open_model_settings", "use_claude_code_login"]


def test_rate_limit_honours_retry_after_up_to_three_times():
    slept = []
    result = run(ask("hello"), FakeExecutor(), FakeAdapter([HTTPError(429, {"retry-after": "7"})] * 3 + [say("hi")]), sleep=slept.append)
    assert result["message"] == "hi" and slept == [7.0, 7.0, 7.0]
    with pytest.raises(loop.AgentError) as err:
        run(ask("hello"), FakeExecutor(), FakeAdapter([HTTPError(429)] * 4))
    assert err.value.status == 429


def test_provider_down_retries_once_then_uses_the_fallback_model():
    primary = FakeAdapter([HTTPError(503), HTTPError(503)])
    backup = FakeAdapter([say("from the fallback")])
    adapters = {"m_" + "a" * 24: primary, "m_" + "b" * 24: backup}
    result = loop.run_turn(ask("hello", model="m_" + "a" * 24, fallback_models=["m_" + "b" * 24]), executor=FakeExecutor(),
                           adapter_factory=lambda mid: adapters[mid], sleep=lambda s: None)
    assert result["message"] == "from the fallback"


def test_no_fallback_once_a_job_started():
    ex = FakeExecutor(results={"compare_runs": {"job_id": "abcdef0123", "result_path": "/x"}})
    primary = FakeAdapter([tool("compare_runs", {"runs": ["fitloop_v2", "fitloop_v1"]}), HTTPError(503), HTTPError(503)])
    with pytest.raises(loop.AgentError) as err:
        loop.run_turn(ask("compare runs", fallback_models=["m_" + "b" * 24]), executor=ex,
                      adapter_factory=lambda mid: primary, sleep=lambda s: None, poll_interval=0)
    assert err.value.code == "down" and "keep running" in str(err.value)


# ---------------------------------------------------------------------------
# request validation and the native / JSON protocols
# ---------------------------------------------------------------------------

def test_request_validation():
    with pytest.raises(ValueError):
        loop.validate({"messages": [{"role": "user", "content": "hi"}]})
    with pytest.raises(ValueError):
        loop.validate({**ask("hi"), "files": [{"name": "a.csv", "text": "x" * 300_000}]})
    with pytest.raises(ValueError):
        loop.validate({**ask("hi"), "model": "gpt-4"})


def test_json_protocol_conversation_and_native_detection():
    from app.services.chat_agent import model
    msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "1", "type": "function", "function": {"name": "list_runs", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "1", "name": "list_runs", "content": "[]"}]
    out = model.to_json_messages(msgs, [{"name": "list_runs", "description": "d", "parameters": {}}])
    assert '"action": "tool"' in out[2]["content"] and out[3]["content"].startswith("Tool result for list_runs")
    assert "list_runs" in out[0]["content"]
    assert model.supports_native("https://api.anthropic.com/v1/") and not model.supports_native("http://127.0.0.1:5055/v1")
    assert model.classify(HTTPError(401)) == "auth" and model.classify(HTTPError(502)) == "down"


def test_workspace_map_stays_compact():
    class Big(FakeExecutor):
        def runs(self):
            return [{"name": f"run_{i}", "title": "t" * 500, "decision": "go", "people": 10, "status": "running"} for i in range(40)]

        def product_profile(self):
            return {"name": "x" * 5000, "unknowns": ["y" * 5000] * 10}
    text = loop.workspace_map(Big(), state.session("chat-map-0001"), {"run": None, "project": None})
    assert len(text) <= loop.MAP_CHARS + 30


def test_phase_detection():
    assert loop.detect_phase("compare my last two experiments", True, []) == "review"
    assert loop.detect_phase("design an audience of young parents on Android", True, []) == "audience"
    assert loop.detect_phase("test these two headlines for busy parents in India", True, []) == "test"
    assert loop.detect_phase("hello", False, []) == "setup"
    assert loop.detect_phase("hello", True, ["analytics"]) == "audience"
