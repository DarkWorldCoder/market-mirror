"""Pictures on the CLI side: local images and video keyframes become data URIs, ffmpeg is optional, and the feed-test
card shows what the buyers saw."""

import base64
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import feed_view  # noqa: E402
import market_cli  # noqa: E402

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


class Visuals(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        with open(os.path.join(self.d, "ad.png"), "wb") as f:
            f.write(PNG)

    def test_local_image_becomes_a_data_uri_and_a_thumbnail(self):
        logs = []
        crs = [{"id": "a", "image": "ad.png"}, {"id": "b", "image": "missing.png"}, {"id": "c", "image": "https://x.io/a.png"}]
        thumbs = market_cli.load_visuals(crs, self.d, logs.append)
        self.assertTrue(crs[0]["image"].startswith("data:image/png;base64,"))
        self.assertNotIn("image", crs[1])
        self.assertEqual(crs[2]["image"], "https://x.io/a.png")
        self.assertEqual(set(thumbs), {"a", "c"})
        self.assertTrue(any("missing" in m or "not found" in m for m in logs))

    def test_video_needs_ffmpeg(self):
        open(os.path.join(self.d, "ad.mp4"), "wb").close()
        with mock.patch("shutil.which", return_value=None):
            with self.assertRaises(ValueError) as e:
                market_cli.video_frames("ad.mp4", self.d)
        self.assertIn("ffmpeg", str(e.exception))
        with self.assertRaises(ValueError):
            market_cli.video_frames("nope.mp4", self.d)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
    def test_video_keyframes_with_ffmpeg(self):
        path = os.path.join(self.d, "clip.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=64x112:d=4", "-pix_fmt", "yuv420p",
                        "-y", path], check=True, timeout=120)
        crs = [{"id": "v", "video": "clip.mp4"}]
        thumbs = market_cli.load_visuals(crs, self.d, lambda m: None)
        self.assertEqual(len(crs[0]["frames"]), 3)                      # 0 s, 1 s, 3 s (no middle frame under 6 s)
        self.assertTrue(all(f.startswith("data:image/jpeg") for f in crs[0]["frames"]))
        self.assertEqual(crs[0]["format"], "video")
        self.assertEqual(thumbs["v"], crs[0]["frames"][0])


class Card(unittest.TestCase):
    def test_feed_card_shows_what_the_buyers_saw(self):
        visual = {"description": "A runner at sunrise.", "on_image_text": "Run free", "first_glance": "Running app",
                  "frames": 1, "passed": 1,
                  "checks": [{"check": "brand_early", "label": "Brand early", "pass": True, "note": "logo", "source": "model"},
                             {"check": "aspect_ratio", "label": "Aspect ratio fits", "pass": False, "note": "60x30",
                              "source": "measured"}]}
        ft = {"creatives": [{"id": "ig1", "platform": "instagram", "text": "Run", "visual": visual, "media_brief": "sunrise run"}],
              "summary": {"per_creative": {"ig1": {"impressions": 10, "ctr": 2.0, "thumb_stop": 20.0, "engagement_rate": 5.0}},
                          "ranked": ["ig1"]}, "personas_tested": 10, "feeds": 10}
        html = feed_view.feed_section(ft, lambda *a, **k: "")[2]
        self.assertIn("What the buyers saw", html)
        self.assertIn("1 of 2 checks pass", html)
        self.assertIn("(measured)", html)
        self.assertIn("not a measured attention or recall score", html)
        self.assertIn("sunrise run", html)


if __name__ == "__main__":
    unittest.main()
