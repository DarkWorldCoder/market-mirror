"""A fake model and a fake tool layer for the chat agent tests: no model calls, no network, no engine."""
import copy
import itertools

from app.services.chat_agent import state, tools as T
from app.services.chat_agent.bridge import ApprovalNeeded, Executor
from app.services.chat_agent.model import Reply

SESSION = "chat-test-0001"
SIM = "sim_abc123"
RUNS = [{"name": "fitloop_v2", "title": "FitLoop v2", "decision": "iterate", "people": 24, "simulation_id": SIM, "status": "completed"},
        {"name": "fitloop_v1", "title": "FitLoop v1", "decision": "go", "people": 20, "simulation_id": "sim_old", "status": "completed"}]


def call(name, args=None, cid=None):
    return {"id": cid or f"c_{name}_{next(_ids)}", "name": name, "arguments": args or {}}


_ids = itertools.count(1)


def tool(name, args=None):
    return Reply([call(name, args)])


def say(text, suggestions=None):
    return Reply(message=text, suggestions=suggestions or [])


class FakeAdapter:
    """Scripted replies; records which tools each step offered. One instance spans a turn and its resumptions."""
    provider = "Anthropic"

    def __init__(self, script):
        self.script = list(script)
        self.offered = []
        self.models = []

    def step(self, messages, tools):
        self.offered.append(None if tools is None else [t["name"] for t in tools])
        self.messages = copy.deepcopy(messages)
        if not self.script:
            return say("Done.")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item(messages, tools) if callable(item) else item


class FakeExecutor(Executor):
    """Records every executed call with its approval; market_test elicits exactly like the MCP server does."""

    def __init__(self, results=None, jobs=None):
        super().__init__()
        self.results = results or {}
        self.jobs = list(jobs or [])
        self.calls = []          # executed calls: (name, args, answers)
        self.attempts = []       # every call attempt, including elicitations
        self.uploads = {}
        self.audiences = {}

    @property
    def usd_per_call(self):
        return 0.01

    def tool_schemas(self):
        return {name: {"description": f"{name} tool", "parameters": {"type": "object", "properties": {}}} for name in T.MCP_TOOLS}

    def runs(self):
        return copy.deepcopy(RUNS)

    def product_profile(self):
        return None

    def spend_plan(self, name, args):
        if name == "market_test":
            cfg = args.get("config") or {}
            people = cfg.get("auto_personas") or (sum(s["count"] for s in cfg["personas"]["segments"])
                                                  if isinstance(cfg.get("personas"), dict) else 24)
            calls = {"people": people // 5 + people + people // 4}
            if cfg.get("survey"):
                calls["survey"] = people
            calls["report"] = 12
            return T.plan_from(calls, people, 0.01)
        return T.plan_from(T.estimate_calls(name, args, 24), 24, 0.01)

    def personas_of(self, cfg):
        spec = cfg.get("personas")
        return T.pseudo_people(T.normalize_segments(spec["segments"])) if isinstance(spec, dict) else None

    def save_upload(self, session_id, name, text):
        path = f"/fake/uploads/{name}"
        self.uploads[path] = text
        return path

    def save_audience(self, session_id, name, spec):
        path = f"/fake/audiences/{name}.json"
        self.audiences[path] = spec
        return path

    def call(self, name, args, *, answers=None, allowed_urls=None, approval=None):
        self.attempts.append((name, copy.deepcopy(args), answers))
        if name == "market_test" and not answers:
            raise ApprovalNeeded("approve_spend", {
                "mode": "form", "message": "MarketMirror market test 'x' wants to spend.",
                "requestedSchema": {"type": "object", "properties": {"decision": {"type": "string", "oneOf": [
                    {"const": "run", "title": "Run everything now (spends on model calls)"},
                    {"const": "people_first", "title": "Create the people only, so I can review them first"}]}}}})
        self.calls.append((name, copy.deepcopy(args), answers or approval))
        value = self.results.get(name, {"ok": True, "tool": name})
        if isinstance(value, Exception):
            raise value
        return value(args) if callable(value) else copy.deepcopy(value)

    def job_status(self, job_id):
        if self.jobs:
            return self.jobs.pop(0)
        return {"job_id": job_id, "status": "done", "log_tail": ["finished"], "result": {"stage": "done"}}


def run(value, ex, adapter, events=None, **kw):
    from app.services.chat_agent import loop
    sink = events if events is not None else []
    return loop.run_turn(value, lambda e, d: sink.append((e, d)), executor=ex, adapter_factory=lambda mid: adapter,
                         sleep=kw.pop("sleep", lambda s: None), poll_interval=0, job_wait_s=kw.pop("job_wait_s", 60), **kw)


def ask(text, **extra):
    return {"session_id": SESSION, "messages": [{"role": "user", "content": text}], **extra}


def answer(result, reply, **extra):
    return {"session_id": SESSION, "messages": [{"role": "user", "content": "(answer)"}],
            "resume": {"id": result["pending"]["id"], "answer": reply}, **extra}


def reset():
    state.reset()


def executed_spend(ex):
    """Executed calls whose cost class is spend, and whether each was approved."""
    out = []
    for name, args, answers in ex.calls:
        if T.classify(name, args)["cost"] == T.SPEND:
            out.append((name, answers))
    return out
