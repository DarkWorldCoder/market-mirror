"""
run_search.py - search across what a run actually produced (people, survey answers, thoughts, feed and landing
reactions, pitch replies, social posts, test results and research quotes). Stdlib only, so the backend, the CLI
and the offline dashboard share one indexer and one ranker (BM25 plus buyer-concern synonyms, whole tokens only).
Nothing is invented: a record exists only when the run wrote that text.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

# Buyer concerns: a query that names one of these words also looks for the others in the same group.
CONCEPTS: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "price": ("Price, budget and payment terms", (
        "price", "pricing", "cost", "costs", "expensive", "cheap", "affordable", "budget", "money", "weekly", "monthly",
        "annual", "subscription", "tier", "plan", "discount", "value", "worth", "fee", "fees", "pay", "spend", "free",
        "trial")),
    "trust": ("Trust, proof and sign-up risk", (
        "trust", "trustworthy", "credible", "scam", "skeptical", "proof", "review", "reviews", "testimonial", "guarantee",
        "refund", "cancel", "cancellation", "card", "credit", "debit", "auto-renew", "autorenew", "trap", "charge",
        "billing", "privacy", "security", "risk", "safe", "signup", "sign-up", "hesitate", "checkout", "abandon",
        "dealbreaker")),
    "authority": ("Who else has to agree", (
        "spouse", "husband", "wife", "partner", "parents", "family", "household", "couple", "committee", "boss",
        "manager", "cfo", "finance", "blocker", "champion", "approval", "permission", "consult")),
    "habit": ("Routine, effort and time", (
        "habit", "routine", "quit", "drop", "churn", "retention", "consistent", "busy", "tired", "fatigue", "schedule",
        "time", "effort", "hard", "easy", "simple", "onboarding", "setup", "daily")),
    "competitor": ("Alternatives and switching", (
        "competitor", "competitors", "alternative", "alternatives", "already", "switch", "switching", "compare",
        "comparison", "versus", "vs", "incumbent")),
    "unclear": ("Clarity and missing details", (
        "unclear", "confusing", "confused", "understand", "explain", "headline", "copy", "landing", "missing", "detail",
        "details", "vague", "jargon")),
    "relevance": ("Relevance and fit", (
        "relevant", "relevance", "need", "fit", "audience", "useful", "problem", "solve", "goal", "match", "interest")),
}

TYPE_LABELS = {"persona": "Person", "survey": "Survey answer", "thought": "Thought", "feed": "Feed and landing",
               "pitch": "Pitch reply", "post": "Social post", "test": "Test result", "research": "Research quote"}

# (key in gtm_suite.json engines, result file name, dashboard anchor, label)
TEST_RESULTS = (
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
    ("geo", "geo_visibility", "#search-geo", "How buyers would search (simulated)"),
    ("voc", "voc_grounding", "#search-geo", "Real vs simulated concerns"),
    ("cascade", "dark_social", "#search-geo", "Word-of-mouth cascade"),
)

_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "do", "does", "for", "from", "has", "have", "how", "i",
    "if", "in", "into", "is", "it", "its", "my", "no", "not", "of", "on", "or", "our", "so", "such", "that", "the",
    "their", "them", "then", "there", "these", "they", "this", "to", "us", "was", "we", "what", "when", "where",
    "which", "who", "why", "will", "with", "would", "you", "your", "can", "could", "should", "about", "people",
    "users", "buyers",
}
_TOKEN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)?")


def tokenize(text: Any) -> List[str]:
    return [t for t in _TOKEN.findall(str(text or "").lower()) if len(t) > 1 and t not in _STOPWORDS]


def detect_concepts(text: Any) -> List[str]:
    """Concept ids whose words appear in the text as whole tokens."""
    tokens = set(tokenize(text))
    return [cid for cid, (_label, words) in CONCEPTS.items() if tokens.intersection(words)]


def expand_query(query: str) -> Dict[str, Any]:
    base = list(dict.fromkeys(tokenize(query)))
    matched = detect_concepts(query)
    expanded = list(base)
    for cid in matched:
        for w in CONCEPTS[cid][1]:
            if w not in expanded:
                expanded.append(w)
    return {"query": query, "base_tokens": base, "matched_concepts": matched,
            "concept_labels": [CONCEPTS[c][0] for c in matched], "expanded_tokens": expanded}


def _short(x: Any, n: int = 240) -> str:
    s = " ".join(str(x or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _dicts(x: Any) -> List[Dict[str, Any]]:
    return [i for i in x if isinstance(i, dict)] if isinstance(x, list) else []


def _obj(x: Any) -> Dict[str, Any]:
    return x if isinstance(x, dict) else {}


def research_items(research: Any) -> List[Dict[str, Any]]:
    """Quotes from `research` output: research.json ({summary, quotes}), voices.json (a list), or older
    {voices} / {items} shapes."""
    if isinstance(research, list):
        return _dicts(research)
    r = _obj(research)
    for key in ("quotes", "voices", "items"):
        if isinstance(r.get(key), list):
            return _dicts(r[key])
    return []


def research_text(item: Dict[str, Any]) -> str:
    return str(item.get("text") or item.get("body") or item.get("title") or "").strip()


def build_docs(bundle: Any, people: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Index every record present in `bundle` (the run's JSON files by name, as the exporter loads them)."""
    b = _obj(bundle)
    cfg = _obj(b.get("config") or b.get("simulation_config"))
    if isinstance(cfg.get("data"), dict):
        cfg = cfg["data"]
    if people is None:
        people = _dicts(cfg.get("persona_index"))
    people = _dicts(people)
    by_id = {p["agent_id"]: p for p in people if p.get("agent_id") is not None}
    docs: List[Dict[str, Any]] = []

    def add(doc_id: str, doc_type: str, title: str, snippet: str, text: str = "", segment: Any = "", verdict: Any = "",
            anchor: str = "#top", meta: Any = "", type_label: str = "") -> None:
        snip = _short(snippet, 260)
        if not snip:
            return
        full = f"{title} {segment or ''} {verdict or ''} {snip} {text}".strip()
        docs.append({"id": doc_id, "type": doc_type, "type_label": type_label or TYPE_LABELS[doc_type],
                     "title": _short(title, 120), "segment": str(segment or ""), "verdict": str(verdict or ""),
                     "snippet": snip, "text": _short(full, 900), "anchor": anchor,
                     "concepts": detect_concepts(full), "meta": _short(meta, 120)})

    def who(name: Any, seg: Any) -> str:
        return f"{name} ({seg})" if seg else str(name)

    for idx, p in enumerate(people[:250]):
        aid = p.get("agent_id", idx + 1)
        bde = p.get("bde") if isinstance(p.get("bde"), dict) else {}
        bde_txt = json.dumps(bde, ensure_ascii=False) if bde else ""
        persona = str(p.get("persona") or p.get("bio") or "").strip()
        occ = p.get("occupation") or p.get("profession") or ""
        place = p.get("country") or p.get("city") or ""
        add(f"persona-{aid}", "persona", ", ".join(str(x) for x in (p.get("name") or f"Person {aid}", occ, place) if x),
            persona or bde_txt, f"{persona} {bde_txt}", p.get("segment"), p.get("model_provider"), "#agents", f"agent #{aid}")

    for idx, r in enumerate(_dicts(_obj(b.get("survey")).get("responses"))[:250]):
        a = _obj(r.get("answer"))
        obj = str(a.get("main_objection") or a.get("reasoning") or a.get("comment") or "").strip()
        p = by_id.get(r.get("agent_id"), {})
        seg = r.get("segment") or p.get("segment") or ""
        otype = str(a.get("objection_type") or "")
        add(f"survey-{r.get('agent_id')}-{idx}", "survey", who(r.get("name") or p.get("name") or f"Person {r.get('agent_id')}", seg),
            obj, json.dumps(a, ensure_ascii=False), seg, str(a.get("would_convert") or "").upper(), "#voices",
            f"objection: {otype}" if otype else "survey")

    for key in ("thought_stream", "thought_harvest"):
        for idx, e in enumerate(_dicts(_obj(b.get(key)).get("entries"))[:250]):
            txt = str(e.get("text") or "").strip()
            if not txt:
                continue
            did = e.get("would_do") or e.get("did") or ""
            src = e.get("source") or "run"
            add(f"thought-{key}-{idx}", "thought", who(e.get("name") or f"Person {e.get('agent_id')}", e.get("segment")),
                txt + (f" → {did}" if did else ""), f"{txt} {e.get('weighing') or ''} {did} {e.get('gut') or ''} {e.get('roadblock') or ''}",
                e.get("segment"), str(e.get("private_verdict") or e.get("gut") or "").upper(), "#thoughts",
                f"{src} · {e.get('roadblock') or e.get('kind') or ''}".strip(" ·"), f"Thought ({src})")

    ft = _obj(b.get("feed_test"))
    first_seed = ft.get("seed")
    for idx, s in enumerate(_dicts(ft.get("sessions"))[:200]):
        if first_seed is not None and s.get("seed") not in (None, first_seed):
            continue
        ad, land = _obj(s.get("ad")), _obj(s.get("landing"))
        th = str(land.get("thought") or ad.get("thought") or "").strip()
        if not th:
            continue
        drop = land.get("drop_reason") or ""
        verdict = "CONVERTED" if land.get("completed") else ("CLICKED" if ad.get("click") else "SCROLLED")
        add(f"feed-{idx}", "feed", f"{s.get('name') or 'Person ' + str(s.get('agent_id'))} on {s.get('creative_id') or 'ad'}",
            th + (f" (drop reason: {drop})" if drop else ""), f"{th} {drop}", s.get("segment"), verdict, "#feedtest",
            s.get("platform"))

    for idx, r in enumerate(_dicts(_obj(b.get("pitch")).get("people"))[:150]):
        t1 = _obj(r.get("turn1"))
        rep = str(t1.get("reply") or "").strip()
        add(f"pitch-{idx}", "pitch", who(r.get("name") or f"Person {r.get('agent_id')}", r.get("segment")), rep,
            f"{rep} {t1.get('thought') or ''} {t1.get('objection') or ''}", r.get("segment"),
            str(r.get("final_verdict") or t1.get("verdict") or "").upper(), "#pitch", f"lead score: {r.get('lead_score', '–')}")

    acts = b.get("actions")
    if isinstance(acts, dict):
        acts = acts.get("actions")
    for idx, a in enumerate(_dicts(acts)[:150]):
        args = _obj(a.get("action_args"))
        content = str(args.get("content") or args.get("quote_content") or a.get("content") or "").strip()
        p = by_id.get(a.get("agent_id"), {})
        atype = str(a.get("action_type") or "POST")
        add(f"post-{idx}", "post", f"{a.get('agent_name') or p.get('name') or 'Person ' + str(a.get('agent_id'))} "
            f"({atype.lower().replace('_', ' ')})", content, f"{content} {a.get('thought') or ''}", p.get("segment"), atype,
            "#posts", f"{a.get('platform') or ''} round {a.get('round_num', '?')}".strip())

    engines = _obj(_obj(b.get("gtm_suite")).get("engines"))
    for key, fname, anchor, label in TEST_RESULTS:
        res = b.get(fname) if isinstance(b.get(fname), dict) else _obj(engines.get(key))
        s = res.get("summary")
        if not isinstance(s, dict) or not s:
            continue
        js = json.dumps(s, ensure_ascii=False)
        add(f"test-{key}", "test", f"{label} ({res.get('answered', 0)} of {res.get('asked', 0)} answered)", js[:250], js[:900],
            "", f"{res.get('answered', 0)}/{res.get('asked', 0)}", anchor, label, label)

    for idx, q in enumerate(research_items(b.get("research"))[:120]):
        txt = research_text(q)
        src = str(q.get("source") or q.get("platform") or "web")
        kind = str(q.get("kind") or "")
        label = "Page text (research)" if kind in ("page", "listing") else "Public post or review (research)"
        add(f"research-{idx}", "research", str(q.get("title") or f"Quote from {src}")[:100], txt, txt, src,
            "public source", "#evidence", q.get("url") or src, label)
    return docs


def search(query: str, docs: Any, top_k: int = 12, doc_type: Optional[str] = None, segment: Optional[str] = None,
           concept: Optional[str] = None) -> Dict[str, Any]:
    """BM25 over the records' words, plus a smaller weight for synonyms of the buyer concerns the query names."""
    pool = _dicts(docs.get("docs") if isinstance(docs, dict) else docs)
    if doc_type and doc_type.lower() not in ("all", "*"):
        pool = [d for d in pool if d.get("type") == doc_type]
    if segment and segment.lower() not in ("all", "*"):
        pool = [d for d in pool if segment.lower() in str(d.get("segment") or "").lower()]
    if concept and concept.lower() not in ("all", "*"):
        pool = [d for d in pool if concept in (d.get("concepts") or [])]
    expansion = expand_query(query)
    base, matched = expansion["base_tokens"], set(expansion["matched_concepts"])
    q_low = " ".join(str(query or "").lower().split())
    if not pool:
        return {"query": query, "expansion": expansion, "total_matches": 0, "results": []}
    if not base and not q_low:
        return {"query": query, "expansion": expansion, "total_matches": len(pool), "results": pool[:top_k]}

    toks = [tokenize(f"{d.get('title', '')} {d.get('snippet', '')} {d.get('text', '')}") for d in pool]
    df: Counter = Counter(t for tl in toks for t in set(tl))
    n = len(pool)
    avgdl = sum(len(tl) for tl in toks) / max(1, n)
    k1, bb = 1.5, 0.75

    def idf(t: str) -> float:
        return math.log(1.0 + (n - df[t] + 0.5) / (df[t] + 0.5))

    scored: List[Tuple[float, Dict[str, Any]]] = []
    for d, tl in zip(pool, toks):
        tf = Counter(tl)
        score = 0.0
        for t in base:
            f = tf.get(t, 0)
            if f:
                score += 2.5 * idf(t) * (f * (k1 + 1.0)) / (f + k1 * (1.0 - bb + bb * len(tl) / max(1.0, avgdl)))
        for t in expansion["expanded_tokens"]:
            if t not in base and tf.get(t, 0):
                score += 0.55 * idf(t)
        overlap = matched & set(d.get("concepts") or [])
        score += 2.0 * len(overlap)
        if len(q_low) >= 3 and (q_low in str(d.get("title", "")).lower() or q_low in str(d.get("snippet", "")).lower()):
            score += 3.5
        if score > 0:
            scored.append((score, {**d, "relevance_score": round(score, 2),
                                   "matched_concepts": [CONCEPTS[c][0] for c in sorted(overlap)]}))
    scored.sort(key=lambda x: -x[0])
    return {"query": query, "expansion": expansion, "total_matches": len(scored), "results": [d for _, d in scored[:top_k]]}
