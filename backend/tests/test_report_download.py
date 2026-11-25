"""Report download when the Markdown file is missing: served from memory, no temp file left behind."""

from types import SimpleNamespace

import pytest

from app import create_app
from app.api import setup as setup_api
from app.services import report_agent


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MIROFISH_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setattr(setup_api, "SETUP_TOKEN", "tok")
    monkeypatch.setattr(report_agent.ReportManager, "get_report", classmethod(
        lambda cls, rid: SimpleNamespace(report_id=rid, markdown_content="# Report\n\nGo, 42 people.\n")))
    monkeypatch.setattr(report_agent.ReportManager, "_get_report_markdown_path",
                        classmethod(lambda cls, rid: str(tmp_path / "missing" / f"{rid}.md")))
    temp_dir = tmp_path / "tmp"
    temp_dir.mkdir()
    import tempfile
    monkeypatch.setattr(tempfile, "tempdir", str(temp_dir))
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client(), temp_dir


def test_download_without_markdown_file_leaves_no_temp_file(client):
    http, temp_dir = client
    resp = http.get("/api/report/rep_1/download", headers={"X-Setup-Token": "tok"})
    assert resp.status_code == 200
    assert resp.data == "# Report\n\nGo, 42 people.\n".encode("utf-8")
    assert "rep_1.md" in resp.headers["Content-Disposition"]
    leftovers = list(temp_dir.iterdir())
    assert not leftovers, f"download left temp files: {leftovers}"
