"""Sales rehearsal: prompts, parsing, scoring, two-turn run with a fake interviewer, and the API."""

import json
import time

from app.services import pitch as ps

PEOPLE = [{"agent_id": 1, "name": "Priya", "segment": "India young professionals", "country": "India"},
          {"agent_id": 2, "name": "Rosario", "segment": "Philippines parents", "country": "Philippines"},
          {"agent_id": 3, "name": "Amani", "segment": "Kenya students", "country": "Kenya"}]

T1 = {1: {"reply": "Hmm, how much is it?", "verdict": "maybe", "interest": 6, "trust": 5, "objection": "Too pricey for me",
          "objection_type": "price", "question_for_seller": "Is there a student plan?", "decision_role": "I decide alone",
          "best_time_to_reach": "WhatsApp, evenings"},
      2: {"reply": "Hindi ako sigurado, parang scam.", "verdict": "no", "interest": 3, "trust": 2, "objection": "Looks like a scam",
          "objection_type": "trust", "decision_role": "I ask my partner/family"},
      3: {"reply": "Sawa, I'm in.", "verdict": "yes", "interest": 9, "trust": 8, "objection": "", "objection_type": "none",
          "decision_role": "I decide alone"}}
T2 = {1: {"reply": "Ok that's fair.", "verdict": "yes", "moved": "yes", "remaining_objection": "", "next_step_you_accept": "a trial"},
      2: {"reply": "Still not sure.", "verdict": "maybe", "moved": "partly", "remaining_objection": "need to see reviews",
          "next_step_you_accept": "more info"}}
REBUTTALS = {"price": "Less than a coffee a week, cancel any time.", "*": "What would need to be true for a yes?"}


def fake_batch(items):
    out = {}
    for it in items:
        aid = it["agent_id"]
        if "Same conversation" in it["prompt"]:
            out[aid] = "```json\n" + json.dumps(T2[aid]) + "\n```"
        else:
            out[aid] = json.dumps(T1[aid])
    return out


def test_prompts_mention_script_and_json():
    p = ps.pitch_prompt("Hi, I'm from Fitloop.", product="Fitloop", channel="call")
    assert "calls you" in p and "Hi, I'm from Fitloop." in p and '"verdict"' in p
    r = ps.rebuttal_prompt({"reply": "too pricey"}, "It is cheap.")
    assert "too pricey" in r and "It is cheap." in r and '"moved"' in r


def test_parse_variants():
    t = ps.parse_turn1('Sure: {"reply": "ok", "verdict": "Probably not", "interest": "7/10", "objection": "x", "objection_type": "weird"}')
    assert t["verdict"] == "no" and t["interest"] == 7.0 and t["objection_type"] == "other"
    assert ps.parse_turn1("no json here") is None
    t2 = ps.parse_turn2('{"verdict": "maybe", "moved": "a bit"}')
    assert t2["moved"] == "partly" and t2["verdict"] == "maybe"


def test_rebuttals_from_markdown_and_pick():
    rb = ps.parse_rebuttals("## price\nCheap.\n\n## any\nGeneric answer.\n")
    assert rb == {"price": "Cheap.", "*": "Generic answer."}
    assert ps.pick_rebuttal("trust", rb) == "Generic answer." and ps.pick_rebuttal("none", rb) is None
    assert ps.parse_rebuttals('{"trust": "Proof."}') == {"trust": "Proof."}
    assert ps.parse_rebuttals("just one answer") == {"*": "just one answer"}


def test_run_two_turns_and_score():
    out = ps.run(fake_batch, PEOPLE, "Hi there", REBUTTALS, product="Fitloop", channel="message", batch=2)
    assert out["answered"] == 3 and out["rebuttals_given"] == 2
    assert out["verdict_before"] == {"yes": 33.3, "maybe": 33.3, "no": 33.3}
    assert out["verdict_after"]["yes"] == 66.7 and out["verdict_after"]["maybe"] == 33.3
    price = next(o for o in out["objections"] if o["type"] == "price")
    assert price["rebuttal_success"] == 100.0 and price["questions"] == ["Is there a student plan?"]
    trust = next(o for o in out["objections"] if o["type"] == "trust")
    assert trust["rebuttal"] == REBUTTALS["*"] and trust["rebuttal_success"] == 50.0
    people = {r["agent_id"]: r for r in out["people"]}
    assert people[3]["turn2"] is None                         # a firm yes is not re-pitched
    assert people[3]["lead_score"] > people[1]["lead_score"] > people[2]["lead_score"]
    assert [h["name"] for h in out["hot_leads"]][:2] == ["Amani", "Priya"]
    assert out["pitch_score"] == 83
    assert any("trust" in f for f in out["fixes"])             # rebuttal moved only half of them


def test_pitch_api(tmp_path, monkeypatch):
    from app import create_app
    from app.config import Config
    from app.services.simulation_manager import SimulationManager
    from app.services.simulation_runner import SimulationRunner
    from app.api import market
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path))
    sim = tmp_path / "sim_p"
    sim.mkdir()
    (sim / "state.json").write_text(json.dumps({"simulation_id": "sim_p", "project_id": "p", "graph_id": "g", "status": "ready"}))
    monkeypatch.setattr(market, "_people", lambda sid: (PEOPLE, {"enable_reddit": True}))

    def fake_interview(sid, interviews, platform=None, timeout=0):
        texts = fake_batch(interviews)
        return {"success": True, "result": {"results": [{"agent_id": a, "response": t} for a, t in texts.items()]}}

    monkeypatch.setattr(SimulationRunner, "interview_agents_batch", staticmethod(fake_interview))
    app = create_app()
    app.config.update(TESTING=True)
    c = app.test_client()
    assert c.post("/api/simulation/pitch", json={"simulation_id": "sim_p"}).status_code == 400

    def run(body):
        r = c.post("/api/simulation/pitch", json=body)
        assert r.status_code == 200, r.get_json()
        task_id = r.get_json()["data"]["task_id"]
        for _ in range(100):
            st = c.post("/api/simulation/market-task/status", json={"task_id": task_id}).get_json()["data"]
            if st["status"] in ("completed", "failed"):
                break
            time.sleep(0.05)
        assert st["status"] == "completed", st
        return r.get_json()["data"], c.get("/api/simulation/sim_p/pitch").get_json()["data"]

    started, got = run({"simulation_id": "sim_p", "script": "Hi", "rebuttals": REBUTTALS})
    assert started["people"] == 3 and started["rebuttals"] == ["*", "price"]
    assert got["answered"] == 3 and got["pitch_score"] == 83 and got["script"] == "Hi"
    started, got = run({"simulation_id": "sim_p", "script": "Hi", "rebuttals": REBUTTALS, "segment": "Kenya students"})
    assert started["people"] == 1 and got["answered"] == 1 and got["people"][0]["name"] == "Amani"
