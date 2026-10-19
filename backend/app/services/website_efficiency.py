"""Small model views and cooperative, whole-run browser budgets.

Full observations remain evidence. Budgets stop at action boundaries: an
in-flight provider call or browser operation cannot be undone by this ledger.
"""
from __future__ import annotations

import hashlib
import json
import math
import time


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def options(spec):
    result = {}
    for key, maximum in (("max_model_calls", 600), ("max_input_tokens", 100_000_000), ("max_elapsed_s", 86400)):
        value = spec.get(key)
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{key} must be a positive number")
            if key != "max_elapsed_s" and int(value) != value:
                raise ValueError(f"{key} must be an integer")
            if value > maximum:
                raise ValueError(f"{key} must be at most {maximum}")
        result[key] = value
    mode = spec.get("observation_mode", "compact")
    if mode not in ("compact", "full"):
        raise ValueError("observation_mode must be compact or full")
    for key, default, low, high in (("observation_text_chars", 4000, 1000, 10000), ("loop_limit", 3, 2, 10)):
        value = spec.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ValueError(f"{key} must be an integer from {low} to {high}")
        result[key] = value
    return {**result, "observation_mode": mode}


def model_observation(observation, spec):
    if spec["observation_mode"] == "full":
        return observation
    # Execution still uses the complete, original observation and handles.
    fields = ("id", "tag", "type", "role", "label", "href", "disabled", "read_only", "checked", "has_value",
              "editable", "required", "multiple", "min", "max", "expanded", "selected", "options", "frame")
    def trim(value):
        if isinstance(value, dict):
            return {k: trim(v) for k, v in value.items() if v is not None and (v != "" or k == "value") and v != []}
        if isinstance(value, list):
            return [trim(v) for v in value]
        return value
    text = observation.get("text", "")
    return trim({**{key: observation.get(key) for key in
        ("observation_id", "url", "title", "active_tab", "tabs", "frames", "allowed_urls", "browser_events")},
        "text": text[:spec["observation_text_chars"]],
        "text_truncated": len(text) > spec["observation_text_chars"],
        "controls": [{key: control.get(key) for key in fields} for control in observation.get("controls", [])]})


class RunBudget:
    def __init__(self, spec):
        self.spec, self.started = spec, time.monotonic()
        self.calls, self.input_tokens, self.usage_complete = 0, 0, True

    def reason(self):
        if self.spec["max_elapsed_s"] is not None and time.monotonic() - self.started >= self.spec["max_elapsed_s"]:
            return "max_elapsed_s"
        if self.spec["max_model_calls"] is not None and self.calls >= self.spec["max_model_calls"]:
            return "max_model_calls"
        if self.spec["max_input_tokens"] is not None:
            if not self.usage_complete:
                return "input_usage_unavailable"
            if self.input_tokens >= self.spec["max_input_tokens"]:
                return "max_input_tokens"
        return None

    def charge(self, usage):
        value = usage.get("input_tokens")
        if value is None:
            self.usage_complete = False
        self.input_tokens += value or 0


def usage_summary(sessions):
    calls = sum(s["model_calls"] for s in sessions)
    usage = [step["usage"] for session in sessions for step in session["steps"] if "usage" in step]
    result = {"model_calls": calls, "measured_calls": len(usage)}
    for field in ("uncached_input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "model_ms", "prompt_chars", "full_prompt_chars"):
        values = [u[field] for u in usage if u.get(field) is not None]
        result[field] = sum(values) if len(values) == calls else None
    costs = [u["cost_usd"] for u in usage if isinstance(u.get("cost_usd"), (int, float)) and math.isfinite(u["cost_usd"]) and u["cost_usd"] >= 0]
    result.update(cost_usd=sum(costs) if len(costs) == calls else None,
                  reported_cost_usd=sum(costs) if costs else None,
                  cost_complete=len(costs) == calls,
                  cost_bases=sorted({u["cost_basis"] for u in usage if u.get("cost_basis")}),
                  models=sorted({u["model"] for u in usage if u.get("model")}))
    return result


class LoopGuard:
    """Detect repeated action attempts on equivalent page/control state.

    Volatile observation IDs and console noise do not count as progress.
    Intentional repeated scrolling is excluded: scroll position is not in the
    snapshot. Identity values never enter the fingerprint.
    """
    def __init__(self, limit):
        self.limit, self.counts = limit, {}

    def repeated(self, observation, action):
        if action.get("action") in ("scroll", "leave", "finish"):
            return False
        controls = observation.get("controls", [])
        target_index = next((i for i, c in enumerate(controls) if c["id"] == action.get("target")), None)
        state = {key: observation.get(key) for key in ("url", "text", "active_tab", "tabs")}
        state["controls"] = [{k: v for k, v in c.items() if k not in ("id", "rect")} for c in controls]
        request = {k: v for k, v in action.items() if k not in ("target", "observation_id", "reason")}
        fingerprint = hashlib.sha256(dumps([state, target_index, request]).encode()).hexdigest()
        self.counts[fingerprint] = self.counts.get(fingerprint, 0) + 1
        return self.counts[fingerprint] >= self.limit
