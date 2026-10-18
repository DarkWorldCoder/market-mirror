"""Webhook delivery: posts a JSON summary, retries, never raises."""

import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import mirofish  # noqa: E402


class WebhookTests(unittest.TestCase):
    def test_delivery_and_failure(self):
        received = []

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                received.append(json.loads(self.rfile.read(n)))
                self.send_response(500 if self.path == "/fail" else 200)
                self.end_headers()

            def log_message(self, *a):
                pass
        srv = HTTPServer(("127.0.0.1", 0), H)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            port = srv.server_address[1]
            r = mirofish.notify_webhook({"event": "test.finished", "winner": "a"}, f"http://127.0.0.1:{port}/ok")
            self.assertTrue(r["sent"]) and self.assertEqual(received[0]["event"], "test.finished")
            self.assertIn("sent_at", received[0])
            r2 = mirofish.notify_webhook({"event": "x"}, f"http://127.0.0.1:{port}/fail", retries=2)
            self.assertFalse(r2["sent"]) and self.assertEqual(len(received), 3)
            self.assertIsNone(mirofish.notify_webhook({"event": "x"}, None))      # no URL configured: silent
        finally:
            srv.shutdown()


if __name__ == "__main__":
    unittest.main()
