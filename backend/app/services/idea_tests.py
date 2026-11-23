"""Two more things to put in front of simulated people: a product concept (or pack) and a public statement.

Concept screen: every exposure shows one concept in its own call, never side by side, as a monadic concept test
does, so there is no answer-order or position effect (vision shoppers favoured the first option, arXiv 2611.09977).
The person gives an honest chance of buying it within a month at the stated price. Kantar, NIQ BASES and Ipsos sell this kind
of AI concept screen; their accuracy figures are self-reported.

Statement test: each person reads one statement (a price rise, a recall, layoffs, a policy change, an apology) as
one of the audiences that receive it, and says how much they trust the brand afterwards, what they would do, and
the exact words that bother them most. LLM predictions of survey-experiment results correlate well with real ones
(r = 0.85 over 70 US experiments) but overstate effect sizes, so gaps between statements read as directions.

Both return one score per person in [0, 1] plus the person's own words; an answer without a valid score raises,
so a failed answer is never counted as a zero.
"""

from __future__ import annotations

import math
from typing import Any, Dict

from .gtm_suite import person_card

ACTIONS = ("nothing", "talk_about_it", "complain", "share_criticism", "stop_buying")


def concept_prompt(person: Dict[str, Any], concept: str, brand: str = "") -> str:
    return (f"WHO YOU ARE\n{person_card(person)}\n\nYou are shown this new product idea{(' from ' + brand) if brand else ''}. "
            f"It is not on sale yet.\n\n{concept}\n\nAnswer as yourself. Most new product ideas do not get bought, and "
            "saying you might is not the same as paying.\n"
            'Return JSON: {"p_buy": 0.0-1.0 (your honest chance of buying it in the next month at the stated price if it '
            'were where you usually shop), "first_impression": "your first thought in your own words", '
            '"unclear": "what you do not understand, or empty", "objection": "what would stop you, or empty", '
            '"instead": "what you buy or use today instead"}')


def statement_prompt(person: Dict[str, Any], statement: str, brand: str = "", audience: str = "") -> str:
    role = f" You receive it as one of these people: {audience}." if audience else ""
    return (f"WHO YOU ARE\n{person_card(person)}\n\n{brand or 'A company'} has just published this statement.{role}\n\n"
            f"{statement}\n\nReact the way you really would. Most statements change little.\n"
            'Return JSON: {"trust_after": 0.0-1.0 (how much you trust them after reading it: 0 not at all, 1 completely), '
            '"feeling": "how it makes you feel, in your own words", '
            f'"would_do": "{"|".join(ACTIONS)}", '
            '"riskiest_phrase": "the exact words from the statement that bother you most, copied exactly, or empty", '
            '"missing": "what you wanted to hear and did not, or empty"}')


def _prob(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise RuntimeError(f"Model returned an invalid {name}. Retry the failed exposure.")
    return float(value)


def _text(value: Any, limit: int = 600) -> str:
    return str(value or "").strip()[:limit]


def read_concept(answer: Dict[str, Any]) -> Dict[str, Any]:
    """One concept answer -> {score, reaction, objection, unclear, instead}."""
    score = _prob(answer.get("p_buy"), "purchase chance")
    return {"score": score, "reaction": _text(answer.get("first_impression")),
            "objection": _text(answer.get("objection") or answer.get("unclear")),
            "unclear": _text(answer.get("unclear")), "instead": _text(answer.get("instead"), 200)}


def read_statement(answer: Dict[str, Any], statement: str) -> Dict[str, Any]:
    """One statement answer -> {score, reaction, objection, would_do, riskiest_phrase}. The riskiest phrase is kept
    only when it really is in the statement (case-insensitive), so a quote is never invented."""
    score = _prob(answer.get("trust_after"), "trust score")
    action = _text(answer.get("would_do"), 40).lower()
    phrase = _text(answer.get("riskiest_phrase"), 300).strip(" \"'“”")
    if phrase and phrase.lower() not in statement.lower():
        phrase = ""
    return {"score": score, "reaction": _text(answer.get("feeling")),
            "objection": _text(answer.get("missing")) or (f'"{phrase}"' if phrase else ""),
            "would_do": action if action in ACTIONS else "", "riskiest_phrase": phrase}
