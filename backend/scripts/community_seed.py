"""
Claude edition: seed the community follow graph before round 1.

`simulation_config.json` may carry `community_config.follows` ([[follower, followee], ...]),
built by app/services/persona_planner.py. Following fellow members and the group account
makes each agent's feed mostly in-group, which is how communities separate people.
"""

import os
import sqlite3
from typing import Any, Callable, Dict, List


def follow_plan(config: Dict[str, Any]) -> Dict[int, List[int]]:
    follows = ((config or {}).get("community_config") or {}).get("follows") or []
    plan: Dict[int, List[int]] = {}
    for pair in follows:
        try:
            a, b = int(pair[0]), int(pair[1])
        except (TypeError, ValueError, IndexError):
            continue
        if a != b:
            plan.setdefault(a, []).append(b)
    return plan


async def seed_community_follows(env, config: Dict[str, Any], manual_action_cls, action_type_cls,
                                 log: Callable[[str], None] = print) -> int:
    """Run one env step in which every member follows their community peers. Returns follow count."""
    plan = follow_plan(config)
    if not plan:
        return 0
    actions = {}
    count = 0
    for agent_id, targets in plan.items():
        try:
            agent = env.agent_graph.get_agent(agent_id)
        except Exception:  # noqa: BLE001 - unknown id: skip
            continue
        acts = [manual_action_cls(action_type=action_type_cls.FOLLOW, action_args={"followee_id": t})
                for t in targets]
        actions[agent] = acts if len(acts) > 1 else acts[0]
        count += len(acts)
    if actions:
        await env.step(actions)
        log(f"seeded {count} community follows for {len(actions)} agents")
    return count


def max_trace_rowid(db_path: str) -> int:
    """Highest trace rowid, so setup follows are not reported as round-1 activity."""
    if not os.path.exists(db_path):
        return 0
    try:
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute("SELECT MAX(rowid) FROM trace").fetchone()
            return int(row[0] or 0)
        finally:
            conn.close()
    except sqlite3.Error:
        return 0


def start_offset_minutes(config: Dict[str, Any], total_rounds: int) -> int:
    """Simulated clock start. time_config.start_hour wins; otherwise a run shorter than a day starts at
    the first peak hour, so short test runs are not spent entirely in the middle of the night."""
    tc = (config or {}).get("time_config") or {}
    if tc.get("start_hour") is not None:
        try:
            return (int(tc["start_hour"]) % 24) * 60
        except (TypeError, ValueError):
            return 0
    minutes = int(tc.get("minutes_per_round") or 60)
    if total_rounds * minutes >= 24 * 60:
        return 0
    peaks = sorted(int(h) for h in (tc.get("peak_hours") or [19, 20, 21, 22]) if str(h).lstrip("-").isdigit())
    if not peaks:
        return 19 * 60
    span_h = max(1, (total_rounds * minutes) // 60)
    # start early enough that the run ends inside the evening peak when it is long enough to reach it
    return max(0, (peaks[0] - max(0, span_h - len(peaks)))) % 24 * 60
