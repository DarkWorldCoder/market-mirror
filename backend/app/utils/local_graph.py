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
just like Zep Cloud. Identical episode texts reuse a cached extraction (no
second LLM call).

Search is hybrid: a pure-Python BM25 ranking fused (reciprocal rank fusion)
with cosine similarity over local fastembed embeddings of facts, node
names/summaries and episode text. Embeddings are optional: without
``fastembed`` (or when the model cannot be loaded) search is BM25 only.

Entity resolution merges an extracted entity into an existing node on exact
normalised name, a declared alias, a safe name variant ("Acme Inc." / "Acme",
"WHO" / "World Health Organization", "Alice" / "Alice Smith" when unambiguous)
or, for the same type, name-embedding cosine >= ``entity_similarity``.

Not implemented compared to Zep Cloud: temporal contradiction resolution (old
facts are never auto-invalidated), cross-encoder reranking (``reranker`` is
accepted and ignored), user/thread memory.
"""

from __future__ import annotations

import hashlib
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

import numpy as np

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

from .embeddings import (
    cosine_rank,
    from_blob,
    reciprocal_rank_fusion,
    text_hash,
    to_blob,
)
from .logger import get_logger

logger = get_logger("mirofish.local_graph")

# Episodes written by the simulation memory updater carry this metadata source.
SIMULATION_ACTIVITY_SOURCE = "mirofish_simulation"
ACTIVITY_EDGE_NAME = "SIMULATION_ACTIVITY"
_MAX_SUMMARY_CHARS = 1200
_EXTRACTION_ATTEMPTS = 3
_EXTRACTION_MAX_TOKENS = 3000
# Bump when the extraction prompt/format changes to invalidate cached results.
_EXTRACTION_PROMPT_VERSION = "2"
_DEFAULT_MAX_EPISODE_CHARS = 6000
_EMBED_TEXT_CHARS = 1000
# Missing vectors computed lazily during one search (e.g. a DB created before
# embeddings were enabled); the rest stay BM25-only until ingested again.
_SEARCH_BACKFILL_LIMIT = 512
_VECTOR_CACHE_MAX = 200_000


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
# Entity name variants (deterministic, conservative)
# --------------------------------------------------------------------------

_HAS_CJK_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯]")
_LEGAL_SUFFIXES = {
    "inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited",
    "llc", "plc", "gmbh", "ag", "sa", "nv", "bv", "pte", "pvt", "tbk", "bhd", "sdn",
}
_CJK_SUFFIXES = ("股份有限公司", "有限责任公司", "有限公司", "集团", "公司")
_ACRONYM_STOPWORDS = {"of", "the", "and", "for", "&", "de", "du", "la", "le", "der", "und"}


def _name_tokens(norm: str) -> List[str]:
    return [t for t in re.split(r"[^0-9a-z\u0080-￿]+", norm) if t]


def _name_core(norm: str) -> str:
    """Name without articles, punctuation and legal-form suffixes."""

    if _HAS_CJK_RE.search(norm):
        core = re.sub(r"\s+", "", norm)
        for suffix in _CJK_SUFFIXES:
            if core.endswith(suffix) and len(core) - len(suffix) >= 2:
                core = core[: -len(suffix)]
                break
        return core
    tokens = _name_tokens(norm)
    if tokens and tokens[0] == "the" and len(tokens) > 1:
        tokens = tokens[1:]
    while len(tokens) > 1 and tokens[-1] in _LEGAL_SUFFIXES:
        tokens = tokens[:-1]
    return " ".join(tokens)


def _acronym_of(short_raw: str, long_norm: str) -> bool:
    short = re.sub(r"[^A-Za-z]", "", short_raw)
    if not (2 <= len(short) <= 6) or not short.isupper() or short_raw.strip() != short_raw.strip().upper():
        return False
    tokens = [t for t in _name_tokens(long_norm) if t not in _ACRONYM_STOPWORDS and t not in _LEGAL_SUFFIXES]
    return len(tokens) == len(short) and "".join(t[0] for t in tokens) == short.lower()


NAME_MATCH_NONE, NAME_MATCH_WEAK, NAME_MATCH_STRONG = 0, 1, 2


def name_match_strength(name_a: str, name_b: str) -> int:
    """How safely two entity names denote the same entity (deterministic).

    STRONG: equal cores ("Acme Inc." / "Acme", "澜舟科技有限公司" / "澜舟科技")
    or an acronym of the other name ("WHO" / "World Health Organization").
    WEAK: a single token of >= 4 letters that is the first or last word of a
    short (2-3 word) name ("Alice" / "Alice Smith"); only used for two nodes
    of the same concrete type and only when exactly one candidate matches.
    """

    norm_a, norm_b = _normalize_name(name_a), _normalize_name(name_b)
    if not norm_a or not norm_b:
        return NAME_MATCH_NONE
    if norm_a == norm_b:
        return NAME_MATCH_STRONG
    core_a, core_b = _name_core(norm_a), _name_core(norm_b)
    if core_a and core_a == core_b and len(core_a) >= 2:
        return NAME_MATCH_STRONG
    if _acronym_of(name_a, norm_b) or _acronym_of(name_b, norm_a):
        return NAME_MATCH_STRONG
    if _HAS_CJK_RE.search(core_a) or _HAS_CJK_RE.search(core_b):
        return NAME_MATCH_NONE
    short, long_ = sorted((core_a, core_b), key=len)
    short_tokens, long_tokens = _name_tokens(short), _name_tokens(long_)
    if (
        len(short_tokens) == 1
        and len(short) >= 4
        and short.isalpha()
        and 2 <= len(long_tokens) <= 3
        and short in (long_tokens[0], long_tokens[-1])
    ):
        return NAME_MATCH_WEAK
    return NAME_MATCH_NONE


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

_EXTRACTION_SYSTEM_PROMPT = """Extract a knowledge graph from the text. Reply with JSON only:
{"entities":[{"name":"","type":"","summary":"","aliases":[],"attributes":{}}],
"relationships":[{"type":"","source":"","target":"","fact":"","valid_at":null,"invalid_at":null}]}
Rules: canonical full names, same name for the same entity; other names/abbreviations in the text go in "aliases" (omit if none).
Use the listed types ("Entity" if none fits) and only their attributes. summary: 1 sentence from the text.
fact: one self-contained sentence. valid_at/invalid_at: ISO date only if stated.
Every relationship endpoint must be an entity. Write in the text's language. Never invent facts."""


def _clip(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _ontology_prompt(ontology: Dict[str, Any]) -> str:
    """Compact one-line-per-type ontology description for the extraction prompt."""

    entity_types = ontology.get("entity_types") or {}
    edge_types = ontology.get("edge_types") or {}
    lines: List[str] = []
    if entity_types:
        lines.append("Entity types:")
        for name, spec in entity_types.items():
            attrs = ",".join((spec.get("attributes") or {}).keys())
            line = f"- {name}: {_clip(spec.get('description', ''), 140)}"
            if attrs:
                line += f" [{attrs}]"
            lines.append(line)
    if edge_types:
        lines.append("Relationship types:")
        for name, spec in edge_types.items():
            pairs = ",".join(
                f"{st.get('source')}->{st.get('target')}"
                for st in spec.get("source_targets") or []
            )
            line = f"- {name}: {_clip(spec.get('description', ''), 120)}"
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
CREATE TABLE IF NOT EXISTS embeddings (
    model TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    dim INTEGER NOT NULL,
    vector BLOB NOT NULL,
    PRIMARY KEY (model, text_hash)
);
CREATE TABLE IF NOT EXISTS extraction_cache (
    cache_key TEXT PRIMARY KEY,
    result TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

# Columns added after the first release; created on open for older databases.
_MIGRATIONS = (
    ("nodes", "aliases", "ALTER TABLE nodes ADD COLUMN aliases TEXT"),
)


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
            for table, column, ddl in _MIGRATIONS:
                columns = {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")}
                if column not in columns:
                    self.conn.execute(ddl)
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
        self._owner._on_graph_deleted(graph_id)
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
        else:
            self._owner._submit_embedding(episode_uuid)
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
        embedder: Any = None,
        entity_similarity: float = 0.9,
        min_similarity: float = 0.3,
        max_episode_chars: int = _DEFAULT_MAX_EPISODE_CHARS,
    ):
        """
        ``embedder``: object with ``model_name`` and ``embed(texts, query=False)``
        returning normalised vectors or ``None`` (see ``app.utils.embeddings``).
        ``None`` (the default for direct construction) means BM25-only search;
        ``get_local_zep_client()`` passes the configured fastembed embedder.
        """

        self.db_path = db_path
        self.extract_activity = extract_activity
        self.entity_similarity = float(entity_similarity)
        self.min_similarity = float(min_similarity)
        self.max_episode_chars = max(500, int(max_episode_chars))
        self.embedder = embedder
        self.stats: Counter[str] = Counter()
        self._store = _Store(db_path)
        self._llm_client = llm_client
        self._llm_lock = threading.Lock()
        self._vector_cache: Dict[str, np.ndarray] = {}
        self._query_cache: Dict[str, Optional[np.ndarray]] = {}
        self._vector_lock = threading.Lock()
        self._inflight: Dict[str, threading.Event] = {}
        self._inflight_lock = threading.Lock()
        self._pending_jobs = 0
        self._pending_lock = threading.Lock()
        # Post-merge document embeddings are batched across episodes by one
        # background thread (far fewer ONNX calls than one per episode).
        self._embed_backlog: List[str] = []
        self._embed_busy = False
        self._embed_cond = threading.Condition()
        self._closed = False
        self._embed_thread: Optional[threading.Thread] = None
        if self.embeddings_enabled:
            self._embed_thread = threading.Thread(
                target=self._embed_loop, name="local-graph-embed", daemon=True
            )
            self._embed_thread.start()
        # Daemon workers: an interrupted extraction is simply re-queued by
        # _resume_unprocessed() on the next start, so shutdown never blocks.
        self._queue: "queue.Queue[Optional[tuple[str, str, Optional[str]]]]" = queue.Queue()
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
        with self._embed_cond:
            self._closed = True
            self._embed_cond.notify_all()
        if self._embed_thread is not None:
            self._embed_thread.join(timeout)
        self._store.close()

    def _worker_loop(self) -> None:
        while True:
            job = self._queue.get()
            if job is None:
                return
            _kind, episode_uuid, batch_item_id = job
            try:
                self._process_episode_safely(episode_uuid, batch_item_id)
            except Exception:  # noqa: BLE001 - store may be closed during shutdown
                logger.exception("Local graph worker failed")
            finally:
                with self._pending_lock:
                    self._pending_jobs -= 1

    def wait_idle(self, timeout: float = 30.0) -> bool:
        """Block until every queued extraction/embedding job has finished."""

        import time

        deadline = time.time() + timeout
        while time.time() < deadline:
            pending = self._store.one(
                "SELECT COUNT(*) FROM episodes e "
                "LEFT JOIN batch_items bi ON bi.episode_uuid = e.uuid "
                "LEFT JOIN batches b ON b.batch_id = bi.batch_id "
                "WHERE e.processed = 0 AND (bi.item_id IS NULL OR b.status != 'draft')"
            )[0]
            with self._pending_lock:
                jobs = self._pending_jobs
            with self._embed_cond:
                embedding = bool(self._embed_backlog) or self._embed_busy
            if not pending and not jobs and not embedding:
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

    # -- embeddings ------------------------------------------------------

    @property
    def embeddings_enabled(self) -> bool:
        return self.embedder is not None and bool(getattr(self.embedder, "available", True))

    @property
    def _embed_model(self) -> str:
        return str(getattr(self.embedder, "model_name", "") or "default")

    def _remember_vectors(self, vectors: Dict[str, np.ndarray]) -> None:
        with self._vector_lock:
            if len(self._vector_cache) + len(vectors) > _VECTOR_CACHE_MAX:
                self._vector_cache.clear()
            self._vector_cache.update(vectors)

    def _vectors_for(self, texts: Sequence[str], *,
                     compute_limit: Optional[int] = None) -> List[Optional[np.ndarray]]:
        """Vectors for ``texts`` from memory, then SQLite, then the embedder.

        ``compute_limit`` caps how many missing vectors are computed now
        (``0`` = lookup only). Returns ``None`` entries for unavailable ones.
        """

        if not texts or not self.embeddings_enabled:
            return [None] * len(texts)
        clipped = [str(text or "").strip()[:_EMBED_TEXT_CHARS] for text in texts]
        hashes = [text_hash(text) if text else "" for text in clipped]
        found: Dict[str, np.ndarray] = {}
        with self._vector_lock:
            for digest in hashes:
                if digest and digest in self._vector_cache:
                    found[digest] = self._vector_cache[digest]
        missing = [d for d in dict.fromkeys(hashes) if d and d not in found]
        loaded: Dict[str, np.ndarray] = {}
        model = self._embed_model
        for start in range(0, len(missing), 500):
            chunk = missing[start:start + 500]
            rows = self._store.query(
                f"SELECT text_hash, vector FROM embeddings WHERE model = ? AND text_hash IN "
                f"({','.join('?' * len(chunk))})",
                [model, *chunk],
            )
            for row in rows:
                loaded[row["text_hash"]] = from_blob(row["vector"])
        found.update(loaded)

        pending: Dict[str, str] = {}
        for digest, text in zip(hashes, clipped):
            if digest and digest not in found and digest not in pending:
                pending[digest] = text
        todo = list(pending.items())
        if compute_limit is not None:
            todo = todo[:max(0, compute_limit)]
        computed: Dict[str, np.ndarray] = {}
        if todo:
            vectors = self.embedder.embed([text for _digest, text in todo])
            if vectors and len(vectors) == len(todo):
                for (digest, _text), vector in zip(todo, vectors):
                    computed[digest] = np.asarray(vector, dtype=np.float32)
                self.stats["embedded_texts"] += len(computed)
                with self._store.transaction() as store:
                    store.conn.executemany(
                        "INSERT OR REPLACE INTO embeddings(model, text_hash, dim, vector) VALUES (?, ?, ?, ?)",
                        [(model, d, int(v.shape[0]), to_blob(v)) for d, v in computed.items()],
                    )
        found.update(computed)
        self._remember_vectors({**loaded, **computed})
        return [found.get(digest) if digest else None for digest in hashes]

    def _query_vector(self, query: str) -> Optional[np.ndarray]:
        key = query.strip()
        with self._vector_lock:
            if key in self._query_cache:
                return self._query_cache[key]
        vectors = self.embedder.embed([key], query=True) if self.embeddings_enabled else None
        vector = np.asarray(vectors[0], dtype=np.float32) if vectors else None
        with self._vector_lock:
            if len(self._query_cache) > 2048:
                self._query_cache.clear()
            self._query_cache[key] = vector
        return vector

    @staticmethod
    def _node_text(name: str, summary: str) -> str:
        return f"{name}: {summary}" if summary else str(name)

    def _queue_embeddings(self, texts: Iterable[str]) -> None:
        texts = [t for t in texts if t and str(t).strip()]
        if not texts or self._embed_thread is None:
            return
        with self._embed_cond:
            self._embed_backlog.extend(texts)
            self._embed_cond.notify()

    def _embed_loop(self) -> None:
        while True:
            with self._embed_cond:
                while not self._embed_backlog and not self._closed:
                    self._embed_cond.wait()
                if self._closed:
                    return
                batch = list(dict.fromkeys(self._embed_backlog[:256]))
                del self._embed_backlog[:256]
                self._embed_busy = True
            try:
                self._vectors_for(batch)
            except Exception:  # noqa: BLE001 - store closed during shutdown, etc.
                logger.exception("Background embedding failed")
            finally:
                with self._embed_cond:
                    self._embed_busy = False

    def _embed_episode(self, episode_uuid: str) -> None:
        """Queue an unextracted (activity) episode and each of its lines."""

        if not self.embeddings_enabled:
            return
        row = self._store.one("SELECT content FROM episodes WHERE uuid = ?", (episode_uuid,))
        if row is None:
            return
        lines = [line.strip() for line in row["content"].splitlines() if line.strip()]
        self._queue_embeddings([row["content"], *lines])

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

    def _enqueue(self, kind: str, episode_uuid: str, batch_item_id: Optional[str] = None) -> None:
        with self._pending_lock:
            self._pending_jobs += 1
        self._queue.put((kind, episode_uuid, batch_item_id))

    def _submit_episode(self, episode_uuid: str, batch_item_id: Optional[str] = None) -> None:
        self._enqueue("extract", episode_uuid, batch_item_id)

    def _submit_embedding(self, episode_uuid: str) -> None:
        self._embed_episode(episode_uuid)

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
        extraction = self._extract_cached(row["content"], ontology)
        name_vectors = self._entity_name_vectors(extraction)
        touched = self._merge_extraction(graph_id, row, ontology, extraction, name_vectors)
        self._embed_touched(touched, row["content"])

    def _extraction_key(self, text: str, ontology: Dict[str, Any]) -> str:
        model = str(getattr(self.llm, "model", "") or "")
        payload = json.dumps(
            [_EXTRACTION_PROMPT_VERSION, model, ontology, text], ensure_ascii=False, sort_keys=True
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _extract_cached(self, text: str, ontology: Dict[str, Any]) -> Dict[str, Any]:
        """LLM extraction, reusing results for identical (text, ontology, model).

        Concurrent workers given the same chunk wait for the first one instead
        of paying for a second LLM call.
        """

        text = str(text or "")
        if len(text) > self.max_episode_chars:
            text = text[: self.max_episode_chars]
        key = self._extraction_key(text, ontology)
        while True:
            cached = self._store.one("SELECT result FROM extraction_cache WHERE cache_key = ?", (key,))
            if cached is not None:
                result = _json_load(cached["result"], None)
                if isinstance(result, dict):
                    self.stats["extraction_cache_hits"] += 1
                    return result
            with self._inflight_lock:
                event = self._inflight.get(key)
                owner = event is None
                if owner:
                    event = threading.Event()
                    self._inflight[key] = event
            if not owner:
                event.wait(timeout=900)
                continue
            try:
                result = self._extract(text, ontology)
                self._store.execute(
                    "INSERT OR REPLACE INTO extraction_cache(cache_key, result, created_at) VALUES (?, ?, ?)",
                    (key, json.dumps(result, ensure_ascii=False), _now()),
                )
                return result
            finally:
                with self._inflight_lock:
                    self._inflight.pop(key, None)
                event.set()

    def _extract(self, text: str, ontology: Dict[str, Any]) -> Dict[str, Any]:
        self.stats["llm_calls"] += 1
        messages = [
            {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"{_ontology_prompt(ontology)}\n\nText:\n<<<\n{text}\n>>>",
            },
        ]
        result = self.llm.chat_json(
            messages=messages,
            temperature=0.1,
            max_tokens=_EXTRACTION_MAX_TOKENS,
            max_attempts=_EXTRACTION_ATTEMPTS,
        )
        if not isinstance(result, dict):
            raise ValueError("extraction response must be a JSON object")
        return result

    def _entity_name_vectors(self, extraction: Dict[str, Any]) -> Dict[str, np.ndarray]:
        """Embed every entity / endpoint name of one extraction in one batch."""

        if not self.embeddings_enabled or not isinstance(extraction, dict):
            return {}
        names: List[str] = []
        for entity in extraction.get("entities") or []:
            if isinstance(entity, dict) and str(entity.get("name") or "").strip():
                names.append(str(entity["name"]).strip())
        for rel in extraction.get("relationships") or extraction.get("edges") or []:
            if isinstance(rel, dict):
                names.extend(str(rel.get(k) or "").strip() for k in ("source", "target"))
        names = [n for n in dict.fromkeys(names) if n]
        vectors = self._vectors_for(names)
        return {_normalize_name(n): v for n, v in zip(names, vectors) if v is not None}

    def _embed_touched(self, touched: Dict[str, Any], episode_text: str) -> None:
        if not self.embeddings_enabled:
            return
        texts = [episode_text]
        node_ids = sorted(touched.get("nodes") or ())
        for start in range(0, len(node_ids), 500):
            chunk = node_ids[start:start + 500]
            rows = self._store.query(
                f"SELECT name, summary FROM nodes WHERE uuid IN ({','.join('?' * len(chunk))})", chunk
            )
            texts.extend(self._node_text(r["name"], r["summary"]) for r in rows)
        texts.extend(touched.get("facts") or ())
        self._queue_embeddings(texts)

    # -- entity resolution ------------------------------------------------

    def _resolve_entity(self, known: List[Dict[str, Any]], name: str, label: str,
                        aliases: Sequence[str], name_vectors: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
        """Pick the existing node an extracted entity refers to (or ``None``).

        Order: exact name, declared alias, strong name variant, unique weak
        variant of the same concrete type, then same-type name-embedding
        cosine >= ``entity_similarity``. Ties prefer the same label, then the
        oldest node, so the result is deterministic for a given graph state.
        """

        norm = _normalize_name(name)
        alias_norms = {_normalize_name(a) for a in aliases or () if a} - {"", norm}

        def compatible(cand: Dict[str, Any]) -> bool:
            return cand["label"] == label or cand["label"] == "Entity" or label == "Entity"

        def best(cands: List[Dict[str, Any]]) -> Dict[str, Any]:
            return sorted(cands, key=lambda c: (c["label"] != label, c["seq"] or 0))[0]

        pool = [c for c in known if compatible(c)]
        exact = [c for c in pool if c["norm"] == norm]
        if exact:
            return best(exact)
        aliased = [c for c in pool if norm in c["aliases"] or c["norm"] in alias_norms]
        if aliased:
            return best(aliased)
        strong = [c for c in pool if name_match_strength(name, c["name"]) == NAME_MATCH_STRONG]
        if strong:
            return best(strong)
        if label == "Entity":
            return None
        same_type = [c for c in known if c["label"] == label]
        weak = [c for c in same_type if name_match_strength(name, c["name"]) == NAME_MATCH_WEAK]
        if len(weak) == 1:
            return weak[0]
        vector = name_vectors.get(norm)
        if vector is None or not same_type:
            return None
        missing = [c for c in same_type if c["norm"] not in name_vectors]
        if missing:
            looked_up = self._vectors_for([c["name"] for c in missing], compute_limit=0)
            for cand, cand_vector in zip(missing, looked_up):
                if cand_vector is not None:
                    name_vectors[cand["norm"]] = cand_vector
        scored = []
        for cand in same_type:
            cand_vector = name_vectors.get(cand["norm"])
            if cand_vector is None or cand_vector.shape != vector.shape:
                continue
            scored.append((float(cand_vector @ vector), cand))
        if not scored:
            return None
        score, cand = sorted(scored, key=lambda pair: (-pair[0], pair[1]["seq"] or 0))[0]
        return cand if score >= self.entity_similarity else None

    def _merge_extraction(self, graph_id: str, episode_row: sqlite3.Row,
                          ontology: Dict[str, Any], extraction: Dict[str, Any],
                          name_vectors: Optional[Dict[str, np.ndarray]] = None) -> Dict[str, Any]:
        entity_specs = ontology.get("entity_types") or {}
        edge_specs = ontology.get("edge_types") or {}
        type_lookup = {name.lower(): name for name in entity_specs}
        edge_lookup = {name.upper(): name for name in edge_specs}
        episode_uuid = episode_row["uuid"]
        episode_time = episode_row["created_at"]
        name_vectors = dict(name_vectors or {})
        touched: Dict[str, Any] = {"nodes": set(), "facts": []}

        raw_entities = extraction.get("entities") or []
        raw_edges = extraction.get("relationships") or extraction.get("edges") or []
        if not isinstance(raw_entities, list) or not isinstance(raw_edges, list):
            raise ValueError("extraction entities/relationships must be lists")

        with self._store.transaction() as store:
            conn = store.conn
            if conn.execute("SELECT 1 FROM graphs WHERE graph_id = ?", (graph_id,)).fetchone() is None:
                return touched  # deleted concurrently
            known: List[Dict[str, Any]] = [
                {
                    "uuid": r["uuid"], "name": r["name"], "norm": r["norm_name"], "label": r["label"],
                    "aliases": list(_json_load(r["aliases"], []) or []), "seq": r["seq"],
                }
                for r in conn.execute(
                    "SELECT uuid, name, norm_name, label, aliases, seq FROM nodes "
                    "WHERE graph_id = ? ORDER BY seq",
                    (graph_id,),
                )
            ]
            name_to_uuid: Dict[str, str] = {}

            def upsert_node(name: str, label: str, summary: str, attributes: Dict[str, Any],
                            aliases: Sequence[str] = ()) -> str:
                name = name.strip()
                norm = _normalize_name(name)
                match = self._resolve_entity(known, name, label, aliases, name_vectors)
                if match is None:
                    node_uuid = str(uuid.uuid4())
                    alias_list = sorted({_normalize_name(a) for a in aliases if a} - {"", norm})
                    seq = store.next_seq()
                    conn.execute(
                        "INSERT INTO nodes(uuid, graph_id, name, norm_name, label, summary, attributes, "
                        "created_at, seq, aliases) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (node_uuid, graph_id, name, norm, label, summary[:_MAX_SUMMARY_CHARS],
                         json.dumps(attributes, ensure_ascii=False), _now(), seq,
                         json.dumps(alias_list, ensure_ascii=False)),
                    )
                    known.append({"uuid": node_uuid, "name": name, "norm": norm, "label": label,
                                  "aliases": alias_list, "seq": seq})
                    touched["nodes"].add(node_uuid)
                    return node_uuid

                existing = conn.execute("SELECT * FROM nodes WHERE uuid = ?", (match["uuid"],)).fetchone()
                new_label = existing["label"]
                if new_label == "Entity" and label != "Entity":
                    # Upgrade a previously untyped node instead of duplicating it.
                    clash = conn.execute(
                        "SELECT 1 FROM nodes WHERE graph_id = ? AND norm_name = ? AND label = ?",
                        (graph_id, existing["norm_name"], label),
                    ).fetchone()
                    if clash is None:
                        new_label = label
                alias_set = set(match["aliases"])
                alias_set.update(_normalize_name(a) for a in [name, *aliases] if a)
                alias_set.discard(existing["norm_name"])
                alias_set.discard("")
                merged_summary = existing["summary"] or ""
                if summary and summary not in merged_summary:
                    merged_summary = f"{merged_summary} {summary}".strip() if merged_summary else summary
                    if len(merged_summary) > _MAX_SUMMARY_CHARS:
                        merged_summary = merged_summary[-_MAX_SUMMARY_CHARS:]
                merged_attrs = _json_load(existing["attributes"], {}) or {}
                merged_attrs.update({k: v for k, v in attributes.items() if v not in (None, "")})
                conn.execute(
                    "UPDATE nodes SET label = ?, summary = ?, attributes = ?, aliases = ? WHERE uuid = ?",
                    (new_label, merged_summary, json.dumps(merged_attrs, ensure_ascii=False),
                     json.dumps(sorted(alias_set), ensure_ascii=False), existing["uuid"]),
                )
                match["label"] = new_label
                match["aliases"] = sorted(alias_set)
                touched["nodes"].add(existing["uuid"])
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
                raw_aliases = entity.get("aliases") if isinstance(entity.get("aliases"), list) else []
                aliases = [str(a).strip() for a in raw_aliases if isinstance(a, str) and a.strip()][:10]
                summary = str(entity.get("summary") or "").strip()
                node_uuid = upsert_node(name, label, summary, attributes, aliases)
                name_to_uuid[_normalize_name(name)] = node_uuid
                for alias in aliases:
                    name_to_uuid.setdefault(_normalize_name(alias), node_uuid)

            def resolve(name: str) -> str:
                norm = _normalize_name(name)
                if norm not in name_to_uuid:
                    name_to_uuid[norm] = upsert_node(name, "Entity", "", {})
                return name_to_uuid[norm]

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
                touched["facts"].append(fact)

            conn.execute(
                "UPDATE episodes SET processed = 1, error = NULL WHERE uuid = ?", (episode_uuid,)
            )
        return touched

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

    def _on_graph_deleted(self, graph_id: str) -> None:
        """Hook for subclasses that mirror graphs elsewhere (Cognee)."""

    def _external_rankings(self, kind: str, graph_id: str, query: str,
                           rows: Sequence[Any], limit: int) -> List[List[int]]:
        """Extra best-first index rankings over ``rows`` fused into search.

        ``kind`` is ``"edges"``, ``"nodes"`` or ``"episodes"``. The local
        backend has none; ``CogneeZep`` adds Cognee's vector search here.
        """

        return []

    def _hybrid_rank(self, query: str, documents: Sequence[str], vector_texts: Sequence[str],
                     limit: int, extra: Optional[Sequence[Sequence[int]]] = None) -> List[tuple[int, float]]:
        """BM25 ranking fused with embedding cosine ranking (RRF).

        Without usable embeddings (and no ``extra`` rankings) this is exactly
        the BM25 ranking/scores.
        """

        keyword = bm25_rank(query, documents)
        semantic: List[tuple[int, float]] = []
        if self.embeddings_enabled and documents:
            query_vector = self._query_vector(query)
            if query_vector is not None:
                vectors = self._vectors_for(vector_texts, compute_limit=_SEARCH_BACKFILL_LIMIT)
                semantic = cosine_rank(
                    query_vector, vectors, min_score=self.min_similarity, top_k=max(limit * 4, 50)
                )
        extra = [list(r) for r in (extra or []) if r]
        if not semantic and not extra:
            return keyword[:limit]
        rankings = [[i for i, _ in keyword]]
        if semantic:
            rankings.append([i for i, _ in semantic])
        fused = reciprocal_rank_fusion(rankings + extra)
        return fused[:limit]

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
        vector_texts = [r["fact"] for r in rows]

        # Episodes stored without LLM extraction (simulation activity by
        # default) stay searchable as line-level pseudo-facts.
        line_edges: List[EntityEdge] = []
        if (not include or ACTIVITY_EDGE_NAME in include) and ACTIVITY_EDGE_NAME not in exclude:
            line_edges = self._unextracted_episode_lines(graph_id)
            documents.extend(edge.fact for edge in line_edges)
            vector_texts.extend(edge.fact for edge in line_edges)

        extra = self._external_rankings("edges", graph_id, query, rows, limit)
        results: List[EntityEdge] = []
        for index, score in self._hybrid_rank(query, documents, vector_texts, limit, extra):
            if index < len(rows):
                results.append(_edge_from_row(rows[index], score))
            else:
                edge = line_edges[index - len(rows)]
                results.append(edge.model_copy(update={"score": score, "relevance": score}))
        return results

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
        documents = [
            f"{r['name']} {r['name']} {' '.join(_json_load(r['aliases'], []) or [])} {r['label']} {r['summary']}"
            for r in rows
        ]
        vector_texts = [self._node_text(r["name"], r["summary"]) for r in rows]
        extra = self._external_rankings("nodes", graph_id, query, rows, limit)
        return [
            _node_from_row(rows[index], score)
            for index, score in self._hybrid_rank(query, documents, vector_texts, limit, extra)
        ]

    def _search_episodes(self, graph_id: str, query: str, limit: int) -> List[Episode]:
        rows = self._store.query("SELECT * FROM episodes WHERE graph_id = ? ORDER BY seq", (graph_id,))
        documents = [r["content"] for r in rows]
        extra = self._external_rankings("episodes", graph_id, query, rows, limit)
        return [
            _episode_from_row(rows[index], score)
            for index, score in self._hybrid_rank(query, documents, documents, limit, extra)
        ]


# --------------------------------------------------------------------------
# Process-wide instance
# --------------------------------------------------------------------------

_instances: Dict[str, LocalZep] = {}
_instances_lock = threading.Lock()


def get_local_zep_client(db_path: Optional[str] = None) -> LocalZep:
    """Return the process-shared ``LocalZep`` for ``db_path`` (or config)."""

    from ..config import Config
    from .embeddings import get_default_embedder

    path = db_path or Config.LOCAL_GRAPH_DB
    with _instances_lock:
        client = _instances.get(path)
        if client is None:
            client = LocalZep(
                path,
                extract_activity=Config.MEMORY_EXTRACT_ACTIVITY,
                max_workers=Config.LOCAL_GRAPH_EXTRACT_WORKERS,
                embedder=get_default_embedder(),
                entity_similarity=Config.MEMORY_ENTITY_SIMILARITY,
                min_similarity=Config.MEMORY_MIN_SIMILARITY,
                max_episode_chars=Config.LOCAL_GRAPH_MAX_EPISODE_CHARS,
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
