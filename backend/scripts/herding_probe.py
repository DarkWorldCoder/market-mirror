"""
MarketMirror: a randomized herding probe inside the social rounds (Muchnik, Aral and Taylor, Science 2013; replicated
with LLM agents in Yang et al., OASIS, arXiv 2411.11581).

Off unless simulation_config.json carries  "herding_probe": {"share": 0.5, "seed": 7}  (true = the defaults).

The observational herding check in app/services/feed_story.py cannot tell "people followed the score" from "who was
online when". This probe randomizes the early score instead:

  * One neutral account that no model drives is appended to the copy of the profiles the runner loads. The on-disk
    profile files, persona_index and agent_configs are left alone, so it is never a persona, a community, a brand
    account, an interviewee or a survey respondent, and get_active_agents_for_round (which walks agent_configs)
    never picks it. `inject` also drops any action other than the probe's own votes.
  * After round r, the organic posts created in round r (persona posts; never reposts, quotes, brand posts, scheduled
    events or community accounts) are randomized: a seeded `share` of them get one vote from the probe in the next
    round that runs (up = a like; down = a dislike, Reddit only, since the X-like platform has no dislike), the rest
    are controls. Posts from the last round are not enrolled. The votes go first in that round's step, so the people
    active that round already see them.
  * <sim>/herding_probe.json logs every batch: the posts and their arms, the database high-water marks at
    assignment (so later reactions are those with a higher id), the round the votes went out in and whether each
    landed. feed_story.probe_check scores it.

The probe's own votes are kept out of actions.jsonl (and so out of the activity view and graph memory) and out of
every count of what people did.
"""

from __future__ import annotations

import csv
import json
import os
import random
import sqlite3
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

LOG_FILE = "herding_probe.json"
DEFAULT_SHARE = 0.5
PROBE_USERNAME = "mm_quiet_reader"
PROBE_NAME = "Quiet Reader"
PROBE_BIO = "Reads a lot, rarely posts."
ARMS = {"twitter": ("up",), "reddit": ("up", "down")}


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

def normalize(value: Any, default_seed: int = 7) -> Optional[Dict[str, Any]]:
    """A user value -> {"share", "seed"} or None (off). Accepts true, a share (0 < share < 1), or {share?, seed?,
    enabled?}. Raises ValueError for a share outside (0, 1) or a non-integer seed."""
    if value is None or value is False:
        return None
    if value is True:
        value = {}
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if value == 0:
            return None
        value = {"share": value}
    if not isinstance(value, dict):
        raise ValueError("herding_probe must be true, a share between 0 and 1, or {share, seed}")
    if value.get("enabled") is False:
        return None
    try:
        share = float(value.get("share", DEFAULT_SHARE))
    except (TypeError, ValueError):
        raise ValueError("herding_probe.share must be a number between 0 and 1")
    if share == 0:
        return None
    if not 0 < share < 1:
        raise ValueError("herding_probe.share must be between 0 and 1 (the rest of the posts are the controls)")
    seed = value.get("seed", default_seed)
    if isinstance(seed, bool):
        raise ValueError("herding_probe.seed must be an integer")
    try:
        seed = int(seed)
    except (TypeError, ValueError):
        raise ValueError("herding_probe.seed must be an integer")
    return {"share": round(share, 4), "seed": seed}


def settings(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The probe settings in simulation_config.json, or None when it is off (or malformed)."""
    config = config or {}
    try:
        return normalize(config.get("herding_probe"), int(config.get("seed") or 7))
    except (ValueError, TypeError):
        return None


def reset_log(sim_dir: str) -> None:
    """Remove a log left by an earlier run, so a probe-off run never shows an old probe."""
    try:
        os.remove(os.path.join(sim_dir, LOG_FILE))
    except OSError:
        pass


# --------------------------------------------------------------------------
# The probe account
# --------------------------------------------------------------------------

def profiles_with_probe(config: Dict[str, Any], platform: str, profile_path: str) -> Tuple[str, Optional[int]]:
    """(profile file to load, probe agent id). With the probe off: (profile_path, None). With it on: a copy of the
    profile file next to it with the probe appended as the last row (its agent id is that row's index)."""
    if settings(config) is None or not os.path.exists(profile_path):
        return profile_path, None
    folder, name = os.path.split(profile_path)
    copy = os.path.join(folder, f".probe_{name}")
    if platform == "twitter":
        with open(profile_path, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        if not rows:
            return profile_path, None
        header, body = rows[0], rows[1:]
        probe_id = len(body)
        values = {"user_id": probe_id, "agent_id": probe_id, "name": PROBE_NAME, "username": PROBE_USERNAME,
                  "user_char": PROBE_BIO, "description": PROBE_BIO, "following_agentid_list": "[]",
                  "previous_tweets": "[]"}
        body.append([str(values.get(h, "")) for h in header])
        with open(copy, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows([header] + body)
    else:
        with open(profile_path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list) or not data:
            return profile_path, None
        probe_id = len(data)
        template = data[0] if isinstance(data[0], dict) else {}
        item = {k: ("" if isinstance(v, str) else v) for k, v in template.items()
                if k in ("created_at", "karma", "age", "mbti")}
        item.update({"user_id": probe_id, "username": PROBE_USERNAME, "name": PROBE_NAME, "realname": PROBE_NAME,
                     "bio": PROBE_BIO, "persona": PROBE_BIO, "karma": 1, "age": 30, "gender": "other",
                     "mbti": template.get("mbti") or "ISTJ", "country": template.get("country") or ""})
        with open(copy, "w", encoding="utf-8") as f:
            json.dump(data + [item], f, ensure_ascii=False, indent=2)
    return copy, probe_id


def discard_copy(path: str, original: str) -> None:
    if path and path != original:
        try:
            os.remove(path)
        except OSError:
            pass


def find_probe(agent_graph: Any, expected: Optional[int]) -> Optional[int]:
    """The probe's agent id in a loaded graph: `expected` when that agent has the probe's user name, else a scan."""
    def uname(agent: Any) -> str:
        info = getattr(agent, "user_info", None)
        return str(getattr(info, "name", "") or getattr(info, "user_name", "") or "")
    if expected is None:
        return None
    try:
        if uname(agent_graph.get_agent(expected)) == PROBE_USERNAME:
            return expected
    except Exception:  # noqa: BLE001 - fall through to the scan
        pass
    try:
        for item in agent_graph.get_agents():
            aid, agent = item if isinstance(item, tuple) else (getattr(item, "social_agent_id", None), item)
            if uname(agent) == PROBE_USERNAME:
                return int(aid)
    except Exception:  # noqa: BLE001
        pass
    return expected


# --------------------------------------------------------------------------
# Assignment
# --------------------------------------------------------------------------

def assign(post_ids: Iterable[int], share: float, seed: int, platform: str, round_num: int) -> Dict[int, str]:
    """post id -> 'up' | 'down' | 'control'. Complete randomization within the round: the posts are shuffled with a
    seeded generator, round(share * n) of them (rounded at random, so the expected share is exact) get a vote, and the
    voted ones alternate between the platform's arms from a random start."""
    ids = sorted({int(p) for p in post_ids})
    rng = random.Random(f"{seed}:{platform}:{round_num}:herding-probe")
    rng.shuffle(ids)
    n_treat = min(len(ids), int(share * len(ids) + rng.random()))
    arms = ARMS.get(platform, ("up",))
    start = rng.randrange(len(arms))
    return {pid: (arms[(start + i) % len(arms)] if i < n_treat else "control") for i, pid in enumerate(ids)}


def _norm(text: Any) -> str:
    return " ".join(str(text or "").split()).strip().lower()


def brand_contents(config: Dict[str, Any], platform: str) -> Set[str]:
    """Normalized texts of the brand's injected posts on this platform (scheduled events and brand initial posts)."""
    ev = (config or {}).get("event_config") or {}
    kinds = _kinds(config)
    out: Set[str] = set()
    for source, rows in (("initial", ev.get("initial_posts")), ("scheduled", ev.get("scheduled_events"))):
        for r in rows or []:
            if not isinstance(r, dict) or not r.get("content"):
                continue
            plat = str(r.get("platform") or "both").lower()
            if plat not in ("both", "all", platform):
                continue
            agent = r.get("poster_agent_id")
            brand = source == "scheduled" or str(r.get("poster_type") or "").lower() == "brand" \
                or kinds.get(_int(agent)) in ("graph", "community")
            if brand:
                out.add(_norm(r["content"]))
    return out


def _kinds(config: Dict[str, Any]) -> Dict[int, str]:
    out: Dict[int, str] = {}
    for r in (config or {}).get("persona_index") or []:
        if isinstance(r, dict) and r.get("agent_id") is not None:
            aid = _int(r["agent_id"])
            if aid is not None:
                out[aid] = str(r.get("kind") or "")
    return out


def _int(v: Any) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# Database (read-only, between steps)
# --------------------------------------------------------------------------

def _connect(db_path: str) -> Optional[sqlite3.Connection]:
    if not os.path.exists(db_path):
        return None
    try:
        return sqlite3.connect("file:" + os.path.abspath(db_path).replace("?", "%3F").replace("#", "%23") + "?mode=ro",
                               uri=True)
    except sqlite3.Error:
        return None


def _max(conn: sqlite3.Connection, table: str, col: str) -> int:
    try:
        row = conn.execute(f'SELECT MAX("{col}") FROM "{table}"').fetchone()
    except sqlite3.Error:
        return 0
    return int(row[0]) if row and row[0] is not None else 0


def marks(conn: sqlite3.Connection) -> Dict[str, int]:
    """The highest id in each table right now: anything later has a higher id."""
    return {"post": _max(conn, "post", "post_id"), "like": _max(conn, "like", "like_id"),
            "dislike": _max(conn, "dislike", "dislike_id"), "comment": _max(conn, "comment", "comment_id")}


def _rows(conn: sqlite3.Connection, sql: str, args: Tuple = ()) -> List[Dict[str, Any]]:
    try:
        cur = conn.execute(sql, args)
    except sqlite3.Error:
        return []
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _user_agents(conn: sqlite3.Connection) -> Dict[Any, int]:
    out: Dict[Any, int] = {}
    for u in _rows(conn, 'SELECT * FROM "user"'):
        aid = u.get("agent_id") if u.get("agent_id") is not None else u.get("user_id")
        if _int(aid) is not None:
            out[u.get("user_id")] = int(aid)
    return out


# --------------------------------------------------------------------------
# The probe during a run
# --------------------------------------------------------------------------

class HerdingProbe:
    """One platform's probe. Call `after_step(round, has_next)` after every env.step (round 0 included),
    `inject(...)` right before every env.step, and `drop_own(...)` on the actions read back from the trace."""

    def __init__(self, config: Dict[str, Any], platform: str, sim_dir: str, db_path: str, probe_agent_id: int,
                 log: Callable[[str], None] = print):
        s = settings(config) or {"share": DEFAULT_SHARE, "seed": int((config or {}).get("seed") or 7)}
        self.share, self.seed = s["share"], s["seed"]
        self.platform = platform
        self.sim_dir = sim_dir
        self.db_path = db_path
        self.probe_agent_id = int(probe_agent_id)
        self.probe_user_id: Optional[int] = None
        self.log = log
        self.kinds = _kinds(config)
        self.has_personas = any(k == "persona" for k in self.kinds.values())
        self.brand = brand_contents(config, platform)
        self.batches: List[Dict[str, Any]] = []
        self.pending: List[Dict[str, Any]] = []
        self.sent: List[Dict[str, Any]] = []
        self.post_mark = 0
        self.save()

    @classmethod
    def start(cls, config: Dict[str, Any], platform: str, sim_dir: str, db_path: str, agent_graph: Any,
              expected_id: Optional[int], log: Callable[[str], None] = print) -> Optional["HerdingProbe"]:
        """The probe for this platform, or None when it is off or its account did not load."""
        if settings(config) is None or expected_id is None:
            return None
        pid = find_probe(agent_graph, expected_id)
        if pid is None:
            log("herding probe: the probe account did not load; probe off")
            return None
        probe = cls(config, platform, sim_dir, db_path, pid, log)
        log(f"herding probe on: agent {pid}, share {probe.share}, seed {probe.seed}")
        return probe

    # -- who may be enrolled --------------------------------------------------
    def organic_author(self, agent_id: Optional[int]) -> bool:
        if agent_id is None or agent_id == self.probe_agent_id:
            return False
        kind = self.kinds.get(agent_id, "")
        if self.has_personas:
            return kind == "persona"
        return kind != "community"          # a run without personas: every account but the community ones

    # -- after each step ------------------------------------------------------
    def after_step(self, round_num: int, has_next: bool) -> int:
        """Confirm the votes sent this round, then enrol the posts created in it. Returns how many got a vote."""
        conn = _connect(self.db_path)
        if conn is None:
            return 0
        try:
            users = _user_agents(conn)
            if self.probe_user_id is None:
                self.probe_user_id = next((u for u, a in users.items() if a == self.probe_agent_id), self.probe_agent_id)
            if self.sent:
                self._confirm(conn)
            m = marks(conn)
            new = _rows(conn, 'SELECT * FROM "post" WHERE post_id > ? ORDER BY post_id', (self.post_mark,))
        finally:
            conn.close()
        self.post_mark = max(self.post_mark, m["post"])
        if not has_next:
            self.save()
            return 0
        eligible = []
        for p in new:
            if p.get("original_post_id") is not None:
                continue                                        # reposts and quotes are reactions, not posts
            aid = users.get(p.get("user_id"), _int(p.get("user_id")))
            if not self.organic_author(aid) or _norm(p.get("content")) in self.brand:
                continue
            eligible.append((int(p["post_id"]), aid))
        if not eligible:
            self.save()
            return 0
        arms = assign([pid for pid, _ in eligible], self.share, self.seed, self.platform, round_num)
        batch = {"round": round_num, "marks": m, "vote_round": None,
                 "posts": [{"post_id": pid, "author_agent_id": aid, "arm": arms[pid]} for pid, aid in eligible]}
        self.batches.append(batch)
        self.pending.append(batch)
        self.save()
        voted = sum(1 for p in batch["posts"] if p["arm"] != "control")
        self.log(f"herding probe: round {round_num}: {len(eligible)} posts enrolled, {voted} get a vote next round")
        return voted

    def _confirm(self, conn: sqlite3.Connection) -> None:
        uid = self.probe_user_id
        liked = {int(r["post_id"]) for r in _rows(conn, 'SELECT post_id FROM "like" WHERE user_id = ?', (uid,))}
        disliked = {int(r["post_id"]) for r in _rows(conn, 'SELECT post_id FROM "dislike" WHERE user_id = ?', (uid,))}
        for b in self.sent:
            for p in b["posts"]:
                if p["arm"] == "up":
                    p["delivered"] = p["post_id"] in liked
                elif p["arm"] == "down":
                    p["delivered"] = p["post_id"] in disliked
        self.sent = []

    # -- before each step -----------------------------------------------------
    def inject(self, actions: Dict[Any, Any], env: Any, round_num: int, manual_action_cls: Callable,
               action_type_cls: Any) -> Dict[Any, Any]:
        """`actions` with the pending votes first (the probe's ManualActions) and nothing else for the probe."""
        try:
            probe_agent = env.agent_graph.get_agent(self.probe_agent_id)
        except Exception:  # noqa: BLE001
            probe_agent = None
        votes = []
        for b in self.pending:
            for p in b["posts"]:
                if p["arm"] == "up":
                    votes.append(manual_action_cls(action_type=action_type_cls.LIKE_POST, action_args={"post_id": p["post_id"]}))
                elif p["arm"] == "down":
                    votes.append(manual_action_cls(action_type=action_type_cls.DISLIKE_POST,
                                                   action_args={"post_id": p["post_id"]}))
            b["vote_round"] = round_num
        out: Dict[Any, Any] = {}
        if probe_agent is not None and votes:
            out[probe_agent] = votes
        dropped = 0
        for agent, act in actions.items():
            if agent is probe_agent or getattr(agent, "social_agent_id", None) == self.probe_agent_id:
                dropped += 1                                     # never a model-driven (or any other) action
                continue
            out[agent] = act
        if dropped:
            self.log(f"herding probe: round {round_num}: removed {dropped} action(s) given to the probe account")
        if votes:
            self.log(f"herding probe: round {round_num}: {len(votes)} probe vote(s)")
        self.sent += self.pending
        self.pending = []
        self.save()
        return out

    def drop_own(self, actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """The trace rows without the probe's: its votes are logged in herding_probe.json, not as people's activity."""
        own = {self.probe_agent_id, self.probe_user_id}
        return [a for a in actions if a.get("agent_id") not in own]

    # -- log ----------------------------------------------------------------
    def snapshot(self) -> Dict[str, Any]:
        return {"probe_agent_id": self.probe_agent_id, "probe_user_id": self.probe_user_id,
                "share": self.share, "seed": self.seed, "arms": list(ARMS.get(self.platform, ("up",))) + ["control"],
                "batches": self.batches}

    def save(self) -> None:
        """Merge this platform's section into <sim>/herding_probe.json (both platforms share the file)."""
        path = os.path.join(self.sim_dir, LOG_FILE)
        data: Dict[str, Any] = {}
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        data.update({"version": 1, "method": "randomized early vote from a neutral account (Muchnik et al. 2013)"})
        data.setdefault("platforms", {})[self.platform] = self.snapshot()
        tmp = path + f".{self.platform}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except OSError as e:
            self.log(f"herding probe: could not write {LOG_FILE}: {e}")
