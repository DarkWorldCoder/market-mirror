"""Evidence-led campaign planning shared by the CLI, API, and agent tools.

The output is a draft decision and executable experiment specs, not a claim
that a channel or audience has been validated in the real world.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


CHANNELS = ("search", "organic", "paid_social", "email", "sales", "referral")
METRICS = {
    "search": ("convert_yes", "search_content", "qualified_visit_rate"),
    "organic": ("convert_yes", "organic_content", "engaged_visit_rate"),
    "paid_social": ("expected_ctr", "ad", "qualified_click_rate"),
    "email": ("click_rate", "nurture", "qualified_click_rate"),
    "sales": ("pitch_score", "sales_outreach", "positive_reply_rate"),
    "referral": ("convert_yes", "referral", "referral_signup_rate"),
}


def _evidence(research: Any) -> List[Dict[str, Any]]:
    if isinstance(research, dict):
        candidates = (research.get("voices") or research.get("quotes") or
                      research.get("items") or research.get("findings") or [])
    elif isinstance(research, list):
        candidates = research
    else:
        candidates = []
    out = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        url = item.get("url") or item.get("source_url")
        if not url:
            continue
        out.append({"text": str(item.get("text") or item.get("quote") or item.get("title") or "")[:300],
                    "source": str(url), "date": item.get("date") or item.get("at"),
                    "market": item.get("market") or item.get("country"),
                    "quality": item.get("quality") or "unverified_public_feedback"})
    return out[:20]


def build(profile: Dict[str, Any], goal: str, budget: Dict[str, Any], channels: Optional[List[str]] = None,
          research: Any = None, project_id: str = "") -> Dict[str, Any]:
    if not isinstance(profile, dict) or not (profile.get("name") or profile.get("what_it_does")):
        raise ValueError("product profile needs a name or what_it_does")
    if not str(goal or "").strip():
        raise ValueError("goal is required")
    if not isinstance(budget, dict):
        raise ValueError("budget must be an object with amount and currency")
    try:
        amount = float(budget.get("amount"))
    except (TypeError, ValueError):
        raise ValueError("budget.amount must be a non-negative number") from None
    if amount < 0:
        raise ValueError("budget.amount must be a non-negative number")
    if round(amount, 2) != amount:
        raise ValueError("budget.amount supports at most two decimal places")
    currency = str(budget.get("currency") or "USD").upper()
    selected = channels if channels is not None else (profile.get("channels") or ["search", "organic", "paid_social", "email", "sales", "referral"])
    selected = list(dict.fromkeys(str(c).strip().lower() for c in selected))
    aliases = {"google": "search", "google_ads": "search", "search_ads": "search",
               "seo": "organic", "content": "organic", "website": "organic", "reddit": "organic",
               "social": "paid_social", "ads": "paid_social", "instagram": "paid_social",
               "facebook": "paid_social", "tiktok": "paid_social", "linkedin": "paid_social",
               "x": "paid_social", "twitter": "paid_social", "newsletter": "email",
               "crm": "sales", "outbound": "sales", "partners": "referral"}
    selected = list(dict.fromkeys(aliases.get(c, c) for c in selected))
    unknown = [c for c in selected if c not in CHANNELS]
    if unknown and channels is None:
        selected = [c for c in selected if c in CHANNELS]
    if not selected:
        raise ValueError("channels must include one or more of: " + ", ".join(CHANNELS))
    if unknown and channels is not None:
        raise ValueError("unsupported channels: " + ", ".join(unknown))

    people = profile.get("for_whom") or []
    audiences = [{"segment": str(p.get("segment")), "market": p.get("country_hint") or None,
                  "job_to_be_done": p.get("job_to_be_done") or None, "basis": "product_profile"}
                 for p in people if isinstance(p, dict) and p.get("segment")]
    gaps = list(profile.get("unknowns") or [])
    if unknown:
        gaps.append("Unmapped profile channels omitted: " + ", ".join(unknown))
    if not audiences:
        gaps.append("Target audience is absent from the product profile")
    evidence = _evidence(research)
    if not evidence:
        gaps.append("No cited public feedback supplied; positioning is based only on the product profile")
    offer = str(profile.get("offer") or profile.get("one_liner") or profile.get("what_it_does") or "").strip()
    differentiators = [str(x) for x in (profile.get("differentiators") or []) if x]
    proofs = [str(x) for x in (profile.get("proofs") or []) if x]
    if not proofs:
        gaps.append("No substantiated proof supplied for campaign claims")
    aud_name = audiences[0]["segment"] if audiences else "the target buyer"
    angle_a = offer
    angle_b = (f"{differentiators[0]} — {offer}" if differentiators else f"{offer} for {aud_name}")
    exposure = {"search": "search results for a stated buyer query", "organic": "unpaid social or article feed",
                "paid_social": "paid social feed", "email": "opted-in lifecycle inbox",
                "sales": "permission-based sales conversation", "referral": "customer referral invitation"}
    tests = []
    cents = round(amount * 100)
    allocations = [(cents // len(selected) + (1 if i < cents % len(selected) else 0)) / 100
                   for i in range(len(selected))]
    for i, channel in enumerate(selected):
        metric, kind, actual_metric = METRICS[channel]
        tests.append({"type": kind, "name": f"{channel} positioning", "variants": [
            {"id": "control", "text": angle_a}, {"id": "treatment", "text": angle_b}],
            "audience": {"segments": [a["segment"] for a in audiences],
                         "countries": [a["market"] for a in audiences if a["market"]]},
            "exposure_context": exposure[channel], "metric": metric,
            "actual_outcome_metric": actual_metric,
            "budget": {"amount": allocations[i], "currency": currency},
            "hypothesis": f"The differentiated message improves {metric} for {aud_name}.",
            "next_real_world_test": f"Run a controlled {channel} A/B test with the same audience and exposure window; measure {actual_metric} and record assignment.",
            "evidence_refs": [e["source"] for e in evidence[:3]], "status": "draft"})
    return {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
            "project_id": project_id or None, "product": profile.get("name") or "Unnamed product",
            "goal": goal.strip(), "budget": {"amount": amount, "currency": currency,
                                                 "period": budget.get("period") or "test period",
                                                 "assumption": "equal draft allocation across selected channels"},
            "audiences": audiences, "positioning": {"control": angle_a, "treatment": angle_b,
                                                     "proofs": proofs, "differentiators": differentiators,
                                                     "claim_status": "product_supplied_unverified"},
            "channels": [{"name": c, "allocation": allocations[i], "simulated_metric": METRICS[c][0],
                          "actual_outcome_metric": METRICS[c][2],
                          "reason": "selected by user" if channels is not None else "profile or default candidate"} for i, c in enumerate(selected)],
            "funnel": [{"stage": "exposure", "metric": "eligible exposures"},
                       {"stage": "engagement", "metric": "qualified engagement"},
                       {"stage": "conversion", "metric": goal.strip()},
                       {"stage": "retention", "metric": "repeat use or qualified follow-up"}],
            "measurement": {"unit": "person or account", "assignment": "random control/treatment allocation within each audience and channel",
                            "holdout": "retain a real-world holdout for calibration", "primary_metric": goal.strip(),
                            "guardrails": ["spend", "unsubscribes", "negative feedback"],
                            "record": ["variant", "audience", "market", "source", "date", "exposure", "outcome"]},
            "test_specs": tests, "evidence": evidence, "unknowns": list(dict.fromkeys(gaps)),
            "interpretation": "Draft hypotheses; simulated responses are exploratory until checked against held-out real outcomes."}


def save(plan: Dict[str, Any], path: str) -> str:
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    return path
