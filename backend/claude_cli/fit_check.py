"""When not to trust a simulated panel: a check that runs before any paid step.

Simulated people are useful for screening ideas, pretesting wording and finding objections. They are weakest where
decisions often matter most. This reads the test's own config and the people it created, and says which of the known
weak spots apply, before money is spent:

- small_segments: segments with fewer than 10 people; their results are too thin to compare.
- less_covered_markets: half or more of the people outside the US, UK, Canada, Australia, New Zealand and Ireland,
  where plain persona prompts track real people worst (arXiv 2605.16193, 2502.16534).
- sensitive_topic: health, religion, ethnicity, politics, sexuality, immigration or money trouble in the brief;
  models flatten and misportray identity groups (Wang, Morgenstern & Dickerson, Nature Machine Intelligence 2025).
- new_category: the brief says the product is new to the world; synthetic samples fail most on questions with no
  history to draw on (Verasight synthetic-sample reports, 2025-26).
- absolute_numbers: the config asks for targets, forecasts or spend; simulated people say yes far more often than
  real ones (MarketMirror-Bench, 1 Nov 2026: 66% predicted vs 43% real), so use the order, not the rates.

Each warning says what to do instead. The check never blocks a run. Stdlib only.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, Iterable, List

WELL_COVERED = {"united states", "usa", "us", "u.s.", "america", "united kingdom", "uk", "u.k.", "gb", "great britain",
                "britain", "england", "scotland", "wales", "northern ireland", "canada", "ca", "australia", "au",
                "new zealand", "nz", "ireland", "ie"}
MIN_SEGMENT = 10

SENSITIVE = re.compile(
    r"\b(diagnos\w*|disease|cancer|diabet\w*|depress\w*|anxiety disorder|mental health|therapy|medication|pregnan\w*|"
    r"hiv|religio\w*|church|mosque|temple|faith|ethnic\w*|race|racial|caste|politic\w*|election|vote|voting|"
    r"lgbt\w*|gay|lesbian|transgender|sexual\w*|immigra\w*|refugee|visa status|debt|bankrupt\w*|payday loan|gambling)\b",
    re.I)
NEW_CATEGORY = re.compile(r"\b(first[- ]ever|world'?s first|new category|category[- ]creating|never been done|"
                          r"nothing like it|no one has (?:ever )?(?:built|made|done))\b", re.I)


def _texts(cfg: Dict[str, Any]) -> Iterable[str]:
    for key in ("requirement", "brief", "offer", "goal", "title", "name"):
        v = cfg.get(key)
        if isinstance(v, str):
            yield v
    survey = cfg.get("survey") if isinstance(cfg.get("survey"), dict) else {}
    for key in ("offer", "goal"):
        if isinstance(survey.get(key), str):
            yield survey[key]
    for m in survey.get("messages") or []:
        if isinstance(m, str):
            yield m
    for cr in cfg.get("creatives") or []:
        if isinstance(cr, dict):
            yield " ".join(str(cr.get(k) or "") for k in ("headline", "text", "media"))


def check(cfg: Dict[str, Any], people: List[Dict[str, Any]], brief_text: str = "") -> Dict[str, Any]:
    """{fit: good|caution|poor, warnings: [{code, text, do_instead}]} from the config, the brief and the people."""
    warnings: List[Dict[str, str]] = []
    segs = Counter(str(p.get("segment") or "").strip() for p in people if str(p.get("segment") or "").strip())
    thin = sorted(s for s, n in segs.items() if n < MIN_SEGMENT)
    if len(segs) >= 2 and thin:
        warnings.append({"code": "small_segments",
                         "text": f"{len(thin)} of {len(segs)} segments have fewer than {MIN_SEGMENT} people "
                                 f"({', '.join(thin[:4])}{'...' if len(thin) > 4 else ''}).",
                         "do_instead": "Compare segments only after adding people, or read their results as anecdotes."})
    countries = [str(p.get("country") or "").strip().lower() for p in people if str(p.get("country") or "").strip()]
    if countries:
        less = [c for c in countries if c not in WELL_COVERED]
        if len(less) * 2 >= len(countries):
            top = [c.title() for c, _ in Counter(less).most_common(3)]
            warnings.append({"code": "less_covered_markets",
                             "text": f"{round(100 * len(less) / len(countries))}% of the people are in markets the models "
                                     f"represent less well ({', '.join(top)}).",
                             "do_instead": "Ground the people in local customer data (intake) and plan a small real test "
                                           "in that market."})
    text = " ".join([brief_text, *_texts(cfg)])
    hits = sorted({m.group(0).lower() for m in SENSITIVE.finditer(text)})
    if hits:
        warnings.append({"code": "sensitive_topic",
                         "text": f"The brief touches identity or sensitive topics ({', '.join(hits[:5])}). Models flatten "
                                 "and misportray identity groups.",
                         "do_instead": "Use the panel to find questions to ask, then ask real people from those groups."})
    if NEW_CATEGORY.search(text):
        warnings.append({"code": "new_category",
                         "text": "The brief describes a product new to the world. Simulated panels fail most where "
                                 "people have no past behaviour to draw on.",
                         "do_instead": "Use the run for objections and wording; size demand with real people."})
    if any(cfg.get(k) for k in ("targets", "target", "forecast", "predict", "spend", "budget")):
        warnings.append({"code": "absolute_numbers",
                         "text": "The config asks for targets, forecasts or budgets. Simulated people say yes far more "
                                 "often than real ones (our bench: 66% predicted vs 43% real).",
                         "do_instead": "Read which option wins, not the rates; calibrate with real answers before "
                                       "forecasting."})
    fit = "good" if not warnings else "poor" if len(warnings) >= 3 else "caution"
    return {"fit": fit, "warnings": warnings,
            "good_uses": "screening ideas, pretesting wording, finding objections, ranking options",
            "note": "Shown before spending. It never blocks a run."}


def lines(result: Dict[str, Any]) -> List[str]:
    """Plain lines for the CLI log."""
    if not result.get("warnings"):
        return ["fit check: no known weak spots for this test"]
    return [f"fit check ({result['fit']}): {w['text']} {w['do_instead']}" for w in result["warnings"]]
