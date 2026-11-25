"""MCP server: a non-numeric MARKET_MIRROR_* value warns and uses the default instead of stopping at import."""

import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
MCP = os.path.abspath(os.path.join(HERE, "..", "..", "..", "plugin", "skills", "market-mirror", "scripts", "mcp_server.py"))
INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}}}
# variable -> (module constant, default the server must use)
CASES = {
    "MARKET_MIRROR_USD_PER_CALL": ("USD_PER_CALL", 0.005),
    "MARKET_MIRROR_ELICIT_TIMEOUT": ("ELICIT_TIMEOUT", 600),
}
# Loads the server file as a module (its main() is behind __main__) and prints the constants it chose.
LOAD = ("import importlib.util, json, sys; "
        "s = importlib.util.spec_from_file_location('mcp_server', sys.argv[1]); "
        "m = importlib.util.module_from_spec(s); s.loader.exec_module(m); "
        "print(json.dumps({'USD_PER_CALL': m.USD_PER_CALL, 'ELICIT_TIMEOUT': m.ELICIT_TIMEOUT}))")


class BadEnvValues(unittest.TestCase):
    def test_bad_values_warn_and_use_default(self):
        for name, (const, default) in CASES.items():
            with self.subTest(variable=name):
                env = {**os.environ, name: "not-a-number"}
                proc = subprocess.run([sys.executable, "-c", LOAD, MCP], capture_output=True,
                                      text=True, env=env, timeout=60)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                values = json.loads(proc.stdout.strip().splitlines()[-1])
                self.assertEqual(values[const], default, f"{const} should fall back to {default}")
                self.assertIn(name, proc.stderr)
                self.assertIn("not-a-number", proc.stderr)

    def test_server_still_answers_initialize(self):
        for name in CASES:
            with self.subTest(variable=name):
                env = {**os.environ, name: "not-a-number"}
                proc = subprocess.run([sys.executable, MCP], input=json.dumps(INIT) + "\n", capture_output=True,
                                      text=True, env=env, timeout=60)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                replies = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
                self.assertTrue(replies and "result" in replies[0], f"no initialize result: {proc.stdout!r}")


if __name__ == "__main__":
    unittest.main()
