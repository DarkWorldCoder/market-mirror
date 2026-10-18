#!/usr/bin/env python3
"""Write docs/API.md and docs/openapi.json from backend/app/api/registry.py.  Run: python backend/scripts/gen_api_docs.py"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from app.api.registry import ENDPOINTS, TAGS  # noqa: E402

INTRO = """# MarketMirror API

The backend is a Flask app on `http://localhost:5001` (start it with `backend/claude_cli/start_server.sh`). Every response is
`{"success": true, "data": ...}` or `{"success": false, "error": "..."}`. Long jobs return a `task_id`; poll
`POST /api/simulation/market-task/status` until `status` is `completed` or `failed`, then `GET` the result. The upstream
engine routes (projects, ontology, graph build, simulations, start/stop, interviews, reports) are documented in
`docs/MIROFISH-UPSTREAM.md`; the `mirofish.py` CLI and the MCP server wrap all of them.

Authentication: none by default (the backend binds to localhost). Put it behind your own auth or network rules before exposing it.
Webhooks: set `MIROFISH_WEBHOOK_URL` (or `"webhook"` in `market_test.json`) and the CLI posts a JSON summary when a run, study
or test finishes. SDK: `pip install -e sdk` then `from marketmirror import MarketMirror`. Machine-readable: `docs/openapi.json`.

"""


def md() -> str:
    out = [INTRO]
    for tag, title in TAGS.items():
        rows = [e for e in ENDPOINTS if e["tag"] == tag]
        if not rows:
            continue
        out.append(f"## {title}\n")
        for e in rows:
            out.append(f"### `{e['method']} {e['path']}`\n\n{e['summary']}.\n")
            if e.get("body"):
                out.append("Request body:\n\n```json\n" + json.dumps(e["body"], ensure_ascii=False, indent=2) + "\n```\n")
            out.append(f"Returns: {e.get('returns', 'data')}\n")
    return "\n".join(out)


def openapi() -> dict:
    paths = {}
    for e in ENDPOINTS:
        p = paths.setdefault(e["path"], {})
        op = {"summary": e["summary"], "tags": [TAGS.get(e["tag"], e["tag"])],
              "responses": {"200": {"description": e.get("returns", "data"), "content": {"application/json": {"schema": {"type": "object"}}}},
                            "400": {"description": "bad request"}, "404": {"description": "not found"}}}
        params = [{"name": seg.strip("{}"), "in": "path", "required": True, "schema": {"type": "string"}} for seg in e["path"].split("/") if seg.startswith("{")]
        if params:
            op["parameters"] = params
        if e.get("body"):
            op["requestBody"] = {"required": True, "content": {"application/json": {"schema": {"type": "object"}, "example": e["body"]}}}
        p[e["method"].lower()] = op
    return {"openapi": "3.0.3", "info": {"title": "MarketMirror API", "version": "0.3.0",
                                         "description": "Marketing and sales simulation on simulated buyers. Long jobs return task ids."},
            "servers": [{"url": "http://localhost:5001"}], "tags": [{"name": v} for v in TAGS.values()], "paths": paths}


if __name__ == "__main__":
    os.makedirs(os.path.join(ROOT, "docs"), exist_ok=True)
    with open(os.path.join(ROOT, "docs", "API.md"), "w", encoding="utf-8") as f:
        f.write(md())
    with open(os.path.join(ROOT, "docs", "openapi.json"), "w", encoding="utf-8") as f:
        json.dump(openapi(), f, indent=2)
    print(f"wrote docs/API.md and docs/openapi.json ({len(ENDPOINTS)} endpoints)")
