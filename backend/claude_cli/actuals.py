"""Normalize user-provided marketing and sales CSV/JSON exports with provenance."""

from __future__ import annotations

import csv
import json
import os
from datetime import date
from typing import Any, Dict, List, Optional

SOURCE_TYPES = ("ads", "email", "website", "crm", "survey")
DEFAULT_MAP = {"date": "date", "market": "market", "campaign": "campaign", "variant": "variant",
               "audience": "audience", "impressions": "impressions", "clicks": "clicks", "spend": "spend",
               "conversions": "conversions", "sends": "sends", "opens": "opens", "visits": "visits",
               "leads": "leads", "opportunities": "opportunities", "deals": "deals", "responses": "responses",
               "positive_responses": "positive_responses", "referrals": "referrals", "signups": "signups"}
COUNT_FIELDS = set(DEFAULT_MAP) - {"date", "market", "campaign", "variant", "audience", "spend"}
NUM_FIELDS = COUNT_FIELDS | {"spend"}
REQUIRED_ANY = {"ads": ("impressions", "clicks", "conversions"), "email": ("sends", "opens", "clicks"),
                "website": ("visits", "signups", "conversions"), "crm": ("leads", "opportunities", "deals", "positive_responses"),
                "survey": ("responses", "positive_responses", "conversions")}


def _rows(path: str) -> List[Dict[str, Any]]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        if path.lower().endswith(".csv"):
            return list(csv.DictReader(f))
        if path.lower().endswith(".json"):
            obj = json.load(f)
            if isinstance(obj, dict):
                obj = obj.get("rows") or obj.get("data") or []
            if not isinstance(obj, list) or any(not isinstance(row, dict) for row in obj):
                raise ValueError("JSON export must be an array of objects or {rows: [...]} ")
            return obj
    raise ValueError("export must be a .csv or .json file")


def normalize(path: str, source_type: str, mapping: Optional[Dict[str, str]] = None,
              source_name: str = "", market: str = "", date_hint: str = "", quality: str = "") -> Dict[str, Any]:
    source_type = str(source_type or "").lower().strip()
    if source_type not in SOURCE_TYPES:
        raise ValueError("source_type must be one of: " + ", ".join(SOURCE_TYPES))
    if not os.path.isfile(path):
        raise ValueError(f"export file not found: {path}")
    mapping = {**DEFAULT_MAP, **(mapping or {})}
    if any(k not in DEFAULT_MAP for k in mapping):
        raise ValueError("mapping contains unsupported normalized fields")
    if date_hint:
        date.fromisoformat(date_hint)
    rows = _rows(path)
    observations, errors = [], []
    for line, row in enumerate(rows, 2):
        row_date = str(row.get(mapping["date"]) or "")[:10]
        row_market = str(row.get(mapping["market"]) or "").strip()
        if date_hint and row_date and row_date != date_hint:
            errors.append({"row": line, "field": "date", "error": "row date conflicts with date hint"})
            continue
        if market and row_market and row_market.casefold() != market.casefold():
            errors.append({"row": line, "field": "market", "error": "row market conflicts with market hint"})
            continue
        item: Dict[str, Any] = {"source_type": source_type, "source": source_name or os.path.basename(path),
                                "source_file": os.path.abspath(path), "row": line,
                                "date": row_date or date_hint,
                                "market": row_market or market,
                                "quality": quality or "user_export_unverified"}
        for k in ("campaign", "variant", "audience"):
            item[k] = str(row.get(mapping[k]) or "")
        if item["date"]:
            try:
                date.fromisoformat(item["date"])
            except ValueError:
                errors.append({"row": line, "field": "date", "error": "expected ISO date YYYY-MM-DD"})
                continue
        else:
            errors.append({"row": line, "field": "date", "error": "date or date_hint required"})
            continue
        if not item["market"]:
            errors.append({"row": line, "field": "market", "error": "market or market hint required"})
            continue
        bad = False
        for k in NUM_FIELDS:
            raw = row.get(mapping[k])
            if raw is None or str(raw).strip() == "":
                continue
            try:
                n = float(str(raw).replace(",", "").replace("$", ""))
                if n < 0 or (k in COUNT_FIELDS and not n.is_integer()):
                    raise ValueError()
                item[k] = int(n) if k in COUNT_FIELDS else n
            except (TypeError, ValueError):
                errors.append({"row": line, "field": k, "error": "expected non-negative count or amount"})
                bad = True
        if bad:
            continue
        if not any(k in item for k in REQUIRED_ANY[source_type]):
            errors.append({"row": line, "field": "metrics", "error": "no outcome or exposure metric for source type"})
            continue
        if item.get("clicks", 0) > item.get("impressions", float("inf")) or item.get("opens", 0) > item.get("sends", float("inf")):
            errors.append({"row": line, "field": "metrics", "error": "outcome exceeds exposure count"})
            continue
        observations.append(item)
    return {"schema_version": 1, "source_type": source_type, "source_file": os.path.abspath(path),
            "observations": observations, "validation_errors": errors,
            "summary": {"rows_read": len(rows), "rows_valid": len(observations),
                        "rows_invalid": len(rows) - len(observations)},
            "use": "Observed outcomes for backtests and calibration; validate attribution and holdout assignment before predictive claims."}


def ad_backtest_table(result: Dict[str, Any]) -> Dict[str, Any]:
    """Aggregate normalized ad observations into the legacy creative backtest contract."""
    if result.get("source_type") != "ads" or not isinstance(result.get("observations"), list):
        raise ValueError("backtest needs normalized ads observations")
    groups: Dict[str, Dict[str, Any]] = {}
    for row in result["observations"]:
        name = row.get("variant") or row.get("campaign")
        if not name or "impressions" not in row or "clicks" not in row:
            continue
        item = groups.setdefault(name, {"key": name, "impressions": 0, "clicks": 0,
                                        "conversions": 0, "sources": [], "markets": [], "dates": []})
        for field in ("impressions", "clicks", "conversions"):
            item[field] += row.get(field, 0)
        for field, dest in (("source", "sources"), ("market", "markets"), ("date", "dates")):
            if row.get(field) and row[field] not in item[dest]:
                item[dest].append(row[field])
    if not groups:
        raise ValueError("normalized ads need a variant or campaign plus impressions and clicks")
    for item in groups.values():
        impressions, clicks = item["impressions"], item["clicks"]
        item["ctr"] = round(100 * clicks / impressions, 4) if impressions else 0.0
        item["conv_rate"] = round(100 * item["conversions"] / clicks, 4) if clicks else 0.0
    return {"tables": {"ad": list(groups.values())}, "source_type": "ads",
            "quality": "user_export_unverified", "source_file": result.get("source_file")}


def save(result: Dict[str, Any], path: str) -> str:
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return path
