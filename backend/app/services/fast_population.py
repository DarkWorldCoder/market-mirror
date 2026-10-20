"""
fast_population.py - write large simulated populations quickly.

Where the time goes when people are written one deep profile at a time: a 5-person persona call, a 12-question life
interview and a follow-up call cost about 3,500 generated tokens per person, and every call through a login CLI also
re-sends 20-30k tokens of that CLI's own prompt. Generation speed (30-90 tokens/s per stream) makes that hours for a
few thousand people. This module cuts both:

1. Tiered depth. Everyone gets a compact card (about 200 tokens): the profile fields plus a short decision card
   (who they ask, speed, risk, deal-breakers, trust cues, spare money). The persona text is assembled from those
   fields in code. Only a stratified sample (by segment and provider) gets the full life interview and follow-ups.
2. Big batches with partial salvage. Up to CARD_BATCH people per call; each row names its slot number, and slots
   whose rows are missing or unusable are asked again on their own. Nobody is filled in by code.
3. One lane per provider. Each provider slot has its own workers and an adaptive limit (halved after a timeout,
   rate limit or server error, raised again after a run of successes), so a slow provider never holds up a fast one.
4. An exact-prompt cache. A card answer is stored under a hash of the prompt, provider and model, so a rerun or a
   restart after a crash reuses everything already written.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ..utils.logger import get_logger
from ..utils.openai_chat_compat import create_chat_completion, extract_chat_completion_text

logger = get_logger('mirofish.fast_population')

PROMPT_VERSION = "card-v1"
CARD_BATCH = max(1, int(os.environ.get("MM_CARD_BATCH") or 20))
CARD_ATTEMPTS = 3

CARD_SYSTEM = (
    "You write realistic synthetic people for a market simulation. Every person is fictional: use common, culturally "
    "plausible names and never a real or public person. Keep every field short and concrete. Include sceptics, the "
    "indifferent and the busy as well as enthusiasts. Return only valid JSON."
)

# short keys keep the output small; expand_card maps them to the planner's field names
CARD_SCHEMA = (
    '{"i": slot number, "name": "...", "city": "...", "occ": "occupation", "hh": "household, few words", '
    '"lang": ["..."], "plat": "where and how they scroll, few words", "role": "their part in buying decisions", '
    '"att": "attitude to the topic, max 15 words", "con": ["max 3 short concerns"], '
    '"why": "what persuades them, max 12 words", "contra": "one believable contradiction, max 15 words", '
    '"voice": "how they write online, max 12 words", "post": "a typical post, max 25 words", '
    '"topics": ["max 4"], "bio": "max 12 words", "knows": "what they know about this category, max 12 words", '
    '"ask": "who they ask before buying", "spd": "impulsive|considered|slow", "risk": "averse|neutral|seeking", '
    '"deal": ["1-2 deal-breakers"], "trust": ["1-2 trust cues"], "spare": "monthly spare money, local currency", '
    '"svd": "where their words and actions differ, max 15 words"}'
)


def card_prompt(seg: Any, slots: List[Dict[str, Any]], numbers: Sequence[int], requirement: str, context: str,
                communities: Sequence[Any] = ()) -> str:
    """The card request for these slots; `numbers` are the slot numbers the rows must carry back."""
    people = "\n".join(
        f"{n}. age {s['age']}, {s['gender']}" + (f", {s['city']}" if s.get("city") else "")
        + (f" ({s['settlement']})" if s.get("settlement") else "") + f", MBTI {s['mbti']}"
        + (f", name starts with '{s['initial']}'" if s.get("initial") else "")
        + "".join(f"; {k.replace('_', ' ')}: {v}" for k, v in (s.get("traits") or {}).items())
        for n, s in zip(numbers, slots))
    groups = ""
    if communities:
        groups = "Groups they may belong to: " + "; ".join(f"{c.name} ({c.kind})" for c in communities) + "\n"
    return f"""Write {len(slots)} distinct people for this audience segment.

Segment: {seg.label}; country: {seg.country or "as implied"}; role: {seg.role or seg.label}
Languages: {", ".join(seg.languages) or "local norms"}; platforms: {", ".join(seg.platforms) or "typical for them"}
Known about this group: {seg.notes or "see the topic"}
{groups}Topic of the simulation: {requirement[:800]}
Background: {context[:1500]}

Fixed demographics (keep each person's slot number as "i"):
{people}

Let where they live, their income, education and thinking style shape every field. Give each person a different
attitude to the topic. Return JSON: {{"people": [{CARD_SCHEMA}]}}"""


def expand_card(r: Dict[str, Any]) -> Dict[str, Any]:
    """A card row in the planner's field names, plus a partial BDE card built only from what the model wrote."""
    def lst(v: Any, n: int) -> List[str]:
        v = v if isinstance(v, list) else [v] if v else []
        return [str(x).strip() for x in v if str(x).strip()][:n]
    row = {"name": r.get("name"), "city": r.get("city"), "occupation": r.get("occ"), "household": r.get("hh"),
           "languages": lst(r.get("lang"), 4), "platform_habits": r.get("plat"), "decision_role": r.get("role"),
           "attitude": r.get("att"), "concerns": lst(r.get("con"), 3), "what_persuades_them": r.get("why"),
           "contradiction": r.get("contra"), "voice": r.get("voice"), "example_post": r.get("post"),
           "interested_topics": lst(r.get("topics"), 4), "bio": r.get("bio")}
    bde = {"background": {"knows": r.get("knows"), "says_vs_does": r.get("svd")},
           "decision_procedure": {"who_they_ask": r.get("ask"), "speed": r.get("spd"), "risk": r.get("risk"),
                                  "stoppers": lst(r.get("deal"), 2)},
           "evaluation": {"monthly_discretionary": r.get("spare"), "dealbreakers": lst(r.get("deal"), 2),
                          "trust_cues": lst(r.get("trust"), 2)}}
    bde = {sec: {k: v for k, v in fields.items() if v not in (None, "", [])} for sec, fields in bde.items()}
    row["bde_card"] = {sec: f for sec, f in bde.items() if f}
    return {k: v for k, v in row.items() if v not in (None, "", [])}


def card_persona(name: str, age: Any, occupation: str, place: str, row: Dict[str, Any], traits: Dict[str, Any]) -> str:
    """The persona text for a card person, assembled from the fields the model wrote (no extra model call)."""
    bits = [f"{name}, {age}, {occupation} from {place}."]
    for label, key in (("Household", "household"), ("Attitude", "attitude"), ("Persuaded by", "what_persuades_them"),
                       ("Contradiction", "contradiction"), ("Online", "platform_habits"), ("Writes like this", "voice")):
        if row.get(key):
            bits.append(f"{label}: {row[key]}.")
    if row.get("concerns"):
        bits.append("Concerns: " + "; ".join(row["concerns"]) + ".")
    if traits:
        bits.append("Background: " + "; ".join(f"{k.replace('_', ' ')}: {v}" for k, v in traits.items()) + ".")
    dp = (row.get("bde_card") or {}).get("decision_procedure") or {}
    ev = (row.get("bde_card") or {}).get("evaluation") or {}
    how = [x for x in (f"asks {dp['who_they_ask']}" if dp.get("who_they_ask") else "",
                       f"decides {dp['speed']}" if dp.get("speed") else "",
                       f"risk {dp['risk']}" if dp.get("risk") else "",
                       f"deal-breakers: {', '.join(ev['dealbreakers'])}" if ev.get("dealbreakers") else "",
                       f"trusts {', '.join(ev['trust_cues'])}" if ev.get("trust_cues") else "",
                       f"spare money {ev['monthly_discretionary']}" if ev.get("monthly_discretionary") else "") if x]
    if how:
        bits.append("How I decide: " + "; ".join(how) + ".")
    return " ".join(bits)


# --------------------------------------------------------------------------
# Exact-prompt cache
# --------------------------------------------------------------------------

def _cache_path() -> str:
    explicit = os.environ.get("MM_POPULATION_CACHE")
    if explicit:
        return explicit
    from ..config import UPLOAD_ROOT
    return os.path.join(UPLOAD_ROOT, "population_cache.sqlite")


class PromptCache:
    """Model answers stored by sha256(version, provider, model, system, prompt). Off with MM_POPULATION_CACHE=off."""

    def __init__(self, path: Optional[str] = None):
        path = path or _cache_path()
        self.enabled = path.lower() != "off"
        self.hits = self.misses = 0
        self._lock = threading.Lock()
        if self.enabled:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            self._db = sqlite3.connect(path, check_same_thread=False, timeout=30)
            self._db.execute("CREATE TABLE IF NOT EXISTS answers (key TEXT PRIMARY KEY, text TEXT, provider TEXT, "
                             "model TEXT, created REAL)")
            self._db.commit()

    @staticmethod
    def key(provider: str, model: str, system: str, prompt: str) -> str:
        return hashlib.sha256("\x1f".join((PROMPT_VERSION, provider, model, system, prompt)).encode("utf-8")).hexdigest()

    def get(self, key: str) -> Optional[Tuple[str, str, str]]:
        if not self.enabled:
            return None
        with self._lock:
            row = self._db.execute("SELECT text, provider, model FROM answers WHERE key = ?", (key,)).fetchone()
            if row:
                self.hits += 1
            else:
                self.misses += 1
        return row

    def put(self, key: str, text: str, provider: str, model: str) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO answers VALUES (?, ?, ?, ?, ?)",
                             (key, text, provider, model, time.time()))
            self._db.commit()


# --------------------------------------------------------------------------
# Provider lanes with an adaptive limit
# --------------------------------------------------------------------------

class Lane:
    """Calls in flight for one provider: the limit halves after an overload (timeout, rate limit, 5xx) and grows by
    one after twice its size in successes, between 1 and `max_limit`."""

    def __init__(self, name: str, limit: int, max_limit: Optional[int] = None):
        self.name = name
        self.max_limit = max(1, max_limit or limit)
        self.limit = max(1, min(limit, self.max_limit))
        self.in_flight = 0
        self._streak = 0
        self._cond = threading.Condition()
        self.calls = self.overloads = 0

    def acquire(self) -> None:
        with self._cond:
            while self.in_flight >= self.limit:
                self._cond.wait()
            self.in_flight += 1

    def release(self, ok: bool, overloaded: bool = False) -> None:
        with self._cond:
            self.in_flight -= 1
            self.calls += 1
            if overloaded:
                self.overloads += 1
                self.limit = max(1, self.limit // 2)
                self._streak = 0
            elif ok:
                self._streak += 1
                if self._streak >= 2 * self.limit and self.limit < self.max_limit:
                    self.limit += 1
                    self._streak = 0
            self._cond.notify_all()


def lane_limit(provider: str, default: int) -> int:
    for name in (f"MM_LANE_{provider.upper()}", "MM_LANE"):
        v = os.environ.get(name)
        if v and v.isdigit():
            return max(1, int(v))
    return max(1, default)


def _overloaded(err: Exception) -> bool:
    from ..utils.model_pool import _is_rate_limit_or_transient
    return _is_rate_limit_or_transient(err)


class Caller:
    """One model call for a provider slot through that provider's lane and the exact-prompt cache; returns the
    parsed JSON with the provider and model that answered. A failed call raises (the caller decides what to ask
    again). Works with a provider pool (one lane per slot) or a single client (one lane)."""

    def __init__(self, client: Any, model: str, parallel: int, cache: Optional[PromptCache] = None):
        self.client, self.model = client, model
        self.slots = getattr(client, "slots", None) or [None]
        self.n = len(self.slots)
        per_lane = max(1, parallel // self.n)
        self.lanes = [Lane(getattr(s, "provider", None) or "default",
                           lane_limit(getattr(s, "provider", None) or "default", per_lane)) for s in self.slots]
        self.cache = cache if cache is not None else PromptCache()

    def lane_of(self, provider: Optional[str]) -> int:
        """The slot index of a provider family (the writer of a person), else 0."""
        if provider and hasattr(self.client, "slot_for_provider"):
            idx = self.client.slot_for_provider(provider)
            if idx is not None:
                return idx % self.n
        return 0

    def text(self, lane_idx: int, system: str, prompt: str, max_tokens: int = 8000,
             temperature: float = 0.8) -> Tuple[str, str, str]:
        from .persona_planner import _resolve_provider_meta
        lane_idx %= self.n
        slot = self.slots[lane_idx]
        key = PromptCache.key(getattr(slot, "provider", None) or "default", getattr(slot, "model", None) or self.model,
                              system, prompt)
        hit = self.cache.get(key)
        if hit:
            return hit
        lane = self.lanes[lane_idx]
        lane.acquire()
        ok = overloaded = False
        try:
            kw: Dict[str, Any] = {"model": self.model, "temperature": temperature, "max_tokens": max_tokens,
                                  "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
            if slot is not None:
                kw["slot_index"] = lane_idx
            resp = create_chat_completion(self.client, **kw)
            text = extract_chat_completion_text(resp)
            prov, mod = _resolve_provider_meta(self.client, self.model, resp, lane_idx if slot is not None else None)
            ok = True
        except Exception as e:  # noqa: BLE001 - classified for the lane, then re-raised
            overloaded = _overloaded(e)
            raise
        finally:
            lane.release(ok, overloaded)
        return text, prov, mod

    def remember(self, lane_idx: int, system: str, prompt: str, answer: Tuple[str, str, str]) -> None:
        """Keep an answer that was usable, so a rerun reuses it."""
        slot = self.slots[lane_idx % self.n]
        self.cache.put(PromptCache.key(getattr(slot, "provider", None) or "default",
                                       getattr(slot, "model", None) or self.model, system, prompt), *answer)

    def stats(self) -> Dict[str, Any]:
        return {"lanes": {ln.name: {"calls": ln.calls, "overloads": ln.overloads, "limit_now": ln.limit} for ln in self.lanes},
                "cache": {"hits": self.cache.hits, "misses": self.cache.misses}}


# --------------------------------------------------------------------------
# Writing the cards
# --------------------------------------------------------------------------

def _parse_rows(text: str) -> List[Dict[str, Any]]:
    from .persona_planner import parse_json_block
    data = parse_json_block(text)
    rows = data.get("people") or data.get("personas") if isinstance(data, dict) else data
    return [r for r in (rows or []) if isinstance(r, dict)]


def write_cards(client: Any, model: str, jobs: List[Tuple[Any, List[Dict[str, Any]], Sequence[Any]]],
                job_slot: List[int], requirement: str, context: str, parallel: int = 12,
                progress: Optional[Callable[[int, int, str], None]] = None,
                cache: Optional[PromptCache] = None, pause_s: float = 3.0) -> Dict[str, Any]:
    """Write a card for every slot of every job. jobs: (segment, slots, communities); job_slot: the provider slot
    index per job. Returns {"rows": {job: {slot: (row, provider, model)}}, "missing": {job: [slot,...]},
    "lanes": {...}, "cache": {...}}. Missing slots stay missing: the caller leaves those people out."""
    slots_of = getattr(client, "slots", None) or [None]
    n_lanes = len(slots_of)
    per_lane = max(1, parallel // n_lanes)
    lanes = [Lane(getattr(s, "provider", None) or "default", lane_limit(getattr(s, "provider", None) or "default", per_lane))
             for s in slots_of]
    cache = cache if cache is not None else PromptCache()
    total = sum(len(j[1]) for j in jobs)
    done = [0]
    lock = threading.Lock()
    rows_out: Dict[int, Dict[int, Tuple[Dict[str, Any], str, str]]] = {}
    missing_out: Dict[int, List[int]] = {}

    def one_call(lane_idx: int, prompt: str) -> Tuple[str, str, str]:
        from .persona_planner import _resolve_provider_meta
        slot = slots_of[lane_idx]
        prov_hint = getattr(slot, "provider", None) or "default"
        model_hint = getattr(slot, "model", None) or model
        key = PromptCache.key(prov_hint, model_hint, CARD_SYSTEM, prompt)
        hit = cache.get(key)
        if hit:
            return hit
        lane = lanes[lane_idx]
        lane.acquire()
        ok = overloaded = False
        try:
            kw: Dict[str, Any] = {"model": model, "temperature": 0.9, "max_tokens": 9000,
                                  "messages": [{"role": "system", "content": CARD_SYSTEM}, {"role": "user", "content": prompt}]}
            if slot is not None:
                kw["slot_index"] = lane_idx
            resp = create_chat_completion(client, **kw)
            text = extract_chat_completion_text(resp)
            prov, mod = _resolve_provider_meta(client, model, resp, lane_idx if slot is not None else None)
            ok = True
            return text, prov, mod
        except Exception as e:  # noqa: BLE001 - classified for the lane, then re-raised
            overloaded = _overloaded(e)
            raise
        finally:
            lane.release(ok, overloaded)

    def run_job(j: int) -> None:
        seg, slots, comms = jobs[j]
        lane_idx = job_slot[j] % n_lanes
        pending = list(range(len(slots)))
        got: Dict[int, Tuple[Dict[str, Any], str, str]] = {}
        for attempt in range(CARD_ATTEMPTS):
            if not pending:
                break
            if attempt:
                time.sleep(pause_s * attempt)
            numbers = [k + 1 for k in pending]
            prompt = card_prompt(seg, [slots[k] for k in pending], numbers, requirement, context, comms)
            try:
                text, prov, mod = one_call(lane_idx, prompt)
                rows = _parse_rows(text)
            except Exception as e:  # noqa: BLE001 - those slots are asked again, then reported missing
                logger.warning(f"card batch {j} ({seg.label}, {len(pending)} people) attempt {attempt + 1}: {str(e)[:160]}")
                continue
            useful = 0
            for pos, r in enumerate(rows):
                try:
                    k = int(r.get("i")) - 1
                except (TypeError, ValueError):
                    k = pending[pos] if pos < len(pending) and len(rows) == len(pending) else -1
                if k in pending and str(r.get("name") or "").strip() and k not in got:
                    got[k] = (expand_card(r), prov, mod)
                    useful += 1
            if useful:
                cache.put(PromptCache.key(getattr(slots_of[lane_idx], "provider", None) or "default",
                                          getattr(slots_of[lane_idx], "model", None) or model, CARD_SYSTEM, prompt),
                          text, prov, mod)
            pending = [k for k in pending if k not in got]
        with lock:
            rows_out[j] = got
            if pending:
                missing_out[j] = pending
            done[0] += len(slots)
            d = done[0]
        if progress:
            progress(d, total, seg.label)

    by_lane: Dict[int, List[int]] = {}
    for j in range(len(jobs)):
        by_lane.setdefault(job_slot[j] % n_lanes, []).append(j)
    executors = [ThreadPoolExecutor(max_workers=lanes[i].max_limit) for i in range(n_lanes)]
    try:
        futures = [executors[i].submit(run_job, j) for i, js in by_lane.items() for j in js]
        for f in futures:
            f.result()
    finally:
        for ex in executors:
            ex.shutdown(wait=True)
    return {"rows": rows_out, "missing": missing_out,
            "lanes": {ln.name: {"calls": ln.calls, "overloads": ln.overloads, "limit_now": ln.limit} for ln in lanes},
            "cache": {"hits": cache.hits, "misses": cache.misses}}


def interview_sample(entities: List[Any], share: float, min_per_cell: int = 2, seed: int = 7) -> List[Any]:
    """A stratified sample for the full life interview: `share` of each (segment, provider) cell, at least
    `min_per_cell` (or the whole cell when it is smaller)."""
    if share >= 1:
        return list(entities)
    cells: Dict[Tuple[str, str], List[Any]] = {}
    for e in entities:
        a = e.attributes or {}
        cells.setdefault((str(a.get("segment") or ""), str(a.get("model_provider") or "")), []).append(e)
    rng = random.Random(seed)
    out = []
    for key in sorted(cells):
        group = cells[key]
        k = min(len(group), max(min_per_cell, int(round(share * len(group)))))
        out.extend(rng.sample(group, k))
    return out
