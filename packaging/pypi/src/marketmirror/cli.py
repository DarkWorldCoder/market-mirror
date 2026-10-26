"""Run the bundled MarketMirror MCP server (stdio by default; pass --help for options).

The server is the same file the Claude Code plugin and Gemini extension use. It drives the MarketMirror engine through
the bundled mm.sh helper; the engine itself is installed on first use with the `setup` tool (into
~/.market-mirror/engine, or MARKET_MIRROR_HOME).
"""

import os
import runpy
import sys


def main() -> None:
    server = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_server", "mcp_server.py")
    if not os.path.isfile(server):
        sys.exit("marketmirror: bundled server files are missing from this install")
    sys.argv[0] = server
    runpy.run_path(server, run_name="__main__")


if __name__ == "__main__":
    main()
