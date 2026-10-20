import pytest

from app.config import Config
from app.utils import local_graph


@pytest.fixture(autouse=True)
def _isolated_local_graph_db(tmp_path, monkeypatch):
    """Never let a test touch the real backend/uploads/local_graph.db."""

    monkeypatch.setattr(Config, "LOCAL_GRAPH_DB", str(tmp_path / "local_graph.db"))
    # Never let a test touch the real backend/uploads/tasks.sqlite either.
    monkeypatch.setenv("MM_TASK_DB_PATH", str(tmp_path / "tasks.sqlite"))
    # ...nor the people cache (backend/uploads/population_cache.sqlite): every test starts with an empty one
    monkeypatch.setenv("MM_POPULATION_CACHE", str(tmp_path / "population_cache.sqlite"))
    # Tests never download an embedding model; embedding tests inject a fake.
    monkeypatch.setattr(Config, "MEMORY_EMBEDDINGS", False)
    local_graph.clear_local_zep_clients()
    yield
    local_graph.clear_local_zep_clients()
