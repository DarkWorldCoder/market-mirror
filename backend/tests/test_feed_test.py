"""Feed test and analyst panel with a mocked LLM: assignment, social proof, landing page, metrics, API."""

import json
import re
import threading
from types import SimpleNamespace

import pytest

from app.services import analyst_panel as ap
from app.services import feed_test as ft


class FakeLLM:
    """Students click Instagram ads; parents comment on Facebook; Reddit downvotes; slow pages lose people."""

    def __init__(self):
        self.prompts = []
        self.lock = threading.Lock()
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        system, user = kw["messages"][0]["content"], kw["messages"][1]["content"]
        with self.lock:
            self.prompts.append((system, user))
        if system == ft.ORGANIC_SYSTEM:
            body = {"posts": [{"kind": "friend", "author": f"Friend {i}", "text": f"post {i}", "media": ""} for i in range(8)]}
        elif system == ft.LANDING_SYSTEM:
            body = {"read": True, "started_form": True, "completed": "phone" not in user.lower(),
                    "drop_reason": "did not want to give my phone number", "thought": "ok"}
        elif system == ft.GENERIC_READER_SYSTEM:
            body = {"scores": [{"id": "ig1", "expected_ctr": 2.0, "thumb_stop": 25.0, "appeal_0_10": 7.5,
                                "top_concern": "price", "verdict": "winner"}]}
        elif system == ft.SYSTEM_PROMPT:
            ids = re.findall(r"^\[(i\d+)\]", user, re.M)
            ad_line = next(l for l in user.splitlines() if "· Sponsored" in l or "· Promoted" in l)
            ad_id = re.match(r"\[(i\d+)\]", ad_line).group(1)
            student = "Student" in user
            platform = "Instagram" if "Instagram" in user else "Reddit" if "Reddit" in user else "Facebook"
            items = []
            for i in ids:
                a = {"id": i, "stopped": False, "dwell_seconds": 0.4, "reaction": "none", "comment": "", "share": "none",
                     "click": False, "hide": False, "thought": "scroll"}
                if i == ad_id:
                    if platform == "Instagram" and student:
                        a.update(stopped=True, dwell_seconds=4, reaction="like", click=True, thought="nice")
                    elif platform == "Facebook" and not student:
                        a.update(stopped=True, dwell_seconds=6, reaction="love", comment="Is it really free?", share="send")
                    elif platform == "Reddit":
                        a.update(stopped=True, dwell_seconds=2, reaction="downvote", comment="ad spam", hide=True)
                items.append(a)
            body = {"items": items}
        else:  # analyst panel
            lens = re.search(r"Your lens: ([^.]+)\.", user).group(1)
            body = {"headline": f"{lens} view", "sentiment": 20 if "Sceptical" not in lens else -10,
                    "purchase_intent_signal": 6, "best_audience": "Students" if "Copywriter" not in lens else "Parents",
                    "best_message": "#1", "themes": [{"theme": "free practice test", "weight": 8, "evidence": "Is it really free?"},
                                                     {"theme": lens.split()[0] + " angle", "weight": 3, "evidence": ""}],
                    "objections": ["scam fears"], "opportunities": ["parents"], "risks": [], "recommendation": "test more",
                    "confidence": 6, "evidence_gaps": "small sample"}
        msg = SimpleNamespace(content=json.dumps(body))
        return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")])


def people(n=12):
    out = []
    for i in range(n):
        student = i % 2 == 0
        out.append({"agent_id": i, "name": f"Name{i} Last", "persona": "Student who loves learning" if student else "Parent paying fees",
                    "age": 18 if student else 45, "gender": "female", "country": "Nepal",
                    "segment": "Students" if student else "Parents", "communities": [],
                    "income": "low" if i % 3 == 0 else "high", "thinking_style": "busy and distracted" if i == 4 else ""})
    return out


CREATIVES = [
    {"id": "ig1", "platform": "instagram", "text": "Free practice test", "headline": "See your score", "cta": "Sign up", "page": "Acme"},
    {"id": "ig2", "platform": "instagram", "text": "Check your eligibility", "cta": "Learn more", "page": "Acme"},
    {"id": "fb1", "platform": "facebook", "text": "Parents: plan before you pay an agent", "page": "Acme", "segments": ["Parents"]},
    {"id": "rd1", "platform": "reddit", "text": "We built a free practice-test site", "page": "u/acme_app"},
]


def test_normalize_and_validation():
    cs = ft.normalize_creatives(CREATIVES + [{"platform": "Twitter", "headline": "x"}])
    assert cs[-1]["platform"] == "x" and cs[-1]["id"] == "ad5"
    with pytest.raises(ValueError):
        ft.normalize_creatives([{"platform": "myspace", "text": "x"}])
    with pytest.raises(ValueError):
        ft.normalize_creatives([{"platform": "facebook"}])
    with pytest.raises(ValueError):
        ft.normalize_creatives([{"id": "a", "text": "x"}, {"id": "a", "text": "y"}])
    assert ft.normalize_landing(None) is None
    assert ft.normalize_landing({"load_seconds": 500})["load_seconds"] == 60.0


def test_assignment_is_balanced_and_respects_targeting():
    cs = ft.normalize_creatives(CREATIVES)
    plan = ft.assign(cs, people(12))
    ig = [c["id"] for (aid, p), c in plan.items() if p == "instagram"]
    assert sorted((ig.count("ig1"), ig.count("ig2"))) == [6, 6]
    fb = [(aid, c["id"]) for (aid, p), c in plan.items() if p == "facebook"]
    assert len(fb) == 6 and all(aid % 2 == 1 for aid, _ in fb)          # parents only
    assert len([1 for (_, p) in plan if p == "reddit"]) == 12


def test_run_feed_test_metrics_social_proof_landing_projection():
    llm = FakeLLM()
    cs = ft.normalize_creatives(CREATIVES)
    landing = ft.normalize_landing({"load_seconds": 2.5, "language": "English", "form_fields": ["name", "email", "phone"]})
    res = ft.run_feed_test(llm, "m", cs, people(12), waves=3, landing=landing, parallel=4, exposures=1, attention_gate=False,
                           benchmarks={"instagram": {"cpm": 2.0, "budget": 100, "ctr": 1.5, "currency": "USD"}})
    per = res["summary"]["per_creative"]
    assert res["failed"] == 0 and res["personas_tested"] == 12
    # instagram: students click, parents do not -> about half CTR
    ig = per["ig1"]
    assert ig["impressions"] == 6 and 0 < ig["ctr"] < 100
    assert ig["reactions"].get("like")
    # facebook: parents comment and send to family
    fb = per["fb1"]
    assert fb["comments"] == 6 and fb["share_rate"] == 100.0 and fb["ctr"] == 0.0
    assert fb["comments_list"][0]["text"] == "Is it really free?"
    # reddit: downvotes and hides
    assert per["rd1"]["reactions"] == {"downvote": 12} and per["rd1"]["hide_rate"] == 100.0
    # social proof: later waves saw earlier comments in their feed
    later = [u for s, u in llm.prompts if s == ft.SYSTEM_PROMPT and " comments · " in u]
    assert later                                                   # reaction/comment counts are always visible
    opened = [u for u in later if "You opened the comments" in u]
    assert all("Is it really free?" in u or "ad spam" in u for u in opened)   # comment text only when opened
    assert fb["proof_effect"] is not None
    # landing: phone field -> nobody completes; some lose the page on slow networks
    lf = ig["landing"]
    assert lf["clicks"] >= 1 and lf["converted"] == 0
    assert lf["page_loaded"] <= lf["clicks"]
    # projection uses real CPM and calibrates CTR to the real platform CTR
    pr = ig["projection"]
    assert pr["impressions"] == 50000 and pr["calibrated"] is True
    assert res["summary"]["calibration"]["instagram"] is not None
    assert res["summary"]["organic_baseline"]["instagram"]["thumb_stop"] == 0.0
    assert set(res["summary"]["ranked"]) == {"ig1", "ig2", "fb1", "rd1"}


def test_people_from_simulation_keeps_personas_only():
    profiles = [{"user_id": 0, "name": "Acme", "gender": "other", "persona": "brand"},
                {"user_id": 1, "name": "Asha", "gender": "female", "persona": "student", "age": 18},
                {"user_id": 2, "name": "Group", "gender": "other", "persona": "group"}]
    index = [{"agent_id": 0, "kind": "graph"}, {"agent_id": 1, "kind": "persona", "segment": "Students", "income": "low"},
             {"agent_id": 2, "kind": "community"}]
    ps = ft.people_from_simulation(profiles, index)
    assert [p["name"] for p in ps] == ["Asha"] and ps[0]["income"] == "low"


def test_analyst_panel_independent_and_consensus():
    llm = FakeLLM()
    material = ap.normalize_material({"comments": [{"segment": "Parents", "text": "Is it really free?"}],
                                      "survey": ["Looks useful", {"segment": "Students", "quote": "Signed up!"}],
                                      "context": "Acme practice test"})
    res = ap.run_panel(llm, "m", material, "Which audience?", n=5)
    assert len(res["analysts"]) == 5 and all(a["result"] for a in res["analysts"])
    # each analyst got its own call and never saw another analyst's output
    users = [u for s, u in llm.prompts if s == ap.SYSTEM]
    assert len(users) == 5 and not any("view" in u for u in users)
    c = res["consensus"]
    assert c["best_audience"]["winner"] == "Students" and c["best_audience"]["agreement"] == 100
    assert c["themes"][0]["theme"] == "free practice test" and c["themes"][0]["analysts"] == 5
    assert c["consensus"] in ("strong", "partial")
    with pytest.raises(ValueError):
        ap.normalize_material({"posts": []})


def test_market_api_routes(tmp_path, monkeypatch):
    from app import create_app
    from app.config import Config
    from app.services.simulation_manager import SimulationManager
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path))
    app = create_app()
    app.config.update(TESTING=True)
    c = app.test_client()
    r = c.post("/api/simulation/feed-test", json={"simulation_id": "sim_missing", "creatives": CREATIVES})
    assert r.status_code == 404
    r = c.get("/api/simulation/sim_missing/feed-test")
    assert r.status_code == 404
    r = c.post("/api/simulation/market-task/status", json={"task_id": "nope"})
    assert r.status_code == 404


def test_economics_roi_cpl_cac():
    e = ft.economics(1000, 50, {"close_rate": 20, "deal_value": 300, "gross_margin": 0.8, "monthly_value": 25})
    assert e["cpl"] == 20.0 and e["customers"] == 10.0 and e["cac"] == 100.0
    assert e["revenue"] == 3000.0 and e["roas"] == 3.0
    assert e["roi_pct"] == 140.0 and e["break_even_cpl"] == 48.0 and e["payback_months"] == 5.0
    simple = ft.economics(100, 4, {"lead_value": 30})
    assert simple["cpl"] == 25.0 and simple["roi_pct"] == 20.0
    assert ft.economics(100, None, {}) == {}


def test_attention_gate_exposures_and_expected_rates():
    llm = FakeLLM()
    cs = ft.normalize_creatives(CREATIVES)
    res = ft.run_feed_test(llm, "m", cs, people(12), waves=2, exposures=3, parallel=4, seed=9)
    per = res["summary"]["per_creative"]
    assert res["exposures"] == 3 and res["feeds"] == len(ft.assign(cs, people(12))) * 3
    calls = res["realism"]["llm_feed_calls"]
    assert 0 < calls < res["feeds"]                               # most exposures never catch the eye
    feed_prompts = [u for s_, u in llm.prompts if s_ == ft.SYSTEM_PROMPT]
    assert len(feed_prompts) == calls
    assert all("ad avoidance" in u and "p_click" in u for u in feed_prompts)
    rd = per["rd1"]
    assert rd["impressions"] == 36 and rd["noticed"] < 100
    assert [e["exposure"] for e in rd["by_exposure"]] == [1, 2, 3]
    assert rd["expected_ctr"] is not None and rd["expected_ctr"] <= 100
    gated = [s for s in res["sessions"] if not s["ad"]["noticed"]]
    assert gated and all(not s["ad"]["stopped"] and s["ad"]["p_click"] == 0 for s in gated)
    later = [u for u in feed_prompts if "scrolled past this same ad" in u]
    assert later                                                  # repeat exposures are told so


class MeteredFakeLLM(FakeLLM):
    """Same behaviour, plus token usage on every response like the real API."""

    def create(self, **kw):
        resp = super().create(**kw)
        resp.usage = SimpleNamespace(prompt_tokens=100, completion_tokens=20)
        return resp


def test_multi_seed_reports_range_per_creative_and_cost():
    llm = MeteredFakeLLM()
    cs = ft.normalize_creatives(CREATIVES)
    seeds = ft.seed_list(5, 3)
    assert len(set(seeds)) == 3 and seeds[0] == 5
    res = ft.run_multi_seed(llm, "m", cs, people(12), seeds=seeds, waves=2, exposures=2, parallel=4)
    single = ft.run_feed_test(FakeLLM(), "m", cs, people(12), seed=5, waves=2, exposures=2, parallel=4)
    ms = res["multi_seed"]
    assert ms["n"] == 3 and ms["seeds"] == seeds
    assert res["feeds"] == 3 * single["feeds"]
    assert {s["seed"] for s in res["sessions"]} == set(seeds)
    # spread: every creative has mean and min-max range across seeds for the headline metrics
    assert set(ms["spread"]) == {"ig1", "ig2", "fb1", "rd1"}
    for cid, sp in ms["spread"].items():
        for k in ("expected_ctr", "thumb_stop", "engagement_rate"):
            assert sp[k]["min"] <= sp[k]["mean"] <= sp[k]["max"] and len(sp[k]["values"]) == 3, (cid, k)
    assert any(sp["thumb_stop"]["max"] > sp["thumb_stop"]["min"] for sp in ms["spread"].values())  # seeds differ
    assert sum(ms["winner_counts"].values()) == 3 and 0 <= ms["winner_agreement"] <= 100
    # cost: every Claude call is counted, per seed and in total
    assert ms["usage"]["calls"] == len(llm.prompts) == res["usage"]["calls"]
    assert sum(ps["usage"]["calls"] for ps in ms["per_seed"]) == ms["usage"]["calls"]
    assert ms["usage"]["input_tokens"] == 100 * ms["usage"]["calls"]
    assert ms["usage"]["output_tokens"] == 20 * ms["usage"]["calls"]
    # the replay keeps one seed so nobody scrolls past twice; metrics pool all seeds
    per = res["summary"]["per_creative"]["rd1"]
    assert per["impressions"] == 3 * single["summary"]["per_creative"]["rd1"]["impressions"]
    assert len(per["events"]) == ms["per_seed"][0]["per_creative"]["rd1"]["impressions"]


def test_single_seed_is_a_plain_run():
    res = ft.run_multi_seed(FakeLLM(), "m", ft.normalize_creatives(CREATIVES), people(12), seeds=[7], waves=1, exposures=1)
    assert "multi_seed" not in res and res["seed"] == 7 and res["usage"]["calls"] > 0


def test_feed_test_api_validates_seeds(tmp_path, monkeypatch):
    from app import create_app
    from app.api import market
    app = create_app()
    app.config.update(TESTING=True)
    monkeypatch.setattr(market, "_sim_dir", lambda sid: str(tmp_path))
    monkeypatch.setattr(market, "_people", lambda sid: (people(4), {}))
    started = {}
    monkeypatch.setattr(market, "_start", lambda kind, sid, work, **kw: started.setdefault("work", work) and "task_1")
    c = app.test_client()
    r = c.post("/api/simulation/feed-test", json={"simulation_id": "sim_x", "creatives": CREATIVES, "seeds": "many"})
    assert r.status_code == 400
    r = c.post("/api/simulation/feed-test", json={"simulation_id": "sim_x", "creatives": CREATIVES, "seeds": 50})
    assert r.status_code == 200 and r.get_json()["data"]["seeds"] == 10          # capped


def test_segment_targeting_is_forgiving():
    from app.services.feed_test import segment_matches
    assert segment_matches("India parents", "Working parents, India, metro cities")
    assert segment_matches("Philippines young professionals", "Young professionals, Philippines, Metro Manila & Makati")
    assert not segment_matches("Kenya students", "Young professionals, Kenya, Nairobi")
    assert segment_matches("Students", "Students")


def test_organic_pool_quotes_real_voices():
    from app.services import feed_test as ft
    seen = {}

    class C:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    seen["prompt"] = kw["messages"][1]["content"]
                    raise RuntimeError("stop here")
    ft.organic_pool(C(), "m", "facebook", "India", "ctx", voices=[{"text": "Bhai offline chalega?", "source": "reddit", "sentiment": "neu", "country": "India"}])
    assert "Real things people posted" in seen["prompt"] and "Bhai offline chalega?" in seen["prompt"]


def test_all_failed_decisions_are_not_a_completed_feed_test(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("provider authentication failed")
    monkeypatch.setattr(ft, "_llm_json", fail)
    with pytest.raises(RuntimeError, match="No usable model decisions"):
        ft.run_feed_test(FakeLLM(), "m", ft.normalize_creatives(CREATIVES), people(4),
                         attention_gate=False, exposures=1, parallel=2)


def test_say_do_friction_competitor_shock_and_generic_baseline():
    import random
    person = {
        "agent_id": 1,
        "name": "Ramesh",
        "bde": {
            "background": {"acquiescence": "high"},
            "decision_procedure": {"stoppers": ["card required"]},
            "evaluation": {"monthly_discretionary": "NPR 500", "discretionary_budget_num": 500.0, "dealbreakers": ["auto-renew"]},
        },
    }
    # Price above discretionary budget triggers wallet_limit friction
    f_wallet = ft.check_say_do_friction(person, {"price": "NPR 1200", "shows": "Pro plan"}, random.Random(1))
    assert f_wallet is not None and f_wallet[0] == "wallet_limit"

    # Dealbreaker present on landing page triggers dealbreaker friction
    f_deal = ft.check_say_do_friction(person, {"price": "NPR 200", "shows": "7-day trial with auto-renew"}, random.Random(1))
    assert f_deal is not None and f_deal[0] == "dealbreaker"

    # Full feed test with competitor counter-offer and generic reader baseline, on a two-provider pool
    pool, _ = _two_provider_pool()
    cs = ft.normalize_creatives(CREATIVES[:1])
    ps = people(4)
    for p in ps:
        p["model_provider"] = "openai"            # who wrote the persona must not decide the answering provider
    res = ft.run_feed_test(
        pool, "m", cs, ps, waves=1, exposures=1, attention_gate=False,
        competitor={"name": "RivalFit", "offer": "50% cheaper, no card"},
        include_generic_baseline=True,
    )
    assert "competitor_shock" in res["summary"]
    assert res["summary"]["competitor_shock"]["name"] == "RivalFit"
    assert "generic_baseline" in res["summary"]
    assert "by_provider" in res["summary"]
    assert set(res["summary"]["by_provider"].keys()) == {"claude", "gemini"}
    assert all(s["persona_provider"] == "openai" for s in res["sessions"])
    assert set(res["usage_by_provider"]) == {"claude", "gemini"}


class _ProviderLLM(FakeLLM):
    """FakeLLM whose calls can be made to fail (rate limit) so the pool fails over."""

    def __init__(self, fail=False):
        super().__init__()
        self.fail = fail
        self.calls = 0

    def create(self, **kw):
        self.calls += 1
        if self.fail:
            raise RuntimeError("Error code: 429 - rate limit exceeded")
        return super().create(**kw)


def _two_provider_pool(fail_first=False):
    from app.utils.model_pool import MultiProviderPool, ProviderSlot
    a, b = _ProviderLLM(fail=fail_first), _ProviderLLM()
    pool = MultiProviderPool([ProviderSlot("claude", "claude-sonnet-4-5", "https://api.anthropic.com/v1/", "k", a),
                              ProviderSlot("gemini", "gemini-2.5-flash", "https://generativelanguage.googleapis.com/v1beta/openai/", "k", b)])
    return pool, (a, b)


def test_by_provider_counts_the_provider_that_answered_after_failover():
    pool, (claude, gemini) = _two_provider_pool(fail_first=True)
    ps = people(4)
    for p in ps:
        p["model_provider"] = "claude"
    res = ft.run_feed_test(pool, "m", ft.normalize_creatives(CREATIVES[:1]), ps, waves=1, exposures=1,
                           attention_gate=False, parallel=1)
    # every claude-routed call hit a rate limit and failed over: gemini answered all of them
    assert claude.calls >= 1 and set(res["summary"]["by_provider"]) == {"gemini"}
    assert {s["model_provider"] for s in res["sessions"]} == {"gemini"}
    assert set(res["usage_by_provider"]) == {"gemini"}


def test_unnoticed_sessions_are_labelled_with_the_routed_provider():
    pool, _ = _two_provider_pool()
    ps = people(4)
    res = ft.run_feed_test(pool, "m", ft.normalize_creatives(CREATIVES[:1]), ps, waves=1, exposures=3,
                           attention_gate=True, seed=3)
    unnoticed = [s for s in res["sessions"] if not s["ad"].get("noticed")]
    assert unnoticed, "the attention gate should skip some exposures"
    for s in unnoticed:
        assert s["model_provider"] == ("claude" if s["agent_id"] % 2 == 0 else "gemini")
        assert s["provider_answered"] is False


def test_gateway_reported_provider_is_used_for_plain_clients():
    class GatewayLLM(FakeLLM):
        def create(self, **kw):
            r = super().create(**kw)
            r.provider = "antigravity"                     # what a multi gateway reports per answer
            return r
    llm = GatewayLLM()
    llm.base_url = "http://127.0.0.1:59999/v1"
    res = ft.run_feed_test(llm, "m", ft.normalize_creatives(CREATIVES[:1]), people(2), waves=1, exposures=1,
                           attention_gate=False)
    assert set(res["summary"]["by_provider"]) == {"antigravity"}


def test_generic_baseline_survives_multiple_seeds():
    llm = FakeLLM()
    res = ft.run_multi_seed(llm, "m", ft.normalize_creatives(CREATIVES[:1]), people(4), seeds=[5, 6],
                            waves=1, exposures=1, attention_gate=False, include_generic_baseline=True,
                            competitor={"name": "RivalFit", "offer": "50% cheaper"})
    assert res["multi_seed"]["n"] == 2
    assert res["summary"]["generic_baseline"]["ranked"]
    assert res["summary"]["competitor_shock"]["name"] == "RivalFit"
    baseline_calls = [1 for s, _ in llm.prompts if s == ft.GENERIC_READER_SYSTEM]
    assert len(baseline_calls) == 1                                    # once on the pooled ranking, not per seed

