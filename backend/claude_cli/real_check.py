"""real_check.py - a ready-to-use check of a run with real people: the few questions that decided its verdict, who to
ask, how many, and the command that compares their answers with the simulated ones (calibrate).

Simulated answers are directions, not measurements; the shortest way to firm one up is a small real survey. This
turns what the run already knows (the offer and goal, the winning messages, the price result, the top objection, the
winning ad) into real_check.md and a blank answers sheet, real_check.csv, whose columns `calibrate --real` reads.

Sample size: enough real answers for a +-10 point interval on the main yes-rate at 95% (more per audience you want
to compare), or the plan from an earlier calibration when there is one. Stdlib only.
"""

from __future__ import annotations

import csv
import io
import math
from typing import Any, Dict, List, Optional

ANSWER_SCALE = "yes / maybe / no"
HALFWIDTH = 0.10


def _verb(goal: Optional[str]) -> str:
    g = str(goal or "").strip().rstrip(".")
    return (g[:1].lower() + g[1:]) if g and len(g) <= 40 else "buy it"


def people_needed(rate_pct: Optional[float], halfwidth: float = HALFWIDTH) -> int:
    """Real answers for a +-halfwidth interval on a yes-rate at 95% (normal approximation, at least 30)."""
    p = min(0.95, max(0.05, (rate_pct if isinstance(rate_pct, (int, float)) else 50.0) / 100))
    return max(30, math.ceil(1.96 ** 2 * p * (1 - p) / halfwidth ** 2))


def _top_creatives(feed: Dict[str, Any], n: int = 2) -> List[str]:
    """The best simulated ads by expected click rate, named by their headline when the run kept it."""
    per = ((feed or {}).get("summary") or {}).get("per_creative") or {}
    names = {str(c.get("id")): str(c.get("headline") or c.get("title") or c.get("name") or "").strip()
             for c in (feed or {}).get("creatives") or [] if isinstance(c, dict)}
    score = lambda m: float((m or {}).get("expected_ctr") if (m or {}).get("expected_ctr") is not None else (m or {}).get("ctr") or 0)  # noqa: E731
    ranked = sorted(per.items(), key=lambda kv: -score(kv[1]))
    return [names.get(str(cid)) or str(cid) for cid, _ in ranked[:n]]


def _price(bundle: Dict[str, Any], mk: Dict[str, Any]) -> Optional[str]:
    """The price to put to real people: the revenue-best Gabor-Granger price, else the Van Westendorp optimum."""
    gg = bundle.get("choice_gabor_granger") or {}
    best = gg.get("revenue_max_price") or (gg.get("result") or {}).get("revenue_max_price")
    if best:
        return str(best)
    pr = mk.get("pricing") or {}
    v = pr.get("optimal")
    cur = mk.get("currency") or ""
    return f"{cur} {v}".strip() if isinstance(v, (int, float)) else None


def build(bundle: Dict[str, Any], mk: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """The check kit for this run: {questions, audience, people_needed, markdown, csv}; None when the run has nothing
    to check (no survey, feed test or price result)."""
    b, mk = bundle or {}, mk or {}
    offer = mk.get("offer") or (b.get("survey") or {}).get("offer") or "the offer"
    goal = _verb(mk.get("goal") or (b.get("survey") or {}).get("goal"))
    overall = mk.get("overall") or {}
    rate = overall.get("convert_yes")
    questions: List[Dict[str, Any]] = []
    if mk.get("has_survey"):
        questions.append({"column": "y", "question": f"Would you {goal} for {offer}?", "answers": ANSWER_SCALE,
                          "simulated": f"{rate}% of simulated people said yes" if rate is not None else ""})
    ranked = [m for m in (mk.get("messages_ranked") or []) if m.get("label")][:2]
    if len(ranked) == 2:
        questions.append({"column": "q_message", "question": f"Which of these makes you more likely to {goal}? "
                          f"A: \"{ranked[0]['label']}\"  B: \"{ranked[1]['label']}\"", "answers": "A / B / neither",
                          "simulated": f"simulated winner: A ({ranked[0].get('share')}% picked it)"})
    price = _price(b, mk)
    if price:
        questions.append({"column": "q_price", "question": f"Would you {goal} for {offer} at {price}?", "answers": ANSWER_SCALE,
                          "simulated": "the simulated price result"})
    ads = _top_creatives(b.get("feed_test") or {})
    if len(ads) == 2:
        questions.append({"column": "q_ad", "question": f"Which of these two ads would you click? A: \"{ads[0]}\"  B: \"{ads[1]}\"",
                          "answers": "A / B / neither", "simulated": "simulated winner: A"})
    objs = [o for o in (mk.get("objections") or []) if o.get("label")]
    if questions:
        questions.append({"column": "q_objection", "question": f"What, if anything, would stop you from going ahead?",
                          "answers": "free text",
                          "simulated": f"top simulated objection: {objs[0]['label']} ({objs[0].get('share')}%)" if objs else ""})
    if not questions:
        return None
    segs = [s for s in (mk.get("by_segment") or []) if s.get("key") and s.get("key") != "Unassigned"][:3]
    countries = [c.get("key") for c in (mk.get("by_country") or []) if c.get("key") and c.get("key") != "Unknown"][:3]
    plan = (((b.get("calibration") or {}).get("ppi") or {}).get("plan") or {})
    n = int(plan.get("more_with_panel") or 0) or people_needed(rate)
    basis = ("the plan from your earlier calibration" if plan.get("more_with_panel")
             else f"a +-{int(HALFWIDTH * 100)} point margin on the yes-rate at 95%")
    audience = {"segments": [s["key"] for s in segs], "countries": countries}
    alloc = (((b.get("calibration") or {}).get("ppi") or {}).get("allocation") or {})
    quotas = {r["stratum"]: r["add"] for r in alloc.get("by_stratum") or [] if isinstance(r, dict) and r.get("add")}
    if quotas and plan.get("more_with_panel") and alloc.get("extra") == n:
        audience["quotas"] = quotas                                     # where the calibrate plan says to collect them
    md = render_markdown(questions, audience, n, basis, len(segs))
    return {"questions": questions, "audience": audience, "people_needed": n, "basis": basis,
            "markdown": md, "csv": answer_sheet(questions)}


def answer_sheet(questions: List[Dict[str, Any]]) -> str:
    """A blank sheet: one row per real person. segment/country/gender/age and y are the columns calibrate reads."""
    cols = ["respondent", "segment", "country", "gender", "age"] + [q["column"] for q in questions]
    out = io.StringIO()
    csv.writer(out).writerow(cols)
    return out.getvalue()


def render_markdown(questions: List[Dict[str, Any]], audience: Dict[str, Any], n: int, basis: str, n_segments: int) -> str:
    who = ", ".join(audience.get("segments") or []) or "the buyers you described"
    where = (" in " + ", ".join(audience["countries"])) if audience.get("countries") else ""
    lines = ["# Check this with real people", "",
             "The results in this run come from simulated people. Before you spend on the decision, ask a small number "
             "of real people the questions that decided it, then compare.", "",
             "## Who to ask", "", f"- {who}{where}.",
             f"- About **{n} people** in total ({basis}).",
             *([f"- Split them as your earlier calibration planned (more where the simulated panel predicted least): "
                + ", ".join(f"{k} {v}" for k, v in audience["quotas"].items()) + "."] if audience.get("quotas") else
               [f"- To compare audiences, aim for about {n} in each of the {n_segments} you care most about."] if n_segments > 1 else []),
             "- Customers, a mailing list, a short paid survey panel or a call list all work. Ask before you show the "
             "simulated answers.", "", "## Questions", ""]
    for i, q in enumerate(questions, 1):
        lines += [f"{i}. {q['question']}", f"   - Answers: {q['answers']}"]
        if q.get("simulated"):
            lines.append(f"   - Simulated: {q['simulated']}")
    lines += ["", "## When the answers are back", "",
              "Fill in `real_check.csv` (one row per person; `y` is the first question), then run:", "",
              "```bash", "python backend/claude_cli/mirofish.py calibrate --run-dir <this run folder> --real real_check.csv",
              "```", "",
              "It shows where the simulated people were right, where they were not, and a corrected rate with its margin.", ""]
    return "\n".join(lines)
