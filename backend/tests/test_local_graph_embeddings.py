"""Hybrid search, embedding fallback, caching and entity resolution of LocalZep.

All tests use a deterministic fake embedder; nothing is downloaded.
"""

from __future__ import annotations

import sqlite3
import sys
import threading
import time
import zlib

import numpy as np

from app.config import Config
from app.utils import embeddings as embeddings_module
from app.utils import local_graph
from app.utils.embeddings import FastEmbedEmbedder, cosine_rank, reciprocal_rank_fusion
from app.utils.local_graph import (
    NAME_MATCH_NONE,
    NAME_MATCH_STRONG,
    NAME_MATCH_WEAK,
    LocalZep,
    name_match_strength,
    tokenize,
)
from app.utils.zep_paging import fetch_all_edges, fetch_all_nodes

from test_local_graph import ONTOLOGY, FakeLLM, _build, _builder

_STOPWORDS = {"who", "is", "the", "a", "of", "as", "for", "with", "what", "does"}
_CONCEPTS = {"boss": "leader", "ceo": "leader", "chief": "leader", "leader": "leader",
             "cash": "money", "funding": "money", "investment": "money", "money": "money"}


class FakeEmbedder:
    """Bag-of-concepts embedder: synonyms share a dimension; ``same`` maps whole texts."""

    model_name = "fake-embedder"
    available = True

    def __init__(self, same: dict | None = None, dim: int = 128):
        self.same = {k.lower(): v.lower() for k, v in (same or {}).items()}
        self.dim = dim
        self.calls: list[list[str]] = []

    def _vector(self, text: str) -> np.ndarray:
        text = self.same.get(text.strip().lower(), text)
        vector = np.zeros(self.dim, dtype=np.float32)
        for token in tokenize(text):
            if token in _STOPWORDS:
                continue
            concept = _CONCEPTS.get(token, token)
            vector[zlib.crc32(concept.encode()) % self.dim] += 1.0
        norm = np.linalg.norm(vector)
        return vector / norm if norm else vector

    def embed(self, texts, *, query=False):
        self.calls.append(list(texts))
        return [self._vector(text) for text in texts]


class ScriptedLLM:
    """Returns a canned extraction per episode text (looked up by substring key)."""

    def __init__(self, script: dict, delay: float = 0.0):
        self.script = script
        self.delay = delay
        self.calls = []
        self._lock = threading.Lock()

    def chat_json(self, messages, temperature=0.3, max_tokens=4096, max_attempts=1):
        with self._lock:
            self.calls.append(messages)
        if self.delay:
            time.sleep(self.delay)
        text = messages[-1]["content"].split("<<<", 1)[1]
        for key, extraction in self.script.items():
            if key in text:
                return extraction
        return {"entities": [], "relationships": []}


def _person(name, summary="", aliases=None):
    entity = {"name": name, "type": "Person", "summary": summary or f"{name} is a person."}
    if aliases:
        entity["aliases"] = aliases
    return entity


def _company(name, summary=""):
    return {"name": name, "type": "Company", "summary": summary or f"{name} is a company."}


def _client(tmp_path, llm, embedder=None, **kwargs):
    kwargs.setdefault("max_workers", 1)
    return LocalZep(str(tmp_path / "g.db"), llm_client=llm, embedder=embedder, **kwargs)


def _add_all(client, graph_id, texts):
    for text in texts:
        client.graph.add(graph_id=graph_id, type="text", data=text)
        assert client.wait_idle(10)


# -- helpers ----------------------------------------------------------------


def test_rrf_and_cosine_rank_helpers():
    fused = reciprocal_rank_fusion([[2, 0, 1], [0, 3]])
    assert [index for index, _ in fused][:2] == [0, 2]
    query = np.array([1.0, 0.0], dtype=np.float32)
    vectors = [np.array([0.0, 1.0], dtype=np.float32), None, np.array([1.0, 0.0], dtype=np.float32)]
    assert cosine_rank(query, vectors, min_score=0.5) == [(2, 1.0)]


def test_name_match_strength_rules():
    assert name_match_strength("Acme Inc.", "acme") == NAME_MATCH_STRONG
    assert name_match_strength("The Guardian", "Guardian") == NAME_MATCH_STRONG
    assert name_match_strength("WHO", "World Health Organization") == NAME_MATCH_STRONG
    assert name_match_strength("who", "World Health Organization") == NAME_MATCH_NONE  # not an acronym
    assert name_match_strength("澜舟科技有限公司", "澜舟科技") == NAME_MATCH_STRONG
    assert name_match_strength("北京", "北京大学") == NAME_MATCH_NONE
    assert name_match_strength("Alice", "Alice Smith") == NAME_MATCH_WEAK
    assert name_match_strength("Smith", "Alice Smith") == NAME_MATCH_WEAK
    assert name_match_strength("Bob", "Bob Smith") == NAME_MATCH_NONE  # too short
    assert name_match_strength("Alice", "Alice Mary Jane Smith") == NAME_MATCH_NONE
    assert name_match_strength("Apple", "Pineapple") == NAME_MATCH_NONE


# -- hybrid search ------------------------------------------------------------


def test_hybrid_search_finds_semantic_matches_bm25_misses(tmp_path):
    chunks = ["Alice is the CEO of Acme.", "Bob is the CTO of Acme.", "Acme partners with Globex."]
    plain = LocalZep(str(tmp_path / "plain.db"), llm_client=FakeLLM(), max_workers=2)
    embedder = FakeEmbedder()
    hybrid = LocalZep(str(tmp_path / "hybrid.db"), llm_client=FakeLLM(), max_workers=2,
                      embedder=embedder, min_similarity=0.1)
    try:
        _build(plain, chunks)
        _build(hybrid, chunks)
        # BM25 alone has no overlap with "boss".
        assert plain.graph.search(graph_id="mirofish_test", query="Who is the boss?").edges == []
        result = hybrid.graph.search(graph_id="mirofish_test", query="Who is the boss?", limit=3)
        assert result.edges[0].fact == "Alice works for Acme as CEO."
        assert result.edges[0].score > 0

        # Keyword hits are still fused in, and filters/limits are honoured.
        both = hybrid.graph.search(graph_id="mirofish_test", query="Globex partners", limit=1)
        assert len(both.edges) == 1 and both.edges[0].name == "PARTNERS_WITH"
        only_works = hybrid.graph.search(
            graph_id="mirofish_test", query="boss", search_filters={"edge_types": ["PARTNERS_WITH"]},
        )
        assert all(edge.name == "PARTNERS_WITH" for edge in only_works.edges)
        nodes = hybrid.graph.search(graph_id="mirofish_test", query="leader", scope="nodes",
                                    search_filters={"node_labels": ["Person"]})
        assert nodes.nodes and nodes.nodes[0].name == "Alice"
        episodes = hybrid.graph.search(graph_id="mirofish_test", query="the boss", scope="episodes", limit=1)
        assert episodes.episodes[0].content == "Alice is the CEO of Acme."
    finally:
        plain.close()
        hybrid.close()


def test_embeddings_are_stored_and_reused_across_instances(tmp_path):
    path = str(tmp_path / "persist.db")
    first = LocalZep(path, llm_client=FakeLLM(), embedder=FakeEmbedder(), max_workers=1)
    _build(first, ["Alice is the CEO of Acme."])
    stored = first._store.one("SELECT COUNT(*), MIN(dim) FROM embeddings")
    assert stored[0] >= 4 and stored[1] == 128  # episode, facts, node texts, names
    first.close()

    embedder = FakeEmbedder()
    second = LocalZep(path, llm_client=FakeLLM(), embedder=embedder, max_workers=1, min_similarity=0.1)
    try:
        second.graph.search(graph_id="mirofish_test", query="boss", scope="edges")
        second.graph.search(graph_id="mirofish_test", query="boss", scope="edges")
        # Only the query was embedded (once): document vectors came from SQLite.
        assert embedder.calls == [["boss"]]
    finally:
        second.close()


def test_activity_lines_get_embedded_and_searchable(tmp_path):
    client = _client(tmp_path, FakeLLM(), FakeEmbedder(), min_similarity=0.1)
    try:
        client.graph.create(graph_id="sim", name="sim")
        client.graph.add(
            graph_id="sim", type="text",
            data="Alice: CREATE_POST 'we need more funding'\nBob: LIKE_POST about bananas",
            metadata={"source": local_graph.SIMULATION_ACTIVITY_SOURCE},
        )
        assert client.wait_idle(10)
        result = client.graph.search(graph_id="sim", query="cash", scope="edges")
        assert result.edges and "funding" in result.edges[0].fact
    finally:
        client.close()


def test_fallback_to_bm25_when_fastembed_missing(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "fastembed", None)  # import fastembed -> ImportError
    embedder = FastEmbedEmbedder("does/not-matter")
    assert embedder.embed(["hello"]) is None
    assert embedder.available is False

    client = _client(tmp_path, FakeLLM(), embedder, max_workers=2)
    try:
        assert client.embeddings_enabled is False
        _build(client, ["Alice is the CEO of Acme.", "Bob is the CTO of Acme."])
        result = client.graph.search(graph_id="mirofish_test", query="Who is the CEO?")
        assert result.edges[0].fact == "Alice works for Acme as CEO."
        assert client._store.one("SELECT COUNT(*) FROM embeddings")[0] == 0
    finally:
        client.close()


def test_default_embedder_follows_config(monkeypatch):
    monkeypatch.setattr(Config, "MEMORY_EMBEDDINGS", False)
    assert embeddings_module.get_default_embedder() is None
    monkeypatch.setattr(Config, "MEMORY_EMBEDDINGS", True)
    monkeypatch.setattr(Config, "MEMORY_EMBED_MODEL", "fake/model-for-test")
    embedder = embeddings_module.get_default_embedder()
    assert isinstance(embedder, FastEmbedEmbedder) and embedder.model_name == "fake/model-for-test"
    assert embedder._model is None  # lazy: nothing loaded until first embed


# -- entity resolution ---------------------------------------------------------


def test_entity_resolution_merges_variants_aliases_and_similar_names(tmp_path):
    script = {
        "[E1]": {"entities": [_person("Alice Smith"), _company("Acme Inc.")],
               "relationships": [{"type": "WORKS_FOR", "source": "Alice Smith", "target": "Acme Inc.",
                                  "fact": "Alice Smith works for Acme Inc."}]},
        "[E2]": {"entities": [_person("Alice", "Alice leads sales."), _company("Acme")],
               "relationships": [{"type": "WORKS_FOR", "source": "Alice", "target": "Acme",
                                  "fact": "Alice leads sales at Acme."}]},
        "[E3]": {"entities": [_company("IBM")]},
        "[E4]": {"entities": [_company("Big Blue", "Big Blue is IBM's nickname.")]},
        "[E5]": {"entities": [_person("John Smith"), _person("John Doe")]},
        "[E6]": {"entities": [_person("John")]},  # ambiguous -> separate node
        "[E7]": {"entities": [_person("Robert Paulson", aliases=["Bob"])]},
        "[E8]": {"entities": [_person("Bob")],
               "relationships": [{"type": "WORKS_FOR", "source": "Bob", "target": "WHO",
                                  "fact": "Bob works for WHO."}]},
        "[E9]": {"entities": [{"name": "World Health Organization", "type": "Company"}]},
        "[E10]": {"entities": [_person("Big Blue")]},  # same name embedding, other type
    }
    embedder = FakeEmbedder(same={"Big Blue": "IBM"})
    llm = ScriptedLLM(script)
    client = _client(tmp_path, llm, embedder)
    try:
        client.graph.create(graph_id="er", name="er")
        _builder(client).set_ontology("er", ONTOLOGY)
        _add_all(client, "er", [f"{key} text" for key in script])

        nodes = {(n.name, tuple(n.labels)) for n in fetch_all_nodes(client, "er")}
        assert nodes == {
            ("Alice Smith", ("Entity", "Person")),
            ("Acme Inc.", ("Entity", "Company")),
            ("IBM", ("Entity", "Company")),
            ("John Smith", ("Entity", "Person")),
            ("John Doe", ("Entity", "Person")),
            ("John", ("Entity", "Person")),
            ("Robert Paulson", ("Entity", "Person")),
            # untyped "WHO" endpoint first, then upgraded by the typed full name
            ("WHO", ("Entity", "Company")),
            ("Big Blue", ("Entity", "Person")),
        }
        by_name = {n.name: n for n in fetch_all_nodes(client, "er")}
        assert "Alice leads sales." in by_name["Alice Smith"].summary
        assert "nickname" in by_name["IBM"].summary
        edges = fetch_all_edges(client, "er")
        assert {(e.source_node_uuid, e.target_node_uuid) for e in edges if "Alice" in e.fact} == {
            (by_name["Alice Smith"].uuid_, by_name["Acme Inc."].uuid_)
        }
        bob_edge = next(e for e in edges if e.fact == "Bob works for WHO.")
        assert bob_edge.source_node_uuid == by_name["Robert Paulson"].uuid_
        aliases = client._store.one("SELECT aliases FROM nodes WHERE name = 'Alice Smith'")[0]
        assert "alice" in aliases
        # Aliases are keyword-searchable.
        found = client.graph.search(graph_id="er", query="Bob", scope="nodes", limit=1)
        assert found.nodes[0].name == "Robert Paulson"
    finally:
        client.close()


def test_entity_similarity_threshold_is_respected(tmp_path):
    script = {"[E3]": {"entities": [_company("IBM")]},
              "[E4]": {"entities": [_company("Big Blue")]}}
    client = _client(tmp_path, ScriptedLLM(script), FakeEmbedder(same={"Big Blue": "IBM"}),
                     entity_similarity=1.01)
    try:
        client.graph.create(graph_id="er", name="er")
        _add_all(client, "er", ["[E3] text", "[E4] text"])
        assert {n.name for n in fetch_all_nodes(client, "er")} == {"IBM", "Big Blue"}
    finally:
        client.close()


# -- speed / cost -----------------------------------------------------------------


def test_identical_chunks_reuse_one_extraction_even_concurrently(tmp_path):
    llm = ScriptedLLM({"Alice": {"entities": [_person("Alice")]}}, delay=0.2)
    client = _client(tmp_path, llm, max_workers=4)
    try:
        client.graph.create(graph_id="d", name="d")
        episodes = [client.graph.add(graph_id="d", type="text", data="Alice text") for _ in range(4)]
        assert client.wait_idle(10)
        assert len(llm.calls) == 1
        assert client.stats["extraction_cache_hits"] == 3
        assert all(client.graph.episode.get(uuid_=e.uuid_).processed for e in episodes)
        assert [n.name for n in fetch_all_nodes(client, "d")] == ["Alice"]
    finally:
        client.close()


def test_long_episodes_are_truncated_and_prompt_is_compact(tmp_path):
    llm = ScriptedLLM({})
    client = _client(tmp_path, llm, max_episode_chars=500)
    try:
        client.graph.create(graph_id="t", name="t")
        client.graph.add(graph_id="t", type="text", data="word " * 1000)
        assert client.wait_idle(10)
        prompt_text = llm.calls[0][-1]["content"].split("<<<", 1)[1]
        assert len(prompt_text) < 520
        assert len(local_graph._EXTRACTION_SYSTEM_PROMPT) < 900
    finally:
        client.close()


def test_old_database_without_aliases_column_is_migrated(tmp_path):
    path = str(tmp_path / "old.db")
    LocalZep(path, llm_client=FakeLLM()).close()
    conn = sqlite3.connect(path)
    conn.execute("ALTER TABLE nodes DROP COLUMN aliases")
    conn.commit()
    conn.close()
    client = LocalZep(path, llm_client=FakeLLM())
    try:
        client.graph.create(graph_id="m", name="m")
        client.graph.add(graph_id="m", type="text", data="Eve is the CEO of Umbrella.")
        assert client.wait_idle(10)
        assert {n.name for n in fetch_all_nodes(client, "m")} == {"Eve", "Umbrella"}
    finally:
        client.close()


def test_fastembed_embedder_handles_model_load_errors(monkeypatch):
    class Broken:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("download failed")

    fake_module = type(sys)("fastembed")
    fake_module.TextEmbedding = Broken
    monkeypatch.setitem(sys.modules, "fastembed", fake_module)
    embedder = FastEmbedEmbedder("x/y")
    assert embedder.embed(["a", "b"]) is None
    assert embedder.embed(["a"]) is None  # no retry storm: stays disabled
    assert not embedder.available
