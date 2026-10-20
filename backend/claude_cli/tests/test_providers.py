import io
import json
import os
import shlex
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import providers
import agent_install


def test_private_provider_configuration_preserves_unrelated_settings(tmp_path):
    from dotenv import dotenv_values
    (tmp_path / ".env").write_text("MEMORY_BACKEND=local\nLLM_GATEWAY=codex\nLLM_API_KEY=old\n")
    result = providers.write_config(tmp_path, "anthropic", "chosen-model", key="secret-sentinel#token")
    assert "secret-sentinel" not in json.dumps(result)
    env = dotenv_values(tmp_path / ".env")
    assert env["LLM_API_KEY"] == "secret-sentinel#token" and env["MEMORY_BACKEND"] == "local"
    assert "LLM_GATEWAY" not in env
    assert os.stat(tmp_path / ".env").st_mode & 0o777 == 0o600
    providers.write_config(tmp_path, "ollama", "installed-local-model")
    assert providers.read_env(tmp_path)["LLM_API_KEY"] == "local"
    assert providers.status(tmp_path)["provider"] == "ollama"


@pytest.mark.parametrize("url", ["http://remote.example/v1", "https://user:key@example.com/v1", "https://example.com/v1?key=secret"])
def test_provider_url_rejects_unsafe_credential_destinations(url):
    with pytest.raises(ValueError):
        providers.validate_url(url)


def test_provider_check_discovers_models_without_inference_or_error_body(tmp_path):
    providers.write_config(tmp_path, "ollama", "local-model")
    def opener(request, timeout):
        assert request.full_url.endswith("/v1/models") and timeout == 15
        return io.BytesIO(b'{"data":[{"id":"local-model"}]}')
    result = providers.check(tmp_path, opener)
    assert result["model_listed"] and result["inference_tested"] is False
    def denied(*args, **kwargs):
        raise HTTPError("https://example.com", 401, "secret-sentinel", {}, io.BytesIO(b"secret-sentinel"))
    result = providers.check(tmp_path, denied)
    assert result["status"] == "authentication_failed" and "secret-sentinel" not in json.dumps(result)


def test_agent_registration_is_portable_and_quotes_paths(tmp_path):
    root = tmp_path / "a project"
    server = root / "plugin/skills/market-mirror/scripts/mcp_server.py"
    server.parent.mkdir(parents=True)
    server.write_text("")
    result = agent_install.configuration(root, "codex")
    assert shlex.split(result["registration_command"]) == result["registration_args"]
    assert result["mcpServers"]["market-mirror"]["args"] == [str(server)]
    assert result["mcpServers"]["market-mirror"]["env"]["MARKET_MIRROR_HOME"] == str(root)


def test_cached_plugin_finds_registered_checkout_with_environment_override(tmp_path):
    import subprocess
    root = tmp_path / "installed checkout"
    server = root / "plugin/skills/market-mirror/scripts/mcp_server.py"
    server.parent.mkdir(parents=True)
    server.write_text("")
    (root / "backend/claude_cli").mkdir(parents=True)
    (root / "backend/claude_cli/mirofish.py").write_text("")
    registry = tmp_path / "registry"
    agent_install.register_engine(root, registry)
    helper = Path(__file__).resolve().parents[3] / "plugin/skills/market-mirror/scripts/mm.sh"
    env = {k:v for k,v in os.environ.items() if k not in ("MARKET_MIRROR_HOME","MIROFISH_HOME")}
    env["MARKET_MIRROR_CONFIG_DIR"] = str(registry)
    def home(settings):
        return subprocess.check_output(["bash",str(helper),"home"],env=settings,text=True).strip()
    assert home(env) == str(root)
    assert home({**env,"MARKET_MIRROR_HOME":"/tmp/explicit-engine"}) == "/tmp/explicit-engine"


def test_other_api_providers_in_catalog_config_and_pool(tmp_path, monkeypatch):
    from dotenv import dotenv_values
    for prov in ("deepseek", "kimi", "mistral", "xai", "groq", "together", "fireworks", "openrouter", "qwen", "zhipu",
                 "cerebras", "minimax"):
        spec = providers.CATALOG[prov]
        assert spec["key_required"] and spec["key_env"].endswith("_API_KEY") and spec["default_model"]
    providers.write_config(tmp_path, "kimi", "kimi-k3", key="moon-secret")
    env = dotenv_values(tmp_path / ".env")
    assert (env["LLM_PROVIDER"], env["LLM_BASE_URL"], env["LLM_MODEL_NAME"]) == ("kimi", "https://api.moonshot.ai/v1", "kimi-k3")
    assert providers.status(tmp_path)["provider"] == "kimi"
    with pytest.raises(ValueError, match="base URL"):
        providers.write_config(tmp_path, "qwen", "qwen3.8-flash", key="q-secret")
    # noninteractive configure: key from the provider's variable, its default model
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-secret-value")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    args = SimpleNamespace(provider="deepseek", model=None, base_url=None, key_env=None, open_guide=False)
    providers.configure(tmp_path, args)
    env = dotenv_values(tmp_path / ".env")
    assert (env["LLM_PROVIDER"], env["LLM_MODEL_NAME"], env["LLM_API_KEY"]) == ("deepseek", "deepseek-flash", "ds-secret-value")
    # a pool led by a hosted API provider keeps it as the single provider
    res = providers.primary_from_pool("deepseek,kimi,claude")
    assert res == {"LLM_PROVIDER": "deepseek", "LLM_BASE_URL": "https://api.deepseek.com", "LLM_MODEL_NAME": "deepseek-flash"}
    assert providers.primary_from_pool("grok:grok-4.7")["LLM_MODEL_NAME"] == "grok-4.7"


def test_gemini_chatgpt_codex_and_multi_provider_catalog(tmp_path):
    for key in ("gemini", "gemini_cli", "chatgpt", "codex", "multi"):
        assert key in providers.CATALOG
    # Gemini API strips models/ prefix during model listing check
    providers.write_config(tmp_path, "gemini", "gemini-2.5-flash", key="gem-secret-key")
    assert providers.status(tmp_path)["provider"] == "gemini"
    def gemini_opener(request, timeout):
        return io.BytesIO(b'{"data":[{"id":"models/gemini-2.5-flash"}]}')
    chk = providers.check(tmp_path, gemini_opener)
    assert chk["model_listed"] is True

    # Multi-provider pool configuration writes LLM_POOL
    res = providers.write_config(tmp_path, "multi", "multi", pool="claude:sonnet,chatgpt:gpt-5.4,codex:gpt-5.4,gemini:gemini-2.5-flash")
    assert res["provider"] == "multi"
    assert "gemini:gemini-2.5-flash" in res["pool"]

    # Gemini CLI MCP registration
    root = tmp_path / "gem_proj"
    server = root / "plugin/skills/market-mirror/scripts/mcp_server.py"
    server.parent.mkdir(parents=True)
    server.write_text("")
    gem_reg = agent_install.configuration(root, "gemini")
    assert gem_reg["registration_args"][:3] == ["gemini", "mcp", "add"]

