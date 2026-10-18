"""
MarketMirror: brand posts and scheduled events inside the OASIS simulation.

simulation_config.json["event_config"] may carry
    initial_posts:    [{"poster_agent_id": 0, "content": "..."}]           (round 0, already supported upstream)
    scheduled_events: [{"round": 3, "poster_agent_id": 0, "content": "...", "platform": "twitter|reddit|both"}]

`inject_scheduled` turns the events of a round into ManualAction(CREATE_POST) entries so a launch can unfold
over time: teaser, launch day, price reveal, a competitor's reply. Injected posts go through the normal OASIS
step, so they land in the trace and are logged with their round like any other action.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional


def events_by_round(config: Dict[str, Any], platform: Optional[str] = None) -> Dict[int, List[Dict[str, Any]]]:
    """round -> events for this platform (events without a platform, or 'both', apply everywhere)."""
    out: Dict[int, List[Dict[str, Any]]] = {}
    for ev in ((config or {}).get("event_config") or {}).get("scheduled_events") or []:
        if not isinstance(ev, dict):
            continue
        try:
            rnd = int(ev.get("round"))
            agent = int(ev.get("poster_agent_id"))
        except (TypeError, ValueError):
            continue
        content = str(ev.get("content") or "").strip()
        if not content or rnd < 1:
            continue
        plat = str(ev.get("platform") or "both").lower()
        if platform and plat not in ("both", platform):
            continue
        out.setdefault(rnd, []).append({"round": rnd, "poster_agent_id": agent, "content": content, "platform": plat})
    return out


def inject_scheduled(actions: Dict[Any, Any], env: Any, round_num: int, by_round: Dict[int, List[Dict[str, Any]]],
                     manual_action_cls: Callable, action_type_cls: Any,
                     log: Callable[[str], None] = print) -> int:
    """Add this round's events to `actions` (agent -> ManualAction or list). Returns how many were added."""
    added = 0
    for ev in by_round.get(round_num, []):
        try:
            agent = env.agent_graph.get_agent(ev["poster_agent_id"])
        except Exception:  # noqa: BLE001 - unknown agent id: skip
            log(f"scheduled event skipped: no agent {ev['poster_agent_id']}")
            continue
        act = manual_action_cls(action_type=action_type_cls.CREATE_POST, action_args={"content": ev["content"]})
        existing = actions.get(agent)
        if existing is None or type(existing).__name__ == "LLMAction":
            actions[agent] = act
        elif isinstance(existing, list):
            existing.append(act)
        else:
            actions[agent] = [existing, act]
        added += 1
    if added:
        log(f"round {round_num}: injected {added} scheduled post(s)")
    return added


def resolve_agent(ref: Any, persona_index: List[Dict[str, Any]]) -> Optional[int]:
    """An agent id, or a persona/entity name (case-insensitive, exact or unique prefix) -> agent id."""
    if isinstance(ref, bool):
        return None
    if isinstance(ref, int):
        return ref
    s = str(ref or "").strip().lower()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    names = [(int(r["agent_id"]), str(r.get("name") or "").strip().lower()) for r in persona_index or []
             if isinstance(r, dict) and r.get("agent_id") is not None]
    exact = [aid for aid, n in names if n == s]
    if len(exact) == 1:
        return exact[0]
    prefix = [aid for aid, n in names if n.startswith(s)]
    return prefix[0] if len(prefix) == 1 else None


def normalize_events(config: Dict[str, Any], posts: Optional[List[Dict[str, Any]]],
                     events: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Validate user-supplied posts/events against persona_index; return the event_config fragments.
    Raises ValueError with a readable message."""
    index = (config or {}).get("persona_index") or []
    initial: List[Dict[str, Any]] = []
    for i, p in enumerate(posts or []):
        if not isinstance(p, dict) or not str(p.get("content") or "").strip():
            raise ValueError(f"posts[{i}] needs 'content'")
        aid = resolve_agent(p.get("agent", p.get("poster_agent_id", 0)), index)
        if aid is None:
            raise ValueError(f"posts[{i}]: unknown agent {p.get('agent')!r}")
        initial.append({"poster_agent_id": aid, "content": str(p["content"]).strip()[:2000],
                        "platform": str(p.get("platform") or "both").lower(), "poster_type": "brand"})
    scheduled: List[Dict[str, Any]] = []
    for i, e in enumerate(events or []):
        if not isinstance(e, dict) or not str(e.get("content") or "").strip():
            raise ValueError(f"events[{i}] needs 'content'")
        try:
            rnd = int(e.get("round"))
        except (TypeError, ValueError):
            raise ValueError(f"events[{i}] needs an integer 'round' (1 = first simulated round)")
        if rnd < 1:
            raise ValueError(f"events[{i}]: round must be >= 1 (use 'posts' for round 0)")
        aid = resolve_agent(e.get("agent", e.get("poster_agent_id", 0)), index)
        if aid is None:
            raise ValueError(f"events[{i}]: unknown agent {e.get('agent')!r}")
        scheduled.append({"round": rnd, "poster_agent_id": aid, "content": str(e["content"]).strip()[:2000],
                          "platform": str(e.get("platform") or "both").lower(), "label": str(e.get("label") or "")[:80]})
    return {"initial_posts": initial, "scheduled_events": scheduled}
