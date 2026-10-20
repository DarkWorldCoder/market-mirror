"""Several backends side by side: per-instance settings and data directories, start/stop scripts per port,
mm.sh gateway arguments, pool-safe multi-provider settings, and the agent context wiring."""

import json
import os
import random
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND / "claude_cli"))
sys.path.insert(0, str(BACKEND / "scripts"))
import providers  # noqa: E402
import agent_context as ac  # noqa: E402


def _config_in_subprocess(env_extra):
    code = ("import json; from app.config import Config; from app.services.simulation_manager import SimulationManager; "
            "from app.services.simulation_runner import SimulationRunner; import os; "
            "print(json.dumps({'upload': Config.UPLOAD_FOLDER, 'sims': Config.OASIS_SIMULATION_DATA_DIR, "
            "'graph': Config.LOCAL_GRAPH_DB, 'manager': SimulationManager.SIMULATION_DATA_DIR, "
            "'runner': SimulationRunner.RUN_STATE_DIR, 'tasks': os.environ.get('MM_TASK_DB_PATH'), "
            "'gateway': os.environ.get('LLM_GATEWAY'), 'model': Config.LLM_MODEL_NAME}))")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("MIROFISH_", "LLM_", "MM_TASK"))}
    env.update(env_extra)
    out = subprocess.run([sys.executable, "-c", code], cwd=str(BACKEND), env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_each_backend_instance_has_its_own_settings_and_data(tmp_path):
    env_file = tmp_path / ".env.codex"
    env_file.write_text("LLM_PROVIDER=openai\nLLM_BASE_URL=http://127.0.0.1:5092/v1\nLLM_API_KEY=tok\n"
                        "LLM_GATEWAY=codex\nLLM_MODEL_NAME=codex\n")
    a = _config_in_subprocess({"MIROFISH_UPLOAD_DIR": str(tmp_path / "a"), "MIROFISH_ENV_FILE": str(env_file)})
    b = _config_in_subprocess({"MIROFISH_UPLOAD_DIR": str(tmp_path / "b"), "MIROFISH_ENV_FILE": str(env_file)})
    for inst, d in ((a, tmp_path / "a"), (b, tmp_path / "b")):
        assert inst["upload"] == str(d) and inst["sims"] == str(d / "simulations")
        assert inst["graph"] == str(d / "local_graph.db") and inst["tasks"] == str(d / "tasks.sqlite")
        assert os.path.abspath(inst["manager"]) == str(d / "simulations") == os.path.abspath(inst["runner"])
        assert inst["gateway"] == "codex" and inst["model"] == "codex"
    assert a["graph"] != b["graph"]


def test_missing_env_file_is_an_error(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("MIROFISH_")}
    env["MIROFISH_ENV_FILE"] = str(tmp_path / "nope.env")
    out = subprocess.run([sys.executable, "-c", "import app.config"], cwd=str(BACKEND), env=env, capture_output=True, text=True, timeout=60)
    assert out.returncode != 0 and "MIROFISH_ENV_FILE not found" in out.stderr


def test_start_and_stop_scripts_take_a_port():
    start = BACKEND / "claude_cli" / "start_server.sh"
    stop = BACKEND / "claude_cli" / "stop_server.sh"
    r = subprocess.run(["bash", str(start), "--port", "abc"], capture_output=True, text=True, timeout=30)
    assert r.returncode == 2 and "--port must be a number" in r.stderr
    r = subprocess.run(["bash", str(start), "--bogus"], capture_output=True, text=True, timeout=30)
    assert r.returncode == 2
    r = subprocess.run(["bash", str(start), "--port", "59997", "--env-file", "/nonexistent/.env.x"], capture_output=True, text=True, timeout=30)
    assert r.returncode == 1 and "env file not found" in r.stderr
    r = subprocess.run(["bash", str(stop), "--port", "59997"], capture_output=True, text=True, timeout=60)
    assert json.loads(r.stdout.strip().splitlines()[-1]) == {"status": "not_running", "port": 59997}


def _mm(*args, home=ROOT):
    env = {**os.environ, "MARKET_MIRROR_HOME": str(home)}
    return subprocess.run(["bash", str(ROOT / "plugin/skills/market-mirror/scripts/mm.sh"), *args],
                          capture_output=True, text=True, timeout=60, env=env)


@pytest.mark.skipif(not (BACKEND / ".venv/bin/python").exists(), reason="needs the backend venv")
def test_mm_gateway_arguments():
    r = _mm("gateway", "start", "nonsense")
    assert r.returncode != 0 and "unknown gateway backend" in r.stderr
    r = _mm("gateway", "start", "claude", "--port", "x1")
    assert r.returncode != 0 and "--port must be a number" in r.stderr
    r = _mm("gateway", "status", "--port", "59996")
    assert "no gateway on port 59996" in r.stderr
    r = _mm("gateway", "stop", "antigravity", "--port", "59996")
    assert "no gateway running on port 59996" in r.stderr
    assert "antigravity" in _mm("help").stderr + _mm("help").stdout


def test_multi_provider_settings_keep_a_working_single_provider(tmp_path):
    from dotenv import dotenv_values
    providers.write_config(tmp_path, "multi", "multi", pool="claude:claude-sonnet-4-5,openai:gpt-5.4,gemini:gemini-2.5-flash")
    env = dotenv_values(tmp_path / ".env")
    assert env["LLM_PROVIDER"] == "claude" and env["LLM_MODEL_NAME"] == "claude-sonnet-4-5"
    assert env["LLM_BASE_URL"].startswith("https://api.anthropic.com") and env["MARKET_MIRROR_PROVIDER"] == "multi"
    assert env["LLM_POOL"].startswith("claude:")
    providers.write_config(tmp_path, "multi", "multi", pool="gemini,claude")
    assert dotenv_values(tmp_path / ".env")["LLM_PROVIDER"] == "gemini"
    with pytest.raises(ValueError, match="login gateway"):
        providers.write_config(tmp_path, "multi", "multi", pool="codex")
    os.environ["CODEX_GATEWAY_URL"], os.environ["CODEX_GATEWAY_KEY"] = "http://127.0.0.1:5092/v1", "gw-token"
    try:
        providers.write_config(tmp_path, "multi", "multi", pool="codex,antigravity")
    finally:
        del os.environ["CODEX_GATEWAY_URL"], os.environ["CODEX_GATEWAY_KEY"]
    env = dotenv_values(tmp_path / ".env")
    assert env["LLM_PROVIDER"] == "openai" and env["LLM_GATEWAY"] == "codex" and env["LLM_API_KEY"] == "gw-token"
    assert "antigravity" in providers.CATALOG


def test_production_example_has_a_single_provider_next_to_the_pool():
    from dotenv import dotenv_values
    env = dotenv_values(ROOT / ".env.production.example")
    assert env["LLM_PROVIDER"] in ("claude", "openai", "gemini") and env["LLM_MODEL_NAME"] != "multi"
    assert env["LLM_POOL"]


def test_agent_context_uses_occupation_and_behavior_state(tmp_path):
    ac.reset()
    sim = tmp_path / "sim"
    sim.mkdir()
    (sim / "behavior_state.json").write_text(json.dumps({"version": 1, "scopes": {"default": {
        "1": {"state": {"fatigue": 0.9, "trust": 0.5}}, "2": {"state": {"fatigue": 0.0, "trust": 0.1}}}}}))
    cfg_path = sim / "simulation_config.json"
    config = {"persona_index": [{"agent_id": 1, "name": "A", "occupation": "night shift nurse"},
                                {"agent_id": 2, "name": "B", "occupation": "student"},
                                {"agent_id": 3, "name": "C", "segment": "Parents"}],
              "agent_configs": [{"agent_id": i, "activity_level": 1.0} for i in (1, 2, 3)]}
    cfg_path.write_text(json.dumps(config))

    class Graph:
        def get_agents(self):
            return []
    ac.install(Graph(), config, platform="twitter", config_path=str(cfg_path))
    st = ac._state("twitter")
    assert st["occupations"] == {1: "night shift nurse", 2: "student", 3: "Parents"}
    ac.begin_round(1, 3, platform="twitter")
    assert st["behavior_states"][1]["fatigue"] == 0.9
    assert st["moods"][1] == "irritated by repeated ads"            # fatigue from earlier ad tests
    assert st["moods"][2] == "sceptical and guarded"                # low trust
    # occupation shapes online hours: at 3am a night-shift worker is more active than an office worker
    night = sum(ac.round_flavour(1, 1, 3, random.Random(s), {1: 1.0}, occupation="night shift nurse")[0] for s in range(200))
    office = sum(ac.round_flavour(1, 1, 3, random.Random(s), {1: 1.0}, occupation="accountant")[0] for s in range(200))
    assert night > office
    ac.reset()


def test_agent_context_recognises_gateways_on_any_port(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:5092/v1")
    monkeypatch.delenv("LLM_GATEWAY", raising=False)
    monkeypatch.setenv("LLM_API_KEY", "tok")
    assert not ac.via_local_gateway()
    monkeypatch.setenv("LLM_GATEWAY", "codex")
    assert ac.via_local_gateway()
