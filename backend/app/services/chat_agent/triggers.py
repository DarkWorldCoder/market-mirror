"""Automatic triggers: what an uploaded file or a phrase in the message should start.

* GA4 / PostHog columns -> analytics_audience before any personas (free, runs at once)
* ad export columns -> ads_import (free, runs at once)
* real answers (segment / y columns) with a selected run -> calibrate (free, runs at once)
* reviews or transcripts -> ask first, then intake (real_split first when there is an outcome column)
* images or videos -> offer creative_check
* "before launch" -> offer to lock a forecast

Detection reads only the header row (or the file name), never sends anything anywhere.
"""
from __future__ import annotations

import csv
import io
import os
import re
from typing import Any, Dict, List, Optional

ANALYTICS_DIMS = {"country", "city", "region", "useragebracket", "age", "agebracket", "usergender", "gender",
                  "devicecategory", "device category", "device", "sessiondefaultchannelgroup", "default channel group",
                  "session default channel group", "first user default channel group", "newvsreturning",
                  "$geoip_country_name", "$geoip_city_name", "$device_type", "$initial_utm_source", "properties.$geoip_country_name"}
ANALYTICS_METRICS = {"activeusers", "active users", "users", "total users", "new users", "newusers", "sessions",
                     "keyevents", "key events", "conversions", "persons", "count()", "unique users", "engaged sessions"}
AD_NAMES = {"ad name", "ad_name", "campaign name", "campaign", "campaign_name", "ad set name", "ad group", "ad group name",
            "adset name", "creative", "headline", "ad"}
AD_METRICS = {"impressions", "clicks", "amount spent", "amount spent (usd)", "spend", "cost", "ctr", "link clicks",
              "results", "conversions", "cpc", "cpm", "reach"}
TEXT_COLS = {"review", "reviews", "comment", "comments", "feedback", "verbatim", "transcript", "notes", "note", "body",
             "text", "content", "response", "answer", "message", "nps comment", "why"}
OUTCOME_COLS = {"converted", "purchased", "bought", "y", "outcome", "churned", "would_buy", "would buy", "won", "renewed"}
ANSWER_COLS = {"segment", "country", "gender", "age"}
MEDIA = re.compile(r"\.(png|jpe?g|webp|gif|mp4|mov|webm|m4v)$", re.I)
TRANSCRIPT = re.compile(r"\.(vtt|srt|txt)$", re.I)
LAUNCH = re.compile(r"\b(before (?:we |the |our |i )?launch|pre-?launch|ahead of (?:the )?launch|launching (?:next|this) (?:week|month))\b", re.I)


def _norm(h: str) -> str:
    return re.sub(r"\s+", " ", str(h or "").strip().strip('"').lower())


def headers(text: str) -> List[str]:
    first = next((line for line in str(text or "").splitlines() if line.strip() and not line.startswith("#")), "")
    if not first:
        return []
    try:
        dialect = csv.Sniffer().sniff(first, delimiters=",;\t")
        row = next(csv.reader(io.StringIO(first), dialect))
    except (csv.Error, StopIteration):
        row = first.split(",")
    return [_norm(h) for h in row if _norm(h)]


def detect_file(name: str, text: str) -> Dict[str, Any]:
    """{kind, headers, outcome}: analytics | ads | answers | reviews | transcript | media | other."""
    lower = str(name or "").lower()
    if MEDIA.search(lower):
        return {"kind": "media", "headers": []}
    if lower.endswith((".vtt", ".srt")):
        return {"kind": "transcript", "headers": []}
    cols = headers(text) if lower.endswith((".csv", ".tsv")) else []
    if not cols:
        if TRANSCRIPT.search(lower) and re.search(r"^\s*[A-Z][\w .'-]{0,30}:\s", str(text or ""), re.M):
            return {"kind": "transcript", "headers": []}
        return {"kind": "other", "headers": []}
    s = set(cols)
    outcome = sorted(s & OUTCOME_COLS)
    if (s & ANALYTICS_DIMS) and (s & ANALYTICS_METRICS):
        return {"kind": "analytics", "headers": cols}
    if (s & AD_NAMES) and (s & AD_METRICS):
        return {"kind": "ads", "headers": cols}
    if ("y" in s or "would_buy" in s) and len(s & ANSWER_COLS) >= 2:
        return {"kind": "answers", "headers": cols, "outcome": outcome}
    if s & TEXT_COLS:
        return {"kind": "reviews", "headers": cols, "outcome": outcome}
    return {"kind": "other", "headers": cols}


def plan(files: List[Dict[str, Any]], message: str, run: Optional[str], latest_run: Optional[str]) -> Dict[str, Any]:
    """{auto: [{tool, args, reason}], offers: [text], notes: [text]} for saved uploads [{name, path, text}]."""
    auto, offers, notes = [], [], []
    for f in files:
        found = detect_file(f["name"], f.get("text", ""))
        f["detected"] = found["kind"]
        path = f.get("path")
        if found["kind"] == "analytics":
            auto.append({"tool": "analytics_audience", "args": {"files": [path]},
                         "reason": f"{f['name']} looks like a GA4 or PostHog export: sizing the audience from it first."})
        elif found["kind"] == "ads":
            stem = os.path.splitext(path)[0]
            auto.append({"tool": "ads_import", "args": {"file": path, "out": stem + "_seed.md"},
                         "reason": f"{f['name']} looks like an ad export: importing it as past ads and benchmarks."})
        elif found["kind"] == "answers":
            if run:
                auto.append({"tool": "calibrate", "args": {"run": run, "real_csv": path},
                             "reason": f"{f['name']} looks like real answers: checking {run} against them."})
            elif latest_run:
                offers.append(f"Check {latest_run} against the real answers in {f['name']}")
        elif found["kind"] in ("reviews", "transcript"):
            if found.get("outcome"):
                offers.append(f"Split {f['name']} first (it has an outcome column), then turn part of it into grounded personas")
            else:
                offers.append(f"Turn {f['name']} into grounded personas")
            notes.append(f"{f['name']} looks like customer material ({found['kind']}). Ask before using it: intake "
                         f"makes model calls{'; run real_split first because it has an outcome column' if found.get('outcome') else ''}. Path: {path}")
        elif found["kind"] == "media":
            offers.append(f"Check {f['name']} before any buyer sees it")
            notes.append(f"{f['name']} is an image or video. Offer creative_check. Path: {path}")
        if path and found["kind"] not in ("analytics", "ads"):
            notes.append(f"Uploaded {f['name']} is saved at {path}")
    for url in re.findall(r"\S+\.(?:png|jpe?g|webp|gif|mp4|mov|webm)\b", message or "", re.I)[:4]:
        offers.append(f"Check {os.path.basename(url)} before any buyer sees it")
    if LAUNCH.search(message or "") and (run or latest_run):
        offers.append(f"Lock a forecast for {run or latest_run} before launch")
        notes.append("The user mentions a launch: offer `cli` with args [\"forecast\", \"lock\", \"--run-dir\", "
                     f"\"mirofish_runs/{run or latest_run}\"] so the forecast is timestamped before real results exist.")
    return {"auto": auto, "offers": list(dict.fromkeys(offers))[:4], "notes": notes}
