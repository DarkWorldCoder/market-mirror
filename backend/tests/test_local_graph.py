"""Tests for the free local (SQLite + LLM extraction) memory graph backend."""

from __future__ import annotations

import re
import time

import pytest
from zep_cloud import NotFoundError

from app.config import Config
from app.services import graph_builder as graph_builder_module
from app.services.graph_builder import GraphBuilderService
from app.services.zep_entity_reader import ZepEntityReader
from app.services.zep_graph_memory_updater import ZepGraphMemoryUpdater
from app.services.zep_tools import ZepToolsService
from app.models.task import TaskManager, TaskStatus
from app.utils import local_graph, zep
from app.utils.local_graph import LocalZep, bm25_rank, tokenize
from app.utils.zep_paging import fetch_all_edges, fetch_all_nodes


ONTOLOGY = {
    "entity_types": [
        {
            "name": "Person",
            "description": "An individual human.",
            "attributes": [
                {"name": "role", "type": "text", "description": "Job title or role"},
                {"name": "name", "type": "text", "description": "Reserved name"},
            ],
        },
        {
            "name": "Company",
            "description": "A business organisation.",
            "attributes": [
                {"name": "industry", "type": "text", "description": "Industry sector"},
            ],
        },
    ],
    "edge_types": [
        {
            "name": "WORKS_FOR",
            "description": "Employment relationship.",
            "source_targets": [{"source": "Person", "target": "Company"}],
            "attributes": [],
        },
        {
            "name": "PARTNERS_WITH",
            "description": "Business partnership.",
            "source_targets": [{"source": "Company", "target": "Company"}],
            "attributes": [],
        },
    ],
}

_WORKS = re.compile(r"(\w+) is the (\w+) of (\w+)")
_PARTNERS = re.compile(r"(\w+) partners with (\w+)")


class FakeLLM:
    """Deterministic stand-in for LLMClient.chat_json."""

    def __init__(self, fail_on: str | None = None):
        self.calls = []
        self.fail_on = fail_on

    def chat_json(self, messages, temperature=0.3, max_tokens=4096, max_attempts=1):
        self.calls.append(messages)
        text = messages[-1]["content"].split("<<<", 1)[1]
        if self.fail_on and self.fail_on in text:
            raise ValueError("simulated LLM failure")
        entities, relationships = [], []
        for person, role, company in _WORKS.findall(text):
            entities.append({
                "name": person, "type": "Person",
                "summary": f"{person} is the {role} of {company}.",
                "attributes": {"role": role, "bogus": "dropped"},
            })
            entities.append({
                "name": company, "type": "company",  # case-insensitive type match
                "summary": f"{company} employs {person}.",
                "attributes": {"industry": "software"},
            })
            relationships.append({
                "type": "works_for", "source": person, "target": company,
                "fact": f"{person} works for {company} as {role}.",
            })
        for names in re.findall(r"Mentions ([A-Z]\w+), ([A-Z]\w+) and ([A-Z]\w+)\.", text):
            for n in names:
                entities.append({"name": n, "type": "Company", "summary": f"{n} is mentioned."})
        for left, right in _PARTNERS.findall(text):
            entities.append({"name": left, "type": "Company", "summary": f"{left} has partners."})
            relationships.append({
                "type": "PARTNERS_WITH", "source": left, "target": right,
                "fact": f"{left} partners with {right}.",
            })
        return {"entities": entities, "relationships": relationships}


@pytest.fixture
def fake_llm():
    return FakeLLM()


@pytest.fixture
def client(tmp_path, fake_llm):
    instance = LocalZep(str(tmp_path / "graph.db"), llm_client=fake_llm, max_workers=2)
    yield instance
    instance.close()


@pytest.fixture
def local_backend(monkeypatch, fake_llm):
    """Route get_zep_client() to a LocalZep using the fake LLM."""

    monkeypatch.setattr(Config, "MEMORY_BACKEND", "local")
    monkeypatch.setattr(Config, "ZEP_API_KEY", None)
    monkeypatch.setattr(Config, "MEMORY_EXTRACT_ACTIVITY", False)
    instance = local_graph.get_local_zep_client()
    instance._llm_client = fake_llm
    return instance


def _builder(client) -> GraphBuilderService:
    builder = GraphBuilderService.__new__(GraphBuilderService)
    builder.api_key = None
    builder.client = client
    builder.task_manager = TaskManager()
    return builder


def _build(client, chunks, graph_id="mirofish_test"):
    builder = _builder(client)
    builder.create_graph("Test", graph_id=graph_id)
    builder.set_ontology(graph_id, ONTOLOGY)
    submission = builder.add_text_batches(graph_id, chunks, batch_size=2)
    assert client.wait_idle(10)
    episode_uuids = builder._wait_for_batch(submission, timeout=10)
    return builder, submission, episode_uuids


# --------------------------------------------------------------------------


def test_tokenize_and_bm25_handle_english_and_cjk():
    assert "alice" in tokenize("Alice WORKS")
    assert "澜舟" in tokenize("澜舟科技")
    ranked = bm25_rank("acme ceo", ["Bob likes tea", "Alice is CEO of Acme", "Acme sells"])
    assert ranked[0][0] == 1
    assert {index for index, _ in ranked} == {1, 2}
    assert bm25_rank("", ["x"]) == []


def test_graph_lifecycle_and_not_found(client):
    graph = client.graph.create(graph_id="g1", name="G", description="desc")
    assert graph.graph_id == "g1" and graph.name == "G"
    assert client.graph.get("g1").description == "desc"
    with pytest.raises(Exception):
        client.graph.create(graph_id="g1", name="dup")
    assert [g.graph_id for g in client.graph.list_all().graphs] == ["g1"]

    client.graph.delete("g1")
    with pytest.raises(NotFoundError):
        client.graph.get("g1")
    with pytest.raises(NotFoundError):
        client.graph.delete("g1")
    with pytest.raises(NotFoundError):
        client.graph.node.get(uuid_="missing")
    with pytest.raises(NotFoundError):
        client.graph.episode.get(uuid_="missing")
    with pytest.raises(NotFoundError):
        client.batch.get(batch_id="missing")
    with pytest.raises(NotFoundError):
        fetch_all_nodes(client, "g1")
    # NotFound must not be treated as retryable by the shared retry policy.
    assert not zep.is_retryable_zep_error(NotFoundError(body=None))


def test_set_ontology_with_real_dynamic_classes(client):
    builder = _builder(client)
    builder.create_graph("G", graph_id="g-ont")
    builder.set_ontology("g-ont", ONTOLOGY)

    ontology = client._ontology("g-ont")
    person = ontology["entity_types"]["Person"]
    assert person["description"] == "An individual human."
    assert person["attributes"]["role"] == "Job title or role"
    # GraphBuilder renames reserved attribute names before calling set_ontology.
    assert "entity_name" in person["attributes"]
    works_for = ontology["edge_types"]["WORKS_FOR"]
    assert works_for["description"] == "Employment relationship."
    assert works_for["source_targets"] == [{"source": "Person", "target": "Company"}]
    types = client.graph.list_entity_types(graph_id="g-ont")
    assert {t.name for t in types.entity_types} == {"Person", "Company"}


def test_batch_flow_as_graph_builder_uses_it(client, fake_llm):
    chunks = [
        "Alice is the CEO of Acme.",
        "Bob is the CTO of Acme.",
        "Acme partners with Globex.",
    ]
    builder, submission, episode_uuids = _build(client, chunks)

    assert submission.item_count == 3
    assert len(submission.episode_uuids) == 3
    assert episode_uuids == submission.episode_uuids
    summary = client.batch.get(batch_id=submission.batch_id)
    assert summary.status == "succeeded"
    assert summary.progress.succeeded_items == 3
    assert summary.progress.percent_complete == 100.0
    assert summary.metadata["graph_id"] == "mirofish_test"
    assert len(fake_llm.calls) == 3
    # Ontology is passed to the extraction prompt.
    assert "WORKS_FOR" in fake_llm.calls[0][-1]["content"]

    # Reconciliation helper used after ambiguous create replies.
    found = builder._find_batch_by_operation_id("mirofish_test", submission.operation_id)
    assert found.batch_id == submission.batch_id

    items = client.batch.list_items(batch_id=submission.batch_id, limit=2)
    assert len(items.items) == 2 and items.next_cursor == 2
    rest = client.batch.list_items(batch_id=submission.batch_id, limit=2, cursor=2)
    assert len(rest.items) == 1 and rest.next_cursor is None
    assert all(item.source_uuid == item.episode_uuid for item in items.items)

    for episode_uuid in episode_uuids:
        episode = client.graph.episode.get(uuid_=episode_uuid)
        assert episode.processed is True
        assert episode.metadata["mirofish_operation_id"] == submission.operation_id
    builder._wait_for_episodes(episode_uuids, timeout=5)

    # Re-processing a non-draft batch is a no-op returning the summary.
    assert client.batch.process(batch_id=submission.batch_id).status == "succeeded"


def test_entities_are_merged_and_edges_listed_via_paging(client):
    builder, _submission, episode_uuids = _build(client, [
        "Alice is the CEO of Acme.",
        "Bob is the CTO of Acme.",
        "Acme partners with Globex.",
        "Alice is the CEO of Acme.",  # duplicate fact -> episode link only
    ])

    nodes = fetch_all_nodes(client, "mirofish_test", page_size=2)
    names = sorted(node.name for node in nodes)
    assert names == ["Acme", "Alice", "Bob", "Globex"]
    by_name = {node.name: node for node in nodes}
    assert by_name["Alice"].labels == ["Entity", "Person"]
    assert by_name["Acme"].labels == ["Entity", "Company"]
    assert by_name["Globex"].labels == ["Entity"]  # only referenced, never typed
    assert by_name["Alice"].attributes == {"role": "CEO"}  # unknown attrs dropped
    assert "employs Alice" in by_name["Acme"].summary and "employs Bob" in by_name["Acme"].summary

    edges = fetch_all_edges(client, "mirofish_test", page_size=2)
    assert len(edges) == 3
    works = [edge for edge in edges if edge.name == "WORKS_FOR"]
    assert len(works) == 2
    alice_edge = next(edge for edge in works if edge.source_node_uuid == by_name["Alice"].uuid_)
    assert alice_edge.target_node_uuid == by_name["Acme"].uuid_
    assert alice_edge.episodes == [episode_uuids[0], episode_uuids[3]]
    assert alice_edge.valid_at and alice_edge.created_at

    # Raw pagination headers follow the zep-next-cursor contract.
    page = client.graph.node.with_raw_response.get_by_graph_id("mirofish_test", limit=3)
    assert len(page.data) == 3 and page.headers["zep-next-cursor"] == "3"
    last = client.graph.node.with_raw_response.get_by_graph_id("mirofish_test", limit=3, cursor="3")
    assert len(last.data) == 1 and "zep-next-cursor" not in last.headers

    acme_edges = client.graph.node.get_edges(node_uuid=by_name["Acme"].uuid_)
    assert {edge.name for edge in acme_edges} == {"WORKS_FOR", "PARTNERS_WITH"}
    assert len(acme_edges) == 3

    graph_data = builder.get_graph_data("mirofish_test")
    assert graph_data["node_count"] == 4 and graph_data["edge_count"] == 3
    info = builder._get_graph_info("mirofish_test")
    assert sorted(info.entity_types) == ["Company", "Person"]


def test_search_scopes_and_filters(client):
    _build(client, ["Alice is the CEO of Acme.", "Bob is the CTO of Acme.", "Acme partners with Globex."])

    result = client.graph.search(
        graph_id="mirofish_test", query="Who is the CEO?", scope="edges",
        limit=5, reranker="cross_encoder", unknown_kwarg=True,
    )
    assert result.edges and result.edges[0].fact == "Alice works for Acme as CEO."
    assert result.edges[0].score > 0

    nodes = client.graph.search(graph_id="mirofish_test", query="Globex partners", scope="nodes", limit=2)
    assert nodes.nodes[0].name in {"Globex", "Acme"}
    filtered = client.graph.search(
        graph_id="mirofish_test", query="Alice Globex", scope="nodes",
        search_filters={"node_labels": ["Person"]},
    )
    assert [node.name for node in filtered.nodes] == ["Alice"]

    episodes = client.graph.search(graph_id="mirofish_test", query="CTO", scope="episodes")
    assert episodes.episodes[0].content == "Bob is the CTO of Acme."

    assert client.graph.search(graph_id="mirofish_test", query="zebra", scope="edges").edges == []
    with pytest.raises(NotFoundError):
        client.graph.search(graph_id="nope", query="x")


def test_failed_extraction_marks_batch_partial(tmp_path):
    llm = FakeLLM(fail_on="Broken")
    client = LocalZep(str(tmp_path / "g.db"), llm_client=llm, max_workers=1)
    try:
        builder = _builder(client)
        builder.create_graph("G", graph_id="g-fail")
        builder.set_ontology("g-fail", ONTOLOGY)
        submission = builder.add_text_batches("g-fail", ["Alice is the CEO of Acme.", "Broken text"], batch_size=2)
        assert client.wait_idle(10)
        assert client.batch.get(batch_id=submission.batch_id).status == "partial"
        with pytest.raises(RuntimeError, match="partial"):
            builder._wait_for_batch(submission, timeout=5)
    finally:
        client.close()


def test_graph_add_activity_skips_llm_but_is_searchable(client, fake_llm):
    client.graph.create(graph_id="sim", name="sim")
    episode = client.graph.add(
        graph_id="sim", type="text",
        data="Alice: CREATE_POST 'Acme stock is soaring'\nBob: LIKE_POST about bananas",
        metadata={"source": local_graph.SIMULATION_ACTIVITY_SOURCE},
    )
    assert episode.processed is True
    assert fake_llm.calls == []
    result = client.graph.search(graph_id="sim", query="Acme stock", scope="edges")
    assert result.edges[0].name == local_graph.ACTIVITY_EDGE_NAME
    assert "soaring" in result.edges[0].fact
    assert fetch_all_edges(client, "sim") == []  # pseudo-facts are not graph edges

    # Non-activity episodes are extracted asynchronously.
    doc = client.graph.add(graph_id="sim", type="text", data="Carol is the CFO of Initech.")
    assert client.wait_idle(10)
    assert client.graph.episode.get(uuid_=doc.uuid_).processed is True
    assert {n.name for n in fetch_all_nodes(client, "sim")} == {"Carol", "Initech"}
    recent = client.graph.episode.get_by_graph_id(graph_id="sim", lastn=1)
    assert [e.uuid_ for e in recent.episodes] == [doc.uuid_]


def test_activity_extraction_can_be_enabled(tmp_path, fake_llm):
    client = LocalZep(str(tmp_path / "g.db"), llm_client=fake_llm, extract_activity=True)
    try:
        client.graph.create(graph_id="sim", name="sim")
        episode = client.graph.add(
            graph_id="sim", type="text", data="Dan is the COO of Hooli.",
            metadata={"source": local_graph.SIMULATION_ACTIVITY_SOURCE},
        )
        assert client.wait_idle(10)
        assert client.graph.episode.get(uuid_=episode.uuid_).processed
        assert len(fake_llm.calls) == 1
    finally:
        client.close()


def test_data_persists_across_client_instances(tmp_path, fake_llm):
    path = str(tmp_path / "persist.db")
    first = LocalZep(path, llm_client=fake_llm)
    first.graph.create(graph_id="p", name="P")
    first.graph.add(graph_id="p", type="text", data="Eve is the CEO of Umbrella.")
    assert first.wait_idle(10)
    first.close()

    second = LocalZep(path, llm_client=fake_llm)
    try:
        assert {n.name for n in fetch_all_nodes(second, "p")} == {"Eve", "Umbrella"}
    finally:
        second.close()


def test_delete_removes_graph_contents(client):
    _build(client, ["Alice is the CEO of Acme."])
    node_uuid = fetch_all_nodes(client, "mirofish_test")[0].uuid_
    client.graph.delete(graph_id="mirofish_test")
    with pytest.raises(NotFoundError):
        client.graph.node.get(uuid_=node_uuid)
    assert client._store.one("SELECT COUNT(*) FROM edges")[0] == 0


# -- wiring -----------------------------------------------------------------


def test_config_and_factory_select_local_backend(local_backend, monkeypatch):
    assert Config.is_local_memory()
    assert Config.memory_backend_configured()
    monkeypatch.setattr(Config, "LLM_API_KEY", "x")
    assert not any("ZEP_API_KEY" in error for error in Config.validate())
    assert zep.get_zep_client() is local_backend
    assert zep.get_zep_client("ignored-key") is local_backend
    assert isinstance(local_backend, LocalZep)

    monkeypatch.setattr(Config, "MEMORY_BACKEND", "zep")
    assert not Config.memory_backend_configured()
    assert any("ZEP_API_KEY" in error for error in Config.validate())
    with pytest.raises(ValueError, match="ZEP_API_KEY"):
        GraphBuilderService()


def test_services_work_without_zep_key(local_backend):
    builder = GraphBuilderService()
    assert builder.client is local_backend
    _build(local_backend, ["Alice is the CEO of Acme.", "Acme partners with Globex."])

    reader = ZepEntityReader()
    filtered = reader.filter_defined_entities("mirofish_test")
    assert sorted(e.name for e in filtered.entities) == ["Acme", "Alice"]
    alice = next(e for e in filtered.entities if e.name == "Alice")
    context = reader.get_entity_with_context("mirofish_test", alice.uuid)
    assert context.related_edges and context.related_edges[0]["edge_name"] == "WORKS_FOR"
    assert reader.get_node_edges(alice.uuid)[0]["name"] == "WORKS_FOR"

    tools = ZepToolsService(llm_client=object())
    search = tools.search_graph("mirofish_test", "Alice CEO", limit=5)
    assert "Alice works for Acme as CEO." in search.facts
    assert tools.get_node_detail(alice.uuid).name == "Alice"
    assert tools.get_node_detail("missing") is None

    updater = ZepGraphMemoryUpdater("mirofish_test", simulation_id="sim-1")
    assert updater.client is local_backend


def test_graph_builder_end_to_end_build(local_backend):
    builder = GraphBuilderService()
    text = "Alice is the CEO of Acme. " * 2 + "Acme partners with Globex."
    task_id = builder.build_graph_async(text, ONTOLOGY, graph_name="E2E", chunk_size=40, chunk_overlap=0)
    deadline = time.time() + 20
    task = None
    while time.time() < deadline:
        task = builder.task_manager.get_task(task_id)
        if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
            break
        time.sleep(0.05)
    assert task.status == TaskStatus.COMPLETED, task.error
    info = task.result["graph_info"]
    assert info["node_count"] == 3
    assert info["edge_count"] == 2
    assert sorted(info["entity_types"]) == ["Company", "Person"]



def test_comention_links_islands(client):
    _build(client, ["Acme partners with Globex.", "Mentions Initech, Umbrella and Acme."], graph_id="mirofish_co")
    nodes = {n.name: n for n in fetch_all_nodes(client, "mirofish_co")}
    edges = fetch_all_edges(client, "mirofish_co")
    linked = {e.source_node_uuid for e in edges} | {e.target_node_uuid for e in edges}
    assert all(n.uuid_ in linked for n in nodes.values())            # no islands
    co = [e for e in edges if e.name == "MENTIONED_WITH"]
    assert {e.source_node_uuid for e in co} == {nodes["Initech"].uuid_, nodes["Umbrella"].uuid_}
    assert all(e.target_node_uuid == nodes["Acme"].uuid_ for e in co)   # the passage's best-connected entity
