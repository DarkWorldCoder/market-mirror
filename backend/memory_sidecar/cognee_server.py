"""Tiny HTTP/JSON sidecar that runs Cognee (https://github.com/topoteretes/cognee).

Why a sidecar: every Cognee release that exists today needs ``tiktoken>=0.8``
and ``openai>=2``, while ``camel-ai==0.2.78`` (pinned by ``camel-oasis==0.2.5``,
the simulation engine) needs ``tiktoken<0.8`` and ``openai<2``. The two cannot
share one virtualenv, so Cognee runs in ``backend/memory_sidecar/.venv`` and the
backend talks to it over localhost (``app/utils/cognee_graph.py``).

Run ``backend/memory_sidecar/cognee_sidecar.sh setup`` once, then
``cognee_sidecar.sh start``. Only the stdlib, ``cognee`` and its dependencies
are used here.

Configuration (environment, MiroFish's ``.env`` is read for defaults):

* LLM: MiroFish ``LLM_PROVIDER=claude`` (default) maps to Cognee
  ``LLM_PROVIDER=anthropic`` with ``LLM_MODEL_NAME`` / ``LLM_API_KEY`` (or
  ``ANTHROPIC_API_KEY``). Any other provider maps to Cognee's OpenAI-compatible
  ``custom`` provider with ``LLM_BASE_URL``. ``COGNEE_LLM_*`` overrides each.
* Embeddings: local fastembed, ``MEMORY_EMBED_MODEL`` (default
  ``sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2``, 384 dims).
* Storage: SQLite (relational) + LanceDB (vectors) + Ladybug/Kuzu (graph)
  under ``COGNEE_DATA_DIR`` (default ``backend/uploads/cognee``).
* ``COGNEE_SIDECAR_HOST`` / ``COGNEE_SIDECAR_PORT`` (default 127.0.0.1:8765).

API (POST bodies and responses are JSON):

* ``GET  /health``  -> ``{"ok": true, "cognee": "<version>"}``
* ``POST /ingest``  ``{"dataset", "texts": [str], "custom_prompt"?}`` -> ``{"graph": snapshot}``
* ``POST /graph``   ``{"dataset"}`` -> snapshot
* ``POST /search``  ``{"dataset", "query", "limit"?, "collections"?}`` ->
  ``{"results": {collection: [{"id", "score", "text"}]}}`` (score: higher is better)
* ``POST /delete``  ``{"dataset"}`` -> ``{"ok": true}``

``snapshot = {"nodes": [{"id", "name", "type", "properties"}],
"edges": [{"source", "target", "relationship_name", "properties"}]}``
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
REPO = BACKEND.parent
DEFAULT_EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBED_DIMENSIONS = {
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2": 384,
    "BAAI/bge-small-en-v1.5": 384,
    "intfloat/multilingual-e5-large": 1024,
    "sentence-transformers/paraphrase-multilingual-mpnet-base-v2": 768,
}


def _read_dotenv(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.split(" #", 1)[0].strip().strip('"').strip("'")
        values[key.strip()] = value
    return values


def configure_environment(env: Dict[str, str] | None = None) -> Dict[str, str]:
    """Translate MiroFish settings into the env vars Cognee reads.

    Must run before ``import cognee``. Returns the Cognee-facing settings
    (without secrets) for logging/tests.
    """

    env = os.environ if env is None else env
    mirofish = {**_read_dotenv(REPO / ".env"), **{k: v for k, v in env.items()}}

    def pick(name: str, default: str = "") -> str:
        return (mirofish.get(name) or default).strip()

    provider = pick("LLM_PROVIDER", "claude").lower()
    api_key = pick("COGNEE_LLM_API_KEY") or pick("LLM_API_KEY") or (
        pick("ANTHROPIC_API_KEY") if provider == "claude" else ""
    )
    if provider == "claude":
        cognee_provider = pick("COGNEE_LLM_PROVIDER", "anthropic")
        model = pick("COGNEE_LLM_MODEL") or pick("LLM_MODEL_NAME", "claude-haiku-4-5")
        endpoint = pick("COGNEE_LLM_ENDPOINT")
    else:
        cognee_provider = pick("COGNEE_LLM_PROVIDER", "custom")
        model = pick("COGNEE_LLM_MODEL") or f"openai/{pick('LLM_MODEL_NAME', 'gpt-4o-mini')}"
        endpoint = pick("COGNEE_LLM_ENDPOINT") or pick("LLM_BASE_URL", "https://api.openai.com/v1")
    embed_model = pick("COGNEE_EMBED_MODEL") or pick("MEMORY_EMBED_MODEL", DEFAULT_EMBED_MODEL)
    data_dir = Path(pick("COGNEE_DATA_DIR") or str(BACKEND / "uploads" / "cognee")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    # Stop Cognee from walking up to MiroFish's .env (its LLM_PROVIDER=claude
    # means something else to Cognee): point it at an empty file instead.
    empty_env = data_dir / "cognee.env"
    if not empty_env.exists():
        empty_env.write_text("# intentionally empty; see memory_sidecar/cognee_server.py\n")

    settings = {
        "COGNEE_ENV_FILE": str(empty_env),
        "LLM_PROVIDER": cognee_provider,
        "LLM_MODEL": model,
        "EMBEDDING_PROVIDER": "fastembed",
        "EMBEDDING_MODEL": embed_model,
        "EMBEDDING_DIMENSIONS": str(EMBED_DIMENSIONS.get(embed_model, 384)),
        "EMBEDDING_MAX_COMPLETION_TOKENS": "512",
        "SYSTEM_ROOT_DIRECTORY": str(data_dir / "system"),
        "DATA_ROOT_DIRECTORY": str(data_dir / "data"),
        "DB_PROVIDER": "sqlite",
        "VECTOR_DB_PROVIDER": "lancedb",
        "GRAPH_DATABASE_PROVIDER": pick("COGNEE_GRAPH_DATABASE_PROVIDER", "ladybug"),
        "TELEMETRY_DISABLED": "1",
        "ENV": "local",
        "LOG_LEVEL": pick("COGNEE_LOG_LEVEL", "WARNING"),
    }
    if endpoint:
        settings["LLM_ENDPOINT"] = endpoint
    if pick("COGNEE_USE_S3").lower() not in {"1", "true", "yes"}:
        # Ambient AWS credentials make Cognee switch ingestion to S3 (needs s3fs).
        for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
            os.environ.pop(name, None)
    os.environ.update(settings)
    if api_key:
        os.environ["LLM_API_KEY"] = api_key
    else:
        os.environ.pop("LLM_API_KEY", None)
    return settings


# --------------------------------------------------------------------------
# Cognee operations (run on one asyncio loop)
# --------------------------------------------------------------------------


class CogneeService:
    def __init__(self):
        import cognee  # noqa: WPS433 - imported after configure_environment()

        self.cognee = cognee
        self.loop = asyncio.new_event_loop()
        self._locks: Dict[str, asyncio.Lock] = {}
        thread = threading.Thread(target=self.loop.run_forever, name="cognee-loop", daemon=True)
        thread.start()
        self.run(self._setup())

    @staticmethod
    async def _setup() -> None:
        """Create Cognee's relational tables and default user (idempotent)."""

        from cognee.modules.engine.operations.setup import setup

        await setup()

    def run(self, coro, timeout: float | None = None):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    def _lock(self, dataset: str) -> asyncio.Lock:
        if dataset not in self._locks:
            self._locks[dataset] = asyncio.Lock()
        return self._locks[dataset]

    async def _user(self):
        from cognee.modules.users.methods import get_default_user

        return await get_default_user()

    async def _dataset(self, dataset: str):
        """Return the existing dataset object for ``dataset`` (or ``None``)."""

        user = await self._user()
        for candidate in await self.cognee.datasets.list_datasets(user=user) or []:
            if getattr(candidate, "name", None) == dataset:
                return candidate
        return None

    async def ingest(self, dataset: str, texts: List[str], custom_prompt: str | None) -> Dict[str, Any]:
        async with self._lock(dataset):
            await self.cognee.add(texts, dataset_name=dataset)
            kwargs: Dict[str, Any] = {"datasets": [dataset]}
            if custom_prompt:
                kwargs["custom_prompt"] = custom_prompt
            await self.cognee.cognify(**kwargs)
            return await self._snapshot(dataset)

    async def snapshot(self, dataset: str) -> Dict[str, Any]:
        async with self._lock(dataset):
            return await self._snapshot(dataset)

    async def _snapshot(self, dataset: str) -> Dict[str, Any]:
        from cognee.context_global_variables import set_database_global_context_variables
        from cognee.infrastructure.databases.graph import get_graph_engine

        found = await self._dataset(dataset)
        if found is None:
            return {"nodes": [], "edges": []}
        async with set_database_global_context_variables(found.id, found.owner_id):
            engine = await get_graph_engine()
            nodes, edges = await engine.get_graph_data()
        return {
            "nodes": [
                {"id": str(node_id), "name": props.get("name") or "", "type": props.get("type") or "",
                 "properties": _jsonable({k: v for k, v in props.items() if k not in {"name", "type"}})}
                for node_id, props in nodes
            ],
            "edges": [
                {"source": str(edge[0]), "target": str(edge[1]), "relationship_name": str(edge[2]),
                 "properties": _jsonable(edge[3] if len(edge) > 3 and isinstance(edge[3], dict) else {})}
                for edge in edges
            ],
        }

    async def search(self, dataset: str, query: str, limit: int, collections: List[str]) -> Dict[str, Any]:
        from cognee.context_global_variables import set_database_global_context_variables
        from cognee.infrastructure.databases.vector import get_vector_engine

        found = await self._dataset(dataset)
        results: Dict[str, List[Dict[str, Any]]] = {name: [] for name in collections}
        if found is None:
            return {"results": results}
        async with set_database_global_context_variables(found.id, found.owner_id):
            engine = get_vector_engine()
            for collection in collections:
                try:
                    hits = await engine.search(collection, query, limit=limit, include_payload=True)
                except Exception as error:  # noqa: BLE001 - collection missing on empty datasets
                    results[collection] = []
                    print(f"[cognee-sidecar] search {collection} failed: {error}", file=sys.stderr)
                    continue
                for hit in hits or []:
                    payload = getattr(hit, "payload", None) or {}
                    distance = float(getattr(hit, "score", 0.0) or 0.0)
                    results[collection].append({
                        "id": str(getattr(hit, "id", "")),
                        # Cognee scores are distances (lower = closer).
                        "score": 1.0 - distance,
                        "text": payload.get("text") or payload.get("name") or "",
                    })
        return {"results": results}

    async def delete(self, dataset: str) -> Dict[str, Any]:
        async with self._lock(dataset):
            found = await self._dataset(dataset)
            if found is not None:
                await self.cognee.datasets.empty_dataset(found.id)
        return {"ok": True}


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------


def make_handler(service: CogneeService):
    class Handler(BaseHTTPRequestHandler):
        server_version = "MiroFishCogneeSidecar/1"

        def log_message(self, fmt, *args):  # quieter default logging
            sys.stderr.write("[cognee-sidecar] " + (fmt % args) + "\n")

        def _send(self, status: int, payload: Dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            if self.path.rstrip("/") == "/health":
                self._send(200, {"ok": True, "cognee": getattr(service.cognee, "__version__", "?")})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):  # noqa: N802
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                dataset = str(body.get("dataset") or "").strip()
                route = self.path.rstrip("/")
                if not dataset:
                    return self._send(400, {"error": "dataset is required"})
                if route == "/ingest":
                    texts = [str(t) for t in body.get("texts") or [] if str(t).strip()]
                    if not texts:
                        return self._send(400, {"error": "texts must be a non-empty list"})
                    graph = service.run(service.ingest(dataset, texts, body.get("custom_prompt")))
                    return self._send(200, {"graph": graph})
                if route == "/graph":
                    return self._send(200, service.run(service.snapshot(dataset)))
                if route == "/search":
                    collections = body.get("collections") or ["Entity_name", "DocumentChunk_text"]
                    result = service.run(service.search(
                        dataset, str(body.get("query") or ""), int(body.get("limit") or 10), list(collections)
                    ))
                    return self._send(200, result)
                if route == "/delete":
                    return self._send(200, service.run(service.delete(dataset)))
                return self._send(404, {"error": "not found"})
            except Exception as error:  # noqa: BLE001 - report to the client
                traceback.print_exc()
                return self._send(500, {"error": f"{type(error).__name__}: {error}"})

    return Handler


def main() -> None:
    settings = configure_environment()
    host = os.environ.get("COGNEE_SIDECAR_HOST", "127.0.0.1")
    port = int(os.environ.get("COGNEE_SIDECAR_PORT", "8765"))
    service = CogneeService()
    print(
        f"[cognee-sidecar] cognee {getattr(service.cognee, '__version__', '?')} on http://{host}:{port} "
        f"(llm={settings['LLM_PROVIDER']}:{settings['LLM_MODEL']}, embeddings={settings['EMBEDDING_MODEL']})",
        file=sys.stderr, flush=True,
    )
    ThreadingHTTPServer((host, port), make_handler(service)).serve_forever()


if __name__ == "__main__":
    main()
