"""World map section and the app shell."""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import exporter  # noqa: E402
import geo_view  # noqa: E402
import shell  # noqa: E402


def bundle():
    idx = [{"agent_id": i, "kind": "persona", "name": f"P{i}", "country": c, "city": city, "settlement": st, "segment": "Parents"}
           for i, (c, city, st) in enumerate([("India", "Pune", "city"), ("IN", "Nashik", "town"), ("Kenya", "Nairobi", "metro"),
                                              ("Atlantis", "Nowhere", "rural")])]
    return {"config": {"persona_index": idx},
            "survey": {"responses": [{"agent_id": 0, "answer": {"would_convert": "yes"}}, {"agent_id": 2, "answer": {"would_convert": "no"}}]},
            "feed_test": {"seed": 5, "sessions": [{"agent_id": 0, "seed": 5, "ad": {"click": True}},
                                                   {"agent_id": 0, "seed": 6, "ad": {"click": True}},
                                                   {"agent_id": 2, "seed": 5, "ad": {}}]},
            "pitch": {"people": [{"agent_id": 2, "final_verdict": "yes", "lead_score": 70}]}}


class GeoTest(unittest.TestCase):
    def test_names(self):
        self.assertEqual(geo_view.geo_name("IN"), "India")
        self.assertEqual(geo_view.geo_name("usa"), "United States of America")
        self.assertEqual(geo_view.geo_name("philippines"), "Philippines")
        self.assertIsNone(geo_view.geo_name("Atlantis"))

    def test_rows_and_section(self):
        rows = {r["country"]: r for r in geo_view.country_rows(bundle())}
        self.assertEqual(rows["India"]["people"], 1)          # "IN" stays its own row but maps to the same shape
        self.assertEqual(rows["India"]["convert"], 100.0)
        self.assertEqual(rows["India"]["ctr"], 100.0)          # only the first seed counts
        self.assertEqual(rows["Kenya"]["pitch"], 100.0)
        self.assertEqual(rows["Kenya"]["lead"], 70)
        anchor, label, html = geo_view.map_section(bundle())
        self.assertEqual(anchor, "worldmap")
        self.assertIn('data-kind="worldmap"', html)
        self.assertIn("(off map)", html)
        spec = json.loads(html.split('data-spec="')[1].split('"></div>')[0].replace("&quot;", '"'))
        self.assertIn("India", [r["name"] for r in spec["rows"]])
        self.assertIsNone(geo_view.map_section({"config": {}}))

    def test_shell_groups_and_dashboard(self):
        side = shell.sidebar([("kpis", "At a glance"), ("feedtest", "Feed test"), ("agents", "People"), ("zzz", "Other")], "Run")
        self.assertLess(side.index("Overview"), side.index("Results"))
        self.assertLess(side.index("Results"), side.index("Tests"))
        self.assertIn('<nav class="toc" data-scrollspy aria-label="Sections">', side)
        b = bundle()
        b.pop("feed_test")
        page, _, _ = exporter.render_dashboard(b, title="T")
        self.assertIn('class="app"', page)
        self.assertIn('id="mm-geo"', page)
        self.assertIn('id="worldmap"', page)


if __name__ == "__main__":
    unittest.main()
