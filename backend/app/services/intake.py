"""Customer intake: turn your own customer material into grounded personas.

Reads what a founder or marketer already has (call or interview transcripts, review exports, NPS / survey verbatims,
CRM or support notes), removes contact details locally, groups the rows by person and writes `real_profiles`
records for the persona planner (`personas.json`). The planner turns each record into a persona marked
"grounded" (provenance `real_intake`), next to the synthetic people it writes for the remaining slots.

Why: interview-grounded agents built from real people predicted held-out answers better than demographic-only
agents (Park et al. 2024, arXiv 2411.10109), and MarketMirror's own life interviews are model-written. Real material
is the strongest grounding a run can get. It is still a small, self-selected sample (reviewers, customers who took a
call): coverage is checked by `calibrate`, not assumed.

Rules:
- Contact details are scrubbed before anything leaves the machine: emails, phone and card-like numbers, links,
  @handles, and the names found in name/author columns (replaced by initials). Names inside free text that are not
  in such a column are not detected: review the output before sharing it.
- Excerpts are verbatim. A quote the model returns that is not in the person's own (scrubbed) material is dropped.
- Nothing is invented: age, country, city and gender are kept only when a column states them or the text contains
  them; BDE fields stay empty unless the material says so. Unknown stays unknown.
- Engines: "llm" (one call per batch of people through an injected `complete(system, user) -> (text, usage)`) and
  "supplied" (no model: columns become fields and the person's own sentences become excerpts; offline).

Stdlib only, so the CLI can load this file by path without the backend's packages.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

VERSION = 1
BATCH = 5                       # people per model call
MAX_PEOPLE = 200
MAX_CHARS_PER_PERSON = 6000     # material sent per person (the rest is summarised by being left out)
MAX_EXCERPTS = 6

Complete = Callable[[str, str], Tuple[str, Dict[str, Any]]]

TEXT_FIELDS = ("text", "review", "review_text", "body", "comment", "comments", "content", "transcript", "notes",
               "note", "feedback", "verbatim", "answer", "response", "message", "description", "why", "reason")
ID_FIELDS = ("customer_id", "customer", "contact_id", "user_id", "author_id", "reviewer_id", "account_id",
             "author", "reviewer", "user", "username", "email", "name", "contact", "id")
NAME_FIELDS = ("name", "author", "reviewer", "customer", "customer_name", "contact", "contact_name", "full_name",
               "first_name", "last_name", "user", "username")
META_FIELDS = {
    "segment": ("segment", "plan", "tier", "persona", "audience", "cohort", "customer_type"),
    "country": ("country", "market", "region"),
    "city": ("city", "town", "location"),
    "age": ("age",),
    "gender": ("gender", "sex"),
    "occupation": ("occupation", "role", "job_title", "title", "job", "industry"),
    "product": ("product", "item", "sku", "product_name"),
    "rating": ("rating", "stars", "score", "nps", "csat"),
    "date": ("date", "created_at", "timestamp", "review_date", "submitted_at"),
}
TRANSCRIPT_EXT = (".txt", ".md", ".vtt", ".srt")

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL = re.compile(r"\b(?:https?://|www\.)\S+", re.I)
_HANDLE = re.compile(r"(?<![\w@])@[A-Za-z0-9_]{2,30}\b")
_NUMBERISH = re.compile(r"(?<![\w$€£₹])\+?\d[\d\s().-]{6,}\d(?![\w%])")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SENT = re.compile(r"(?<=[.!?。！？])\s+")


# --------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------

def _rows_from_text(text: str, name: str) -> List[Dict[str, Any]]:
    ext = os.path.splitext(name)[1].lower()
    if ext in (".json", ".jsonl"):
        if ext == ".jsonl":
            data: Any = [json.loads(line) for line in text.splitlines() if line.strip()]
        else:
            data = json.loads(text)
        if isinstance(data, dict):
            data = next((data[k] for k in ("rows", "data", "reviews", "items", "records", "responses", "customers")
                         if isinstance(data.get(k), list)), [data])
        return [r if isinstance(r, dict) else {"text": str(r)} for r in data or []]
    if ext in (".csv", ".tsv"):
        dialect = "excel-tab" if ext == ".tsv" else "excel"
        return [dict(r) for r in csv.DictReader(io.StringIO(text), dialect=dialect)]
    # a transcript or notes file: one person (or one conversation) per file
    stem = os.path.splitext(os.path.basename(name))[0]
    return [{"id": stem, "text": text, "_transcript": True}]


def read_sources(paths: Sequence[str]) -> List[Dict[str, Any]]:
    """Rows from CSV / TSV / JSON / JSONL exports and txt / md / vtt / srt transcripts (one row per transcript)."""
    rows: List[Dict[str, Any]] = []
    for p in paths:
        with open(p, encoding="utf-8-sig") as f:
            text = f.read()
        for r in _rows_from_text(text, p):
            r.setdefault("_source", os.path.basename(p))
            rows.append(r)
    return rows


def _lower_keys(raw: Dict[str, Any]) -> Dict[str, Any]:
    return {str(k).strip().lower().replace(" ", "_").replace("-", "_"): v for k, v in raw.items()}


def _first(row: Dict[str, Any], keys: Sequence[str]) -> str:
    for k in keys:
        v = row.get(k)
        if v not in (None, "") and str(v).strip():
            return str(v).strip()
    return ""


def normalize_row(raw: Dict[str, Any], idx: int, id_field: str = "", segment_field: str = "",
                  text_field: str = "") -> Optional[Dict[str, Any]]:
    """One row -> {id, source, text, names, meta}. Returns None for a row without words."""
    r = _lower_keys(raw)
    fields = [text_field.lower()] if text_field else list(TEXT_FIELDS)
    texts = [str(r[k]).strip() for k in fields if r.get(k) not in (None, "") and str(r[k]).strip()]
    if not texts and not text_field:   # an export with an unusual text column: take the longest free-text value
        cand = [str(v).strip() for k, v in r.items() if not k.startswith("_") and isinstance(v, str) and len(v.split()) >= 6]
        texts = sorted(cand, key=len, reverse=True)[:1]
    text = "\n".join(texts)
    if not text:
        return None
    pid = _first(r, [id_field.lower()]) if id_field else _first(r, ID_FIELDS)
    meta = {k: _first(r, keys) for k, keys in META_FIELDS.items()}
    if segment_field:
        meta["segment"] = _first(r, [segment_field.lower()]) or meta["segment"]
    names = [str(r[k]).strip() for k in NAME_FIELDS if isinstance(r.get(k), str) and r[k].strip() and "@" not in r[k]]
    return {"id": pid or f"row{idx + 1}", "source": str(raw.get("_source") or ""), "text": text,
            "transcript": bool(raw.get("_transcript")), "names": names,
            "meta": {k: v for k, v in meta.items() if v}}


# --------------------------------------------------------------------------
# scrubbing
# --------------------------------------------------------------------------

def initials(name: str) -> str:
    parts = [p for p in re.split(r"[\s._-]+", name.strip()) if p and p[0].isalpha()]
    return ".".join(p[0].upper() for p in parts[:3]) + "." if parts else "X."


def scrub(text: str, names: Sequence[str] = ()) -> Tuple[str, Dict[str, int]]:
    """Remove contact details. Returns (clean text, counts per kind)."""
    counts = {"email": 0, "link": 0, "handle": 0, "phone": 0, "number": 0, "name": 0}

    def sub(pattern: re.Pattern, repl: str, kind: str, s: str) -> str:
        out, n = pattern.subn(repl, s)
        counts[kind] += n
        return out

    s = sub(_EMAIL, "[email]", "email", text or "")
    s = sub(_URL, "[link]", "link", s)
    s = sub(_HANDLE, "[handle]", "handle", s)

    def number(m: re.Match) -> str:
        raw = m.group(0)
        digits = sum(ch.isdigit() for ch in raw)
        if digits < 8 or _ISO_DATE.match(raw.strip()):
            return raw
        kind = "number" if digits >= 13 else "phone"
        counts[kind] += 1
        return f"[{kind}]"
    s = _NUMBERISH.sub(number, s)
    for full in sorted({n for n in names if n}, key=len, reverse=True):
        tokens = [full] + [t for t in re.split(r"\s+", full) if len(t) >= 3]
        for t in tokens:
            pat = re.compile(rf"(?<!\w){re.escape(t)}(?!\w)", re.I)
            s, n = pat.subn(initials(full) if t == full else initials(t), s)
            counts["name"] += n
    return s, counts


# --------------------------------------------------------------------------
# grouping
# --------------------------------------------------------------------------

def group_people(rows: List[Dict[str, Any]], max_people: int = MAX_PEOPLE) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Normalized rows -> people (all rows with the same id), scrubbed. Returns (people, scrub counts)."""
    by_id: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        key = f"{r['source']}::{r['id']}" if r.get("transcript") else str(r["id"])
        p = by_id.setdefault(key, {"key": key, "sources": [], "texts": [], "names": [], "meta": {}})
        if r["source"] and r["source"] not in p["sources"]:
            p["sources"].append(r["source"])
        p["texts"].append(r["text"])
        p["names"] += [n for n in r.get("names") or [] if n not in p["names"]]
        for k, v in (r.get("meta") or {}).items():
            p["meta"].setdefault(k, v)
    totals = {"email": 0, "link": 0, "handle": 0, "phone": 0, "number": 0, "name": 0}
    people = []
    for k, p in enumerate(list(by_id.values())[:max_people]):
        clean = []
        for t in p["texts"]:
            s, c = scrub(t, p["names"])
            clean.append(s)
            for kind, n in c.items():
                totals[kind] += n
        material = "\n---\n".join(clean)
        people.append({"n": k + 1, "alias": f"Customer {k + 1}", "sources": p["sources"], "rows": len(p["texts"]),
                       "material": material[:MAX_CHARS_PER_PERSON], "truncated": len(material) > MAX_CHARS_PER_PERSON,
                       "meta": p["meta"]})
    return people, totals


# --------------------------------------------------------------------------
# extraction
# --------------------------------------------------------------------------

SYSTEM = (
    "You turn real customer material (reviews, interview or call transcripts, survey verbatims, CRM notes) into "
    "structured customer records for a market simulation. You never invent facts: a field the material does not "
    "state stays empty (\"\" or [] or null). Quotes are copied word for word from the material, never paraphrased. "
    "Reply with JSON only."
)

BDE_FIELDS = {
    "background": {"who": "", "knows": "", "believes": "", "says_vs_does": ""},
    "decision_procedure": {"who_they_ask": "", "speed": "impulsive|considered|slow or empty", "triggers": [], "stoppers": []},
    "evaluation": {"monthly_discretionary": "", "value_priorities": [], "pays_for": [], "never_pays_for": [],
                   "dealbreakers": [], "trust_cues": []},
}


def extract_prompt(people: List[Dict[str, Any]], context: str = "") -> Tuple[str, str]:
    blocks = []
    for i, p in enumerate(people, 1):
        known = ", ".join(f"{k}: {v}" for k, v in p["meta"].items() if k in ("segment", "country", "city", "age", "gender", "occupation", "product", "rating"))
        blocks.append(f"### Person {i}" + (f" ({known})" if known else "") + f"\n{p['material']}")
    schema = {"people": [{"i": 1, "segment": "", "age": None, "gender": "", "country": "", "city": "", "occupation": "",
                          "excerpts": ["up to 6 verbatim quotes that show needs, objections, triggers and how they decide"],
                          "past_purchases": [], "interested_topics": [], "bde": BDE_FIELDS}]}
    user = ((f"Product context: {context}\n\n" if context else "")
            + "For each person below, write one record. Fill a field only when the material states it. "
              "Excerpts must be exact substrings of that person's material (copy them; keep the original language). "
              "If the material is one conversation with several customers, describe only the customer, never the "
              "interviewer or the company.\n\n"
            + "\n\n".join(blocks)
            + "\n\nReply with only this JSON:\n" + json.dumps(schema, ensure_ascii=False))
    return SYSTEM, user


def json_block(text: str) -> Any:
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    for open_, close in (("{", "}"), ("[", "]")):
        a, b = text.find(open_), text.rfind(close)
        if a != -1 and b > a:
            try:
                return json.loads(text[a:b + 1])
            except ValueError:
                continue
    return None


def _squash(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().strip("\"'“”‘’")).lower()


def _stated(value: Any, person: Dict[str, Any]) -> bool:
    """A demographic value counts only when a column gave it or the material contains it."""
    v = str(value or "").strip()
    if not v or v.lower() in ("none", "null", "unknown", "n/a"):
        return False
    if any(str(m).strip().lower() == v.lower() for m in person["meta"].values()):
        return True
    return re.search(rf"(?<!\w){re.escape(v.lower())}(?!\w)", person["material"].lower()) is not None


def _str_list(v: Any, n: int = 5) -> List[str]:
    items = v if isinstance(v, list) else [v] if v else []
    return [str(x).strip()[:160] for x in items if str(x).strip()][:n]


def finish_record(person: Dict[str, Any], entry: Dict[str, Any], engine: str, stats: Dict[str, int]) -> Optional[Dict[str, Any]]:
    """Validate one model (or supplied) entry against the person's own material and build a real_profiles record."""
    hay = _squash(person["material"])
    excerpts = []
    for q in _str_list(entry.get("excerpts"), 12):
        if len(q) >= 8 and _squash(q) in hay:
            if q not in excerpts:
                excerpts.append(q)
        else:
            stats["excerpts_dropped"] += 1
    excerpts = excerpts[:MAX_EXCERPTS]
    stats["excerpts_kept"] += len(excerpts)
    if not excerpts:
        return None
    rec: Dict[str, Any] = {"name": person["alias"], "excerpts": excerpts}
    meta = person["meta"]
    for f in ("segment", "occupation"):
        val = str(entry.get(f) or meta.get(f) or "").strip()
        if val:
            rec[f] = val[:120]
    for f in ("country", "city", "gender"):
        val = entry.get(f) or meta.get(f)
        if _stated(val, person):
            rec[f] = str(val).strip()[:80]
        elif entry.get(f):
            stats["fields_dropped"] += 1
    age = entry.get("age") if entry.get("age") not in (None, "") else meta.get("age")
    try:
        age_i = int(float(str(age))) if age not in (None, "") else None
    except ValueError:
        age_i = None
    if age_i is not None and 13 <= age_i <= 100 and _stated(age_i, person):
        rec["age"] = age_i
    elif age not in (None, ""):
        stats["fields_dropped"] += 1
    for f in ("past_purchases", "interested_topics"):
        vals = _str_list(entry.get(f))
        if vals:
            rec[f] = vals
    if meta.get("product") and "past_purchases" not in rec:
        rec["past_purchases"] = [meta["product"]]
    bde = entry.get("bde")
    if isinstance(bde, dict) and any(isinstance(v, dict) and any(x for x in v.values()) for v in bde.values()):
        rec["bde"] = bde
        rec["bde_source"] = "real_intake: model-extracted from the customer's own words"
    rec["persona"] = f"A real customer ({rec.get('segment') or 'customer'})" + (
        f", {rec['occupation']}" if rec.get("occupation") else "") + "."
    rec["intake"] = {"sources": person["sources"], "rows": person["rows"], "engine": engine,
                     "rating": meta.get("rating") or None, "date": meta.get("date") or None,
                     "truncated": person["truncated"]}
    rec["intake"] = {k: v for k, v in rec["intake"].items() if v not in (None, "", [])}
    return rec


def extract_supplied(people: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """No model: columns become fields and the person's own longest sentences become excerpts."""
    stats = {"excerpts_kept": 0, "excerpts_dropped": 0, "fields_dropped": 0, "failed": 0}
    out = []
    for p in people:
        sents = [s.strip() for s in _SENT.split(p["material"].replace("\n---\n", " ")) if len(s.split()) >= 4]
        picks = sorted(sents, key=len, reverse=True)[:MAX_EXCERPTS]
        rec = finish_record(p, {"excerpts": [s[:400] for s in picks]}, "supplied", stats)
        if rec:
            out.append(rec)
        else:
            stats["failed"] += 1
    return out, stats


def extract_llm(people: List[Dict[str, Any]], complete: Complete, context: str = "", parallel: int = 4,
                batch: int = BATCH) -> Tuple[List[Dict[str, Any]], Dict[str, int], Dict[str, int]]:
    """One call per `batch` people. A person the model leaves out, or a failed call, gets no record."""
    batches = [people[i:i + batch] for i in range(0, len(people), batch)]
    usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
    stats = {"excerpts_kept": 0, "excerpts_dropped": 0, "fields_dropped": 0, "failed": 0}

    def one(b: List[Dict[str, Any]]):
        try:
            text, u = complete(*extract_prompt(b, context))
        except Exception as e:  # noqa: BLE001 - one failed batch must not lose the others
            return b, None, {}, str(e)[:200]
        return b, json_block(text), u or {}, None

    with ThreadPoolExecutor(max_workers=max(1, min(parallel, len(batches) or 1))) as pool:
        results = list(pool.map(one, batches))
    records: List[Dict[str, Any]] = []
    for b, parsed, u, err in results:
        usage["calls"] += 1
        for k in ("input_tokens", "output_tokens"):
            usage[k] += int(u.get(k) or 0)
        rows = parsed.get("people") if isinstance(parsed, dict) else parsed
        by_i: Dict[int, Dict[str, Any]] = {}
        for r in rows or []:
            if isinstance(r, dict):
                try:
                    by_i[int(r.get("i"))] = r
                except (TypeError, ValueError):
                    continue
        for n, p in enumerate(b, 1):
            rec = finish_record(p, by_i[n], "llm", stats) if (not err and n in by_i) else None
            if rec:
                records.append(rec)
            else:
                stats["failed"] += 1
    return records, stats, usage


# --------------------------------------------------------------------------
# the whole step
# --------------------------------------------------------------------------

def prepare(raw_rows: List[Dict[str, Any]], id_field: str = "", segment_field: str = "", text_field: str = "",
            segment: str = "", max_people: int = MAX_PEOPLE) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Raw rows -> scrubbed people ready for extraction, plus counts. No model call."""
    rows = [n for i, r in enumerate(raw_rows) if isinstance(r, dict)
            for n in [normalize_row(r, i, id_field, segment_field, text_field)] if n]
    if segment:
        for r in rows:
            r["meta"].setdefault("segment", segment)
    people, scrubbed = group_people(rows, max_people)
    return people, {"rows": len(raw_rows), "rows_with_text": len(rows), "people": len(people), "scrubbed": scrubbed}


def run(raw_rows: List[Dict[str, Any]], engine: str = "supplied", complete: Optional[Complete] = None,
        context: str = "", id_field: str = "", segment_field: str = "", text_field: str = "", segment: str = "",
        max_people: int = MAX_PEOPLE, parallel: int = 4) -> Dict[str, Any]:
    """The intake: rows -> real_profiles records, with counts and a plain-language note."""
    if engine not in ("llm", "supplied"):
        raise ValueError("engine must be llm or supplied")
    people, counts = prepare(raw_rows, id_field, segment_field, text_field, segment, max_people)
    if not people:
        raise ValueError("intake: no rows with customer words (looked for text, review, transcript, notes, comment ...)")
    usage: Dict[str, int] = {}
    if engine == "llm":
        if complete is None:
            raise ValueError("intake: engine llm needs a model")
        records, stats, usage = extract_llm(people, complete, context, parallel)
    else:
        records, stats = extract_supplied(people)
    counts.update({"records": len(records), **stats})
    return {"version": VERSION, "engine": engine, "records": records, "counts": counts, "usage": usage,
            "note": ("Grounded personas come from real customer words with contact details removed. They are a small, "
                     "self-selected sample (the people who wrote reviews or took a call); synthetic people fill the "
                     "remaining audience. Check coverage with calibrate before treating results as representative.")}


def merge_into_spec(records: List[Dict[str, Any]], spec: Optional[Dict[str, Any]] = None,
                    replace: bool = False) -> Dict[str, Any]:
    """Add the records to a persona spec's real_profiles (replacing earlier intake records when replace=True)."""
    spec = dict(spec or {})
    existing = [r for r in spec.get("real_profiles") or [] if isinstance(r, dict)]
    if replace:
        existing = [r for r in existing if not r.get("intake")]
    seen = {r.get("name") for r in existing}
    n = len(existing)
    added = []
    for r in records:
        r = dict(r)
        if r.get("name") in seen:
            n += 1
            r["name"] = f"Customer {n}"
        seen.add(r["name"])
        added.append(r)
    spec["real_profiles"] = existing + added
    return spec


def render_markdown(data: Dict[str, Any]) -> str:
    c = data.get("counts") or {}
    sc = c.get("scrubbed") or {}
    lines = ["# Customer intake", "",
             f"{c.get('records', 0)} grounded customer records from {c.get('people', 0)} people "
             f"({c.get('rows', 0)} rows, engine {data.get('engine')}).", "",
             "Removed before any model call: " + (", ".join(f"{v} {k}" for k, v in sc.items() if v) or "nothing found") + ".",
             f"Quotes kept: {c.get('excerpts_kept', 0)}; quotes dropped because they were not in the source: "
             f"{c.get('excerpts_dropped', 0)}; demographic values dropped because nothing stated them: {c.get('fields_dropped', 0)}.",
             "", data.get("note") or "", ""]
    for r in data.get("records") or []:
        who = ", ".join(str(r[k]) for k in ("segment", "age", "city", "country", "occupation") if r.get(k))
        lines.append(f"## {r['name']}" + (f" ({who})" if who else ""))
        lines += [f"> {q}" for q in r.get("excerpts") or []]
        lines.append("")
    return "\n".join(lines)
