"""
quota.py - pause on usage limits and resume. When the local login gateway (backend/gateway/local_gateway.py)
hits a Claude Code / Codex usage limit it pauses until the reset and says so on /health. Pipelines call
``guarded(step, fn)``: wait while the gateway is paused, run the step, and if a limit was hit during the step,
wait for the reset and run that step again, so a half-failed step never becomes a result. Stdlib only.

The gateway is found from MM_GATEWAY_URL, else from LLM_BASE_URL (environment or the repository .env) when
it points at the local gateway. Without a gateway every function is a no-op.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from typing import Any, Callable, Dict, List, Optional

MAX_WAIT_S = 12 * 3600
GATEWAY_PORTS = (":5055",)
_ENV = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env")


def _env_value(key: str) -> str:
    if os.environ.get(key):
        return os.environ[key]
    try:
        # MIROFISH_ENV_FILE: the settings file of this backend instance (several can run side by side)
        with open(os.environ.get("MIROFISH_ENV_FILE") or _ENV, encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith(key + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def _is_local_gateway(base: str) -> bool:
    """LLM_BASE_URL is a local login gateway: the default port, or any loopback URL when LLM_GATEWAY names one."""
    from urllib.parse import urlparse
    if any(p in base for p in GATEWAY_PORTS):
        return True
    try:
        host = (urlparse(base).hostname or "").lower()
    except ValueError:
        return False
    return host in ("127.0.0.1", "localhost") and bool(_env_value("LLM_GATEWAY"))


def gateway_url() -> Optional[str]:
    url = os.environ.get("MM_GATEWAY_URL") or ""
    if not url:
        base = _env_value("LLM_BASE_URL")
        if _is_local_gateway(base):
            url = base.split("/v1")[0]
    return url.rstrip("/") or None


# the gateways of a provider pool (LLM_POOL): each person may be answered through any of them
POOL_GATEWAY_KEYS = ("CLAUDE_CODE_GATEWAY_URL", "CODEX_GATEWAY_URL", "ANTIGRAVITY_GATEWAY_URL", "GEMINI_CLI_GATEWAY_URL")


def gateway_urls() -> List[str]:
    """Every local gateway this run uses: the main one and those of the provider pool."""
    urls = [gateway_url()] + [_env_value(k).split("/v1")[0].rstrip("/") for k in POOL_GATEWAY_KEYS]
    return list(dict.fromkeys(u for u in urls if u))


def _one_status(url: str) -> Optional[Dict[str, Any]]:
    try:
        with urllib.request.urlopen(url + "/health", timeout=5) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - gateway down: nothing to wait for here
        return None


def status(url: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """One gateway's /health, or with no url all of this run's gateways together: paused while any of them is paused
    (for less than MAX_WAIT_S; a provider paused for longer is left out, its calls fail and are counted), the latest
    reset, and the limit hits added up."""
    if url:
        return _one_status(url)
    urls = gateway_urls()
    if not urls:
        return None
    states = [(u, _one_status(u)) for u in urls]
    states = [(u, st) for u, st in states if st]
    if not states:
        return None
    waiting = [(u, st) for u, st in states if st.get("paused") and 0 < int(st.get("resume_in_s") or 0) <= MAX_WAIT_S]
    out: Dict[str, Any] = {"limit_hits": sum(int(st.get("limit_hits") or 0) for _, st in states),
                           "paused": bool(waiting), "gateways": [u for u, _ in states]}
    if waiting:
        u, st = max(waiting, key=lambda x: int(x[1].get("resume_in_s") or 0))
        out.update(resume_in_s=int(st.get("resume_in_s") or 0), paused_until=f"{st.get('paused_until')} ({u})")
    return out


def limit_hits(url: Optional[str] = None) -> int:
    return int((status(url) or {}).get("limit_hits") or 0)


def any_gateway() -> bool:
    return bool(gateway_urls())


def wait_if_paused(log: Callable[[str], None], url: Optional[str] = None, sleep: Callable[[float], None] = time.sleep,
                   max_wait_s: float = MAX_WAIT_S) -> float:
    """Block while the gateway is paused for a usage limit; returns the seconds waited."""
    waited = 0.0
    announced = False
    while waited < max_wait_s:
        st = status(url)
        left = int((st or {}).get("resume_in_s") or 0) if (st or {}).get("paused") else 0
        if left <= 0:
            if announced:
                log("usage limit: reset reached, resuming")
            return waited
        if not announced:
            log(f"usage limit: the model account is paused until {st.get('paused_until')} "
                f"({left // 3600}h {left % 3600 // 60}m); waiting, then resuming where the run stopped")
            announced = True
        step = min(left + 5, 300)
        sleep(step)
        waited += step
    raise RuntimeError(f"usage limit: still paused after {int(max_wait_s // 3600)} hours")


def guarded(name: str, fn: Callable[[], Any], log: Callable[[str], None], retries: int = 4,
            url: Optional[str] = None, sleep: Callable[[float], None] = time.sleep) -> Any:
    """Run one pipeline step so that a usage limit pauses and redoes it instead of failing or half-finishing it."""
    if not url and not any_gateway():
        return fn()
    for attempt in range(retries + 1):
        wait_if_paused(log, url, sleep)
        before = limit_hits(url)
        try:
            result = fn()
        except Exception:
            if limit_hits(url) > before and attempt < retries:
                log(f"usage limit hit during {name}; it will run again after the reset")
                continue
            raise
        if limit_hits(url) > before and attempt < retries:
            log(f"usage limit hit during {name}; its answers may be incomplete, so it will run again after the reset")
            continue
        return result
    return result
