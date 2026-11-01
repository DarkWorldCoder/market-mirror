import pytest


@pytest.fixture(autouse=True)
def _no_real_jev(tmp_path, monkeypatch):
    """Never call the real Jev from a test: no key from the environment or a .env file."""
    for k in ("TYPESAFE_API_KEY", "OPENROUTER_API_KEY", "JEV_VIA", "JEV_BASE_URL"):
        monkeypatch.delenv(k, raising=False)
    (tmp_path / "no.env").write_text("")
    monkeypatch.setenv("MIROFISH_ENV_FILE", str(tmp_path / "no.env"))
