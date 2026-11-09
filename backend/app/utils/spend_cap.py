"""A hard dollar cap on model calls.

Two caps, both estimates from token usage and the price table below (US dollars per million tokens):

- a run cap: `arm(limit_usd)` writes a small ledger file (spend_cap.json in the uploads folder, or MM_SPEND_FILE).
  Every model call checks it first and adds its estimated cost after, under a file lock, so the server and the
  simulation subprocesses it starts count against the same cap. `market-test` arms it from `max_spend_usd` and
  disarms it when the run ends.
  A cap left behind by a run that was killed lapses after MM_SPEND_CAP_TTL_S (a day).
- a process cap: MM_MAX_SPEND_USD stops one process (the server, or one simulation subprocess) after that much.

Once a cap is reached, `check()` raises SpendCapReached before any request is sent, so no new model call starts;
steps that catch per-person errors finish at once and the run keeps what it already has. Prices are list prices
and can be overridden with MM_USD_PER_MTOK="input,output". Calls through a login gateway are counted at the same
prices, although they are not billed per token. Stdlib only.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
import time
from typing import Any, Callable, Dict, Iterator, Optional, Tuple

try:
    import fcntl
except ImportError:          # Windows: the thread lock still guards one process
    fcntl = None

# USD per million tokens (input, output), most specific pattern first; list prices, used as estimates
PRICES: Tuple[Tuple[str, Tuple[float, float]], ...] = (
    ("haiku-3-5", (0.8, 4.0)), ("haiku", (1.0, 5.0)),
    ("sonnet", (3.0, 15.0)),
    ("opus-4-1", (15.0, 75.0)), ("opus-4-0", (15.0, 75.0)), ("opus-4-2025", (15.0, 75.0)), ("opus", (5.0, 25.0)),
    ("gpt-5-nano", (0.05, 0.4)), ("gpt-5-mini", (0.25, 2.0)), ("gpt-5", (1.25, 10.0)),
    ("gpt-4.1-nano", (0.1, 0.4)), ("gpt-4.1-mini", (0.4, 1.6)), ("gpt-4.1", (2.0, 8.0)),
    ("gpt-4o-mini", (0.15, 0.6)), ("gpt-4o", (2.5, 10.0)),
    ("gemini-2.5-flash-lite", (0.1, 0.4)), ("flash", (0.3, 2.5)), ("gemini-2.5-pro", (1.25, 10.0)),
)
DEFAULT_PRICE = (3.0, 15.0)
CACHE_READ = 0.1             # cache reads cost a tenth of input; cache writes 1.25x
CACHE_WRITE = 1.25

_LOCK = threading.Lock()
_PROCESS = {"spent_usd": 0.0, "calls": 0}


class SpendCapReached(RuntimeError):
    """A spend cap is reached: no new model call is started."""
    no_retry = True


def _path() -> str:
    if os.environ.get("MM_SPEND_FILE"):
        return os.environ["MM_SPEND_FILE"]
    root = os.environ.get("MIROFISH_UPLOAD_DIR") or os.path.join(os.path.dirname(__file__), "..", "..", "uploads")
    return os.path.abspath(os.path.join(root, "spend_cap.json"))


def price_for(model: Optional[str]) -> Tuple[Tuple[float, float], str]:
    """(input, output) USD per million tokens and where the price came from."""
    override = (os.environ.get("MM_USD_PER_MTOK") or "").strip()
    if override:
        try:
            i, o = (float(x) for x in override.split(",", 1))
            return (i, o), "MM_USD_PER_MTOK"
        except ValueError:
            pass
    name = str(model or "").lower()
    for pattern, price in PRICES:
        if pattern in name:
            return price, f"list price ({pattern})"
    return DEFAULT_PRICE, "default (unknown model)"


def cost_usd(model: Optional[str], input_tokens: int, output_tokens: int, cache_read: int = 0, cache_write: int = 0) -> float:
    """Estimated cost of one call. `input_tokens` counts cached and uncached input, as OpenAI-shaped usage does."""
    (pin, pout), _ = price_for(model)
    plain = max(0, int(input_tokens) - int(cache_read) - int(cache_write))
    return (plain * pin + cache_read * pin * CACHE_READ + cache_write * pin * CACHE_WRITE + int(output_tokens) * pout) / 1e6


def _usage_tokens(response: Any) -> Tuple[int, int, int, int]:
    u = getattr(response, "usage", None)
    if u is None and isinstance(response, dict):
        u = response.get("usage")
    get = (lambda k: (u.get(k) if isinstance(u, dict) else getattr(u, k, None)) or 0) if u is not None else (lambda k: 0)
    details = get("prompt_tokens_details")
    cached = (details.get("cached_tokens") if isinstance(details, dict) else getattr(details, "cached_tokens", 0)) if details else 0
    read = int(get("cache_read_input_tokens") or cached or 0)
    return int(get("prompt_tokens") or 0), int(get("completion_tokens") or 0), read, int(get("cache_creation_input_tokens") or 0)


def _process_limit() -> Optional[float]:
    try:
        v = float(os.environ.get("MM_MAX_SPEND_USD") or 0)
    except ValueError:
        return None
    return v if v > 0 else None


@contextlib.contextmanager
def _ledger(create: bool = False) -> Iterator[Tuple[Any, Optional[Callable[[Optional[Dict[str, Any]]], None]]]]:
    """The run ledger under an exclusive lock: yields (state, write); (None, None) when there is no file."""
    path = _path()
    with _LOCK:
        if not create and not os.path.exists(path):
            yield None, None
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a+", encoding="utf-8") as f:
            if fcntl:
                fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.seek(0)
                try:
                    state = json.loads(f.read() or "null")
                except ValueError:
                    state = None

                def write(new_state: Optional[Dict[str, Any]]) -> None:
                    f.seek(0)
                    f.truncate()
                    if new_state is not None:
                        f.write(json.dumps(new_state))
                    f.flush()
                yield state, write
            finally:
                if fcntl:
                    fcntl.flock(f, fcntl.LOCK_UN)


TTL_S = float(os.environ.get("MM_SPEND_CAP_TTL_S") or 24 * 3600)   # a cap left by a killed run lapses after a day


def _armed(state: Any) -> bool:
    return (isinstance(state, dict) and bool(state.get("limit_usd"))
            and time.time() < float(state.get("armed_at") or 0) + TTL_S)


def arm(limit_usd: float, label: str = "") -> Dict[str, Any]:
    """Start a run cap of `limit_usd` (replaces any earlier one)."""
    try:
        limit = float(limit_usd)
    except (TypeError, ValueError):
        limit = 0.0
    if not limit > 0:
        raise ValueError("max_spend_usd must be a positive number of US dollars")
    state = {"limit_usd": round(limit, 4), "spent_usd": 0.0, "calls": 0, "input_tokens": 0, "output_tokens": 0,
             "reached": False, "label": str(label or "")[:120], "armed_at": time.time(), "estimate": True}
    with _ledger(create=True) as (_, write):
        write(state)
    return state


def status() -> Optional[Dict[str, Any]]:
    """The run cap and what has been spent against it, or None when no cap is armed."""
    with _ledger() as (state, _):
        return state if _armed(state) else None


def disarm() -> Optional[Dict[str, Any]]:
    """End the run cap; returns its final state."""
    with _ledger() as (state, write):
        if write is None:
            return None
        write(None)
    try:
        os.remove(_path())
    except OSError:
        pass
    return state if _armed(state) else None


def _usd(x: float) -> str:
    return f"${x:.2f}" if x >= 1 else f"${x:.4f}"


def check() -> None:
    """Raise SpendCapReached when a cap is reached. Costs one stat() when no run cap is armed."""
    limit = _process_limit()
    if limit is not None and _PROCESS["spent_usd"] >= limit:
        raise SpendCapReached(f"spend cap reached: about {_usd(_PROCESS['spent_usd'])} of the {_usd(limit)} "
                              "allowed for this process (MM_MAX_SPEND_USD)")
    if not os.path.exists(_path()):
        return
    st = status()
    if st and (st.get("reached") or float(st.get("spent_usd") or 0) >= float(st["limit_usd"])):
        raise SpendCapReached(f"spend cap reached: about {_usd(float(st['spent_usd']))} of the {_usd(float(st['limit_usd']))} "
                              "allowed for this run (max_spend_usd)")


def charge_tokens(model: Optional[str], input_tokens: int, output_tokens: int, cache_read: int = 0, cache_write: int = 0) -> float:
    """Add one finished call to the process total and to the armed run cap; returns its estimated cost."""
    usd = cost_usd(model, input_tokens, output_tokens, cache_read, cache_write)
    with _LOCK:
        _PROCESS["spent_usd"] += usd
        _PROCESS["calls"] += 1
    if not os.path.exists(_path()):
        return usd
    with _ledger() as (state, write):
        if _armed(state):
            state["spent_usd"] = round(float(state.get("spent_usd") or 0) + usd, 6)
            state["calls"] = int(state.get("calls") or 0) + 1
            state["input_tokens"] = int(state.get("input_tokens") or 0) + int(input_tokens)
            state["output_tokens"] = int(state.get("output_tokens") or 0) + int(output_tokens)
            if state["spent_usd"] >= float(state["limit_usd"]) and not state.get("reached"):
                state["reached"], state["reached_at"] = True, time.time()
            write(state)
    return usd


def charge(response: Any, model: Optional[str] = None) -> float:
    """Charge an OpenAI-shaped response by its usage (no usage: nothing is charged)."""
    inp, out, read, write = _usage_tokens(response)
    if not (inp or out):
        return 0.0
    return charge_tokens(model or getattr(response, "model", None), inp, out, read, write)


def process_spent() -> Dict[str, Any]:
    return dict(_PROCESS)
