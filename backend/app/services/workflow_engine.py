"""Small, reusable workflow operations over the existing simulation engines.

No graph/social simulation is needed for an isolated creative comparison. The
same operations are used by the workflow API (and its CLI client). Nothing here
approves spending, persists credentials, substitutes failed answers or publishes.
"""
from __future__ import annotations

import math
import threading
from types import SimpleNamespace

from . import persona_planner as planner
from . import gtm_suite, cro_and_sparring, email_test


class CallLimitReached(RuntimeError):
    pass


class BoundedClient:
    """Reserve each attempt before dispatch, including nested provider bindings.

    Persisting the reservation before the request also counts an interrupted or
    failed call. SDK retries must be disabled on the wrapped client.
    """
    def __init__(self, client, reserve, record, failures=None):
        self._client, self._reserve, self._record = client, reserve, record
        self._failures = failures if failures is not None else {"count": 0, "lock": threading.Lock()}
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def __getattr__(self, name):
        if name in ("for_agent", "for_slot", "with_people", "with_options") and hasattr(self._client, name):
            return lambda *a, **kw: BoundedClient(getattr(self._client, name)(*a, **kw), self._reserve, self._record, self._failures)
        return getattr(self._client, name)

    def _create(self, **kwargs):
        self._reserve()
        try:
            response = self._client.chat.completions.create(**kwargs)
        except Exception:
            with self._failures["lock"]:
                self._failures["count"] += 1
            self._record({"failed": True})
            raise RuntimeError("Configured provider request failed; check Model settings.") from None
        usage = getattr(response, "usage", None)
        self._record({"input_tokens": getattr(usage, "prompt_tokens", None),
                      "output_tokens": getattr(usage, "completion_tokens", None)})
        return response


def prepare_batch(client, model, inputs, offset, count):
    spec = planner.PersonaSpec.from_dict({
        "segments": [{"label": inputs["audience"], "country": inputs["country"],
                      "count": count, "languages": [inputs["language"]], "platforms": [inputs["platform"]]}],
        "auto": False, "communities": [], "depth": "fast", "interview": False,
        "probes": False, "seed": inputs["seed"] + offset, "graph_agents": "none",
    })
    entities = planner.generate_personas(client, model, spec, inputs["product"], inputs["facts"], parallel=1)
    rows = planner.persona_index(entities)
    for i, (row, entity) in enumerate(zip(rows, entities)):
        row["agent_id"] = offset + i
        row["persona"] = (entity.attributes.get(planner.SYNTHETIC_PROFILE_KEY) or {}).get("persona", "")
        row["fictional"] = True
    return rows


def test_one(client, model, inputs, person, variant):
    """An independent exposure. Never load/write cross-variant behaviour memory."""
    person = {k: v for k, v in person.items() if k not in ("history", "memory")}
    kind = inputs["recipe"]
    text = variant["text"]
    profile = {"name": inputs["name"], "one_liner": inputs["product"], "what_it_does": inputs["facts"]}
    if kind == "landing":
        raw = cro_and_sparring.run_landing_teardown(client, model, {"title": variant["label"], "text": text},
                                                   [person], profile=profile, parallel=1)
        if not raw.get("answered"):
            raise RuntimeError("No usable landing-page response")
        summary = raw.get("summary") or {}
        share = ((summary.get("would_continue") or {}).get("yes") or {}).get("pct")
        if share is None or not summary.get("understood"):
            raise RuntimeError("Incomplete landing-page response or grading")
        return {"score": share / 100 if share is not None else None, "raw": raw,
                "objection": next((q for r in summary.get("confusing") or [] for q in r.get("quotes") or []), "")}
    if kind == "committee":
        raw = gtm_suite.run_buying_committee(client, model, text, [person], mode="b2b", committee_count=1,
                                            profile=profile, parallel=1)
        if not raw.get("answered") or not raw.get("rows"):
            raise RuntimeError("No usable committee response")
        row = raw["rows"][0]
        if row.get("outcome") not in ("buy", "try_first", "wait", "no"):
            raise RuntimeError("Invalid committee outcome")
        return {"score": float(row["outcome"] == "buy"), "raw": raw,
                "objection": row.get("blocker", ""), "reaction": row.get("what_would_unblock", "")}
    if kind == "email":
        failures_before = client._failures["count"]
        subject, _, body = text.partition("\n")
        emails, _ = email_test.normalize_emails([{"id": variant["id"], "from_name": inputs["name"],
                                                "subject": subject, "body": body}])
        raw = email_test.run_email_test(client, model, emails, [person], context=inputs["product"],
                                       seed=inputs["seed"], parallel=1, emotions="off", strict_answers=True)
        sessions = raw.get("sessions") or []
        if client._failures["count"] > failures_before or not sessions or any(
            r.get("opened") and (not r.get("reason") or r.get("reason") == "(no answer)") for r in sessions
        ):
            raise RuntimeError("No usable email response")
        row = sessions[0]
        return {"score": float(row.get("action") == "click"), "raw": raw,
                "objection": row.get("what_would_make_you_click", ""), "reaction": row.get("reason", "")}
    creative = {"headline": text.splitlines()[0], "text": text, "cta": "",
                "platform": inputs["platform"]}
    raw = gtm_suite.score_ad(client, model, creative, [person], inputs["name"], parallel=1)
    answers = raw.pop("_asked", [])
    raw.pop("_by_person", None)
    if not answers or not answers[0].get("ok"):
        raise RuntimeError("Model did not return a usable reaction. Retry the failed exposure.")
    answer = answers[0]["data"]
    value = answer.get("p_click")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise RuntimeError("Model returned an invalid reaction score. Retry the failed exposure.")
    return {"score": value, "objection": str(answer.get("objection") or "")[:600],
            "reaction": str(answer.get("reaction") or "")[:600], "raw": raw}
