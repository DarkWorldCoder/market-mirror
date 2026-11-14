"""Build/open the local Vue app on the existing loopback Flask server."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import webbrowser


def main():
    parser = argparse.ArgumentParser(description="Open the MarketMirror local app. A model provider is optional until running a test.")
    parser.add_argument("--port", type=int, default=5001)
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument("--build", action="store_true", help="Rebuild even when the app is already built")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be between 1024 and 65535")
    root = Path(__file__).resolve().parents[2]
    frontend = root / "frontend"
    if args.build or not (frontend / "dist/index.html").is_file():
        if not shutil.which("npm"):
            parser.error("Node.js/npm is needed to build the local interface once. Install Node.js 20.19+ or 22.12+ and try again.")
        if not (frontend / "node_modules").is_dir():
            subprocess.run(["npm", "ci"], cwd=frontend, check=True)
        subprocess.run(["npm", "run", "build"], cwd=frontend, check=True)
    # Unlike `mm start`, opening the app must also work before credentials exist.
    subprocess.run(["bash", str(root / "backend/claude_cli/start_server.sh"), "--port", str(args.port)],
                   cwd=root, env={**os.environ, "MM_LOCAL_APP": "1"}, check=True)
    url = f"http://127.0.0.1:{args.port}"
    with urllib.request.urlopen(url + "/health", timeout=5) as response:
        if json.load(response).get("workflows") != 1:
            parser.error("An older backend is running on this port. Stop it with ./mm stop, then run ./mm app again, or choose another --port.")
    token = (root / "backend/logs/setup.token").read_text().strip()
    if not args.no_open:
        webbrowser.open(url + "/#t=" + token)
    print(json.dumps({"url": url, "opened": not args.no_open,
                      "note": "Local app ready. If using --no-open, open the URL with #t=<the local backend/logs/setup.token value> on this computer. Never share that token."}))


if __name__ == "__main__":
    try:
        main()
    except (OSError, subprocess.CalledProcessError, urllib.error.URLError):
        print("Could not start the local app. Check Node/Python dependencies and the backend startup message.", file=sys.stderr)
        sys.exit(1)
