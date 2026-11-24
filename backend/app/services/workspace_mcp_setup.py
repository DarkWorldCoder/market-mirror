"""Copy-ready settings for adding MarketMirror's own MCP server to other AI apps.

Built from this checkout's real paths. The launch line matches plugin/skills/market-mirror/scripts/mcp_server.py:
stdio by default, or `--http --port N --token-file FILE` for authenticated loopback HTTP at /mcp. MARKET_MIRROR_HOME
points mm.sh at this checkout instead of ~/.market-mirror/engine. Nothing here contains a token or key: the HTTP
examples use a placeholder for the bearer token the user keeps in their own file.
"""
import json
import shlex
import shutil
import sys

NAME = "market-mirror"
HTTP_PORT = 5061
TOKEN_PLACEHOLDER = "<token from your token file>"
TOKEN_FILE_PLACEHOLDER = "<path to a private file holding a long random token>"


def _root():
    from ..api import setup
    return setup.ROOT


def _desktop_config_path():
    if sys.platform == "darwin":
        return "~/Library/Application Support/Claude/claude_desktop_config.json"
    if sys.platform.startswith("win"):
        return "%APPDATA%\\Claude\\claude_desktop_config.json"
    return "~/.config/Claude/claude_desktop_config.json"


def _toml_string(value):
    # A TOML basic string accepts the same escapes json.dumps writes for these paths.
    return json.dumps(str(value))


def snippets():
    root = _root()
    server = root / "plugin" / "skills" / "market-mirror" / "scripts" / "mcp_server.py"
    python = shutil.which("python3") or "python3"
    env = {"MARKET_MIRROR_HOME": str(root)}
    stdio = {"command": python, "args": [str(server)], "env": env}

    def block(key, servers):
        return json.dumps({key: servers}, indent=2)

    claude_code = " ".join(["claude", "mcp", "add", "--env", shlex.quote(f"MARKET_MIRROR_HOME={root}"), NAME, "--",
                            shlex.quote(python), shlex.quote(str(server))])
    codex = "\n".join([f"[mcp_servers.{NAME}]", f"command = {_toml_string(python)}", f"args = [{_toml_string(server)}]",
                       f"env = {{ MARKET_MIRROR_HOME = {_toml_string(root)} }}"])
    clients = [
        {"id": "claude-desktop", "label": "Claude Desktop", "format": "json", "where": _desktop_config_path(),
         "steps": "Open Settings > Developer > Edit Config, add this inside the file, save, then restart Claude Desktop.",
         "snippet": block("mcpServers", {NAME: stdio})},
        {"id": "claude-code", "label": "Claude Code", "format": "shell", "where": "Terminal",
         "steps": "Run this once. Check it with: claude mcp list",
         "snippet": claude_code},
        {"id": "cursor", "label": "Cursor", "format": "json", "where": "~/.cursor/mcp.json",
         "steps": "Add this to the file (or a project's .cursor/mcp.json), then turn the server on in Cursor's MCP settings.",
         "snippet": block("mcpServers", {NAME: stdio})},
        {"id": "vscode", "label": "VS Code", "format": "json", "where": ".vscode/mcp.json",
         "steps": "Add this to the workspace file, then start the server from the MCP view.",
         "snippet": block("servers", {NAME: {"type": "stdio", **stdio}})},
        {"id": "codex", "label": "Codex", "format": "toml", "where": "~/.codex/config.toml",
         "steps": "Add this to the file, then restart Codex.",
         "snippet": codex},
        {"id": "other", "label": "Other apps", "format": "json", "where": "The app's MCP settings file",
         "steps": "Most apps that take an mcpServers JSON block accept this.",
         "snippet": block("mcpServers", {NAME: stdio})},
    ]
    http_start = " ".join([shlex.quote(python), shlex.quote(str(server)), "--http", "--port", str(HTTP_PORT),
                           "--token-file", TOKEN_FILE_PLACEHOLDER])
    url = f"http://127.0.0.1:{HTTP_PORT}/mcp"
    http = {
        "start": http_start,
        "url": url,
        "note": "Only apps on this computer can reach it. Every request needs the token from your file as a bearer token.",
        "snippet": block("mcpServers", {NAME: {"url": url, "headers": {"Authorization": f"Bearer {TOKEN_PLACEHOLDER}"}}}),
        "claude_code": " ".join(["claude", "mcp", "add", "--transport", "http", NAME, url, "--header",
                                 shlex.quote(f"Authorization: Bearer {TOKEN_PLACEHOLDER}")]),
    }
    return {"name": NAME, "server_path": str(server), "server_found": server.is_file(), "home": str(root),
            "python": python, "clients": clients, "http": http}
