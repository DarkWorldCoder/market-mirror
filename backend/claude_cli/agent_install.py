"""Print registration instructions without changing another agent's configuration."""
import argparse
import json
import shlex
import os
import tempfile
from pathlib import Path


def register_engine(root: Path, config_dir: Path = None) -> dict:
    """Let cached plugins find an explicitly installed checkout."""
    root = root.resolve()
    configuration(root)
    directory = config_dir or Path(os.environ.get("MARKET_MIRROR_CONFIG_DIR") or Path.home() / ".market-mirror")
    directory.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="engine.", dir=directory)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump({"schema_version": 1, "path": str(root)}, f)
        os.replace(name, directory / "engine.json")
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return {"engine": str(root), "registration_file": str(directory / "engine.json")}


def configuration(root: Path, client: str = "generic") -> dict:
    root = root.resolve()
    server = root / "plugin/skills/market-mirror/scripts/mcp_server.py"
    if not server.is_file():
        raise ValueError("MarketMirror MCP server is missing from this checkout")
    entry = {"command": "python3", "args": [str(server)], "env": {"MARKET_MIRROR_HOME": str(root)}}
    result = {"client": client, "mcpServers": {"market-mirror": entry},
              "next": "Restart your agent, call doctor, choose a provider, then run a small simulation fixture."}
    if client in ("codex", "claude"):
        command = [client, "mcp", "add", "market-mirror", "--env", f"MARKET_MIRROR_HOME={root}", "--", "python3", str(server)]
        result["registration_args"] = command
        result["registration_command"] = shlex.join(command)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--client", choices=("generic", "codex", "claude", "cursor", "gemini"), default="generic")
    parser.add_argument("--register-engine", action="store_true")
    args = parser.parse_args()
    print(json.dumps(register_engine(args.root) if args.register_engine else configuration(args.root, args.client), indent=2))


if __name__ == "__main__":
    main()
