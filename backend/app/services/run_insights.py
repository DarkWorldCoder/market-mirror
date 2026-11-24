"""Cross-run insights for the workspace overview, read from saved run folders only (no model calls, no network).

`collect(root)` walks `mirofish_runs/<name>/` and the forecast ledger next to them and returns one aggregate: runs per
day with their decision, the decision mix, buying intent per run (with n and a 95% Wilson interval), objections and
segments merged across runs, audience geography (people per country and city), evidence grades and real-sample
checks, recorded spend estimates, the forecast ledger with hits and misses kept, and runs that still look busy.

Every file is read defensively: a missing, unreadable, oversized or malformed file is skipped, never fatal. Each run's
digest is cached by the size and mtime of the files it reads, so a second request over hundreds of runs only stats
files. Every number here describes simulated people; the frontend labels them that way.
"""
from __future__ import annotations

import json
import math
import re
import threading
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")
MAX_JSON = 25 * 1024 * 1024
MAX_LEDGER = 5 * 1024 * 1024
# The files a run digest reads; their (size, mtime) is the cache key. progress.log only marks activity.
TRACKED = ("summary.json", "run_manifest.json", "run_status.json", "config.json", "feed_test.json",
           "calibration.json", "spend_cap.json", "forecast_lock.json", "progress.log", "actions.json", "timeline.json")
ACTIVE = re.compile(r"^(running|preparing|processing|pending|queued|in_progress|starting)$", re.I)
STALE_AFTER = 30 * 60          # a "running" run whose files have not changed for this long is not shown as live
SMALL_SAMPLE = 30
TOP = 12

_cache: Dict[str, Tuple[Tuple, Dict[str, Any]]] = {}
_lock = threading.Lock()


# ---------------------------------------------------------------- reading

def _plain(path: Path) -> bool:
    try:
        return not path.is_symlink() and path.is_file()
    except OSError:
        return False


def _read(path: Path) -> Optional[Any]:
    try:
        if not _plain(path) or path.stat().st_size > MAX_JSON:
            return None
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, RecursionError):
        return None
    if isinstance(data, dict) and "success" in data and "data" in data:
        data = data["data"]
    return data


def _obj(v: Any) -> Dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _list(v: Any) -> List[Any]:
    return v if isinstance(v, list) else []


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v) if math.isfinite(v) else None


def _int(v: Any) -> Optional[int]:
    n = _num(v)
    return int(n) if n is not None and n >= 0 and n == int(n) else None


def _text(v: Any, limit: int = 200) -> str:
    return v.strip()[:limit] if isinstance(v, str) else ""


def _signature(path: Path) -> Tuple:
    sig: List[Tuple] = []
    try:
        sig.append(("", path.stat().st_mtime_ns))
    except OSError:
        return ()
    for name in TRACKED:
        p = path / name
        try:
            if not p.is_symlink() and p.is_file():
                st = p.stat()
                sig.append((name, st.st_size, st.st_mtime_ns))
        except OSError:
            continue
    return tuple(sig)


def _run_dirs(root: Path) -> List[Path]:
    try:
        entries = list(root.iterdir())
    except OSError:
        return []
    out = []
    for d in entries:
        try:
            if d.is_symlink() or not d.is_dir() or not NAME.fullmatch(d.name) or ".." in d.name:
                continue
        except OSError:
            continue
        if _plain(d / "summary.json") or _plain(d / "run_manifest.json"):
            out.append(d)
    return out


# ---------------------------------------------------------------- per-run digest

def decision_key(value: Any) -> str:
    """go / iterate / no_go / unrecorded. Any other recorded decision counts as iterate (neither go nor stop)."""
    d = value.strip().lower() if isinstance(value, str) else ""
    if not d:
        return "unrecorded"
    if re.fullmatch(r"go|launch|proceed|scale", d):
        return "go"
    if re.search(r"no.?go|stop|reject|kill", d):
        return "no_go"
    return "iterate"


def wilson(pct: float, n: int, z: float = 1.96) -> Tuple[float, float]:
    """95% Wilson interval for a percentage over n answers, in percent."""
    p = min(1.0, max(0.0, pct / 100.0))
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return round(max(0.0, centre - half) * 100, 1), round(min(1.0, centre + half) * 100, 1)


def _iso_date(value: Any) -> Optional[str]:
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def _city(city: Any, country: str) -> str:
    c = _text(city, 120)
    if country and c.lower().endswith(", " + country.lower()):      # "Bengaluru, India" -> "Bengaluru"
        c = c[: -(len(country) + 2)].strip()
    return c


def _people(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Simulated people from persona_index: kind persona (graph entities and communities are not people)."""
    return [r for r in _list(cfg.get("persona_index"))
            if isinstance(r, dict) and str(r.get("kind") or "persona").lower() == "persona"]


def _evidence(summary_mk: Dict[str, Any], feed: Dict[str, Any], cal: Dict[str, Any],
              people: List[Dict[str, Any]], has_test: bool) -> Optional[Dict[str, Any]]:
    """The run's A-D grade from app/services/evidence.py, on what the saved files show. The feelings check needs the
    behaviour state and is left out here, so the dashboard's own grade can be a step lower when feelings were flagged."""
    if not has_test:
        return None
    try:
        from . import evidence
    except Exception:  # noqa: BLE001 - the overview works without grades
        return None
    answered = _int(summary_mk.get("answered")) or _int(_obj(summary_mk.get("overall")).get("n")) or 0
    survey = {"responses": [{"answer": True}] * min(answered, 100000),
              "ssr": _obj(summary_mk.get("ssr")), "retest": _obj(summary_mk.get("retest"))}
    feed_light = {k: feed.get(k) for k in ("multi_seed", "usage_by_provider") if isinstance(feed.get(k), dict)}
    if not answered and isinstance(feed.get("sessions"), list):
        feed_light["sessions"] = [{"agent_id": s.get("agent_id")} for s in feed["sessions"] if isinstance(s, dict)]
    try:
        g = evidence.grade({"survey": survey, "feed_test": feed_light or ({"ran": True} if feed else {}),
                            "calibration": cal, "profiles": people})
    except Exception:  # noqa: BLE001
        return None
    return {"grade": g.get("grade"), "points": g.get("points"), "meaning": g.get("meaning"),
            "reasons": [str(r) for r in _list(g.get("reasons"))][:8]}


def _spend(path: Path, manifest: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    cap = _obj(_read(path / "spend_cap.json"))
    source = "spend_cap.json"
    if _num(cap.get("spent_usd")) is None:
        cap, source = _obj(manifest.get("spend_cap")), "run_manifest.json"
    prov = _obj(manifest.get("provenance"))
    spent, limit = _num(cap.get("spent_usd")), _num(cap.get("limit_usd"))
    if limit is None:
        limit = _num(prov.get("max_spend_usd"))
    if spent is None or spent < 0:
        return None
    return {"spent_usd": round(spent, 4), "limit_usd": round(limit, 2) if limit is not None and limit > 0 else None,
            "calls": _int(cap.get("calls")), "reached": bool(cap.get("reached")), "source": source}


def digest_run(path: Path) -> Dict[str, Any]:
    manifest = _obj(_read(path / "run_manifest.json"))
    summary = _obj(_read(path / "summary.json"))
    status = _obj(_read(path / "run_status.json"))
    mk = _obj(summary.get("marketing"))
    decision = _obj(summary.get("decision"))
    overall = _obj(mk.get("overall"))
    cfg = _obj(_read(path / "config.json"))
    people = _people(cfg)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0

    when = next((v for v in (manifest.get("finished_at"), manifest.get("started_at"), summary.get("generated_at"))
                 if _iso_date(v)), None)
    day = _iso_date(when) or (datetime.fromtimestamp(mtime).date().isoformat() if mtime else None)
    raw_decision = decision.get("decision") if isinstance(decision.get("decision"), str) else None
    title = _text(manifest.get("title")) or _text(summary.get("project_name")) or path.name
    count = _int(mk.get("people"))
    if count is None:
        count = _int(summary.get("agents"))
    out: Dict[str, Any] = {"name": path.name, "title": title, "date": day, "at": when if isinstance(when, str) else None,
                           "decision": decision_key(raw_decision), "decision_raw": raw_decision, "people": count}

    # buying intent: the share who said they would convert, with n
    rate, n = _num(overall.get("convert_yes")), _int(overall.get("n"))
    if rate is not None and n:
        low, high = wilson(rate, n)
        purchase = _obj(_obj(overall.get("ssr")).get("purchase"))
        out["intent"] = {"rate": round(rate, 1), "maybe": _num(overall.get("convert_maybe")), "n": n, "low": low,
                         "high": high, "small_sample": n < SMALL_SAMPLE,
                         "purchase_mean": _num(purchase.get("mean")), "purchase_sd": _num(purchase.get("sd")),
                         "goal": _text(mk.get("goal"), 120) or None}

    # objections, by label
    objs = []
    for o in _list(mk.get("objections")):
        if isinstance(o, dict) and _text(o.get("label")):
            objs.append({"label": _text(o.get("label"), 120), "type": _text(o.get("type"), 60) or None,
                         "people": _int(o.get("count")) or 0})
    out["objections"] = objs

    # segments: survey rows when present, else the people's recorded segments
    segs = []
    for r in _list(mk.get("by_segment")):
        if isinstance(r, dict) and _text(r.get("key")):
            segs.append({"segment": _text(r.get("key"), 120), "people": _int(r.get("n")) or 0,
                         "rate": _num(r.get("convert_yes"))})
    if not segs:
        tally = Counter(_text(p.get("segment"), 120) for p in people if _text(p.get("segment")))
        segs = [{"segment": k, "people": v, "rate": None} for k, v in tally.items()]
    out["segments"] = segs

    # geography: people per country and city
    places: Counter = Counter()
    seg_by_country: Dict[str, Counter] = defaultdict(Counter)
    for p in people:
        country = _text(p.get("country"), 80)
        if not country:
            continue
        places[(country, _city(p.get("city"), country))] += 1
        seg = _text(p.get("segment"), 120)
        if seg:
            seg_by_country[country][seg] += 1
    if not places:                                     # no people file: fall back to the survey's country rows
        for r in _list(mk.get("by_country")):
            if isinstance(r, dict) and _text(r.get("key")) and _int(r.get("n")):
                places[(_text(r.get("key"), 80), "")] += _int(r.get("n"))
    out["places"] = [[c, city, k] for (c, city), k in places.items()]
    out["place_segments"] = {c: dict(t) for c, t in seg_by_country.items()}
    out["people_total"] = len(people) if people else sum(places.values())

    # trust: evidence grade and real-sample check
    cal = _obj(_read(path / "calibration.json"))
    ppi_overall = _obj(_obj(cal.get("ppi")).get("overall"))
    n_real = _int(cal.get("n_real")) or _int(ppi_overall.get("n_real"))
    calibrated = bool(cal and (n_real or cal.get("overlap") or cal.get("ppi") or cal.get("calibration")))
    feed = _obj(_read(path / "feed_test.json")) if _plain(path / "feed_test.json") else {}
    has_test = bool(mk.get("has_survey") or overall or feed)
    out["trust"] = {"calibrated": calibrated, "n_real": n_real,
                    "spread": _text(_obj(cal.get("spread")).get("verdict"), 40) or None,
                    "evidence": _evidence(mk, feed, cal, people, has_test)}

    out["spend"] = _spend(path, manifest)

    lock = _obj(_read(path / "forecast_lock.json"))
    out["lock"] = ({"sha256": lock.get("sha256"), "run": path.name, "locked_at": lock.get("locked_at"),
                    "outcome_due": lock.get("outcome_due"), "prediction": _obj(lock.get("prediction"))}
                   if isinstance(lock.get("sha256"), str) else None)

    # live state: the saved runner status, unless the manifest recorded a finish or an error
    state = _text(status.get("runner_status") or summary.get("runner_status") or summary.get("simulation_status"), 40)
    activity = mtime
    for name in ("run_status.json", "progress.log", "actions.json", "timeline.json"):
        try:
            p = path / name
            if _plain(p):
                activity = max(activity, p.stat().st_mtime)
        except OSError:
            continue
    out["status"] = state or None
    out["running"] = bool(ACTIVE.fullmatch(state or "") and not manifest.get("finished_at") and not manifest.get("error"))
    out["progress"] = {"progress_percent": _num(status.get("progress_percent")),
                       "current_round": _int(status.get("current_round")),
                       "total_rounds": _int(status.get("total_rounds")), "last_activity": activity}
    return out


def _cached(path: Path) -> Optional[Dict[str, Any]]:
    sig = _signature(path)
    if not sig:
        return None
    key = str(path)
    with _lock:
        hit = _cache.get(key)
    if hit and hit[0] == sig:
        return hit[1]
    try:
        d = digest_run(path)
    except Exception:  # noqa: BLE001 - one broken run never breaks the overview
        return None
    with _lock:
        _cache[key] = (sig, d)
    return d


# ---------------------------------------------------------------- forecast ledger

def _ledger(root: Path, run_locks: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    entries: List[Dict[str, Any]] = []
    path = root / "forecast_ledger.jsonl"
    try:
        if _plain(path) and path.stat().st_size <= MAX_LEDGER:
            with path.open(encoding="utf-8") as f:
                for line in f:
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(e, dict) and isinstance(e.get("sha256"), str):
                        entries.append(e)
    except OSError:
        pass
    locks: Dict[str, Dict[str, Any]] = {}
    for e in entries:
        if e.get("kind") == "lock":
            locks.setdefault(e["sha256"], e)
    for lk in run_locks:                       # a lock file in a run folder that the ledger here does not list
        if lk and isinstance(lk.get("sha256"), str):
            locks.setdefault(lk["sha256"], {**lk, "in_ledger": False})
    scores = {e["sha256"]: e for e in entries if e.get("kind") == "score"}  # the last score wins
    rows = []
    for sha, e in locks.items():
        pred = _obj(e.get("prediction"))
        s = scores.get(sha)
        res = _obj(s.get("result")) if s else {}
        hits, total = _int(res.get("hits")), _int(res.get("total"))
        if not s:
            outcome = "pending"
        elif not total:
            outcome = "no_checks"
        else:
            outcome = "hit" if hits == total else "miss" if not hits else "mixed"
        order = _list(pred.get("segment_order"))
        rows.append({"id": sha[:12], "run": _text(e.get("run"), 120), "locked_at": _text(e.get("locked_at"), 40) or None,
                     "outcome_due": _text(e.get("outcome_due"), 40) or None, "in_ledger": e.get("in_ledger", True),
                     "predicted": {"decision": _text(pred.get("decision"), 40) or None, "rate": _num(pred.get("rate")),
                                   "top_segment": _text(order[0], 120) if order else None},
                     "scored": bool(s), "scored_at": _text(s.get("scored_at"), 40) if s else None,
                     "hits": hits if s else None, "total": total if s else None, "outcome": outcome,
                     "checks": [{"check": _text(c.get("check"), 80), "hit": bool(c.get("hit"))}
                                for c in _list(res.get("checks")) if isinstance(c, dict)][:8]})
    rows.sort(key=lambda r: r["locked_at"] or "", reverse=True)
    scored = [r for r in rows if r["scored"]]
    return {"locked": len(rows), "scored": len(scored),
            "hits": sum(r["hits"] or 0 for r in scored), "checks": sum(r["total"] or 0 for r in scored),
            "entries": rows}


# ---------------------------------------------------------------- aggregate

def collect(root: Path, now: Optional[float] = None) -> Dict[str, Any]:
    now = datetime.now().timestamp() if now is None else now
    runs = [d for d in (_cached(p) for p in _run_dirs(root)) if d]
    runs.sort(key=lambda r: (r.get("at") or r.get("date") or "", r["name"]), reverse=True)
    with _lock:                                        # forget runs that were deleted
        live = {str(root / r["name"]) for r in runs}
        for key in [k for k in _cache if k.startswith(str(root)) and k not in live]:
            _cache.pop(key, None)

    activity: Dict[str, List[str]] = defaultdict(list)
    decisions = Counter({"go": 0, "iterate": 0, "no_go": 0, "unrecorded": 0})
    objections: Dict[str, Dict[str, Any]] = {}
    segments: Dict[str, Dict[str, Any]] = {}
    countries: Dict[str, Dict[str, Any]] = {}
    cities: Dict[Tuple[str, str], Dict[str, Any]] = {}
    intent, trust_rows, spend_rows, running = [], [], [], []
    people_with_country = 0

    for r in runs:
        if r.get("date"):
            activity[r["date"]].append(r["name"])
        decisions[r["decision"]] += 1
        if r.get("intent"):
            intent.append({"run": r["name"], "title": r["title"], "date": r["date"], "decision": r["decision"], **r["intent"]})
        for o in r.get("objections") or []:
            key = re.sub(r"\s+", " ", o["label"].lower())
            row = objections.setdefault(key, {"label": o["label"], "type": o.get("type"), "runs": 0, "people": 0,
                                              "run_names": []})
            if r["name"] not in row["run_names"]:
                row["runs"] += 1
                row["run_names"].append(r["name"])
            row["people"] += o["people"]
        for s in r.get("segments") or []:
            key = re.sub(r"\s+", " ", s["segment"].lower())
            row = segments.setdefault(key, {"segment": s["segment"], "runs": 0, "people": 0, "rated_people": 0,
                                            "_yes": 0.0, "run_names": []})
            if r["name"] not in row["run_names"]:
                row["runs"] += 1
                row["run_names"].append(r["name"])
            row["people"] += s["people"]
            if s.get("rate") is not None and s["people"]:
                row["rated_people"] += s["people"]
                row["_yes"] += s["rate"] * s["people"]
        seen_countries = set()
        for country, city, k in r.get("places") or []:
            people_with_country += k
            c = countries.setdefault(country, {"country": country, "people": 0, "runs": 0, "segments": Counter()})
            c["people"] += k
            if country not in seen_countries:
                c["runs"] += 1
                seen_countries.add(country)
            if city:
                ci = cities.setdefault((country, city), {"country": country, "city": city, "people": 0, "runs": set()})
                ci["people"] += k
                ci["runs"].add(r["name"])
        for country, segs in (r.get("place_segments") or {}).items():
            if country in countries:
                countries[country]["segments"].update(segs)
        t = r.get("trust") or {}
        ev = t.get("evidence") or {}
        trust_rows.append({"run": r["name"], "title": r["title"], "date": r["date"], "grade": ev.get("grade"),
                           "points": ev.get("points"), "meaning": ev.get("meaning"), "reasons": ev.get("reasons") or [],
                           "calibrated": bool(t.get("calibrated")), "n_real": t.get("n_real"), "spread": t.get("spread")})
        if r.get("spend"):
            spend_rows.append({"run": r["name"], "title": r["title"], "date": r["date"], **r["spend"]})
        if r.get("running"):
            pr = r.get("progress") or {}
            last = pr.get("last_activity") or 0
            running.append({"name": r["name"], "title": r["title"], "status": r.get("status"),
                            "progress_percent": pr.get("progress_percent"), "current_round": pr.get("current_round"),
                            "total_rounds": pr.get("total_rounds"),
                            "last_activity": datetime.fromtimestamp(last).isoformat(timespec="seconds") if last else None,
                            "stale": bool(last) and now - last > STALE_AFTER})

    seg_rows = []
    for row in segments.values():
        rate = round(row["_yes"] / row["rated_people"], 1) if row["rated_people"] else None
        seg_rows.append({"segment": row["segment"], "runs": row["runs"], "people": row["people"],
                         "rate": rate, "rated_people": row["rated_people"], "run_names": row["run_names"][:20]})
    seg_rows.sort(key=lambda s: (-s["runs"], -s["people"], s["segment"]))
    obj_rows = sorted(objections.values(), key=lambda o: (-o["runs"], -o["people"], o["label"]))
    for o in obj_rows:
        o["run_names"] = o["run_names"][:20]
    country_rows = sorted(({**c, "segments": dict(c["segments"].most_common(8))} for c in countries.values()),
                          key=lambda c: (-c["people"], c["country"]))
    city_rows = sorted(({**c, "runs": len(c["runs"])} for c in cities.values()),
                       key=lambda c: (-c["people"], c["country"], c["city"]))
    graded = [t for t in trust_rows if t["grade"]]
    spend_rows.sort(key=lambda s: -s["spent_usd"])
    return {
        "generated_at": datetime.fromtimestamp(now).isoformat(timespec="seconds"),
        "total_runs": len(runs),
        "runs": [{k: r.get(k) for k in ("name", "title", "date", "at", "decision", "decision_raw", "people", "status")}
                 for r in runs],
        "activity": [{"date": d, "count": len(names), "runs": names} for d, names in sorted(activity.items())],
        "decisions": dict(decisions),
        "intent": intent,
        "objections": obj_rows[:TOP],
        "segments": seg_rows[:TOP],
        "geography": {"countries": country_rows, "cities": city_rows[:200],
                      "people_with_country": people_with_country,
                      "runs_with_places": sum(1 for r in runs if r.get("places"))},
        "trust": {"runs": graded + [t for t in trust_rows if not t["grade"] and t["calibrated"]],
                  "graded": len(graded), "calibrated": sum(1 for t in trust_rows if t["calibrated"]),
                  "grades": dict(Counter(t["grade"] for t in graded))},
        "spend": {"runs": spend_rows, "total_usd": round(sum(s["spent_usd"] for s in spend_rows), 4),
                  "estimate": True},
        "forecasts": _ledger(root, (r.get("lock") for r in runs)),
        "running": running,
    }
