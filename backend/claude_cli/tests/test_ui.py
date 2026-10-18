"""Shared dashboard helpers (ui.py) and design tokens (tokens.py): no LLM, no backend."""

import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import feed_view  # noqa: E402
import marketing  # noqa: E402
import report_view  # noqa: E402
import social_feed  # noqa: E402
import tokens  # noqa: E402
import ui  # noqa: E402


class HelperTests(unittest.TestCase):
    def test_esc_and_raw(self):
        self.assertEqual(ui.esc('<b>"x"</b>'), "&lt;b&gt;&quot;x&quot;&lt;/b&gt;")
        self.assertEqual(ui.esc(None), "")
        self.assertEqual(ui.esc(ui.Raw("<b>ok</b>")), "<b>ok</b>")

    def test_trunc_keeps_newlines_unless_collapsed(self):
        self.assertEqual(ui.trunc("a\nb", 10), "a\nb")
        self.assertEqual(ui.trunc("a \n  b", 10, collapse=True), "a b")
        self.assertEqual(ui.trunc("abcdefgh", 5), "abcd…")

    def test_pct_ci_and_low_n(self):
        self.assertEqual(ui.pct_ci(None, 10), "–")
        self.assertEqual(ui.pct_ci(50, 100), "50% ±10")
        self.assertEqual(ui.ci(50, 0), None)
        self.assertIn("low n=4", ui.low_n_pill(4))
        self.assertEqual(ui.low_n_pill(40), "")
        self.assertEqual(ui.low_n_pill(4, threshold=3), "")

    def test_pill_and_kpi(self):
        self.assertEqual(ui.pill(""), "")
        self.assertEqual(ui.pill("yes", "mint"), '<span class="pill mint">yes</span>')
        k = ui.kpi("42%", "Would click", "+3% maybe", delta="-2 pt", hl=True)
        for frag in ('class="kpi hl"', '<div class="v">42%</div>', '<div class="k">Would click</div>', '<div class="h">+3% maybe</div>',
                     '<div class="d down">-2 pt</div>'):
            self.assertIn(frag, k)
        self.assertIn('class="d up"', ui.kpi(1, "x", delta="+1"))
        self.assertNotIn('class="h"', ui.kpi(1, "x"))

    def test_section_head(self):
        h = ui.section_head("Sales & marketing", "intro <i>", "Trust is the blocker", aside=ui.Raw('<div class="dl">b</div>'))
        self.assertTrue(h.startswith('<div class="section-head"><div class="sh-row"><div class="sh-text"><h2>Sales &amp; marketing</h2>'))
        self.assertIn('<p class="intro muted small">intro &lt;i&gt;</p>', h)
        self.assertIn('<div class="dl">b</div></div>', h)
        self.assertIn('<div class="callout insight" role="note">Trust is the blocker</div>', h)
        self.assertLess(h.index("</h2>"), h.index("callout insight"))
        self.assertNotIn("callout", ui.section_head("Plain"))

    def test_table_numeric_detection_sortable_and_summary(self):
        t = ui.table(["Segment", "People", "Share"], [["A", 3, "40%"], ["B <x>", 10, "–"]])
        self.assertIn('<table class="sortable">', t)
        self.assertIn('<th data-sort="text" aria-sort="none" scope="col">Segment</th>', t)
        self.assertIn('<th class="num" data-sort="num" aria-sort="none" scope="col">People</th>', t)
        self.assertIn('<th class="num" data-sort="num" aria-sort="none" scope="col">Share</th>', t)
        self.assertIn("<td>B &lt;x&gt;</td><td class=num>10</td><td class=num>–</td>", t)
        d = ui.table(["a", "b"], [[1, ui.Raw("<b>raw</b>")]], summary="Show the numbers", sortable=False)
        self.assertTrue(d.startswith('<details class="tv"><summary>Show the numbers</summary>'))
        self.assertIn("<table><thead>", d)
        self.assertNotIn("aria-sort", d)
        self.assertIn("<b>raw</b>", d)

    def test_modules_share_the_helpers(self):
        self.assertIs(feed_view.PLATFORM_LABEL, ui.PLATFORM_LABEL)
        self.assertIs(social_feed.PLATFORM_LABEL, ui.PLATFORM_LABEL)
        self.assertEqual(ui.PLATFORM_LABEL["twitter"], "X / Twitter")
        self.assertIs(feed_view._e, ui.esc)
        self.assertIs(marketing._e, ui.esc)
        self.assertIs(report_view._pill, ui.pill)
        self.assertIs(marketing._pct_ci, ui.pct_ci)
        self.assertIs(feed_view.low_n_pill, ui.low_n_pill)


class ScriptAndTokenTests(unittest.TestCase):
    def test_scripts_are_inline_safe(self):
        for js in (ui.UI_JS, ui.HEAD_JS, marketing.MARKETING_JS, social_feed.SOCIAL_JS, feed_view.FEED_JS):
            self.assertNotIn("</script>", js)
        self.assertIn("localStorage.getItem('mm-theme')", ui.HEAD_JS)
        self.assertTrue(ui.HEAD_JS.startswith("try{") and ui.HEAD_JS.endswith("catch(e){}"))
        for frag in ("data-theme-toggle", "data-scrollspy", "table.sortable", "aria-sort", "data-filter-root", "data-filter-count",
                     "beforeprint", "window.MM="):
            self.assertIn(frag, ui.UI_JS)
        # the module scripts read the chart theme from ui, not from private copies
        self.assertIn("window.MM.theme()", marketing.MARKETING_JS)
        self.assertIn("window.MM.theme()", social_feed.SOCIAL_JS)
        self.assertNotIn("getPropertyValue", marketing.MARKETING_JS)
        self.assertNotIn("getPropertyValue", social_feed.SOCIAL_JS)

    def test_tokens_define_palette_once_and_dark_twice(self):
        css = tokens.TOKENS_CSS
        self.assertEqual(css.count("--bg:#eeeeea"), 1)
        self.assertEqual(css.count("--bg:#0d0d0c"), 2)
        self.assertIn('@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){', css)
        self.assertIn(':root[data-theme="dark"]{', css)
        dark_blocks = re.findall(r'(?:data-theme="light"\]\)|data-theme="dark"\])\{([^}]+)\}', css)
        self.assertEqual(len(dark_blocks), 2)
        self.assertEqual(dark_blocks[0], dark_blocks[1])              # ONE dark block, reused
        for var in ("--line", "--mono", "--font-sans", "--r-xl", "--shadow-2", "--ease", "--mm-yes", "--mm-maybe", "--mm-no", "--s8"):
            self.assertIn(var + ":", css)
        for cls in (".kpi{", ".kpi .v{", ".kpi .d.up{", ".pill.mint{", ".pill.accent{", ".pill.orchid{", ".pill.sky{",
                    ".pill.neutral{", ".callout{", ".callout.insight{", ".section-head{", ".voices{", "blockquote.voice{",
                    ".filter-bar{", "table.sortable th[aria-sort=\"ascending\"]::after", ":focus-visible", "prefers-reduced-motion"):
            self.assertIn(cls, css)

    def test_old_palette_blocks_are_gone(self):
        import exporter
        self.assertNotIn(":root{", exporter.CSS)
        self.assertNotIn(":root{", marketing.MARKETING_CSS)
        self.assertNotIn("prefers-color-scheme:dark", marketing.MARKETING_CSS)
        self.assertNotIn(".tile{", exporter.CSS)
        self.assertNotIn(".hero-stats", marketing.MARKETING_CSS)
        self.assertNotIn(".proj-g .v", feed_view.FEED_CSS)
        self.assertNotIn("\n.grid2{", report_view.REPORT_CSS)
        self.assertNotIn("tile-v", report_view.REPORT_CSS)
        self.assertIn(".mixbar .yes{background:var(--mm-yes)}", report_view.REPORT_CSS)
        self.assertIn("var(--mono)", report_view.REPORT_CSS)
        self.assertNotIn("var(--mono,", report_view.REPORT_CSS)


if __name__ == "__main__":
    unittest.main()
