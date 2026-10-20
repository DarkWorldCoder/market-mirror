"""Tests for Agent Thoughts, Production Readiness, GTM Suite, CRO Lab, search and the search / VoC / cascade tests."""

import json
from types import SimpleNamespace
import pytest

from app import create_app
from app.models.task import TaskManager, TaskStatus
from app.services import agent_thoughts as at
from app.services import cro_and_sparring as cro
from app.services import gtm_suite
from app.services import search_and_geo as sg
from claude_cli import gtm_view


class FakeSmartLLM:
    """Prompt-aware fake LLM that returns valid JSON matching whichever MarketMirror test called it."""

    def __init__(self):
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        user = kw["messages"][1]["content"]
        assert isinstance(user, str), f"prompt must be a string, got {type(user).__name__}"
        assert isinstance(kw["messages"][0]["content"], str)
        self.calls.append(user)

        if user.startswith("Question: "):
            body = {"answer": "Buyers cite card friction [#1] and budget [#2] [#9].", "key_points": ["[#1] Card trust", "[#2] Price"]}
        elif "private_verdict" in user and "conviction_0_10" in user:
            body = {
                "thought": "7 days free sounds nice, but if they ask for my debit card upfront I'm closing the tab.",
                "gut": "skeptical",
                "weighing": "My monthly discretionary budget is tight and auto-renew is a dealbreaker.",
                "roadblock": "payment_or_signup",
                "private_verdict": "maybe",
                "would_do": "check if card is required, then wait",
                "conviction_0_10": 4.5,
            }
        elif '"participants"' in user and '"deciding_voice"' in user:
            body = {
                "setting": "household",
                "participants": [
                    {
                        "role": "buyer",
                        "relation": "self",
                        "says": "Looks helpful for 15-minute routines.",
                        "privately_thinks": "Worried about auto-debit after trial.",
                        "stance": "maybe",
                        "concern": "Card required upfront",
                        "concern_type": "trust",
                    },
                    {
                        "role": "partner",
                        "relation": "spouse",
                        "says": "Only if we don't have to enter a card for the trial.",
                        "privately_thinks": "Budget is tight this month.",
                        "stance": "no",
                        "concern": "Monthly cost",
                        "concern_type": "price",
                    },
                ],
                "outcome": "try_first",
                "deciding_voice": "partner",
                "blocker": "Upfront card requirement",
                "blocker_type": "trust",
                "what_would_unblock": "No-card 7-day trial",
            }
        elif '"probability_of_click"' in user:
            body = {
                "stopped_scrolling": True,
                "would_click": True,
                "probability_of_click": 0.42,
                "first_thought": "Short 15-min routine fits my busy schedule.",
                "main_objection": "Need to know the price after trial.",
                "objection_type": "price",
            }
        elif '"change_summary"' in user and '"cta"' in user:
            body = {
                "headline": "15-min home routine — no card for 7 days",
                "text": "Try 3 workouts free before paying anything.",
                "cta": "Start 7-day pass",
                "change_summary": "Removed card friction and stated 15-min routine clearly",
            }
        elif '"qualification_questions"' in user:
            body = {
                "objections": [
                    {
                        "type": "price",
                        "buyer_says": "It costs too much right now.",
                        "why_they_say_it": "End of month budget pressure.",
                        "rebuttal": "Start with the 7-day pass with no card required.",
                        "discovery_question": "What monthly budget feels comfortable for you?",
                        "proof_needed": "Clear pricing table",
                    }
                ],
                "outreach": [{"day": 1, "channel": "WhatsApp", "message": "Try Day 1 free with no card."}],
                "qualification_questions": ["How many days a week do you currently work out?"],
            }
        elif '"moved"' in user and '"reply"' in user:
            body = {"reply": "That answers my concern, I would try the 7-day pass.", "moved": "yes"}
        elif '"steps"' in user and '"signed_up_at"' in user:
            body = {
                "steps": [
                    {"touch": 1, "noticed": True, "clicked": True, " signed_up": False, "signed_up": False, "thought": "Curious about the routine"},
                    {"touch": 2, "noticed": True, "clicked": True, "signed_up": True, "thought": "No card needed convinced me"},
                ],
                "signed_up_at": 2,
                "using_after_week": True,
                "would_recommend": True,
                "drop_reason": "",
                "drop_type": "none",
            }
        elif '"touches"' in user and '"day"' in user:
            body = {
                "touches": [
                    {"name": "First ad", "channel": "instagram", "day": "0", "text": "15-min routine"},
                    {"name": "Reminder", "channel": "instagram", "day": "2", "text": "Still thinking about it?"},
                    {"name": "Offer page", "channel": "web", "day": "3", "text": "Start your 7-day pass"},
                    {"name": "Follow-up", "channel": "whatsapp", "day": "7", "text": "How did week 1 go?"},
                ]
            }
        elif '"action"' in user and ('"ignore|notice|click"' in user or '"leave|sign_up|buy"' in user or '"keep_using|stop|pay|cancel"' in user or '"ignore|come_back|sign_up|unsubscribe"' in user):
            body = {
                "action": "click" if "ignore|notice|click" in user else ("sign_up" if "leave|sign_up|buy" in user else "keep_using"),
                "why": "Fits my 15-minute routine",
                "would_recommend": True,
            }
        elif '"options"' in user and '"billing"' in user:
            body = {
                "options": [
                    {"name": "Weekly Pass", "price": 199, "billing": "per week", "includes": "All routines", "terms": "No auto-renew"},
                    {"name": "Monthly Standard", "price": 999, "billing": "per month", "includes": "All routines + coach", "terms": "Cancel anytime"},
                ],
            }
        elif '"max_price_you_would_pay"' in user:
            body = {"choice": "A", "why": "Fits my pocket budget", "max_price_you_would_pay": 500, "deal_breaker": ""}
        elif '"competitors"' in user and '"description"' in user:
            body = {
                "competitors": [
                    {"name": "Free YouTube Workouts", "description": "Free workout videos on YouTube"},
                    {"name": "Local Gym", "description": "Neighborhood gym membership"},
                ]
            }
        elif '"suggestions"' in user and '"evidence"' in user:
            body = {
                "suggestions": [
                    {
                        "title": "Zero-card trial",
                        "change": "Let people try 7 days without entering a card",
                        "addresses": "trust",
                        "evidence": "People worried about auto-debit",
                        "kind": "offer",
                        "effort": "low",
                    }
                ]
            }
        elif '"what_would_make_you_choose_brand"' in user:
            body = {
                "choice": "FitLoop",
                "why": "Structured 15-min habit fits my schedule",
                "what_would_make_you_choose_brand": "No credit card required upfront",
            }
        elif '"what_is_it"' in user and '"read_until"' in user:
            body = {
                "what_is_it": "A 15-minute home workout program",
                "who_is_it_for": "Busy students and working parents",
                "would_continue": "yes",
                "read_until": "end",
                "confusing": "Whether a card is required for the trial",
                "confusing_type": "trust",
                "missing_to_decide": "Exact price after 7 days",
                "noticed_trust_signal": "Cancel anytime note",
            }
        elif '"grades"' in user:
            body = {"grades": [{"i": 0, "grade": "correct"}, {"i": 1, "grade": "correct"}]}
        elif '"replies"' in user and '"lost_me_at"' in user:
            body = {
                "replies": ["Tell me more about the 7-day pass.", "Okay, I can try that."],
                "outcome": "agreed_to_next_step",
                "scores": {"clear": 4, "relevant_to_me": 4, "trustworthy": 4, "pushy": 2},
                "what_they_should_have_said": "Mention no credit card is needed in message 1.",
                "lost_me_at": 0,
            }
        elif '"choices"' in user and '"what_mattered_most"' in user:
            body = {"choices": ["A", "B", "A", "B"], "what_mattered_most": "No card required for trial"}
        elif '"attributes"' in user:
            body = {
                "attributes": {
                    "Trial terms": ["Card required", "No card required"],
                    "Price": ["NPR 999/mo", "NPR 199/week"],
                }
            }
        elif '"angle"' in user and '"headline"' in user:
            body = {
                "headline": "Tailored 15-min routine for your schedule",
                "text": "Start with zero card upfront.",
                "cta": "Try 7 days free",
                "angle": "Directly answers card and schedule objections",
            }
        elif '"known_options"' in user and '"would_look_for_help"' in user:
            body = {
                "would_look_for_help": "yes",
                "search_query": "best 15 minute home workout app without credit card",
                "known_options": ["Free workout videos", "Local Gym"],
            }
        elif '"verify_question"' in user and '"would_shortlist"' in user:
            body = {
                "understood_category": "Home fitness habit app",
                "would_shortlist": "yes",
                "verify_question": "Does FitLoop charge my card automatically after 7 days?",
                "missing_fact": "Which local payment methods are accepted",
                "missing_type": "price",
            }
        elif '"llms_txt"' in user and '"faqs"' in user:
            body = {
                "llms_txt": "# FitLoop\n> 15-min home routine with NPR 999/mo plan.",
                "faqs": [
                    {
                        "question": "What is FitLoop?",
                        "answer": "FitLoop is a 15-min home routine starting with a 7-day free trial.",
                    }
                ],
                "unanswered_gaps": ["Local payment options"],
            }
        elif '"key_phrase"' in user and '"plain_meaning"' in user:
            body = {
                "concern_type": "trust",
                "key_phrase": "asks for a card before I see one workout",
                "plain_meaning": "Upfront credit card requirement blocks trial signup",
            }
        elif '"would_share"' in user and '"message_you_would_send"' in user:
            body = {
                "would_share": "yes",
                "channel": "direct_message",
                "who": "my sister",
                "message_you_would_send": "Check out this 15-min home workout, looks easy to do at home.",
                "why": "We work out together at home.",
            }
        elif '"would_try"' in user and '"would_forward_again"' in user:
            body = {"would_try": "yes", "reaction": "A friend sent it, so I would give it a go.", "would_forward_again": "maybe"}
        elif '"would_try"' in user:
            body = {"would_try": "maybe", "reaction": "Looks fine, but it is just another ad."}
        else:
            body = {"answer": "Buyers cite card friction [#1] and budget [#2].", "key_points": ["[#1] Card trust", "[#2] Price"]}

        msg = SimpleNamespace(content=json.dumps(body))
        return SimpleNamespace(
            choices=[SimpleNamespace(message=msg, finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=60, completion_tokens=35),
            _mm_provider="gemini",
            _mm_model="gemini-2.5-flash",
        )


def _sample_people():
    return [
        {
            "agent_id": 1,
            "name": "Asha Rai",
            "age": 21,
            "city": "Kathmandu",
            "country": "Nepal",
            "segment": "Nepal students",
            "occupation": "student",
            "payday_status": "end_of_month_tight",
            "model_provider": "gemini",
            "provenance": {"profile": "real_intake: customer_excerpts"},
            "persona": "Final-year student in Kathmandu who shares an account with her sister.",
            "bde": {
                "background": {"believes": "free trials trap cards", "says_vs_does": "polite yes, strict wallet"},
                "decision_procedure": {"who_they_ask": "sister", "stoppers": ["card upfront"]},
                "evaluation": {"monthly_discretionary": "NPR 1500", "dealbreakers": ["auto-renew"]},
            },
        },
        {
            "agent_id": 2,
            "name": "Bikash Thapa",
            "age": 34,
            "city": "Pokhara",
            "country": "Nepal",
            "segment": "Working parents",
            "occupation": "accountant",
            "model_provider": "claude",
            "persona": "Busy parent in Pokhara looking for a 15-minute routine.",
            "bde": {"evaluation": {"monthly_discretionary": "NPR 2500", "dealbreakers": ["hidden fees"]}},
        },
    ]


def test_agent_thought_simulation_and_harvest(tmp_path):
    people = _sample_people()
    llm = FakeSmartLLM()
    res = at.run_thought_simulation(
        llm,
        "gemini-2.5-flash",
        {"headline": "Start your 7-day free trial", "text": "15-min home workouts", "price": "NPR 999/mo after trial"},
        people,
    )
    assert res["total"] == 2
    assert res["people"] == 2
    assert res["thought_test"]["gut"]["skeptical"]["k"] == 2
    assert res["thought_test"]["roadblock"]["payment_or_signup"]["k"] == 2
    assert res["thought_test"]["said_yes_but_would_not_act"]["k"] == 2

    (tmp_path / "simulation_config.json").write_text(json.dumps({"persona_index": people}), encoding="utf-8")
    (tmp_path / "thought_stream.json").write_text(json.dumps(res), encoding="utf-8")
    harvested = at.harvest_thoughts(str(tmp_path))
    assert harvested["total"] == 2
    assert harvested["entries"][0]["source"] == "thought_test"

    bundle = {"config": {"persona_index": people}, "thought_stream": res, "thought_harvest": harvested}
    sec = gtm_view.thoughts_section(bundle)
    assert sec is not None and sec[0] == "thoughts"
    assert "Thought test" in sec[2]
    assert "Everything people wrote in this run" in sec[2]


def test_production_middleware_auth_ratelimit_probes_and_metrics(tmp_path, monkeypatch):
    monkeypatch.setenv("MM_TASK_DB_PATH", str(tmp_path / "tasks.sqlite"))
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()

    r_health = client.get("/health")
    assert r_health.status_code == 200
    assert r_health.headers.get("X-Request-ID")
    assert r_health.headers.get("X-Content-Type-Options") == "nosniff"

    r_ready = client.get("/ready")
    assert r_ready.status_code == 200
    assert r_ready.get_json()["ready"] is True

    r_sys = client.get("/api/system/status")
    assert r_sys.status_code == 200
    assert r_sys.get_json()["data"]["version"] == "2.0.0"

    r_metrics = client.get("/metrics")
    assert r_metrics.status_code == 200
    assert "marketmirror_uptime_seconds" in r_metrics.get_data(as_text=True)

    app.config["MM_API_AUTH_TOKEN"] = "prod-secret-token-123"
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200
    assert client.get("/api/system/status").status_code == 401
    assert client.get("/api/system/status", headers={"Authorization": "Bearer prod-secret-token-123"}).status_code == 200
    assert client.get("/api/system/status", headers={"X-API-Key": "prod-secret-token-123"}).status_code == 200
    app.config.pop("MM_API_AUTH_TOKEN", None)

    app.config["MM_RATE_LIMIT_RPM"] = 2
    assert client.get("/api/system/status").status_code == 200
    assert client.get("/api/system/status").status_code == 200
    limited = client.get("/api/system/status")
    assert limited.status_code == 429
    assert limited.headers.get("Retry-After")
    app.config.pop("MM_RATE_LIMIT_RPM", None)


def test_sqlite_persistent_task_manager_survives_cache_eviction(tmp_path, monkeypatch):
    db_file = tmp_path / "persistent_tasks.sqlite"
    monkeypatch.setenv("MM_TASK_DB_PATH", str(db_file))
    tm = TaskManager()
    tm._init_db()
    tid = tm.create_task("thought-stream", metadata={"simulation_id": "sim_1"})
    tm.complete_task(tid, {"total_thoughts": 12})

    with tm._task_lock:
        tm._tasks.pop(tid, None)

    reloaded = tm.get_task(tid)
    assert reloaded is not None
    assert reloaded.status == TaskStatus.COMPLETED
    assert reloaded.result == {"total_thoughts": 12}


def test_full_gtm_cro_and_search_geo_engines_and_views(tmp_path):
    people = _sample_people()
    llm = FakeSmartLLM()
    offer = {"name": "FitLoop", "headline": "FitLoop 15-min home routine", "text": "Start your 7-day free trial today", "price": "NPR 999/mo"}
    run_data = {
        "survey": {
            "responses": [
                {"agent_id": 1, "name": "Asha Rai", "segment": "Nepal students",
                 "answer": {"main_objection": "Asking for a card upfront scares me off.", "objection_type": "trust", "would_convert": "maybe"}},
                {"agent_id": 2, "name": "Bikash Thapa", "segment": "Working parents",
                 "answer": {"main_objection": "NPR 999/mo is steep without trying first.", "objection_type": "price", "would_convert": "no"}},
            ]
        }
    }

    # 1. GTM Suite (all 6 core engines)
    suite = gtm_suite.run_full_gtm_suite(llm, "gemini-2.5-flash", people, offer=offer, run_dir=str(tmp_path), run_data=run_data)
    assert set(suite["engines"].keys()) == {"committee", "creative", "battlecard", "journey", "pricing", "competitors"}
    assert not suite["errors"]

    # 2. CRO & Sparring engines
    td = cro.run_landing_teardown(llm, "gemini-2.5-flash", "FitLoop 15-min home workout page text", people)
    rp = cro.run_sales_roleplay(llm, "gemini-2.5-flash", people, offer=offer, rep_messages=["Hi! Want to try FitLoop?", "No card needed for 7 days."])
    wi = cro.run_causal_whatif_model(people, client=llm, model="gemini-2.5-flash", offer=offer)
    sp = cro.run_segment_personalizer(llm, "gemini-2.5-flash", offer, people, run_data=run_data)
    assert td["engine"] == "teardown" and td["answered"] == 2
    assert rp["engine"] == "roleplay" and rp["answered"] == 2
    assert wi["engine"] == "whatif" and wi["answered"] == 2
    assert sp["engine"] == "personalize" and len(sp["summary"]["segments"]) == 2

    # 3. How buyers would search, real vs simulated concerns, word-of-mouth cascade
    geo = sg.run_geo_visibility_audit(llm, "gemini-2.5-flash", offer=offer, people=people)
    voc = sg.run_voc_grounding(
        llm, "gemini-2.5-flash",
        raw_reviews=["Every app asks for a card before I see one workout.", "Why pay when free workout videos exist?"],
        run_data=run_data,
    )
    casc = sg.run_dark_social_cascade(llm, "gemini-2.5-flash", people=people, offer=offer)
    assert geo["engine"] == "geo" and geo["summary"]["would_shortlist"]["yes"]["k"] == 2
    assert geo["asked"] == 4 and geo["summary"]["would_look_for_help"]["yes"]["k"] == 2
    assert geo["summary"]["llms_txt"].startswith("# FitLoop")
    assert voc["engine"] == "voc" and voc["summary"]["available"] is True
    assert casc["engine"] == "cascade" and casc["summary"]["would_share"]["yes"]["k"] >= 1
    assert casc["summary"]["wave2_peer_pickup"]["available"] is False   # 2 people: 1 in wave 1 leaves 1 for wave 2

    # 4. Hybrid BM25 + Concept Search & Cited Copilot
    bundle = {
        "config": {"persona_index": people},
        "survey": run_data["survey"],
        "gtm_suite": suite,
        "landing_teardown": td,
        "sales_roleplay": rp,
        "causal_whatif": wi,
        "segment_personalization": sp,
        "geo_visibility": geo,
        "voc_grounding": voc,
        "dark_social": casc,
    }
    idx = sg.build_search_index(people=people, bundle=bundle)
    assert idx["total_docs"] >= 8
    hits = sg.search_market_evidence("credit card auto-renew trap", idx)
    assert hits["total_matches"] >= 1
    assert "trust" in hits["expansion"]["matched_concepts"]

    copilot = sg.ask_market_copilot("Why do people hesitate at signup?", idx, client=llm, model="gemini-2.5-flash")
    assert copilot["citations"] and copilot["answer_ok"] is True, copilot.get("error")
    assert "[#1]" in copilot["cited_answer"] and "[#9]" not in copilot["cited_answer"]

    # 5. Dashboard sections render cleanly via gtm_view
    lab_sec = gtm_view.lab_section(bundle)
    comp_sec = gtm_view.competitor_section(bundle)
    cro_sec = gtm_view.cro_lab_section(bundle)
    sgeo_sec = gtm_view.search_geo_section(bundle)
    assert lab_sec is not None and lab_sec[0] == "gtm"
    assert comp_sec is not None and comp_sec[0] == "competitors"
    assert cro_sec is not None and cro_sec[0] == "cro-lab"
    assert sgeo_sec is not None and sgeo_sec[0] == "search-geo"
    assert "Search everything people said, thought or posted in this run" in sgeo_sec[2]
    assert "How buyers would search (simulated)" in sgeo_sec[2]
    assert "Real vs simulated concerns" in sgeo_sec[2]
    assert "Private sharing and word-of-mouth cascade" in sgeo_sec[2]
    assert "In facts" not in sgeo_sec[2] and "metaKey" not in sgeo_sec[2] and "ctrlKey" not in sgeo_sec[2]


# --------------------------------------------------------------------------
# Search, how buyers would search, real vs simulated concerns, cascade
# --------------------------------------------------------------------------

def _crowd(n):
    base = _sample_people()
    out = []
    for i in range(n):
        p = dict(base[i % 2])
        p["agent_id"] = i + 1
        p["name"] = f"{p['name']} {i + 1}"
        out.append(p)
    return out


class _Reply:
    """Fake client: `answer(system, user)` returns the JSON body; every call is recorded and must be a string."""

    def __init__(self, answer):
        self.answer = answer
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        system, user = kw["messages"][0]["content"], kw["messages"][1]["content"]
        assert isinstance(system, str) and isinstance(user, str)
        self.calls.append((system, user))
        body = self.answer(system, user)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(body)), finish_reason="stop")],
                               usage=SimpleNamespace(prompt_tokens=10, completion_tokens=10))


class _Down:
    def __init__(self):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        raise RuntimeError("provider unavailable")


OFFER = {"name": "FitLoop", "headline": "FitLoop 15-min home routine", "text": "Start your 7-day free trial today", "price": "NPR 999/mo"}


def test_voc_reads_research_quotes_labels_none_and_drops_phrases_not_in_text():
    def answer(system, user):
        assert system == sg.CLASSIFIER_SYSTEM
        if "love" in user:
            return {"concern_type": "none", "key_phrase": "love it", "plain_meaning": "Praise."}
        if "card" in user.lower():
            return {"concern_type": "trust", "key_phrase": "wants my card first", "plain_meaning": "Card required."}
        return {"concern_type": "price", "key_phrase": "far too costly for students", "plain_meaning": "Too expensive."}

    llm = _Reply(answer)
    run_data = {
        "research": {"summary": {"query": "home workouts"}, "quotes": [
            {"text": "I love it, the routines are short.", "source": "appstore", "kind": "review"},
            {"text": "It wants my card first, which I hate.", "source": "reddit"},
            {"text": "Too expensive for what it is.", "source": "reddit"},
        ]},
        "survey": {"responses": [
            {"agent_id": 1, "answer": {"main_objection": "Card upfront scares me.", "objection_type": "trust"}},
            {"agent_id": 2, "answer": {"main_objection": "The price is steep.", "objection_type": "price"}},
        ]},
    }
    res = sg.run_voc_grounding(llm, "m", run_data=run_data)
    s = res["summary"]
    assert s["available"] and s["source_kind"] == "research"
    assert s["real"]["texts"] == 3 and s["real"]["classified"] == 3 and s["simulated"]["classified"] == 2
    assert len(llm.calls) == 5                                   # real and simulated text, same classifier
    rows = {c["concern"]: c for c in s["comparison"]}
    assert rows["none"]["real"]["k"] == 1 and rows["none"]["simulated"]["k"] == 0
    assert "other" not in rows
    assert rows["trust"]["real"]["k"] == 1 and rows["trust"]["simulated"]["k"] == 1
    d = rows["trust"]["difference"]
    assert d["method"].startswith("Newcombe") and d["lo"] < d["points"] < d["hi"]
    assert "none" not in {r["key"] for r in s["real_concerns"]}
    phrases = {p["concern"]: p for p in s["phrases"]}
    assert phrases["trust"]["copied_from_text"] is True and phrases["trust"]["phrase"] == "wants my card first"
    assert phrases["price"]["copied_from_text"] is False and phrases["price"]["phrase"] == "Too expensive for what it is."
    assert res["unit"] == "texts classified by the model"
    assert "texts classified by the model" in gtm_view.voc_card(res)


def test_voc_page_text_is_labelled_as_page_text(monkeypatch):
    monkeypatch.setattr(sg, "fetch_url_snapshot",
                        lambda url: {"url": url, "text": "Start your free trial today with no card. Plans cost less than a coffee each week."})
    llm = _Reply(lambda system, user: {"concern_type": "price", "key_phrase": "cost less", "plain_meaning": "Cheap."})
    res = sg.run_voc_grounding(llm, "m", url="https://example.com/")
    assert res["summary"]["real_label"] == "page text" and res["summary"]["source_kind"] == "page"
    html = gtm_view.voc_card(res)
    assert "Phrases from the page text" in html and "customer" not in html.lower()


def test_geo_asks_before_and_after_in_separate_calls():
    def answer(system, user):
        if '"known_options"' in user:
            return {"would_look_for_help": "yes", "search_query": "short home workout plan", "known_options": ["FitLoop", "Gym Co"]}
        if '"verify_question"' in user:
            return {"understood_category": "fitness app", "would_shortlist": "maybe", "verify_question": "Is the trial free?",
                    "missing_fact": "", "missing_type": "none"}
        return {"llms_txt": "# FitLoop", "faqs": [{"question": "Is the trial free?", "answer": "Yes, 7 days.", "in_facts": True}],
                "unanswered_gaps": []}

    llm = _Reply(answer)
    people = _crowd(3)
    res = sg.run_geo_visibility_audit(llm, "m", offer=OFFER, people=people, competitors=["Gym Co"])
    before = [u for _, u in llm.calls if '"known_options"' in u]
    after = [u for _, u in llm.calls if '"verify_question"' in u]
    assert len(before) == 3 and len(after) == 3 and res["asked"] == 6
    assert all("FitLoop" not in u and "NPR 999" not in u for u in before)      # no exposure before the offer
    assert all("NPR 999" in u for u in after)
    assert not any(w in u for _, u in llm.calls for w in ("ChatGPT", "Perplexity", "Gemini"))
    s = res["summary"]
    assert s["named_the_brand_before"]["k"] == 3 and s["named_competitors_before"][0]["share"]["k"] == 3
    assert s["would_shortlist"]["maybe"]["k"] == 3 and s["missing_facts"] == []
    assert s["faqs"] == [{"question": "Is the trial free?", "answer": "Yes, 7 days."}]
    html = gtm_view.geo_card(res)
    assert "How buyers would search (simulated)" in html and "In facts" not in html

    with pytest.raises(RuntimeError, match="no simulated person answered"):
        sg.run_geo_visibility_audit(_Down(), "m", offer=OFFER, people=people)


def test_cascade_compares_friend_forward_with_cold_offer_on_the_same_people():
    def answer(system, user):
        if '"message_you_would_send"' in user:
            return {"would_share": "yes", "channel": "family_chat", "who": "my sister",
                    "message_you_would_send": "Try this, looks easy.", "why": "We train together."}
        if '"would_forward_again"' in user:
            return {"would_try": "yes", "reaction": "A friend sent it.", "would_forward_again": "no"}
        return {"would_try": "no", "reaction": "Just an ad."}

    ticks = []
    llm = _Reply(answer)
    res = sg.run_dark_social_cascade(llm, "m", people=_crowd(5), offer=OFFER, progress=lambda d, t: ticks.append((d, t)))
    w2 = res["summary"]["wave2_peer_pickup"]
    assert w2["available"] and w2["people"] == 3 and w2["paired"] == 3
    assert w2["friend_minus_cold"]["mean"] == 1.0 and w2["friend_minus_cold"]["verdict"] == "better"
    assert w2["would_try_cold"]["no"]["k"] == 3 and w2["would_try_from_friend"]["yes"]["k"] == 3
    wave2 = [u for _, u in llm.calls if '"would_try"' in u]
    assert len(wave2) == 6 and sum('"would_forward_again"' in u for u in wave2) == 3
    assert all("my sister" not in u for u in wave2) and any("A friend posts in your family group chat" in u for u in wave2)
    assert ticks and ticks[-1][0] == ticks[-1][1] == 8
    assert "Friend minus cold" in gtm_view.cascade_card(res)

    one = sg.run_dark_social_cascade(_Reply(answer), "m", people=_crowd(1), offer=OFFER)
    assert one["summary"]["wave2_peer_pickup"]["available"] is False
    assert "at least 2 people" in one["summary"]["wave2_peer_pickup"]["reason"]


def test_copilot_failure_is_reported_and_citations_kept():
    idx = sg.build_search_index(people=_sample_people(), bundle={"survey": {"responses": [
        {"agent_id": 1, "answer": {"main_objection": "The card at signup worries me.", "objection_type": "trust"}}]}})
    res = sg.ask_market_copilot("card signup", idx, client=_Down(), model="m")
    assert res["answer_ok"] is False and "provider unavailable" in res["error"]
    assert res["citations"] and res["cited_answer"] == ""
    res = sg.ask_market_copilot("card signup", idx)
    assert res["answer_ok"] is False and res["citations"]


def test_run_search_whole_tokens_and_odd_shapes():
    from claude_cli import run_search
    assert run_search.detect_concepts("an industrial cardigan") == []
    assert run_search.detect_concepts("the card fee") == ["price", "trust"]
    bundle = {"survey": {"responses": "oops"}, "actions": {"actions": "x"}, "feed_test": {"sessions": [1, None]},
              "gtm_suite": {"engines": []}, "config": {"persona_index": {"bad": 1}},
              "research": {"summary": {}, "quotes": [{"text": "It costs too much for a student budget.", "source": "reddit"}, "junk"]}}
    idx = sg.build_search_index(bundle=bundle)
    assert [d["type"] for d in idx["docs"]] == ["research"]
    hit = sg.search_market_evidence("price", idx)["results"][0]
    assert hit["type_label"] == "Public post or review (research)"
    view = gtm_view.search_geo_section({"research": bundle["research"]})
    assert view is not None and "Public post or review (research)" in view[2]


def test_cli_gtm_body_sends_research_quotes(tmp_path):
    from claude_cli import mirofish
    (tmp_path / "research.json").write_text(json.dumps({"summary": {}, "quotes": [{"text": "Too pricey", "source": "web", "extra": 1}]}))
    body = mirofish._gtm_body(SimpleNamespace(simulation="sim_x", parallel=4), str(tmp_path))
    assert body["research"] == {"quotes": [{"text": "Too pricey", "source": "web", "url": None, "kind": None}]}


def test_search_and_gtm_routes_reject_bad_input(tmp_path, monkeypatch):
    from app.api import market as market_api
    monkeypatch.setenv("MM_TASK_DB_PATH", str(tmp_path / "tasks.sqlite"))
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    monkeypatch.setattr(market_api, "_sim_dir", lambda sid: str(tmp_path))
    monkeypatch.setattr(market_api, "_people", lambda sid: (_sample_people(), {}))
    monkeypatch.setattr(market_api, "_profile", lambda sid: None)
    monkeypatch.setattr(market_api, "_voices", lambda sid: None)
    monkeypatch.setattr(market_api, "_start", lambda kind, sid, work: "task_x")

    def no_key():
        raise ValueError("LLM_API_KEY is not configured")
    monkeypatch.setattr(market_api, "_client", no_key)

    base = {"simulation_id": "sim_x", "query": "price"}
    assert client.post("/api/simulation/search", json=base).status_code == 200
    for bad in ({"top_k": 0}, {"top_k": 500}, {"top_k": "many"}, {"bundle": "x"}, {"type": 5}, {"segment": ["a"]}, {"ask": True}):
        assert client.post("/api/simulation/search", json={**base, **bad}).status_code == 400, bad
    assert "LLM_API_KEY" in client.post("/api/simulation/search", json={**base, "ask": True}).get_json()["error"]
    assert client.get("/api/simulation/sim_x/search?q=price&top_k=abc").status_code == 400
    assert client.get("/api/simulation/sim_x/search?q=price&top_k=5").status_code == 200

    voc = {"simulation_id": "sim_x"}
    assert client.post("/api/simulation/gtm/voc", json={**voc, "reviews": "too short\nalso short"}).status_code == 400
    assert client.post("/api/simulation/gtm/voc", json={**voc, "reviews": 42}).status_code == 400
    assert client.post("/api/simulation/gtm/voc", json={**voc, "url": "ftp://example.com/x"}).status_code == 400
    ok = client.post("/api/simulation/gtm/voc", json={**voc, "reviews": "The card requirement put me off completely.\nshort"})
    assert ok.status_code == 200 and ok.get_json()["data"]["task_id"] == "task_x"
    assert client.post("/api/simulation/gtm/geo", json={**voc, "need": ["x"], "offer": "A home workout plan"}).status_code == 400
