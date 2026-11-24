"""A small scripted eval of the chat agent: intent -> expected tool sequence, with zero unapproved spend.

The model is scripted (what a good model would call); the eval checks what the app does with those calls: which tools
actually run, which cards the user sees and that nothing that makes model calls runs without the user's yes.
"""
import pytest

from app.services.chat_agent import state, tools as T
from chat_agent_fakes import SIM, FakeAdapter, FakeExecutor, answer, ask, run, say, tool

GA4 = "Country,City,Active users\nIndia,Mumbai,1200\nIndia,Pune,300\n"
REVIEWS = "id,review,purchased\n1,Too pricey,no\n2,Love it,yes\n"
JOB = {"job_id": "abcdef0123", "result_path": "/r", "status": "running"}
SEGS = [{"label": "Busy parents", "count": 12, "country": "India", "platforms": ["instagram"]}]

CHATS = [
    {"name": "headline test for busy parents in India",
     "say": "test these two headlines for busy parents in India: 'Dinner in 10' vs 'No more 8pm panic'",
     "script": [tool("design_audience", {"name": "parents_in", "segments": SEGS}),
                tool("market_test", {"config": {"requirement": "Which headline makes busy parents in India want to try it?",
                                                "personas": "/fake/audiences/parents_in.json",
                                                "survey": {"messages": ["Dinner in 10", "No more 8pm panic"], "split": True}}}),
                say("Both headlines are running on 12 simulated parents.")],
     "answers": [{"segments": SEGS}, {"decision": "run", "max_spend_usd": 3}],
     "cards": ["audience", "spend"], "ran": ["market_test"]},
    {"name": "design an audience",
     "say": "design an audience of young parents on Android",
     "script": [tool("design_audience", {"segments": [{"label": "Young parents", "count": 10, "platforms": ["android"]}]}), say("Saved.")],
     "answers": [{"segments": [{"label": "Young parents", "count": 15, "platforms": ["android"]}]}],
     "cards": ["audience"], "ran": []},
    {"name": "compare last two",
     "say": "compare my last two experiments and tell me which to run next",
     "script": [tool("compare_runs", {"runs": ["fitloop_v2", "fitloop_v1"]}), say("v2 leans ahead, too close to call.")],
     "answers": [], "cards": [], "ran": ["compare_runs"]},
    {"name": "ask the buyers about price",
     "say": "ask the buyers about price",
     "script": [tool("ask_buyers", {"action": "focus_group", "simulation_id": SIM, "guide": ["Would you pay $9 a month?"]}),
                say("The group split on price.")],
     "answers": [{"decision": "run"}], "cards": ["spend"], "ran": ["ask_buyers"]},
    {"name": "GA4 export sizes the audience",
     "say": "use my GA4 export to size the audience", "files": [{"name": "ga4.csv", "text": GA4}],
     "script": [say("Your visitors are mostly in Mumbai and Pune.")],
     "answers": [], "cards": [], "ran": ["analytics_audience"]},
    {"name": "public research",
     "say": "what do people say about meal kits?",
     "script": [tool("switch_phase", {"phase": "setup"}), tool("research", {"query": "meal kits"}), say("Price and waste come up most.")],
     "answers": [{"decision": "go"}], "cards": ["outside"], "ran": ["research"]},
    {"name": "read a landing page",
     "say": "understand my product from https://example.com/mealkit",
     "script": [tool("switch_phase", {"phase": "setup"}), tool("understand", {"url": "https://example.com/mealkit"}), say("Read it.")],
     "answers": [{"decision": "run"}], "cards": ["spend"], "ran": ["understand"]},
    {"name": "reviews -> split, intake declined",
     "say": "here are my customer reviews", "files": [{"name": "reviews.csv", "text": REVIEWS}],
     "script": [tool("real_split", {"real_csv": "/fake/uploads/reviews.csv"}),
                tool("intake", {"files": ["/fake/uploads/reviews_conditioning.csv"]}), say("Kept them aside.")],
     "answers": [{"decision": "stop"}], "cards": ["spend"], "ran": ["real_split"]},
    {"name": "world map",
     "say": "show the world map of my last run",
     "script": [tool("open_view", {"view": "world_map", "run": "fitloop_v2"}), say("Here it is.")],
     "answers": [], "cards": [], "ran": ["open_view"]},
    {"name": "price test with missing facts",
     "say": "price check: 9 or 12 dollars?",
     "script": [tool("run_test", {"spec": {"type": "price"}}), say("12 holds up with this audience.")],
     "answers": [{"values": {"simulation_id": SIM, "spec.variants": "9\n12"}}, {"decision": "run"}],
     "cards": ["form", "spend"], "ran": ["run_test"]},
    {"name": "lock a forecast before launch",
     "say": "before launch, lock the forecast for fitloop_v2",
     "script": [tool("cli", {"args": ["forecast", "lock", "--run-dir", "mirofish_runs/fitloop_v2"]}), say("Locked.")],
     "answers": [], "cards": [], "ran": ["cli"]},
    {"name": "model tries to approve its own spend, user stops",
     "say": "just run the full test",
     "script": [tool("market_test", {"config": {"requirement": "x", "auto_personas": 50, "approve_spend": True}}), say("Nothing ran.")],
     "answers": [{"decision": "stop"}], "cards": ["spend"], "ran": []},
]


@pytest.mark.parametrize("chat", CHATS, ids=[c["name"] for c in CHATS])
def test_scripted_chat(chat):
    state.reset()
    ex = FakeExecutor(results={"market_test": JOB, "ask_buyers": JOB, "analytics_audience": {"out": "/fake/personas.json"}})
    adapter = FakeAdapter(chat["script"])
    answers = list(chat["answers"])
    cards = []
    result = run(ask(chat["say"], files=chat.get("files", [])), ex, adapter)
    while result["status"] == "waiting":
        cards.append(result["pending"]["kind"])
        result = run(answer(result, answers.pop(0)), ex, adapter)
    assert result["status"] == "complete" and not answers
    assert cards == chat["cards"]
    assert [c[0] for c in ex.calls] == chat["ran"]
    for name, args, approval in ex.calls:                    # zero unapproved spend
        if T.classify(name, args)["cost"] == T.SPEND:
            assert approval, f"{name} ran without the user's approval"
            if name == "market_test":
                assert approval["approve_spend"]["content"]["decision"] in ("run", "people_first")
                assert "approve_spend" not in args["config"]
