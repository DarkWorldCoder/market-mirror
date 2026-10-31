"""Say vs do: what simulated people said next to what the same people would likely do, under fixed rules.

The most common objection to synthetic panels is the say-do gap: people (and models playing them) say yes far more
often than they act. The feed test already applies three rules to clickers on the landing page, from each person's
decision card (persona_planner's BDE card):

1. wallet: the price is above what this person comfortably spends (tighter at the end of the month);
2. dealbreaker: the page shows something on their own list of dealbreakers or stoppers;
3. polite yes: a person who agrees easily (high acquiescence) backs out at a payment or card step about 45% of the
   time.

`split` applies the same rules to stated yeses in the survey and the pitch, so reports show "stated" next to "after
say-do rules". The rules are assumptions written down in code, not measurements; the report says so.

Stdlib only and no package-relative imports: the CLI loads this file by path.
"""

import random
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

BASIS = ("assumption: fixed rules from each person's decision card (budget, dealbreakers, polite yes-sayers backing "
         "out at payment); not measured")
_PRICE = re.compile(r"(?:[$€£₹]|rs\.?|npr|inr|usd|eur|gbp|php|₱)\s*\d[\d,]*(?:\.\d+)?(?:\s*[kK])?"
                    r"|\d[\d,]*(?:\.\d+)?\s*(?:[kK]\b)?\s*(?:usd|eur|gbp|npr|inr|php|rupees|dollars|euros)", re.I)


def parse_amount(text: Any) -> Optional[float]:
    """The number in a money string ('NPR 2,000', '$120/mo', '1.5k'); same rule as persona_planner."""
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return float(text) if text >= 0 else None
    s = str(text or "").strip()
    if not s:
        return None
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*([kK])?", s)
    if not m:
        return None
    try:
        val = float(m.group(1).replace(",", ""))
        if m.group(2):
            val *= 1000.0
        return val
    except ValueError:
        return None


def price_in(text: str) -> str:
    """The first price written in an offer ('Pro plan, $9/month' -> '$9'); '' when there is none."""
    m = _PRICE.search(str(text or ""))
    return m.group(0).strip() if m else ""


def friction(person: Dict[str, Any], landing: Dict[str, Any], rng: random.Random,
             fx: Optional[Dict[str, float]] = None) -> Optional[Tuple[str, str]]:
    """(gate, reason) when this person would drop off at the commitment step, else None. landing: {price, shows,
    form_fields}. fx: emotion couplings ("wallet" scales the spend threshold, "backout" the back-out chance), 1.0
    unless emotions are "on". Draws one random number only for a polite yes-sayer facing a commitment."""
    fx = fx or {}
    bde = person.get("bde") if isinstance(person.get("bde"), dict) else {}
    b_bg = bde.get("background") if isinstance(bde.get("background"), dict) else {}
    b_dp = bde.get("decision_procedure") if isinstance(bde.get("decision_procedure"), dict) else {}
    b_ev = bde.get("evaluation") if isinstance(bde.get("evaluation"), dict) else {}

    price_str = str(landing.get("price") or "free").strip()
    price_num = parse_amount(price_str) if price_str.lower() not in ("free", "0", "$0", "rs 0") else 0.0
    budget_num = b_ev.get("discretionary_budget_num")
    if budget_num is None:
        budget_num = parse_amount(b_ev.get("monthly_discretionary"))

    payday = str(person.get("payday_status") or "mid_month").lower()
    if price_num and budget_num and budget_num > 0:
        ratio = price_num / budget_num
        # Compare only when both numbers are in the same currency order-of-magnitude
        if 0.15 <= ratio <= 25.0:
            threshold = 0.55 if payday == "end_of_month_tight" else (0.95 if payday == "just_paid" else 0.80)
            threshold *= fx.get("wallet", 1.0)
            if ratio > threshold:
                disc_label = b_ev.get("monthly_discretionary") or str(budget_num)
                return ("wallet_limit", f"price ({price_str}) exceeds comfortable discretionary budget ({disc_label})")

    page_blob = " ".join([
        str(landing.get("shows") or ""),
        price_str,
        " ".join(str(f) for f in (landing.get("form_fields") or [])),
    ]).lower()
    dealbreakers = [str(x).strip() for x in (b_ev.get("dealbreakers") or []) + (b_dp.get("stoppers") or []) if str(x).strip()]
    for db in dealbreakers:
        db_low = db.lower()
        tokens = [w for w in re.findall(r"[a-z0-9]+", db_low) if len(w) > 3]
        if (db_low in page_blob) or (tokens and all(t in page_blob for t in tokens[:2])):
            return ("dealbreaker", f"triggered dealbreaker: {db}")

    acq = str(b_bg.get("acquiescence") or "").strip().lower()
    says_do = str(b_bg.get("says_vs_does") or "").strip()
    has_commitment = (price_num and price_num > 0) or any(
        k in page_blob for k in ("card", "credit", "payment", "subscribe", "auto-renew", "phone")
    )
    if acq == "high" and has_commitment and rng.random() < min(0.9, 0.45 * fx.get("backout", 1.0)):
        detail = f" ({says_do[:90]})" if says_do else ""
        return ("say_vs_do_gap", f"polite interest, but backed out at commitment step{detail}")

    return None


def split(rows: Sequence[Dict[str, Any]], people: Dict[Any, Dict[str, Any]], offer: str = "", price: str = "",
          seed: int = 7) -> Dict[str, Any]:
    """rows: [{agent_id, stated: yes|maybe|no}]. Stated yes share next to the share left after the say-do rules,
    with how many each rule removed and a few reasons. Deterministic for a seed (one draw per person)."""
    stated = [r for r in rows if str(r.get("stated") or "").lower() in ("yes", "maybe", "no")]
    n = len(stated)
    if not n:
        return {}
    page = {"price": price or price_in(offer) or "free", "shows": offer}
    yes = [r for r in stated if str(r["stated"]).lower() == "yes"]
    dropped: Dict[str, int] = {}
    reasons: List[str] = []
    kept = 0
    carded = 0
    for r in yes:
        person = people.get(r["agent_id"]) or people.get(str(r["agent_id"])) or {}
        carded += int(isinstance(person.get("bde"), dict))
        try:
            rid = int(r["agent_id"])
        except (TypeError, ValueError):
            rid = sum(map(ord, str(r["agent_id"])))
        hit = friction(person, page, random.Random(seed * 1009 + rid))
        if hit:
            dropped[hit[0]] = dropped.get(hit[0], 0) + 1
            if len(reasons) < 3:
                reasons.append(hit[1])
        else:
            kept += 1
    return {"n": n, "stated_yes_pct": round(100.0 * len(yes) / n, 1), "after_rules_yes_pct": round(100.0 * kept / n, 1),
            "dropped": dropped, "reasons": reasons, "yes_with_a_decision_card": carded, "price_used": page["price"],
            "basis": BASIS}
