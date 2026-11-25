"""--base-url / MIROFISH_URL must be a full http(s) URL; request failures come back as one-line errors, not tracebacks."""

import contextlib
import io
import json
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import mirofish  # noqa: E402


class BaseUrlTests(unittest.TestCase):
    def test_accepts_http_and_https_and_trims_slash(self):
        self.assertEqual(mirofish.Client("http://localhost:5001/", token="").base, "http://localhost:5001")
        self.assertEqual(mirofish.Client(" https://mm.example.com/api ", token="").base, "https://mm.example.com/api")
        self.assertEqual(mirofish.Client("http://[::1]:5001", token="").base, "http://[::1]:5001")

    def test_rejects_urls_without_scheme_or_host(self):
        for bad in ("localhost:5001", "127.0.0.1:5001", "mm.example.com", "", "   ", "ftp://localhost", "http://", "http:///x",
                    "http://[::1", "http://[zz]"):
            with self.subTest(url=bad):
                with self.assertRaises(mirofish.CLIError) as ctx:
                    mirofish.Client(bad, token="")
                self.assertIn("http://localhost:5001", str(ctx.exception))

    def test_cli_prints_one_json_line_and_exits_1(self):
        for bad in ("localhost:5001", "http://[::1"):
            with self.subTest(url=bad):
                out = io.StringIO()
                with mock.patch.dict(os.environ, {"MM_API_AUTH_TOKEN": ""}), \
                        contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                    code = mirofish.main(["--base-url", bad, "health"])
                self.assertEqual(code, 1)
                lines = out.getvalue().strip().splitlines()
                self.assertEqual(len(lines), 1)
                body = json.loads(lines[0])
                self.assertIs(body["success"], False)
                self.assertIn(bad, body["error"])
                self.assertIn("http://localhost:5001", body["error"])

    def test_other_request_errors_become_cli_errors(self):
        c = mirofish.Client("http://localhost:5001", token="")
        boom = c.requests.exceptions.InvalidURL("bad url")
        with mock.patch.object(c.session, "request", side_effect=boom) as req:
            with self.assertRaises(mirofish.CLIError) as ctx:
                c.get("/health")
        self.assertEqual(req.call_count, 1)   # not retried
        self.assertIn("GET /health", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
