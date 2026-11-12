"""Audience from web analytics: turn Google Analytics 4 or PostHog data into a persona spec.

Reads aggregate rows that a GA4 or PostHog export already has, or rows an agent pulled through the host's Google
Analytics or PostHog MCP server, and writes for the persona planner (`personas.json`):

  segments    one per top country (or acquisition channel), sized by its share of users, with that country's top
              cities, the age range most of its users fall in, the share of women, and what the analytics say about
              how they arrived and what they did (device, channel, new vs returning, key events per user) in `notes`
  population  per-country age and gender shares, so the planner's raking weights match the visitors

Rules:
- Aggregates only. Columns other than the known dimensions and metrics are never read, so a persons export that also
  carries emails or names does not pass them on.
- Nothing is invented. A dimension missing from the data stays unknown and its segment key is left out; "(not set)",
  "unknown" and "other" are counted and reported, never spread over the known values.
- No double counting across reports. Rows are grouped into tables by file and by the dimensions they carry (GA4
  exports one table per breakdown); each share comes from the largest table that has the dimensions it needs.
- GA4 age and gender come from Google signals and are thresholded, so they cover only part of the users. The report
  says how many users those shares rest on.
- Analytics describe who visited, not the whole market. The report says so; `calibrate` checks coverage.

Stdlib only, so the CLI can load this file by path without the backend's packages.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence, Tuple

# canonical dimension -> normalised column names (GA4 Data API, GA4 UI exports, PostHog properties and HogQL aliases)
DIMENSIONS: Dict[str, Tuple[str, ...]] = {
    "country": ("country", "countryname", "geoipcountryname"),
    "city": ("city", "cityname", "geoipcityname"),
    "age": ("useragebracket", "agebracket", "age", "agerange"),
    "gender": ("usergender", "gender"),
    "device": ("devicecategory", "devicetype", "device"),
    "channel": ("sessiondefaultchannelgroup", "firstuserdefaultchannelgroup", "sessionprimarychannelgroup",
                "defaultchannelgroup", "channelgroup", "channel", "sessionsourcemedium", "sessionsource",
                "firstusersource", "initialutmsource", "utmsource", "source", "initialreferringdomain",
                "referringdomain"),
    "returning": ("newvsreturning", "neworreturning"),
    "language": ("language", "browserlanguage"),
    "interest": ("brandinginterest", "interests", "affinitycategory"),
}
# canonical metric -> normalised column names; the first metric found weights each row (users before sessions)
METRICS: Dict[str, Tuple[str, ...]] = {
    "users": ("activeusers", "totalusers", "users", "uniqueusers", "persons", "uniqpersonid", "uniqdistinctid",
              "countdistinctpersonid", "countdistinctdistinctid"),
    "sessions": ("sessions",),
    "count": ("count", "eventcount", "events", "pageviews", "screenpageviews"),
    "conversions": ("keyevents", "conversions", "converters", "purchasers", "transactions", "ecommercepurchases"),
    "revenue": ("totalrevenue", "purchaserevenue", "revenue"),
}
WEIGHT_ORDER = ("users", "sessions", "count")
UNKNOWN = {"", "(not set)", "not set", "unknown", "(other)", "other", "(none)", "none", "null", "undefined", "n/a",
           "(data not available)", "(not provided)"}
TOTAL_LABELS = {"total", "totals", "grand total"}
AGE_BOUNDS = {"18-24": (18, 24), "25-34": (25, 34), "35-44": (35, 44), "45-54": (45, 54), "55-64": (55, 64),
              "65+": (65, 80)}
SOURCE_NAMES = {"ga4": "Google Analytics 4", "posthog": "PostHog", "rows": "analytics rows"}


def _norm(col: Any) -> str:
    """'Session default channel group' / 'person.properties.$geoip_country_name' / 'uniq(person_id)' -> one key."""
    s = str(col or "").strip()
    if "." in s and not s.endswith(")"):
        s = s.rsplit(".", 1)[-1]
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v or "").strip().replace(",", "").replace("%", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


# --------------------------------------------------------------------------
# reading exports
# --------------------------------------------------------------------------

def _flatten(row: Dict[str, Any]) -> Dict[str, Any]:
    """A PostHog person ({"properties": {...}}) or event row: lift nested properties next to the plain columns."""
    out = {k: v for k, v in row.items() if not isinstance(v, dict)}
    for key in ("properties", "person_properties"):
        nested = row.get(key)
        if isinstance(nested, dict):
            for k, v in nested.items():
                out.setdefault(k, v)
    person = row.get("person")
    if isinstance(person, dict) and isinstance(person.get("properties"), dict):
        for k, v in person["properties"].items():
            out.setdefault(k, v)
    return out


def rows_from_json(data: Any, origin: str = "json") -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Rows and metadata from the JSON shapes these tools produce:
    GA4 Data API runReport ({dimensionHeaders, metricHeaders, rows}) and batchRunReports ({reports: [...]});
    PostHog HogQL ({columns, results}) and persons/events ({results: [{properties}]}); or a plain list of rows."""
    meta: Dict[str, Any] = {}
    if isinstance(data, dict) and isinstance(data.get("reports"), list):
        rows: List[Dict[str, Any]] = []
        for k, rep in enumerate(data["reports"]):
            got, m = rows_from_json(rep, f"{origin}#report{k + 1}")
            rows += got
            meta.update({key: val for key, val in m.items() if key not in meta})
        return rows, meta
    if isinstance(data, dict) and ("dimensionHeaders" in data or "metricHeaders" in data):
        dims = [h.get("name") for h in data.get("dimensionHeaders") or []]
        mets = [h.get("name") for h in data.get("metricHeaders") or []]
        rows = []
        for r in data.get("rows") or []:
            row = {d: (v or {}).get("value") for d, v in zip(dims, r.get("dimensionValues") or [])}
            row.update({m: (v or {}).get("value") for m, v in zip(mets, r.get("metricValues") or [])})
            rows.append({**row, "_table": origin})
        ranges = (data.get("metadata") or {}).get("dateRanges") or data.get("dateRanges")
        if isinstance(ranges, list) and ranges and isinstance(ranges[0], dict):
            meta["period"] = f"{ranges[0].get('startDate')} to {ranges[0].get('endDate')}"
        meta["source"] = "ga4"
        return rows, meta
    if isinstance(data, dict) and isinstance(data.get("columns"), list) and isinstance(data.get("results"), list):
        cols = [str(c) for c in data["columns"]]
        rows = [{**dict(zip(cols, r)), "_table": origin} for r in data["results"] if isinstance(r, (list, tuple))]
        meta["source"] = "posthog"
        return rows, meta
    if isinstance(data, dict) and isinstance(data.get("results"), list):
        data = data["results"]
    if isinstance(data, dict) and isinstance(data.get("rows"), list):
        data = data["rows"]
    if isinstance(data, list):
        return [{**_flatten(r), "_table": origin} for r in data if isinstance(r, dict)], meta
    return [], meta


def rows_from_csv(text: str, origin: str = "csv") -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """GA4 UI exports start with '#' comment lines (property, start and end date) and can hold several tables
    separated by blank lines; each table keeps its own header."""
    meta: Dict[str, Any] = {}
    start = end = None
    body: List[str] = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#"):
            m = re.match(r"#\s*(start|end)\s*date\s*:\s*(\S+)", s, re.I)
            if m:
                start, end = (m.group(2), end) if m.group(1).lower() == "start" else (start, m.group(2))
            continue
        body.append(line)
    if start or end:
        meta["period"] = f"{_ymd(start)} to {_ymd(end)}"
        meta["source"] = "ga4"
    blocks, cur = [], []
    for line in body:
        if line.strip():
            cur.append(line)
        elif cur:
            blocks.append(cur)
            cur = []
    if cur:
        blocks.append(cur)
    rows = []
    for k, blk in enumerate(blocks):
        sample = "\n".join(blk[:5])
        delim = "\t" if sample.count("\t") > sample.count(",") else ","
        for r in csv.DictReader(io.StringIO("\n".join(blk)), delimiter=delim):
            rows.append({**{str(key): val for key, val in r.items() if key is not None}, "_table": f"{origin}#{k + 1}"})
    return rows, meta


def _ymd(s: Optional[str]) -> str:
    if s and re.fullmatch(r"\d{8}", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s or "?"


def read_sources(paths: Sequence[str]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Rows from CSV / TSV / JSON / JSONL analytics exports, each tagged with the table it came from."""
    rows: List[Dict[str, Any]] = []
    meta: Dict[str, Any] = {"files": []}
    for p in paths:
        with open(p, encoding="utf-8-sig") as f:
            text = f.read()
        name = os.path.basename(p)
        meta["files"].append(name)
        ext = os.path.splitext(p)[1].lower()
        if ext == ".jsonl":
            got, m = rows_from_json([json.loads(x) for x in text.splitlines() if x.strip()], name)
        elif ext == ".json":
            got, m = rows_from_json(json.loads(text), name)
        else:
            got, m = rows_from_csv(text, name)
        rows += got
        for k, v in m.items():
            meta.setdefault(k, v)
    return rows, meta


# --------------------------------------------------------------------------
# analysis
# --------------------------------------------------------------------------

def _columns(rows: List[Dict[str, Any]], field_map: Optional[Dict[str, str]]) -> Dict[str, str]:
    """canonical field -> the column that holds it in these rows, from --map first, then the known names."""
    present: Dict[str, str] = {}
    for r in rows:
        for col in r:
            if col != "_table":
                present.setdefault(_norm(col), col)
    out: Dict[str, str] = {}
    actual = {col for r in rows for col in r}
    for canon, col in (field_map or {}).items():
        if (canon in DIMENSIONS or canon in METRICS) and col in actual:
            out[canon] = col
    for canon, names in list(DIMENSIONS.items()) + list(METRICS.items()):
        if canon in out:
            continue
        for n in names:
            if n in present:
                out[canon] = present[n]
                break
    return out


def _detect_source(cols: Dict[str, str], meta: Dict[str, Any]) -> str:
    if meta.get("source"):
        return meta["source"]
    raw = " ".join(cols.values())
    if "$" in raw or "uniq(" in raw or "person_id" in raw or "distinct_id" in raw:
        return "posthog"
    if re.search(r"activeUsers|totalUsers|userAgeBracket|sessionDefaultChannelGroup|deviceCategory|Active users|"
                 r"Total users|Device category|Session default channel group|Key events", raw):
        return "ga4"
    return "rows"


def _clean(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v if v is not None else "")).strip()


def _age_label(v: str) -> str:
    s = v.replace(" ", "").replace("–", "-").replace("—", "-")
    return s if s in AGE_BOUNDS else v


def _gender_label(v: str) -> str:
    low = v.lower()
    return {"f": "female", "woman": "female", "women": "female", "m": "male", "man": "male", "men": "male"}.get(low, low)


class _Table:
    """Rows of one export table (one file, or one block of a multi-table GA4 CSV) and the dimensions it carries."""

    def __init__(self, name: str, dims: set, weight: str, has_conversions: bool):
        self.name, self.dims, self.weight, self.has_conversions = name, dims, weight, has_conversions
        self.rows: List[Tuple[Dict[str, str], float, float]] = []   # (dimension values, weight, conversions)

    @property
    def total(self) -> float:
        return sum(w for _, w, _ in self.rows)


def _tables(rows: List[Dict[str, Any]], field_map: Optional[Dict[str, str]]) -> Tuple[List[_Table], Dict[str, str]]:
    """Group rows by the table they came from; each table resolves its own column names (a GA4 export and a PostHog
    export can be mixed). A row missing a value the table has is counted as unknown, not moved to another table."""
    by_origin: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_origin[str(r.get("_table") or "rows")].append(r)
    tables: List[_Table] = []
    used: Dict[str, str] = {}
    for origin, group in by_origin.items():
        cols = _columns(group, field_map)
        dims = [d for d in DIMENSIONS if d in cols]
        if not dims:
            continue
        weight = next((m for m in WEIGHT_ORDER if m in cols), "")
        # aggregate rows (with a count) are cells of a breakdown: rows carrying different dimension columns belong to
        # different breakdowns, even in one list. Per-person rows (no count) stay one table whatever they lack.
        parts: Dict[frozenset, List[Dict[str, Any]]] = defaultdict(list)
        for r in group:
            parts[frozenset(d for d in dims if cols[d] in r) if weight else frozenset(dims)].append(r)
        for key, part in parts.items():
            name = origin if len(parts) == 1 else f"{origin}[{','.join(d for d in DIMENSIONS if d in key)}]"
            t = _Table(name, set(key), weight or "rows", "conversions" in cols)
            for r in part:
                vals = {d: _clean(r.get(cols[d])) for d in key}
                if any(v.lower() in TOTAL_LABELS for v in vals.values()) or all(v == "" for v in vals.values()):
                    continue                  # a totals row, or a row with none of the table's values
                if "age" in vals:
                    vals["age"] = _age_label(vals["age"])
                if "gender" in vals:
                    vals["gender"] = _gender_label(vals["gender"])
                w = _num(r.get(cols[weight])) if weight else 1.0
                if w is None or w <= 0:
                    continue
                t.rows.append((vals, w, (_num(r.get(cols["conversions"])) or 0.0) if t.has_conversions else 0.0))
            if t.rows and t.dims:
                tables.append(t)
                for k, v in cols.items():
                    used.setdefault(k, v)
    return tables, used


def _best(tables: List[_Table], need: Sequence[str]) -> Optional[_Table]:
    fit = [t for t in tables if all(d in t.dims for d in need)]
    return max(fit, key=lambda t: (t.total, -len(t.dims))) if fit else None


def _shares(table: _Table, dim: str, where: Optional[Tuple[str, str]] = None) -> Dict[str, Any]:
    """Shares of the known values of `dim` (optionally within where=(dimension, value)), plus the unknown share."""
    known: Dict[str, float] = defaultdict(float)
    unknown = 0.0
    for dims, w, _ in table.rows:
        if where and dims.get(where[0]) != where[1]:
            continue
        v = dims.get(dim, "")
        if v.lower() in UNKNOWN:
            unknown += w
        else:
            known[v] += w
    k_total = sum(known.values())
    total = k_total + unknown
    return {"shares": {k: round(v / k_total, 3) for k, v in sorted(known.items(), key=lambda kv: -kv[1])} if k_total else {},
            "users": round(k_total, 1), "unknown_share": round(unknown / total, 3) if total else None,
            "table": table.name}


def _key_events(tables: List[_Table], where: Optional[Tuple[str, str]] = None) -> Optional[float]:
    """Key events (conversions) per user from the largest user-weighted table that has them."""
    need = [where[0]] if where else []
    t = _best([t for t in tables if t.has_conversions and t.weight == "users"], need)
    if not t:
        return None
    rows = [(w, c) for d, w, c in t.rows if not where or d.get(where[0]) == where[1]]
    users = sum(w for w, _ in rows)
    return round(sum(c for _, c in rows) / users, 4) if users else None


def analyse(rows: List[Dict[str, Any]], meta: Optional[Dict[str, Any]] = None,
            field_map: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Shares per dimension site-wide, and per country and per channel, each from the largest table that carries the
    dimensions it needs."""
    meta = dict(meta or {})
    tables, cols = _tables(rows, field_map)
    source = _detect_source(cols, meta)
    top = _best(tables, [])
    out: Dict[str, Any] = {"source": source, "source_name": SOURCE_NAMES.get(source, source),
                           "period": meta.get("period") or "", "files": meta.get("files") or [], "columns": cols,
                           "weight": top.weight if top else "rows", "users": round(top.total, 1) if top else 0,
                           "rows": sum(len(t.rows) for t in tables), "tables": len(tables), "dimensions": {},
                           "by": {"country": {}, "channel": {}}}
    for dim in DIMENSIONS:
        t = _best(tables, [dim])
        if t:
            out["dimensions"][dim] = _shares(t, dim)
    kpu = _key_events(tables)
    if kpu is not None:
        out["key_events_per_user"] = kpu
    for group in ("country", "channel"):
        for name in ((out["dimensions"].get(group) or {}).get("shares") or {}):
            per: Dict[str, Any] = {"share": out["dimensions"][group]["shares"][name]}
            for dim in DIMENSIONS:
                t = _best(tables, [group, dim]) if dim != group else None
                if t:
                    s = _shares(t, dim, (group, name))
                    if s["shares"]:
                        per[dim] = s
            k = _key_events(tables, (group, name))
            if k is not None:
                per["key_events_per_user"] = k
            out["by"][group][name] = per
    return out


# --------------------------------------------------------------------------
# persona spec
# --------------------------------------------------------------------------

def _counts(shares: Sequence[float], total: int) -> List[int]:
    """Largest-remainder split of `total` people over the shares, at least one each."""
    if not shares:
        return []
    s = sum(shares) or 1.0
    raw = [total * x / s for x in shares]
    got = [max(1, int(r)) for r in raw]
    order = sorted(range(len(raw)), key=lambda i: -(raw[i] - int(raw[i])))
    k = 0
    while sum(got) < total and order:
        got[order[k % len(order)]] += 1
        k += 1
    while sum(got) > total and max(got) > 1:
        got[got.index(max(got))] -= 1
    return got


def _age_range(shares: Dict[str, float], tail: float = 0.1) -> Optional[Tuple[int, int]]:
    """Trim brackets holding less than `tail` of users from each end; the rest gives age_min / age_max."""
    known = [(b, shares[b]) for b in AGE_BOUNDS if b in shares]
    if not known:
        return None
    lo, hi = 0, len(known) - 1
    cut = 0.0
    while lo < hi and cut + known[lo][1] < tail:
        cut += known[lo][1]
        lo += 1
    cut = 0.0
    while hi > lo and cut + known[hi][1] < tail:
        cut += known[hi][1]
        hi -= 1
    return AGE_BOUNDS[known[lo][0]][0], AGE_BOUNDS[known[hi][0]][1]


def _top(shares: Dict[str, float], n: int = 3, floor: float = 0.0) -> List[Tuple[str, float]]:
    return [(k, v) for k, v in list(shares.items())[:n] if v >= floor]


def _pct(x: float) -> str:
    return f"{round(100 * x)}%"


def _notes(info: Dict[str, Any], site: Dict[str, Any], analysis: Dict[str, Any], lead: str, skip: str,
           group: Optional[Dict[str, Any]] = None) -> str:
    """What the analytics say about this group, in plain words for the persona writer. A figure that only exists for
    the whole site is marked so."""
    parts = [f"From {analysis['source_name']}" + (f" ({analysis['period']})" if analysis.get("period") else "")
             + f": {lead}."]
    for name, title in (("country", "Countries"), ("device", "Devices"), ("channel", "Came from"),
                        ("returning", "New vs returning"), ("language", "Languages"), ("interest", "Interests")):
        if name == skip or (name == "country" and skip != "channel"):
            continue
        d, scope = _pick(info, site, group or {}, name)
        top = _top(d.get("shares") or {}, 3, 0.05)
        if top:
            parts.append(f"{title}{' (whole site)' if scope == 'site' else ''}: "
                         + ", ".join(f"{k} {_pct(v)}" for k, v in top) + ".")
    kpu, scope = info.get("key_events_per_user"), ""
    if kpu is None and analysis.get("key_events_per_user") is not None:
        kpu, scope = analysis["key_events_per_user"], " (whole site)"
    if kpu is not None:
        parts.append(f"Key events{scope}: {100 * kpu:.2g} per 100 users.")
    parts.append("These are visitors, not the whole market.")
    return " ".join(parts)


def _pick(info: Dict[str, Any], site: Dict[str, Any], group: Dict[str, Any], dim: str) -> Tuple[Dict[str, Any], str]:
    """The group's own shares for `dim`; the whole-site shares only when no group in the data has that breakdown
    (a country thresholded out of a per-country table stays unknown rather than borrowing other countries' mix)."""
    if info.get(dim):
        return info[dim], "own"
    if site.get(dim) and not any(dim in g for g in group.values()):
        return site[dim], "site"
    return {}, ""


def _women(gender: Dict[str, float]) -> Optional[str]:
    f, m = gender.get("female", 0.0), gender.get("male", 0.0)
    return f"{f / (f + m):.2f}" if f + m else None


def build_spec(analysis: Dict[str, Any], people: int = 24, segment_by: str = "country", min_share: float = 0.05,
               max_segments: int = 6, role: str = "") -> Dict[str, Any]:
    """Segments sized by share of users, and per-country age / gender shares for raking. Keys the data does not
    support are left out, so the planner's own defaults apply and the report says what was unknown."""
    if segment_by not in ("country", "channel"):
        raise ValueError("segment_by must be country or channel")
    site = analysis.get("dimensions") or {}
    by = analysis.get("by") or {}
    groups = (site.get(segment_by) or {}).get("shares") or {}
    chosen = [(k, v) for k, v in groups.items() if v >= min_share][:max(1, max_segments)]
    if not chosen and groups:
        chosen = list(groups.items())[:1]
    left_out = round(1 - sum(v for _, v in chosen), 3) if chosen else None
    sizes = _counts([v for _, v in chosen], max(len(chosen), int(people)))
    top_country = next(iter((site.get("country") or {}).get("shares") or {}), "")
    segments: List[Dict[str, Any]] = []
    for (name, share), n in zip(chosen, sizes):
        group = by.get(segment_by) or {}
        info = group.get(name) or {}
        if segment_by == "country":
            country, lead = name, f"{_pct(share)} of users"
        else:
            country = next(iter((info.get("country") or {}).get("shares") or {}), "") or top_country
            lead = f"{_pct(share)} of users came from {name}"
        place = (by.get("country") or {}).get(country) or {}
        seg: Dict[str, Any] = {"label": f"{name} {role or 'visitors'}", "count": n, "source": "analytics"}
        if country:
            seg["country"] = country
        cities = _top(((place.get("city") or {}).get("shares") or {}), 5)
        if cities:
            seg["cities"] = [c for c, _ in cities]
        age, age_scope = _pick(info, site, group, "age")
        rng = _age_range(age.get("shares") or {})
        if rng:
            seg["age_min"], seg["age_max"] = rng
        gender, gender_scope = _pick(info, site, group, "gender")
        women = _women(gender.get("shares") or {})
        if women is not None:
            seg["gender_mix"] = women
        langs = _top((_pick(info, site, group, "language")[0].get("shares") or {}), 3, 0.1)
        if langs:
            seg["languages"] = [k for k, _ in langs]
        if role:
            seg["role"] = role
        seg["notes"] = _notes(info, site, analysis, lead, segment_by, group)
        if "site" in (age_scope, gender_scope):
            seg["notes"] = seg["notes"].replace(" These are visitors", " Age and gender are whole-site figures. These are visitors")
        segments.append(seg)
    population: Dict[str, Any] = {}
    for country in dict.fromkeys(s["country"] for s in segments if s.get("country")):
        countries = by.get("country") or {}
        place = countries.get(country) or {}
        pop: Dict[str, Any] = {}
        a, a_scope = _pick(place, site, countries, "age")
        age = {k: v for k, v in (a.get("shares") or {}).items() if k in AGE_BOUNDS}
        if age:
            pop["age"] = age
        g, g_scope = _pick(place, site, countries, "gender")
        gender = {k: v for k, v in (g.get("shares") or {}).items() if k in ("female", "male")}
        if gender:
            pop["gender"] = gender
        if pop:
            pop["scope"] = "whole site" if "site" in (a_scope, g_scope) else "country"
            pop["source"] = "analytics"
            population[country] = pop
    return {"segments": segments, "population": population, "left_out_share": left_out}


def merge_into_spec(built: Dict[str, Any], spec: Optional[Dict[str, Any]], replace: bool = False,
                    population_only: bool = False) -> Dict[str, Any]:
    """Add the analytics segments (replacing earlier analytics segments, keeping the user's own) and the population
    shares: a country the spec already gives keeps the user's shares unless replace=True; earlier analytics shares
    are always refreshed."""
    spec = json.loads(json.dumps(spec or {}))
    if not population_only:
        own = [s for s in spec.get("segments") or [] if s.get("source") != "analytics"]
        spec["segments"] = own + built.get("segments", [])
    pop = dict(spec.get("population") or {})
    for country, shares in (built.get("population") or {}).items():
        if replace or country not in pop or (pop.get(country) or {}).get("source") == "analytics":
            pop[country] = shares
    if pop:
        spec["population"] = pop
    return spec


def run(rows: List[Dict[str, Any]], meta: Optional[Dict[str, Any]] = None, field_map: Optional[Dict[str, str]] = None,
        people: int = 24, segment_by: str = "country", min_share: float = 0.05, max_segments: int = 6,
        role: str = "", period: str = "") -> Dict[str, Any]:
    analysis = analyse(rows, {**(meta or {}), **({"period": period} if period else {})}, field_map)
    if not analysis.get("dimensions"):
        raise ValueError("analytics: no known dimension found (country, city, age, gender, device, channel ...); "
                         "pass --map country=<column> for a renamed column")
    if not (analysis["dimensions"].get(segment_by) or {}).get("shares"):
        raise ValueError(f"analytics: no {segment_by} column with known values; use --segment-by "
                         f"{'channel' if segment_by == 'country' else 'country'} or --map {segment_by}=<column>")
    built = build_spec(analysis, people, segment_by, min_share, max_segments, role)
    return {"analysis": analysis, **built, "caveats": caveats(analysis)}


def caveats(analysis: Dict[str, Any]) -> List[str]:
    out = ["Analytics describe the people who visited, not everyone you could sell to."]
    dims = analysis.get("dimensions") or {}
    if analysis.get("source") == "ga4" and ("age" in dims or "gender" in dims):
        users = max((dims.get(d) or {}).get("users") or 0 for d in ("age", "gender"))
        out.append(f"GA4 age and gender come from Google signals and are thresholded: they rest on {users:,.0f} of "
                   f"{analysis.get('users', 0):,.0f} users.")
    for d in ("age", "gender", "country"):
        if d not in dims:
            out.append(f"No {d} in the data: the planner's defaults apply for it.")
        elif (dims[d].get("unknown_share") or 0) >= 0.2:
            out.append(f"{_pct(dims[d]['unknown_share'])} of users have no {d}; shares are of the known rest.")
    if analysis.get("weight") == "users":
        out.append("Users are summed across rows, so a person seen in two rows (say two devices) counts twice.")
    elif analysis.get("weight") == "rows":
        out.append("No user or session count in the data: each row counts as one person.")
    return out


def render_markdown(data: Dict[str, Any]) -> str:
    a = data["analysis"]
    lines = [f"# Audience from {a['source_name']}", ""]
    meta = [f"{a.get('users', 0):,.0f} {a.get('weight')}" if a.get("weight") != "rows" else f"{a.get('rows')} rows"]
    if a.get("period"):
        meta.append(a["period"])
    if a.get("files"):
        meta.append("files: " + ", ".join(a["files"]))
    lines += [" · ".join(meta), "", "## Segments the planner will build", "",
              "| segment | people | country | cities | ages | share of women |", "|---|---|---|---|---|---|"]
    for s in data.get("segments") or []:
        ages = f"{s['age_min']}-{s['age_max']}" if "age_min" in s else "unknown"
        lines.append(f"| {s['label']} | {s['count']} | {s.get('country', 'unknown')} | {', '.join(s.get('cities') or []) or 'unknown'} "
                     f"| {ages} | {s.get('gender_mix', 'unknown')} |")
    if data.get("left_out_share"):
        lines += ["", f"Left out (below the minimum share): {_pct(data['left_out_share'])} of users."]
    lines += ["", "## What each segment's notes say", ""]
    lines += [f"- **{s['label']}**: {s.get('notes', '')}" for s in data.get("segments") or []]
    if data.get("population"):
        lines += ["", "## Population shares for weighting", ""]
        for country, p in data["population"].items():
            bits = [f"{dim}: " + ", ".join(f"{k} {_pct(v)}" for k, v in shares.items())
                    for dim, shares in p.items() if isinstance(shares, dict)]
            lines.append(f"- {country} ({p.get('scope', 'country')}): " + "; ".join(bits))
    lines += ["", "## Columns read", ""]
    lines += [f"- {k}: `{v}`" for k, v in (a.get("columns") or {}).items()]
    lines += ["", "No other column was read.", "", "## Caveats", ""] + [f"- {c}" for c in data.get("caveats") or []]
    return "\n".join(lines) + "\n"
