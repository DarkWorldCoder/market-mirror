"""Product understanding: turn whatever the user gives (documents, a landing page, an ads export) into one
structured product profile that every later step leans on (persona planning, feed test, survey wording,
pitch, report, ideas, quickstart prefill).

One Claude call over a compact view of the material; strict JSON; a headings-only fallback when the model
fails, so the pipeline never blocks on this step.
"""

import html
import json
import os
import re
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional

PROFILE_FILE = "product_profile.json"
MAX_MATERIAL = 12000

SCHEMA = {
    "name": "", "category": "", "one_liner": "", "what_it_does": "",
    "for_whom": [{"segment": "", "country_hint": "", "job_to_be_done": ""}],
    "pricing": {"model": "", "price_points": [], "currency": ""},
    "offer": "", "proofs": [], "differentiators": [],
    "competitors": [{"name": "", "how_they_win": ""}],
    "channels": [], "likely_objections": [{"type": "", "text": ""}],
    "brand_voice": "", "funnel_goal": "", "kpis": [], "unknowns": [],
}
OBJECTION_TYPES = ("price", "trust", "relevance", "timing", "effort", "unclear", "privacy", "language", "competitor", "other")

SYSTEM = ("You are a senior marketing strategist reading a company's material before a campaign. Extract only what the "
          "material supports; put guesses in 'unknowns'. Plain words, no hype. Return JSON only.")


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer"}

    def __init__(self):
        super().__init__()
        self.parts: List[str] = []
        self._skip = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            a = dict(attrs)
            if (a.get("name") or a.get("property") or "").lower() in ("description", "og:description", "og:title"):
                self.parts.append(a.get("content") or "")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if not self._skip and data.strip():
            self.parts.append(data.strip())


def html_to_text(page: str) -> str:
    p = _Text()
    try:
        p.feed(page)
    except Exception:  # noqa: BLE001 - keep whatever parsed
        pass
    text = "\n".join(x for x in p.parts if x)
    text = html.unescape(re.sub(r"\n{3,}", "\n\n", text))
    return (f"{p.title.strip()}\n\n" if p.title.strip() else "") + text


def fetch_url_text(url: str, timeout: float = 20) -> str:
    """Landing page / app-store page -> readable text (no JS). Never raises; returns '' on failure."""
    try:
        import requests
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "MarketMirror/0.3 (+https://github.com/DarkWorldCoder/market-mirror)"})
        r.raise_for_status()
        ctype = r.headers.get("content-type", "")
        return html_to_text(r.text) if "html" in ctype or r.text.lstrip().startswith("<") else r.text
    except Exception:  # noqa: BLE001
        return ""


def compact_material(documents: str = "", url_text: str = "", ads_summary: Optional[Dict[str, Any]] = None,
                     requirement: str = "", limit: int = MAX_MATERIAL) -> str:
    """Budgeted view of everything we know, documents first."""
    parts = []
    if requirement:
        parts.append(f"## What the user wants to learn\n{requirement[:1500]}")
    if documents:
        parts.append(f"## Documents\n{documents[: int(limit * 0.6)]}")
    if url_text:
        parts.append(f"## Web page\n{url_text[: int(limit * 0.3)]}")
    if ads_summary:
        tot = ads_summary.get("total") or {}
        rows = []
        for dim, table in (ads_summary.get("tables") or {}).items():
            for r in (table or [])[:5]:
                rows.append(f"- {dim} '{r.get('key')}': spend {r.get('spend')}, CTR {r.get('ctr')}%, conversions {r.get('conversions')}, CPA {r.get('cpa')}")
        parts.append("## Past ads\n" + f"Total spend {tot.get('spend')}, CTR {tot.get('ctr')}%, CPA {tot.get('cpa')}\n" + "\n".join(rows[:20]))
    return "\n\n".join(parts)[:limit]


def _prompt(material: str) -> str:
    return (
        "Read the material and fill this product profile. Every field must come from the material; when it does not say, "
        "leave the field empty and name the gap in 'unknowns'. likely_objections are the hesitations the buyers described "
        "would have (types: " + ", ".join(OBJECTION_TYPES) + "). channels = where buyers see the brand. kpis = the numbers "
        "the business watches. brand_voice = how the brand talks, in 10 words.\n\n"
        f"MATERIAL:\n{material}\n\n"
        "Return exactly this JSON:\n" + json.dumps(SCHEMA, ensure_ascii=False)
    )


def _s(v: Any, n: int = 300) -> str:
    return str(v or "").strip()[:n]


def clean(raw: Any) -> Dict[str, Any]:
    d = raw if isinstance(raw, dict) else {}
    out: Dict[str, Any] = {
        "name": _s(d.get("name"), 80), "category": _s(d.get("category"), 80), "one_liner": _s(d.get("one_liner"), 200),
        "what_it_does": _s(d.get("what_it_does"), 800),
        "for_whom": [{"segment": _s(x.get("segment"), 80), "country_hint": _s(x.get("country_hint"), 60),
                      "job_to_be_done": _s(x.get("job_to_be_done"), 200)}
                     for x in (d.get("for_whom") or []) if isinstance(x, dict) and x.get("segment")][:8],
        "pricing": {"model": _s((d.get("pricing") or {}).get("model"), 80),
                    "price_points": [_s(p, 60) for p in ((d.get("pricing") or {}).get("price_points") or [])][:6],
                    "currency": _s((d.get("pricing") or {}).get("currency"), 8)},
        "offer": _s(d.get("offer"), 300),
        "proofs": [_s(p, 200) for p in (d.get("proofs") or []) if _s(p)][:8],
        "differentiators": [_s(p, 200) for p in (d.get("differentiators") or []) if _s(p)][:8],
        "competitors": [{"name": _s(x.get("name"), 80), "how_they_win": _s(x.get("how_they_win"), 200)}
                        for x in (d.get("competitors") or []) if isinstance(x, dict) and x.get("name")][:8],
        "channels": [_s(p, 40) for p in (d.get("channels") or []) if _s(p)][:10],
        "likely_objections": [], "brand_voice": _s(d.get("brand_voice"), 120), "funnel_goal": _s(d.get("funnel_goal"), 120),
        "kpis": [_s(p, 80) for p in (d.get("kpis") or []) if _s(p)][:8],
        "unknowns": [_s(p, 160) for p in (d.get("unknowns") or []) if _s(p)][:10],
    }
    for x in d.get("likely_objections") or []:
        if isinstance(x, dict) and x.get("text"):
            t = _s(x.get("type"), 20).lower()
            out["likely_objections"].append({"type": t if t in OBJECTION_TYPES else "other", "text": _s(x.get("text"), 200)})
        elif isinstance(x, str) and x.strip():
            out["likely_objections"].append({"type": "other", "text": _s(x, 200)})
    out["likely_objections"] = out["likely_objections"][:8]
    return out


def fallback_profile(material: str, name_hint: str = "") -> Dict[str, Any]:
    """Headings-only profile when the model gives nothing usable: keeps the pipeline moving."""
    heads = re.findall(r"^#{1,3}\s+(.+)$", material, re.M)
    first = re.sub(r"\s+", " ", material.strip())[:200]
    prices = re.findall(r"(?:USD|EUR|GBP|INR|PHP|KES|\$|€|£|₹|₱)\s?\d[\d,.]*(?:\s?(?:/|per)\s?(?:month|mo|year|yr|week))?", material)[:4]
    return clean({"name": name_hint or (heads[0] if heads else ""), "one_liner": first,
                  "what_it_does": "\n".join(heads[:8]), "pricing": {"price_points": prices},
                  "unknowns": ["profile written from headings only: the model returned nothing usable"]})


def generate(client, model: str, material: str, name_hint: str = "") -> Dict[str, Any]:
    from ..utils.openai_chat_compat import create_chat_completion, extract_chat_completion_text
    from .persona_planner import parse_json_block
    usage = {"input_tokens": 0, "output_tokens": 0}
    method = "llm"
    profile: Dict[str, Any] = {}
    try:
        resp = create_chat_completion(client, model=model, temperature=0.2, max_tokens=3000,
                                      messages=[{"role": "system", "content": SYSTEM},
                                                {"role": "user", "content": _prompt(material)}])
        u = getattr(resp, "usage", None)
        if u:
            usage = {"input_tokens": getattr(u, "prompt_tokens", 0) or 0, "output_tokens": getattr(u, "completion_tokens", 0) or 0}
        profile = clean(parse_json_block(extract_chat_completion_text(resp)))
    except Exception:  # noqa: BLE001
        profile = {}
    if not profile.get("name") and not profile.get("what_it_does"):
        method = "fallback"
        profile = fallback_profile(material, name_hint)
    if name_hint and not profile.get("name"):
        profile["name"] = name_hint
    profile["method"] = method
    profile["usage"] = usage
    profile["material_chars"] = len(material)
    return profile


def render_text(p: Dict[str, Any], limit: int = 2500) -> str:
    """The profile as a short brief that prompts can prepend (persona planning, feed test, survey, pitch)."""
    if not p:
        return ""
    lines = [f"PRODUCT PROFILE: {p.get('name') or 'the product'}" + (f" ({p['category']})" if p.get("category") else "")]
    if p.get("one_liner"):
        lines.append(p["one_liner"])
    if p.get("what_it_does"):
        lines.append(f"What it does: {p['what_it_does']}")
    if p.get("for_whom"):
        lines.append("For: " + "; ".join(f"{x['segment']}" + (f" ({x['country_hint']})" if x.get("country_hint") else "")
                                         + (f" - {x['job_to_be_done']}" if x.get("job_to_be_done") else "") for x in p["for_whom"]))
    pr = p.get("pricing") or {}
    if pr.get("price_points") or pr.get("model"):
        lines.append("Pricing: " + ", ".join(pr.get("price_points") or []) + (f" ({pr['model']})" if pr.get("model") else ""))
    if p.get("offer"):
        lines.append(f"Offer: {p['offer']}")
    if p.get("proofs"):
        lines.append("Proof: " + "; ".join(p["proofs"]))
    if p.get("differentiators"):
        lines.append("Different because: " + "; ".join(p["differentiators"]))
    if p.get("competitors"):
        lines.append("Competitors: " + "; ".join(f"{c['name']}" + (f" ({c['how_they_win']})" if c.get("how_they_win") else "") for c in p["competitors"]))
    if p.get("channels"):
        lines.append("Channels: " + ", ".join(p["channels"]))
    if p.get("likely_objections"):
        lines.append("Likely objections: " + "; ".join(f"{o['type']}: {o['text']}" for o in p["likely_objections"]))
    if p.get("brand_voice"):
        lines.append(f"Brand voice: {p['brand_voice']}")
    if p.get("funnel_goal"):
        lines.append(f"Goal: {p['funnel_goal']}")
    return "\n".join(lines)[:limit]


def graph_episode(p: Dict[str, Any]) -> str:
    """A short factual text to add to the knowledge graph so Brand/Product/Benefit/Objection/Competitor nodes exist."""
    name = p.get("name") or "The brand"
    bits = [f"{name} sells {p.get('one_liner') or p.get('what_it_does') or 'a product'}."]
    for x in p.get("for_whom") or []:
        bits.append(f"{name} targets {x['segment']}" + (f" in {x['country_hint']}" if x.get("country_hint") else "") + ".")
    for c in p.get("competitors") or []:
        bits.append(f"{name} competes with {c['name']}.")
    for b in p.get("differentiators") or []:
        bits.append(f"Customers value {b} about {name}.")
    for o in p.get("likely_objections") or []:
        bits.append(f"Some buyers object to {name} because of {o['type']}: {o['text']}")
    for ch in p.get("channels") or []:
        bits.append(f"{name} uses the channel {ch}.")
    for pp in (p.get("pricing") or {}).get("price_points") or []:
        bits.append(f"{name} is priced at {pp}.")
    return " ".join(bits)[:6000]


def profile_path(project_dir: str) -> str:
    return os.path.join(project_dir, PROFILE_FILE)


def load(project_dir: str) -> Optional[Dict[str, Any]]:
    try:
        with open(profile_path(project_dir), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save(project_dir: str, profile: Dict[str, Any]) -> str:
    path = profile_path(project_dir)
    os.makedirs(project_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)
    return path


def quickstart_answers(p: Dict[str, Any]) -> Dict[str, Any]:
    """Prefill the quickstart questions from a profile (the user only confirms)."""
    pr = p.get("pricing") or {}
    price = (pr.get("price_points") or [""])[0]
    product = " ".join(x for x in (p.get("one_liner"), p.get("what_it_does")) if x)[:400]
    if price and price not in product:
        product += f" Price: {price}."
    buyers = "; ".join(f"{x['segment']}" + (f" in {x['country_hint']}" if x.get("country_hint") else "") for x in p.get("for_whom") or [])
    plats = [c for c in (p.get("channels") or []) if c.lower().replace(" ", "") in
             ("facebook", "instagram", "tiktok", "reddit", "linkedin", "x", "twitter", "youtube")]
    return {"brand": p.get("name") or "", "product": product, "buyers": buyers,
            "platforms": ", ".join(plats) if plats else "", "budget": "", "tests": "ads, messages, price"}
