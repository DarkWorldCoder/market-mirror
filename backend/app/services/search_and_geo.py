"""
search_and_geo.py - evidence search across a run, plus AI search visibility (GEO), real-vs-simulated
voice comparison (VoC), and word-of-mouth cascade tests answered by the simulated people.

  * build_search_index / search_market_evidence / ask_market_copilot: indexes what the run actually produced
    (persona cards, survey objections, pitch replies, feed-test and landing-page thoughts, social posts,
    research quotes, and GTM / CRO test answers) and ranks them with BM25 + buyer-concern synonym expansion.
    Nothing is invented when a file is absent.
  * run_geo_visibility_audit: asks each simulated person in the cohort what they would type into an AI
    assistant or search engine when looking for this kind of product, which options they already know,
    and what is unclear in the offer facts; then tests those real queries to measure how often the brand
    is mentioned or recommended and drafts an `/llms.txt` and `FAQPage` JSON-LD strictly from the product facts.
  * run_voc_grounding: compares the objections raised by the simulated people against real customer voices
    from `research.json`, `raw_reviews`, or a public `url` (using `wilson` intervals for both).
  * run_dark_social_cascade: asks each simulated person whether they would privately forward or mention the
    offer (and what they would write), then shows those real forwarded messages to a second wave of people
    to measure peer-referral pickup versus cold exposure.
"""

from __future__ import annotations

import json
import math
import os
import random
import re
from collections import Counter, defaultdict
from typing import Any, Callable, Dict, List, Optional, Tuple

from .cro_and_sparring import fetch_url_snapshot
from .gtm_suite import (
    CONCERN_TYPES,
    _ctype,
    _f,
    _meter,
    _need,
    _short,
    ask_people,
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


# --------------------------------------------------------------------------
# 1. Buyer-concern synonym & concept ontology for hybrid BM25 search
# --------------------------------------------------------------------------

CONCEPT_ONTOLOGY: Dict[str, Dict[str, Any]] = {
    "price": {
        "label": "Price, budget & payment terms",
        "keywords": [
            "price", "pricing", "cost", "expensive", "cheap", "affordable", "budget",
            "wallet", "money", "weekly", "monthly", "annual", "subscription", "tier",
            "plan", "discount", "value", "worth", "fee", "pay", "payday", "spend",
            "discretionary", "free", "trial",
        ],
    },
    "trust": {
        "label": "Trust, proof, card & cancellation risk",
        "keywords": [
            "trust", "trustworthy", "credible", "scam", "skeptical", "proof", "review",
            "reviews", "testimonial", "guarantee", "refund", "cancel", "cancellation",
            "card", "credit", "debit", "auto-renew", "autorenew", "trap", "charge",
            "billing", "privacy", "security", "risk", "safe", "signup", "sign-up",
            "hesitate", "checkout", "abandon", "stopper", "dealbreaker",
        ],
    },
    "authority": {
        "label": "Household, partner, boss & committee approval",
        "keywords": [
            "spouse", "husband", "wife", "partner", "parents", "family", "household",
            "shared", "couple", "committee", "boss", "manager", "cfo", "finance",
            "blocker", "champion", "approval", "permission", "ask", "consult", "team",
        ],
    },
    "habit": {
        "label": "Routine, effort, time & retention",
        "keywords": [
            "habit", "routine", "streak", "quit", "drop", "churn", "retention",
            "consistent", "busy", "tired", "fatigue", "schedule", "shift", "time",
            "effort", "hard", "easy", "simple", "onboarding", "setup", "daily",
        ],
    },
    "competitor": {
        "label": "Competitors, free alternatives & switching",
        "keywords": [
            "competitor", "competitors", "alternative", "alternatives", "already",
            "using", "switch", "switching", "compare", "comparison", "versus", "vs",
            "better", "different", "unique", "youtube", "free", "incumbent", "status",
        ],
    },
    "unclear": {
        "label": "Clarity, confusion & missing details",
        "keywords": [
            "unclear", "confusing", "confused", "understand", "what", "how", "work",
            "works", "explain", "headline", "copy", "landing", "page", "missing",
            "detail", "details", "vague", "jargon",
        ],
    },
    "relevance": {
        "label": "Relevance, audience fit & need",
        "keywords": [
            "relevant", "relevance", "need", "fit", "for", "audience", "segment",
            "useful", "problem", "solve", "goal", "match", "interest",
        ],
    },
}

_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "do", "does", "for",
    "from", "has", "have", "how", "i", "if", "in", "into", "is", "it", "its",
    "my", "no", "not", "of", "on", "or", "our", "so", "such", "that", "the",
    "their", "them", "then", "there", "these", "they", "this", "to", "us", "was",
    "we", "what", "when", "where", "which", "who", "why", "will", "with", "would",
    "you", "your", "can", "could", "should", "about", "people", "users", "buyers",
}


def _tokenize(text: str) -> List[str]:
    if not text:
        return []
    raw = re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)?", str(text).lower())
    return [t for t in raw if len(t) > 1 and t not in _STOPWORDS]


def detect_concepts(text: str) -> List[str]:
    low = str(text or "").lower()
    tokens = set(_tokenize(low))
    matched: List[str] = []
    for cid, spec in CONCEPT_ONTOLOGY.items():
        if any(kw in tokens or (len(kw) >= 5 and kw in low) for kw in spec["keywords"]):
            matched.append(cid)
    return matched


def expand_query_concepts(query: str) -> Dict[str, Any]:
    base_tokens = _tokenize(query)
    matched = detect_concepts(query)
    expanded = list(dict.fromkeys(base_tokens))
    labels: List[str] = []
    for cid in matched:
        spec = CONCEPT_ONTOLOGY[cid]
        labels.append(spec["label"])
        for kw in spec["keywords"][:12]:
            if kw not in expanded:
                expanded.append(kw)
    return {
        "query": query,
        "base_tokens": base_tokens,
        "matched_concepts": matched,
        "concept_labels": labels,
        "expanded_tokens": expanded,
    }


# --------------------------------------------------------------------------
# 2. Multi-artifact search indexer & hybrid BM25 + concept ranker
# --------------------------------------------------------------------------

def _load_json(folder: Optional[str], name: str) -> Any:
    if not folder:
        return None
    path = os.path.join(folder, name if name.endswith(".json") else f"{name}.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def build_search_index(
    people: Optional[List[Dict[str, Any]]] = None,
    run_dir: Optional[str] = None,
    sim_dir: Optional[str] = None,
    bundle: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Index every real artifact present in `bundle`, `run_dir`, or `sim_dir`. Nothing is invented."""
    b = dict(bundle or {})

    def get(name: str) -> Any:
        if name in b and b[name] is not None:
            return b[name]
        return _load_json(run_dir, name) or _load_json(sim_dir, name)

    cfg = get("config") or get("simulation_config") or {}
    if isinstance(cfg, dict) and "data" in cfg and isinstance(cfg["data"], dict):
        cfg = cfg["data"]
    if people is None:
        people = [p for p in (cfg.get("persona_index") or []) if isinstance(p, dict)]

    by_id: Dict[Any, Dict[str, Any]] = {}
    for p in people or []:
        if isinstance(p, dict) and p.get("agent_id") is not None:
            by_id[p["agent_id"]] = p

    docs: List[Dict[str, Any]] = []

    def add_doc(doc_id: str, doc_type: str, type_label: str, title: str, snippet: str,
                text: str = "", segment: str = "", verdict: str = "", anchor: str = "#top",
                meta: str = "") -> None:
        snip = _short(snippet, 260)
        if not snip:
            return
        full = f"{title} {segment} {verdict} {snip} {text}".strip()
        docs.append({
            "id": doc_id,
            "type": doc_type,
            "type_label": type_label,
            "title": _short(title, 120),
            "segment": str(segment or ""),
            "verdict": str(verdict or ""),
            "snippet": snip,
            "text": _short(full, 900),
            "anchor": anchor,
            "concepts": detect_concepts(full),
            "meta": _short(meta, 120),
        })

    # 1. Personas from persona_index
    for idx, p in enumerate((people or [])[:250]):
        aid = p.get("agent_id", idx + 1)
        name = p.get("name") or f"Person {aid}"
        seg = p.get("segment") or ""
        country = p.get("country") or p.get("city") or ""
        occ = p.get("occupation") or p.get("profession") or ""
        bde = p.get("bde") if isinstance(p.get("bde"), dict) else {}
        bde_txt = json.dumps(bde, ensure_ascii=False) if bde else ""
        persona_txt = str(p.get("persona") or p.get("bio") or "").strip()
        if not (persona_txt or bde_txt):
            continue
        add_doc(
            doc_id=f"persona-{aid}",
            doc_type="persona",
            type_label="Person",
            title=", ".join(str(x) for x in (name, occ, country) if x),
            snippet=persona_txt or bde_txt,
            text=f"{persona_txt} {bde_txt}",
            segment=seg,
            verdict=str(p.get("model_provider") or ""),
            anchor="#agents",
            meta=f"agent #{aid}",
        )

    # 2. Survey responses
    survey = get("survey")
    if isinstance(survey, dict):
        for idx, r in enumerate((survey.get("responses") or [])[:250]):
            if not isinstance(r, dict):
                continue
            a = r.get("answer") if isinstance(r.get("answer"), dict) else {}
            obj = str(a.get("main_objection") or a.get("reasoning") or a.get("comment") or "").strip()
            if not obj:
                continue
            aid = r.get("agent_id")
            p = by_id.get(aid, {})
            name = r.get("name") or p.get("name") or f"Person {aid}"
            seg = r.get("segment") or p.get("segment") or ""
            wc = str(a.get("would_convert") or "").upper()
            otype = str(a.get("objection_type") or "")
            add_doc(
                doc_id=f"survey-{aid}-{idx}",
                doc_type="survey",
                type_label="Survey answer",
                title=f"{name} ({seg})" if seg else str(name),
                snippet=obj,
                text=json.dumps(a, ensure_ascii=False),
                segment=seg,
                verdict=wc,
                anchor="#voices",
                meta=f"objection: {otype}" if otype else "survey",
            )

    # 3. Thought stream & harvested thoughts
    for t_key in ("thought_stream", "thought_harvest"):
        ts = get(t_key)
        if isinstance(ts, dict):
            for idx, e in enumerate((ts.get("entries") or [])[:250]):
                if not isinstance(e, dict) or not str(e.get("text") or "").strip():
                    continue
                aid = e.get("agent_id")
                name = e.get("name") or f"Person {aid}"
                seg = e.get("segment") or ""
                src = e.get("source") or "thought"
                did = e.get("would_do") or e.get("did") or ""
                weigh = e.get("weighing") or ""
                add_doc(
                    doc_id=f"thought-{t_key}-{idx}",
                    doc_type="thought",
                    type_label=f"Thought ({src})",
                    title=f"{name} ({seg})" if seg else str(name),
                    snippet=f"{e['text']}" + (f" → {did}" if did else ""),
                    text=f"{e['text']} {weigh} {did} {e.get('gut', '')} {e.get('roadblock', '')}",
                    segment=seg,
                    verdict=str(e.get("private_verdict") or e.get("gut") or "").upper(),
                    anchor="#thoughts",
                    meta=f"{src} · {e.get('roadblock') or e.get('kind') or ''}".strip(" ·"),
                )

    # 4. Feed test thoughts & landing drop reasons
    ft = get("feed_test")
    if isinstance(ft, dict):
        first_seed = ft.get("seed")
        for idx, s in enumerate((ft.get("sessions") or [])[:200]):
            if not isinstance(s, dict) or (first_seed is not None and s.get("seed") not in (None, first_seed)):
                continue
            ad = s.get("ad") or {}
            land = s.get("landing") or {}
            th = str(land.get("thought") or ad.get("thought") or "").strip()
            if not th:
                continue
            name = s.get("name") or f"Person {s.get('agent_id')}"
            seg = s.get("segment") or ""
            verdict = "CONVERTED" if land.get("completed") else ("CLICKED" if ad.get("click") else "SCROLLED")
            add_doc(
                doc_id=f"feed-{idx}",
                doc_type="feed_test",
                type_label="Feed & landing",
                title=f"{name} on {s.get('creative_id') or 'ad'}",
                snippet=th + (f" (Drop reason: {land['drop_reason']})" if land.get("drop_reason") else ""),
                text=f"{th} {land.get('drop_reason', '')}",
                segment=seg,
                verdict=verdict,
                anchor="#feedtest",
                meta=str(s.get("platform") or ""),
            )

    # 5. Pitch replies
    pitch = get("pitch")
    if isinstance(pitch, dict):
        for idx, r in enumerate((pitch.get("people") or [])[:150]):
            if not isinstance(r, dict):
                continue
            t1 = r.get("turn1") or {}
            rep = str(t1.get("reply") or "").strip()
            if not rep:
                continue
            name = r.get("name") or f"Person {r.get('agent_id')}"
            seg = r.get("segment") or ""
            add_doc(
                doc_id=f"pitch-{idx}",
                doc_type="pitch",
                type_label="Pitch reply",
                title=f"{name} ({seg})" if seg else str(name),
                snippet=rep,
                text=f"{rep} {t1.get('thought', '')} {t1.get('objection', '')}",
                segment=seg,
                verdict=str(r.get("final_verdict") or t1.get("verdict") or "").upper(),
                anchor="#pitch",
                meta=f"lead score: {r.get('lead_score', '–')}",
            )

    # 6. Social actions (posts & comments)
    acts = get("actions")
    if isinstance(acts, dict):
        acts = acts.get("actions")
    for idx, a in enumerate((acts or [])[:150]):
        if not isinstance(a, dict):
            continue
        args = a.get("action_args") or {}
        content = str(args.get("content") or args.get("quote_content") or a.get("content") or "").strip()
        if not content:
            continue
        aid = a.get("agent_id")
        p = by_id.get(aid, {})
        name = a.get("agent_name") or p.get("name") or f"Person {aid}"
        seg = p.get("segment") or ""
        atype = str(a.get("action_type") or "POST")
        add_doc(
            doc_id=f"social-{idx}",
            doc_type="social_post",
            type_label="Social post",
            title=f"{name} ({atype.lower().replace('_', ' ')})",
            snippet=content,
            text=f"{content} {a.get('thought', '')}",
            segment=seg,
            verdict=atype,
            anchor="#posts",
            meta=f"{a.get('platform', '')} round {a.get('round_num', '?')}".strip(),
        )

    # 7. GTM & CRO test outputs (when present)
    suite = get("gtm_suite")
    engines = (suite.get("engines") if isinstance(suite, dict) else None) or {}
    for key, fname, anchor, label in (
        ("committee", "buying_committee", "#gtm", "Buying committee"),
        ("creative", "creative_optimizer", "#gtm", "Creative test"),
        ("battlecard", "sales_battlecard", "#gtm", "Sales battlecard"),
        ("journey", "journey_sim", "#gtm", "Customer journey"),
        ("pricing", "pricing_conjoint", "#gtm", "Pricing choice"),
        ("competitors", "competitor_intel", "#competitors", "Competitor choice"),
        ("teardown", "landing_teardown", "#cro-lab", "Landing teardown"),
        ("roleplay", "sales_roleplay", "#cro-lab", "Sales roleplay"),
        ("whatif", "causal_whatif", "#cro-lab", "What-if choice"),
        ("personalize", "segment_personalization", "#cro-lab", "Tailored ads"),
        ("geo", "geo_visibility", "#search-geo", "AI search (GEO)"),
        ("voc", "voc_grounding", "#search-geo", "Real vs simulated voices"),
        ("cascade", "dark_social", "#search-geo", "Word-of-mouth cascade"),
    ):
        res = get(fname) or engines.get(key)
        if not isinstance(res, dict) or not res.get("summary"):
            continue
        s = res["summary"]
        add_doc(
            doc_id=f"gtm-summary-{key}",
            doc_type=key,
            type_label=label,
            title=f"{label} ({res.get('answered', 0)} people answered)",
            snippet=json.dumps(s, ensure_ascii=False)[:250],
            text=json.dumps(s, ensure_ascii=False)[:900],
            segment="All audiences",
            verdict=f"{res.get('answered', 0)}/{res.get('asked', 0)}",
            anchor=anchor,
            meta=label,
        )

    # 8. External research voices (if `research.json` exists)
    research = get("research")
    if isinstance(research, dict):
        for idx, v in enumerate((research.get("voices") or research.get("items") or [])[:120]):
            if not isinstance(v, dict):
                continue
            txt = str(v.get("text") or v.get("body") or v.get("title") or "").strip()
            if not txt:
                continue
            src = str(v.get("source") or v.get("platform") or "web")
            add_doc(
                doc_id=f"research-{idx}",
                doc_type="research",
                type_label="Real customer voice",
                title=str(v.get("title") or f"Voice from {src}")[:100],
                snippet=txt,
                text=txt,
                segment=src,
                verdict="REAL VOICE",
                anchor="#evidence",
                meta=src,
            )

    by_type = Counter(d["type"] for d in docs)
    by_concept = Counter(c for d in docs for c in d.get("concepts", []))
    return {
        "total_docs": len(docs),
        "by_type": dict(by_type),
        "by_concept": dict(by_concept),
        "ontology": {
            cid: {"label": spec["label"], "keywords": spec["keywords"][:14]}
            for cid, spec in CONCEPT_ONTOLOGY.items()
        },
        "docs": docs,
    }


def search_market_evidence(
    query: str,
    index_or_docs: Any,
    top_k: int = 12,
    doc_type: Optional[str] = None,
    segment: Optional[str] = None,
) -> Dict[str, Any]:
    """Hybrid BM25 + concept-synonym search over the run's real indexed artifacts."""
    docs: List[Dict[str, Any]]
    if isinstance(index_or_docs, dict):
        docs = list(index_or_docs.get("docs") or [])
    elif isinstance(index_or_docs, list):
        docs = list(index_or_docs)
    else:
        docs = []

    if doc_type and doc_type.lower() not in ("all", "*"):
        docs = [d for d in docs if d.get("type") == doc_type]
    if segment and segment.lower() not in ("all", "*"):
        docs = [d for d in docs if segment.lower() in str(d.get("segment", "")).lower()]

    expansion = expand_query_concepts(query)
    base_tokens = expansion["base_tokens"]
    expanded_tokens = expansion["expanded_tokens"]
    matched_concepts = set(expansion["matched_concepts"])
    q_low = (query or "").strip().lower()

    if not docs:
        return {"query": query, "expansion": expansion, "total_matches": 0, "results": []}
    if not base_tokens and not q_low:
        return {"query": query, "expansion": expansion, "total_matches": len(docs), "results": docs[:top_k]}

    doc_tokens_list: List[List[str]] = []
    df: Counter = Counter()
    for d in docs:
        toks = _tokenize(f"{d.get('title', '')} {d.get('snippet', '')} {d.get('text', '')}")
        doc_tokens_list.append(toks)
        for t in set(toks):
            df[t] += 1

    n_docs = len(docs)
    avgdl = sum(len(t) for t in doc_tokens_list) / max(1, n_docs)
    k1, b = 1.5, 0.75

    scored: List[Tuple[float, Dict[str, Any]]] = []
    for idx, d in enumerate(docs):
        toks = doc_tokens_list[idx]
        tf = Counter(toks)
        dl = len(toks)
        score = 0.0

        for qt in base_tokens:
            f = tf.get(qt, 0)
            if f > 0:
                idf = math.log(1.0 + (n_docs - df[qt] + 0.5) / (df[qt] + 0.5))
                denom = f + k1 * (1.0 - b + b * (dl / max(1.0, avgdl)))
                score += 2.5 * idf * ((f * (k1 + 1.0)) / denom)
            elif any(qt in tok or tok in qt for tok in tf if len(qt) >= 4 and len(tok) >= 4):
                score += 1.0

        for syn in expanded_tokens:
            if syn in base_tokens:
                continue
            if tf.get(syn, 0) > 0:
                idf = math.log(1.0 + (n_docs - df[syn] + 0.5) / (df[syn] + 0.5))
                score += 0.55 * idf

        overlap = matched_concepts & set(d.get("concepts") or [])
        if overlap:
            score += 2.0 * len(overlap)

        title_low = str(d.get("title", "")).lower()
        snip_low = str(d.get("snippet", "")).lower()
        if len(q_low) >= 3 and (q_low in title_low or q_low in snip_low):
            score += 3.5

        if score > 0:
            item = dict(d)
            item["relevance_score"] = round(score, 2)
            item["matched_concepts"] = [
                CONCEPT_ONTOLOGY[c]["label"] for c in overlap if c in CONCEPT_ONTOLOGY
            ]
            scored.append((score, item))

    scored.sort(key=lambda x: x[0], reverse=True)
    return {
        "query": query,
        "expansion": expansion,
        "total_matches": len(scored),
        "results": [item for _, item in scored[:top_k]],
    }


def ask_market_copilot(
    query: str,
    index_or_docs: Any,
    client: Any = None,
    model: str = "",
    top_k: int = 8,
) -> Dict[str, Any]:
    """Answer a question over the run's evidence with inline [#1], [#2] citations.
    When `client` is passed, uses `write_once` + `guard_numbers` over the retrieved items only;
    otherwise returns the matched items and their counts without inventing prose."""
    search_res = search_market_evidence(query, index_or_docs, top_k=top_k)
    hits = search_res["results"]
    citations = [
        {
            "ref": f"[#{i}]",
            "id": h["id"],
            "type": h["type"],
            "type_label": h["type_label"],
            "title": h["title"],
            "snippet": h["snippet"],
            "anchor": h["anchor"],
            "score": h.get("relevance_score", 0.0),
        }
        for i, h in enumerate(hits[:6], start=1)
    ]
    if not citations:
        return {
            "query": query,
            "cited_answer": "No matching records in this run for that query.",
            "citations": [],
            "search": search_res,
        }

    if client is not None and model:
        try:
            meter = _meter(client)
            lines = "\n".join(f"[#{i}] ({c['type_label']}) {c['title']}: {c['snippet']}" for i, c in enumerate(citations, 1))
            ans = write_once(
                meter,
                model,
                (
                    f"Question: {query}\n\nEvidence from this run (use only these items, cite them as [#1], [#2], "
                    "and never invent numbers or facts):\n"
                    f"{lines}\n\n"
                    'Return JSON: {"answer": "2-3 sentences with [#1] citations", "key_points": ["..."]}'
                ),
                max_tokens=450,
                temperature=0.2,
            )
            ans = guard_numbers(ans, {"citations": citations, "total_matches": search_res["total_matches"]})
            if isinstance(ans, dict) and str(ans.get("answer") or "").strip():
                return {
                    "query": query,
                    "cited_answer": str(ans["answer"]).strip(),
                    "key_takeaways": [str(x) for x in (ans.get("key_points") or [])[:4]],
                    "citations": citations,
                    "search": search_res,
                }
        except Exception:
            pass

    # Factual, non-invented summary of the retrieved items
    top_parts = [f"{c['ref']} {c['title']}: “{c['snippet']}”" for c in citations[:3]]
    return {
        "query": query,
        "cited_answer": f"{search_res['total_matches']} matching records in this run. Top matches: " + " · ".join(top_parts),
        "key_takeaways": [f"{c['ref']} ({c['type_label']}) {c['title']}: {c['snippet']}" for c in citations[:4]],
        "citations": citations,
        "search": search_res,
    }


# --------------------------------------------------------------------------
# 3. AI Search Visibility & Generative Engine Optimization (GEO) test
# --------------------------------------------------------------------------

def run_geo_visibility_audit(
    client: Any,
    model: str,
    offer: Any = "",
    people: Optional[List[Dict[str, Any]]] = None,
    queries: Optional[List[str]] = None,
    competitors: Optional[List[Any]] = None,
    seed: int = 41,
    cohort_size: int = 30,
    profile: Optional[Dict[str, Any]] = None,
    parallel: int = 8,
    progress: Optional[Callable[[int, int], None]] = None,
) -> Dict[str, Any]:
    """One call per person: how they would search for this in an AI assistant or search engine, which options
    they already know before seeing the offer, and what facts are missing from the offer for an AI answer or FAQ."""
    _need(client)
    meter = _meter(client)
    o = offer_dict(offer, profile)
    facts = product_facts(profile, o)
    brand = o.get("name") or o.get("headline")[:40]
    cohort = sample_people(people or [], cohort_size, seed)

    jobs = [
        {
            "person": p,
            "prompt": (
                f"WHO YOU ARE\n{person_card(p)}\n\n"
                "STEP 1 — Before you see any specific brand, imagine you have the problem or need this kind of product "
                "solves and you ask an AI assistant (like ChatGPT, Perplexity or Gemini) or a search engine for help.\n"
                "STEP 2 — Then read this offer:\n"
                f"{offer_text(o)}\n\n"
                "Answer honestly as yourself.\n"
                'Return JSON: {"search_query": "the exact question or search you would type in your own words", '
                '"known_alternatives": ["up to 3 brands, tools or free ways you already knew before seeing this"], '
                '"would_ask_ai_about_brand": "what you would ask an AI assistant to verify about this offer before trusting it", '
                '"understood_category": "what category or kind of product you think this is", '
                '"would_shortlist": "yes|maybe|no", '
                '"missing_fact": "what fact is missing from the offer that an FAQ or AI answer would need to state, or empty", '
                f'"missing_type": "{"|".join(CONCERN_TYPES)}|none"}}'
            ),
        }
        for p in cohort
    ]
    asked = ask_people(meter, model, jobs, parallel, progress, max_tokens=500)
    ok = [r for r in asked if r["ok"]]
    n = len(ok)

    shortlist = Counter(str(r["data"].get("would_shortlist") or "").lower() for r in ok)
    known_counts: Counter = Counter()
    for r in ok:
        for alt in (r["data"].get("known_alternatives") or [])[:3]:
            s_alt = _short(alt, 60)
            if s_alt:
                known_counts[s_alt] += 1

    person_queries = [_short(r["data"].get("search_query"), 160) for r in ok if r["data"].get("search_query")]
    verify_questions = [_short(r["data"].get("would_ask_ai_about_brand"), 160) for r in ok if r["data"].get("would_ask_ai_about_brand")]
    missing = ranked(
        [(_ctype(r["data"].get("missing_type")) or "unclear", r["data"].get("missing_fact"))
         for r in ok if r["data"].get("missing_fact")],
        n,
    )

    # Draft /llms.txt and FAQPage JSON-LD strictly from the provided product facts and the top questions people asked
    top_questions = (verify_questions + person_queries)[:6]
    geo_assets = write_once(
        meter,
        model,
        (
            "Using ONLY the product facts below (do not invent any prices, features, guarantees or statistics; if a "
            "question cannot be answered from the facts, state what is not specified yet), write:\n"
            "1. A concise `/llms.txt` markdown summary of the product for AI search crawlers.\n"
            "2. Up to 4 FAQ pairs answering the questions simulated buyers asked.\n\n"
            f"PRODUCT FACTS:\n{facts}\n\n"
            f"QUESTIONS BUYERS ASKED AI:\n{json.dumps(top_questions, ensure_ascii=False)}\n\n"
            'Return JSON: {"llms_txt": "# Brand\\n...", "faqs": [{"question": "...", "answer": "...", "in_facts": true}], '
            '"unanswered_gaps": ["facts buyers asked for that are not in the product facts yet"]}'
        ),
        max_tokens=1200,
        temperature=0.2,
    )
    geo_assets = guard_numbers(geo_assets, {"facts": facts, "offer": o})

    summary = {
        "brand": brand,
        "would_shortlist": {k: wilson(shortlist.get(k, 0), n) for k in ("yes", "maybe", "no")},
        "known_alternatives": [
            {"name": k, "count": c, "share": wilson(c, n)} for k, c in known_counts.most_common(8)
        ],
        "buyer_search_queries": person_queries[:12],
        "verification_questions": verify_questions[:10],
        "missing_facts_for_ai": missing,
        "understood_as": [_short(r["data"].get("understood_category"), 120) for r in ok if r["data"].get("understood_category")][:8],
        "llms_txt": str(geo_assets.get("llms_txt") or "").strip(),
        "faqs": [x for x in (geo_assets.get("faqs") or []) if isinstance(x, dict) and x.get("question")][:5],
        "unanswered_gaps": [_short(x, 180) for x in (geo_assets.get("unanswered_gaps") or []) if x][:6],
    }
    return envelope("geo", asked, meter, cohort=len(cohort), summary=summary)


# --------------------------------------------------------------------------
# 4. Voice-of-Customer (VoC) real-vs-simulated comparison
# --------------------------------------------------------------------------

def run_voc_grounding(
    client: Any,
    model: str,
    offer: Any = "",
    people: Optional[List[Dict[str, Any]]] = None,
    url: Optional[str] = None,
    raw_reviews: Optional[List[str]] = None,
    run_data: Optional[Dict[str, Any]] = None,
    seed: int = 43,
    profile: Optional[Dict[str, Any]] = None,
    parallel: int = 8,
    progress: Optional[Callable[[int, int], None]] = None,
) -> Dict[str, Any]:
    """Compare the concerns raised by the simulated people in this run against real customer voices
    (from `research.json`, `raw_reviews`, or a public `url`)."""
    _need(client)
    meter = _meter(client)
    rd = run_data or {}
    sim_objs = gather_objections(rd.get("survey"), rd.get("pitch"), rd.get("feed_test"))

    real_texts: List[str] = []
    source_label = ""
    if raw_reviews:
        real_texts = [_short(x, 300) for x in raw_reviews if str(x).strip()][:60]
        source_label = "passed reviews"
    elif url:
        snap = fetch_url_snapshot(url)
        chunks = [s.strip() for s in re.split(r"(?<=[.!?])\s+", snap.get("text") or "") if len(s.strip()) >= 30]
        real_texts = chunks[:40]
        source_label = snap.get("url") or url
    elif isinstance(rd.get("research"), dict):
        voices = (rd["research"].get("voices") or rd["research"].get("items") or [])
        real_texts = [_short(v.get("text") or v.get("body") or v.get("title"), 300)
                      for v in voices if isinstance(v, dict) and (v.get("text") or v.get("body") or v.get("title"))][:60]
        source_label = "research.json"

    if not real_texts:
        return envelope(
            "voc", [], meter, cohort=0,
            summary={
                "available": False,
                "reason": "Pass `raw_reviews`, a public `url`, or run `mirofish.py research` first so there are real voices to compare against.",
            },
        )

    # Tag each real voice with the same CONCERN_TYPES used by the simulated people
    jobs = [
        {
            "person": {"agent_id": i},
            "prompt": (
                f"Real customer quote or page excerpt:\n\"{txt}\"\n\n"
                "Classify the main concern or topic expressed here, and extract the exact phrase the person used.\n"
                f'Return JSON: {{"concern_type": "{"|".join(CONCERN_TYPES)}|none", '
                '"exact_phrase": "the key phrase in their own words", "plain_meaning": "one short sentence"}'
            ),
        }
        for i, txt in enumerate(real_texts)
    ]
    asked = ask_people(meter, model, jobs, parallel, progress, max_tokens=220, temperature=0.1)
    ok = [r for r in asked if r["ok"]]
    n_real = len(ok)
    n_sim = len(sim_objs)

    real_ranked = ranked(
        [(_ctype(r["data"].get("concern_type")), r["data"].get("exact_phrase") or real_texts[r["person"]["agent_id"]])
         for r in ok if _ctype(r["data"].get("concern_type"))],
        n_real,
    )
    sim_ranked = ranked([(x["type"], x["text"]) for x in sim_objs], n_sim) if n_sim else []

    real_by_k = {r["key"]: r["share"] for r in real_ranked}
    sim_by_k = {r["key"]: r["share"] for r in sim_ranked}
    all_keys = list(dict.fromkeys([r["key"] for r in real_ranked] + [r["key"] for r in sim_ranked]))

    comparison = [
        {
            "concern": k,
            "real_share": real_by_k.get(k) or wilson(0, n_real),
            "simulated_share": sim_by_k.get(k) or wilson(0, n_sim),
        }
        for k in all_keys
    ]

    phrases = [
        {
            "concern": _ctype(r["data"].get("concern_type")) or "other",
            "exact_phrase": _short(r["data"].get("exact_phrase"), 160),
            "meaning": _short(r["data"].get("plain_meaning"), 160),
        }
        for r in ok if r["data"].get("exact_phrase")
    ][:12]

    summary = {
        "available": True,
        "source": source_label,
        "real_voices_count": n_real,
        "simulated_objections_count": n_sim,
        "real_concerns": real_ranked,
        "simulated_concerns": sim_ranked,
        "comparison": comparison,
        "verbatim_phrases": phrases,
    }
    return envelope("voc", asked, meter, cohort=n_real, summary=summary)


# --------------------------------------------------------------------------
# 5. Dark-social & word-of-mouth cascade test
# --------------------------------------------------------------------------

def run_dark_social_cascade(
    client: Any,
    model: str,
    people: List[Dict[str, Any]],
    offer: Any = "",
    seed: int = 47,
    cohort_size: int = 36,
    profile: Optional[Dict[str, Any]] = None,
    parallel: int = 8,
    progress: Optional[Callable[[int, int], None]] = None,
) -> Dict[str, Any]:
    """Wave 1 asks each person if they would privately forward or mention the offer and what they would write.
    Wave 2 shows those real forwarded messages to another group of simulated people to test peer-referral pickup."""
    _need(client)
    meter = _meter(client)
    o = offer_dict(offer, profile)
    cohort = sample_people(people, cohort_size, seed)
    half = max(1, len(cohort) // 2)
    wave1_people = cohort[:half]
    wave2_people = cohort[half:] or cohort[:half]

    w1_jobs = [
        {
            "person": p,
            "prompt": (
                f"WHO YOU ARE\n{person_card(p)}\n\nYOU SEE THIS OFFER\n{offer_text(o)}\n\n"
                "Would you mention, screenshot or forward this to anyone in private (for example a partner, family chat, "
                "friend group, colleague on WhatsApp/Slack/DM, or nobody)? Be realistic: most ads do not get shared.\n"
                'Return JSON: {"would_share": "yes|maybe|no", '
                '"channel": "whatsapp_dm|family_chat|work_chat|social_post|in_person|none", '
                '"who": "who you would tell, or nobody", '
                '"message_you_would_send": "the exact message you would send them in your own words, or empty if you would not share", '
                '"why": "one sentence"}'
            ),
        }
        for p in wave1_people
    ]
    asked1 = ask_people(meter, model, w1_jobs, parallel, progress, max_tokens=400)
    ok1 = [r for r in asked1 if r["ok"]]
    n1 = len(ok1)

    share_counts = Counter(str(r["data"].get("would_share") or "").lower() for r in ok1)
    channels = Counter(str(r["data"].get("channel") or "none").lower() for r in ok1 if str(r["data"].get("would_share") or "").lower() in ("yes", "maybe"))
    shared_msgs = [
        {
            "from_name": r["person"].get("name"),
            "from_segment": r["person"].get("segment"),
            "channel": str(r["data"].get("channel") or "dm"),
            "who": _short(r["data"].get("who"), 80),
            "message": _short(r["data"].get("message_you_would_send"), 220),
        }
        for r in ok1
        if str(r["data"].get("would_share") or "").lower() in ("yes", "maybe")
        and str(r["data"].get("message_you_would_send") or "").strip()
    ]

    asked2: List[Dict[str, Any]] = []
    wave2_summary = None
    if shared_msgs and wave2_people:
        w2_jobs = []
        for idx, p in enumerate(wave2_people):
            m = shared_msgs[idx % len(shared_msgs)]
            w2_jobs.append({
                "person": p,
                "prompt": (
                    f"WHO YOU ARE\n{person_card(p)}\n\n"
                    f"Someone you know ({m['who'] or 'a friend'}) sends you this in {m['channel'].replace('_', ' ')}:\n"
                    f"\"{m['message']}\"\n\n"
                    f"When you look it up, here is the offer:\n{offer_text(o)}\n\n"
                    'Return JSON: {"reaction_to_friend_forward": "one sentence", '
                    '"would_try_from_friend": "yes|maybe|no", "would_try_if_seen_as_cold_ad": "yes|maybe|no", '
                    '"would_forward_again": "yes|maybe|no"}',
                ),
            })
        asked2 = ask_people(meter, model, w2_jobs, parallel, None, max_tokens=350)
        ok2 = [r for r in asked2 if r["ok"]]
        n2 = len(ok2)
        if n2:
            friend_try = Counter(str(r["data"].get("would_try_from_friend") or "").lower() for r in ok2)
            cold_try = Counter(str(r["data"].get("would_try_if_seen_as_cold_ad") or "").lower() for r in ok2)
            fwd_again = Counter(str(r["data"].get("would_forward_again") or "").lower() for r in ok2)
            wave2_summary = {
                "people": n2,
                "would_try_from_friend": {k: wilson(friend_try.get(k, 0), n2) for k in ("yes", "maybe", "no")},
                "would_try_if_cold_ad": {k: wilson(cold_try.get(k, 0), n2) for k in ("yes", "maybe", "no")},
                "would_forward_again": {k: wilson(fwd_again.get(k, 0), n2) for k in ("yes", "maybe", "no")},
                "reactions": [_short(r["data"].get("reaction_to_friend_forward"), 180) for r in ok2 if r["data"].get("reaction_to_friend_forward")][:6],
            }

    summary = {
        "wave1_people": n1,
        "would_share": {k: wilson(share_counts.get(k, 0), n1) for k in ("yes", "maybe", "no")},
        "channels": [{"channel": k, "count": c, "share": wilson(c, n1)} for k, c in channels.most_common()],
        "forwarded_messages": shared_msgs[:8],
        "why_or_why_not": [_short(r["data"].get("why"), 180) for r in ok1 if r["data"].get("why")][:8],
        "wave2_peer_pickup": wave2_summary,
    }
    return envelope("cascade", asked1 + asked2, meter, cohort=len(cohort), summary=summary)
