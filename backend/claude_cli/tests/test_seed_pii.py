"""Seed documents with contact details: upload warns, --scrub-seeds uploads a cleaned copy, --no-pii-check skips it."""

import contextlib
import glob
import io
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import mirofish  # noqa: E402

SEED = ("Customer thread.\n"
        "Reach Maya at maya.chen@example.com or leo@example.org.\n"
        "Call +44 20 7946 0958 before Friday.\n"
        "Follow @maya_c and see https://example.com/offer\n")


class FakeClient:
    """Records what the upload would send and returns a minimal ontology response."""

    def __init__(self):
        self.sent = []

    def data(self, method, path, files=None, data=None, **kw):
        self.sent = [(name, fh.read().decode("utf-8", "replace")) for _, (name, fh) in files]
        return {"project_id": "proj_test", "ontology": {"entity_types": [], "edge_types": []}}


class SeedPII(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        self.seed = os.path.join(self.d, "seed.md")
        with open(self.seed, "w", encoding="utf-8") as f:
            f.write(SEED)

    def upload(self, **kw):
        err = io.StringIO()
        client = FakeClient()
        with contextlib.redirect_stderr(err):
            data = mirofish.step_upload(client, [self.seed], "What will buyers think?", None, **kw)
        return data, client, err.getvalue()

    def test_warning_names_file_and_counts(self):
        _, _, err = self.upload()
        self.assertIn("warning: seed.md contains personal data", err)
        self.assertIn("2 email", err)
        self.assertIn("1 phone", err)
        self.assertIn("1 handle", err)
        self.assertIn("1 link", err)

    def test_scrub_seeds_uploads_cleaned_copy_with_same_name(self):
        _, client, _ = self.upload(scrub_seeds=True)
        self.assertEqual(len(client.sent), 1)
        name, text = client.sent[0]
        self.assertEqual(name, "seed.md")
        self.assertNotIn("@example", text)
        self.assertNotIn("7946 0958", text)
        self.assertNotIn("@maya_c", text)
        self.assertNotIn("example.com/offer", text)
        self.assertIn("[email]", text)
        self.assertIn("[phone]", text)
        self.assertIn("[handle]", text)
        self.assertIn("[link]", text)
        with open(self.seed, encoding="utf-8") as f:
            self.assertEqual(f.read(), SEED)  # the original file is left alone

    def test_no_pii_check_skips_warning(self):
        _, client, err = self.upload(pii_check=False)
        self.assertNotIn("personal data", err)
        self.assertIn("@example", client.sent[0][1])

    def test_pdf_seed_gets_a_not_checked_warning(self):
        pdf = os.path.join(self.d, "brief.pdf")
        with open(pdf, "wb") as f:
            f.write(b"%PDF-1.4 binary")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            mirofish.step_upload(FakeClient(), [pdf], "What will buyers think?", None)
        self.assertIn("warning: brief.pdf is a PDF", err.getvalue())
        self.assertIn("not checked for personal data", err.getvalue())

    def test_scrub_seeds_refuses_pdf_and_removes_earlier_copies(self):
        pdf = os.path.join(self.d, "brief.pdf")
        with open(pdf, "wb") as f:
            f.write(b"%PDF-1.4 binary")
        before = set(glob.glob(os.path.join(tempfile.gettempdir(), "mm_scrub_*")))
        client = FakeClient()
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(mirofish.CLIError) as ctx:
                mirofish.step_upload(client, [self.seed, pdf], "What will buyers think?", None, scrub_seeds=True)
        self.assertIn("--scrub-seeds cannot clean brief.pdf", str(ctx.exception))
        self.assertEqual(client.sent, [])  # nothing was uploaded
        after = set(glob.glob(os.path.join(tempfile.gettempdir(), "mm_scrub_*")))
        self.assertEqual(after - before, set())  # the copy already written for seed.md was removed


if __name__ == "__main__":
    unittest.main()
