"""Customer intake: reading exports and transcripts, scrubbing contact details, verbatim-only quotes, nothing
invented, the offline engine, records flowing into grounded personas, and the API."""

import json
from types import SimpleNamespace

from app.services import intake
from app.services import persona_planner as pp

REVIEWS = [
    {"Customer ID": "c1", "Name": "Priya Sharma", "Plan": "Pro", "Country": "India", "Rating": "2",
     "Review": "Priya here. The app kept charging me after I cancelled, email me at priya.s@example.com or call "
               "+91 98765 43210. I only pay for tools my manager approves."},
    {"Customer ID": "c1", "Name": "Priya Sharma", "Plan": "Pro", "Country": "India", "Rating": "3",
     "Review": "Support fixed it in two days. I still compare three options before paying for anything."},
    {"Customer ID": "c2", "Name": "Tom Becker", "Plan": "Free", "Review": "Love the reminders but the free plan "
               "is too limited, see https://example.com/post. I would pay if it synced with my calendar."},
    {"Customer ID": "c3", "Name": "Empty Row", "Review": ""},
]


class FakeLLM:
    def __init__(self, body=None, fail=False):
        self.body, self.fail, self.prompts = body, fail, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.prompts.append(kw["messages"][1]["content"])
        if self.fail:
            raise TimeoutError("boom")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.body), finish_reason="stop")],
                               usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50))


def complete_from(body, seen=None):
    def complete(system, user):
        if seen is not None:
            seen.append(user)
        return body, {"input_tokens": 10, "output_tokens": 5}
    return complete


MODEL_BODY = json.dumps({"people": [
    {"i": 1, "segment": "Pro", "age": 34, "gender": "female", "country": "India", "city": "Pune",
     "excerpts": ["The app kept charging me after I cancelled", "I only pay for tools my manager approves.",
                  "I hate subscriptions so much"],
     "bde": {"decision_procedure": {"who_they_ask": "my manager", "stoppers": ["charges after cancelling"]}}},
    {"i": 2, "segment": "Free", "excerpts": ["I would pay if it synced with my calendar."], "country": "Germany"},
]})


# ---------------------------------------------------------------- reading and scrubbing

def test_scrub_removes_contact_details_and_names_but_keeps_prices_and_dates():
    text = ("Ana Lopez wrote on 2026-03-14: mail ana@x.io, phone (555) 123-4567, card 4111 1111 1111 1111, "
            "@ana_l on X, https://x.io/a. It costs $1,200,000 a year, 5 stars. Ana says hi.")
    out, counts = intake.scrub(text, ["Ana Lopez"])
    for gone in ("ana@x.io", "123-4567", "4111", "@ana_l", "https://", "Ana Lopez", "Ana says"):
        assert gone not in out
    assert "2026-03-14" in out and "$1,200,000" in out and "A.L." in out
    assert counts["email"] == 1 and counts["phone"] == 1 and counts["number"] == 1 and counts["handle"] == 1
    assert counts["link"] == 1 and counts["name"] >= 2


def test_read_sources_handles_csv_json_and_transcripts(tmp_path):
    (tmp_path / "r.csv").write_text("author,text\nJo,I paid twice for the same thing and nobody answered\n", encoding="utf-8")
    (tmp_path / "r.json").write_text(json.dumps({"reviews": [{"user": "Kim", "body": "Too pricey for students like me honestly"}]}), encoding="utf-8")
    (tmp_path / "call_07.txt").write_text("Interviewer: why did you leave?\nCustomer: the onboarding took an hour.", encoding="utf-8")
    rows = intake.read_sources([str(tmp_path / n) for n in ("r.csv", "r.json", "call_07.txt")])
    assert [r["_source"] for r in rows] == ["r.csv", "r.json", "call_07.txt"]
    people, counts = intake.prepare(rows)
    assert counts["people"] == 3 and counts["rows_with_text"] == 3
    assert any("onboarding took an hour" in p["material"] for p in people)


def test_rows_group_by_customer_and_empty_rows_are_skipped():
    people, counts = intake.prepare(REVIEWS)
    assert counts == {**counts, "rows": 4, "rows_with_text": 3, "people": 2}
    priya = people[0]
    assert priya["rows"] == 2 and priya["meta"]["segment"] == "Pro" and priya["meta"]["country"] == "India"
    assert "Priya" not in priya["material"] and "priya.s@example.com" not in priya["material"]
    assert "98765" not in priya["material"] and "P." in priya["material"]
    assert "https://" not in people[1]["material"]


# ---------------------------------------------------------------- extraction rules

def test_llm_records_keep_only_verbatim_quotes_and_stated_facts():
    seen = []
    out = intake.run(REVIEWS, engine="llm", complete=complete_from(MODEL_BODY, seen), context="Habit app")
    assert "Habit app" in seen[0] and "Priya" not in seen[0] and "example.com" not in seen[0]
    a, b = out["records"]
    assert a["excerpts"] == ["The app kept charging me after I cancelled", "I only pay for tools my manager approves."]
    assert a["country"] == "India" and a["segment"] == "Pro"
    assert "age" not in a and "city" not in a and "gender" not in a      # nothing in the material says 34, Pune or female
    assert a["bde"]["decision_procedure"]["who_they_ask"] == "my manager"
    assert a["bde_source"].startswith("real_intake")
    assert "country" not in b                                             # "Germany" appears nowhere in Tom's words
    c = out["counts"]
    assert c["excerpts_dropped"] == 1 and c["fields_dropped"] >= 4 and c["records"] == 2 and c["failed"] == 0
    assert out["usage"] == {"calls": 1, "input_tokens": 10, "output_tokens": 5}


def test_person_left_out_or_failed_call_gets_no_record():
    body = json.dumps({"people": [{"i": 1, "excerpts": ["Support fixed it in two days."]}]})
    out = intake.run(REVIEWS, engine="llm", complete=complete_from(body))
    assert len(out["records"]) == 1 and out["counts"]["failed"] == 1

    def boom(system, user):
        raise TimeoutError("down")
    out = intake.run(REVIEWS, engine="llm", complete=boom)
    assert out["records"] == [] and out["counts"]["failed"] == 2


def test_supplied_engine_needs_no_model_and_quotes_the_person():
    out = intake.run(REVIEWS, engine="supplied")
    assert out["engine"] == "supplied" and out["usage"] == {} and len(out["records"]) == 2
    for r in out["records"]:
        assert r["excerpts"] and r["intake"]["engine"] == "supplied"
    assert any("compare three options" in q for q in out["records"][0]["excerpts"])


def test_bad_input_is_refused():
    for rows, engine in (([{"Review": ""}], "supplied"), (REVIEWS, "magic"), (REVIEWS, "llm")):
        try:
            intake.run(rows, engine=engine)
        except ValueError:
            continue
        raise AssertionError(f"{engine} should fail")


def test_merge_into_spec_keeps_segments_and_renames_clashes():
    spec = {"segments": [{"name": "Students", "count": 4}], "real_profiles": [{"name": "Customer 1", "excerpts": ["x"]}]}
    out = intake.run(REVIEWS, engine="supplied")
    merged = intake.merge_into_spec(out["records"], spec)
    names = [r["name"] for r in merged["real_profiles"]]
    assert merged["segments"] == spec["segments"] and len(names) == 3 and len(set(names)) == 3
    again = intake.merge_into_spec(out["records"], merged, replace=True)
    assert len(again["real_profiles"]) == 3                               # earlier intake records replaced, not doubled
    assert "Customer 2" in intake.render_markdown(out)


# ---------------------------------------------------------------- into the planner

class PlannerClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="{}"), finish_reason="stop")],
                               usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1))


def test_records_become_grounded_personas_with_honest_provenance():
    out = intake.run(REVIEWS, engine="llm", complete=complete_from(MODEL_BODY))
    spec = pp.PersonaSpec.from_dict(intake.merge_into_spec(out["records"], {"interview": False}))
    ents = pp.generate_personas(PlannerClient(), "m", spec, "req", "ctx")
    grounded = [e for e in ents if str((e.attributes.get("provenance") or {}).get("profile", "")).startswith("real_intake")]
    assert len(grounded) == 2
    first = grounded[0].attributes
    assert first["provenance"]["bde"].startswith("real_intake: model-extracted")
    assert "The app kept charging me after I cancelled" in first["interview_summary"]
    assert first["segment"] == "Pro" and first["country"] == "India"


# ---------------------------------------------------------------- API

def _app(monkeypatch, body=MODEL_BODY):
    from app import create_app
    from app.api import market
    monkeypatch.setattr(market, "_client", lambda: FakeLLM(body))
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_intake_api(monkeypatch):
    c = _app(monkeypatch)
    assert c.post("/api/simulation/intake", json={}).status_code == 400
    assert c.post("/api/simulation/intake", json={"rows": REVIEWS, "engine": "magic"}).status_code == 400
    r = c.post("/api/simulation/intake", json={"rows": REVIEWS, "context": "Habit app"})
    assert r.status_code == 200, r.get_json()
    d = r.get_json()["data"]
    assert d["engine"] == "llm" and d["counts"]["records"] == 2 and d["usage"]["calls"] == 1
    off = c.post("/api/simulation/intake", json={"rows": REVIEWS, "engine": "supplied"}).get_json()["data"]
    assert off["engine"] == "supplied" and "model" not in off
