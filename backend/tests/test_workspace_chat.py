"""Local conversational assistant: no live model calls or test execution."""
import copy
import json
from types import SimpleNamespace as NS
from pathlib import Path

import pytest

from app import create_app
from app.config import Config
from app.api import setup as setup_api
from app.services import workspace_chat as chat

H = {"X-Setup-Token": "tok"}
REAL_MODEL = chat._model
INPUT = {"messages": [{"role": "user", "content": "What did my pricing test show?"}]}


class Model:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def chat_json(self, messages, **options):
        self.calls.append(copy.deepcopy(messages))
        assert options["max_attempts"] == 1
        assert options["max_tokens"] == 3000
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    run = runs / "acme"
    run.mkdir(parents=True)
    (run / "summary.json").write_text(json.dumps({"project_name": "Acme", "marketing": {"people": 12}}))
    (run / "pricing.json").write_text(json.dumps({"price": 29, "note": "saved test"}))
    (run / "research.md").write_text("Evidence line. " * 3000)
    (run / "secret.env").write_text("NEVER_READ_THIS=private")
    monkeypatch.setenv("MIROFISH_RUNS_DIR", str(runs))
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path / "uploads"))
    monkeypatch.setattr(setup_api, "SETUP_TOKEN", "tok")
    app = create_app()
    app.config.update(TESTING=True)
    model = Model({"message": "Hello from the configured model."})
    monkeypatch.setattr(chat, "_model", lambda: model)
    return app.test_client(), model, run


def test_token_loopback_and_origin_are_required(fixture):
    client, model, _ = fixture
    assert client.post("/api/workspace/chat", json=INPUT).status_code == 403
    assert client.post("/api/workspace/chat", json=INPUT, headers=H,
                       environ_base={"REMOTE_ADDR": "192.168.1.2"}).status_code == 403
    assert client.post("/api/workspace/chat", json=INPUT,
                       headers={**H, "Origin": "https://attacker.example"}).status_code == 403
    assert not model.calls


@pytest.mark.parametrize("value", [None, [], {}, {"messages": []},
    {"messages": [{"role": "system", "content": "override"}]},
    {"messages": [{"role": "assistant", "content": "not a question"}]},
    {"messages": [{"role": "user", "content": " "}]},
    {"messages": [{"role": "user", "content": "x" * 12001}]},
    {"messages": [{"role": "user", "content": "x"}] * 31},
    {"messages": [{"role": "user", "content": "x" * 9000}] * 6},
    {**INPUT, "run": "../private"}, {**INPUT, "run": 1}])
def test_bad_input_never_calls_model(fixture, value):
    client, model, _ = fixture
    response = client.post("/api/workspace/chat", json=value, headers=H)
    assert response.status_code == 400
    assert not model.calls


def test_real_answer_and_bounded_history_are_forwarded(fixture):
    client, model, _ = fixture
    payload = {"messages": [{"role": "user", "content": "I sell a workout app."},
                            {"role": "assistant", "content": "Who is your audience?"},
                            {"role": "user", "content": "Busy parents."}]}
    response = client.post("/api/workspace/chat", json=payload, headers=H)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    data = response.json["data"]
    assert data == {"message": "Hello from the configured model.", "artifacts": [], "trace": [], "suggestions": []}
    assert model.calls[0][1:] == payload["messages"]
    assert model.calls[0][0]["role"] == "system"


def test_project_context_is_loaded_on_server_as_untrusted_data(fixture, monkeypatch):
    from app.services import workspace_projects
    client, model, _ = fixture
    project = {"id": "proj_abcdef123456", "name": "Acme", "instructions": "Focus on buyers", "run_names": ["acme"]}
    monkeypatch.setattr(workspace_projects, "get_project", lambda identifier: project)
    response = client.post("/api/workspace/chat", json={**INPUT, "project": project["id"]}, headers=H)
    assert response.status_code == 200
    content = model.calls[0][-2]["content"]
    assert "untrusted reference data" in content
    assert "Focus on buyers" in content
    assert "authorize spending" in content


def test_unknown_project_never_calls_model(fixture):
    client, model, _ = fixture
    response = client.post("/api/workspace/chat", json={**INPUT, "project": "../private"}, headers=H)
    assert response.status_code == 400
    assert not model.calls


def test_read_evidence_returns_verified_artifact_and_actual_trace(fixture):
    client, model, _ = fixture
    model.answers = [
        {"action": "list_runs", "arguments": {"limit": 10}},
        {"action": "read_run", "arguments": {"run": "acme"}},
        {"action": "read_run_file", "arguments": {"run": "acme", "file": "pricing.json"}},
        {"action": "respond", "message": "The saved price is 29.",
         "artifacts": [{"run": "acme", "file": "pricing.json"}, {"run": "acme", "file": "secret.env"}],
         "suggestions": ["Compare segments"]},
    ]
    data = client.post("/api/workspace/chat", json={**INPUT, "run": "acme"}, headers=H).json["data"]
    assert data["artifacts"] == [{"run": "acme", "file": "pricing.json"}]
    assert [t["tool"] for t in data["trace"]] == ["list_runs", "read_run", "read_run_file"]
    assert all(t["status"] == "completed" for t in data["trace"])
    assert len(model.calls) == 4
    tool_result = json.loads(model.calls[-1][-2]["content"].split(": ", 1)[1])
    assert json.loads(tool_result["content"])["price"] == 29
    assert data["suggestions"] == ["Compare segments"]


def test_tools_are_read_only_and_reject_paths_and_symlinks(fixture, tmp_path):
    client, model, run = fixture
    outside = tmp_path / "private.json"
    outside.write_text('{"password":"NEVER_READ_THIS"}')
    (run / "linked.json").symlink_to(outside)
    for action, arguments in [("shell", {"command": "rm -rf /"}),
                               ("read_run_file", {"run": "acme", "file": "../private.json"}),
                               ("read_run_file", {"run": "acme", "file": "linked.json"}),
                               ("read_run_file", {"run": "acme", "file": "secret.env"})]:
        model.answers = [{"action": action, "arguments": arguments}, {"message": "Cannot read that file."}]
        result = client.post("/api/workspace/chat", json=INPUT, headers=H).json["data"]
        assert result["artifacts"] == []
        assert result["trace"][0]["status"] == "failed"
        assert "NEVER_READ_THIS" not in json.dumps(model.calls[-1])


def test_report_reads_are_paged_with_explicit_truncation(fixture):
    _, _, _ = fixture
    value, artifact = chat._tool("read_run_file", {"run": "acme", "file": "research.md", "limit": 100})
    assert len(value["content"]) == 100
    assert value["truncated"] is True and value["next_offset"] == 100
    next_page, _ = chat._tool("read_run_file", {"run": "acme", "file": "research.md", "offset": 100, "limit": 100})
    assert next_page["offset"] == 100
    assert artifact == {"run": "acme", "file": "research.md"}
    for args in ({"limit": 999999}, {"offset": -1}, {"offset": True}):
        with pytest.raises(ValueError):
            chat._tool("read_run_file", {"run": "acme", "file": "research.md", **args})


def test_repeated_tools_stop_after_four_model_turns(fixture):
    client, model, _ = fixture
    model.answers = [{"action": "list_runs", "arguments": {}} for _ in range(4)]
    data = client.post("/api/workspace/chat", json=INPUT, headers=H).json["data"]
    assert len(model.calls) == 4 and len(data["trace"]) == 3
    assert "lookup limit" in data["message"]


def test_provider_errors_are_redacted(fixture, monkeypatch):
    client, model, _ = fixture
    model.answers = [RuntimeError("sk-secret sensitive request body")]
    response = client.post("/api/workspace/chat", json=INPUT, headers=H)
    assert response.status_code == 502
    assert "sk-secret" not in response.get_data(as_text=True)
    def missing():
        raise chat.ChatError("Connect a model in Model settings, then send your message again.", 409)
    monkeypatch.setattr(chat, "_model", missing)
    response = client.post("/api/workspace/chat", json=INPUT, headers=H)
    assert response.status_code == 409 and "Model settings" in response.json["error"]


def test_workflow_draft_is_saved_but_never_executed(fixture):
    client, model, _ = fixture
    draft = {"recipe": "ads", "name": "Fitloop", "product": "Short home workouts", "audience": "Busy parents",
             "country": "Nepal", "variants": [{"text": "Short workouts at home"}, {"text": "Fifteen-minute sessions"}]}
    model.answers = [{"message": "I prepared your comparison draft.", "workflow_draft": draft}]
    data = client.post("/api/workspace/chat", json=INPUT, headers=H).json["data"]
    from app.services import workflows
    record = workflows.get(data["workflow_id"])
    assert record["stages"] == {} and record["people"] == []
    assert record["inputs"]["product"] == draft["product"]
    assert data["trace"][-1]["tool"] == "create_draft"
    assert "approving" in data["message"]


def test_incomplete_draft_prompts_for_details(fixture):
    client, model, _ = fixture
    model.answers = [{"message": "Let's prepare a test.", "workflow_draft": {"name": "Acme"}}]
    data = client.post("/api/workspace/chat", json=INPUT, headers=H).json["data"]
    assert "workflow_id" not in data
    assert data["trace"][-1]["status"] == "needs_input"
    assert not (Path(Config.UPLOAD_FOLDER) / "workflows").exists()


def test_attached_context_is_forwarded_as_untrusted_data(fixture):
    client, model, _ = fixture
    context = {"name": "Product brief.md", "text": "The app has ten-minute classes. " * 500}
    response = client.post("/api/workspace/chat", json={**INPUT, "context": context}, headers=H)
    assert response.status_code == 200
    assert model.calls[0][-1] == INPUT["messages"][-1]
    assert "untrusted reference data" in model.calls[0][-2]["content"]
    assert context["text"].strip() in model.calls[0][-2]["content"]


@pytest.mark.parametrize("context", [[], {"name": "x", "text": "x" * 24001},
    {"name": "x" * 201, "text": "brief"}, {"name": "x", "text": None}])
def test_invalid_context_never_calls_model(fixture, context):
    client, model, _ = fixture
    response = client.post("/api/workspace/chat", json={**INPUT, "context": context}, headers=H)
    assert response.status_code == 400 and not model.calls


@pytest.fixture
def catalog(fixture, tmp_path, monkeypatch):
    client, _, _ = fixture
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr(setup_api, "LOGS", logs)
    monkeypatch.setattr(setup_api, "_find_bin", lambda backend: None)
    monkeypatch.setattr(chat, "_gateway_models", lambda port, key: (["sonnet"] if port == 5055 else ["gpt-login"] if port == 5056 else None) if key else None)
    slots = [NS(provider="claude", model="sonnet", base_url="http://127.0.0.1:5055/v1", api_key="PRIVATE_LOCAL_TOKEN"),
             NS(provider="openai", model="gpt-configured", base_url="https://api.openai.com/v1", api_key="PRIVATE_HOSTED_KEY")]
    monkeypatch.setattr(Config, "get_model_pool", lambda: NS(slots=slots))
    monkeypatch.setattr(chat, "_gateway_health", lambda port: {"backend": "claude", "model": "sonnet", "available": True,
                                                           "auth_required": True} if port == 5055 else None)
    return client, slots


def test_model_catalog_is_safe_stable_and_token_guarded(catalog):
    client, _ = catalog
    assert client.get("/api/workspace/models").status_code == 403
    response = client.get("/api/workspace/models", headers=H)
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    data = response.json["data"]
    assert data == client.get("/api/workspace/models", headers=H).json["data"]
    assert {row["model"] for row in data["models"]} == {"sonnet", "haiku", "opus", "gpt-configured"}
    assert data["default_id"] == next(row["id"] for row in data["models"] if row["model"] == "sonnet")
    encoded = json.dumps(data)
    assert "PRIVATE" not in encoded and "api_key" not in encoded and "base_url" not in encoded
    assert all(row["available"] for row in data["models"])


def test_selected_models_route_exact_provider_credentials_without_global_writes(catalog, monkeypatch):
    _, slots = catalog
    calls = []
    class Client:
        def __init__(self, **kwargs):
            calls.append(kwargs)
            self.client = self
        def with_options(self, **kwargs):
            assert kwargs == {"max_retries": 0, "timeout": 90}
            return self
    monkeypatch.setattr(chat, "LLMClient", Client)
    models = chat.models()["models"]
    opus = next(m for m in models if m["model"] == "opus")
    hosted = next(m for m in models if m["model"] == "gpt-configured")
    REAL_MODEL(opus["id"])
    REAL_MODEL(hosted["id"])
    assert calls == [{"api_key": "PRIVATE_LOCAL_TOKEN", "base_url": "http://127.0.0.1:5055/v1", "model": "opus"},
                     {"api_key": "PRIVATE_HOSTED_KEY", "base_url": "https://api.openai.com/v1", "model": "gpt-configured"}]
    assert slots[0].model == "sonnet" and slots[1].model == "gpt-configured"


def test_chat_forwards_selected_catalog_id(fixture, monkeypatch):
    client, model, _ = fixture
    selected = "m_" + "a" * 24
    received = []
    def choose(identifier):
        received.append(identifier)
        return model
    monkeypatch.setattr(chat, "_model", choose)
    response = client.post("/api/workspace/chat", headers=H, json={**INPUT, "model": selected,
        "base_url": "https://evil.example", "api_key": "DO_NOT_USE"})
    assert response.status_code == 200 and received == [selected]


def test_arbitrary_or_unavailable_model_cannot_be_selected(catalog, fixture, monkeypatch):
    client, _ = catalog
    monkeypatch.setattr(chat, "_model", REAL_MODEL)
    for model in ("opus", {"api_key": "bad"}, "m_" + "0" * 24):
        assert client.post("/api/workspace/chat", headers=H, json={**INPUT, "model": model}).status_code == 400
    monkeypatch.setattr(chat, "_gateway_health", lambda port: None)
    rows = chat.models()["models"]
    sonnet = next(m for m in rows if m["model"] == "sonnet")
    assert sonnet["available"] is False
    response = client.post("/api/workspace/chat", headers=H, json={**INPUT, "model": sonnet["id"]})
    assert response.status_code == 409 and "unavailable" in response.json["error"]


def test_discovered_gateway_requires_usable_local_credentials(catalog, monkeypatch):
    client, slots = catalog
    monkeypatch.setattr(chat, "_gateway_health", lambda port: {"backend": "codex", "model": "gpt-login", "available": True,
        "auth_required": True} if port == 5056 else None)
    rows = chat.models()["models"]
    discovered = next(m for m in rows if m["model"] == "gpt-login")
    assert discovered["available"] is False
    (setup_api.LOGS / "gateway-5056.token").write_text("PRIVATE_DISCOVERED_TOKEN")
    rows = chat.models()["models"]
    assert next(m for m in rows if m["model"] == "gpt-login")["available"] is True
    assert "PRIVATE_DISCOVERED_TOKEN" not in json.dumps(rows)


@pytest.mark.parametrize("selected_model,expected_url", [("haiku", "http://127.0.0.1:5055/v1"),
                                                        ("gpt-configured", "https://api.openai.com/v1")])
def test_catalog_choice_reaches_actual_chat_completion_request(catalog, monkeypatch, selected_model, expected_url):
    client, _ = catalog
    from app.utils import llm_client
    calls = []
    class Transport:
        def __init__(self, **options):
            self.options = options
            self.base_url = options["base_url"]
            self.chat = NS(completions=self)
        def with_options(self, **options):
            return self
        def create(self, **kwargs):
            calls.append({"target": self.options, "request": kwargs})
            return NS(choices=[NS(finish_reason="stop", message=NS(content='{"message":"Model-specific answer"}'))])
    monkeypatch.setattr(llm_client, "OpenAI", Transport)
    monkeypatch.setattr(chat, "_model", REAL_MODEL)
    chosen = next(m for m in chat.models()["models"] if m["model"] == selected_model)
    response = client.post("/api/workspace/chat", headers=H, json={**INPUT, "model": chosen["id"]})
    assert response.status_code == 200
    assert response.json["data"]["message"] == "Model-specific answer"
    assert calls[0]["request"]["model"] == selected_model
    assert calls[0]["target"]["base_url"] == expected_url


def test_chat_home_guided_entry_and_brand_asset_are_served(fixture, tmp_path, monkeypatch):
    from app.api import workflows as web
    client, _, _ = fixture
    dist = tmp_path / 'dist'
    dist.mkdir()
    (dist / 'index.html').write_text('<main>MarketMirror chat</main>')
    (dist / 'marketmirror.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"><title>MarketMirror</title></svg>')
    monkeypatch.setattr(web, 'DIST', dist)
    for path in ('/', '/start', '/workspace/chat'):
        response = client.get(path)
        assert response.status_code == 200 and b'MarketMirror chat' in response.data
    assert client.get('/start', environ_base={'REMOTE_ADDR': '192.168.1.2'}).status_code == 403
    icon = client.get('/marketmirror.svg')
    assert icon.status_code == 200 and 'svg' in icon.content_type


def test_chat_recovers_actual_plain_completion_without_another_model_call(fixture, monkeypatch):
    client, _, _ = fixture
    from app.utils.llm_client import LLMClient
    calls = []
    def complete(**kwargs):
        calls.append(kwargs)
        return NS(choices=[NS(finish_reason="stop", message=NS(content="Hello! Tell me about the product you want to test."))])
    model = object.__new__(LLMClient)
    model.model = "haiku"
    model.client = NS(chat=NS(completions=NS(create=complete)))
    monkeypatch.setattr(chat, "_model", lambda: model)
    response = client.post("/api/workspace/chat", headers=H, json=INPUT)
    assert response.status_code == 200
    assert response.json["data"] == {"message": "Hello! Tell me about the product you want to test.",
                                      "artifacts": [], "trace": [], "suggestions": []}
    assert len(calls) == 1 and calls[0]["model"] == "haiku"


@pytest.mark.parametrize("text,finish", [('{"action":"respond","message":', "stop"),
    ('Here is the result: {"action":"read_run_file","arguments":', "stop"),
    ('```json\n{"action":"respond"', "stop"), ("Partial plain text", "length")])
def test_chat_does_not_accept_broken_or_truncated_protocol_as_prose(fixture, monkeypatch, text, finish):
    client, _, _ = fixture
    from app.utils.llm_client import LLMClient
    calls = []
    def complete(**kwargs):
        calls.append(kwargs)
        return NS(choices=[NS(finish_reason=finish, message=NS(content=text))])
    model = object.__new__(LLMClient)
    model.model = "haiku"
    model.client = NS(chat=NS(completions=NS(create=complete)))
    monkeypatch.setattr(chat, "_model", lambda: model)
    response = client.post("/api/workspace/chat", headers=H, json=INPUT)
    assert response.status_code == 502 and "data" not in response.json
    assert len(calls) == 1


def test_local_browser_can_bootstrap_without_cli_token(fixture):
    client, _, _ = fixture
    response = client.get('/api/workspace/session', headers={'Sec-Fetch-Site': 'same-origin'})
    assert response.status_code == 200
    assert response.get_json()['data']['token'] == 'tok'
    assert response.headers['Cache-Control'] == 'no-store'
    assert response.headers['Cross-Origin-Resource-Policy'] == 'same-origin'


@pytest.mark.parametrize('headers,remote', [({}, '127.0.0.1'),
    ({'Sec-Fetch-Site': 'cross-site'}, '127.0.0.1'),
    ({'Sec-Fetch-Site': 'same-site', 'Origin':'http://localhost:9999'}, '127.0.0.1'),
    ({'Sec-Fetch-Site': 'same-origin','Origin':'https://evil.example'}, '127.0.0.1'),
    ({'Sec-Fetch-Site': 'same-origin','Host':'evil.example'}, '127.0.0.1'),
    ({'Sec-Fetch-Site': 'same-origin'}, '192.168.1.2')])
def test_session_bootstrap_rejects_external_or_cross_origin_reads(fixture, headers, remote):
    client, _, _ = fixture
    response = client.get('/api/workspace/session', headers=headers, environ_base={'REMOTE_ADDR':remote})
    assert response.status_code == 403
    assert 'token' not in (response.get_json().get('data') or {})


def test_spending_limit_has_actionable_response(fixture):
    from app.utils.spend_cap import SpendCapReached
    client, model, _ = fixture
    model.answers = [SpendCapReached('limit reached')]
    response = client.post('/api/workspace/chat', json=INPUT, headers=H)
    assert response.status_code == 409
    assert 'Spending in Settings' in response.json['error']


def test_only_enabled_read_only_connector_tools_are_forwarded(fixture, monkeypatch):
    from app.services import workspace_connectors
    client, model, _ = fixture
    monkeypatch.setattr(workspace_connectors, 'list_connectors', lambda: [{
        'id': 'mcp_abcdef123456', 'name': 'Analytics', 'enabled': True,
        'allowed_tools': ['reports', 'delete'], 'tools': [
            {'name': 'reports', 'description': 'Read reports', 'inputSchema': {}, 'read_only': True},
            {'name': 'delete', 'description': 'Mutate account', 'inputSchema': {}, 'read_only': False}]}])
    calls = []
    def call(identifier, name, arguments):
        calls.append((identifier, name, arguments))
        return {'connector_id': identifier, 'connector': 'Analytics', 'tool': name, 'result': '{"visits":100}', 'truncated': False}
    monkeypatch.setattr(workspace_connectors, 'call_tool', call)
    model.answers = [{'action': 'connector_tool', 'arguments': {'connector_id': 'mcp_abcdef123456', 'name': 'reports', 'arguments': {'period': 'week'}}}, {'message': 'The account report shows 100 visits.'}]
    response = client.post('/api/workspace/chat', json=INPUT, headers=H)
    assert response.status_code == 200
    assert calls == [('mcp_abcdef123456', 'reports', {'period': 'week'})]
    assert response.json['data']['tool_results'][0]['result'] == '{"visits":100}'
    assert 'Mutate account' not in model.calls[0][0]['content']
    assert response.json['data']['trace'][0]['status'] == 'completed'


def test_conversation_tool_selection_blocks_unchosen_tools(fixture, monkeypatch):
    from app.services import workspace_connectors
    client, model, _ = fixture
    monkeypatch.setattr(workspace_connectors, 'list_connectors', lambda: [{'id': 'mcp_abcdef123456', 'name': 'Ads', 'enabled': True, 'allowed_tools': ['reports'], 'tools': [{'name': 'reports', 'read_only': True}]}])
    def forbidden(*args):
        pytest.fail('Unselected tool was called')
    monkeypatch.setattr(workspace_connectors, 'call_tool', forbidden)
    model.answers = [{'action': 'connector_tool', 'arguments': {'connector_id': 'mcp_abcdef123456', 'name': 'reports'}}, {'message': 'Choose and connect a tool to read account data.'}]
    data = client.post('/api/workspace/chat', json={**INPUT, 'connector_tools': []}, headers=H).json['data']
    assert data['trace'][0]['status'] == 'failed'
    assert not data.get('tool_results')


def test_team_mode_runs_only_when_selected(fixture, monkeypatch):
    from app.services import workspace_team
    client, model, _ = fixture
    calls = []
    monkeypatch.setattr(workspace_team, 'review_answer', lambda result, history, selected, **kwargs: calls.append(selected) or {**result, 'agent_activity': [{'role': 'Review', 'status': 'completed', 'summary': 'Checked.'}]})
    response = client.post('/api/workspace/chat', json={**INPUT, 'mode': 'team'}, headers=H)
    assert response.status_code == 200
    assert calls == [model]
    assert response.json['data']['agent_activity'][0]['summary'] == 'Checked.'


def test_saved_summary_reaches_all_reviewers_and_links_to_source(fixture, monkeypatch):
    client, _, run = fixture
    (run / "summary.json").write_text(json.dumps({
        "project_name": "Fit trial",
        "decision": {"decision": "iterate"},
        "marketing": {
            "answered": 20,
            "funnel": [["Surveyed", 20], ["Would start trial", 2]],
            "overall": {"n": 20, "convert_yes": 10.0},
            "responses": [{"nickname": "EXCLUDED_PERSONA"}],
        },
    }))
    reviewed = []

    class ReviewModel:
        def chat_json(self, messages, **options):
            if options["max_tokens"] == 3000:
                assert "Would start trial" in messages[-2]["content"]
                assert "EXCLUDED_PERSONA" not in messages[-2]["content"]
                return {"message": "Draft interpretation."}
            if options["max_tokens"] == 1000:
                material = json.loads(messages[-1]["content"].split("\n", 1)[1])
                evidence = material["selected_run_summary"]
                assert evidence["source"] == {"run": "acme", "file": "summary.json"}
                assert json.loads(evidence["content"])["survey"]["funnel"][-1] == ["Would start trial", 2]
                reviewed.append(evidence)
                return {"summary": "Checked the two of twenty denominator."}
            return {"message": "Combined interpretation."}

    monkeypatch.setattr(chat, "_model", ReviewModel)
    payload = {**INPUT, "mode": "team", "run": "acme", "review_summary": True,
               "team_agents": ["data-analyst", "measurement-specialist", "critical-reviewer"]}
    response = client.post("/api/workspace/chat", json=payload, headers=H)
    assert response.status_code == 200
    result = response.json["data"]
    assert result["artifacts"] == [{"run": "acme", "file": "summary.json"}]
    assert result["message"] == "Combined interpretation."
    assert len(reviewed) == 3
    assert client.post("/api/workspace/chat", json={**payload, "mode": "standard"}, headers=H).status_code == 400


def test_browser_only_opens_a_user_provided_url(fixture, monkeypatch):
    from app.services import workspace_browser
    client, model, _ = fixture
    calls = []
    monkeypatch.setattr(workspace_browser, 'observe', lambda value: calls.append(value) or {'session_id':'br_'+'a'*24,'title':'Example','text':'Actual page content','url':value['url'],'screenshot':'/api/workspace/browser/br_'+'a'*24+'/image'})
    model.answers = [{'action':'browse_page','arguments':{'url':'https://example.com'}},{'message':'The page says Actual page content.'}]
    response=client.post('/api/workspace/chat',json={'messages':[{'role':'user','content':'Analyze https://example.com'}]},headers=H)
    assert response.status_code==200
    assert calls==[{'url':'https://example.com'}]
    assert response.json['data']['browser_observations'][0]['text']=='Actual page content'
    assert 'Actual page content' in model.calls[-1][-1]['content']


def test_browser_cannot_follow_a_model_invented_url(fixture, monkeypatch):
    from app.services import workspace_browser
    client, model, _ = fixture
    def forbidden(value):
        pytest.fail('An unrequested page was opened')
    monkeypatch.setattr(workspace_browser,'observe',forbidden)
    model.answers=[{'action':'browse_page','arguments':{'url':'https://example.com'}},{'message':'Please provide a page URL to analyze.'}]
    data=client.post('/api/workspace/chat',json=INPUT,headers=H).json['data']
    assert data['trace'][0]['status']=='failed'
    assert not data.get('browser_observations')


def test_explicit_website_analysis_captures_before_model_and_reuses_evidence(fixture, monkeypatch):
    from app.services import workspace_browser
    client, model, _ = fixture
    captures = []
    url = 'https://example.com/pricing'
    observation = {'session_id': 'br_' + 'a' * 24, 'url': url, 'text': 'Here is the actual pricing page.'}
    monkeypatch.setattr(workspace_browser, 'observe', lambda value: captures.append(value['url']) or observation)
    model.answers = [{'message': 'Based on the pricing page.'}]
    payload = {'messages': [{'role': 'user', 'content': f'Analyze {url}'}], 'inspect_url': url}
    response = client.post('/api/workspace/chat', json=payload, headers=H)
    assert response.status_code == 200
    assert captures == [url]
    assert response.json['data']['browser_observations'] == [observation]
    assert model.calls[0][-1]['content'] == f'Analyze {url}'
    assert 'actual pricing page' in model.calls[0][-2]['content']
    assert 'untrusted reference data' in model.calls[0][-2]['content']

    bad = client.post('/api/workspace/chat', json={**payload, 'inspect_url': 'https://example.org'}, headers=H)
    assert bad.status_code == 400
    assert captures == [url]
    assert len(model.calls) == 1


def test_explicit_website_analysis_does_not_call_model_when_capture_fails(fixture, monkeypatch):
    from app.services import workspace_browser
    client, model, _ = fixture
    url = 'https://example.com/'
    def fail(value):
        raise ValueError('Capture denied')
    monkeypatch.setattr(workspace_browser, 'observe', fail)
    response = client.post('/api/workspace/chat', headers=H, json={
        'messages': [{'role': 'user', 'content': f'Analyze {url}'}], 'inspect_url': url,
    })
    assert response.status_code == 422
    assert not model.calls


def test_workspace_bodies_are_not_logged(fixture, caplog):
    import logging
    client, _, _ = fixture
    marker='private-workspace-prompt-not-for-log'
    with caplog.at_level(logging.DEBUG):
        client.post('/api/workspace/chat',json={'messages':[{'role':'user','content':marker}]},headers=H)
    assert marker not in caplog.text


def test_selected_project_sources_are_paged_and_reported_as_real_work(fixture, monkeypatch):
    from app.services import workspace_projects
    client, model, _ = fixture
    project={'id':'proj_abcdef123456','name':'Acme','instructions':'Use product evidence.','sources':[{'id':'src_abcdef123456','name':'Product brief','text':'The supported price is 29.'}]}
    monkeypatch.setattr(workspace_projects,'get_project',lambda identity:project)
    model.answers=[{'action':'read_project_source','arguments':{'project_id':project['id'],'source_id':project['sources'][0]['id']}},{'message':'The supplied product brief says the price is 29.'}]
    events=[]
    result=chat.chat({**INPUT,'project':project['id']},on_event=events.append)
    assert result['trace'][0]['label']=='Read project context'
    assert 'The supported price is 29.' in model.calls[-1][-1]['content']
    assert any(event['type']=='tool' and event['status']=='completed' for event in events)


def test_invalid_team_selection_never_spends(fixture):
    client, model, _ = fixture
    response=client.post('/api/workspace/chat',json={**INPUT,'mode':'team','team_agents':['market-analyst']},headers=H)
    assert response.status_code==400
    assert not model.calls
