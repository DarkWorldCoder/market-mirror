"""Exporter / CLI tests that need no LLM key and no running backend.

Run:  python -m unittest discover -s backend/claude_cli/tests -v
  or: cd backend && uv run --no-sync python -m pytest claude_cli/tests -q
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CLI_DIR = os.path.dirname(HERE)
FIXTURE = os.path.join(HERE, "fixtures", "sample_run")
sys.path.insert(0, CLI_DIR)

import exporter  # noqa: E402
import mirofish  # noqa: E402


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class MarkdownTests(unittest.TestCase):
    def test_blocks(self):
        md = ("# Title\n\nPara with **bold**, *em*, `code` and [link](https://x.org).\n\n"
              "- a\n- b\n  - nested\n\n1. one\n2. two\n\n> quote\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n"
              "```python\nprint('<x>')\n```\n\n---\n")
        h = exporter.markdown_to_html(md)
        for frag in ["<h1>Title</h1>", "<strong>bold</strong>", "<em>em</em>", "<code>code</code>",
                     '<a href="https://x.org" rel="noopener">link</a>', "<ul><li>a</li><li>b<ul><li>nested</li></ul></li></ul>",
                     "<ol><li>one</li><li>two</li></ol>", "<blockquote><p>quote</p></blockquote>",
                     "<th>A</th>", "<td>2</td>", "print(&#x27;&lt;x&gt;&#x27;)", "<hr>"]:
            self.assertIn(frag, h)

    def test_escapes_html_and_unsafe_links(self):
        h = exporter.markdown_to_html("<script>alert(1)</script> [x](javascript:alert(1))")
        self.assertNotIn("<script>", h)
        self.assertNotIn("javascript:", h)

    def test_snake_case_not_italic(self):
        self.assertNotIn("<em>", exporter.markdown_to_html("CREATE_POST and LIKE_POST"))


class ExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.paths = exporter.export_run_dir(FIXTURE, os.path.join(cls.tmp, "dash.html"))
        with open(cls.paths["html"], encoding="utf-8") as f:
            cls.html = f.read()

    def test_outputs_exist(self):
        for p in self.paths.values():
            self.assertTrue(os.path.getsize(p) > 0, p)
        summary = json.loads(_read(self.paths["summary_json"]))
        self.assertEqual(summary["simulation_id"], "sim_demo123")
        self.assertEqual(summary["graph"]["node_count"], 24)
        self.assertEqual(summary["agents"], 24)
        self.assertEqual(summary["rounds_with_actions"], 12)
        self.assertIn("CREATE_POST", summary["action_types"])
        self.assertTrue(_read(self.paths["report_md"]).startswith("# Predicted Reaction"))

    def test_page_contract(self):
        h = self.html
        self.assertRegex(h, r"<title>[^<]{3,}</title>")
        self.assertIn('name="viewport"', h)
        self.assertIn("prefers-color-scheme:dark", h)
        self.assertIn(':root[data-theme="dark"]', h)
        self.assertNotRegex(h, r"<script[^>]+src=")          # no external scripts
        self.assertNotRegex(h, r"<link[^>]+stylesheet")       # no external CSS
        self.assertLess(len(h.encode()), 2_000_000)
        self.assertNotIn("http://", h.split("<body>")[0].split("<meta")[0])   # nothing fetched from the network

    def test_theme_tokens_and_switcher(self):
        h = self.html
        head = h.split("</head>")[0]
        self.assertIn("localStorage.getItem('mm-theme')", head)                 # pre-paint theme script
        self.assertLess(head.index("mm-theme"), head.index("<style>"))
        style = head.split("<style>")[1].split("</style>")[0]
        self.assertEqual(style.count("--bg:#eeeeea"), 1)                       # light palette once ...
        self.assertEqual(style.count("--bg:#0d0d0c"), 2)                       # ... dark block under both selectors
        self.assertGreater(style.rindex(":root{"), style.index(".sf-feed"))     # tokens loaded last
        self.assertIn('<button type="button" class="theme-btn" data-theme-toggle', h)
        self.assertLess(h.index("data-theme-toggle"), h.index('<nav class="toc"'))
        used = set(re.findall(r"var\((--[a-z0-9-]+)", h))
        defined = set(re.findall(r"(--[a-z0-9-]+):", style))
        self.assertEqual(used - defined, set())                                # no undefined custom properties
        self.assertIn("prefers-reduced-motion", style)
        self.assertIn(":focus-visible", style)

    def test_scrollspy_sortable_tables_and_filter_roots(self):
        h = self.html
        self.assertIn('<nav class="toc" data-scrollspy aria-label="Sections">', h)
        self.assertIn("data-scrollspy", h.split("<script>")[-1])              # UI_JS is on the page
        self.assertLess(h.index("window.MM="), h.index("window.MM.theme()"))  # ui script before the chart scripts
        self.assertIn('<table class="personas sortable">', h)
        self.assertIn('data-sort="num" aria-sort="none" scope="col"', h)
        self.assertIn('data-filter-root data-filter-noun="posts"', h)          # social feed uses the generic filter root
        self.assertIn('data-filter="segment"', h)
        self.assertIn("data-filter-count", h)
        self.assertEqual(h.count('class="callout insight"'), h.count('role="note"'))
        self.assertGreaterEqual(h.count('class="callout insight"'), 2)        # timeline + graph insights on the fixture
        self.assertIn('<div class="kpis auto">', h)                            # run-details tiles are kpi tiles
        self.assertNotIn('class="tile"', h)
        self.assertNotIn("hero-stats", h)

    def test_sections(self):
        for sid in ["overview", "graph", "timeline", "agents", "socialfeed", "report"]:   # fixture has a feed story
            self.assertIn(f'<section id="{sid}"', self.html)
        self.assertEqual(self.html.count("<circle"), 24)
        self.assertEqual(len(re.findall(r"<line x1=", self.html)), len([
            e for e in json.loads(_read(os.path.join(FIXTURE, "graph.json")))["data"]["edges"]
            if e["source_node_uuid"] != e["target_node_uuid"]]))
        self.assertIn("Lena Park", self.html)                 # persona table
        self.assertIn("Top posts", self.html)
        self.assertIn("<h2>2. Key actors</h2>", self.html)    # rendered report
        for sid in ["agents", "timeline", "graph", "overview", "socialfeed", "report"]:
            self.assertRegex(self.html, rf'<section id="{sid}"><div class="section-head">')
        self.assertIn("var(--other)", self.html)              # >8 entity types fold into Other

    def test_empty_bundle_renders(self):
        page, md, summary = exporter.render_dashboard({})
        self.assertIn("No graph data", page)
        self.assertIn("No report yet", page)
        self.assertNotIn('id="engine-report"', page)
        self.assertEqual(md, "")

    def test_fallback_timeline_from_actions(self):
        b = exporter.load_run_dir(FIXTURE)
        b.pop("timeline")
        rounds, values, series = exporter.build_timeline(b)
        self.assertEqual(len(rounds), 12)
        self.assertEqual(sum(sum(v) for v in values.values()), len(b["actions"]))

    def test_layout_in_bounds(self):
        pos = exporter.force_layout(30, [(i, (i + 1) % 30) for i in range(30)], [i % 3 for i in range(30)], 1000, 680)
        for x, y in pos:
            self.assertTrue(0 <= x <= 1000 and 0 <= y <= 680)


class CLITests(unittest.TestCase):
    def test_offline_export_via_cli(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "x.html")
            proc = subprocess.run([sys.executable, os.path.join(CLI_DIR, "mirofish.py"), "export",
                                   "--run-dir", FIXTURE, "--out", out], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(json.loads(proc.stdout)["html"], out)
            self.assertTrue(os.path.exists(os.path.join(d, "summary.json")))

    def test_unreachable_backend_is_clean_json_error(self):
        try:
            import requests  # noqa: F401
        except ImportError:
            self.skipTest("requests not installed")
        proc = subprocess.run([sys.executable, os.path.join(CLI_DIR, "mirofish.py"), "--base-url",
                               "http://127.0.0.1:9", "health"], capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(json.loads(proc.stdout)["success"])

    def test_parser_has_all_commands(self):
        p = mirofish.build_parser()
        for cmd in ["health", "run", "upload", "build-graph", "create-sim", "prepare", "start", "status",
                    "report", "chat", "interview", "list", "export", "pitch", "ideas", "quickstart", "captions", "understand", "calibrate", "emailtest", "test", "study"]:
            self.assertIn(cmd, mirofish.COMMANDS)
        a = p.parse_args(["run", "--seed", "a.md", "--requirement", "q", "--max-rounds", "3", "--platform", "reddit"])
        self.assertEqual((a.max_rounds, a.platform), (3, "reddit"))
        self.assertEqual(mirofish.platform_flags("reddit"), {"enable_twitter": False, "enable_reddit": True})


if __name__ == "__main__":
    unittest.main()
