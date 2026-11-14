"""Local, revisioned decision workflows. Approval and checkpoints survive restarts."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import threading
import uuid

from ..config import Config
from ..models.task import TaskManager, TaskStatus
from . import workflow_engine as engine

RECIPES = [
    {"id": "ads", "name": "Ads or headlines", "question": "Which idea is clearer?", "hint": "Paste two headlines or complete ads."},
    {"id": "landing", "name": "Landing-page clarity", "question": "Do people understand what I sell?", "hint": "Paste two versions of your page copy. This checks comprehension, not a live website journey."},
    {"id": "saas", "name": "SaaS trial offer", "question": "Is the billing or card requirement confusing?", "hint": "Include the actual trial length, billing and card requirements in each version."},
    {"id": "ecommerce", "name": "Ecommerce offer", "question": "Is shipping, price or returns causing hesitation?", "hint": "Include your actual shipping, price and return policies."},
    {"id": "email", "name": "Email subject and CTA", "question": "Which email communicates the offer?", "hint": "First line: subject. Then paste the body and CTA. No real email is sent."},
    {"id": "committee", "name": "B2B buying committee", "question": "What might the team question?", "hint": "Describe two offers. Simulated users, managers and finance roles discuss them."},
    {"id": "regional", "name": "Regional messaging", "question": "Does the wording make sense in this market?", "hint": "Use the same offer and the target language. Validate with native speakers afterward."},
]
IDS = {r["id"] for r in RECIPES}
CLAIM = re.compile(r"real (?:people|results)|testimonial|\b\d[\d,.+]*\s*(?:happy |paying |active )?(?:customers|users|teams|businesses)|trusted by|guarantee|cancel any\s*time|no commitment", re.I)


class Conflict(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def root():
    return Path(Config.UPLOAD_FOLDER) / "workflows"


def folder(wid):
    if not isinstance(wid, str) or not re.fullmatch(r"wf_[a-f0-9]{24}", wid):
        raise ValueError("Invalid workflow ID")
    return root() / wid


@contextmanager
def locked(wid):
    path = folder(wid)
    if not (path / "workflow.json").is_file():
        raise FileNotFoundError("Workflow not found")
    with (path / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield json.loads((path / "workflow.json").read_text())
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def save(record):
    record["updated_at"] = now()
    path = folder(record["id"])
    temp = path / (".write-" + uuid.uuid4().hex)
    with temp.open("w") as stream:
        os.chmod(temp, 0o600)
        json.dump(record, stream, ensure_ascii=False, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path / "workflow.json")


def text(data, key, maximum=5000):
    value = data.get(key, "")
    if not isinstance(value, str):
        raise ValueError(f"{key} must be text")
    if len(value) > maximum:
        raise ValueError(f"{key} is too long (maximum {maximum} characters)")
    return value.strip()


def integer(value, low, high, label):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{label} must be an integer from {low} to {high}")
    return value


def normalize(data):
    if not isinstance(data, dict):
        raise ValueError("inputs must be an object")
    recipe = data.get("recipe", "ads")
    if not isinstance(recipe, str) or recipe not in IDS:
        raise ValueError("Choose a supported recipe")
    variants = data.get("variants", [{"text": ""}, {"text": ""}])
    if not isinstance(variants, list) or len(variants) != 2 or not all(isinstance(v, dict) for v in variants):
        raise ValueError("Provide exactly two variants")
    amount = data.get("ad_budget")
    if amount is not None and (isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount) or amount < 0):
        raise ValueError("Advertising budget must be a nonnegative number")
    return {"recipe": recipe, "name": text(data, "name", 120), "product": text(data, "product"),
            "facts": text(data, "facts", 24000), "source_url": text(data, "source_url", 2000),
            "audience": text(data, "audience", 1500), "country": text(data, "country", 120),
            "language": text(data, "language", 80) or "English", "platform": data.get("platform", "instagram")
            if data.get("platform", "instagram") in ("instagram", "facebook", "tiktok", "linkedin", "x", "reddit") else "instagram",
            "people": integer(data.get("people", 20), 4, 60, "Audience size"),
            "seed": integer(data.get("seed", 7), 0, 1000000, "Seed"), "seeds": 1,
            "ad_budget": amount, "currency": text(data, "currency", 8) or "USD",
            "claim_evidence": text(data, "claim_evidence", 4000),
            "variants": [{"id": f"v{i+1}", "label": text(v, "label", 80) or f"Version {'AB'[i]}",
                          "text": text(v, "text", 8000)} for i, v in enumerate(variants)]}


def validate_ready(inputs):
    for key in ("name", "product", "audience", "country"):
        if not inputs[key]:
            raise ValueError(f"Add {key.replace('_', ' ')} before preparing the audience")
    if any(not v["text"] for v in inputs["variants"]):
        raise ValueError("Add both variants before preparing the audience")
    if inputs["variants"][0]["text"] == inputs["variants"][1]["text"]:
        raise ValueError("The variants are identical. Change one to make a comparison.")
    if any(CLAIM.search(v["text"]) for v in inputs["variants"]) and not inputs["claim_evidence"]:
        raise ValueError("Add the source for customer, testimonial, guarantee or cancellation claims, or remove those claims")
    if inputs["recipe"] in ("saas", "ecommerce") and not inputs["facts"]:
        raise ValueError("Add the actual billing, shipping or return policies before testing this offer")


def provider():
    """Only allowlisted public metadata and an opaque configuration fingerprint."""
    try:
        pool = Config.get_model_pool()
    except ValueError:
        return {"models": [], "configured": False, "fingerprint": digest("unconfigured")}
    slots = getattr(pool, "slots", [])
    public = [{"provider": str(s.provider), "model": str(s.model)} for s in slots]
    # Include credentials/URL in the one-way fingerprint to invalidate approval on
    # account or endpoint changes, without ever storing those values themselves.
    secret_basis = [(s.provider, s.model, str(s.base_url), str(getattr(s, "api_key", ""))) for s in slots]
    return {"models": public[:1], "configured": bool(slots) and bool(Config.LLM_API_KEY or Config.LLM_POOL),
            "fingerprint": digest(secret_basis)}


def create(inputs, parent=None):
    inputs = normalize(inputs)
    previous = get(parent) if parent else None
    wid = "wf_" + uuid.uuid4().hex[:24]
    root().mkdir(parents=True, exist_ok=True, mode=0o700)
    folder(wid).mkdir(parents=True, mode=0o700)
    record = {"id": wid, "revision": (previous["revision"] + 1) if previous else 1,
              "parent_id": parent, "created_at": now(), "inputs": inputs, "stages": {},
              "people": [], "exposures": {}, "failed_exposures": [], "events": [{"name": "draft_created", "at": now()}],
              "worksheet": None, "provider": None}
    record["artifacts"] = {"checkpoint": "workflow.json", "results": f"/api/workflows/{wid}/results",
                           "evidence": f"/api/workflows/{wid}/evidence", "worksheet": f"/api/workflows/{wid}/worksheet"}
    save(record)
    return record


def get(wid):
    with locked(wid) as record:
        changed = False
        for stage in record["stages"].values():
            if stage["status"] == "running":
                task = TaskManager().get_task(stage["task_id"])
                if task is None or task.status == TaskStatus.FAILED:
                    stage.update(status="interrupted", error="Execution stopped. Review the remaining calls and retry; completed work is saved.")
                    changed = True
        if changed:
            save(record)
        return record


def listing():
    if not root().exists():
        return []
    records = []
    for path in root().glob("wf_*/workflow.json"):
        try:
            record = get(path.parent.name)
            records.append({k: record[k] for k in ("id", "revision", "created_at", "updated_at", "inputs", "stages", "parent_id")})
        except (ValueError, OSError):
            continue
    return sorted(records, key=lambda r: r["updated_at"], reverse=True)


def event(name, wid=None, seconds=None):
    """Small local-only event log. Never include product text, tokens or prompts."""
    if name not in ("setup_opened", "setup_connected", "comparison_started", "active_seconds"):
        raise ValueError("Unsupported local event")
    if wid:
        get(wid)
    row = {"name": name, "at": now(), "workflow_id": wid}
    if seconds is not None:
        row["seconds"] = integer(seconds, 0, 86400, "Active seconds")
    root().mkdir(parents=True, exist_ok=True, mode=0o700)
    path = root() / "local-events.jsonl"
    fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.write(json.dumps(row) + "\n")
    return {"saved": True}


def metrics():
    records = listing()
    events = []
    path = root() / "local-events.jsonl"
    if path.is_file():
        for line in path.read_text().splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
    workflow_events = []
    for record in records:
        workflow_events.extend(get(record["id"])["events"])
    completed = [r for r in records if r["stages"].get("test", {}).get("status") == "completed"]
    return {"storage": "local only; never transmitted as telemetry", "drafts": len(records),
            "setup_opened": sum(e["name"] == "setup_opened" for e in events),
            "setup_connected": sum(e["name"] == "setup_connected" for e in events),
            "comparisons_started": sum(e["name"] == "test_approved" for e in workflow_events),
            "comparisons_completed": len(completed),
            "second_comparisons_completed": max(0, len(completed) - 1),
            "revised_comparisons_completed": sum(bool(r["parent_id"]) for r in completed),
            "failures": sum(e["name"].endswith("_failed") for e in workflow_events),
            "retries": sum(e["name"].endswith("_retried") for e in workflow_events),
            "active_seconds": sum(e.get("seconds", 0) for e in events if e["name"] == "active_seconds"),
            "notes": "Connection confirmations and visible active editing time, not install success or verified usability. No baseline or improvement claim yet."}


def update(wid, inputs):
    inputs = normalize(inputs)
    with locked(wid) as record:
        if record["stages"] and record["inputs"] != inputs:
            raise Conflict("This comparison has an execution history. Save the changes as a new comparison.")
        record["inputs"] = inputs
        save(record)
        return record


def fingerprint(record, phase, current):
    return digest({"inputs": record["inputs"], "provider": current["fingerprint"], "phase": phase,
                   "people": record["people"] if phase == "test" else None})


def estimate(wid, phase):
    if phase not in ("prepare", "test"):
        raise ValueError("Phase must be prepare or test")
    record = get(wid)
    validate_ready(record["inputs"])
    current = provider()
    if phase == "test":
        if record["stages"].get("prepare", {}).get("status") != "completed":
            raise Conflict("Finish preparing and reviewing the audience first")
        if record["provider"]["fingerprint"] != current["fingerprint"]:
            raise Conflict("Provider settings changed. Create a new comparison to prepare a compatible audience.")
    remaining = max(0, record["inputs"]["people"] - len(record["people"])) if phase == "prepare" else \
        len(record["people"]) * 2 - len(record["exposures"])
    # Preparation writes compact cards in batches of five. Recipe engines may
    # make auxiliary calls and retry malformed answers: this is a disclosed
    # planning allowance, not a dollar quote or a promise to use every call.
    expected = math.ceil(remaining / 5) if phase == "prepare" else remaining * (2 if record["inputs"]["recipe"] in ("email", "landing") else 1)
    planned = expected * 3
    used = record["stages"].get(phase, {}).get("calls_used", 0)
    return {"phase": phase, "digest": fingerprint(record, phase, current), "provider": current,
            "remaining_items": remaining, "calls_used": used, "suggested_call_limit": min(1000, max(1, used + planned)),
            "estimated_calls": expected, "retry_allowance": planned, "cost_usd": None, "cost_basis": "unavailable",
            "explanation": "Cost unavailable: model pricing and prompt lengths vary. Set a total model-call limit for this stage, including retries. SDK retries are disabled; provider-internal billing may differ.",
            "ad_budget": record["inputs"]["ad_budget"], "ad_budget_note": "Planning context only; no advertising spend or publishing."}


def approve(wid, phase, supplied_digest, limit, retry=False):
    quote = estimate(wid, phase)
    if not quote["provider"]["configured"]:
        raise Conflict("Connect a model provider in Settings before approving model calls.")
    if supplied_digest != quote["digest"]:
        raise Conflict("Inputs, audience or provider changed. Review a fresh estimate before approving.")
    integer(limit, 1, 1000, "Call limit")
    with locked(wid) as record:
        current = provider()
        if supplied_digest != fingerprint(record, phase, current):
            raise Conflict("The comparison changed during approval. Review it again.")
        stage = record["stages"].get(phase)
        if stage:
            if stage["digest"] != supplied_digest:
                raise Conflict("Provider settings changed. Save as a new comparison.")
            if stage["status"] in ("running", "completed") or not retry:
                return record
        used = stage["calls_used"] if stage else 0
        if limit <= used:
            raise ValueError(f"This stage has already reserved {used} calls. Increase the total limit to retry.")
        task_id = TaskManager().create_task("workflow_" + phase, metadata={"workflow_id": wid})
        record["stages"][phase] = {"status": "running", "task_id": task_id, "digest": supplied_digest,
                                   "call_limit": limit, "calls_used": used, "approved_at": now(),
                                   "usage": stage.get("usage", []) if stage else [], "error": None}
        record["provider"] = current
        record["events"].append({"name": phase + ("_retried" if retry else "_approved"), "at": now()})
        save(record)
    start_worker(wid, phase, task_id)
    return get(wid)


def start_worker(wid, phase, task_id):
    threading.Thread(target=run, args=(wid, phase, task_id), daemon=True).start()


def run(wid, phase, task_id):
    tm = TaskManager()
    def reserve():
        with locked(wid) as record:
            stage = record["stages"][phase]
            if stage["task_id"] != task_id or stage["status"] != "running":
                raise engine.CallLimitReached("Stage no longer active")
            if provider()["fingerprint"] != record["provider"]["fingerprint"]:
                raise engine.CallLimitReached("Provider changed. Stop and create a new comparison.")
            if stage["calls_used"] >= stage["call_limit"]:
                raise engine.CallLimitReached("Model-call limit reached. Completed work is saved; review and increase the limit to retry.")
            stage["calls_used"] += 1
            save(record)
    def usage(value):
        with locked(wid) as record:
            record["stages"][phase]["usage"].append(value)
            save(record)
    try:
        tm.update_task(task_id, status=TaskStatus.PROCESSING, progress=1, message="Preparing audience" if phase == "prepare" else "Comparing variants")
        from ..utils.model_pool import MultiProviderPool
        # One explicit provider, with neither pool failover nor SDK retries hidden
        # behind a single reserved call. Multi-provider studies remain advanced.
        configured = Config.get_model_pool()
        pool = MultiProviderPool([configured.slots[0]], client_options={"max_retries": 0, "timeout": 60})
        client = engine.BoundedClient(pool, reserve, usage)
        record = get(wid)
        inputs = record["inputs"]
        if phase == "prepare":
            while len(record["people"]) < inputs["people"]:
                offset = len(record["people"])
                count = min(5, inputs["people"] - offset)
                people = engine.prepare_batch(client, Config.LLM_MODEL_NAME, inputs, offset, count)
                if not people:
                    stage = get(wid)["stages"][phase]
                    if stage["calls_used"] >= stage["call_limit"]:
                        raise engine.CallLimitReached("Model-call limit reached while preparing profiles. Saved profiles are preserved; review remaining work and increase the limit to retry.")
                    raise RuntimeError("No usable profiles returned. Check your provider and retry; no profiles were invented as replacements.")
                with locked(wid) as record:
                    record["people"].extend(people[:count])
                    save(record)
                tm.update_task(task_id, progress=int(95 * len(record["people"]) / inputs["people"]),
                               message=f"{len(record['people'])} of {inputs['people']} simulated buyers prepared")
        else:
            errors = []
            for variant in inputs["variants"]:
                for person in record["people"]:
                    key = f"{variant['id']}:{person['agent_id']}"
                    if key in record["exposures"]:
                        continue
                    try:
                        response = engine.test_one(client, Config.LLM_MODEL_NAME, inputs, person, variant)
                        with locked(wid) as record:
                            record["exposures"][key] = {"variant": variant["id"], "person": person["agent_id"], **response}
                            save(record)
                    except Exception:
                        errors.append(key)
                        with locked(wid) as record:
                            record["failed_exposures"] = errors
                            save(record)
                    tm.update_task(task_id, progress=int(95 * len(record["exposures"]) / (len(record["people"]) * 2)),
                                   message=f"{len(record['exposures'])} of {len(record['people']) * 2} exposures saved")
                    if get(wid)["stages"][phase]["calls_used"] >= get(wid)["stages"][phase]["call_limit"]:
                        if len(record["exposures"]) < len(record["people"]) * 2:
                            raise engine.CallLimitReached("Model-call limit reached. Saved exposures are preserved; increase the limit and retry remaining work.")
            if errors:
                raise RuntimeError(f"{len(errors)} exposures did not return usable answers. Saved answers are preserved; check the provider and retry remaining exposures.")
        with locked(wid) as record:
            record["stages"][phase]["status"] = "completed"
            if phase == "test":
                record["failed_exposures"] = []
            record["events"].append({"name": phase + "_completed", "at": now()})
            if phase == "test" and record["worksheet"] is None:
                record["worksheet"] = default_worksheet(record)
            save(record)
        tm.complete_task(task_id, {"workflow_id": wid, "phase": phase})
    except Exception as error:
        # Exception strings from SDKs may contain account information or URLs.
        message = str(error) if isinstance(error, (engine.CallLimitReached, Conflict)) else \
            "Stage failed or the provider returned unusable answers. Check provider settings, then retry. Completed outputs are saved."
        with locked(wid) as record:
            record["stages"][phase].update(status="failed", error=message)
            record["events"].append({"name": phase + "_failed", "at": now()})
            save(record)
        tm.fail_task(task_id, message)


def default_worksheet(record):
    i = record["inputs"]
    return (f"# Real-world test: {i['name']}\n\nHypothesis: [What could be clearer?]\n\n"
            f"Audience: {i['audience']} — {i['country']}\n\nVersion A: {i['variants'][0]['text']}\n\n"
            f"Version B: {i['variants'][1]['text']}\n\nHold fixed: offer, audience, channel and timing.\n\n"
            "Method: randomly assign real participants to one version.\nPrimary measure: [Choose before testing]\n"
            "Sample and stopping rule: [Choose before testing]\nBudget and owner: [Add]\n"
            "Observed results: [Add real counts, dates and source]\nDecision: [Keep, change or investigate]\n\n"
            "The simulation generated hypotheses; it did not establish real-world demand or sales performance.\n")


def result(record):
    groups = []
    for variant in record["inputs"]["variants"]:
        rows = [r for r in record["exposures"].values() if r["variant"] == variant["id"]]
        scores = [r["score"] for r in rows if r.get("score") is not None]
        groups.append({"id": variant["id"], "label": variant["label"], "answered": len(rows),
                       "mean": round(sum(scores) / len(scores), 4) if scores else None,
                       "objections": list(dict.fromkeys(r["objection"] for r in rows if r.get("objection")))[:6],
                       "reactions": [r["reaction"] for r in rows if r.get("reaction")][:4]})
    complete = record["stages"].get("test", {}).get("status") == "completed"
    means = [g["mean"] for g in groups]
    comparable = complete and all(m is not None for m in means)
    gap = abs(means[0] - means[1]) if comparable else None
    # A small descriptive difference is inconclusive, not a significance test.
    lead = groups[0 if means[0] > means[1] else 1]["label"] if comparable and gap > 0.05 else None
    objections = [value for group in groups for value in group["objections"]]
    next_action = (f"Investigate this simulated concern first: “{objections[0][:180]}”. Check whether the relevant factual detail is missing from the copy; change only that detail, then test with real people.") if objections else \
        "Ask real participants to explain each version in their own words. Investigate missing or confusing details before choosing a version."
    what_differed = (f"The two versions differ by {gap * 100:.1f} percentage points in this simulation's descriptive score.") if comparable else \
        "The comparison is incomplete or lacks comparable scores. Review the saved evidence and remaining work."
    metrics = {"landing": "Simulated share who would continue", "committee": "Simulated share choosing buy", "email": "Simulated share clicking"}
    return {"evidence_type": "simulation", "complete": complete, "variants": groups,
            "metric_label": metrics.get(record["inputs"]["recipe"], "Mean model-reported click likelihood"),
            "failed_exposures": len(record.get("failed_exposures", [])),
            "verdict": f"{lead} received more simulated interest" if lead else "No clear winner",
            "what_differed": what_differed,
            "difference": "Descriptive model reactions only; a difference above five percentage points is highlighted for exploration, not statistical significance or predictive confidence.",
            "next_action": next_action,
            "limits": "Fictional buyers and AI-generated reactions. These are not observed clicks, testimonials, established demand or sales forecasts.",
            "worksheet": record["worksheet"] if record["worksheet"] is not None else default_worksheet(record)}


def evidence_html(record):
    data = html.escape(json.dumps(record, ensure_ascii=False, indent=2))
    return ("<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
            "<title>MarketMirror simulation evidence</title><style>body{font:16px system-ui;max-width:1000px;margin:40px auto;padding:20px}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>"
            "<h1>MarketMirror simulation evidence</h1><p>Fictional buyers. AI-generated responses, not observed customer behaviour.</p><pre>" + data + "</pre></html>")
