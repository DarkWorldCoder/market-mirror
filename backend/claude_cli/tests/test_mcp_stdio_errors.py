"""MCP stdio: lines that are not JSON get a -32700 reply, and JSON that is not an object gets -32600 (both id null)."""

import json
import os
import subprocess
import sys
import tempfile
import shutil
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
MCP = os.path.abspath(os.path.join(HERE, "..", "..", "..", "plugin", "skills", "market-mirror", "scripts", "mcp_server.py"))


class StdioErrors(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, True)

    def test_invalid_lines_get_json_rpc_errors(self):
        lines = [
            "this is not json",
            json.dumps(["tools/list"]),
            json.dumps("a string"),
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}),
        ]
        p = subprocess.run([sys.executable, MCP], input="\n".join(lines) + "\n", capture_output=True, text=True,
                           timeout=120, env={**os.environ, "MARKET_MIRROR_HOME": self.home})
        out = [json.loads(line) for line in p.stdout.splitlines()]
        self.assertEqual(len(out), 4, p.stdout)
        self.assertEqual(out[0]["error"]["code"], -32700)
        self.assertIsNone(out[0]["id"])
        self.assertEqual(out[1]["error"]["code"], -32600)
        self.assertIsNone(out[1]["id"])
        self.assertEqual(out[2]["error"]["code"], -32600)
        self.assertIsNone(out[2]["id"])
        self.assertEqual(out[3]["id"], 1)
        self.assertIn("result", out[3])


if __name__ == "__main__":
    unittest.main()
