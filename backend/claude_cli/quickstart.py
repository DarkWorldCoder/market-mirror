"""
quickstart.py - a few plain questions -> a ready scenario folder for MarketMirror.

Writes scenarios/<brand>/ with brief.md, question.txt, personas.json (auto, sized), creatives.json (two captions
per platform), messages.txt, posts.json + events.json (launch calendar when asked), pitch.md + rebuttals.md (when
asked), past_ads.md/.json (from an ad export when given) and market_test.json that ties them together. Stdlib only.
Agents pass --answers @file.json; people answer on the terminal.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from typing import Any, Callable, Dict, List, Optional

QUESTIONS: List[Dict[str, Any]] = [
    {"key": "brand", "q": "Brand or product name?", "required": True},
    {"key": "product", "q": "What do you sell, for whom, and at what price? (one or two sentences)", "required": True},
    {"key": "buyers", "q": "Who buys it and where? e.g. 'young professionals in India and the Philippines; parents in Kenya'",
     "required": True},
    {"key": "platforms", "q": "Where do they see you? (facebook, instagram, tiktok, reddit, linkedin, x; comma separated)",
     "default": "facebook, instagram"},
    {"key": "tests", "q": "What do you want to test? (ads, messages, price, launch, pitch; comma separated)",
     "default": "ads, messages, price"},
    {"key": "budget", "q": "Monthly ad budget and currency, e.g. '500 USD'", "default": "300 USD"},
    {"key": "size", "q": "How many simulated people? small (20), medium (60) or large (150)", "default": "small"},
    {"key": "past_ads", "q": "Past ad results export (CSV/JSON path), or leave empty", "default": ""},
    {"key": "docs", "q": "Extra documents to learn from (paths, comma separated), or leave empty", "default": ""},
]
SIZES = {"small": 20, "medium": 60, "large": 150}
GENERATED = {"brief.md", "question.txt", "personas.json", "creatives.json", "messages.txt", "posts.json", "events.json",
             "pitch.md", "rebuttals.md", "market_test.json", "past_ads.md", "past_ads.json"}
PLATFORMS = ["facebook", "instagram", "tiktok", "reddit", "linkedin", "x"]
TESTS = ["ads", "messages", "price", "launch", "pitch"]


def slug(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", str(s or "")).strip("_").lower()
    return s[:40] or "my_test"


def _list(v: Any, allowed: Optional[List[str]] = None) -> List[str]:
    if isinstance(v, str):
        items = [x.strip().lower() for x in re.split(r"[,;/]+", v) if x.strip()]
    else:
        items = [str(x).strip().lower() for x in (v or [])]
    items = ["x" if x in ("twitter", "x.com") else x for x in items]
    return [x for x in items if not allowed or x in allowed]


def _paths(v: Any) -> List[str]:
    if isinstance(v, str):
        return [x.strip() for x in v.split(",") if x.strip()]
    return [str(x) for x in (v or []) if str(x).strip()]


def _budget(v: Any) -> Dict[str, Any]:
    s = str(v or "").strip()
    m = re.search(r"(\d[\d,.]*)", s)
    amount = float(m.group(1).replace(",", "")) if m else 300.0
    cur = re.sub(r"[\d,.\s]", "", s).upper()[:4] or "USD"
    return {"amount": amount, "currency": cur}


def load_answers(arg: str) -> Dict[str, Any]:
    path = arg[1:] if arg.startswith("@") else arg
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("answers must be a JSON object keyed by question key")
    return data


def ask(stdin, stderr, prefill: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Terminal wizard; stderr for prompts so stdout stays JSON. prefill (from `understand`) becomes the defaults."""
    answers: Dict[str, Any] = {}
    prefill = prefill or {}
    stderr.write("MarketMirror quickstart. Press Enter to accept a default; empty answers are fine.\n\n")
    for q in QUESTIONS:
        default = str(prefill.get(q["key"]) or q.get("default", ""))
        while True:
            stderr.write(q["q"] + (f" [{default}]" if default else "") + "\n> ")
            stderr.flush()
            line = stdin.readline()
            if not line:
                raise ValueError("no input")
            v = line.strip() or default
            if v or not q.get("required"):
                answers[q["key"]] = v
                break
            stderr.write("(this one is needed)\n")
    return answers


def normalize(answers: Dict[str, Any]) -> Dict[str, Any]:
    a = {q["key"]: answers.get(q["key"], q.get("default", "")) for q in QUESTIONS}
    for q in QUESTIONS:
        if q.get("required") and not str(a[q["key"]]).strip():
            raise ValueError(f"answer needed for '{q['key']}': {q['q']}")
    a["platforms"] = _list(a["platforms"], PLATFORMS) or ["facebook", "instagram"]
    a["tests"] = _list(a["tests"], TESTS) or ["ads", "messages"]
    size = str(a["size"] or "small").strip().lower()
    a["people"] = SIZES.get(size) or max(8, min(500, int(re.sub(r"\D", "", size) or 20)))
    a["budget"] = _budget(a["budget"])
    a["past_ads"] = str(a["past_ads"] or "").strip()
    a["docs"] = _paths(a["docs"])
    for k in ("brand", "product", "buyers"):
        a[k] = str(a[k]).strip()
    a["price"] = (re.search(r"(\d[\d,.]*)\s*(?:[A-Z]{3}|\$|€|£|₹|/month|/mo|per month)", a["product"]) or [None, None])[1] if a["product"] else None
    return a


def brief_md(a: Dict[str, Any]) -> str:
    return (f"# {a['brand']}\n\n## What we sell\n\n{a['product']}\n\n## Who buys it and where\n\n{a['buyers']}\n\n"
            f"## Where they see us\n\n{', '.join(a['platforms'])}\n\n## Budget\n\n{a['budget']['amount']:g} {a['budget']['currency']} per month\n\n"
            f"## What we want to learn\n\n" + "\n".join(f"- {t}" for t in a["tests"]) + "\n")


def question_txt(a: Dict[str, Any]) -> str:
    return (f"Simulate the market for {a['brand']}: {a['product']} Buyers: {a['buyers']}. They see the brand on "
            f"{', '.join(a['platforms'])}. Predict which audience and country are most likely to take the offer, which "
            f"message and ad work best, the main objections by audience, and the price people accept.")


def personas_json(a: Dict[str, Any]) -> Dict[str, Any]:
    return {"auto": True, "auto_total": a["people"], "auto_communities": True, "interview": True,
            "notes": f"Buyers: {a['buyers']}. Every country, age band and income level that buys; include sceptics."}


def captions(a: Dict[str, Any]) -> List[Dict[str, Any]]:
    brand, product = a["brand"], a["product"]
    first = re.split(r"(?<=[.!?])\s", product)[0][:140]
    out = []
    for p in a["platforms"]:
        page = brand if p in ("facebook", "linkedin") else brand.lower().replace(" ", "")
        out.append({"id": f"{p[:2]}_benefit", "name": f"Benefit ({p})", "platform": p, "format": "image", "page": page,
                    "text": f"{first}\nTry {brand} today.", "headline": first[:60], "cta": "Learn more",
                    "media": f"the product in use by one of the buyers described: {a['buyers'][:80]}"})
        out.append({"id": f"{p[:2]}_proof", "name": f"Proof ({p})", "platform": p, "format": "video", "page": page,
                    "text": f"Real people, real results. See what {brand} did for someone like you.\n{first}",
                    "headline": f"Why people switch to {brand}", "cta": "See how",
                    "media": "a short testimonial clip with a before/after"})
    return out


def creatives_json(a: Dict[str, Any], benchmarks: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {"creatives": captions(a),
                           "landing": {"load_seconds": 2.5, "form_fields": 3, "asks_card": False, "mobile_ok": True},
                           "budget": a["budget"]["amount"], "currency": a["budget"]["currency"]}
    if benchmarks:
        out["benchmarks"] = benchmarks
    return out


def messages_txt(a: Dict[str, Any]) -> str:
    brand = a["brand"]
    first = re.split(r"(?<=[.!?])\s", a["product"])[0][:140]
    return "\n---\n".join([
        f"{first} Try {brand} today.",
        f"Join the people already using {brand}. {first}",
        f"{brand}: " + (f"from {a['price']} " if a.get("price") else "") + "with no commitment. Cancel any time.",
    ]) + "\n"


def launch_events(a: Dict[str, Any]) -> Dict[str, Any]:
    brand = a["brand"]
    first = re.split(r"(?<=[.!?])\s", a["product"])[0][:140]
    posts = [{"agent": brand, "platform": "both", "content": f"Something new is coming from {brand}. Can you guess what?"}]
    events = [
        {"round": 1, "agent": brand, "platform": "both", "content": f"Teaser: {first} Launching this week."},
        {"round": 3, "agent": brand, "platform": "both", "content": f"{brand} is live! {first} Link in bio."},
        {"round": 5, "agent": brand, "platform": "both",
         "content": f"Launch offer: " + (f"{a['price']} " if a.get("price") else "") + "for the first 100 people. Ends Sunday."},
        {"round": 7, "agent": brand, "platform": "both", "content": f"A competitor just dropped their price. Here is why {brand} is still the better deal."},
    ]
    return {"posts": posts, "events": events}


def pitch_md(a: Dict[str, Any]) -> str:
    return (f"Hi, I'm from {a['brand']}. {a['product']}\n\nMost people like you ({a['buyers'][:120]}) tell us the same two things: "
            "they want results without a big commitment, and they want to know it will work for them.\n\n"
            "Can I show you how it works in two minutes, and you tell me if it fits?\n")


def rebuttals_md(a: Dict[str, Any]) -> str:
    return ("## price\nFair question. Compare it with what you spend today on the same problem; most people find it costs less "
            "per week than one coffee, and you can cancel any time.\n\n"
            "## trust\nYou don't have to take my word for it: here are three people like you and what changed for them. "
            "And there is no card needed to try it.\n\n"
            "## timing\nUnderstood. What would make it the right time? If I follow up then, would that help?\n\n"
            "## any\nWhat is the one thing that would have to be true for you to say yes? Let's see if we can make that true.\n")


def market_test(a: Dict[str, Any], files: Dict[str, str]) -> Dict[str, Any]:
    cfg: Dict[str, Any] = {
        "name": slug(a["brand"]), "title": f"{a['brand']} market test", "brand": a["brand"],
        "seeds": list(dict.fromkeys(["brief.md"] + ([os.path.basename(files["past_ads_md"])] if files.get("past_ads_md") else [])
                                    + list(a.get("doc_names") or []))),
        "requirement": "question.txt", "personas": "personas.json", "platform": "parallel",
        "rounds": 6 if "launch" in a["tests"] else 3, "panel": {"analysts": 5, "brief": question_txt(a)}, "report": True,
    }
    if "ads" in a["tests"]:
        cfg["creatives"] = "creatives.json"
        cfg["exposures"] = 2
        cfg["seeds_n"] = 2
    survey: Dict[str, Any] = {"offer": a["product"][:200], "goal": "take the offer (sign up, buy or start the trial)"}
    if "messages" in a["tests"]:
        survey["messages"] = "messages.txt"
        survey["split"] = True
    if "price" in a["tests"]:
        survey["pricing"] = a["budget"]["currency"]
    cfg["survey"] = survey
    if "launch" in a["tests"]:
        cfg["posts"] = "posts.json"
        cfg["events"] = "events.json"
    if "pitch" in a["tests"]:
        cfg["pitch"] = {"script": "pitch.md", "rebuttals": "rebuttals.md", "channel": "message"}
    cfg["budget"] = a["budget"]
    cfg["approve_spend"] = False
    return cfg


def build_scenario(answers: Dict[str, Any], root: str, ads_import: Optional[Callable[..., Any]] = None) -> Dict[str, Any]:
    a = normalize(answers)
    os.makedirs(root, exist_ok=True)
    files: Dict[str, str] = {}

    def put(name: str, content: Any) -> None:
        path = os.path.join(root, name)
        with open(path, "w", encoding="utf-8") as f:
            if isinstance(content, str):
                f.write(content)
            else:
                json.dump(content, f, ensure_ascii=False, indent=2)
        files[name.rsplit(".", 1)[0] if name.count(".") == 1 else name] = path

    put("brief.md", brief_md(a))
    put("question.txt", question_txt(a))
    put("personas.json", personas_json(a))
    benchmarks = None
    if a["past_ads"]:
        if not os.path.exists(a["past_ads"]):
            raise ValueError(f"past ads file not found: {a['past_ads']}")
        if ads_import is None:
            raise ValueError("past ads given but no importer available")
        md = os.path.join(root, "past_ads.md")
        js = os.path.join(root, "past_ads.json")
        imported = ads_import(a["past_ads"], md, js, f"{a['brand']}: past ad results")
        files["past_ads_md"], files["past_ads_json"] = md, js
        benchmarks = (imported or {}).get("benchmarks") if isinstance(imported, dict) else None
        if benchmarks is None:
            try:
                with open(js, encoding="utf-8") as f:
                    benchmarks = json.load(f).get("benchmarks")
            except (OSError, ValueError):
                benchmarks = None
    doc_names: List[str] = []
    for d in a["docs"]:
        if not os.path.exists(d):
            raise ValueError(f"document not found: {d}")
        name = os.path.basename(d)
        if os.path.abspath(os.path.dirname(d)) != os.path.abspath(root):
            if name in GENERATED or os.path.exists(os.path.join(root, name)):
                name = "doc_" + name                      # never overwrite a generated file (brief.md, ...)
            shutil.copy(d, os.path.join(root, name))
        doc_names.append(name)
    a["doc_names"] = list(dict.fromkeys(doc_names))
    if "ads" in a["tests"]:
        put("creatives.json", creatives_json(a, benchmarks))
    put("messages.txt", messages_txt(a))
    if "launch" in a["tests"]:
        ev = launch_events(a)
        put("posts.json", ev["posts"])
        put("events.json", ev["events"])
    if "pitch" in a["tests"]:
        put("pitch.md", pitch_md(a))
        put("rebuttals.md", rebuttals_md(a))
    put("market_test.json", market_test(a, files))
    return {"scenario": os.path.abspath(root), "config": os.path.abspath(os.path.join(root, "market_test.json")),
            "files": sorted(os.listdir(root)), "people": a["people"], "tests": a["tests"], "platforms": a["platforms"],
            "edit_first": ["creatives.json: replace the two template captions per platform with your real ads",
                           "messages.txt: your real messages, separated by ---",
                           "personas.json: add 'segments' if you know your audiences; auto mode plans them otherwise"]}


def key_configured(repo_root: str) -> bool:
    """True when an API key is set, without ever reading the value into the output."""
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("LLM_API_KEY"):
        return True
    env = os.path.join(repo_root, ".env")
    try:
        with open(env, encoding="utf-8") as f:
            for line in f:
                if line.startswith("LLM_API_KEY="):
                    v = line.split("=", 1)[1].strip().strip("'\"")
                    return bool(v) and v != "your_api_key_here"
    except OSError:
        return False
    return False


def ensure_env(repo_root: str, stdin, stderr) -> Dict[str, Any]:
    """Interactive only: create .env from .env.example and ask for the key (typed hidden, never printed)."""
    env, example = os.path.join(repo_root, ".env"), os.path.join(repo_root, ".env.example")
    if not os.path.exists(env) and os.path.exists(example):
        shutil.copy(example, env)
        stderr.write(f"created {env}\n")
    if key_configured(repo_root):
        return {"env": env, "key": "set"}
    clis = [c for c in ("claude", "codex") if shutil.which(c)]
    if clis:
        stderr.write(f"No API key found, but {' and '.join(clis)} CLI is installed. Use that login instead of a key? "
                     "(slower, your subscription's limits, personal use) [y/N]: ")
        stderr.flush()
        if (stdin.readline() or "").strip().lower().startswith("y"):
            be = clis[0]
            lines = []
            try:
                with open(env, encoding="utf-8") as f:
                    lines = [ln for ln in f.read().splitlines()
                             if not ln.startswith(("LLM_PROVIDER=", "LLM_BASE_URL=", "LLM_API_KEY=", "LLM_GATEWAY=", "LLM_MODEL_NAME="))]
            except OSError:
                pass
            lines += ["LLM_PROVIDER=openai", "LLM_BASE_URL=http://127.0.0.1:5055/v1", "LLM_API_KEY=gateway", f"LLM_GATEWAY={be}", f"LLM_MODEL_NAME={be}"]
            with open(env, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            stderr.write(f"Gateway settings written. Start it with: python backend/gateway/local_gateway.py --backend {be}\n")
            return {"env": env, "key": f"gateway ({be})"}
    stderr.write("No Anthropic API key found. Paste it now (input is hidden), or press Enter to add it to .env later:\n")
    try:
        import getpass
        key = getpass.getpass("API key: ", stream=stderr) if stdin.isatty() else stdin.readline().strip()
    except (EOFError, OSError):
        key = ""
    if not key:
        return {"env": env, "key": "missing (edit LLM_API_KEY in .env)"}
    lines = []
    try:
        with open(env, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        pass
    lines = [ln for ln in lines if not ln.startswith("LLM_API_KEY=")]
    lines.append("LLM_API_KEY=" + key)
    with open(env, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    try:
        os.chmod(env, 0o600)
    except OSError:
        pass
    return {"env": env, "key": "set"}
