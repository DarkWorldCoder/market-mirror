"""Owner-configured remote MCP discovery and explicitly enabled read-only tools.

Streamable HTTP (2025-11-25 / 2025-06-18), JSON and SSE responses.
No subprocesses, OAuth flow, model sampling or write-tool execution.
"""
import ipaddress
import json
import os
import re
import socket
import tempfile
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import urllib3

from ..config import Config

_LOCK = threading.RLock()
_ID = re.compile(r"^mcp_[a-f0-9]{12}$")
_NAME = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_MAX_BYTES = 2 * 1024 * 1024
_VERSIONS = ("2025-11-25", "2025-06-18")
_FIELDS = {"name", "url", "token", "clear_token", "enabled", "allowed_tools", "protocol_version"}


class ConnectorError(ValueError):
    pass


class ConnectorAuthenticationError(ConnectorError):
    pass


def _path():
    return Path(Config.UPLOAD_FOLDER) / "workspace_connectors.json"


def _read():
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []


def _write(rows):
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".connectors.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(rows, handle, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]") if secret else value
    if isinstance(value, dict):
        return {_redact(key, secret): _redact(item, secret) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    return value


def _public(row):
    return _redact({key: value for key, value in row.items() if key != "token"}, row.get("token")) | {"token_configured": bool(row.get("token"))}


def list_connectors():
    with _LOCK:
        return [_public(row) for row in _read()]


def _get(connector_id):
    if not isinstance(connector_id, str) or not _ID.fullmatch(connector_id):
        raise LookupError("Connector not found")
    row = next((row for row in _read() if row["id"] == connector_id), None)
    if not row:
        raise LookupError("Connector not found")
    return row


def _text(value, field, limit):
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ConnectorError(f"{field} must be a single line of at most {limit} characters")
    return value.strip()


def _is_public(value):
    address = ipaddress.ip_address(value)
    return (address.is_global and not address.is_multicast and not address.is_reserved
            and not getattr(address, "is_site_local", False)
            and not getattr(address, "sixtofour", None) and not getattr(address, "teredo", None))


def _endpoint(value):
    value = _text(value, "url", 2048)
    parsed = urlsplit(value)
    try:
        port = parsed.port or 443
    except ValueError as exc:
        raise ConnectorError("Invalid endpoint port") from exc
    if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        raise ConnectorError("Use a public HTTPS MCP endpoint without credentials, query or fragment")
    if parsed.hostname.lower() in {"localhost", "metadata.google.internal"}:
        raise ConnectorError("Private and local endpoints are not supported")
    try:
        if not _is_public(parsed.hostname):
            raise ConnectorError("Private and local endpoints are not supported")
    except ValueError as exc:
        if isinstance(exc, ConnectorError):
            raise
    return value


def save(data, connector_id=None):
    if not isinstance(data, dict) or set(data) - _FIELDS:
        raise ConnectorError("Use name, url, token, enabled, allowed_tools or protocol_version")
    with _LOCK:
        rows = _read()
        old = _get(connector_id) if connector_id else None
        if not old and len(rows) >= 30:
            raise ConnectorError("Use at most 30 remote connectors")
        row = dict(old) if old else {"id": "mcp_" + uuid.uuid4().hex[:12], "name": "", "url": "", "token": "", "enabled": False,
                                     "allowed_tools": [], "protocol_version": _VERSIONS[0], "status": "not_tested", "tools": [], "checked_at": None, "error": None}
        for key, value in data.items():
            if key == "name":
                row[key] = _text(value, key, 100)
            elif key == "url":
                row[key] = _endpoint(value)
            elif key == "token":
                value = _text(value, key, 8192)
                if value:
                    row[key] = value
            elif key == "clear_token":
                if type(value) is not bool:
                    raise ConnectorError("clear_token must be true or false")
                if value:
                    row["token"] = ""
            elif key == "enabled":
                if type(value) is not bool:
                    raise ConnectorError("enabled must be true or false")
                row[key] = value
            elif key == "protocol_version":
                if value not in _VERSIONS:
                    raise ConnectorError("Select a supported Streamable HTTP protocol version")
                row[key] = value
            elif key == "allowed_tools":
                if not isinstance(value, list) or len(value) > 100 or any(not isinstance(v, str) or not _NAME.fullmatch(v) for v in value):
                    raise ConnectorError("allowed_tools must contain at most 100 tool names")
                row[key] = list(dict.fromkeys(value))
        if not row["name"] or not row["url"]:
            raise ConnectorError("Give the connector a name and HTTPS MCP endpoint")
        if old and any(row.get(key) != old.get(key) for key in ("url", "token", "protocol_version")):
            row.update(status="not_tested", tools=[], checked_at=None, error=None, allowed_tools=[])
        if old:
            rows = [row if item["id"] == row["id"] else item for item in rows]
        else:
            rows.append(row)
        _write(rows)
        return _public(row)


def remove(connector_id):
    with _LOCK:
        _get(connector_id)
        _write([row for row in _read() if row["id"] != connector_id])


def _resolve(url):
    parsed = urlsplit(_endpoint(url))
    try:
        addresses = list(dict.fromkeys(info[4][0] for info in socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)))
    except OSError as exc:
        raise ConnectorError("The MCP hostname could not be resolved") from exc
    if not addresses or any(not _is_public(address) for address in addresses):
        raise ConnectorError("The MCP hostname must resolve only to public addresses")
    return parsed, addresses[0]


def _http(url, payload, headers):
    """Pin a checked address while retaining TLS SNI/hostname verification. Never follow redirects."""
    parsed, address = _resolve(url)
    host = parsed.hostname
    pool = urllib3.HTTPSConnectionPool(address, port=parsed.port or 443, server_hostname=host, assert_hostname=host,
                                       cert_reqs="CERT_REQUIRED", timeout=urllib3.Timeout(connect=5, read=10), retries=False)
    response = None
    try:
        deadline = time.monotonic() + 20
        response = pool.urlopen("POST", parsed.path or "/", body=json.dumps(payload).encode(),
                                headers={**headers, "Host": parsed.netloc}, redirect=False, preload_content=False)
        if response.status in (401, 403):
            raise ConnectorAuthenticationError("Authentication required or account access denied. Check the bearer token and provider permissions.")
        if response.status not in (200, 202):
            raise ConnectorError(f"MCP endpoint returned HTTP {response.status}. Check its URL and credentials.")
        raw = bytearray()
        result = None
        while len(raw) <= _MAX_BYTES:
            if time.monotonic() >= deadline:
                raise ConnectorError("MCP response exceeded its time limit")
            chunk = response.read1(4096, decode_content=True)
            if not chunk:
                break
            raw.extend(chunk)
            if "text/event-stream" in response.headers.get("Content-Type", ""):
                # Stop on the response for this request instead of waiting on a persistent SSE stream.
                for event in bytes(raw).decode("utf-8", errors="replace").replace("\r\n", "\n").split("\n\n")[:-1]:
                    parts = [line[5:].lstrip() for line in event.splitlines() if line.startswith("data:")]
                    if parts:
                        try:
                            candidate = json.loads("\n".join(parts))
                            if isinstance(candidate, dict) and candidate.get("id") == payload.get("id") and ("result" in candidate or "error" in candidate):
                                result = candidate
                        except ValueError:
                            continue
                if result is not None:
                    break
        if len(raw) > _MAX_BYTES:
            raise ConnectorError("MCP response exceeds the 2 MB limit")
        if response.status == 202 and "id" not in payload:
            return {}, dict(response.headers)
        if result is None:
            try:
                result = json.loads(raw)
            except ValueError as exc:
                raise ConnectorError("MCP endpoint did not return a valid JSON-RPC response") from exc
        return result, dict(response.headers)
    except ConnectorError:
        raise
    except Exception as exc:
        # Never reflect a response body, Authorization header or transport exception containing secrets.
        raise ConnectorError("MCP connection failed. Check the endpoint, TLS certificate and server availability.") from exc
    finally:
        if response is not None and hasattr(response, "close"):
            response.close()
        pool.close()


class _Client:
    def __init__(self, row):
        self.row = row
        self.counter = 0
        self.headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if row.get("token"):
            self.headers["Authorization"] = "Bearer " + row["token"]
        result = self.rpc("initialize", {"protocolVersion": row["protocol_version"], "capabilities": {},
                                          "clientInfo": {"name": "MarketMirror", "version": "0.4.0"}})
        version = result.get("protocolVersion")
        if version not in _VERSIONS:
            raise ConnectorError("This server negotiated an unsupported MCP version")
        self.headers["MCP-Protocol-Version"] = version
        self.rpc("notifications/initialized", notification=True)

    def rpc(self, method, params=None, notification=False):
        self.counter += 1
        payload = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if not notification:
            payload["id"] = self.counter
        result, headers = _http(self.row["url"], payload, self.headers)
        session = next((value for key, value in headers.items() if key.lower() == "mcp-session-id"), None)
        if session:
            if len(session) > 1024 or any(ord(c) < 33 or ord(c) > 126 for c in session):
                raise ConnectorError("Invalid MCP session identifier")
            self.headers["Mcp-Session-Id"] = session
        if notification:
            return {}
        if not isinstance(result, dict) or result.get("id") != payload["id"] or "error" in result or not isinstance(result.get("result"), dict):
            raise ConnectorError("MCP request failed. Check server permissions and protocol support.")
        return result["result"]

    def tools(self):
        tools = []
        seen = set()
        cursor = None
        for _ in range(3):
            page = self.rpc("tools/list", {"cursor": cursor} if cursor else {})
            if not isinstance(page.get("tools"), list):
                raise ConnectorError("MCP server returned an invalid tools list")
            for item in page["tools"]:
                if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not _NAME.fullmatch(item["name"]):
                    continue
                if item["name"] in seen:
                    continue
                seen.add(item["name"])
                tools.append({"name": item["name"], "description": str(item.get("description") or "")[:1000],
                              "inputSchema": item.get("inputSchema") if isinstance(item.get("inputSchema"), dict) else {"type": "object"},
                              "read_only": item.get("annotations", {}).get("readOnlyHint") is True if isinstance(item.get("annotations", {}), dict) else False})
                if len(tools) >= 100:
                    return tools, True
            cursor = page.get("nextCursor")
            if not cursor:
                return tools, False
        return tools, True


def discover(connector_id):
    with _LOCK:
        row = dict(_get(connector_id))
    try:
        client = _Client(row)
        tools, truncated = client.tools()
        changes = {"status": "connected", "tools": tools, "tools_truncated": truncated, "error": None, "checked_at": time.time()}
    except ConnectorError as exc:
        changes = {"status": "auth_required" if isinstance(exc, ConnectorAuthenticationError) else "error", "tools": [], "error": str(exc), "checked_at": time.time()}
    with _LOCK:
        current = _get(connector_id)
        if any(row.get(key) != current.get(key) for key in ("url", "token", "protocol_version")):
            raise ConnectorError("Connector changed during discovery. Check it again.")
        current.update(changes)
        rows = [current if item["id"] == connector_id else item for item in _read()]
        _write(rows)
        return _public(current)


def call_tool(connector_id, name, arguments):
    with _LOCK:
        row = dict(_get(connector_id))
    if not row.get("enabled") or name not in row.get("allowed_tools", []):
        raise ConnectorError("Enable this connector and explicitly allow the tool before using it in chat")
    if not isinstance(arguments, dict) or len(json.dumps(arguments)) > 16000:
        raise ConnectorError("Tool arguments must be an object of at most 16000 characters")
    client = _Client(row)
    tools, _ = client.tools()
    tool = next((tool for tool in tools if tool["name"] == name and tool["read_only"]), None)
    if tool is None:
        raise ConnectorError("Only discovered tools declaring readOnlyHint=true can run in chat")
    result = client.rpc("tools/call", {"name": name, "arguments": arguments})
    if result.get("isError"):
        raise ConnectorError("The MCP tool reported an error. Check its arguments and account permissions.")
    text = json.dumps(_redact(result, row.get("token")), ensure_ascii=False)
    return {"connector_id": connector_id, "connector": _redact(row["name"], row.get("token")), "tool": name,
            "result": text[:20000], "truncated": len(text) > 20000}
