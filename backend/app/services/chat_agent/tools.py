"""The chat agent's tool catalog: which MCP tools the in-app agent may call, their cost class, their phase, the
slots they need and the cards the user sees before anything costs money or contacts the outside world.

Approval is decided here from the tool name and its arguments, never by the model:

* ``free``: runs at once (reads saved files, offline transforms, views in the browser).
* ``outside``: contacts public websites or connected accounts; a one-line notice with Go / Skip, remembered for the
  chat session.
* ``spend``: model calls; an approval card with people, calls per step and an estimated dollar figure, every time.

Everything here is pure (no network, no model call), so it can be tested without the engine.
"""
from __future__ import annotations

import copy
import json
import math
import re
from typing import Any, Dict, List, Optional

FREE, OUTSIDE, SPEND = "free", "outside", "spend"
RANK = {FREE: 0, OUTSIDE: 1, SPEND: 2}
PHASES = ("setup", "audience", "test", "review")

# MCP tools the chat may call. setup / start_backend / start_live are host chores the app already does.
MCP_TOOLS = (
    "doctor", "provider_setup", "understand", "quickstart", "research", "ads_import", "actuals_import",
    "campaign_plan", "analytics_audience", "intake", "real_split", "market_test", "run_test", "study", "pitch",
    "email_test", "website_test", "creative_check", "push_context", "ad_patterns", "ideas", "job_status", "results",
    "list_runs", "compare_runs", "ask_buyers", "calibrate", "backtest", "holdout_backtest", "predict", "brain_response",
    "cli",
)

# Everything the app shows can be shown inline in the chat with open_view. Every view is read-only and free.
RUN_VIEWS = ("results", "reports", "audience", "world_map", "people", "buyer_responses", "activity", "social_feed",
             "landing", "brain_response")
WORKSPACE_VIEWS = ("dashboard_map", "insights", "projects", "skills", "connectors", "settings_summary", "spend")
VIEWS = (*RUN_VIEWS, "compare", *WORKSPACE_VIEWS)
INSIGHT_PANELS = ("activity_calendar", "intent", "objections", "audiences", "trust", "spend", "live_runs")
VERDICTS = ("yes", "maybe", "no")
OBJECTION_TYPES = ("trust", "price", "effort", "unclear", "privacy", "relevance", "timing", "other")
RESPONSE_SOURCES = ("survey", "feed", "thought")
VIEW_FILTERS = {"people": ("segment", "country", "verdict", "gender", "query"),
                "buyer_responses": ("verdict", "segment", "objection", "source", "query")}
# views whose numbers come from simulated buyers (the others show this computer's own settings and lists)
SIMULATED_VIEWS = frozenset((*RUN_VIEWS, "compare", "dashboard_map", "insights"))


def _run_name(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError(f"{field} must be a saved run name.")
    return value.strip()


def normalize_view(args: Dict[str, Any]) -> Dict[str, Any]:
    """open_view arguments checked and trimmed to what the view takes, or ValueError with a plain reason.
    A missing run (or compare pair) is left to the slot form."""
    args = args if isinstance(args, dict) else {}
    view = args.get("view")
    if view not in VIEWS:
        raise ValueError(f"Choose a view: {', '.join(VIEWS)}.")
    out: Dict[str, Any] = {"view": view}
    if view in RUN_VIEWS:
        if args.get("run") not in (None, ""):
            out["run"] = _run_name(args["run"], "run")
    elif view == "compare":
        runs = args.get("runs")
        if runs is None and args.get("run") and args.get("other"):
            runs = [args["run"], args["other"]]
        if runs is not None:
            if not isinstance(runs, list) or len(runs) != 2:
                raise ValueError("compare needs runs: two saved run names.")
            out["runs"] = [_run_name(r, "runs") for r in runs]
            if out["runs"][0] == out["runs"][1]:
                raise ValueError("Choose two different runs to compare.")
    elif args.get("run") not in (None, ""):
        raise ValueError(f"{view} is a workspace view; it takes no run.")
    panel = args.get("panel")
    if panel not in (None, ""):
        if view != "insights":
            raise ValueError("Only the insights view takes a panel.")
        if panel not in INSIGHT_PANELS:
            raise ValueError(f"Choose a panel: {', '.join(INSIGHT_PANELS)}.")
        out["panel"] = panel
    filters = args.get("filters")
    if filters not in (None, {}):
        allowed = VIEW_FILTERS.get(view)
        if not allowed:
            raise ValueError(f"{view} takes no filters; filters work on people and buyer_responses.")
        if not isinstance(filters, dict):
            raise ValueError("filters must be an object.")
        unknown = [str(k) for k in filters if k not in allowed]
        if unknown:
            raise ValueError(f"{view} filters are {', '.join(allowed)}, not {', '.join(unknown)}.")
        clean = {}
        for key, value in filters.items():
            if value in (None, ""):
                continue
            if not isinstance(value, str) or len(value) > 80 or any(ord(c) < 32 for c in value):
                raise ValueError(f"The {key} filter must be a short line of text.")
            value = value.strip()
            if key in ("verdict", "objection", "source"):
                value = value.lower()
                choices = {"verdict": VERDICTS, "objection": OBJECTION_TYPES, "source": RESPONSE_SOURCES}[key]
                if value not in choices:
                    raise ValueError(f"The {key} filter is one of {', '.join(choices)}.")
            clean[key] = value
        if clean:
            out["filters"] = clean
    return out


# Tools only the app needs. They render in the browser or steer the conversation and never cost money.
APP_TOOLS: Dict[str, Dict[str, Any]] = {
    "open_view": {
        "description": "Show something inline in the chat, read from saved files (free, no model call, renders in the "
                       "browser). Run views need `run`: results, reports, audience / world_map (people on a map with "
                       "who talked to whom), people (every simulated person; filters segment, country, verdict, gender, "
                       "query), buyer_responses (what each buyer said; filters verdict, segment, objection, source, "
                       "query), activity, social_feed, landing (landing page analysis), brain_response. compare needs "
                       "`runs` [a, b]. Workspace views take no run: dashboard_map (audience geography across runs), "
                       "insights (with `panel`: activity_calendar, intent, objections, audiences, trust, spend, "
                       "live_runs), projects, skills, connectors, settings_summary, spend.",
        "parameters": {"type": "object", "properties": {
            "view": {"type": "string", "enum": list(VIEWS)},
            "run": {"type": "string", "description": "saved run name (run views)"},
            "runs": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 2,
                     "description": "two saved run names (compare)"},
            "panel": {"type": "string", "enum": list(INSIGHT_PANELS), "description": "insights panel"},
            "filters": {"type": "object", "description": "people or buyer_responses filters", "properties": {
                "segment": {"type": "string"}, "country": {"type": "string"}, "gender": {"type": "string"},
                "verdict": {"type": "string", "enum": list(VERDICTS)},
                "objection": {"type": "string", "enum": list(OBJECTION_TYPES)},
                "source": {"type": "string", "enum": list(RESPONSE_SOURCES)}, "query": {"type": "string"}}}},
            "required": ["view"]}},
    "read_run_file": {
        "description": "Read one saved file of a run (JSON, Markdown or CSV) in pages. Free.",
        "parameters": {"type": "object", "properties": {
            "run": {"type": "string"}, "file": {"type": "string"},
            "offset": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 12000}},
            "required": ["run", "file"]}},
    "browse_page": {
        "description": "Open a public page the user gave in this chat (read-only capture: text, links, screenshot).",
        "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}},
    "design_audience": {
        "description": "Propose the simulated audience as segments for the user to review and edit in a table "
                       "before anything is created. Each segment: label, count, country, cities, age_min, age_max, "
                       "gender_mix (balanced | female | male | share of women 0-1), platforms, notes, communities "
                       "(names of groups its members join). Only use facts the user or their data gave; leave the "
                       "rest empty. Free; the user confirms the table, then use the returned personas path in "
                       "market_test.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "short scenario name"},
            "segments": {"type": "array", "items": {"type": "object"}}}, "required": ["segments"]}},
    "ask_user": {
        "description": "Ask the user for missing facts in ONE short form. Use once per request, with every missing "
                       "field at once. Never invent the answers.",
        "parameters": {"type": "object", "properties": {
            "reason": {"type": "string"},
            "fields": {"type": "array", "items": {"type": "object", "properties": {
                "name": {"type": "string"}, "label": {"type": "string"},
                "type": {"type": "string", "enum": ["text", "textarea", "number", "select", "list"]},
                "options": {"type": "array", "items": {"type": "string"}}, "required": {"type": "boolean"}},
                "required": ["name", "label"]}}}, "required": ["fields"]}},
    "switch_phase": {
        "description": "Switch to the tools of another phase: setup (product, models, research, imports), audience "
                       "(who the simulated buyers are), test (run tests), review (results, compare, ask buyers, "
                       "calibrate).",
        "parameters": {"type": "object", "properties": {"phase": {"type": "string", "enum": list(PHASES)}},
                       "required": ["phase"]}},
}

ALWAYS = ("list_runs", "job_status", "ask_user", "switch_phase", "open_view")
PHASE_TOOLS: Dict[str, tuple] = {
    "setup": ("doctor", "provider_setup", "understand", "quickstart", "research", "browse_page", "ads_import",
              "actuals_import", "campaign_plan"),
    "audience": ("design_audience", "analytics_audience", "intake", "real_split", "market_test", "understand",
                 "research", "browse_page"),
    "test": ("market_test", "design_audience", "run_test", "study", "pitch", "email_test", "website_test",
             "creative_check", "push_context", "ad_patterns", "ideas", "campaign_plan", "results", "cli"),
    "review": ("results", "compare_runs", "open_view", "read_run_file", "ask_buyers", "calibrate", "backtest",
               "holdout_backtest", "predict", "real_split", "ideas", "brain_response", "cli"),
}

LABELS = {
    "doctor": "Checking MarketMirror", "provider_setup": "Checking model settings", "understand": "Reading the product",
    "quickstart": "Setting up the scenario", "research": "Reading what real people say", "ads_import": "Importing past ads",
    "actuals_import": "Importing real results", "campaign_plan": "Drafting a campaign plan",
    "analytics_audience": "Sizing the audience from analytics", "intake": "Turning customer material into personas",
    "real_split": "Splitting real answers", "market_test": "Market test", "run_test": "Running the test",
    "study": "Running the study", "pitch": "Rehearsing the pitch", "email_test": "Testing the emails",
    "website_test": "Sending visitors to the website", "creative_check": "Checking the creatives",
    "push_context": "Adding live context", "ad_patterns": "Labelling the ads", "ideas": "Finding next tests",
    "job_status": "Checking the job", "results": "Reading the results", "list_runs": "Listing saved runs",
    "compare_runs": "Comparing two runs", "ask_buyers": "Asking the simulated buyers", "calibrate": "Checking against real answers",
    "backtest": "Scoring against real ads", "holdout_backtest": "Scoring held-out experiments", "predict": "Predicting",
    "brain_response": "Predicting brain response (research)",
    "cli": "Running a MarketMirror command", "open_view": "Opening the view", "read_run_file": "Reading a saved report",
    "browse_page": "Opening the page", "design_audience": "Designing the audience", "ask_user": "Asking for details",
    "switch_phase": "Switching tools",
}

# Results that come from simulated buyers carry a Simulated badge, set by the renderer from this list.
SIMULATED = {"market_test", "run_test", "study", "pitch", "email_test", "website_test", "results", "compare_runs",
             "ask_buyers", "open_view", "predict", "ideas", "quickstart", "design_audience"}

FREE_CLI = {"forecast", "list", "status", "health", "export"}
OUTSIDE_NOTES = {
    "research": "contacts public websites (Hacker News, the App Store, Reddit and any page you gave)",
    "browse_page": "opens the public page you gave in a read-only browser",
    "understand": "reads the web page you gave",
    "creative_check": "fetches the creatives from their web addresses",
    "ad_patterns": "sends the ads to Jev, an outside labelling service",
    "provider_setup": "asks your model provider which models it offers (no model call)",
    "website_test": "sends simulated visitors to the live website",
    "brain_response": "sends the ads to your own TRIBE v2 brain-response server (MM_BRAIN_RESPONSE_URL)",
}


def all_tools() -> List[str]:
    return [*MCP_TOOLS, *APP_TOOLS]


def is_known(name: str) -> bool:
    return name in MCP_TOOLS or name in APP_TOOLS


def phase_tools(phase: str) -> List[str]:
    return list(dict.fromkeys([*PHASE_TOOLS.get(phase, PHASE_TOOLS["test"]), *ALWAYS]))


def _https(values: Any) -> bool:
    return any(isinstance(v, str) and v.lower().startswith(("http://", "https://")) for v in values)


def classify(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """{cost, notes}: the cost class of one call, and what it touches outside this computer."""
    args = args if isinstance(args, dict) else {}
    cost, notes = FREE, []

    def bump(level, note=None):
        nonlocal cost
        if RANK[level] > RANK[cost]:
            cost = level
        if note and note not in notes:
            notes.append(note)

    if name in ("market_test", "quickstart", "run_test", "study", "pitch", "email_test", "ask_buyers",
                "push_context", "ideas", "campaign_plan"):
        bump(SPEND)
    if name == "understand":
        bump(SPEND)
        if args.get("url"):
            bump(OUTSIDE, OUTSIDE_NOTES["understand"])
    if name == "quickstart" and args.get("url"):
        bump(OUTSIDE, OUTSIDE_NOTES["understand"])
    if name == "intake" and (args.get("engine") or "llm") != "supplied":
        bump(SPEND)
    if name == "ad_patterns":
        engine = args.get("engine") or "auto"
        if engine == "jev":
            bump(OUTSIDE, OUTSIDE_NOTES["ad_patterns"])
        elif engine != "supplied":
            bump(SPEND)
        if args.get("vision"):
            bump(SPEND)
    if name == "creative_check":
        bump(SPEND)        # one vision-model call per creative
        media = [c.get(k) for c in args.get("creatives") or [] if isinstance(c, dict) for k in ("image", "video")]
        if _https(media):
            bump(OUTSIDE, OUTSIDE_NOTES["creative_check"])
    if name == "website_test":
        bump(SPEND)
        bump(OUTSIDE, OUTSIDE_NOTES["website_test"])
    if name in ("research", "browse_page", "brain_response"):
        bump(OUTSIDE, OUTSIDE_NOTES[name])
    if name == "provider_setup" and args.get("action") == "check":
        bump(OUTSIDE, OUTSIDE_NOTES["provider_setup"])
    if name == "cli":
        argv = args.get("args") if isinstance(args.get("args"), list) else []
        if not argv or str(argv[0]) not in FREE_CLI:
            bump(SPEND)
    return {"cost": cost, "notes": notes}


def refusal(name: str, args: Dict[str, Any]) -> Optional[str]:
    """A reason the chat never makes this call, or None."""
    if name == "provider_setup" and args.get("action") not in (None, "list", "status", "check"):
        return "Model keys and providers are changed in Model settings, not from the chat."
    if name == "cli":
        argv = args.get("args") if isinstance(args.get("args"), list) else []
        if argv and str(argv[0]) in ("setup", "configure", "provider") or any("key" in str(a).lower() for a in argv[:2]):
            return "That command changes the installation or keys; use Settings instead."
    return None


# ---------------------------------------------------------------------------
# spend estimates (rough, shown before approval; the server's own spend_plan for market_test)
# ---------------------------------------------------------------------------

QUICKSTART_PEOPLE = {"small": 12, "medium": 24, "large": 48}


def estimate_calls(name: str, args: Dict[str, Any], people: Optional[int]) -> Dict[str, int]:
    """Model calls by step for a spend tool other than market_test (market_test uses the MCP server's spend_plan)."""
    a = args if isinstance(args, dict) else {}
    p = people or 0
    spec = a.get("spec") if isinstance(a.get("spec"), dict) else {}
    if name == "run_test":
        variants = spec.get("variants") if isinstance(spec.get("variants"), list) else []
        return {"test": p * max(1, len(variants))} if p else {}
    if name == "study":
        scen = len(spec.get("scenarios") or []) or 1
        seeds = len(spec.get("seeds") or []) or 1
        steps = len(spec.get("steps") or []) or 1
        return {"study": p * scen * seeds * steps} if p else {}
    if name == "pitch":
        return {"pitch": p * 2} if p else {}
    if name == "email_test":
        return {"email_test": p * max(1, len(a.get("emails") or []))} if p else {}
    if name == "website_test":
        visitors = int(spec.get("max_personas") or 3)
        cap = spec.get("max_model_calls")
        return {"visitors": int(cap) if cap else visitors * int(spec.get("max_steps") or 15)}
    if name == "ask_buyers":
        if a.get("action") == "ask":
            return {"answer": 1}
        n = int(a.get("people") or 6)
        return {"focus_group": n * (2 + len(a.get("guide") or [])) + 2}
    if name == "understand":
        return {"profile": 1}
    if name == "quickstart":
        size = QUICKSTART_PEOPLE.get(str((a.get("answers") or {}).get("size") or "small"), 12)
        return {"people": math.ceil(size / 5) + size + math.ceil(size / 4), "profile": 1 if a.get("from_docs") or a.get("url") else 0}
    if name == "intake":
        return {"profiles": int(a.get("max_people") or len(a.get("rows") or []) or 20)}
    if name in ("ideas", "campaign_plan"):
        return {name: 2}
    if name == "creative_check":
        return {"vision": max(1, len(a.get("creatives") or []))}
    if name == "ad_patterns":
        n = len(a.get("rows") or []) or int(a.get("max_ads") or 0)
        return {"labels": math.ceil(n / 5)} if n else {}
    if name == "push_context":
        return {}
    return {}


def plan_from(calls: Dict[str, int], people: Optional[int], usd_per_call: float) -> Dict[str, Any]:
    calls = {k: int(v) for k, v in calls.items() if v}
    total = sum(calls.values())
    known = bool(calls) or people is not None
    return {"people": people, "model_calls": calls, "total_calls": total if known else None,
            "usd_estimate": round(total * usd_per_call, 2) if known else None, "usd_per_call": usd_per_call}


def _usd(v: Optional[float]) -> str:
    return "unknown" if v is None else f"about ${v:.2f}"


def spend_card(name: str, args: Dict[str, Any], plan: Dict[str, Any], *, elicitation: Optional[Dict[str, Any]] = None,
               fit: Optional[Dict[str, Any]] = None, notes: Optional[List[str]] = None) -> Dict[str, Any]:
    """The approval card. For market_test the options and message come from the MCP server's own elicitation
    (spend_question), so the in-app card says exactly what an outside agent's user is asked."""
    if elicitation:
        schema = ((elicitation.get("requestedSchema") or {}).get("properties") or {}).get("decision") or {}
        options = [{"value": o.get("const"), "label": {"run": "Run", "people_first": "Create people first",
                                                       "stop": "Stop"}.get(o.get("const"), o.get("title")),
                    "detail": o.get("title")} for o in schema.get("oneOf") or [] if isinstance(o, dict)]
        if not any(o["value"] == "stop" for o in options):
            options.append({"value": "stop", "label": "Stop", "detail": "Run nothing"})
        message = str(elicitation.get("message") or "")
    else:
        options = [{"value": "run", "label": "Run", "detail": "Spend on model calls now"},
                   {"value": "stop", "label": "Stop", "detail": "Run nothing"}]
        message = f"{LABELS.get(name, name)} makes model calls."
    for o in options:
        if o["value"] == "people_first":
            people_calls = (plan.get("model_calls") or {}).get("people")
            usd = round(people_calls * plan["usd_per_call"], 2) if people_calls else None
            o["detail"] = ("Still spends on the persona planner: "
                           + (f"~{people_calls} model calls ({_usd(usd)})" if people_calls else "a cost known once the people are planned")
                           + ". No test steps run until you approve them.")
    card = {"kind": "spend", "tool": name, "title": f"Approve spend: {LABELS.get(name, name)}", "message": message,
            "people": plan.get("people"), "steps": plan.get("model_calls") or {}, "total_calls": plan.get("total_calls"),
            "usd_estimate": plan.get("usd_estimate"), "usd_per_call": plan.get("usd_per_call"), "options": options,
            "estimate_note": "A rough estimate at a list price per call; the real cost depends on the model and prompt lengths.",
            "notes": list(notes or [])}
    if name == "market_test":
        usd = plan.get("usd_estimate")
        card["max_spend_usd"] = {"suggested": round(max(1.0, (usd or 0) * 1.5), 2), "max": 1000,
                                 "help": "Hard cap: no new model call starts once the estimated spend reaches it."}
    if fit and fit.get("warnings"):
        card["fit_check"] = fit
    return card


def outside_card(name: str, notes: List[str]) -> Dict[str, Any]:
    note = "; ".join(notes) or "contacts the outside world"
    return {"kind": "outside", "tool": name, "title": LABELS.get(name, name),
            "message": f"{LABELS.get(name, name)} {note}. Allowed once, it is remembered for this chat.",
            "options": [{"value": "go", "label": "Go"}, {"value": "skip", "label": "Skip"}]}


# ---------------------------------------------------------------------------
# required slots: ask for what is missing once, in one form
# ---------------------------------------------------------------------------

def _get(obj: Any, path: str) -> Any:
    cur = obj
    for part in path.split("."):
        if isinstance(cur, list) and part.isdigit():
            idx = int(part)
            cur = cur[idx] if idx < len(cur) else None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _filled(value: Any, minimum: int = 1) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return len(value) >= minimum
    return True


def _slot(path, label, type_="text", any_of=None, minimum=1, options=None, when=None):
    return {"path": path, "label": label, "type": type_, "any_of": any_of or [path], "min": minimum,
            "options": options, "when": when}


TEST_TYPES = ["ad", "message", "price", "offer", "positioning", "naming", "landing", "launch", "pitch", "email",
              "creator_post", "channel_mix", "maxdiff", "conjoint", "gabor_granger"]

SLOTS: Dict[str, List[Dict[str, Any]]] = {
    "quickstart": [_slot("answers.brand", "Brand name"),
                   _slot("answers.product", "What you sell, for whom, at what price", "textarea"),
                   _slot("answers.buyers", "Who the buyers are and where they live", "textarea")],
    "market_test": [_slot("config.requirement", "What should the test find out?", "textarea",
                          any_of=["config.requirement", "config.seeds"]),
                    _slot("config.auto_personas", "How many simulated people?", "number",
                          any_of=["config.personas", "config.auto_personas", "config.simulation_id", "config.analytics"])],
    "run_test": [_slot("simulation_id", "Which simulated people (simulation)?", "simulation"),
                 _slot("spec.type", "What kind of test?", "select", options=TEST_TYPES),
                 _slot("spec.variants", "The options to compare, one per line", "list", minimum=2,
                       when=lambda a: (_get(a, "spec.type") or "") != "conjoint")],
    "pitch": [_slot("simulation_id", "Which simulated people (simulation)?", "simulation"),
              _slot("script", "Your pitch script", "textarea")],
    "email_test": [_slot("simulation_id", "Which simulated people (simulation)?", "simulation"),
                   _slot("emails", "Emails: subject on the first line, body below, a blank line between emails", "emails")],
    "ask_buyers": [_slot("simulation_id", "Which simulated people (simulation)?", "simulation"),
                   _slot("agent_id", "Which person (number)?", "number", when=lambda a: a.get("action") == "ask"),
                   _slot("message", "Your question", "textarea", when=lambda a: a.get("action") == "ask"),
                   _slot("guide", "Discussion questions, one per line", "list", when=lambda a: a.get("action") != "ask")],
    "website_test": [_slot("simulation_id", "Which simulated people (simulation)?", "simulation"),
                     _slot("spec.url", "Website address")],
    "campaign_plan": [_slot("goal", "Campaign goal"), _slot("budget.amount", "Budget amount", "number")],
    "calibrate": [_slot("run", "Which run?", "run"), _slot("real_csv", "Path of the real answers CSV")],
    "backtest": [_slot("run", "Which run?", "run"), _slot("actuals", "Path of the real ad results (from ads_import)")],
    "research": [_slot("query", "What should I look up?")],
    "understand": [_slot("url", "Product page address or document",
                         any_of=["docs", "url", "project", "ads_file"])],
    "compare_runs": [_slot("runs.0", "First run", "run", any_of=["runs.0"]),
                     _slot("runs.1", "Second run", "run", any_of=["runs.1"])],
    "analytics_audience": [_slot("files", "Analytics export file paths, one per line", "list",
                                 any_of=["files", "rows", "reports"])],
    "intake": [_slot("files", "Customer material file paths, one per line", "list", any_of=["files", "rows"])],
    "results": [_slot("run", "Which run?", "run")],
    "open_view": [_slot("run", "Which run?", "run", when=lambda a: a.get("view") in RUN_VIEWS),
                  _slot("runs.0", "First run", "run", any_of=["runs.0"], when=lambda a: a.get("view") == "compare"),
                  _slot("runs.1", "Second run", "run", any_of=["runs.1"], when=lambda a: a.get("view") == "compare")],
}


def missing_slots(name: str, args: Dict[str, Any], *, runs: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Form fields for the slots this call still needs (empty when nothing is missing)."""
    args = args if isinstance(args, dict) else {}
    runs = runs or []
    fields = []
    for slot in SLOTS.get(name, []):
        if slot["when"] and not slot["when"](args):
            continue
        if any(_filled(_get(args, p), slot["min"]) for p in slot["any_of"]):
            continue
        field = {"name": slot["path"], "label": slot["label"], "type": slot["type"], "required": True}
        if slot["type"] == "select":
            field["options"] = [{"value": o, "label": o.replace("_", " ")} for o in slot["options"] or []]
        elif slot["type"] == "simulation":
            field.update(type="select", options=[{"value": r["simulation_id"], "label": r.get("title") or r["name"]}
                                                 for r in runs if r.get("simulation_id")])
            if not field["options"]:
                field["type"] = "text"
        elif slot["type"] == "run":
            field.update(type="select", options=[{"value": r["name"], "label": r.get("title") or r["name"]} for r in runs])
            if not field["options"]:
                field["type"] = "text"
        elif slot["type"] == "emails":
            field["type"] = "textarea"
        fields.append(field)
    return fields


def _set(obj: Dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cur: Any = obj
    for i, part in enumerate(parts[:-1]):
        nxt_is_index = parts[i + 1].isdigit()
        if isinstance(cur, list):
            idx = int(part)
            while len(cur) <= idx:
                cur.append([] if nxt_is_index else {})
            cur = cur[idx]
            continue
        if not isinstance(cur.get(part), (dict, list)):
            cur[part] = [] if nxt_is_index else {}
        cur = cur[part]
    last = parts[-1]
    if isinstance(cur, list):
        idx = int(last)
        while len(cur) <= idx:
            cur.append(None)
        cur[idx] = value
    else:
        cur[last] = value


def _emails(text: str) -> List[Dict[str, Any]]:
    out = []
    for i, block in enumerate(b for b in re.split(r"\n\s*\n", text.strip()) if b.strip()):
        lines = block.strip().splitlines()
        out.append({"id": f"email_{i + 1}", "subject": lines[0].strip()[:300], "body": "\n".join(lines[1:]).strip()})
    return out


def coerce(field_type: str, value: Any) -> Any:
    if value is None:
        return None
    if field_type == "number":
        try:
            num = float(value)
        except (TypeError, ValueError):
            raise ValueError("Enter a number.") from None
        if not math.isfinite(num):
            raise ValueError("Enter a number.")
        return int(num) if num.is_integer() else num
    if field_type == "list":
        items = value if isinstance(value, list) else str(value).splitlines()
        return [str(v).strip()[:2000] for v in items if str(v).strip()][:50]
    if field_type == "emails":
        return _emails(str(value))
    return str(value).strip()[:12000]


def apply_form(args: Dict[str, Any], fields: List[Dict[str, Any]], values: Dict[str, Any], *, tool: str = "") -> Dict[str, Any]:
    """The call's arguments with the user's form answers filled in (only the asked fields)."""
    out = copy.deepcopy(args if isinstance(args, dict) else {})
    if not isinstance(values, dict):
        raise ValueError("Send the form answers as an object.")
    kinds = {s["path"]: s["type"] for s in SLOTS.get(tool, [])}
    for field in fields:
        name = field["name"]
        if name not in values or values[name] in (None, ""):
            continue
        _set(out, name, coerce(kinds.get(name, field.get("type", "text")), values[name]))
    return out


def sanitize_fields(fields: Any) -> List[Dict[str, Any]]:
    """ask_user fields from the model, bounded to a short plain form."""
    out = []
    for f in fields if isinstance(fields, list) else []:
        if not isinstance(f, dict) or not re.fullmatch(r"[A-Za-z0-9_.]{1,60}", str(f.get("name") or "")):
            continue
        ftype = f.get("type") if f.get("type") in ("text", "textarea", "number", "select", "list") else "text"
        field = {"name": f["name"], "label": str(f.get("label") or f["name"])[:200], "type": ftype,
                 "required": bool(f.get("required", True))}
        if ftype == "select":
            opts = [str(o)[:120] for o in f.get("options") or [] if isinstance(o, (str, int, float))][:20]
            if not opts:
                field["type"] = "text"
            else:
                field["options"] = [{"value": o, "label": o} for o in opts]
        out.append(field)
        if len(out) >= 8:
            break
    return out


# ---------------------------------------------------------------------------
# audience design: an editable segments table -> a persona spec
# ---------------------------------------------------------------------------

SEGMENT_KEYS = ("label", "count", "country", "cities", "age_min", "age_max", "gender_mix", "platforms", "notes",
                "communities")
MAX_PEOPLE = 500


def _list(v: Any) -> List[str]:
    if isinstance(v, str):
        v = re.split(r"[,\n]", v)
    return [str(x).strip()[:120] for x in v or [] if str(x).strip()][:20] if isinstance(v, list) else []


def normalize_segments(segments: Any) -> List[Dict[str, Any]]:
    if not isinstance(segments, list) or not segments:
        raise ValueError("Add at least one segment.")
    out = []
    for raw in segments[:30]:
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or "").strip()[:120]
        if not label:
            raise ValueError("Every segment needs a label.")
        try:
            count = int(raw.get("count") or 5)
        except (TypeError, ValueError):
            raise ValueError(f"Segment {label!r}: count must be a whole number.") from None
        seg = {"label": label, "count": max(1, min(count, 200)), "country": str(raw.get("country") or "").strip()[:80],
               "cities": _list(raw.get("cities")), "platforms": _list(raw.get("platforms")),
               "notes": str(raw.get("notes") or "").strip()[:2000], "communities": _list(raw.get("communities")),
               "gender_mix": str(raw.get("gender_mix") or "balanced").strip().lower()[:20]}
        age = raw.get("age_range")
        if isinstance(age, str) and re.fullmatch(r"\s*\d{1,3}\s*[-–]\s*\d{1,3}\s*", age):
            lo, hi = (int(x) for x in re.split(r"[-–]", age))
            raw = {**raw, "age_min": lo, "age_max": hi}
        for key, default in (("age_min", 18), ("age_max", 65)):
            try:
                seg[key] = max(10, min(100, int(raw.get(key) or default)))
            except (TypeError, ValueError):
                seg[key] = default
        if seg["age_min"] > seg["age_max"]:
            seg["age_min"], seg["age_max"] = seg["age_max"], seg["age_min"]
        out.append(seg)
    if sum(s["count"] for s in out) > MAX_PEOPLE:
        raise ValueError(f"Keep the audience at {MAX_PEOPLE} people or fewer.")
    return out


def persona_spec(segments: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The persona planner's spec: segments, plus one community per name with the segments that join it."""
    communities: Dict[str, List[str]] = {}
    for seg in segments:
        for name in seg.get("communities") or []:
            communities.setdefault(name, []).append(seg["label"])
    return {"segments": [{k: v for k, v in seg.items() if k != "communities"} for seg in segments],
            "communities": [{"name": n, "segments": labels} for n, labels in communities.items()]}


def pseudo_people(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One row per planned person (segment + country), the shape the fit check reads."""
    return [{"segment": s["label"], "country": s.get("country") or ""} for s in segments for _ in range(s["count"])]


def compact(value: Any, limit: int = 12000) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + f"... [truncated, {len(text)} characters in total]"
