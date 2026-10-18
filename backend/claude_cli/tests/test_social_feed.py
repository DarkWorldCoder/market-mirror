"""Social feed dashboard section rendered from fixtures/sample_run/feed_story.json (no LLM, no backend)."""

import json
import os
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import exporter  # noqa: E402
import marketing  # noqa: E402
import social_feed  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "sample_run")


def _story():
    with open(os.path.join(FIXTURE, "feed_story.json"), encoding="utf-8") as f:
        return json.load(f)


class SocialFeedSectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.story = _story()
        cls.section = social_feed.feed_story_section(cls.story, marketing.chart)
        cls.anchor, cls.label, cls.html = cls.section

    def test_anchor_and_label(self):
        self.assertEqual(self.anchor, "socialfeed")
        self.assertEqual(self.label, "Social feed")

    def test_two_platform_tabs_and_panels(self):
        tabs = re.findall(r'<button type="button" data-tab="(\w+)"', self.html)
        self.assertEqual(tabs, ["twitter", "reddit"])
        self.assertIn('data-panel="twitter">', self.html)
        self.assertIn('data-panel="reddit" hidden>', self.html)

    def test_round_slider_spans_all_rounds(self):
        m = re.search(r'<input type="range" min="-1" max="(\d+)" value="-1"', self.html)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "2")
        self.assertIn("all rounds", self.html)

    def test_one_card_per_post_with_filter_attributes(self):
        cards = re.findall(r'<article class="sf-card pm (pm-x|pm-rd)" ([^>]+)>', self.html)
        self.assertEqual(len(cards), 4)                               # 3 twitter + 1 reddit
        self.assertEqual([c[0] for c in cards], ["pm-x", "pm-x", "pm-x", "pm-rd"])
        attrs = cards[1][1]
        for frag in ['data-platform="twitter"', 'data-round="1"', 'data-segment="Students"', 'data-country="Brazil"',
                     'data-brand="0"', 'data-score="3"', 'data-id="2"']:
            self.assertIn(frag, attrs)
        self.assertIn('data-brand="1"', cards[0][1])

    def test_card_content_round_quote_and_counts(self):
        h = self.html
        self.assertIn("round 1 · 19:00", h)
        self.assertIn("Flat tuition but the fees went up", h)
        self.assertIn('<div class="sf-q"><b>Riverside University</b>', h)   # quoted original
        self.assertIn("reposted Riverside University", h)                   # repost card
        self.assertIn('title="liked by Omar Haddad"', h)                   # liker names on hover
        self.assertIn("2 comments", h)                                      # reddit comments in <details>
        self.assertIn("[neg] Terrible, the hidden fees are the catch.", h)

    def test_segment_and_country_filters(self):
        self.assertIn('<option value="Students">Students (2)</option>', self.html)
        self.assertIn('<option value="Parents">Parents (1)</option>', self.html)
        self.assertIn('<option value="Brazil">Brazil (2)</option>', self.html)
        self.assertIn("data-brand", self.html)
        self.assertIn("data-sort", self.html)

    def test_post_content_is_escaped(self):
        self.assertNotIn("<script>alert(1)</script>", self.html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", self.html)
        # the only script element is the JSON index
        scripts = re.findall(r"<script[^>]*>", self.html)
        self.assertEqual(scripts, ['<script type="application/json" data-sf-index>'])

    def test_brand_table(self):
        h = self.html
        self.assertIn("<h3>Brand posts</h3>", h)
        row = re.search(r'<table class="sf-brand-t">.*?<tbody>(.*?)</tbody>', h, re.S).group(1)
        self.assertEqual(row.count("<tr>"), 1)
        self.assertIn("X / Twitter", row)
        self.assertIn("round 0 · 00:00 · initial_post", row)
        self.assertIn('<td class="num">2</td><td class="num">1</td><td class="num">1</td><td class="num">0</td><td class="num">7</td>', row)
        self.assertIn('title="0 positive, 0 neutral, 1 negative replies (lexicon)"', row)
        self.assertIn('<span class="pill neg">neg</span> <b>Ana Souza</b>', row)   # best reply
        self.assertNotIn("alert(1)</script>", row)

    def test_round_chart_uses_chart_callable(self):
        charts = re.findall(r'data-kind="sfrounds"[^>]*data-spec="([^"]+)"', self.html)
        self.assertEqual(len(charts), 2)
        spec = json.loads(charts[0].replace("&quot;", '"').replace("&#x27;", "'").replace("&amp;", "&"))
        self.assertEqual(spec["cats"], ["r0 · 00:00", "r1 · 19:00", "r2 · 20:00"])
        self.assertEqual(spec["posts"], [1, 1, 1])
        self.assertEqual(spec["likes"], [0, 3, 2])

    def test_empty_story_gives_no_section(self):
        self.assertIsNone(social_feed.feed_story_section({}, marketing.chart))
        self.assertIsNone(social_feed.feed_story_section({"platforms": {"twitter": {"posts": []}}}, marketing.chart))

    def test_cap_300_posts_per_platform(self):
        base = self.story["platforms"]["twitter"]["posts"][1]
        many = [dict(base, post_id=100 + i, round=i % 4) for i in range(350)]
        story = {"platforms": {"twitter": {"posts": many, "rounds": [], "total_posts": 350}}, "brand_posts": []}
        _, _, h = social_feed.feed_story_section(story, marketing.chart)
        self.assertEqual(h.count('<article class="sf-card'), 300)
        self.assertIn("Showing the first 300 of 350 posts", h)

    def test_css_and_js_are_strings_for_the_exporter(self):
        self.assertIn(".sf-feed", social_feed.SOCIAL_CSS)
        self.assertIn("data-sf-root", social_feed.SOCIAL_JS)
        self.assertNotIn("</script>", social_feed.SOCIAL_JS)


class ExporterStillWorksTests(unittest.TestCase):
    def test_export_run_dir_ignores_the_fixture_until_wired(self):
        tmp = tempfile.mkdtemp()
        paths = exporter.export_run_dir(FIXTURE, os.path.join(tmp, "dash.html"))
        with open(paths["html"], encoding="utf-8") as f:
            html_ = f.read()
        self.assertIn("<title>", html_)
        self.assertTrue(os.path.getsize(paths["summary_json"]) > 0)


if __name__ == "__main__":
    unittest.main()
