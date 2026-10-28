"""People cards (BDE drawer, behaviour memory, provenance), the models-and-sources card and null-safe rendering.

Fixtures use the real shapes: persona_planner.clean_bde writes persona_index[].bde as
{background, decision_procedure, evaluation}, persona provenance is a dict ({"profile": "real_intake: ..."}), and
behavior_state.json is {"scopes": {scope: {agent_id: {"state", "memory", "trajectory"}}}} in the simulation folder.
"""

import csv
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
FIXTURE = os.path.join(HERE, "fixtures", "sample_run")

import exporter  # noqa: E402
import feed_view  # noqa: E402
import overview  # noqa: E402
import report_view  # noqa: E402
import ui  # noqa: E402

BDE = {
    "background": {"who": "Second-year nursing student who works weekend shifts", "knows": "used two free apps",
                   "believes": ["free trials trap your card", "local creators are honest"], "acquiescence": "high",
                   "social_desirability": "medium", "says_vs_does": "says she will start Monday, rarely does"},
    "decision_procedure": {"who_they_ask": "her sister", "speed": "slow", "style": "satisficer", "risk": "averse",
                           "patience": "low", "triggers": ["a friend already uses it"], "stoppers": ["card upfront"]},
    "evaluation": {"monthly_discretionary": "NPR 1500", "value_priorities": ["price", "offline use"],
                   "pays_for": ["mobile data"], "never_pays_for": ["apps"], "dealbreakers": ["auto-renew"],
                   "trust_cues": ["reviews from people like her"], "discretionary_budget_num": 1500.0},
}
STATE = {"state": {"familiarity": 0.45, "fatigue": 0.6, "trust": 0.3, "mood": "irritated by repeated ads", "energy": 0.5,
                   "wallet_pressure": 0.45},
         "memory": [{"t": "2026-10-19T14:30:16", "test": "feed_test", "kind": "hid_ad", "text": "You hid the Fitloop ad on tiktok.",
                     "source": "tt#1"},
                    {"t": "2026-10-19T14:31:00", "test": "survey", "kind": "objected", "text": "Your biggest hesitation: the card step."}],
         "trajectory": [{"step": 1, "trust": 0.5, "familiarity": 0.1, "fatigue": 0.08},
                        {"step": 2, "trust": 0.3, "familiarity": 0.45, "fatigue": 0.6}]}


def persona(aid, **kw):
    base = {"agent_id": aid, "kind": "persona", "name": f"Person {aid}", "segment": "Nepal students", "country": "Nepal",
            "age": 20, "occupation": "student"}
    base.update(kw)
    return base


GROUNDED = persona(1, name="Asha Rai", bde=BDE, model_provider="grounded", model_name="real_intake",
                   provenance={"demographics": "real_intake: observed", "profile": "real_intake: customer_excerpts",
                               "bde": "real_intake: structured"})
SYNTHETIC = persona(2, name="Bina Gurung", model_provider="gemini",
                    provenance={"demographics": "planner: coupled life-stage slot", "profile": "synthetic: model-written (gemini/x)"})
UNKNOWN = persona(3, name="Chandra KC")                         # an older run: no provider, no provenance


class BdeDrawerTests(unittest.TestCase):
    def test_nested_bde_and_behaviour_record(self):
        html = report_view._bde_inspector_drawer(GROUNDED, STATE)
        for frag in ('class="bde-drawer"', "Spare money a month", "NPR 1500", "auto-renew", "card upfront",
                     "speed slow · style satisficer", "free trials trap your card", "trust 30%", "ad fatigue 60%",
                     "irritated by repeated ads", "50% → 30% over 2 events", "You hid the Fitloop ad on tiktok.",
                     "Decision profile and memory"):
            self.assertIn(frag, html)

    def test_memory_only_and_bde_only(self):
        self.assertIn("Memory from the tests", report_view._bde_inspector_drawer(UNKNOWN, STATE))
        only_bde = report_view._bde_inspector_drawer(GROUNDED, None)
        self.assertIn("Decision profile", only_bde)
        self.assertNotIn("What happened to them", only_bde)

    def test_no_drawer_without_real_data(self):
        flat = persona(4, loss_aversion="high", discretionary_budget="NPR 900", dealbreakers=["x"], life_stage="student_dependent",
                       payday_status="end_of_month_tight", bde={"loss_aversion": "high"})
        self.assertEqual(report_view._bde_inspector_drawer(flat, {}), "")
        self.assertEqual(report_view._bde_inspector_drawer(flat, {"agents": {"4": {"mood": "x"}}}), "")
        self.assertEqual(report_view._bde_inspector_drawer(UNKNOWN, {"state": {"trust": None}, "memory": []}), "")

    def test_behavior_states_reads_scopes(self):
        bundle = {"behavior_state": {"version": 1, "scopes": {"default": {"1": STATE, "2": "junk"}}}}
        self.assertEqual(list(exporter.behavior_states(bundle)), ["1"])
        study = {"behavior_state": {"scopes": {"cell_a": {"1": STATE}, "cell_b": {"1": STATE, "3": STATE}}}}
        self.assertEqual(sorted(exporter.behavior_states(study)), ["1", "3"])       # largest scope when no default
        self.assertEqual(exporter.behavior_states({"behavior_state": {"agents": {"1": {}}}}), {})
        self.assertEqual(exporter.behavior_states({}), {})

    def test_export_copies_behavior_state_from_the_simulation_folder(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        run = os.path.join(tmp, "run")
        shutil.copytree(FIXTURE, run)
        uploads = os.path.join(tmp, "uploads")
        sim_dir = os.path.join(uploads, "simulations", "sim_demo123")
        os.makedirs(sim_dir)
        with open(os.path.join(sim_dir, "behavior_state.json"), "w", encoding="utf-8") as f:
            json.dump({"version": 1, "scopes": {"default": {"1": STATE}}}, f)
        with open(os.path.join(run, "config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        (cfg.get("data") or cfg)["persona_index"] = [GROUNDED, SYNTHETIC]
        with open(os.path.join(run, "config.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        with mock.patch.dict(os.environ, {"MIROFISH_UPLOADS": uploads}):
            bundle = exporter.load_run_dir(run)
        self.assertTrue(os.path.exists(os.path.join(run, "behavior_state.json")))
        self.assertIn("scopes", bundle["behavior_state"])
        html, _, _ = exporter.render_dashboard(bundle)
        self.assertIn("You hid the Fitloop ad on tiktok.", html)
        self.assertIn("NPR 1500", html)                                            # CRM budget column reads the BDE card

    def test_no_copy_without_a_simulation_folder(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        with mock.patch.dict(os.environ, {"MIROFISH_UPLOADS": os.path.join(tmp, "nothing")}):
            self.assertIsNone(exporter.copy_behavior_state(FIXTURE))
        self.assertFalse(os.path.exists(os.path.join(FIXTURE, "behavior_state.json")))


class ProvenanceTests(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(ui.persona_provenance(GROUNDED), "grounded")
        self.assertEqual(ui.persona_provenance(SYNTHETIC), "synthetic")
        self.assertEqual(ui.persona_provenance(UNKNOWN), "")
        self.assertEqual(ui.persona_provenance(persona(9, provenance="real_intake")), "grounded")
        self.assertEqual(ui.persona_provider(GROUNDED), "")                          # "grounded" is a source, not a model
        self.assertEqual(ui.persona_provider(SYNTHETIC), "gemini")

    def test_cards_and_filter(self):
        html = report_view.people_cards([GROUNDED, SYNTHETIC, UNKNOWN], {}, {}, {})
        self.assertEqual(html.count('data-provenance="grounded"'), 2)              # card + CRM row
        self.assertEqual(html.count('data-provenance="synthetic"'), 2)
        self.assertIn("prov-pill-real", html)
        self.assertIn('<option value="grounded">Grounded in real intake (1)</option>', html)
        self.assertIn('<option value="synthetic">Model-written (1)</option>', html)
        self.assertNotIn("Synthetic seeded", html)
        self.assertNotIn('data-provider="grounded"', html)

    def test_no_provenance_filter_without_grounded_people(self):
        html = report_view.people_cards([SYNTHETIC, UNKNOWN], {}, {}, {})
        self.assertNotIn('data-filter="provenance"', html)
        self.assertNotIn('data-filter="provider"', html)                            # one provider: nothing to filter
        self.assertNotIn(">Model</th>", report_view.people_cards([UNKNOWN], {}, {}, {}))

    def test_leads_csv(self):
        text = report_view.leads_csv([GROUNDED, SYNTHETIC, UNKNOWN], {}, {1: 80})
        rows = {r["agent_id"]: r for r in csv.DictReader(io.StringIO(text))}
        self.assertEqual(rows["1"]["provenance"], "grounded")
        self.assertEqual(rows["1"]["provenance_profile"], "real_intake: customer_excerpts")
        self.assertEqual(rows["1"]["model_provider"], "")
        self.assertEqual(rows["2"]["provenance"], "synthetic")
        self.assertEqual(rows["3"]["provenance"], "")
        self.assertNotIn("llm_seeded", text)
        self.assertNotIn("{", text)


class ModelsCardTests(unittest.TestCase):
    def test_hidden_without_a_recorded_provider(self):
        bundle = {"config": {"persona_index": [UNKNOWN, persona(5)]}}
        self.assertEqual(overview.ensemble_card(bundle, {}), "")
        self.assertEqual(overview.active_providers(bundle), [])
        grounded_only = {"config": {"persona_index": [GROUNDED]}}
        self.assertEqual(overview.ensemble_card(grounded_only, {}), "")

    def test_recorded_providers_and_sources(self):
        bundle = {"config": {"persona_index": [GROUNDED, SYNTHETIC, UNKNOWN]}}
        card = overview.ensemble_card(bundle, {})
        self.assertIn('data-prov="gemini"', card)
        self.assertIn("1 grounded in real intake", card)
        self.assertIn("1 model-written", card)
        self.assertIn("1 not recorded", card)
        for filler in ("Active", "synthetic seeded", "claude"):
            self.assertNotIn(filler, card)

    def test_stand_in_writer_is_one_row_not_two(self):
        # 3,000-person run: Gemini (antigravity) wrote 1,000 people that Claude played; the feed test reports them
        # as "antigravity". The card listed both rows ("4 providers", 3,999 people) before.
        bundle = {"config": {"persona_index": [persona(1, model_provider="claude"), persona(2, model_provider="claude"),
                                               persona(3, model_provider="antigravity"), persona(4, model_provider="codex")]},
                  "feed_test": {"summary": {"by_provider": {"claude": {"personas": 2, "expected_ctr": 1.5},
                                                            "antigravity": {"personas": 1, "expected_ctr": 1.2},
                                                            "codex": {"personas": 1, "expected_ctr": 0.4}}}}}
        with mock.patch.dict(os.environ, {"MM_PROVIDER_STANDIN": "antigravity=claude"}):
            card = overview.ensemble_card(bundle, {})
        self.assertEqual(card.count("<tr><td>"), 3)
        self.assertIn("3 writers · 2 answering models", card)
        self.assertIn("Written by", card)
        self.assertIn("Played by", card)
        self.assertNotIn("played by claude)", card)
        self.assertIn("CTR 1.2%", card)
        with mock.patch.dict(os.environ, {"MM_PROVIDER_STANDIN": ""}):
            self.assertIn("3 providers", overview.ensemble_card(bundle, {}))

    def test_dashboard_without_providers_has_no_models_card(self):
        bundle = exporter.load_run_dir(FIXTURE)
        bundle["config"]["persona_index"] = [UNKNOWN]
        html, _, _ = exporter.render_dashboard(bundle)
        self.assertNotIn("Models and sources", html)
        self.assertNotIn('class="ws-provs"', html)


class NullSafetyTests(unittest.TestCase):
    def test_number_helpers(self):
        self.assertIsNone(ui.num(None))
        self.assertIsNone(ui.num("n/a"))
        self.assertIsNone(ui.num(True))
        self.assertIsNone(ui.num(float("nan")))
        self.assertEqual(ui.num("1,008"), 1008.0)
        self.assertEqual(ui.num("4.5%"), 4.5)
        self.assertEqual(ui.fnum(None, ".0f", "%"), "–")
        self.assertEqual(ui.fnum("12", ".0f", "%"), "12%")
        self.assertEqual(ui.rawnum(66.7, "%"), "66.7%")
        self.assertEqual(ui.rawnum("text", "%"), "–")

    def test_competitor_card_never_invents_a_share(self):
        self.assertEqual(feed_view._competitor_shock_html({"impressions": 40, "brand_win_share_pct": None}), "")
        html = feed_view._competitor_shock_html({"impressions": 40, "name": "Gym", "brand_ctr": "3", "competitor_ctr": None,
                                                 "defection_rate": "n/a"})
        self.assertNotIn("50%", html)
        self.assertIn("3% vs –", html)
        self.assertNotIn("Defection", html)

    def test_feed_parts_with_none_and_text(self):
        self.assertIn("–", feed_view._projection_html({"budget": None, "impressions": None, "clicks": "many", "cpm": None,
                                                         "roas": None, "ctr_used": None}))
        lf = feed_view._landing_html({"clicks": 5, "page_loaded": None, "form_started": "x", "converted": 1,
                                      "say_do_gap": "<b>2</b>", "load_rate": None})
        self.assertIn("&lt;b&gt;2&lt;/b&gt;", lf)
        self.assertNotIn("<b>2</b>", lf)
        self.assertNotIn("Page loaded for", lf)
        rows = feed_view._baseline_html({"per_creative": {"a": {"persona_ctr": None, "generic_reader_ctr": "2"}}})
        self.assertIn("–", rows)
        self.assertNotIn("0%", rows)
        self.assertEqual(feed_view._provider_breakdown_html({"claude": {"ctr": None}}), "")
        panel = feed_view.panel_section({"analysts": [{"id": "a1", "lens": "x", "result": None}],
                                         "consensus": {"analysts_ok": None, "sentiment_mean": None, "consensus": "mixed"}})
        self.assertNotIn("None", panel[2])

    def test_pitch_with_missing_numbers(self):
        _, _, html = report_view.pitch_section({"answered": 3, "pitch_score": None, "verdict_after": {"yes": None},
                                               "objections": [{"type": "price", "share": None, "count": "2"}]})
        self.assertNotIn("None", html)
        self.assertNotIn("0%", html)

    def test_waterfall_uses_one_base(self):
        card = overview.funnel_waterfall_card({}, {"funnel": [["Asked", 100], ["Clicked", 50], ["Bought", 25]]})
        self.assertIn("% of asked", card)
        for frag in ("100%", "50%", "25%"):
            self.assertIn(frag, card)
        self.assertNotIn("(50%)", card)                                               # no step-to-step rates mixed in
        self.assertEqual(overview.funnel_waterfall_card({}, {"funnel": [["Asked", None], ["Clicked", "x"]]}), "")

    def test_malformed_sections_do_not_take_down_the_export(self):
        bundle = exporter.load_run_dir(FIXTURE)
        bundle["feed_test"] = {"summary": {"per_creative": {"a": "not a dict"}, "ranked": ["a"]}}
        bundle["gtm_suite"] = {"buying_committee": {"win_rate_pct": "high", "committees": "x"}}
        bundle["competitor_intel"] = {"current_brand_win_share_pct": None}
        bundle["pitch"] = {"answered": 2, "objections": [None, {"type": "x"}], "by_segment": "bad"}
        bundle["analyst_panel"] = {"analysts": [{"id": "a"}], "consensus": "bad"}
        bundle["behavior_state"] = {"scopes": {"default": "bad"}}
        with mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            html, _, _ = exporter.render_dashboard(bundle)
        self.assertIn("</html>", html)
        self.assertIn('<section id="agents">', html)
        self.assertIn("dashboard: skipped", err.getvalue())


if __name__ == "__main__":
    unittest.main()
