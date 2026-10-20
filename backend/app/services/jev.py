"""
Client for TypeSafe's Jev ("System One" decision model), an optional scoring and classification engine.

Jev is not a chat model. It reads a `state` (text, an object or a list) and answers typed questions with
probabilities:

    POST https://api.typesafe.ai/v1/systemone          Authorization: Bearer $TYPESAFE_API_KEY
    {"state": "...", "model": "jev-latest", "questions": {"q1": {...}}}
    -> {"model": "jev-1.14...", "answers": {"q1": {...}}, "usage": {"input_tokens": n, "output_tokens": n}}

    choice  {type, instructions?, criteria: {label: description}}  -> {choice, confidence, probabilities{label: p}}
    score   {type, instructions?, criteria: [level 0, level 1, ...]} -> {score, confidence, legend, probabilities{"0": p}}
    noul    {type, instructions}                                    -> {noul: 0..1}

OpenRouter serves the same endpoint at https://openrouter.ai/api/v1/systemone (models typesafe/jev-1.14,
~typesafe/jev-latest) with an OpenRouter key, and adds `usage.cost` in USD.

Routing (read from the environment, with the repo .env filling keys the environment does not set):
  - TYPESAFE_API_KEY set (JEV_VIA empty, "typesafe" or "direct"): direct to api.typesafe.ai
  - JEV_VIA=openrouter and OPENROUTER_API_KEY set: through OpenRouter
  - JEV_BASE_URL overrides the endpoint of either route; JEV_MODEL overrides the model
  - JEV_PARALLEL (default 4) caps parallel requests, JEV_TIMEOUT (s, default 60), JEV_RETRIES (default 3)

Requests that fail after the retries are counted as failed and raise; callers never get a substitute answer.
This module uses only the standard library and `requests`, so the CLI can load it without the backend.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import requests

logger = logging.getLogger("mirofish.jev")

TYPESAFE_URL = "https://api.typesafe.ai/v1/systemone"
OPENROUTER_URL = "https://openrouter.ai/api/v1/systemone"
DEFAULT_MODELS = {"typesafe": "jev-latest", "openrouter": "~typesafe/jev-latest"}
ENV_KEYS = ("TYPESAFE_API_KEY", "OPENROUTER_API_KEY", "JEV_VIA", "JEV_BASE_URL", "JEV_MODEL", "JEV_PARALLEL",
            "JEV_TIMEOUT", "JEV_RETRIES", "SSR_ENGINE")
RETRY_STATUS = (408, 409, 425, 429)
MAX_WAIT_S = 60.0

_sleep = time.sleep          # tests replace this


class JevError(RuntimeError):
    """A Jev request failed (after retries) or returned an unusable answer."""


class JevUnavailable(JevError):
    """No Jev key or route is configured."""


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------

def env_file_path() -> str:
    """The settings file the backend loads (backend/app/config.py): MIROFISH_ENV_FILE or the repo .env."""
    return os.environ.get("MIROFISH_ENV_FILE") or os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".env"))


def _env_file_values(path: str) -> Dict[str, str]:
    found: Dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[len("export "):].strip()
                key, sep, value = line.partition("=")
                if sep and key.strip() in ENV_KEYS:
                    found[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    return found


def _env(env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """The Jev settings: `env` when given (tests), else the process environment with the .env file filling gaps.
    The backend has already loaded .env into the environment; the CLI has not."""
    if env is not None:
        return {k: str(env.get(k) or "") for k in ENV_KEYS}
    out = {k: os.environ.get(k) or "" for k in ENV_KEYS}
    for k, v in _env_file_values(env_file_path()).items():
        if not out.get(k):
            out[k] = v
    return out


def _int(value: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(str(value).strip())))
    except (TypeError, ValueError):
        return default


def _resolve(env: Optional[Dict[str, str]] = None) -> Tuple[Dict[str, Any], str]:
    """(settings without the key, key). settings["configured"] is False with a reason when no route is usable."""
    e = _env(env)
    via = e["JEV_VIA"].strip().lower()
    base = e["JEV_BASE_URL"].strip().rstrip("/")
    cfg: Dict[str, Any] = {"configured": False, "route": None, "endpoint": None, "model": None, "key_env": None,
                           "reason": None, "parallel": _int(e["JEV_PARALLEL"], 4, 1, 32),
                           "timeout": _int(e["JEV_TIMEOUT"], 60, 5, 600), "retries": _int(e["JEV_RETRIES"], 3, 0, 8),
                           "ssr_engine": (e["SSR_ENGINE"] or "").strip().lower() or "embeddings"}
    if via == "openrouter":
        route, key_env, url = "openrouter", "OPENROUTER_API_KEY", OPENROUTER_URL
    elif via in ("", "typesafe", "direct"):
        route, key_env, url = "typesafe", "TYPESAFE_API_KEY", TYPESAFE_URL
    else:
        cfg["reason"] = f"JEV_VIA={via!r} is not a known route (use typesafe or openrouter)"
        return cfg, ""
    if base:
        url = base if base.endswith("/systemone") else base + "/systemone"
    key = e[key_env].strip()
    cfg.update(route=route, endpoint=url, model=e["JEV_MODEL"].strip() or DEFAULT_MODELS[route], key_env=key_env)
    if not key:
        hint = (" (OPENROUTER_API_KEY is set: add JEV_VIA=openrouter to use Jev through OpenRouter)"
                if route == "typesafe" and e["OPENROUTER_API_KEY"].strip() else "")
        cfg["reason"] = f"{key_env} is not set{hint}"
        return cfg, ""
    cfg["configured"] = True
    return cfg, key


def settings(env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Route, endpoint and model, and whether a key is configured. Never contains the key."""
    return _resolve(env)[0]


def available(env: Optional[Dict[str, str]] = None) -> bool:
    return bool(_resolve(env)[0]["configured"])


def method_label(model: Optional[str]) -> str:
    """'jev (jev-1.14)': the engine name used in results and on the dashboard."""
    return f"jev ({model})" if model else "jev"


# --------------------------------------------------------------------------
# Usage accounting
# --------------------------------------------------------------------------

class JevUsage:
    """Requests, failures and tokens across many calls (thread-safe). cost is summed only when the route reports
    it (OpenRouter's usage.cost, USD); otherwise it stays None."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.requests = self.ok = self.failed = 0
        self.input_tokens = self.output_tokens = 0
        self.cost: Optional[float] = None
        self.models: Dict[str, int] = {}
        self.errors: List[str] = []

    def add_ok(self, usage: Dict[str, Any], model: Optional[str]) -> None:
        with self._lock:
            self.requests += 1
            self.ok += 1
            self.input_tokens += int(usage.get("input_tokens") or 0)
            self.output_tokens += int(usage.get("output_tokens") or 0)
            if isinstance(usage.get("cost"), (int, float)) and not isinstance(usage.get("cost"), bool):
                self.cost = (self.cost or 0.0) + float(usage["cost"])
            if model:
                self.models[model] = self.models.get(model, 0) + 1

    def add_failed(self, error: str) -> None:
        with self._lock:
            self.requests += 1
            self.failed += 1
            if error and error not in self.errors and len(self.errors) < 5:
                self.errors.append(error[:200])

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {"requests": self.requests, "ok": self.ok, "failed": self.failed,
                    "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                    "cost_usd": round(self.cost, 6) if self.cost is not None else None,
                    "models": dict(self.models), "errors": list(self.errors)}


# --------------------------------------------------------------------------
# Questions and answers
# --------------------------------------------------------------------------

def choice_question(criteria: Dict[str, str], instructions: Optional[str] = None) -> Dict[str, Any]:
    q: Dict[str, Any] = {"type": "choice", "criteria": {str(k): str(v) for k, v in criteria.items()}}
    if instructions:
        q["instructions"] = instructions
    return q


def score_question(levels: Sequence[str], instructions: Optional[str] = None) -> Dict[str, Any]:
    """levels: descriptions from the lowest (score 0) to the highest."""
    q: Dict[str, Any] = {"type": "score", "criteria": [str(x) for x in levels]}
    if instructions:
        q["instructions"] = instructions
    return q


def noul_question(instructions: str) -> Dict[str, Any]:
    return {"type": "noul", "instructions": instructions}


def score_pmf(answer: Any, levels: int) -> Optional[List[float]]:
    """A score answer's probabilities as a list over levels 0..levels-1 (normalised), or None when unusable."""
    probs = answer.get("probabilities") if isinstance(answer, dict) else None
    if not isinstance(probs, dict):
        return None
    out: List[float] = []
    for k in range(levels):
        v = probs.get(str(k), probs.get(k, 0.0))
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0:
            return None
        out.append(float(v))
    total = sum(out)
    if total <= 0:
        return None
    return [x / total for x in out]


def choice_label(answer: Any, allowed: Sequence[str]) -> Optional[str]:
    """The chosen label when it is one of `allowed`, else None."""
    c = answer.get("choice") if isinstance(answer, dict) else None
    return c if isinstance(c, str) and c in allowed else None


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

def _retry_after(resp: Any) -> Optional[float]:
    raw = (getattr(resp, "headers", None) or {}).get("Retry-After")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        pass
    try:
        return max(0.0, parsedate_to_datetime(str(raw)).timestamp() - time.time())
    except (TypeError, ValueError, IndexError):
        return None


def _error_text(resp: Any) -> str:
    status = getattr(resp, "status_code", "?")
    try:
        data = resp.json()
    except ValueError:
        data = None
    detail = ""
    if isinstance(data, dict):
        d = data.get("detail")
        if isinstance(d, list):          # 422 HTTPValidationError: [{loc, msg, type}]
            detail = "; ".join(f'{".".join(str(x) for x in (it.get("loc") or []))}: {it.get("msg")}'
                               for it in d if isinstance(it, dict))[:400]
        elif d:
            detail = str(d)[:400]
        else:
            err = data.get("error")
            detail = str(err.get("message") if isinstance(err, dict) else err or data.get("message") or "")[:400]
    if not detail:
        detail = str(getattr(resp, "text", "") or "")[:300]
    return f"Jev request failed: HTTP {status}" + (f": {detail}" if detail else "")


def _post(url: str, key: str, body: Dict[str, Any], timeout: float, retries: int) -> Dict[str, Any]:
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    last = ""
    for attempt in range(retries + 1):
        wait: Optional[float] = None
        try:
            resp = requests.post(url, json=body, headers=headers, timeout=timeout)
        except (requests.ConnectionError, requests.Timeout) as e:
            last = f"Jev request failed: {type(e).__name__}"
        else:
            if resp.status_code == 200:
                try:
                    data = resp.json()
                except ValueError:
                    raise JevError("Jev returned a response that is not JSON") from None
                if not isinstance(data, dict):
                    raise JevError("Jev returned an unexpected response")
                return data
            last = _error_text(resp)
            if resp.status_code not in RETRY_STATUS and resp.status_code < 500:
                raise JevError(last)
            wait = _retry_after(resp)
        if attempt == retries:
            break
        delay = min(MAX_WAIT_S, wait if wait is not None else 2.0 ** attempt)
        logger.info("jev: %s, retrying in %.1fs (%d/%d)", last, delay, attempt + 1, retries)
        _sleep(delay)
    raise JevError(f"{last} (after {retries + 1} attempts)")


def _state_for(route: Optional[str], state: Any) -> Any:
    # OpenRouter documents state as a list of items (text or images); TypeSafe takes a string, object or list
    return [state] if route == "openrouter" and isinstance(state, str) else state


def ask(state: Any, questions: Dict[str, Dict[str, Any]], model: Optional[str] = None,
        usage: Optional[JevUsage] = None, env: Optional[Dict[str, str]] = None,
        _resolved: Optional[Tuple[Dict[str, Any], str]] = None) -> Dict[str, Any]:
    """One request: {"model", "answers": {id: answer}, "usage": {...}}. Raises JevUnavailable without a key and
    JevError on failure (counted in `usage`). Every question must come back answered."""
    cfg, key = _resolved or _resolve(env)
    if not cfg["configured"]:
        raise JevUnavailable(f"Jev is not configured: {cfg['reason']}")
    if not isinstance(questions, dict) or not questions:
        raise ValueError("questions must be a non-empty {id: question} object")
    body = {"state": _state_for(cfg["route"], state), "model": model or cfg["model"], "questions": questions}
    try:
        data = _post(cfg["endpoint"], key, body, cfg["timeout"], cfg["retries"])
        answers = data.get("answers")
        missing = [q for q in questions if not isinstance(answers, dict) or not isinstance(answers.get(q), dict)]
        if missing:
            raise JevError(f"Jev returned no answer for {', '.join(missing[:5])}")
    except JevError as e:
        if usage is not None:
            usage.add_failed(str(e))
        raise
    u = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    used_model = str(data.get("model") or body["model"])
    if usage is not None:
        usage.add_ok(u, used_model)
    return {"model": used_model, "answers": answers,
            "usage": {k: u.get(k) for k in ("input_tokens", "output_tokens", "cost") if k in u}}


def ask_many(jobs: Sequence[Tuple[Any, Dict[str, Dict[str, Any]]]], parallel: Optional[int] = None,
             usage: Optional[JevUsage] = None, env: Optional[Dict[str, str]] = None,
             progress: Optional[Callable[[int, int], None]] = None) -> List[Dict[str, Any]]:
    """[(state, questions)] -> one {"ok", "model", "answers", "error"} per job, in order. Parallel requests are
    capped by `parallel` or JEV_PARALLEL. A failed job stays failed. Raises JevUnavailable without a key."""
    resolved = _resolve(env)
    cfg = resolved[0]
    if not cfg["configured"]:
        raise JevUnavailable(f"Jev is not configured: {cfg['reason']}")
    total = len(jobs)
    done = [0]
    lock = threading.Lock()

    def one(job: Tuple[Any, Dict[str, Dict[str, Any]]]) -> Dict[str, Any]:
        try:
            res = ask(job[0], job[1], usage=usage, _resolved=resolved)
            out = {"ok": True, "model": res["model"], "answers": res["answers"], "error": None}
        except (JevError, ValueError) as e:
            out = {"ok": False, "model": None, "answers": None, "error": str(e)[:300]}
        if progress:
            with lock:
                done[0] += 1
                progress(done[0], total)
        return out

    if not jobs:
        return []
    workers = max(1, min(int(parallel or cfg["parallel"]), total))
    if workers == 1:
        return [one(j) for j in jobs]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(one, jobs))
