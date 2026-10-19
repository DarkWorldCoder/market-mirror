import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import campaign_flow
import experiments


class CampaignFlowTests(unittest.TestCase):
    def test_plan_has_executable_specs_and_evidence(self):
        profile = {"name": "Fitloop", "offer": "Seven-day workout trial", "for_whom": [
            {"segment": "busy parents", "country_hint": "PH", "job_to_be_done": "work out at home"}],
            "differentiators": ["short sessions"], "proofs": []}
        research = [{"text": "short sessions help", "url": "https://example.org/review", "date": "2026-01-01", "market": "PH"}]
        plan = campaign_flow.build(profile, "trial signup", {"amount": 600, "currency": "USD"},
                                   ["search", "organic", "paid_social", "email", "sales", "referral"], research)
        self.assertEqual(len(plan["test_specs"]), 6)
        self.assertEqual(sum(c["allocation"] for c in plan["channels"]), 600)
        self.assertEqual(plan["evidence"][0]["source"], "https://example.org/review")
        for spec in plan["test_specs"]:
            normalized = experiments.normalize(spec)
            self.assertEqual(normalized["metric"], spec["metric"])
            self.assertTrue(normalized["exposure_context"])
            self.assertTrue(normalized["next_real_world_test"])
            if normalized["type"] == "nurture":
                from app.services.email_test import normalize_emails
                normalize_emails(experiments.to_emails(normalized))
        self.assertTrue(any("proof" in x.lower() for x in plan["unknowns"]))

    def test_rejects_unsupported_channel_and_missing_goal(self):
        with self.assertRaises(ValueError):
            campaign_flow.build({"name": "X"}, "", {"amount": 1})
        with self.assertRaises(ValueError):
            campaign_flow.build({"name": "X"}, "signup", {"amount": 1}, ["telepathy"])

    def test_product_profile_platforms_map_to_supported_channels(self):
        plan = campaign_flow.build({"name": "Fitloop", "offer": "Trial",
                                    "channels": ["Instagram", "TikTok", "Facebook", "SEO"]},
                                   "trial signup", {"amount": 100})
        self.assertEqual([c["name"] for c in plan["channels"]], ["paid_social", "organic"])
        thirds = campaign_flow.build({"name": "X"}, "signup", {"amount": 100}, ["search", "email", "sales"])
        self.assertEqual(sum(round(c["allocation"] * 100) for c in thirds["channels"]), 10000)


if __name__ == "__main__":
    unittest.main()
