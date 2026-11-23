"""Pre-registered forecasts: lock what a run predicts before the real result exists, score it when it does.

A simulation is easy to believe after the fact. The ledger makes the claim checkable: `lock` reads a finished run,
writes its scorable predictions to forecast_lock.json, hashes them (SHA-256 over canonical JSON) and appends the hash
to an append-only ledger. `score` takes the real numbers later, refuses if the lock file no longer matches its hash,
and records hits and misses next to the lock. `table` writes the whole ledger as Markdown, misses included, so it can
be published. Commit the ledger to a public repository (or post the hash anywhere public) to get an outside timestamp.

Why: predictions of real experiments track the direction but overstate the size (Hewitt et al. 2024), and vendors now
earn trust with blind scoring against outcomes they could not see. Stdlib only, no model calls.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def sha(obj: Any) -> str:
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()


def _rate(row: Dict[str, Any]) -> Optional[float]:
    """The run's would-convert estimate for a group: the expected (probability-weighted) share when present."""
    for key in ("expected_convert_yes", "convert_yes"):
        v = row.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
            return round(float(v), 2)
    return None


def predictions(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """Scorable predictions from a run's saved files: the decision, the overall rate, and the order of segments,
    messages and creatives. Only what the run actually measured is included."""
    summary = bundle.get("summary") or {}
    mk = summary.get("marketing") or {}
    out: Dict[str, Any] = {}
    decision = (summary.get("decision") or {}).get("decision")
    if decision:
        out["decision"] = str(decision)
    overall = _rate(mk.get("overall") or {})
    if overall is not None:
        out["rate"] = overall
    segs = [(str(r.get("key")), _rate(r)) for r in mk.get("by_segment") or [] if isinstance(r, dict) and r.get("key")]
    segs = [(k, v) for k, v in segs if v is not None]
    if len(segs) >= 2:
        out["segment_rates"] = dict(segs)
        out["segment_order"] = [k for k, _ in sorted(segs, key=lambda kv: -kv[1])]
    msgs = [(str(m.get("key")), _rate(m)) for m in mk.get("messages_ranked") or [] if isinstance(m, dict) and m.get("key")]
    msgs = [(k, v) for k, v in msgs if v is not None]
    if len(msgs) >= 2:
        out["message_order"] = [k for k, _ in sorted(msgs, key=lambda kv: -kv[1])]
    fs = (bundle.get("feed_test") or {}).get("summary") or {}
    ranked = [str(x) for x in fs.get("ranked") or [] if x]
    if len(ranked) >= 2:                      # the feed test's own ranking of the creatives
        out["creative_order"] = ranked
        ctr = {k: (fs.get("per_creative") or {}).get(k, {}).get("expected_ctr") for k in ranked}
        ctr = {k: v for k, v in ctr.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
        if ctr:
            out["creative_expected_ctr"] = ctr
    return out


def _append(ledger: str, entry: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(ledger)), exist_ok=True)
    with open(ledger, "a", encoding="utf-8") as f:
        f.write(canonical(entry) + "\n")


def read_ledger(ledger: str) -> List[Dict[str, Any]]:
    if not os.path.exists(ledger):
        return []
    with open(ledger, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def lock(bundle: Dict[str, Any], run_dir: str, ledger: str, note: str = "", outcome_due: str = "") -> Dict[str, Any]:
    """Write forecast_lock.json in the run folder and append its hash to the ledger. Refuses to lock twice."""
    path = os.path.join(run_dir, "forecast_lock.json")
    if os.path.exists(path):
        raise ValueError(f"{path} already exists: a forecast is locked once. Score it, or copy the run to lock again.")
    pred = predictions(bundle)
    if not pred:
        raise ValueError("this run has nothing scorable yet (no survey, decision or feed test in summary.json)")
    manifest = bundle.get("run_manifest") or {}
    body = {"version": VERSION, "run": os.path.basename(os.path.abspath(run_dir)), "locked_at": _now(),
            "simulation_id": (bundle.get("summary") or {}).get("simulation_id") or manifest.get("simulation_id"),
            "note": note[:500], "outcome_due": outcome_due[:40], "prediction": pred,
            "provenance": manifest.get("provenance") or {}}
    digest = sha(body)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({**body, "sha256": digest}, f, ensure_ascii=False, indent=2)
    entry = {"kind": "lock", "id": digest[:12], "sha256": digest, "run": body["run"], "locked_at": body["locked_at"],
             "outcome_due": body["outcome_due"], "prediction": pred}
    _append(ledger, entry)
    return entry


def _ranks(order: Sequence[str], keys: Sequence[str]) -> List[int]:
    pos = {k: i for i, k in enumerate(order)}
    return [pos[k] for k in keys]


def spearman(a: Sequence[str], b: Sequence[str]) -> Optional[float]:
    """Rank correlation of two orders over the keys they share (None below 3 shared keys)."""
    shared = [k for k in a if k in set(b)]
    n = len(shared)
    if n < 3:
        return None
    ra = _ranks([k for k in a if k in shared], shared)
    rb = _ranks([k for k in b if k in shared], shared)
    d2 = sum((x - y) ** 2 for x, y in zip(ra, rb))
    return round(1 - 6 * d2 / (n * (n * n - 1)), 3)


def _order_from_rates(rates: Dict[str, Any]) -> List[str]:
    clean = {str(k): float(v) for k, v in (rates or {}).items()
             if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)}
    return [k for k, _ in sorted(clean.items(), key=lambda kv: -kv[1])]


def score_one(pred: Dict[str, Any], actual: Dict[str, Any]) -> Dict[str, Any]:
    """Compare a locked prediction with real numbers. actual: {rate?, segment_rates?, message_rates?,
    creative_rates?, decision_held?}. Only parts present on both sides are scored."""
    res: Dict[str, Any] = {"checks": []}
    if isinstance(actual.get("rate"), (int, float)) and pred.get("rate") is not None:
        err = round(float(pred["rate"]) - float(actual["rate"]), 2)
        res["rate"] = {"predicted": pred["rate"], "actual": actual["rate"], "error_points": err,
                       "ratio": round(float(pred["rate"]) / float(actual["rate"]), 2) if actual["rate"] else None}
        res["checks"].append(("rate within 5 points", abs(err) <= 5))
    for name, actual_key in (("segment_order", "segment_rates"), ("message_order", "message_rates"),
                             ("creative_order", "creative_rates")):
        if pred.get(name) and actual.get(actual_key):
            real = _order_from_rates(actual[actual_key])
            shared = [k for k in pred[name] if k in real]
            if len(shared) < 2:
                continue
            top_hit = [k for k in pred[name] if k in real][0] == real[0]
            res[name] = {"predicted": pred[name], "actual": real, "top_hit": top_hit, "spearman": spearman(pred[name], real)}
            res["checks"].append((f"{name.replace('_order', '')} winner", top_hit))
    if isinstance(actual.get("decision_held"), bool) and pred.get("decision"):
        res["decision"] = {"predicted": pred["decision"], "held": actual["decision_held"]}
        res["checks"].append(("decision held", actual["decision_held"]))
    hits = sum(1 for _, ok in res["checks"] if ok)
    res["hits"], res["total"] = hits, len(res["checks"])
    res["checks"] = [{"check": c, "hit": ok} for c, ok in res["checks"]]
    return res


def score(run_dir: str, actual: Dict[str, Any], ledger: str, source: str = "") -> Dict[str, Any]:
    """Verify the lock against its hash and the ledger, score it, append the score."""
    path = os.path.join(run_dir, "forecast_lock.json")
    if not os.path.exists(path):
        raise ValueError(f"no forecast_lock.json in {run_dir}: lock the run before the real result is known")
    with open(path, encoding="utf-8") as f:
        locked = json.load(f)
    digest = locked.pop("sha256", None)
    if sha(locked) != digest:
        raise ValueError("forecast_lock.json was changed after it was locked (hash mismatch); it cannot be scored")
    entries = [e for e in read_ledger(ledger) if e.get("kind") == "lock" and e.get("sha256") == digest]
    if not entries:
        raise ValueError("this lock is not in the ledger: pass the --ledger it was locked into")
    result = score_one(locked["prediction"], actual)
    entry = {"kind": "score", "id": digest[:12], "sha256": digest, "run": locked.get("run"), "scored_at": _now(),
             "source": source[:300], "actual": actual, "result": result,
             "days_after_lock": _days(locked.get("locked_at"))}
    _append(ledger, entry)
    return entry


def _days(iso: Optional[str]) -> Optional[int]:
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(str(iso))).days
    except (TypeError, ValueError):
        return None


def table(ledger: str) -> str:
    """The whole ledger as Markdown: every lock, scored or not, with hits and misses."""
    entries = read_ledger(ledger)
    scores = {e["sha256"]: e for e in entries if e.get("kind") == "score"}
    locks = [e for e in entries if e.get("kind") == "lock"]
    lines = ["# Forecast ledger", "",
             "Each row is a prediction locked (hashed) before the real result existed. Misses stay in the table.", "",
             "| Locked | Run | Hash | Predicted | Real | Hits |", "|---|---|---|---|---|---|"]
    for e in locks:
        s = scores.get(e["sha256"])
        pred = e.get("prediction") or {}
        guess = ", ".join(x for x in (f"rate {pred['rate']}%" if "rate" in pred else "",
                                      f"top segment {pred['segment_order'][0]}" if pred.get("segment_order") else "",
                                      pred.get("decision", "")) if x)
        if s:
            r = s["result"]
            real = ", ".join(x for x in (f"rate {r['rate']['actual']}%" if r.get("rate") else "",
                                         f"top segment {r['segment_order']['actual'][0]}" if r.get("segment_order") else "") if x)
            hits = f"{r['hits']} of {r['total']}"
        else:
            real, hits = "not scored yet" + (f" (due {e['outcome_due']})" if e.get("outcome_due") else ""), "-"
        lines.append(f"| {str(e['locked_at'])[:10]} | {e['run']} | `{e['id']}` | {guess or '-'} | {real or '-'} | {hits} |")
    scored = [scores[e["sha256"]]["result"] for e in locks if e["sha256"] in scores]
    if scored:
        h, t = sum(r["hits"] for r in scored), sum(r["total"] for r in scored)
        lines += ["", f"{len(scored)} of {len(locks)} forecasts scored; {h} of {t} checks hit."]
    return "\n".join(lines) + "\n"
