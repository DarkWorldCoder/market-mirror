"""MEMORY_BACKEND=cognee: CogneeZep with the Cognee sidecar mocked.

The fake sidecar returns graphs in the exact shape the real sidecar produced
with cognee 1.6.5 (lower-cased Entity names, EntityType via ``is_a``,
DocumentChunk ``contains`` edges, relation ``edge_text``).
"""

from __future__ import annotations

import importlib.util
import os
import re
import uuid
from pathlib import Path

import pytest
from zep_cloud import NotFoundError

from app.config import Config
from app.services.zep_entity_reader import ZepEntityReader
from app.services.zep_tools import ZepToolsService
from app.utils import cognee_graph, local_graph, zep
from app.utils.cognee_graph import CogneeSidecarError, CogneeZep, dataset_name
from app.utils.zep_paging import fetch_all_edges, fetch_all_nodes

from test_local_graph import ONTOLOGY, _builder

_WORKS = re.compile(r"(\w+) is the (\w+) of (\w+)")
_PARTNERS = re.compile(r"(\w+) partners with (\w+)")


def _id(*parts: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_OID, "|".join(parts)))


class FakeSidecar:
    def __init__(self, fail_on: str | None = None, search_error: bool = False):
        self.datasets: dict[str, dict] = {}
        self.ingests: list[tuple[str, list[str], str | None]] = []
        self.searches: list[tuple[str, str]] = []
        self.deleted: list[str] = []
        self.fail_on = fail_on
        self.search_error = search_error

    def _graph(self, dataset):
        return self.datasets.setdefault(dataset, {"nodes": {}, "edges": {}})

    def _entity(self, graph, name, type_name, description, chunk_id):
        eid, tid = _id("entity", name.lower()), _id("type", type_name.lower())
        graph["nodes"][eid] = {"id": eid, "name": name.lower(), "type": "Entity",
                               "properties": {"description": description, "created_at": 1792224187638}}
        graph["nodes"][tid] = {"id": tid, "name": type_name.lower(), "type": "EntityType",
                               "properties": {"description": type_name.lower()}}
        graph["edges"][(eid, "is_a", tid)] = {"source": eid, "target": tid, "relationship_name": "is_a",
                                               "properties": {"relationship_name": "is_a"}}
        graph["edges"][(chunk_id, "contains", eid)] = {
            "source": chunk_id, "target": eid, "relationship_name": "contains", "properties": {}}
        return eid

    def ingest(self, dataset, texts, custom_prompt=None):
        self.ingests.append((dataset, list(texts), custom_prompt))
        if self.fail_on and any(self.fail_on in t for t in texts):
            raise CogneeSidecarError("cognify failed: simulated")
        graph = self._graph(dataset)
        for text in texts:
            chunk_id = _id("chunk", text)
            doc_id = _id("doc", text)
            graph["nodes"][chunk_id] = {"id": chunk_id, "name": "", "type": "DocumentChunk",
                                        "properties": {"text": text}}
            graph["nodes"][doc_id] = {"id": doc_id, "name": f"text_{doc_id[:8]}", "type": "TextDocument",
                                      "properties": {}}
            graph["edges"][(chunk_id, "is_part_of", doc_id)] = {
                "source": chunk_id, "target": doc_id, "relationship_name": "is_part_of", "properties": {}}
            for person, role, company in _WORKS.findall(text):
                p = self._entity(graph, person, "Person", f"{person} is {role} of {company}", chunk_id)
                c = self._entity(graph, company, "company", f"{company} is a company", chunk_id)
                graph["edges"][(p, "works_for", c)] = {
                    "source": p, "target": c, "relationship_name": "works_for",
                    "properties": {"edge_text": f"{person} works for {company} as {role}.",
                                   "edge_object_id": _id("edge", p, c), "updated_at": "2026-10-17 08:03:07"}}
            for left, right in _PARTNERS.findall(text):
                a = self._entity(graph, left, "Company", f"{left} has partners", chunk_id)
                b = self._entity(graph, right, "Company", f"{right} has partners", chunk_id)
                graph["edges"][(a, "partners_with", b)] = {
                    "source": a, "target": b, "relationship_name": "partners_with", "properties": {}}
        return self.graph(dataset)

    def graph(self, dataset):
        graph = self._graph(dataset)
        return {"nodes": list(graph["nodes"].values()), "edges": list(graph["edges"].values())}

    def search(self, dataset, query, limit=10, collections=("Entity_name", "DocumentChunk_text")):
        self.searches.append((dataset, query))
        if self.search_error:
            raise CogneeSidecarError("sidecar down")
        graph = self._graph(dataset)
        entity_hits = []
        if "boss" in query.lower():  # pretend Cognee's vectors know CEO ~ boss
            entity_hits = [{"id": _id("entity", "alice"), "score": 0.9, "text": "alice"}]
        chunk_hits = [
            {"id": n["id"], "score": 0.8, "text": n["properties"]["text"]}
            for n in graph["nodes"].values()
            if n["type"] == "DocumentChunk" and "money" in query.lower() and "Globex" in n["properties"]["text"]
        ]
        return {"Entity_name": entity_hits, "DocumentChunk_text": chunk_hits}

    def delete(self, dataset):
        self.deleted.append(dataset)
        self.datasets.pop(dataset, None)


@pytest.fixture
def sidecar():
    return FakeSidecar()


@pytest.fixture
def client(tmp_path, sidecar):
    instance = CogneeZep(str(tmp_path / "cognee.db"), sidecar=sidecar, ingest_batch_size=10)
    yield instance
    instance.close()


def _build(client, chunks, graph_id="cg"):
    builder = _builder(client)
    builder.create_graph("Cognee", graph_id=graph_id)
    builder.set_ontology(graph_id, ONTOLOGY)
    submission = builder.add_text_batches(graph_id, chunks, batch_size=2)
    assert client.wait_idle(10)
    return builder, submission, builder._wait_for_batch(submission, timeout=10)


CHUNKS = ["Alice is the CEO of Acme.", "Bob is the CTO of Acme.", "Acme partners with Globex."]


def test_cognee_graph_is_mirrored_as_zep_shapes(client, sidecar):
    builder, submission, episode_uuids = _build(client, CHUNKS)
    assert client.batch.get(batch_id=submission.batch_id).status == "succeeded"
    # Episodes were batched into few cognify runs, with the ontology prompt.
    assert 1 <= len(sidecar.ingests) <= 2
    dataset, _texts, prompt = sidecar.ingests[0]
    assert dataset == dataset_name("cg") == "mirofish_cg"
    assert "WORKS_FOR" in prompt and "Person" in prompt

    nodes = fetch_all_nodes(client, "cg", page_size=2)
    by_name = {n.name: n for n in nodes}
    assert sorted(by_name) == ["Acme", "Alice", "Bob", "Globex"]  # original casing recovered
    assert by_name["Alice"].labels == ["Entity", "Person"]
    assert by_name["Acme"].labels == ["Entity", "Company"]  # "company" type matched case-insensitively
    assert by_name["Alice"].summary == "Alice is CEO of Acme"
    assert by_name["Alice"].uuid_ == _id("entity", "alice")  # cognee ids are kept

    edges = fetch_all_edges(client, "cg", page_size=2)
    assert sorted(e.name for e in edges) == ["PARTNERS_WITH", "WORKS_FOR", "WORKS_FOR"]
    alice_edge = next(e for e in edges if e.source_node_uuid == by_name["Alice"].uuid_)
    assert alice_edge.fact == "Alice works for Acme as CEO."
    assert alice_edge.episodes == [episode_uuids[0]]
    partners = next(e for e in edges if e.name == "PARTNERS_WITH")
    assert partners.fact == "Acme partners with Globex"  # synthesized (cased) without edge_text
    assert client.graph.node.get(uuid_=by_name["Acme"].uuid_).name == "Acme"
    assert {e.name for e in client.graph.node.get_edges(node_uuid=by_name["Acme"].uuid_)} == {
        "WORKS_FOR", "PARTNERS_WITH"}
    data = builder.get_graph_data("cg")
    assert data["node_count"] == 4 and data["edge_count"] == 3

    # A later ingest keeps existing node identity/order and adds new ones.
    first_seq = client._store.one("SELECT seq FROM nodes WHERE name = 'Alice'")[0]
    client.graph.add(graph_id="cg", type="text", data="Carol is the CFO of Initech.")
    assert client.wait_idle(10)
    assert client._store.one("SELECT seq FROM nodes WHERE name = 'Alice'")[0] == first_seq
    assert {n.name for n in fetch_all_nodes(client, "cg")} >= {"Carol", "Initech"}


def test_search_fuses_cognee_vector_hits(client, sidecar):
    _build(client, CHUNKS)
    # BM25 alone cannot match "boss"; Cognee's entity hit pulls Alice's edge in.
    result = client.graph.search(graph_id="cg", query="who is the boss", scope="edges", limit=2)
    assert result.edges and result.edges[0].fact == "Alice works for Acme as CEO."
    nodes = client.graph.search(graph_id="cg", query="boss", scope="nodes",
                                search_filters={"node_labels": ["Company"]})
    assert all("Company" in n.labels for n in nodes.nodes)  # filters still apply to Cognee hits
    episodes = client.graph.search(graph_id="cg", query="money flows", scope="episodes", limit=1)
    assert episodes.episodes[0].content == "Acme partners with Globex."
    # Keyword hits still work and the existing contract (score > 0) holds.
    ceo = client.graph.search(graph_id="cg", query="CEO", scope="edges")
    assert ceo.edges[0].fact == "Alice works for Acme as CEO." and ceo.edges[0].score > 0


def test_search_survives_sidecar_outage(tmp_path):
    sidecar = FakeSidecar(search_error=True)
    client = CogneeZep(str(tmp_path / "c.db"), sidecar=sidecar)
    try:
        _build(client, CHUNKS)
        result = client.graph.search(graph_id="cg", query="CTO", scope="edges")
        assert result.edges[0].fact == "Bob works for Acme as CTO."
    finally:
        client.close()


def test_ingest_failure_marks_items_failed(tmp_path):
    sidecar = FakeSidecar(fail_on="Broken")
    client = CogneeZep(str(tmp_path / "c.db"), sidecar=sidecar, ingest_batch_size=1)
    try:
        builder = _builder(client)
        builder.create_graph("G", graph_id="gf")
        builder.set_ontology("gf", ONTOLOGY)
        submission = builder.add_text_batches("gf", ["Alice is the CEO of Acme.", "Broken text"], batch_size=2)
        assert client.wait_idle(10)
        assert client.batch.get(batch_id=submission.batch_id).status == "partial"
        failed = [e for e in client.graph.episode.get_by_graph_id(graph_id="gf").episodes]
        assert any(e.processed for e in failed)
        error = client._store.one("SELECT error FROM episodes WHERE content = 'Broken text'")[0]
        assert "simulated" in error
        episode_uuid = client._insert_episode(  # not queued: processed synchronously below
            graph_id="gf", content="Broken again", source="text", source_description=None,
            metadata=None, created_at=None, extract=True,
        )
        with pytest.raises(CogneeSidecarError):
            client.process_episode(episode_uuid)
    finally:
        client.close()


def test_delete_removes_cognee_dataset(client, sidecar):
    _build(client, ["Alice is the CEO of Acme."])
    node_uuid = fetch_all_nodes(client, "cg")[0].uuid_
    client.graph.delete(graph_id="cg")
    assert sidecar.deleted == ["mirofish_cg"]
    with pytest.raises(NotFoundError):
        client.graph.node.get(uuid_=node_uuid)
    with pytest.raises(NotFoundError):
        client.graph.search(graph_id="cg", query="x")


def test_activity_stays_local_and_resync(client, sidecar):
    client.graph.create(graph_id="sim", name="sim")
    client.graph.add(graph_id="sim", type="text", data="Alice: CREATE_POST 'Acme is great'",
                     metadata={"source": local_graph.SIMULATION_ACTIVITY_SOURCE})
    assert client.wait_idle(5)
    assert sidecar.ingests == []
    assert client.graph.search(graph_id="sim", query="Acme great").edges[0].name == local_graph.ACTIVITY_EDGE_NAME
    sidecar.ingest("mirofish_sim", ["Dan is the COO of Hooli."])  # e.g. added out of band
    client.graph.add(graph_id="sim", type="text", data="Dan is the COO of Hooli.",
                     metadata={"source": local_graph.SIMULATION_ACTIVITY_SOURCE})
    client.resync("sim")
    assert {n.name for n in fetch_all_nodes(client, "sim")} == {"Dan", "Hooli"}


# -- wiring --------------------------------------------------------------------


@pytest.fixture
def cognee_backend(monkeypatch, sidecar):
    monkeypatch.setattr(Config, "MEMORY_BACKEND", "cognee")
    monkeypatch.setattr(Config, "ZEP_API_KEY", None)
    monkeypatch.setattr(Config, "COGNEE_GRAPH_DB", Config.LOCAL_GRAPH_DB + ".cognee")
    monkeypatch.setattr(cognee_graph, "CogneeSidecarClient", lambda *a, **k: sidecar)
    return cognee_graph.get_cognee_zep_client()


def test_factory_and_services_with_cognee_backend(cognee_backend, monkeypatch):
    assert isinstance(cognee_backend, CogneeZep)
    assert zep.get_zep_client() is cognee_backend
    assert Config.is_local_memory() and Config.is_cognee_memory()
    assert Config.memory_backend_configured()
    monkeypatch.setattr(Config, "LLM_API_KEY", "x")
    assert Config.validate() == []

    _build(cognee_backend, ["Alice is the CEO of Acme.", "Acme partners with Globex."])
    reader = ZepEntityReader()
    filtered = reader.filter_defined_entities("cg")
    assert sorted(e.name for e in filtered.entities) == ["Acme", "Alice", "Globex"]
    alice = next(e for e in filtered.entities if e.name == "Alice")
    context = reader.get_entity_with_context("cg", alice.uuid)
    assert context.related_edges[0]["edge_name"] == "WORKS_FOR"
    tools = ZepToolsService(llm_client=object())
    assert "Alice works for Acme as CEO." in tools.search_graph("cg", "Alice CEO", limit=5).facts


def test_unknown_backend_is_rejected(monkeypatch):
    monkeypatch.setattr(Config, "MEMORY_BACKEND", "mem0")
    monkeypatch.setattr(Config, "LLM_API_KEY", "x")
    assert any("MEMORY_BACKEND" in error for error in Config.validate())


# -- sidecar configuration (no cognee import needed) -----------------------------


def _load_sidecar_module():
    path = Path(__file__).resolve().parents[1] / "memory_sidecar" / "cognee_server.py"
    spec = importlib.util.spec_from_file_location("cognee_server_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sidecar_maps_mirofish_settings_to_cognee(tmp_path, monkeypatch):
    module = _load_sidecar_module()
    monkeypatch.setattr(module, "REPO", tmp_path)  # ignore the developer's .env
    fake_env = {"LLM_PROVIDER": "claude", "ANTHROPIC_API_KEY": "sk-ant-test", "LLM_MODEL_NAME": "claude-haiku-4-5",
                "COGNEE_DATA_DIR": str(tmp_path / "cg"), "AWS_ACCESS_KEY_ID": "a", "AWS_SECRET_ACCESS_KEY": "b"}
    monkeypatch.setattr(os, "environ", dict(fake_env))
    settings = module.configure_environment()
    assert settings["LLM_PROVIDER"] == "anthropic" and settings["LLM_MODEL"] == "claude-haiku-4-5"
    assert settings["EMBEDDING_PROVIDER"] == "fastembed" and settings["EMBEDDING_DIMENSIONS"] == "384"
    assert os.environ["LLM_API_KEY"] == "sk-ant-test"
    assert "AWS_ACCESS_KEY_ID" not in os.environ
    assert Path(settings["COGNEE_ENV_FILE"]).is_file()
    assert "LLM_ENDPOINT" not in settings

    monkeypatch.setattr(os, "environ", {"LLM_PROVIDER": "openai", "LLM_API_KEY": "k", "LLM_MODEL_NAME": "qwen-plus",
                                        "LLM_BASE_URL": "https://example.test/v1", "COGNEE_DATA_DIR": str(tmp_path / "c2")})
    settings = module.configure_environment()
    assert settings["LLM_PROVIDER"] == "custom"
    assert settings["LLM_MODEL"] == "openai/qwen-plus" and settings["LLM_ENDPOINT"] == "https://example.test/v1"
