"""One market, several providers: the survey split by the provider that wrote and answered for each person."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import marketing  # noqa: E402


def bundle(providers):
    index, responses = [], []
    for i, prov in enumerate(providers):
        index.append({"agent_id": i, "kind": "persona", "name": f"P{i}", "segment": "S", "country": "IN",
                      "model_provider": prov})
        yes = (prov == "codex") or i % 3 == 0
        responses.append({"agent_id": i, "answer": {"would_click": "yes", "would_convert": "yes" if yes else "no",
                                                    "objection_type": "price" if prov != "antigravity" else "trust",
                                                    "main_objection": "costs money"}})
    return {"config": {"persona_index": index}, "survey": {"responses": responses}}


class ModelsAgreeTest(unittest.TestCase):
    def test_breakdown_and_checks_per_provider(self):
        a = marketing.analyze(bundle(["claude_code"] * 10 + ["codex"] * 10 + ["antigravity"] * 10))
        self.assertEqual({g["key"] for g in a["by_provider"]}, {"claude_code", "codex", "antigravity"})
        pa = a["provider_agreement"]
        codex = next(r for r in pa["providers"] if r["provider"] == "codex")
        self.assertEqual((codex["n"], codex["convert_yes"]), (10, 100.0))
        self.assertLess(codex["lo"], 100.0)
        self.assertIs(pa["checks"]["top_objection"], False)
        self.assertIsNotNone(pa["gap"])
        sec = marketing.models_section(a)
        self.assertEqual(sec[0], "models")
        self.assertIn("Do the models agree?", sec[2])
        self.assertIn("antigravity", sec[2])

    def test_single_provider_has_no_section(self):
        a = marketing.analyze(bundle(["claude"] * 6))
        self.assertEqual(a["by_provider"], [])
        self.assertIsNone(marketing.models_section(a))


if __name__ == "__main__":
    unittest.main()
