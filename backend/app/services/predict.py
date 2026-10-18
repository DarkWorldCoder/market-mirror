"""Predictions that say what they rest on, and a store that learns from every real result.

The calibration store (backend/uploads/calibration_store.json) keeps paired observations per brand and metric:
what the simulation said and what reality said (from `backtest`, `calibrate`, real email stats, a real survey).
`fit()` turns them into a scale factor with an uncertainty; `predict()` applies it to a new simulated number and
returns an interval plus the probability of clearing a target. Without real pairs the prediction is the raw
simulated number with a wide prior interval, labelled "uncalibrated". `forecast()` projects reach and adoption
over 30/90 days from a spend, the ad economics and the word of mouth seen in the rounds (a K-factor from shares
and quotes per brand post). Everything here is arithmetic; no model calls.
"""

import json
import math
import os
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

from ..config import Config

STORE = os.path.join(Config.UPLOAD_FOLDER, "calibration_store.json")
PRIOR_SPREAD = {"ctr": 0.6, "would_convert": 0.7, "open_rate": 0.5, "click_rate": 0.6, "cpl": 0.7, "conversion_after_click": 0.7}


# --------------------------------------------------------------------------
# Store
# --------------------------------------------------------------------------

def load_store(path: Optional[str] = None) -> Dict[str, Any]:
    path = path or STORE
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"pairs": []}


def save_store(store: Dict[str, Any], path: Optional[str] = None) -> None:
    path = path or STORE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)


def add_pairs(brand: str, metric: str, pairs: List[Dict[str, Any]], source: str, path: Optional[str] = None) -> int:
    """pairs: [{"sim": x, "real": y, "label": "..."}] -> stored with brand, metric, source and time."""
    store = load_store(path)
    n = 0
    for p in pairs:
        try:
            sim, real = float(p["sim"]), float(p["real"])
        except (KeyError, TypeError, ValueError):
            continue
        store["pairs"].append({"brand": brand, "metric": metric, "sim": sim, "real": real, "label": str(p.get("label") or "")[:80],
                               "source": source, "at": time.strftime("%Y-%m-%d")})
        n += 1
    save_store(store, path)
    return n


# --------------------------------------------------------------------------
# Fit and predict
# --------------------------------------------------------------------------

def fit(brand: str, metric: str, store: Optional[Dict[str, Any]] = None, path: Optional[str] = None) -> Dict[str, Any]:
    """Scale factor real/sim for a brand+metric (falls back to every brand for that metric), with its spread."""
    store = store or load_store(path)
    own = [p for p in store.get("pairs") or [] if p.get("metric") == metric and p.get("brand") == brand and p.get("sim")]
    pool = own or [p for p in store.get("pairs") or [] if p.get("metric") == metric and p.get("sim")]
    if not pool:
        return {"metric": metric, "n": 0, "factor": 1.0, "spread": PRIOR_SPREAD.get(metric, 0.7), "basis": "uncalibrated prior"}
    ratios = sorted(p["real"] / p["sim"] for p in pool if p["sim"] > 0)
    if not ratios:
        return {"metric": metric, "n": 0, "factor": 1.0, "spread": PRIOR_SPREAD.get(metric, 0.7), "basis": "uncalibrated prior"}
    med = ratios[len(ratios) // 2] if len(ratios) % 2 else (ratios[len(ratios) // 2 - 1] + ratios[len(ratios) // 2]) / 2
    logs = [math.log(r) for r in ratios if r > 0]
    sd = math.sqrt(sum((x - sum(logs) / len(logs)) ** 2 for x in logs) / max(1, len(logs) - 1)) if len(logs) > 1 else 0.35
    spread = max(0.15, min(1.0, sd + 0.6 / math.sqrt(len(ratios))))        # fewer pairs -> wider
    basis = f"calibrated on {len(pool)} real {'results' if len(pool) > 1 else 'result'} of {brand}" if own else \
        f"calibrated on {len(pool)} real results of other brands (no {brand} pairs yet)"
    return {"metric": metric, "n": len(pool), "factor": round(med, 3), "spread": round(spread, 3), "basis": basis,
            "sources": sorted({p.get("source") for p in pool})}


def predict(sim_value: float, metric: str, brand: str, target: Optional[float] = None, higher_is_better: bool = True,
            store: Optional[Dict[str, Any]] = None, path: Optional[str] = None) -> Dict[str, Any]:
    """Point estimate = sim x factor; interval = log-normal with the fitted spread; P(beats target)."""
    f = fit(brand, metric, store, path)
    point = sim_value * f["factor"]
    lo, hi = point * math.exp(-1.96 * f["spread"]), point * math.exp(1.96 * f["spread"])
    out = {"metric": metric, "simulated": round(sim_value, 3), "predicted": round(point, 3), "low": round(lo, 3), "high": round(hi, 3),
           "basis": f["basis"], "pairs": f["n"], "factor": f["factor"]}
    if target is not None and point > 0:
        z = (math.log(target) - math.log(point)) / f["spread"]
        p_above = 1 - _phi(z)
        out["target"] = target
        out["p_success"] = round(p_above if higher_is_better else 1 - p_above, 3)
    return out


def _phi(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def predict_run(summary: Dict[str, Any], feed_test: Dict[str, Any], brand: str, targets: Optional[Dict[str, float]] = None,
                email_test: Optional[Dict[str, Any]] = None, store: Optional[Dict[str, Any]] = None, path: Optional[str] = None) -> Dict[str, Any]:
    """Predictions for the headline numbers of a run: CTR per ad, CPL, would-convert, email click rate."""
    targets = targets or {}
    out: Dict[str, Any] = {"brand": brand, "predictions": []}
    per = ((feed_test or {}).get("summary") or {}).get("per_creative") or {}
    for cid, m in per.items():
        if m.get("expected_ctr") is not None:
            out["predictions"].append({"what": f"CTR of {cid}", **predict(float(m["expected_ctr"]), "ctr", brand, targets.get("ctr"), True, store, path)})
        pr = m.get("projection") or {}
        if pr.get("cpl"):
            out["predictions"].append({"what": f"cost per lead of {cid}", **predict(float(pr["cpl"]), "cpl", brand, targets.get("cpl"), False, store, path)})
    mk = (summary or {}).get("marketing") or {}
    o = mk.get("overall") or {}
    if o.get("convert_yes") is not None:
        out["predictions"].append({"what": "would convert (all audiences)", **predict(float(o["convert_yes"]), "would_convert", brand, targets.get("would_convert"), True, store, path)})
    for seg in (mk.get("by_segment") or [])[:6]:
        if seg.get("convert_yes") is not None:
            out["predictions"].append({"what": f"would convert: {seg.get('key')}", **predict(float(seg["convert_yes"]), "would_convert", brand, targets.get("would_convert"), True, store, path)})
    pe = ((email_test or {}).get("summary") or {}).get("per_email") or {}
    for eid, m in pe.items():
        if m.get("click_rate") is not None:
            out["predictions"].append({"what": f"click rate of email {eid}", **predict(float(m["click_rate"]), "click_rate", brand, targets.get("click_rate"), True, store, path)})
    out["calibrated"] = any(p["pairs"] for p in out["predictions"])
    out["note"] = ("Point estimates are the simulated numbers scaled by what reality showed before; intervals are 95% log-normal bands. "
                   if out["calibrated"] else "No real results stored for these metrics yet: intervals are wide priors; run backtest or calibrate to narrow them. ")
    return out


# --------------------------------------------------------------------------
# Forecast: reach and adoption over time
# --------------------------------------------------------------------------

def k_factor(feed_story: Dict[str, Any]) -> Dict[str, Any]:
    """Word of mouth from the rounds: shares + quotes per brand post, and how many people each reached."""
    posts = (feed_story or {}).get("brand_posts") or []
    if not posts:
        return {"k": 0.0, "basis": "no brand posts in the rounds"}
    spread = sum(len(p.get("quotes") or []) + (p.get("reposts") or 0) + 0.5 * len(p.get("comments") or []) for p in posts)
    reach = sum(p.get("reach_proxy") or 0 for p in posts) or 1
    k = round(min(2.0, spread / max(1, len(posts)) / 5.0), 3)             # per-post spread, scaled: 5 shares per post ~ K of 1
    return {"k": k, "posts": len(posts), "shares_quotes": round(spread, 1), "reach": reach,
            "basis": f"{round(spread, 1)} shares/quotes/comments across {len(posts)} brand posts"}


def forecast(spend: float, cpm: float, ctr_pct: float, conv_after_click_pct: float, k: float = 0.0, days: int = 90,
             churn_monthly_pct: float = 10.0, currency: str = "USD") -> Dict[str, Any]:
    """Daily spend -> impressions -> clicks -> conversions, plus viral extra adoption with decay, with monthly churn."""
    daily = spend / 30.0
    imps_day = daily / max(cpm, 0.01) * 1000
    clicks_day = imps_day * ctr_pct / 100
    conv_day = clicks_day * conv_after_click_pct / 100
    users, cum, rows = 0.0, 0.0, []
    viral_pool = 0.0
    for d in range(1, days + 1):
        new = conv_day + viral_pool
        viral_pool = new * k * 0.3                                           # each cohort brings k more over ~3 days
        users = users * (1 - churn_monthly_pct / 100 / 30) + new
        cum += new
        if d in (7, 14, 30, 60, 90) or d == days:
            rows.append({"day": d, "new_customers_cum": round(cum), "active_customers": round(users), "spend": round(daily * d, 2)})
    cac = round(spend * (days / 30) / cum, 2) if cum else None
    return {"days": days, "spend_total": round(daily * days, 2), "currency": currency, "impressions_per_day": round(imps_day),
            "clicks_per_day": round(clicks_day, 1), "conversions_per_day": round(conv_day, 2), "k_factor": k,
            "curve": rows, "customers_total": round(cum), "active_at_end": round(users), "cac": cac,
            "note": "a projection from one creative's expected CTR, the landing conversion and the word of mouth seen in the rounds; not a forecast of your real account"}


def forecast_run(feed_test: Dict[str, Any], feed_story: Dict[str, Any], spend: Optional[float] = None, days: int = 90) -> Optional[Dict[str, Any]]:
    summ = (feed_test or {}).get("summary") or {}
    per = summ.get("per_creative") or {}
    ranked = summ.get("ranked") or list(per)
    if not ranked:
        return None
    best = per.get(ranked[0]) or {}
    pr = best.get("projection") or {}
    lf = best.get("landing") or {}
    if not pr.get("cpm") or not (pr.get("budget") or spend):
        return None
    conv = lf.get("conversion_after_click")
    if conv is None:
        conv = 2.0                                                          # no landing data: a conservative default, flagged
    kf = k_factor(feed_story)
    out = forecast(float(spend or pr["budget"]), float(pr["cpm"]), float(best.get("expected_ctr") or 0), float(conv), kf["k"], days,
                   currency=pr.get("currency") or "USD")
    out["creative"] = ranked[0]
    out["word_of_mouth"] = kf
    if lf.get("conversion_after_click") is None:
        out["note"] += " Landing conversion assumed at 2% (no landing data)."
    return out
