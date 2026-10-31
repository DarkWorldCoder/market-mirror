"""How sure is this? An A-D evidence grade for a run's headline result, from what the run itself can show.

Simulated results differ a lot in how much they can carry: 20 people on one seed with no real data behind them is a
sketch; 300 people, three seeds that agree, a retest and a check against real answers is much firmer. The grade adds
up points from what the run recorded and says why, so the report writer and the dashboard never present a D as firm.

Points (the reasons list says which applied):
  people answering        200+ -> 2, 50+ -> 1
  seeds agree on the winner   80%+ over 3+ seeds -> 2, 60%+ -> 1
  answers rated from their words (SSR)  -> 1
  retest a simulated week later        70%+ same verdict -> 1, under 50% -> -1
  checked against real answers (calibration)  -> 2
  more than one model provider answered        -> 1
  feelings look too uniform / caricatured / too positive  -> -1 each, at most -2
Grade: A 7+ (and only with a real-data check), B 5+, C 3+, D below.

Stdlib only and no package-relative imports: the offline dashboard exporter loads this file by path.
"""

from typing import Any, Dict, List, Optional

GRADES = (("A", 7), ("B", 5), ("C", 3), ("D", -99))
MEANING = {"A": "firm enough to act on, within the stated margins",
           "B": "a solid direction; confirm the decision with a small real test",
           "C": "a direction only; test with real people before spending",
           "D": "a sketch; do not act on it without real data"}


def _answered(survey: Optional[Dict[str, Any]]) -> int:
    return sum(1 for r in (survey or {}).get("responses") or [] if isinstance(r, dict) and r.get("answer"))


def grade(bundle: Dict[str, Any], emotion_flags: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """{grade, points, reasons, meaning, basis} for the run in bundle (the exporter's bundle, or the report's)."""
    b = bundle or {}
    survey, feed = b.get("survey") or {}, b.get("feed_test") or {}
    pts, reasons = 0, []

    def add(k: int, text: str) -> None:
        nonlocal pts
        pts += k
        reasons.append(f"{text} ({'+' if k >= 0 else ''}{k})")
    n = _answered(survey) or len({s.get("agent_id") for s in feed.get("sessions") or [] if isinstance(s, dict)})
    if n >= 200:
        add(2, f"{n} simulated people answered")
    elif n >= 50:
        add(1, f"{n} simulated people answered")
    elif n:
        add(0, f"only {n} simulated people answered")
    ms = feed.get("multi_seed") or {}
    agree = ms.get("winner_agreement")
    if ms.get("n", 1) >= 3 and agree is not None and agree >= 80:
        add(2, f"{ms['n']} seeds, {agree}% picked the same winner")
    elif ms.get("n", 1) >= 2 and agree is not None and agree >= 60:
        add(1, f"{ms['n']} seeds, {agree}% picked the same winner")
    elif feed:
        add(0, "one seed, or seeds disagree on the winner")
    if (survey.get("ssr") or {}).get("used"):
        add(1, f"answers rated from their own words (SSR)")
    rt = (survey.get("retest") or {}).get("agreement_pct")
    if rt is not None:
        if rt >= 70:
            add(1, f"retest a simulated week later: {rt}% same verdict")
        elif rt < 50:
            add(-1, f"retest a simulated week later: only {rt}% same verdict")
    cal = b.get("calibration") or {}
    real = bool(cal and (cal.get("overlap") or cal.get("ppi") or cal.get("n_real")))
    if real:
        add(2, f"checked against real answers")
    provs = [k for k, v in (feed.get("usage_by_provider") or {}).items() if isinstance(v, dict) and v.get("calls")]
    if len(provs) > 1:
        add(1, f"{len(provs)} model providers answered")
    fl = emotion_flags or {}
    bad = [k for k in ("uniform", "caricature", "positive_skew") if fl.get(k)]
    if bad:
        add(-min(2, len(bad)), f"feelings flagged: {', '.join(x.replace('_', ' ') for x in bad)}")
    g = next(letter for letter, floor in GRADES if pts >= floor)
    if g == "A" and not real:
        g = "B"
        reasons.append("capped at B: no check against real answers")
    return {"grade": g, "points": pts, "reasons": reasons, "meaning": MEANING[g],
            "basis": "computed from what this run recorded; see app/services/evidence.py for the points"}


def badge_text(e: Optional[Dict[str, Any]]) -> str:
    return f"Evidence {e['grade']}: {e['meaning']}" if e and e.get("grade") else ""


def reasons_list(e: Optional[Dict[str, Any]]) -> List[str]:
    return list((e or {}).get("reasons") or [])
