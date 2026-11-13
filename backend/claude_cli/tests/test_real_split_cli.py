"""real-split offline (two CSVs and a manifest with hashed ids) and calibrate's guard: the persona-building side is
left out of the check, its file is refused, and a real file that also built the run's personas is flagged."""

import contextlib
import csv
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import mirofish  # noqa: E402


def run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = mirofish.main(argv)
    return code, out.getvalue(), err.getvalue()


class RealSplit(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        self.real = os.path.join(self.d, "answers.csv")
        with open(self.real, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["email", "segment", "would_convert"])
            for i in range(100):
                w.writerow([f"user{i}@example.com", "Pro" if i % 2 else "Free", "yes" if i % 3 else "no"])

    def split(self, *extra):
        code, stdout, err = run_cli(["real-split", "--real", self.real, "--segment-field", "segment", *extra])
        self.assertEqual(code, 0, err)
        return json.loads(stdout)

    def read(self, path):
        with open(path, encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def test_split_files_manifest_and_report(self):
        res = self.split()
        self.assertEqual(res["share"], 0.2)
        cond, hold = self.read(res["conditioning"]), self.read(res["holdout"])
        self.assertEqual((len(cond), len(hold)), (20, 80))
        self.assertFalse({r["email"] for r in cond} & {r["email"] for r in hold})
        manifest = json.load(open(res["manifest"], encoding="utf-8"))
        self.assertNotIn("example.com", json.dumps(manifest))
        self.assertEqual(manifest["files"]["holdout"], "answers_holdout.csv")
        md = open(res["markdown"], encoding="utf-8").read()
        self.assertIn("| 20% | 20 | 80 |", md)
        self.assertEqual(self.split("--share", "0.3")["counts"]["conditioning"], 30)
        code, _, _ = run_cli(["real-split", "--real", self.real, "--share", "1.5"])
        self.assertEqual(code, 1)

    def test_calibrate_guard(self):
        res = self.split()
        run = os.path.join(self.d, "run")
        os.makedirs(run)
        args = lambda real: SimpleNamespace(real=real, split=None)                  # noqa: E731
        # the full file: the persona-building people are left out
        rows = self.read(self.real)
        kept, info = mirofish._holdout_check(args(self.real), run, rows)
        self.assertEqual((info["status"], info["removed"], len(kept)), ("removed", 20, 80))
        # the holdout file: nothing to remove
        kept, info = mirofish._holdout_check(args(res["holdout"]), run, self.read(res["holdout"]))
        self.assertEqual((info["status"], len(kept)), ("clean", 80))
        # the persona-building file itself is refused
        with self.assertRaises(mirofish.CLIError):
            mirofish._holdout_check(args(res["conditioning"]), run, self.read(res["conditioning"]))
        # a file that also built the run's grounded personas is flagged
        other = os.path.join(self.d, "elsewhere", "survey.csv")
        os.makedirs(os.path.dirname(other))
        shutil.copy(self.real, other)
        with open(os.path.join(run, "personas_intake.json"), "w", encoding="utf-8") as f:
            json.dump({"real_profiles": [{"name": "Customer 1", "intake": {"sources": ["survey.csv"]}}]}, f)
        _, info = mirofish._holdout_check(args(other), run, self.read(other))
        self.assertTrue(info["same_file_as_personas"])
        self.assertIn("real-split", info["warning"])
        with self.assertRaises(mirofish.CLIError):
            mirofish._holdout_check(SimpleNamespace(real=other, split=os.path.join(self.d, "none.json")), run, [])


if __name__ == "__main__":
    unittest.main()
