"""intake command offline (--engine supplied): files in, a persona spec with grounded records and a report out."""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import mirofish  # noqa: E402


def run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = mirofish.main(argv)
    return code, out.getvalue(), err.getvalue()


class IntakeCLI(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        with open(os.path.join(self.d, "reviews.csv"), "w", encoding="utf-8") as f:
            f.write("author,plan,review\n"
                    "Maya Chen,Pro,\"The weekly report saves me an hour. Call me on 415 555 0199 if you need a quote.\"\n"
                    "Leo Park,Free,\"Too many notifications, I switched them all off within a day.\"\n")
        with open(os.path.join(self.d, "call_01.txt"), "w", encoding="utf-8") as f:
            f.write("Q: What almost stopped you from buying?\nA: My finance team asks for an invoice before any card payment.")

    def test_offline_intake_writes_spec_and_report(self):
        out = os.path.join(self.d, "scn", "personas.json")
        with open(os.path.join(self.d, "base.json"), "w") as f:
            json.dump({"segments": [{"name": "Teams", "count": 3}]}, f)
        code, stdout, _ = run_cli(["intake", "--files", os.path.join(self.d, "reviews.csv"), os.path.join(self.d, "call_01.txt"),
                                   "--engine", "supplied", "--segment-field", "plan", "--segment", "Interviewed",
                                   "--base", os.path.join(self.d, "base.json"), "--out", out])
        self.assertEqual(code, 0, stdout)
        res = json.loads(stdout)
        self.assertEqual(res["counts"]["records"], 3)
        self.assertEqual(res["counts"]["scrubbed"]["phone"], 1)
        with open(out, encoding="utf-8") as f:
            spec = json.load(f)
        self.assertEqual(spec["segments"], [{"name": "Teams", "count": 3}])
        segs = sorted(r["segment"] for r in spec["real_profiles"])
        self.assertEqual(segs, ["Free", "Interviewed", "Pro"])
        blob = json.dumps(spec)
        for gone in ("Maya", "Chen", "555 0199"):
            self.assertNotIn(gone, blob)
        md = open(os.path.join(self.d, "scn", "intake.md"), encoding="utf-8").read()
        self.assertIn("invoice before any card payment", md)
        # running again adds to the spec; --replace swaps the earlier intake records instead
        run_cli(["intake", "--files", os.path.join(self.d, "reviews.csv"), "--engine", "supplied", "--out", out])
        self.assertEqual(len(json.load(open(out))["real_profiles"]), 5)
        run_cli(["intake", "--files", os.path.join(self.d, "reviews.csv"), "--engine", "supplied", "--out", out, "--replace"])
        self.assertEqual(len(json.load(open(out))["real_profiles"]), 2)

    def test_llm_engine_without_backend_says_how_to_run_offline(self):
        code, stdout, _ = run_cli(["intake", "--files", os.path.join(self.d, "reviews.csv"),
                                   "--base-url", "http://127.0.0.1:9", "--out", os.path.join(self.d, "p.json")])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
