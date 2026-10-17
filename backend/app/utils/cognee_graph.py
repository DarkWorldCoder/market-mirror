"""Optional Cognee memory backend (``MEMORY_BACKEND=cognee``).

`Cognee <https://github.com/topoteretes/cognee>`_ (Apache-2.0) does the
knowledge extraction (``add`` + ``cognify``) and vector search. It cannot be
installed next to ``camel-ai==0.2.78`` (tiktoken/openai pins conflict), so it
runs as a small sidecar in its own virtualenv
(``backend/memory_sidecar/cognee_server.py``) and this module talks to it over
HTTP.

``CogneeZep`` subclasses ``LocalZep`` and reuses all of its bookkeeping
(graphs, ontology, episodes, batches, paging, ``NotFoundError``) plus its
hybrid BM25/embedding search. Episodes are batched into Cognee; after each
run the Cognee graph is read back and mirrored into the local SQLite tables as
``zep_cloud`` ``EntityNode`` / ``EntityEdge`` rows, so graph_builder,
zep_entity_reader, zep_tools and report_agent work unchanged. Search fuses
Cognee's own vector hits (entity names, document chunks) into the local
ranking with reciprocal rank fusion.
"""

from __future__ import annotations

import json
import queue
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

import httpx

from .local_graph import (
    LocalZep,
    _instances,
    _instances_lock,
    _normalize_edge_name,
    _normalize_name,
    _now,
    _ontology_prompt,
)
from .logger import get_logger

logger = get_logger("mirofish.cognee_graph")

_STRUCTURAL_EDGES = {"is_a", "contains", "made_from", "is_part_of", "belongs_to_set", "mentioned_in"}
_SEARCH_CACHE_SECONDS = 30.0


class CogneeSidecarError(RuntimeError):
    pass


class CogneeSidecarClient:
    """Minimal JSON client for ``memory_sidecar/cognee_server.py``."""

    def __init__(self, base_url: str, timeout: float = 900.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _post(self, path: str, payload: Dict[str, Any], timeout: Optional[float] = None) -> Dict[str, Any]:
        try:
            response = httpx.post(f"{self.base_url}{path}", json=payload, timeout=timeout or self.timeout)
        except httpx.HTTPError as error:
            raise CogneeSidecarError(
                f"Cognee sidecar unreachable at {self.base_url} ({error}). "
                "Start it with backend/memory_sidecar/cognee_sidecar.sh start"
            ) from error
        try:
            body = response.json()
        except ValueError:
            body = {"error": response.text[:500]}
        if response.status_code >= 400:
            raise CogneeSidecarError(f"Cognee sidecar {path} failed: {body.get('error') or response.status_code}")
        return body

    def health(self) -> Dict[str, Any]:
        try:
            return httpx.get(f"{self.base_url}/health", timeout=5).json()
        except Exception as error:  # noqa: BLE001
            raise CogneeSidecarError(f"Cognee sidecar unreachable at {self.base_url}: {error}") from error

    def ingest(self, dataset: str, texts: List[str], custom_prompt: Optional[str] = None) -> Dict[str, Any]:
        return self._post("/ingest", {"dataset": dataset, "texts": texts, "custom_prompt": custom_prompt})["graph"]

    def graph(self, dataset: str) -> Dict[str, Any]:
        return self._post("/graph", {"dataset": dataset})

    def search(self, dataset: str, query: str, limit: int = 10,
               collections: Sequence[str] = ("Entity_name", "DocumentChunk_text")) -> Dict[str, Any]:
        return self._post(
            "/search", {"dataset": dataset, "query": query, "limit": limit, "collections": list(collections)},
            timeout=60,
        ).get("results") or {}

    def delete(self, dataset: str) -> None:
        self._post("/delete", {"dataset": dataset}, timeout=120)


def dataset_name(graph_id: str) -> str:
    return "mirofish_" + re.sub(r"[^0-9A-Za-z_]+", "_", str(graph_id))


def cognee_prompt(ontology: Dict[str, Any]) -> str:
    """Cognee ``custom_prompt`` carrying the MiroFish ontology."""

    return (
        "You are a knowledge-graph extraction engine. Extract the entities (nodes) and "
        "relationships (edges) the text states.\n"
        f"{_ontology_prompt(ontology)}\n"
        "Rules: node type must be one of the entity types above (closest fit). Node id/name: the "
        "canonical full name as written in the text. Node description: one sentence from the text. "
        "Edge relationship_name: one of the relationship types above in snake_case when it applies. "
        "Edge description: one self-contained fact sentence using the endpoint names. "
        "Write in the text's language. Never invent facts."
    )


def _iso(value: Any) -> Optional[str]:
    if isinstance(value, (int, float)) and value > 0:
        seconds = value / 1000.0 if value > 1e11 else float(value)
        return datetime.fromtimestamp(seconds, timezone.utc).isoformat()
    if isinstance(value, str) and value:
        return value
    return None


def _type_key(name: str) -> str:
    return re.sub(r"[^0-9a-z一-鿿]+", "", str(name or "").lower())


class CogneeZep(LocalZep):
    """``LocalZep`` whose extraction and vector search are done by Cognee."""

    def __init__(self, db_path: str, *, sidecar: Optional[CogneeSidecarClient] = None,
                 ingest_batch_size: int = 20, **kwargs: Any):
        from ..config import Config

        self.sidecar = sidecar or CogneeSidecarClient(Config.COGNEE_SIDECAR_URL, Config.COGNEE_SIDECAR_TIMEOUT)
        self.ingest_batch_size = max(1, int(ingest_batch_size))
        self._search_cache: Dict[tuple, tuple[float, Dict[str, Any]]] = {}
        self._search_warned = False
        # One worker: Cognee serialises a dataset's pipeline anyway, and
        # batching several episodes per cognify run is much cheaper.
        kwargs["max_workers"] = 1
        kwargs.setdefault("llm_client", object())  # extraction never uses the local LLM
        super().__init__(db_path, **kwargs)

    # -- ingestion -------------------------------------------------------

    def _worker_loop(self) -> None:
        while True:
            job = self._queue.get()
            if job is None:
                return
            jobs = [job]
            stop = False
            while len(jobs) < self.ingest_batch_size:
                try:
                    nxt = self._queue.get_nowait()
                except queue.Empty:
                    break
                if nxt is None:
                    stop = True
                    break
                jobs.append(nxt)
            try:
                self._process_jobs([(episode_uuid, item_id) for _kind, episode_uuid, item_id in jobs])
            except Exception:  # noqa: BLE001 - store may be closed during shutdown
                logger.exception("Cognee ingestion worker failed")
            finally:
                with self._pending_lock:
                    self._pending_jobs -= len(jobs)
            if stop:
                return

    def process_episode(self, episode_uuid: str) -> None:
        """Synchronously ingest one episode (tests / scripts)."""

        self._process_jobs([(episode_uuid, None)], raise_errors=True)

    def _process_jobs(self, jobs: Sequence[tuple[str, Optional[str]]], raise_errors: bool = False) -> None:
        by_graph: Dict[str, List[tuple[Any, Optional[str]]]] = {}
        for episode_uuid, item_id in jobs:
            row = self._store.one("SELECT * FROM episodes WHERE uuid = ?", (episode_uuid,))
            if row is None or row["processed"]:
                self._set_item_status(item_id, "succeeded" if row is not None else "canceled")
                continue
            by_graph.setdefault(row["graph_id"], []).append((row, item_id))

        for graph_id, entries in by_graph.items():
            for _row, item_id in entries:
                self._set_item_status(item_id, "processing")
            ontology = self._ontology(graph_id)
            texts = list(dict.fromkeys(row["content"][: self.max_episode_chars] for row, _ in entries))
            try:
                snapshot = self.sidecar.ingest(dataset_name(graph_id), texts, cognee_prompt(ontology))
                touched = self._sync_snapshot(graph_id, snapshot, ontology)
            except Exception as error:  # noqa: BLE001 - recorded per episode / item
                logger.error("Cognee ingestion failed for graph %s: %s", graph_id, error)
                for row, item_id in entries:
                    self._store.execute(
                        "UPDATE episodes SET processed = 1, error = ? WHERE uuid = ?",
                        (str(error)[:2000], row["uuid"]),
                    )
                    self._set_item_status(
                        item_id, "failed", {"message": str(error)[:2000], "type": type(error).__name__}
                    )
                if raise_errors:
                    raise
                continue
            for row, item_id in entries:
                self._store.execute("UPDATE episodes SET processed = 1, error = NULL WHERE uuid = ?", (row["uuid"],))
                self._set_item_status(item_id, "succeeded")
            self._embed_touched(touched, "\n".join(texts))
        self._search_cache.clear()

    def resync(self, graph_id: str) -> None:
        """Re-read the Cognee graph for ``graph_id`` into the local mirror."""

        self._require_graph(graph_id)
        self._sync_snapshot(graph_id, self.sidecar.graph(dataset_name(graph_id)), self._ontology(graph_id))

    # -- Cognee graph -> zep_cloud shapes ---------------------------------

    def _sync_snapshot(self, graph_id: str, snapshot: Dict[str, Any], ontology: Dict[str, Any]) -> Dict[str, Any]:
        nodes = {str(n.get("id")): n for n in snapshot.get("nodes") or [] if n.get("id")}
        edges = [e for e in snapshot.get("edges") or [] if e.get("source") and e.get("target")]
        entity_ids = [nid for nid, n in nodes.items() if n.get("type") == "Entity"]
        entity_set = set(entity_ids)

        entity_types = ontology.get("entity_types") or {}
        edge_types = ontology.get("edge_types") or {}
        type_lookup = {_type_key(name): name for name in entity_types}
        edge_lookup = {name.upper(): name for name in edge_types}

        episodes = self._store.query(
            "SELECT uuid, content FROM episodes WHERE graph_id = ? ORDER BY seq", (graph_id,)
        )

        def episode_for_chunk(text: str) -> Optional[str]:
            text = (text or "").strip()
            if not text:
                return None
            for row in episodes:
                content = row["content"].strip()
                if text == content or text in content or (len(content) > 20 and content in text):
                    return row["uuid"]
            return None

        chunk_episode = {
            nid: episode_for_chunk((n.get("properties") or {}).get("text") or "")
            for nid, n in nodes.items() if n.get("type") == "DocumentChunk"
        }
        labels: Dict[str, str] = {}
        entity_episodes: Dict[str, List[str]] = {nid: [] for nid in entity_ids}
        relations = []
        for edge in edges:
            src, tgt = str(edge["source"]), str(edge["target"])
            rel = str(edge.get("relationship_name") or "")
            if rel == "is_a" and src in entity_set and tgt in nodes:
                labels[src] = type_lookup.get(_type_key(nodes[tgt].get("name")), "Entity")
            elif rel == "contains" and tgt in entity_set and chunk_episode.get(src):
                if chunk_episode[src] not in entity_episodes[tgt]:
                    entity_episodes[tgt].append(chunk_episode[src])
            elif src in entity_set and tgt in entity_set and rel not in _STRUCTURAL_EDGES:
                relations.append(edge)

        episode_text = {row["uuid"]: row["content"] for row in episodes}

        def display_name(nid: str) -> str:
            # Cognee lower-cases names; recover the casing used in the text.
            name = str(nodes[nid].get("name") or "").strip()
            for episode_uuid in entity_episodes.get(nid) or list(episode_text):
                match = re.search(re.escape(name), episode_text.get(episode_uuid, ""), re.IGNORECASE)
                if match:
                    return match.group(0)
            return name

        touched: Dict[str, Any] = {"nodes": set(), "facts": []}
        with self._store.transaction() as store:
            conn = store.conn
            if conn.execute("SELECT 1 FROM graphs WHERE graph_id = ?", (graph_id,)).fetchone() is None:
                return touched
            old_nodes = {r["uuid"]: r for r in conn.execute(
                "SELECT uuid, seq, created_at, summary FROM nodes WHERE graph_id = ?", (graph_id,))}
            old_edges = {r["uuid"]: r for r in conn.execute(
                "SELECT uuid, seq, created_at FROM edges WHERE graph_id = ?", (graph_id,))}
            conn.execute("DELETE FROM edges WHERE graph_id = ?", (graph_id,))
            conn.execute("DELETE FROM nodes WHERE graph_id = ?", (graph_id,))

            identity: Dict[tuple, str] = {}
            node_uuid: Dict[str, str] = {}
            def order(nid: str) -> tuple:
                created = (nodes[nid].get("properties") or {}).get("created_at")
                created = created if isinstance(created, (int, float)) else 0
                return (old_nodes[nid]["seq"] if nid in old_nodes else 10**18, created, nid)

            for nid in sorted(entity_ids, key=order):
                node = nodes[nid]
                name = display_name(nid) or nid
                label = labels.get(nid, "Entity")
                key = (_normalize_name(name), label)
                if key in identity:
                    node_uuid[nid] = identity[key]
                    continue
                props = node.get("properties") or {}
                summary = str(props.get("description") or "")
                previous = old_nodes.get(nid)
                conn.execute(
                    "INSERT INTO nodes(uuid, graph_id, name, norm_name, label, summary, attributes, "
                    "created_at, seq, aliases) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (nid, graph_id, name, key[0], label, summary, json.dumps({}),
                     (previous["created_at"] if previous else None) or _iso(props.get("created_at")) or _now(),
                     previous["seq"] if previous else store.next_seq(), json.dumps([])),
                )
                identity[key] = nid
                node_uuid[nid] = nid
                if previous is None or previous["summary"] != summary:
                    touched["nodes"].add(nid)

            seen_edges = set()
            for edge in relations:
                src, tgt = node_uuid.get(str(edge["source"])), node_uuid.get(str(edge["target"]))
                if not src or not tgt:
                    continue
                props = edge.get("properties") or {}
                rel = str(edge.get("relationship_name") or "related_to")
                name = _normalize_edge_name(rel)
                name = edge_lookup.get(name, name)
                edge_id = str(props.get("edge_object_id") or uuid.uuid5(uuid.NAMESPACE_URL, f"{src}|{rel}|{tgt}"))
                if edge_id in seen_edges:
                    continue
                seen_edges.add(edge_id)
                fact = str(props.get("edge_text") or props.get("description") or "").strip()
                if not fact:
                    fact = f"{display_name(str(edge['source']))} {rel.replace('_', ' ')} {display_name(str(edge['target']))}"
                src_eps = entity_episodes.get(str(edge["source"])) or []
                tgt_eps = entity_episodes.get(str(edge["target"])) or []
                linked = [e for e in src_eps if e in tgt_eps] or list(dict.fromkeys(src_eps + tgt_eps))
                previous = old_edges.get(edge_id)
                created = (previous["created_at"] if previous else None) or _iso(props.get("updated_at")) or _now()
                conn.execute(
                    "INSERT INTO edges(uuid, graph_id, name, fact, source_node_uuid, target_node_uuid, "
                    "attributes, episodes, created_at, valid_at, invalid_at, expired_at, seq) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?)",
                    (edge_id, graph_id, name, fact, src, tgt, json.dumps({}), json.dumps(linked),
                     created, created, previous["seq"] if previous else store.next_seq()),
                )
                if previous is None:
                    touched["facts"].append(fact)
        return touched

    # -- search / lifecycle ------------------------------------------------

    def _cognee_hits(self, graph_id: str, query: str, limit: int) -> Dict[str, Any]:
        key = (graph_id, query, limit)
        cached = self._search_cache.get(key)
        if cached and time.time() - cached[0] < _SEARCH_CACHE_SECONDS:
            return cached[1]
        try:
            hits = self.sidecar.search(dataset_name(graph_id), query, limit=max(limit * 2, 10))
            self._search_warned = False
        except Exception as error:  # noqa: BLE001 - search degrades to the local ranking
            if not self._search_warned:
                logger.warning("Cognee search unavailable, using local ranking only: %s", error)
                self._search_warned = True
            hits = {}
        if len(self._search_cache) > 256:
            self._search_cache.clear()
        self._search_cache[key] = (time.time(), hits)
        return hits

    def _external_rankings(self, kind: str, graph_id: str, query: str,
                           rows: Sequence[Any], limit: int) -> List[List[int]]:
        if not rows:
            return []
        hits = self._cognee_hits(graph_id, query, limit)
        entity_rank: Dict[str, int] = {}
        for hit in hits.get("Entity_name") or []:
            entity_rank.setdefault(str(hit.get("id")), len(entity_rank))
        if kind == "nodes":
            index = {row["uuid"]: i for i, row in enumerate(rows)}
            return [[index[nid] for nid in entity_rank if nid in index]]
        if kind == "edges":
            ranked = []
            for i, row in enumerate(rows):
                best = min(
                    entity_rank.get(row["source_node_uuid"], 10**9),
                    entity_rank.get(row["target_node_uuid"], 10**9),
                )
                if best < 10**9:
                    ranked.append((best, row["seq"] or 0, i))
            return [[i for _best, _seq, i in sorted(ranked)]]
        if kind == "episodes":
            order: List[int] = []
            for hit in hits.get("DocumentChunk_text") or []:
                text = str(hit.get("text") or "").strip()
                for i, row in enumerate(rows):
                    content = row["content"].strip()
                    if text and (text in content or content in text) and i not in order:
                        order.append(i)
                        break
            return [order]
        return []

    def _on_graph_deleted(self, graph_id: str) -> None:
        try:
            self.sidecar.delete(dataset_name(graph_id))
        except Exception as error:  # noqa: BLE001 - local delete already succeeded
            logger.warning("Could not delete Cognee dataset for %s: %s", graph_id, error)


def get_cognee_zep_client(db_path: Optional[str] = None) -> CogneeZep:
    """Process-shared ``CogneeZep`` (registered with the local client cache)."""

    from ..config import Config
    from .embeddings import get_default_embedder

    path = db_path or Config.COGNEE_GRAPH_DB
    key = f"cognee::{path}"
    with _instances_lock:
        client = _instances.get(key)
        if client is None:
            client = CogneeZep(
                path,
                ingest_batch_size=Config.COGNEE_INGEST_BATCH,
                extract_activity=Config.MEMORY_EXTRACT_ACTIVITY,
                embedder=get_default_embedder(),
                min_similarity=Config.MEMORY_MIN_SIMILARITY,
                max_episode_chars=Config.LOCAL_GRAPH_MAX_EPISODE_CHARS,
            )
            _instances[key] = client
        return client  # type: ignore[return-value]


__all__ = [
    "CogneeSidecarClient",
    "CogneeSidecarError",
    "CogneeZep",
    "cognee_prompt",
    "dataset_name",
    "get_cognee_zep_client",
]
