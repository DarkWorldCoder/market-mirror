"""
search_and_geo.py - evidence search across a run, plus three tests: how buyers would search (simulated),
real vs simulated concerns (VoC), and a word-of-mouth cascade answered by the simulated people.

  * build_search_index / search_market_evidence / ask_market_copilot: index what the run actually produced and rank
    it with the shared stdlib ranker in claude_cli/run_search.py (BM25 plus buyer-concern synonyms). The cited answer
    is written by the model from the retrieved records only; when that call fails the records are returned with
    answer_ok false and the error, never a stand-in answer.
  * run_geo_visibility_audit ("How buyers would search (simulated)"): two calls per person. Before seeing the offer:
    whether and how they would look for help with the need, and which options they already know. After seeing it:
    what they think it is, whether they would shortlist it, what they would check and which fact is missing. It does
    not measure what any real assistant or search engine says about the brand.
  * run_voc_grounding: classifies real text (`raw_reviews`, a public `url`, or `research` quotes) and the simulated
    people's objections with the same classifier prompt, then compares the shares per concern (Wilson 95% ranges)
    and their difference (Newcombe hybrid score interval). classifier="jev" labels both sides with one Jev `choice`
    question instead (services/jev.py); run_objection_check uses the same question shape on survey objections.
  * run_dark_social_cascade: wave 1 says whether and what they would forward; wave 2 (other people) answers the cold
    offer and a friend's forward in two separate calls, scored yes=1, maybe=0.5, no=0 and compared per person.
"""

from __future__ import annotations

import json
import math
import os
import random
import re
from collections import Counter
from typing import Any, Callable, Dict, List, Optional, Tuple

from claude_cli import run_search

from . import jev
from .cro_and_sparring import fetch_url_snapshot
from .gtm_suite import (
    CONCERN_TYPES,
    _ctype,
    _meter,
    _need,
    _short,
    ask_people,
    competitor_list,
    envelope,
    gather_objections,
    guard_numbers,
    mean_ci,
    offer_dict,
    offer_text,
    person_card,
    product_facts,
    ranked,
    sample_people,
    verdict_from_ci,
    wilson,
    write_once,
)

CLASSIFIER_SYSTEM = (
    "You label short texts for a market study. Read the text exactly as given and pick the one concern it mainly "
    "expresses, or none. Copy phrases word for word; never rewrite or add facts. Reply with JSON only.")

# Concern types as Jev `choice` criteria (classifier="jev"): the same labels the model classifier returns
CONCERN_CRITERIA = {
    "price": "Cost or value for money, or doubt that it is really free",
    "trust": "Doubt that it is legitimate, safe or honest; fear of a scam or a hidden catch",
    "relevance": "It does not fit the person's needs or situation",
    "effort": "Too much time, work or hassle to start or to use",
    "timing": "Not the right time; maybe later",
    "unclear": "Not clear what it is, what it does or what happens next",
    "privacy": "Worry about personal data, tracking or being contacted",
    "competitor": "Already uses or prefers another product or a free alternative",
    "authority": "Needs someone else's approval or advice before deciding",
    "habit": "Content with the current way of doing things and does not want to change",
    "other": "A concern that fits none of the other types",
    "none": "No concern: praise, a plain description or an unrelated remark",
}
JEV_CONCERN_INSTRUCTIONS = ("The state is a short text from a market study, quoted exactly. Pick the one concern it "
                            "mainly expresses, or none when it expresses no concern.")
CLASSIFIERS = ("model", "jev")


def jev_label_texts(texts: List[str], criteria: Dict[str, str], instructions: str,
                    usage: Optional[jev.JevUsage] = None, parallel: Optional[int] = None) -> List[Dict[str, Any]]:
    """One Jev `choice` question per text -> [{ok, label, confidence, model, error}] in order. A failed request, or a
    choice outside the criteria, stays unlabelled. Raises jev.JevUnavailable without a key."""
    jobs = [(t, {"label": jev.choice_question(criteria, instructions)}) for t in texts]
    out = []
    for r in jev.ask_many(jobs, parallel=parallel, usage=usage) if jobs else []:
        ans = (r.get("answers") or {}).get("label") if r.get("ok") else None
        label = jev.choice_label(ans, list(criteria))
        out.append({"ok": label is not None, "label": label, "model": r.get("model"),
                    "confidence": ans.get("confidence") if isinstance(ans, dict) else None,
                    "error": r.get("error") or (None if label else "Jev chose a label outside the criteria")})
    return out


def run_objection_check(items: List[Dict[str, Any]], criteria: Dict[str, str],
                        parallel: Optional[int] = None) -> Dict[str, Any]:
    """Survey check: Jev labels each person's main objection with the same types they tagged it with, and the
    agreement with their own tag is reported as a share with a Wilson 95% range. items: [{id, text, self_tag}].
    Answers Jev fails on are counted and left out of the agreement. Raises jev.JevUnavailable without a key."""
    rows = [it for it in items if isinstance(it, dict) and str(it.get("text") or "").strip()]
    usage = jev.JevUsage()
    labs = jev_label_texts([_short(r["text"], 600) for r in rows], criteria,
                           "The state is one person's biggest hesitation about an offer, in their own words. "
                           "Pick the type of objection it expresses.", usage, parallel)
    pairs = [(r, lab) for r, lab in zip(rows, labs) if lab["ok"]]
    agree = sum(1 for r, lab in pairs if str(r.get("self_tag") or "").strip().lower() == lab["label"])
    models = Counter(lab["model"] for _, lab in pairs if lab.get("model"))
    model = models.most_common(1)[0][0] if models else None
    disagree = [{"id": r.get("id"), "text": _short(r["text"], 200), "self_tag": r.get("self_tag"), "jev": lab["label"]}
                for r, lab in pairs if str(r.get("self_tag") or "").strip().lower() != lab["label"]]
    return {"engine": "jev", "method": jev.method_label(model), "model": model, "asked": len(rows),
            "labelled": len(pairs), "failed": len(rows) - len(pairs), "agreement": wilson(agree, len(pairs)),
            "pairs": dict(Counter(f'{r.get("self_tag")}->{lab["label"]}' for r, lab in pairs).most_common()),
            "disagreements": disagree[:10], "usage": usage.snapshot()}


# --------------------------------------------------------------------------
# 1. Evidence search and cited answers
# --------------------------------------------------------------------------

def _load_json(folder: Optional[str], name: str) -> Any:
    if not folder:
        return None
    try:
        with open(os.path.join(folder, f"{name}.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def build_search_index(people: Optional[List[Dict[str, Any]]] = None, run_dir: Optional[str] = None,
                       sim_dir: Optional[str] = None, bundle: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Index every record present in `bundle`, `run_dir` or `sim_dir` (bundle first). Nothing is invented."""
    b = dict(bundle) if isinstance(bundle, dict) else {}
    names = ["config", "simulation_config", "survey", "thought_stream", "thought_harvest", "feed_test", "pitch",
             "actions", "gtm_suite", "research"] + [fname for _, fname, _, _ in run_search.TEST_RESULTS]
    for name in names:
        if b.get(name) is None:
            v = _load_json(run_dir, name)
            b[name] = v if v is not None else _load_json(sim_dir, name)
    docs = run_search.build_docs(b, people)
    return {
        "total_docs": len(docs),
        "by_type": dict(Counter(d["type"] for d in docs)),
        "by_concept": dict(Counter(c for d in docs for c in d["concepts"])),
        "ontology": {cid: {"label": label, "keywords": list(words)} for cid, (label, words) in run_search.CONCEPTS.items()},
        "docs": docs,
    }


def search_market_evidence(query: str, index_or_docs: Any, top_k: int = 12, doc_type: Optional[str] = None,
                           segment: Optional[str] = None, concept: Optional[str] = None) -> Dict[str, Any]:
    """Ranked records from the run (see claude_cli/run_search.py)."""
    return run_search.search(query, index_or_docs, top_k=top_k, doc_type=doc_type, segment=segment, concept=concept)


def _keep_refs(text: str, n: int) -> str:
    """Drop [#k] references that point past the citations given."""
    out = re.sub(r"\[#(\d+)\]", lambda m: m.group(0) if 1 <= int(m.group(1)) <= n else "", text or "")
    return re.sub(r"\s+([.,;:])", r"\1", " ".join(out.split()))


def ask_market_copilot(query: str, index_or_docs: Any, client: Any = None, model: str = "", top_k: int = 8) -> Dict[str, Any]:
    """Answer a question over the run's records with [#1], [#2] citations, written from the retrieved records only.
    Without a model, or when the call fails, answer_ok is false and the matching records are returned as they are."""
    search_res = search_market_evidence(query, index_or_docs, top_k=top_k)
    citations = [{"ref": f"[#{i}]", "id": h["id"], "type": h["type"], "type_label": h["type_label"], "title": h["title"],
                  "snippet": h["snippet"], "anchor": h["anchor"], "score": h.get("relevance_score", 0.0)}
                 for i, h in enumerate(search_res["results"][:6], start=1)]
    base = {"query": query, "citations": citations, "search": search_res}

    def failed(err: str) -> Dict[str, Any]:
        return {**base, "answer_ok": False, "cited_answer": "", "key_takeaways": [], "error": err}

    if not citations:
        return failed("no matching records in this run")
    if client is None or not model:
        return failed("no model connection: only the matching records are shown")
    lines = "\n".join(f"[#{i}] ({c['type_label']}) {c['title']}: {c['snippet']}" for i, c in enumerate(citations, 1))
    try:
        ans = write_once(client, model, (
            f"Question: {query}\n\nRecords from this run (use only these, cite them as [#1], [#2], and never invent "
            f"numbers or facts):\n{lines}\n\n"
            'Return JSON: {"answer": "2-3 sentences with [#1] citations", "key_points": ["..."]}'),
            max_tokens=450, temperature=0.2)
    except Exception as e:  # noqa: BLE001 - reported, not replaced
        return failed(str(e)[:200])
    ans = guard_numbers(ans, {"citations": citations, "total_matches": search_res["total_matches"]})
    text = _keep_refs(str(ans.get("answer") or ""), len(citations))
    if not text:
        return failed("the model returned no answer")
    points = [_keep_refs(_short(x, 300), len(citations)) for x in ans.get("key_points") or [] if isinstance(x, str)]
    return {**base, "answer_ok": True, "cited_answer": text, "key_takeaways": [p for p in points if p][:4]}


# --------------------------------------------------------------------------
# 2. How buyers would search (simulated)
# --------------------------------------------------------------------------

def _words(s: Any) -> List[str]:
    return re.findall(r"[a-z0-9]+", str(s or "").lower())


def _names(name: str, text: Any) -> bool:
    """True when the name appears in the text as whole words (in order)."""
    n, t = _words(name), _words(text)
    return bool(n) and any(t[i:i + len(n)] == n for i in range(len(t) - len(n) + 1))


def _need_description(need: Any, profile: Optional[Dict[str, Any]], o: Dict[str, str]) -> Tuple[str, str]:
    """The need shown before the offer, without the product's name: given, from the product profile, or the offer
    text with the name removed."""
    prof = profile or {}
    jobs = [str(x.get("job_to_be_done") or "").strip() for x in prof.get("for_whom") or [] if isinstance(x, dict)]
    for txt, source in ((str(need or ""), "given"),
                        ("; ".join(x for x in [str(prof.get("category") or "").strip()] + jobs[:2] if x), "product profile"),
                        (f"{o.get('headline', '')}. {o.get('text', '')}", "offer text without the product name")):
        if o.get("name"):
            txt = re.sub(re.escape(o["name"]), "", txt, flags=re.I)
        txt = " ".join(txt.split()).strip(" .;")
        if txt:
            return _short(txt, 400), source
    return "", ""


def run_geo_visibility_audit(client: Any, model: str, offer: Any = "", people: Optional[List[Dict[str, Any]]] = None,
                             need: str = "", competitors: Optional[List[Any]] = None, seed: int = 41,
                             cohort_size: int = 30, profile: Optional[Dict[str, Any]] = None, parallel: int = 8,
                             progress: Optional[Callable[[int, int], None]] = None) -> Dict[str, Any]:
    """How buyers would search (simulated). Two separate calls per person: before the offer (would they look for
    help, what they would type into an AI assistant or search engine, which options they already know) and after
    it (what they think it is, would they shortlist it, what they would check, which fact is missing)."""
    _need(client)
    meter = _meter(client)
    o = offer_dict(offer, profile)
    brand = o.get("name") or ""
    need_text, need_source = _need_description(need, profile, o)
    comps = competitor_list([competitors] if isinstance(competitors, str) else competitors, profile)
    cohort = sample_people(people or [], cohort_size, seed)

    jobs = []
    for p in cohort:
        jobs.append({"person": p, "step": "before", "prompt": (
            f"WHO YOU ARE\n{person_card(p)}\n\nSomething comes up in your life that relates to this need: {need_text}\n"
            "You have not seen any particular product or brand for it. If you looked for help, you would ask an AI "
            "assistant or a search engine. Answer as yourself.\n"
            'Return JSON: {"would_look_for_help": "yes|maybe|no", "search_query": "the exact question or search you '
            'would type, in your own words, or empty", "known_options": ["up to 3 products, brands or free ways you '
            'already know for this; an empty list if none"]}')})
        jobs.append({"person": p, "step": "after", "prompt": (
            f"WHO YOU ARE\n{person_card(p)}\n\nWhile looking into a need of yours, you come across this offer:\n"
            f"{offer_text(o)}\n\nAnswer as yourself.\n"
            'Return JSON: {"understood_category": "what kind of product you think this is, in a few words", '
            '"would_shortlist": "yes|maybe|no", "verify_question": "what you would ask an AI assistant or a search '
            'engine to check before trusting it", "missing_fact": "a fact you would need that the offer does not '
            f'state, or empty", "missing_type": "{"|".join(CONCERN_TYPES)}|none"}}')})
    asked = ask_people(meter, model, jobs, parallel, progress, max_tokens=400)
    before = [r for r in asked if r["ok"] and r["step"] == "before"]
    after = [r for r in asked if r["ok"] and r["step"] == "after"]
    nb, na = len(before), len(after)
    if not (nb or na):
        errs = "; ".join(sorted({str(r.get("error"))[:120] for r in asked if r.get("error")})[:3])
        raise RuntimeError(f"no simulated person answered ({len(asked)} calls failed{': ' + errs if errs else ''})")

    look = Counter(str(r["data"].get("would_look_for_help") or "").lower() for r in before)
    known: Counter = Counter()
    shown: Dict[str, str] = {}
    options_by_person = []
    for r in before:
        opts = r["data"].get("known_options")
        opts = [_short(x, 60) for x in (opts if isinstance(opts, list) else []) if isinstance(x, str) and x.strip()][:3]
        options_by_person.append(opts)
        for key, name in {x.lower(): x for x in opts}.items():
            known[key] += 1
            shown.setdefault(key, name)
    queries = [_short(r["data"].get("search_query"), 160) for r in before if str(r["data"].get("search_query") or "").strip()]

    shortlist = Counter(str(r["data"].get("would_shortlist") or "").lower() for r in after)
    verify = [_short(r["data"].get("verify_question"), 160) for r in after if str(r["data"].get("verify_question") or "").strip()]
    missing = []
    for r in after:
        mt = str(r["data"].get("missing_type") or "").strip().lower()
        fact = str(r["data"].get("missing_fact") or "").strip()
        if fact and mt != "none":
            missing.append((_ctype(mt) or "other", fact))

    summary: Dict[str, Any] = {
        "brand": brand, "need_shown": need_text, "need_source": need_source,
        "answered_before": nb, "answered_after": na,
        "would_look_for_help": {k: wilson(look.get(k, 0), nb) for k in ("yes", "maybe", "no")},
        "search_queries": queries[:12],
        "known_options": [{"name": shown[k], "count": c, "share": wilson(c, nb)} for k, c in known.most_common(10)],
        "named_the_brand_before": wilson(sum(1 for opts in options_by_person if any(_names(brand, x) for x in opts)), nb) if brand else None,
        "named_competitors_before": [{"name": c["name"], "share": wilson(sum(1 for opts in options_by_person
                                                                             if any(_names(c["name"], x) for x in opts)), nb)}
                                     for c in comps],
        "would_shortlist": {k: wilson(shortlist.get(k, 0), na) for k in ("yes", "maybe", "no")},
        "understood_as": [_short(r["data"].get("understood_category"), 120) for r in after if r["data"].get("understood_category")][:8],
        "verification_questions": verify[:10],
        "missing_facts": ranked(missing, na, top=len(CONCERN_TYPES)),
    }

    # Draft /llms.txt and FAQ answers strictly from the product facts, for the questions people asked
    questions = (verify + queries)[:6]
    if questions:
        facts = product_facts(profile, o)
        try:
            drafts = write_once(meter, model, (
                "Using ONLY the product facts below (do not invent prices, features, guarantees or statistics; if a "
                "question cannot be answered from the facts, say it is not stated yet), write:\n"
                "1. A concise `/llms.txt` markdown summary of the product.\n"
                "2. Up to 4 FAQ pairs answering the questions simulated buyers asked.\n\n"
                f"PRODUCT FACTS:\n{facts}\n\nQUESTIONS SIMULATED BUYERS ASKED:\n{json.dumps(questions, ensure_ascii=False)}\n\n"
                'Return JSON: {"llms_txt": "# Name\\n...", "faqs": [{"question": "...", "answer": "..."}], '
                '"unanswered_gaps": ["facts buyers asked for that the product facts do not state"]}'),
                max_tokens=1200, temperature=0.2)
            drafts = guard_numbers(drafts, {"facts": facts, "offer": o})
            summary["llms_txt"] = str(drafts.get("llms_txt") or "").strip()
            summary["faqs"] = [{"question": _short(x.get("question"), 200), "answer": _short(x.get("answer"), 600)}
                               for x in drafts.get("faqs") or [] if isinstance(x, dict) and x.get("question")][:5]
            summary["unanswered_gaps"] = [_short(x, 180) for x in drafts.get("unanswered_gaps") or [] if isinstance(x, str) and x][:6]
        except Exception as e:  # noqa: BLE001 - the people's answers stand without the drafts
            summary["drafts_error"] = str(e)[:200]
    return envelope("geo", asked, meter, cohort=len(cohort), summary=summary,
                    unit="answers received (two calls per person: before and after seeing the offer)")


# --------------------------------------------------------------------------
# 3. Real vs simulated concerns (VoC)
# --------------------------------------------------------------------------

def _norm(s: Any) -> str:
    s = str(s or "").lower().translate(str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"',
                                                      "–": "-", "—": "-"}))
    return " ".join(s.split()).strip(" \"'.,;:!?…")


def _concern(x: Any) -> str:
    """'none' stays 'none'; known concern types as they are; anything else answered is 'other'; empty is ''."""
    s = str(x or "").strip().lower().replace(" ", "_")
    return "none" if s == "none" else _ctype(s)


def _wilson_bounds(k: int, n: int, z: float = 1.96) -> Tuple[float, float, float]:
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, max(0.0, c - h), min(1.0, c + h)


def share_difference(k1: int, n1: int, k2: int, n2: int) -> Optional[Dict[str, Any]]:
    """p1 - p2 in percentage points with Newcombe's hybrid score 95% interval (from the two Wilson intervals)."""
    if not (n1 and n2):
        return None
    p1, l1, u1 = _wilson_bounds(k1, n1)
    p2, l2, u2 = _wilson_bounds(k2, n2)
    d = p1 - p2
    lo = d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    hi = d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return {"points": round(100 * d, 1), "lo": round(100 * lo, 1), "hi": round(100 * hi, 1),
            "method": "Newcombe hybrid score interval, 95%"}


def _review_texts(raw: Any) -> List[str]:
    if isinstance(raw, str):
        return [s.strip() for s in raw.splitlines() if len(s.strip()) >= 20]
    out = []
    for x in raw if isinstance(raw, list) else []:
        t = x if isinstance(x, str) else (str(x.get("text") or x.get("body") or "") if isinstance(x, dict) else "")
        if t.strip():
            out.append(t.strip())
    return out


def run_voc_grounding(client: Any, model: str, url: Optional[str] = None, raw_reviews: Any = None,
                      run_data: Optional[Dict[str, Any]] = None, parallel: int = 8,
                      progress: Optional[Callable[[int, int], None]] = None,
                      classifier: Optional[str] = None) -> Dict[str, Any]:
    """Compare the concerns in real text (`raw_reviews`, a public `url`, or `research` quotes in run_data) with the
    objections the simulated people raised. Both sides are classified by the same classifier: the model prompt
    (default) or, with classifier="jev", one Jev `choice` question over CONCERN_CRITERIA per text."""
    classifier = str(classifier or "model").strip().lower()
    if classifier not in CLASSIFIERS:
        raise ValueError(f"classifier must be one of {', '.join(CLASSIFIERS)}")
    use_jev = classifier == "jev"
    if use_jev and not jev.available():
        raise jev.JevUnavailable(f"Jev is not configured: {jev.settings()['reason']}")
    if not use_jev:
        _need(client)
    meter = _meter(client)
    rd = run_data or {}
    real: List[str] = []
    kind, source, real_label = "", "", ""
    if raw_reviews:
        real = [_short(x, 300) for x in _review_texts(raw_reviews)][:60]
        kind, source, real_label = "reviews", "passed reviews", "real customer quotes"
    elif url:
        snap = fetch_url_snapshot(url)
        real = [s.strip() for s in re.split(r"(?<=[.!?])\s+", snap.get("text") or "") if len(s.strip()) >= 30][:40]
        kind, source, real_label = "page", snap.get("url") or url, "page text"
    else:
        real = [_short(run_search.research_text(q), 300) for q in run_search.research_items(rd.get("research"))
                if run_search.research_text(q)][:60]
        kind, source, real_label = "research", "research quotes", "public posts and reviews (research)"
    if not real:
        return envelope("voc", [], meter, cohort=0, unit="texts classified by the model", summary={
            "available": False,
            "reason": "Pass reviews, a public url, or run `mirofish.py research` first so there is real text to compare against."})

    sim_all = [x["text"] for x in gather_objections(rd.get("survey"), rd.get("pitch"), rd.get("feed_test")) if x.get("text")]
    sim = sim_all[:60]
    unit = "texts classified by the Jev decision model" if use_jev else "texts classified by the model"
    if use_jev:
        texts = [(side, txt) for side, items in (("real", real), ("simulated", sim)) for txt in items]
        jusage = jev.JevUsage()
        labs = jev_label_texts([t for _, t in texts], CONCERN_CRITERIA, JEV_CONCERN_INSTRUCTIONS, jusage, parallel)
        asked = [{"person": {}, "side": side, "src": txt, "ok": lab["ok"], "data": {"concern_type": lab["label"] or ""},
                  "provider": "jev" if lab["ok"] else None, "model": lab["model"], "error": lab["error"]}
                 for (side, txt), lab in zip(texts, labs)]
        if progress:
            progress(len(asked), len(asked))
    else:
        asked = _voc_model_labels(meter, model, real, sim, parallel, progress)
    return _voc_summary(asked, meter, sim, sim_all, kind, source, real_label, unit,
                        {"classifier": "jev", "classifier_model": jev.method_label(_top_model(asked)),
                         "classifier_usage": jusage.snapshot()} if use_jev else {"classifier": "model"})


def _top_model(asked: List[Dict[str, Any]]) -> Optional[str]:
    models = Counter(r.get("model") for r in asked if r.get("ok") and r.get("model"))
    return models.most_common(1)[0][0] if models else None


def _voc_model_labels(meter: Any, model: str, real: List[str], sim: List[str], parallel: int,
                      progress: Optional[Callable[[int, int], None]]) -> List[Dict[str, Any]]:
    jobs = [{"person": {}, "side": side, "src": txt, "system": CLASSIFIER_SYSTEM, "prompt": (
        f"Text:\n\"{txt}\"\n\n"
        "Which one concern does this text mainly express? Use none when it expresses no concern (for example praise, "
        "a plain description or an unrelated remark).\n"
        f'Return JSON: {{"concern_type": "{"|".join(CONCERN_TYPES)}|none", '
        '"key_phrase": "the few words of the text that show it, copied exactly, or empty", '
        '"plain_meaning": "one short sentence"}')}
        for side, texts in (("real", real), ("simulated", sim)) for txt in texts]
    return ask_people(meter, model, jobs, parallel, progress, max_tokens=220, temperature=0.1)


def _voc_summary(asked: List[Dict[str, Any]], meter: Any, sim: List[str], sim_all: List[str],
                 kind: str, source: str, real_label: str, unit: str, classifier: Dict[str, Any]) -> Dict[str, Any]:
    use_jev = classifier.get("classifier") == "jev"

    def side_counts(side: str):
        rows = [r for r in asked if r["side"] == side]
        ok = [r for r in rows if r["ok"]]
        labelled = [(r, _concern(r["data"].get("concern_type"))) for r in ok]
        labelled = [(r, t) for r, t in labelled if t]
        stats = {"texts": len(rows), "classified": len(labelled), "failed": len(rows) - len(ok),
                 "no_label": len(ok) - len(labelled)}
        return labelled, Counter(t for _, t in labelled), stats

    real_lab, real_counts, real_stats = side_counts("real")
    sim_lab, sim_counts, sim_stats = side_counts("simulated")
    nr, ns = real_stats["classified"], sim_stats["classified"]
    sim_stats["available_in_run"] = len(sim_all)
    comparison = [{"concern": k, "real": wilson(real_counts[k], nr), "simulated": wilson(sim_counts[k], ns),
                   "difference": share_difference(real_counts[k], nr, sim_counts[k], ns)}
                  for k in CONCERN_TYPES + ("none",) if real_counts[k] or sim_counts[k]]
    comparison.sort(key=lambda c: -max(c["real"]["pct"] or 0, c["simulated"]["pct"] or 0))

    phrases = []
    for r, t in ([] if use_jev else real_lab):       # Jev returns a label, not a phrase
        if t == "none" or len(phrases) >= 12:
            continue
        ph = _short(r["data"].get("key_phrase"), 160)
        copied = bool(_norm(ph)) and _norm(ph) in _norm(r["src"])
        phrases.append({"concern": t, "phrase": ph if copied else _short(r["src"], 200), "copied_from_text": copied,
                        "meaning": guard_numbers(_short(r["data"].get("plain_meaning"), 160), {"text": r["src"]})})

    summary = {
        "available": True, "source": source, "source_kind": kind, "real_label": real_label,
        "real": real_stats, "simulated": sim_stats,
        "comparison": comparison,
        "real_concerns": ranked([(t, r["src"]) for r, t in real_lab if t != "none"], nr, top=len(CONCERN_TYPES)),
        "simulated_concerns": ranked([(t, r["src"]) for r, t in sim_lab if t != "none"], ns, top=len(CONCERN_TYPES)),
        "phrases": phrases,
        "method": (("Every text, real and simulated, was labelled by the same Jev decision model question "
                    f"({classifier.get('classifier_model')}): one choice over the concern types, including none. "
                    if use_jev else "Every text, real and simulated, was labelled by the same classifier prompt. ")
                   + "Shares are Wilson 95% ranges; the difference (real minus simulated, in points) uses Newcombe's "
                     "hybrid score interval."),
        **classifier,
    }
    if not sim:
        summary["simulated_note"] = "This run has no survey, pitch or feed-test objections yet, so there is nothing simulated to compare."
    return envelope("voc", asked, meter, cohort=nr, summary=summary, unit=unit)


# --------------------------------------------------------------------------
# 4. Word-of-mouth cascade
# --------------------------------------------------------------------------

CHANNELS = {"direct_message": "sends you a direct message", "family_chat": "posts in your family group chat",
            "work_chat": "posts in a work chat", "social_post": "shares a post", "in_person": "mentions it to you in person"}
SCORE = {"yes": 1.0, "maybe": 0.5, "no": 0.0}


def run_dark_social_cascade(client: Any, model: str, people: List[Dict[str, Any]], offer: Any = "", seed: int = 47,
                            cohort_size: int = 36, profile: Optional[Dict[str, Any]] = None, parallel: int = 8,
                            progress: Optional[Callable[[int, int], None]] = None) -> Dict[str, Any]:
    """Wave 1: would each person privately pass the offer on, and what would they write. Wave 2 (other people): the
    cold offer and a friend's forward of a wave-1 message, in two separate calls per person in random order; the
    per-person difference (friend minus cold, yes=1, maybe=0.5, no=0) gets a 95% range."""
    _need(client)
    meter = _meter(client)
    o = offer_dict(offer, profile)
    cohort = sample_people(people, cohort_size, seed)
    wave1 = cohort[: len(cohort) // 2] if len(cohort) >= 2 else cohort
    wave2 = cohort[len(wave1):]
    total = len(wave1) + (2 * len(wave2) if len(wave2) >= 2 else 0)
    done = [0]

    def prog(_d, _t):
        done[0] += 1
        if progress:
            progress(done[0], max(total, done[0]))

    asked1 = ask_people(meter, model, [{"person": p, "prompt": (
        f"WHO YOU ARE\n{person_card(p)}\n\nYOU SEE THIS OFFER\n{offer_text(o)}\n\n"
        "Would you mention, screenshot or forward this to anyone in private (for example a partner, a family chat, a "
        "friend group, a colleague in a direct message), or to nobody? Be realistic: most ads do not get shared.\n"
        f'Return JSON: {{"would_share": "yes|maybe|no", "channel": "{"|".join(CHANNELS)}|none", '
        '"who": "who you would tell, or nobody", '
        '"message_you_would_send": "the exact message you would send, in your own words, or empty if you would not share", '
        '"why": "one sentence"}')} for p in wave1], parallel, prog, max_tokens=400)
    ok1 = [r for r in asked1 if r["ok"]]
    n1 = len(ok1)
    sharers = [r for r in ok1 if str(r["data"].get("would_share") or "").lower() in ("yes", "maybe")]
    shares = Counter(str(r["data"].get("would_share") or "").lower() for r in ok1)
    channels = Counter(str(r["data"].get("channel") or "none").lower() for r in sharers)
    forwards = [{"from_name": r["person"].get("name"), "from_segment": r["person"].get("segment"),
                 "channel": str(r["data"].get("channel") or "").lower(), "who": _short(r["data"].get("who"), 80),
                 "message": _short(r["data"].get("message_you_would_send"), 220)}
                for r in sharers if str(r["data"].get("message_you_would_send") or "").strip()]

    asked2: List[Dict[str, Any]] = []
    if len(wave2) < 2:
        wave2_summary: Dict[str, Any] = {"available": False, "reason": (
            f"Wave 2 needs at least 2 people who were not in wave 1; this cohort of {len(cohort)} leaves {len(wave2)}.")}
    elif not forwards:
        wave2_summary = {"available": False, "reason": "Nobody in wave 1 wrote a message they would pass on, so there was nothing to forward."}
    else:
        rng = random.Random(seed)
        jobs = []
        for i, p in enumerate(wave2):
            m = forwards[i % len(forwards)]
            pair = [
                {"person": p, "arm": "cold", "prompt": (
                    f"WHO YOU ARE\n{person_card(p)}\n\nThis ad appears in your feed:\n{offer_text(o)}\n\n"
                    "Would you try it?\n"
                    'Return JSON: {"would_try": "yes|maybe|no", "reaction": "one sentence in your own words"}')},
                {"person": p, "arm": "friend", "forward": m, "prompt": (
                    f"WHO YOU ARE\n{person_card(p)}\n\nA friend {CHANNELS.get(m['channel'], 'sends you a message')}:\n"
                    f"\"{m['message']}\"\n\nWhen you look it up, this is the offer:\n{offer_text(o)}\n\n"
                    "Would you try it?\n"
                    'Return JSON: {"would_try": "yes|maybe|no", "reaction": "one sentence in your own words", '
                    '"would_forward_again": "yes|maybe|no"}')},
            ]
            rng.shuffle(pair)
            jobs += pair
        asked2 = ask_people(meter, model, jobs, parallel, prog, max_tokens=300)
        by_person: Dict[Any, Dict[str, Dict[str, Any]]] = {}
        for r in asked2:
            if r["ok"]:
                by_person.setdefault(r["person"].get("agent_id"), {})[r["arm"]] = r["data"]
        pairs = [(SCORE.get(str(a.get("friend", {}).get("would_try") or "").lower()),
                  SCORE.get(str(a.get("cold", {}).get("would_try") or "").lower())) for a in by_person.values()]
        pairs = [(f, c) for f, c in pairs if f is not None and c is not None]
        diff = mean_ci([f - c for f, c in pairs])
        friend_ans = [a["friend"] for a in by_person.values() if "friend" in a]
        n_pairs = len(pairs)
        wave2_summary = {
            "available": True, "people": len(wave2), "paired": n_pairs,
            "friend_minus_cold": {**diff, "verdict": verdict_from_ci(diff),
                                  "metric": "would try (yes=1, maybe=0.5, no=0): friend's forward minus cold ad, same people"},
            "would_try_cold": {k: wilson(sum(1 for _, c in pairs if c == SCORE[k]), n_pairs) for k in SCORE},
            "would_try_from_friend": {k: wilson(sum(1 for f, _ in pairs if f == SCORE[k]), n_pairs) for k in SCORE},
            "would_forward_again": {k: wilson(sum(1 for a in friend_ans if str(a.get("would_forward_again") or "").lower() == k),
                                              len(friend_ans)) for k in SCORE},
            "reactions_to_forward": [_short(a.get("reaction"), 180) for a in friend_ans if a.get("reaction")][:6],
        }
    if progress and total:
        progress(max(total, done[0]), max(total, done[0]))

    summary = {
        "wave1_people": n1,
        "would_share": {k: wilson(shares.get(k, 0), n1) for k in ("yes", "maybe", "no")},
        "channels": [{"channel": k, "count": c, "share": wilson(c, n1)} for k, c in channels.most_common()],
        "forwarded_messages": forwards[:8],
        "why_or_why_not": [_short(r["data"].get("why"), 180) for r in ok1 if r["data"].get("why")][:8],
        "wave2_peer_pickup": wave2_summary,
    }
    return envelope("cascade", asked1 + asked2, meter, cohort=len(cohort), summary=summary,
                    unit="answers received (wave 2 people answer twice)")
