"""Every manifest shows the same version as the PyPI package."""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _json(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _pyproject_version():
    text = (ROOT / "packaging/pypi/pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise AssertionError("packaging/pypi/pyproject.toml has no version")
    return match.group(1)


def _mcp_server_version():
    text = (ROOT / "plugin/skills/market-mirror/scripts/mcp_server.py").read_text(
        encoding="utf-8"
    )
    # the literal in initialize, or the SERVER_INFO constant it uses
    match = re.search(r'(?:"serverInfo":|SERVER_INFO\s*=)\s*\{[^}]*"version":\s*"([^"]+)"', text)
    if not match:
        raise AssertionError("mcp_server.py has no serverInfo version")
    return match.group(1)


class ManifestVersionTest(unittest.TestCase):
    def test_manifests_share_the_release_version(self):
        expected = _pyproject_version()
        server = _json("server.json")
        versions = {
            "server.json": server["version"],
            "server.json packages[0]": server["packages"][0]["version"],
            "gemini-extension.json": _json("gemini-extension.json")["version"],
            "plugin/.claude-plugin/plugin.json": _json(
                "plugin/.claude-plugin/plugin.json"
            )["version"],
            ".claude-plugin/marketplace.json": _json(
                ".claude-plugin/marketplace.json"
            )["plugins"][0]["version"],
            "mcp_server.py": _mcp_server_version(),
        }
        for name, version in versions.items():
            self.assertEqual(version, expected, name)


if __name__ == "__main__":
    unittest.main()
