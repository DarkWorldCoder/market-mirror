"""Marketing and sales tests answered by the simulated people: engines, CRO lab, thoughts and their dashboard view."""

import json
import os
import sys
from types import SimpleNamespace

import pytest

from app.services import agent_thoughts as at
from app.services import cro_and_sparring as cro
from app.services import gtm_suite as g

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "claude_cli"))
import gtm_view  # noqa: E402


def people(n=12):
    segs = ["Restaurant owners", "Cafe managers", "Food truck operators"]
    return [{"agent_id": i, "name": f"P{i}", "age": 30 + i, "country": "Kenya", "segment": segs[i % 3],
             "persona": f"Runs a small food business, person {i}.", "bde": {"evaluation": {"monthly_discretionary": "USD 200"}}}
            for i in range(n)]


class Fake:
    """Answers by what the prompt asks for; `fail` makes every n-th person call fail."""

    def __init__(self, fail_every=0):
        self.calls = 0
        self.fail_every = fail_every
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
        self.base_url = "http://fake"

    def create(self, **kw):
        self.calls += 1
        msgs = kw["messages"]
        sys_p, prompt = msgs[0]["content"], msgs[-1]["content"]
        person = "simulated person" in sys_p
        if person and self.fail_every and any(f"P{k}, " in prompt for k in range(0, 100, self.fail_every)):
            raise RuntimeError("upstream failed")                       # the same people fail on every retry
        data = self.answer(prompt, person)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(data)), finish_reason="stop")],
                               usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))

    def answer(self, p, person):
        if '"setting"' in p:
            return {"setting": "work", "participants": [{"role": "Owner", "says": "Looks handy", "privately_thinks": "Is it worth it?",
                                                         "stance": "maybe", "concern_type": "price"},
                                                        {"role": "Accountant", "says": "Too pricey", "privately_thinks": "No", "stance": "no"}],
                    "outcome": "wait", "deciding_voice": "Accountant", "blocker": "Monthly cost", "blocker_type": "price",
                    "what_would_unblock": "A cheaper starter plan"}
        if '"p_click"' in p and "stopped" in p:
            better = "No setup fee" in p
            return {"stopped": True, "p_click": 0.5 if better else 0.2, "reaction": "hmm",
                    "objection": "setup fee" if not better else "", "objection_type": "price" if not better else "none"}
        if "Rewrite this ad" in p:
            return {"headline": "No setup fee", "text": "Start today. No setup fee.", "cta": "Book a demo",
                    "change_summary": "Answers the setup fee worry", "angle": "cost"}
        if "what would make you hesitate" in p:
            return {"objection": "I don't trust new software", "objection_type": "trust"}
        if "sales battlecard" in p:
            return {"objections": [{"type": "trust", "buyer_says": "Not sure", "rebuttal": "You can cancel any time.",
                                    "discovery_question": "What worried you before?", "proof_to_prepare": "Customer references",
                                    "avoid_saying": "Trust me", "extra": "82% of users love it"}],
                    "outreach": [{"step": 1, "day": 0, "channel": "email", "message": "Hello"}], "qualification_questions": ["Who decides?"]}
        if '"moved"' in p:
            return {"moved": "somewhat", "reply": "Ok, maybe", "still_worried_about": "data"}
        if "four-step customer journey" in p:
            return {"touches": [{"name": n, "channel": "email", "day": str(i), "text": f"{n} text"}
                                for i, n in enumerate(["first ad", "reminder", "offer page", "follow-up"])]}
        if '"action": "ignore|notice|click"' in p:
            return {"action": "click", "why": "curious"}
        if '"action": "leave|sign_up|buy"' in p:
            return {"action": "sign_up", "why": "worth a try"}
        if '"would_recommend"' in p:
            return {"action": "keep_using", "why": "useful", "would_recommend": True}
        if "package and price THIS offer" in p:
            return {"options": [{"name": "Basic", "price": 29, "billing": "per month", "includes": "POS"},
                                {"name": "Pro", "price": 59, "billing": "per month", "includes": "POS and stock"}]}
        if '"max_price_you_would_pay"' in p:
            return {"choice": "A" if "A) Basic" in p.split("Your options:")[1].split("\n")[1] else "B", "why": "fits", "max_price_you_would_pay": 40}
        if "You are choosing between" in p:
            return {"choice": "Square", "why": "already know it", "what_would_make_you_choose_Tillpoint": "A free month"}
        if "Suggest up to five concrete changes" in p:
            return {"suggestions": [{"title": "Free first month", "change": "Offer it", "evidence": "people chose Square, 99 of them",
                                     "kind": "pricing", "effort": "low"}]}
        if "In the first five seconds" in p:
            return {"what_is_it": "a till system", "who_is_it_for": "shops", "would_continue": "yes", "read_until": "middle",
                    "confusing": "pricing", "confusing_type": "price", "missing_to_decide": "contract length", "noticed_trust_signal": ""}
        if "Grade each answer" in p:
            return {"grades": [{"i": i, "grade": "correct"} for i in range(50)]}
        if "salesperson contacts you" in p:
            return {"replies": ["who is this?", "ok"], "outcome": "maybe_later", "scores": {"clear": 4, "relevant_to_me": 3, "trustworthy": 3, "pushy": 2},
                    "what_they_should_have_said": "the price", "lost_me_at": 2}
        if "Pick three attributes" in p:
            return {"attributes": {"price": ["29", "19"], "contract": ["monthly", "yearly"]}}
        if '"choices"' in p:
            n = p.count("Choice ")
            return {"choices": ["A"] * n, "what_mattered_most": "price"}
        if "for the audience" in p:
            return {"headline": "No setup fee", "text": "No setup fee for cafes", "cta": "Try", "angle": "cost"}
        if '"gut"' in p:
            return {"thought": "Interesting but pricey", "gut": "curious", "weighing": "budget", "roadblock": "price",
                    "private_verdict": "maybe", "would_do": "scroll past", "conviction_0_10": 4}
        return {}


OFFER = {"name": "Tillpoint", "headline": "Tillpoint POS", "text": "Point of sale for small restaurants", "price": "USD 29 per month"}


def test_stats_helpers():
    w = g.wilson(5, 20)
    assert w["pct"] == 25.0 and w["lo"] < 25 < w["hi"]
    assert g.wilson(0, 0)["pct"] is None
    assert g.verdict_from_ci({"lo": 0.1, "hi": 0.3}) == "better" and g.verdict_from_ci({"lo": -0.1, "hi": 0.3}) == "no clear difference"
    with pytest.raises(ValueError):
        g.offer_dict(None, None)


def test_engines_need_a_model():
    with pytest.raises(ValueError):
        g.run_buying_committee(None, "m", OFFER, people())


def test_committee_counts_failures_and_aggregates():
    res = g.run_buying_committee(Fake(fail_every=4), "m", OFFER, people(12), committee_count=12, parallel=1)
    assert res["asked"] == 12 and res["failed"] == 3 and res["answered"] == 9
    assert res["summary"]["outcomes"]["wait"]["k"] == 9
    assert res["summary"]["blockers"][0]["key"] == "price"
    assert any(r["key"] == "accountant" for r in res["summary"]["roles_saying_no"])


def test_creative_optimizer_paired_lift():
    res = g.run_creative_optimizer(Fake(), "m", {"text": "Tillpoint POS. Setup fee applies.", "cta": "Book a demo"}, people(10),
                                   generations=2, cohort_size=10, parallel=1)
    gens = res["summary"]["generations"]
    assert len(gens) == 2 and gens[1]["vs_original"]["verdict"] == "better"
    assert res["summary"]["best_generation"] == 2


def test_battlecard_from_asked_objections_with_number_guard():
    res = g.run_sales_battlecard(Fake(), "m", people(8), offer=OFFER, cohort_size=8)
    s = res["summary"]
    assert s["objection_sources"] == {"asked": 8}
    assert "82%" not in json.dumps(s["card"])                         # invented statistic dropped by the guard
    assert s["rebuttal_test"][0]["tested_on"] == 8 and s["rebuttal_test"][0]["moved_somewhat"]["pct"] == 100.0


def test_journey_funnel_and_economics():
    res = g.run_journey_simulation(Fake(), "m", OFFER, people(6), cohort_size=6, spend=600, audience=1000, price=29)
    s = res["summary"]
    assert [f["k"] for f in s["funnel"]] == [6, 6, 6, 6]
    assert s["touches_generated"] is True and s["economics"]["cost_per_signup"] == 0.6


def test_pricing_shares_sum_to_100():
    res = g.run_pricing_conjoint(Fake(), "m", people(10), offer=OFFER, currency="USD", cohort_size=10)
    s = res["summary"]
    total = sum(o["share"]["k"] for o in s["options"]) + s["none"]["share"]["k"]
    assert total == res["answered"] == 10 and s["options_generated"] is True


def test_competitors_need_input_and_use_real_choices():
    none = g.run_competitor_intelligence(Fake(), "m", OFFER, people())
    assert none["summary"]["available"] is False and none["asked"] == 0
    res = g.run_competitor_intelligence(Fake(), "m", OFFER, people(9), competitors=["Square"], cohort_size=9,
                                        moves=["Square cuts its price by 30%"])
    opts = {o["name"]: o["share"]["k"] for o in res["summary"]["options"]}
    assert opts["Square"] == 9 and opts["Tillpoint"] == 0
    assert "99" not in json.dumps(res["summary"]["suggestions"])        # a count that is not in the facts is dropped
    assert res["summary"]["moves"][0]["people"] == 9


def test_cro_lab_engines():
    t = cro.run_landing_teardown(Fake(), "m", "Tillpoint: the till for small restaurants. Pricing below...", people(6),
                                 cohort_size=6, profile={"one_liner": "POS for restaurants"})
    assert t["summary"]["understood"]["correct"]["k"] == 6
    r = cro.run_sales_roleplay(Fake(), "m", people(4), offer=OFFER, rep_messages=["Hi, quick question", "Can I call?"], cohort_size=4)
    assert r["summary"]["outcomes"]["maybe_later"]["k"] == 4 and r["summary"]["scores"]["clear"]["mean"] == 4
    w = cro.run_causal_whatif_model(people(10), client=Fake(), model="m", offer=OFFER, cohort_size=10)
    assert w["summary"]["effects"] and all("verdict" in e for e in w["summary"]["effects"])
    p = cro.run_segment_personalizer(Fake(), "m", OFFER, people(9), creative={"text": "Setup fee applies"}, segments=2, per_segment=3)
    assert len(p["summary"]["segments"]) == 2 and p["summary"]["segments"][0]["difference"]["verdict"] in ("better", "too few answers", "no clear difference")
    with pytest.raises(ValueError):
        cro.run_sales_roleplay(Fake(), "m", people(2), rep_messages=[])


def test_thoughts_simulation_and_harvest(tmp_path):
    res = at.run_thought_simulation(Fake(fail_every=5), "m", "Tillpoint POS, USD 29", people(10), max_personas=10, parallel=1)
    assert res["asked"] == 10 and res["failed"] == 2 and res["thought_test"]["people"] == 8
    assert res["thought_test"]["said_yes_but_would_not_act"]["k"] == 8
    (tmp_path / "survey.json").write_text(json.dumps({"responses": [{"agent_id": 1, "answer": {"main_objection": "price", "would_convert": "no"}}]}))
    (tmp_path / "actions.json").write_text(json.dumps([{"agent_id": 2, "action_type": "CREATE_POST", "action_args": {"content": "hi"}},
                                                        {"agent_id": 3, "action_type": "LIKE_POST", "action_args": {}}]))
    h = at.harvest_thoughts(str(tmp_path))
    assert h["by_kind"] == {"said": 1, "posted": 1}                     # a like with no text adds nothing


def test_dashboard_view_renders_real_results_only():
    f = Fake()
    bundle = {
        "buying_committee": g.run_buying_committee(f, "m", OFFER, people(6), committee_count=6),
        "creative_optimizer": g.run_creative_optimizer(f, "m", {"text": "Setup fee applies"}, people(6), generations=2, cohort_size=6),
        "pricing_conjoint": g.run_pricing_conjoint(f, "m", people(6), offer=OFFER, cohort_size=6),
        "competitor_intel": g.run_competitor_intelligence(f, "m", OFFER, people(6), competitors=["Square"], cohort_size=6),
        "landing_teardown": cro.run_landing_teardown(f, "m", "page text", people(4), cohort_size=4),
        "thought_stream": at.run_thought_simulation(f, "m", "Tillpoint", people(4), max_personas=4),
    }
    html = "".join(sec[2] for sec in (gtm_view.lab_section(bundle), gtm_view.competitor_section(bundle),
                                      gtm_view.cro_lab_section(bundle), gtm_view.thoughts_section(bundle)) if sec)
    for word in ("YouTube", "WhatsApp", "fitness", "82%", "LTV:CAC", "win share"):
        assert word not in html
    assert "simulated people answered" in html and "Square" in html
    assert gtm_view.lab_section({}) is None and gtm_view.thoughts_section({}) is None
