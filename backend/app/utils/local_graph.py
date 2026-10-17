"""Free, local, SQLite-backed replacement for the Zep Cloud graph SDK subset.

``LocalZep`` mimics the parts of ``zep_cloud.client.Zep`` that MiroFish uses
(``client.graph`` / ``client.graph.node`` / ``client.graph.edge`` /
``client.graph.episode`` / ``client.batch``) and returns the real ``zep_cloud``
pydantic types (``EntityNode``, ``EntityEdge``, ``Episode``, ``BatchSummary``
...), so every existing caller and ``except NotFoundError`` clause keeps
working unchanged.

Knowledge extraction (entities + relationships from episode text) is done by
the project's own LLM (``LLMClient.chat_json``) in a small background worker
pool, so ``episode.processed`` and batch statuses transition asynchronously
just like Zep Cloud. Search is a pure-Python BM25 ranking over facts, node
names/summaries and episode text.

Not implemented compared to Zep Cloud: embeddings / semantic search, temporal
contradiction resolution (old facts are never auto-invalidated), cross-encoder
reranking (``reranker`` is accepted and ignored), user/thread memory.
"""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import threading
import uuid
from collections import Counter
import queue
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional, Sequence

from zep_cloud import (
    BadRequestError,
    BatchItemDetail,
    BatchItemListResponse,
    BatchListResponse,
    BatchProgress,
    BatchSummary,
    EntityEdge,
    EntityNode,
    Episode,
    GraphSearchResults,
    NotFoundError,
)
from zep_cloud.types import EpisodeResponse, Graph, GraphListResponse, SuccessResponse
from zep_cloud.types.api_error import ApiError as ApiErrorBody

from .logger import get_logger

logger = get_logger("mirofish.local_graph")

# Episodes written by the simulation memory updater carry this metadata source.
SIMULATION_ACTIVITY_SOURCE = "mirofish_simulation"
ACTIVITY_EDGE_NAME = "SIMULATION_ACTIVITY"
_MAX_SUMMARY_CHARS = 1200
_EXTRACTION_ATTEMPTS = 3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _not_found(message: str) -> NotFoundError:
    return NotFoundError(body=ApiErrorBody(message=message))


def _bad_request(message: str) -> BadRequestError:
    return BadRequestError(body=ApiErrorBody(message=message))


def _normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", str(name or "")).strip().lower()


def _normalize_edge_name(name: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_一-鿿]+", "_", str(name or "").strip())
    cleaned = cleaned.strip("_").upper()
    return cleaned or "RELATED_TO"


def _json_load(value: Optional[str], default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------
# BM25
# --------------------------------------------------------------------------

_WORD_RE = re.compile(r"[0-9a-z]+(?:['_-][0-9a-z]+)*")
_CJK_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯]+")


def tokenize(text: str) -> List[str]:
    """Lowercased word tokens plus CJK unigrams and bigrams."""

    text = str(text or "").lower()
    tokens = _WORD_RE.findall(text)
    for run in _CJK_RE.findall(text):
        tokens.extend(run)
        tokens.extend(run[i:i + 2] for i in range(len(run) - 1))
    return tokens


def bm25_rank(
    query: str,
    documents: Sequence[str],
    *,
    k1: float = 1.5,
    b: float = 0.75,
) -> List[tuple[int, float]]:
    """Return ``(index, score)`` for documents with a positive BM25 score."""

    query_terms = list(dict.fromkeys(tokenize(query)))
    if not query_terms or not documents:
        return []
    doc_tokens = [tokenize(doc) for doc in documents]
    n_docs = len(doc_tokens)
    avg_len = (sum(len(tokens) for tokens in doc_tokens) / n_docs) or 1.0
    doc_freq: Counter[str] = Counter()
    for tokens in doc_tokens:
        doc_freq.update(set(tokens))

    scored: List[tuple[int, float]] = []
    for index, tokens in enumerate(doc_tokens):
        if not tokens:
            continue
        freqs = Counter(tokens)
        score = 0.0
        for term in query_terms:
            tf = freqs.get(term)
            if not tf:
                continue
            df = doc_freq[term]
            idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
            score += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * len(tokens) / avg_len))
        if score > 0:
            scored.append((index, score))
    scored.sort(key=lambda pair: (-pair[1], pair[0]))
    return scored


# --------------------------------------------------------------------------
# Ontology helpers
# --------------------------------------------------------------------------


def _model_fields(model_cls: Any) -> Dict[str, str]:
    fields = getattr(model_cls, "model_fields", None) or {}
    return {
        name: (getattr(info, "description", None) or "")
        for name, info in fields.items()
    }


def _describe_model(model_cls: Any, fallback: str) -> str:
    doc = getattr(model_cls, "__doc__", None) or ""
    return doc.strip() or fallback


def serialize_ontology(
    entities: Optional[Dict[str, Any]],
    edges: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Convert dynamic EntityModel/EdgeModel classes into a JSON ontology."""

    entity_types: Dict[str, Any] = {}
    for name, model_cls in (entities or {}).items():
        entity_types[str(name)] = {
            "description": _describe_model(model_cls, f"A {name} entity."),
            "attributes": _model_fields(model_cls),
        }

    edge_types: Dict[str, Any] = {}
    for name, definition in (edges or {}).items():
        if isinstance(definition, (tuple, list)) and definition:
            model_cls = definition[0]
            source_targets = definition[1] if len(definition) > 1 else []
        else:
            model_cls, source_targets = definition, []
        edge_types[str(name)] = {
            "description": _describe_model(model_cls, f"A {name} relationship."),
            "attributes": _model_fields(model_cls),
            "source_targets": [
                {
                    "source": getattr(st, "source", None) or "Entity",
                    "target": getattr(st, "target", None) or "Entity",
                }
                for st in (source_targets or [])
            ],
        }
    return {"entity_types": entity_types, "edge_types": edge_types}


# --------------------------------------------------------------------------
# Extraction prompt
# --------------------------------------------------------------------------

_EXTRACTION_SYSTEM_PROMPT = """You are a knowledge-graph extraction engine.
Read the episode text and extract the entities and relationships it states.
Return ONLY a JSON object of the form:
{
  "entities": [
    {"name": "...", "type": "<one of the entity types or Entity>",
     "summary": "<one or two sentences about this entity based on the text>",
     "attributes": {"<attribute name>": "<value>"}}
  ],
  "relationships": [
    {"type": "<one of the relationship types, UPPER_SNAKE_CASE>",
     "source": "<entity name>", "target": "<entity name>",
     "fact": "<a self-contained sentence stating the relationship>",
     "valid_at": "<ISO-8601 date if the text says when it became true, else null>",
     "invalid_at": "<ISO-8601 date if the text says when it stopped being true, else null>"}
  ]
}
Rules:
- Use the canonical, fully-qualified name of each entity; reuse exactly the same name for the same entity.
- Prefer the provided entity and relationship types. Use "Entity" only when no type fits.
- Only include attributes defined for that entity type; omit unknown values.
- Every relationship source and target must also appear in "entities".
- Write summaries and facts in the same language as the episode text.
- Do not invent information that is not in the text."""


def _ontology_prompt(ontology: Dict[str, Any]) -> str:
    entity_types = ontology.get("entity_types") or {}
    edge_types = ontology.get("edge_types") or {}
    lines: List[str] = []
    if entity_types:
        lines.append("Entity types:")
        for name, spec in entity_types.items():
            attrs = ", ".join(
                f"{attr} ({desc})" if desc else attr
                for attr, desc in (spec.get("attributes") or {}).items()
            )
            line = f"- {name}: {spec.get('description', '')}"
            if attrs:
                line += f" Attributes: {attrs}"
            lines.append(line)
    if edge_types:
        lines.append("Relationship types:")
        for name, spec in edge_types.items():
            pairs = ", ".join(
                f"{st.get('source')}->{st.get('target')}"
                for st in spec.get("source_targets") or []
            )
            line = f"- {name}: {spec.get('description', '')}"
            if pairs:
                line += f" ({pairs})"
            lines.append(line)
    if not lines:
        lines.append("No ontology was defined: choose concise generic types.")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS graphs (
    graph_id TEXT PRIMARY KEY,
    uuid TEXT NOT NULL,
    name TEXT,
    description TEXT,
    ontology TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS episodes (
    uuid TEXT PRIMARY KEY,
    graph_id TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT,
    source_description TEXT,
    metadata TEXT,
    created_at TEXT NOT NULL,
    processed INTEGER NOT NULL DEFAULT 0,
    extract INTEGER NOT NULL DEFAULT 1,
    error TEXT,
    seq INTEGER
);
CREATE INDEX IF NOT EXISTS idx_episodes_graph ON episodes(graph_id, seq);
CREATE TABLE IF NOT EXISTS nodes (
    uuid TEXT PRIMARY KEY,
    graph_id TEXT NOT NULL,
    name TEXT NOT NULL,
    norm_name TEXT NOT NULL,
    label TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    attributes TEXT,
    created_at TEXT NOT NULL,
    seq INTEGER
);
CREATE INDEX IF NOT EXISTS idx_nodes_graph ON nodes(graph_id, seq);
CREATE UNIQUE INDEX IF NOT EXISTS idx_nodes_identity ON nodes(graph_id, norm_name, label);
CREATE TABLE IF NOT EXISTS edges (
    uuid TEXT PRIMARY KEY,
    graph_id TEXT NOT NULL,
    name TEXT NOT NULL,
    fact TEXT NOT NULL,
    source_node_uuid TEXT NOT NULL,
    target_node_uuid TEXT NOT NULL,
    attributes TEXT,
    episodes TEXT,
    created_at TEXT NOT NULL,
    valid_at TEXT,
    invalid_at TEXT,
    expired_at TEXT,
    seq INTEGER
);
CREATE INDEX IF NOT EXISTS idx_edges_graph ON edges(graph_id, seq);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_node_uuid);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_node_uuid);
CREATE TABLE IF NOT EXISTS batches (
    batch_id TEXT PRIMARY KEY,
    metadata TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    processed_at TEXT,
    completed_at TEXT,
    seq INTEGER
);
CREATE TABLE IF NOT EXISTS batch_items (
    item_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    sequence_index INTEGER NOT NULL,
    graph_id TEXT,
    episode_uuid TEXT,
    status TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_batch_items ON batch_items(batch_id, sequence_index);
"""


class _Store:
    """Thread-safe SQLite wrapper (one connection guarded by an RLock)."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        if db_path != ":memory:":
            directory = os.path.dirname(os.path.abspath(db_path))
            os.makedirs(directory, exist_ok=True)
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        with self.lock:
            if db_path != ":memory:":
                self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.executescript(_SCHEMA)
            row = self.conn.execute(
                "SELECT MAX(m) FROM (SELECT MAX(seq) m FROM nodes UNION ALL "
                "SELECT MAX(seq) FROM edges UNION ALL SELECT MAX(seq) FROM episodes "
                "UNION ALL SELECT MAX(seq) FROM batches)"
            ).fetchone()
            self._seq = int(row[0] or 0)

    def next_seq(self) -> int:
        with self.lock:
            self._seq += 1
            return self._seq

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self.lock:
            return self.conn.execute(sql, tuple(params))

    def query(self, sql: str, params: Iterable[Any] = ()) -> List[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, tuple(params)).fetchall()

    def one(self, sql: str, params: Iterable[Any] = ()) -> Optional[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, tuple(params)).fetchone()

    def transaction(self):
        return _Transaction(self)

    def close(self) -> None:
        with self.lock:
            self.conn.close()


class _Transaction:
    def __init__(self, store: _Store):
        self.store = store

    def __enter__(self):
        self.store.lock.acquire()
        self.store.conn.execute("BEGIN IMMEDIATE")
        return self.store

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self.store.conn.execute("COMMIT")
            else:
                self.store.conn.execute("ROLLBACK")
        finally:
            self.store.lock.release()
        return False


# --------------------------------------------------------------------------
# Row -> SDK object conversion
# --------------------------------------------------------------------------


def _node_from_row(row: sqlite3.Row, score: Optional[float] = None) -> EntityNode:
    label = row["label"]
    labels = ["Entity"] if label == "Entity" else ["Entity", label]
    return EntityNode(
        uuid_=row["uuid"],
        name=row["name"],
        labels=labels,
        summary=row["summary"] or "",
        attributes=_json_load(row["attributes"], {}),
        created_at=row["created_at"],
        score=score,
        relevance=score,
    )


def _edge_from_row(row: sqlite3.Row, score: Optional[float] = None) -> EntityEdge:
    return EntityEdge(
        uuid_=row["uuid"],
        name=row["name"],
        fact=row["fact"],
        source_node_uuid=row["source_node_uuid"],
        target_node_uuid=row["target_node_uuid"],
        attributes=_json_load(row["attributes"], {}),
        episodes=_json_load(row["episodes"], []),
        created_at=row["created_at"],
        valid_at=row["valid_at"],
        invalid_at=row["invalid_at"],
        expired_at=row["expired_at"],
        score=score,
        relevance=score,
    )


def _episode_from_row(row: sqlite3.Row, score: Optional[float] = None) -> Episode:
    return Episode(
        uuid_=row["uuid"],
        content=row["content"],
        source=row["source"],
        source_description=row["source_description"],
        metadata=_json_load(row["metadata"], None),
        created_at=row["created_at"],
        processed=bool(row["processed"]),
        score=score,
        relevance=score,
    )


class _RawResponse:
    """Mimics the SDK's ``HttpResponse`` (``.data`` + ``.headers``)."""

    def __init__(self, data: Any, headers: Optional[Dict[str, str]] = None):
        self.data = data
        self.headers = headers or {}


# --------------------------------------------------------------------------
# Sub-clients
# --------------------------------------------------------------------------


def _page_bounds(cursor: Any, limit: Any) -> tuple[int, Optional[int]]:
    offset = 0
    if cursor not in (None, "", ...):
        try:
            offset = max(int(cursor), 0)
        except (TypeError, ValueError):
            offset = 0
    page_limit = None
    if limit not in (None, ...):
        page_limit = max(int(limit), 1)
    return offset, page_limit


class _NodeRawClient:
    def __init__(self, owner: "LocalZep"):
        self._owner = owner

    def get_by_graph_id(self, graph_id: str, *, limit: Any = None, cursor: Any = None,
                        uuid_cursor: Any = None, **_ignored: Any) -> _RawResponse:
        return self._owner._page("nodes", graph_id, limit, cursor, _node_from_row)


class _EdgeRawClient:
    def __init__(self, owner: "LocalZep"):
        self._owner = owner

    def get_by_graph_id(self, graph_id: str, *, limit: Any = None, cursor: Any = None,
                        uuid_cursor: Any = None, **_ignored: Any) -> _RawResponse:
        return self._owner._page("edges", graph_id, limit, cursor, _edge_from_row)


class LocalNodeClient:
    def __init__(self, owner: "LocalZep"):
        self._owner = owner
        self.with_raw_response = _NodeRawClient(owner)

    def get(self, uuid_: str, **_ignored: Any) -> EntityNode:
        row = self._owner._store.one("SELECT * FROM nodes WHERE uuid = ?", (uuid_,))
        if row is None:
            raise _not_found(f"node not found: {uuid_}")
        return _node_from_row(row)

    def get_by_graph_id(self, graph_id: str, **kwargs: Any) -> List[EntityNode]:
        return self.with_raw_response.get_by_graph_id(graph_id, **kwargs).data

    def get_edges(self, node_uuid: str, **_ignored: Any) -> List[EntityEdge]:
        self.get(node_uuid)
        rows = self._owner._store.query(
            "SELECT * FROM edges WHERE source_node_uuid = ? OR target_node_uuid = ? ORDER BY seq",
            (node_uuid, node_uuid),
        )
        return [_edge_from_row(row) for row in rows]

    def get_episodes(self, node_uuid: str, **_ignored: Any) -> EpisodeResponse:
        episode_ids: List[str] = []
        for edge in self.get_edges(node_uuid):
            for episode_id in edge.episodes or []:
                if episode_id not in episode_ids:
                    episode_ids.append(episode_id)
        episodes = []
        for episode_id in episode_ids:
            row = self._owner._store.one("SELECT * FROM episodes WHERE uuid = ?", (episode_id,))
            if row is not None:
                episodes.append(_episode_from_row(row))
        return EpisodeResponse(episodes=episodes)

    def delete(self, uuid_: str, **_ignored: Any) -> SuccessResponse:
        self.get(uuid_)
        with self._owner._store.transaction() as store:
            store.conn.execute(
                "DELETE FROM edges WHERE source_node_uuid = ? OR target_node_uuid = ?",
                (uuid_, uuid_),
            )
            store.conn.execute("DELETE FROM nodes WHERE uuid = ?", (uuid_,))
        return SuccessResponse(message="node deleted")


class LocalEdgeClient:
    def __init__(self, owner: "LocalZep"):
        self._owner = owner
        self.with_raw_response = _EdgeRawClient(owner)

    def get(self, uuid_: str, **_ignored: Any) -> EntityEdge:
        row = self._owner._store.one("SELECT * FROM edges WHERE uuid = ?", (uuid_,))
        if row is None:
            raise _not_found(f"edge not found: {uuid_}")
        return _edge_from_row(row)

    def get_by_graph_id(self, graph_id: str, **kwargs: Any) -> List[EntityEdge]:
        return self.with_raw_response.get_by_graph_id(graph_id, **kwargs).data

    def delete(self, uuid_: str, **_ignored: Any) -> SuccessResponse:
        self.get(uuid_)
        self._owner._store.execute("DELETE FROM edges WHERE uuid = ?", (uuid_,))
        return SuccessResponse(message="edge deleted")


class LocalEpisodeClient:
    def __init__(self, owner: "LocalZep"):
        self._owner = owner

    def get(self, uuid_: str, **_ignored: Any) -> Episode:
        row = self._owner._store.one("SELECT * FROM episodes WHERE uuid = ?", (uuid_,))
        if row is None:
            raise _not_found(f"episode not found: {uuid_}")
        return _episode_from_row(row)

    def get_by_graph_id(self, graph_id: str, *, lastn: Optional[int] = None,
                        **_ignored: Any) -> EpisodeResponse:
        self._owner._require_graph(graph_id)
        sql = "SELECT * FROM episodes WHERE graph_id = ? ORDER BY seq DESC"
        params: List[Any] = [graph_id]
        if lastn:
            sql += " LIMIT ?"
            params.append(int(lastn))
        rows = list(reversed(self._owner._store.query(sql, params)))
        return EpisodeResponse(episodes=[_episode_from_row(row) for row in rows])

    def get_nodes_and_edges(self, uuid_: str, **_ignored: Any) -> SimpleNamespace:
        self.get(uuid_)
        edge_rows = [
            row for row in self._owner._store.query(
                "SELECT * FROM edges WHERE episodes LIKE ? ORDER BY seq", (f'%"{uuid_}"%',)
            )
        ]
        node_ids = {row["source_node_uuid"] for row in edge_rows} | {
            row["target_node_uuid"] for row in edge_rows
        }
        nodes = [self._owner.graph.node.get(node_id) for node_id in sorted(node_ids)]
        return SimpleNamespace(edges=[_edge_from_row(row) for row in edge_rows], nodes=nodes)

    def delete(self, uuid_: str, **_ignored: Any) -> SuccessResponse:
        self.get(uuid_)
        self._owner._store.execute("DELETE FROM episodes WHERE uuid = ?", (uuid_,))
        return SuccessResponse(message="episode deleted")


class LocalGraphClient:
    def __init__(self, owner: "LocalZep"):
        self._owner = owner
        self.node = LocalNodeClient(owner)
        self.edge = LocalEdgeClient(owner)
        self.episode = LocalEpisodeClient(owner)

    # -- graph lifecycle -------------------------------------------------

    def create(self, *, graph_id: str, name: Optional[str] = None,
               description: Optional[str] = None, **_ignored: Any) -> Graph:
        if not graph_id:
            raise _bad_request("graph_id is required")
        store = self._owner._store
        if store.one("SELECT 1 FROM graphs WHERE graph_id = ?", (graph_id,)):
            raise _bad_request(f"graph already exists: {graph_id}")
        created_at = _now()
        graph_uuid = str(uuid.uuid4())
        store.execute(
            "INSERT INTO graphs(graph_id, uuid, name, description, ontology, created_at) "
            "VALUES (?, ?, ?, ?, NULL, ?)",
            (graph_id, graph_uuid, name, description, created_at),
        )
        return self.get(graph_id)

    def get(self, graph_id: str, **_ignored: Any) -> Graph:
        row = self._owner._require_graph(graph_id)
        return Graph(
            graph_id=row["graph_id"],
            id=None,
            uuid_=row["uuid"],
            name=row["name"],
            description=row["description"],
            created_at=row["created_at"],
        )

    def list_all(self, *, page_number: Optional[int] = None, page_size: Optional[int] = None,
                 **_ignored: Any) -> GraphListResponse:
        rows = self._owner._store.query("SELECT graph_id FROM graphs ORDER BY created_at")
        graphs = [self.get(row["graph_id"]) for row in rows]
        total = len(graphs)
        if page_size:
            start = max((page_number or 1) - 1, 0) * page_size
            graphs = graphs[start:start + page_size]
        return GraphListResponse(graphs=graphs, row_count=len(graphs), total_count=total)

    def update(self, graph_id: str, *, name: Any = None, description: Any = None,
               **_ignored: Any) -> Graph:
        self._owner._require_graph(graph_id)
        if name not in (None, ...):
            self._owner._store.execute("UPDATE graphs SET name = ? WHERE graph_id = ?", (name, graph_id))
        if description not in (None, ...):
            self._owner._store.execute(
                "UPDATE graphs SET description = ? WHERE graph_id = ?", (description, graph_id)
            )
        return self.get(graph_id)

    def delete(self, graph_id: str, **_ignored: Any) -> SuccessResponse:
        self._owner._require_graph(graph_id)
        with self._owner._store.transaction() as store:
            for table in ("edges", "nodes", "episodes", "graphs"):
                store.conn.execute(f"DELETE FROM {table} WHERE graph_id = ?", (graph_id,))
        return SuccessResponse(message="graph deleted")

    # -- ontology --------------------------------------------------------

    def set_ontology(self, entities: Optional[Dict[str, Any]] = None,
                     edges: Optional[Dict[str, Any]] = None, *,
                     graph_ids: Optional[Sequence[str]] = None,
                     user_ids: Optional[Sequence[str]] = None,
                     **_ignored: Any) -> SuccessResponse:
        ontology = serialize_ontology(entities, edges)
        for graph_id in graph_ids or []:
            self._owner._require_graph(graph_id)
            self._owner._store.execute(
                "UPDATE graphs SET ontology = ? WHERE graph_id = ?",
                (json.dumps(ontology, ensure_ascii=False), graph_id),
            )
        return SuccessResponse(message="ontology set")

    set_entity_types = set_ontology

    def list_entity_types(self, *, graph_id: Optional[str] = None, **_ignored: Any) -> SimpleNamespace:
        ontology = self._owner._ontology(graph_id) if graph_id else {}
        return SimpleNamespace(
            entity_types=[
                SimpleNamespace(name=name, description=spec.get("description"), properties=spec.get("attributes"))
                for name, spec in (ontology.get("entity_types") or {}).items()
            ],
            edge_types=[
                SimpleNamespace(name=name, description=spec.get("description"), properties=spec.get("attributes"),
                                source_targets=spec.get("source_targets"))
                for name, spec in (ontology.get("edge_types") or {}).items()
            ],
        )

    # -- ingestion -------------------------------------------------------

    def add(self, *, data: str, type: str = "text", graph_id: Optional[str] = None,
            created_at: Optional[str] = None, source_description: Optional[str] = None,
            metadata: Optional[Dict[str, Any]] = None, user_id: Optional[str] = None,
            **_ignored: Any) -> Episode:
        if not graph_id:
            raise _bad_request("graph_id is required for the local memory backend")
        self._owner._require_graph(graph_id)
        if not isinstance(data, str) or not data.strip():
            raise _bad_request("data must be a non-empty string")
        is_activity = (metadata or {}).get("source") == SIMULATION_ACTIVITY_SOURCE
        extract = (not is_activity) or self._owner.extract_activity
        episode_uuid = self._owner._insert_episode(
            graph_id=graph_id,
            content=data,
            source=type,
            source_description=source_description,
            metadata=metadata,
            created_at=created_at,
            extract=extract,
        )
        if extract:
            self._owner._submit_episode(episode_uuid)
        return self.episode.get(episode_uuid)

    # -- search ----------------------------------------------------------

    def search(self, *, query: str, graph_id: Optional[str] = None, limit: Optional[int] = None,
               scope: Optional[str] = None, search_filters: Any = None,
               **_ignored: Any) -> GraphSearchResults:
        if not graph_id:
            raise _bad_request("graph_id is required for the local memory backend")
        self._owner._require_graph(graph_id)
        if not isinstance(query, str) or not query.strip():
            raise _bad_request("query must be a non-empty string")
        limit = int(limit) if limit not in (None, ...) else 10
        limit = max(1, min(limit, 50))
        scope = scope if scope not in (None, ...) else "edges"
        if scope == "auto":
            return GraphSearchResults(
                edges=self._owner._search_edges(graph_id, query, limit, search_filters),
                nodes=self._owner._search_nodes(graph_id, query, limit, search_filters),
                episodes=self._owner._search_episodes(graph_id, query, limit),
            )
        if scope == "nodes":
            return GraphSearchResults(nodes=self._owner._search_nodes(graph_id, query, limit, search_filters))
        if scope == "episodes":
            return GraphSearchResults(episodes=self._owner._search_episodes(graph_id, query, limit))
        if scope == "edges":
            return GraphSearchResults(edges=self._owner._search_edges(graph_id, query, limit, search_filters))
        return GraphSearchResults()


class LocalBatchClient:
    def __init__(self, owner: "LocalZep"):
        self._owner = owner

    def create(self, *, metadata: Optional[Dict[str, Any]] = None, ignore_roles: Any = None,
               **_ignored: Any) -> BatchSummary:
        batch_id = f"local_batch_{uuid.uuid4().hex}"
        now = _now()
        self._owner._store.execute(
            "INSERT INTO batches(batch_id, metadata, status, created_at, updated_at, seq) "
            "VALUES (?, ?, 'draft', ?, ?, ?)",
            (batch_id, json.dumps(metadata or {}, ensure_ascii=False), now, now,
             self._owner._store.next_seq()),
        )
        return self.get(batch_id)

    def _batch_row(self, batch_id: str) -> sqlite3.Row:
        row = self._owner._store.one("SELECT * FROM batches WHERE batch_id = ?", (batch_id,))
        if row is None:
            raise _not_found(f"batch not found: {batch_id}")
        return row

    def add(self, batch_id: str, *, items: Sequence[Any], **_ignored: Any) -> List[BatchItemDetail]:
        row = self._batch_row(batch_id)
        if row["status"] != "draft":
            raise _bad_request(f"batch {batch_id} is not a draft")
        store = self._owner._store
        prepared = []
        for item in items:
            item_type = getattr(item, "type", None) or "graph_episode"
            graph_id = getattr(item, "graph_id", None)
            data = getattr(item, "data", None) or getattr(item, "content", None)
            if item_type != "graph_episode" or not graph_id:
                raise _bad_request("local batches only support graph_episode items with a graph_id")
            self._owner._require_graph(graph_id)
            if not isinstance(data, str) or not data.strip():
                raise _bad_request("batch item data must be a non-empty string")
            prepared.append((item, graph_id, data))

        created: List[str] = []
        with store.lock:
            existing = store.one(
                "SELECT COUNT(*) FROM batch_items WHERE batch_id = ?", (batch_id,)
            )[0]
            for offset, (item, graph_id, data) in enumerate(prepared):
                episode_uuid = self._owner._insert_episode(
                    graph_id=graph_id,
                    content=data,
                    source=getattr(item, "data_type", None) or "text",
                    source_description=getattr(item, "source_description", None),
                    metadata=getattr(item, "metadata", None),
                    created_at=getattr(item, "created_at", None),
                    extract=True,
                )
                item_id = str(uuid.uuid4())
                now = _now()
                store.execute(
                    "INSERT INTO batch_items(item_id, batch_id, sequence_index, graph_id, "
                    "episode_uuid, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)",
                    (item_id, batch_id, existing + offset, graph_id, episode_uuid, now, now),
                )
                created.append(item_id)
            store.execute("UPDATE batches SET updated_at = ? WHERE batch_id = ?", (_now(), batch_id))
        return [self._item_from_row(self._item_row(item_id)) for item_id in created]

    def _item_row(self, item_id: str) -> sqlite3.Row:
        return self._owner._store.one("SELECT * FROM batch_items WHERE item_id = ?", (item_id,))

    @staticmethod
    def _item_from_row(row: sqlite3.Row) -> BatchItemDetail:
        return BatchItemDetail(
            item_id=row["item_id"],
            kind="graph_episode",
            sequence_index=row["sequence_index"],
            graph_id=row["graph_id"],
            episode_uuid=row["episode_uuid"],
            source_uuid=row["episode_uuid"],
            status=row["status"],
            error=_json_load(row["error"], None),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def process(self, batch_id: str, **_ignored: Any) -> BatchSummary:
        row = self._batch_row(batch_id)
        if row["status"] != "draft":
            return self.get(batch_id)
        store = self._owner._store
        item_rows = store.query(
            "SELECT * FROM batch_items WHERE batch_id = ? ORDER BY sequence_index", (batch_id,)
        )
        now = _now()
        with store.lock:
            if not item_rows:
                store.execute(
                    "UPDATE batches SET status = 'invalid', updated_at = ?, completed_at = ? WHERE batch_id = ?",
                    (now, now, batch_id),
                )
                return self.get(batch_id)
            store.execute(
                "UPDATE batches SET status = 'queued', processed_at = ?, updated_at = ? WHERE batch_id = ?",
                (now, now, batch_id),
            )
            store.execute(
                "UPDATE batch_items SET status = 'queued', updated_at = ? WHERE batch_id = ?",
                (now, batch_id),
            )
        for item in item_rows:
            self._owner._submit_episode(item["episode_uuid"], batch_item_id=item["item_id"])
        return self.get(batch_id)

    def get(self, batch_id: str, **_ignored: Any) -> BatchSummary:
        row = self._batch_row(batch_id)
        counts = Counter(
            r["status"] for r in self._owner._store.query(
                "SELECT status FROM batch_items WHERE batch_id = ?", (batch_id,)
            )
        )
        total = sum(counts.values())
        status = row["status"]
        if status not in {"draft", "invalid", "canceled"} and total:
            done = counts["succeeded"] + counts["failed"] + counts["skipped"] + counts["canceled"]
            if done < total:
                status = "processing" if (done or counts["processing"]) else "queued"
            elif counts["failed"] == 0 and counts["canceled"] == 0:
                status = "succeeded"
            elif counts["succeeded"] or counts["skipped"]:
                status = "partial"
            else:
                status = "failed"
            if status != row["status"]:
                now = _now()
                completed = now if status in {"succeeded", "partial", "failed"} else None
                self._owner._store.execute(
                    "UPDATE batches SET status = ?, updated_at = ?, completed_at = COALESCE(?, completed_at) "
                    "WHERE batch_id = ?",
                    (status, now, completed, batch_id),
                )
                row = self._batch_row(batch_id)
        finished = counts["succeeded"] + counts["failed"] + counts["skipped"] + counts["canceled"]
        progress = BatchProgress(
            total_items=total,
            succeeded_items=counts["succeeded"],
            failed_items=counts["failed"],
            skipped_items=counts["skipped"],
            canceled_items=counts["canceled"],
            processing_items=counts["processing"],
            queued_items=counts["queued"] + counts["pending"],
            percent_complete=(100.0 * finished / total) if total else 0.0,
        )
        return BatchSummary(
            batch_id=row["batch_id"],
            status=row["status"],
            metadata=_json_load(row["metadata"], {}),
            item_count=total,
            progress=progress,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            processed_at=row["processed_at"],
            completed_at=row["completed_at"],
        )

    def list(self, *, limit: Optional[int] = None, cursor: Optional[int] = None,
             status: Optional[str] = None, **_ignored: Any) -> BatchListResponse:
        rows = self._owner._store.query("SELECT batch_id FROM batches ORDER BY seq")
        batches = [self.get(row["batch_id"]) for row in rows]
        if status:
            batches = [batch for batch in batches if batch.status == status]
        offset, page_limit = _page_bounds(cursor, limit)
        end = offset + page_limit if page_limit else len(batches)
        next_cursor = end if end < len(batches) else None
        return BatchListResponse(batches=batches[offset:end], next_cursor=next_cursor)

    def list_items(self, batch_id: str, *, limit: Optional[int] = None,
                   cursor: Optional[int] = None, status: Optional[str] = None,
                   **_ignored: Any) -> BatchItemListResponse:
        self._batch_row(batch_id)
        sql = "SELECT * FROM batch_items WHERE batch_id = ?"
        params: List[Any] = [batch_id]
        if status:
            sql += " AND status = ?"
            params.append(status)
        rows = self._owner._store.query(sql + " ORDER BY sequence_index", params)
        offset, page_limit = _page_bounds(cursor, limit)
        end = offset + page_limit if page_limit else len(rows)
        next_cursor = end if end < len(rows) else None
        return BatchItemListResponse(
            items=[self._item_from_row(row) for row in rows[offset:end]],
            next_cursor=next_cursor,
        )

    def delete(self, batch_id: str, **_ignored: Any) -> SuccessResponse:
        self._batch_row(batch_id)
        with self._owner._store.transaction() as store:
            store.conn.execute("DELETE FROM batch_items WHERE batch_id = ?", (batch_id,))
            store.conn.execute("DELETE FROM batches WHERE batch_id = ?", (batch_id,))
        return SuccessResponse(message="batch deleted")


# --------------------------------------------------------------------------
# Main client
# --------------------------------------------------------------------------


class LocalZep:
    """Drop-in local replacement for ``zep_cloud.client.Zep`` (graph + batch)."""

    def __init__(
        self,
        db_path: str,
        *,
        llm_client: Any = None,
        extract_activity: bool = False,
        max_workers: int = 4,
    ):
        self.db_path = db_path
        self.extract_activity = extract_activity
        self._store = _Store(db_path)
        self._llm_client = llm_client
        self._llm_lock = threading.Lock()
        # Daemon workers: an interrupted extraction is simply re-queued by
        # _resume_unprocessed() on the next start, so shutdown never blocks.
        self._queue: "queue.Queue[Optional[tuple[str, Optional[str]]]]" = queue.Queue()
        self._workers = [
            threading.Thread(target=self._worker_loop, name=f"local-graph-{i}", daemon=True)
            for i in range(max(1, int(max_workers)))
        ]
        for worker in self._workers:
            worker.start()
        self.graph = LocalGraphClient(self)
        self.batch = LocalBatchClient(self)
        self._resume_unprocessed()

    # -- infrastructure --------------------------------------------------

    @property
    def llm(self) -> Any:
        with self._llm_lock:
            if self._llm_client is None:
                from .llm_client import LLMClient

                self._llm_client = LLMClient()
            return self._llm_client

    def close(self, timeout: float = 5.0) -> None:
        for _worker in self._workers:
            self._queue.put(None)
        for worker in self._workers:
            worker.join(timeout)
        self._store.close()

    def _worker_loop(self) -> None:
        while True:
            job = self._queue.get()
            if job is None:
                return
            try:
                self._process_episode_safely(*job)
            except Exception:  # noqa: BLE001 - store may be closed during shutdown
                logger.exception("Local graph worker failed")

    def wait_idle(self, timeout: float = 30.0) -> bool:
        """Block until every queued extraction has finished (tests/scripts)."""

        import time

        deadline = time.time() + timeout
        while time.time() < deadline:
            pending = self._store.one(
                "SELECT COUNT(*) FROM episodes e "
                "LEFT JOIN batch_items bi ON bi.episode_uuid = e.uuid "
                "LEFT JOIN batches b ON b.batch_id = bi.batch_id "
                "WHERE e.processed = 0 AND (bi.item_id IS NULL OR b.status != 'draft')"
            )[0]
            if not pending:
                return True
            time.sleep(0.02)
        return False

    def _require_graph(self, graph_id: str) -> sqlite3.Row:
        row = self._store.one("SELECT * FROM graphs WHERE graph_id = ?", (graph_id,))
        if row is None:
            raise _not_found(f"graph not found: {graph_id}")
        return row

    def _ontology(self, graph_id: str) -> Dict[str, Any]:
        row = self._store.one("SELECT ontology FROM graphs WHERE graph_id = ?", (graph_id,))
        if row is None:
            return {}
        return _json_load(row["ontology"], {}) or {}

    def _page(self, table: str, graph_id: str, limit: Any, cursor: Any, convert) -> _RawResponse:
        self._require_graph(graph_id)
        offset, page_limit = _page_bounds(cursor, limit)
        sql = f"SELECT * FROM {table} WHERE graph_id = ? ORDER BY seq"
        params: List[Any] = [graph_id]
        if page_limit:
            sql += " LIMIT ? OFFSET ?"
            params.extend([page_limit + 1, offset])
        rows = self._store.query(sql, params)
        headers: Dict[str, str] = {}
        if page_limit and len(rows) > page_limit:
            rows = rows[:page_limit]
            headers["zep-next-cursor"] = str(offset + page_limit)
        return _RawResponse([convert(row) for row in rows], headers)

    def _resume_unprocessed(self) -> None:
        """Re-queue extraction work interrupted by a process restart."""

        rows = self._store.query(
            "SELECT e.uuid, bi.item_id FROM episodes e "
            "LEFT JOIN batch_items bi ON bi.episode_uuid = e.uuid "
            "LEFT JOIN batches b ON b.batch_id = bi.batch_id "
            "WHERE e.processed = 0 AND (bi.item_id IS NULL OR b.status NOT IN ('draft', 'invalid', 'canceled')) "
            "ORDER BY e.seq"
        )
        for row in rows:
            self._submit_episode(row["uuid"], batch_item_id=row["item_id"])

    # -- episodes --------------------------------------------------------

    def _insert_episode(self, *, graph_id: str, content: str, source: Optional[str],
                        source_description: Optional[str], metadata: Optional[Dict[str, Any]],
                        created_at: Optional[str], extract: bool) -> str:
        episode_uuid = str(uuid.uuid4())
        self._store.execute(
            "INSERT INTO episodes(uuid, graph_id, content, source, source_description, metadata, "
            "created_at, processed, extract, seq) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                episode_uuid,
                graph_id,
                content,
                source if source not in (None, ...) else "text",
                source_description if source_description not in (None, ...) else None,
                json.dumps(metadata, ensure_ascii=False) if metadata not in (None, ...) else None,
                created_at if created_at not in (None, ...) else _now(),
                0 if extract else 1,
                1 if extract else 0,
                self._store.next_seq(),
            ),
        )
        return episode_uuid

    def _submit_episode(self, episode_uuid: str, batch_item_id: Optional[str] = None) -> None:
        self._queue.put((episode_uuid, batch_item_id))

    def _set_item_status(self, item_id: Optional[str], status: str, error: Any = None) -> None:
        if not item_id:
            return
        self._store.execute(
            "UPDATE batch_items SET status = ?, error = ?, updated_at = ? WHERE item_id = ?",
            (status, json.dumps(error, ensure_ascii=False) if error else None, _now(), item_id),
        )

    def _process_episode_safely(self, episode_uuid: str, batch_item_id: Optional[str]) -> None:
        try:
            self._set_item_status(batch_item_id, "processing")
            self.process_episode(episode_uuid)
            self._set_item_status(batch_item_id, "succeeded")
        except Exception as error:  # noqa: BLE001 - recorded on the item/episode
            logger.error("Local graph extraction failed for episode %s: %s", episode_uuid, error)
            self._store.execute(
                "UPDATE episodes SET processed = 1, error = ? WHERE uuid = ?",
                (str(error)[:2000], episode_uuid),
            )
            self._set_item_status(
                batch_item_id, "failed", {"message": str(error)[:2000], "type": type(error).__name__}
            )

    def process_episode(self, episode_uuid: str) -> None:
        """Extract entities/edges from one episode with the LLM and merge them."""

        row = self._store.one("SELECT * FROM episodes WHERE uuid = ?", (episode_uuid,))
        if row is None:
            return  # graph deleted while queued
        if row["processed"]:
            return
        graph_id = row["graph_id"]
        ontology = self._ontology(graph_id)
        extraction = self._extract(row["content"], ontology)
        self._merge_extraction(graph_id, row, ontology, extraction)

    def _extract(self, text: str, ontology: Dict[str, Any]) -> Dict[str, Any]:
        messages = [
            {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"{_ontology_prompt(ontology)}\n\nEpisode text:\n<<<\n{text}\n>>>",
            },
        ]
        result = self.llm.chat_json(
            messages=messages,
            temperature=0.1,
            max_tokens=4096,
            max_attempts=_EXTRACTION_ATTEMPTS,
        )
        if not isinstance(result, dict):
            raise ValueError("extraction response must be a JSON object")
        return result

    def _merge_extraction(self, graph_id: str, episode_row: sqlite3.Row,
                          ontology: Dict[str, Any], extraction: Dict[str, Any]) -> None:
        entity_specs = ontology.get("entity_types") or {}
        edge_specs = ontology.get("edge_types") or {}
        type_lookup = {name.lower(): name for name in entity_specs}
        edge_lookup = {name.upper(): name for name in edge_specs}
        episode_uuid = episode_row["uuid"]
        episode_time = episode_row["created_at"]

        raw_entities = extraction.get("entities") or []
        raw_edges = extraction.get("relationships") or extraction.get("edges") or []
        if not isinstance(raw_entities, list) or not isinstance(raw_edges, list):
            raise ValueError("extraction entities/relationships must be lists")

        with self._store.transaction() as store:
            conn = store.conn
            if conn.execute("SELECT 1 FROM graphs WHERE graph_id = ?", (graph_id,)).fetchone() is None:
                return  # deleted concurrently
            name_to_uuid: Dict[str, str] = {}

            def upsert_node(name: str, label: str, summary: str, attributes: Dict[str, Any]) -> str:
                norm = _normalize_name(name)
                existing = conn.execute(
                    "SELECT * FROM nodes WHERE graph_id = ? AND norm_name = ? AND label = ?",
                    (graph_id, norm, label),
                ).fetchone()
                if existing is None and label == "Entity":
                    # An untyped mention of an already typed entity reuses it.
                    existing = conn.execute(
                        "SELECT * FROM nodes WHERE graph_id = ? AND norm_name = ? ORDER BY seq LIMIT 1",
                        (graph_id, norm),
                    ).fetchone()
                elif existing is None:
                    # Upgrade a previously untyped node instead of duplicating it.
                    untyped = conn.execute(
                        "SELECT * FROM nodes WHERE graph_id = ? AND norm_name = ? AND label = 'Entity'",
                        (graph_id, norm),
                    ).fetchone()
                    if untyped is not None:
                        conn.execute("UPDATE nodes SET label = ? WHERE uuid = ?", (label, untyped["uuid"]))
                        existing = conn.execute(
                            "SELECT * FROM nodes WHERE uuid = ?", (untyped["uuid"],)
                        ).fetchone()
                if existing is None:
                    node_uuid = str(uuid.uuid4())
                    conn.execute(
                        "INSERT INTO nodes(uuid, graph_id, name, norm_name, label, summary, attributes, "
                        "created_at, seq) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (node_uuid, graph_id, name.strip(), norm, label, summary[:_MAX_SUMMARY_CHARS],
                         json.dumps(attributes, ensure_ascii=False), _now(), store.next_seq()),
                    )
                    return node_uuid
                merged_summary = existing["summary"] or ""
                if summary and summary not in merged_summary:
                    merged_summary = f"{merged_summary} {summary}".strip() if merged_summary else summary
                    if len(merged_summary) > _MAX_SUMMARY_CHARS:
                        merged_summary = merged_summary[-_MAX_SUMMARY_CHARS:]
                merged_attrs = _json_load(existing["attributes"], {}) or {}
                merged_attrs.update({k: v for k, v in attributes.items() if v not in (None, "")})
                conn.execute(
                    "UPDATE nodes SET summary = ?, attributes = ? WHERE uuid = ?",
                    (merged_summary, json.dumps(merged_attrs, ensure_ascii=False), existing["uuid"]),
                )
                return existing["uuid"]

            for entity in raw_entities:
                if not isinstance(entity, dict):
                    continue
                name = str(entity.get("name") or "").strip()
                if not name:
                    continue
                raw_type = str(entity.get("type") or entity.get("label") or "Entity").strip()
                label = type_lookup.get(raw_type.lower(), "Entity")
                allowed = set((entity_specs.get(label) or {}).get("attributes") or {})
                raw_attrs = entity.get("attributes") if isinstance(entity.get("attributes"), dict) else {}
                attributes = {
                    str(k): v for k, v in raw_attrs.items()
                    if (not allowed or k in allowed) and isinstance(v, (str, int, float, bool))
                }
                summary = str(entity.get("summary") or "").strip()
                name_to_uuid[_normalize_name(name)] = upsert_node(name, label, summary, attributes)

            def resolve(name: str) -> str:
                norm = _normalize_name(name)
                if norm in name_to_uuid:
                    return name_to_uuid[norm]
                existing = conn.execute(
                    "SELECT uuid FROM nodes WHERE graph_id = ? AND norm_name = ? ORDER BY seq LIMIT 1",
                    (graph_id, norm),
                ).fetchone()
                node_uuid = existing["uuid"] if existing else upsert_node(name, "Entity", "", {})
                name_to_uuid[norm] = node_uuid
                return node_uuid

            for rel in raw_edges:
                if not isinstance(rel, dict):
                    continue
                source = str(rel.get("source") or "").strip()
                target = str(rel.get("target") or "").strip()
                fact = str(rel.get("fact") or "").strip()
                if not source or not target:
                    continue
                edge_name = _normalize_edge_name(rel.get("type") or rel.get("name") or "RELATED_TO")
                edge_name = edge_lookup.get(edge_name, edge_name)
                if not fact:
                    fact = f"{source} {edge_name.replace('_', ' ').lower()} {target}"
                source_uuid = resolve(source)
                target_uuid = resolve(target)
                allowed = set((edge_specs.get(edge_name) or {}).get("attributes") or {})
                raw_attrs = rel.get("attributes") if isinstance(rel.get("attributes"), dict) else {}
                attributes = {
                    str(k): v for k, v in raw_attrs.items()
                    if (not allowed or k in allowed) and isinstance(v, (str, int, float, bool))
                }
                valid_at = rel.get("valid_at") or episode_time
                invalid_at = rel.get("invalid_at") or None
                duplicate = conn.execute(
                    "SELECT * FROM edges WHERE graph_id = ? AND source_node_uuid = ? AND "
                    "target_node_uuid = ? AND name = ? AND lower(fact) = lower(?)",
                    (graph_id, source_uuid, target_uuid, edge_name, fact),
                ).fetchone()
                if duplicate is not None:
                    episodes = _json_load(duplicate["episodes"], []) or []
                    if episode_uuid not in episodes:
                        episodes.append(episode_uuid)
                    conn.execute(
                        "UPDATE edges SET episodes = ?, invalid_at = COALESCE(?, invalid_at) WHERE uuid = ?",
                        (json.dumps(episodes), invalid_at, duplicate["uuid"]),
                    )
                    continue
                conn.execute(
                    "INSERT INTO edges(uuid, graph_id, name, fact, source_node_uuid, target_node_uuid, "
                    "attributes, episodes, created_at, valid_at, invalid_at, expired_at, seq) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)",
                    (str(uuid.uuid4()), graph_id, edge_name, fact, source_uuid, target_uuid,
                     json.dumps(attributes, ensure_ascii=False), json.dumps([episode_uuid]),
                     _now(), str(valid_at), str(invalid_at) if invalid_at else None,
                     store.next_seq()),
                )

            conn.execute(
                "UPDATE episodes SET processed = 1, error = NULL WHERE uuid = ?", (episode_uuid,)
            )

    # -- search ----------------------------------------------------------

    @staticmethod
    def _filter_values(search_filters: Any, name: str) -> Optional[List[str]]:
        if search_filters is None:
            return None
        if isinstance(search_filters, dict):
            value = search_filters.get(name)
        else:
            value = getattr(search_filters, name, None)
        return list(value) if value else None

    def _search_edges(self, graph_id: str, query: str, limit: int,
                      search_filters: Any = None) -> List[EntityEdge]:
        rows = self._store.query("SELECT * FROM edges WHERE graph_id = ? ORDER BY seq", (graph_id,))
        include = self._filter_values(search_filters, "edge_types")
        exclude = self._filter_values(search_filters, "exclude_edge_types") or []
        rows = [r for r in rows if (not include or r["name"] in include) and r["name"] not in exclude]
        node_names = {
            r["uuid"]: r["name"]
            for r in self._store.query("SELECT uuid, name FROM nodes WHERE graph_id = ?", (graph_id,))
        }
        documents = [
            f"{r['fact']} {r['name'].replace('_', ' ')} "
            f"{node_names.get(r['source_node_uuid'], '')} {node_names.get(r['target_node_uuid'], '')}"
            for r in rows
        ]
        candidates: List[tuple[float, EntityEdge]] = []
        for index, score in bm25_rank(query, documents):
            candidates.append((score, _edge_from_row(rows[index], score)))

        # Episodes stored without LLM extraction (simulation activity by
        # default) stay searchable as line-level pseudo-facts.
        if not include or ACTIVITY_EDGE_NAME in include:
            line_edges = self._unextracted_episode_lines(graph_id)
            line_docs = [edge.fact for edge in line_edges]
            for index, score in bm25_rank(query, line_docs):
                edge = line_edges[index].model_copy(update={"score": score, "relevance": score})
                candidates.append((score, edge))

        candidates.sort(key=lambda pair: -pair[0])
        return [edge for _score, edge in candidates[:limit]]

    def _unextracted_episode_lines(self, graph_id: str) -> List[EntityEdge]:
        rows = self._store.query(
            "SELECT * FROM episodes WHERE graph_id = ? AND extract = 0 ORDER BY seq", (graph_id,)
        )
        edges: List[EntityEdge] = []
        for row in rows:
            for line_number, line in enumerate(row["content"].splitlines()):
                line = line.strip()
                if not line:
                    continue
                edges.append(
                    EntityEdge(
                        uuid_=f"{row['uuid']}:{line_number}",
                        name=ACTIVITY_EDGE_NAME,
                        fact=line,
                        source_node_uuid="",
                        target_node_uuid="",
                        attributes={"episode_uuid": row["uuid"], "unextracted": True},
                        episodes=[row["uuid"]],
                        created_at=row["created_at"],
                        valid_at=row["created_at"],
                    )
                )
        return edges

    def _search_nodes(self, graph_id: str, query: str, limit: int,
                      search_filters: Any = None) -> List[EntityNode]:
        rows = self._store.query("SELECT * FROM nodes WHERE graph_id = ? ORDER BY seq", (graph_id,))
        include = self._filter_values(search_filters, "node_labels")
        exclude = self._filter_values(search_filters, "exclude_node_labels") or []
        rows = [r for r in rows if (not include or r["label"] in include) and r["label"] not in exclude]
        documents = [f"{r['name']} {r['name']} {r['label']} {r['summary']}" for r in rows]
        return [
            _node_from_row(rows[index], score)
            for index, score in bm25_rank(query, documents)[:limit]
        ]

    def _search_episodes(self, graph_id: str, query: str, limit: int) -> List[Episode]:
        rows = self._store.query("SELECT * FROM episodes WHERE graph_id = ? ORDER BY seq", (graph_id,))
        documents = [r["content"] for r in rows]
        return [
            _episode_from_row(rows[index], score)
            for index, score in bm25_rank(query, documents)[:limit]
        ]


# --------------------------------------------------------------------------
# Process-wide instance
# --------------------------------------------------------------------------

_instances: Dict[str, LocalZep] = {}
_instances_lock = threading.Lock()


def get_local_zep_client(db_path: Optional[str] = None) -> LocalZep:
    """Return the process-shared ``LocalZep`` for ``db_path`` (or config)."""

    from ..config import Config

    path = db_path or Config.LOCAL_GRAPH_DB
    with _instances_lock:
        client = _instances.get(path)
        if client is None:
            client = LocalZep(
                path,
                extract_activity=Config.MEMORY_EXTRACT_ACTIVITY,
                max_workers=Config.LOCAL_GRAPH_EXTRACT_WORKERS,
            )
            _instances[path] = client
        return client


def clear_local_zep_clients() -> None:
    """Close and forget cached local clients (tests / reconfiguration)."""

    with _instances_lock:
        clients = list(_instances.values())
        _instances.clear()
    for client in clients:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass
