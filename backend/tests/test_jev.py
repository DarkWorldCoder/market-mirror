"""Jev client, SSR engine selection, VoC Jev classifier and the survey objection check, with faked HTTP only."""

import io
import json
import os
import sys
from contextlib import redirect_stdout

import numpy as np
import pytest

from app.services import jev, search_and_geo as sg, ssr
from app.services.gtm_suite import wilson

KEY = "test-key-not-real"
DIRECT = {"TYPESAFE_API_KEY": KEY}
VIA_OR = {"OPENROUTER_API_KEY": KEY, "JEV_VIA": "openrouter"}


class Resp:
    def __init__(self, status=200, body=None, headers=None, text=""):
        self.status_code, self._body, self.headers, self.text = status, body, headers or {}, text

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


class FakeHTTP:
    """Records every POST; `reply(url, body)` returns a Resp (or a list of Resps consumed in order)."""

    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def __call__(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        r = self.reply(url, json)
        return r.pop(0) if isinstance(r, list) else r


def answered(questions, model="jev-1.14", usage=None, **per_type):
    """A 200 response answering every question by its type."""
    ans = {}
    for qid, q in questions.items():
        if q["type"] == "score":
            n = len(q["criteria"])
            probs = per_type.get("score") or {str(k): (1.0 if k == n - 1 else 0.0) for k in range(n)}
            ans[qid] = {"type": "score", "score": n - 1, "confidence": 0.9, "probabilities": probs,
                        "legend": {str(k): c for k, c in enumerate(q["criteria"])}}
        elif q["type"] == "choice":
            label = per_type.get("choice") or next(iter(q["criteria"]))
            ans[qid] = {"type": "choice", "choice": label, "confidence": 0.8,
                        "probabilities": {k: (0.8 if k == label else 0.2 / (len(q["criteria"]) - 1)) for k in q["criteria"]}}
        else:
            ans[qid] = {"type": "noul", "noul": 0.7}
    return Resp(200, {"model": model, "answers": ans, "usage": usage or {"input_tokens": 50, "output_tokens": 3}})


@pytest.fixture(autouse=True)
def _no_real_jev(monkeypatch, tmp_path):
    """No key from the machine, no .env, no real HTTP, no real sleeping."""
    for k in jev.ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(jev, "env_file_path", lambda: str(tmp_path / "missing.env"))

    def refuse(*a, **kw):
        raise AssertionError("real HTTP attempted")
    monkeypatch.setattr(jev.requests, "post", refuse)
    monkeypatch.setattr(jev, "_sleep", lambda s: None)
    ssr._anchor_cache.clear()
    yield
    ssr._anchor_cache.clear()


def fake(monkeypatch, reply):
    http = FakeHTTP(reply)
    monkeypatch.setattr(jev.requests, "post", http)
    return http


# --------------------------------------------------------------------------
# client
# --------------------------------------------------------------------------

def test_request_shape_for_each_question_type(monkeypatch):
    http = fake(monkeypatch, lambda url, body: answered(body["questions"]))
    qs = {"pick": jev.choice_question({"price": "Cost", "none": "No concern"}, "Pick one."),
          "rate": jev.score_question(["bad", "ok", "good"], "Rate it."),
          "yes": jev.noul_question("Is it positive?")}
    res = jev.ask("Too pricey for me.", qs, env=DIRECT)
    body = http.calls[0]["json"]
    assert body == {"state": "Too pricey for me.", "model": "jev-latest", "questions": {
        "pick": {"type": "choice", "criteria": {"price": "Cost", "none": "No concern"}, "instructions": "Pick one."},
        "rate": {"type": "score", "criteria": ["bad", "ok", "good"], "instructions": "Rate it."},
        "yes": {"type": "noul", "instructions": "Is it positive?"}}}
    assert res["model"] == "jev-1.14" and set(res["answers"]) == {"pick", "rate", "yes"}
    assert res["usage"] == {"input_tokens": 50, "output_tokens": 3}


def test_direct_and_openrouter_routes(monkeypatch):
    http = fake(monkeypatch, lambda url, body: answered(body["questions"], usage={"input_tokens": 9, "output_tokens": 0, "cost": 0.0004}))
    q = {"q": jev.noul_question("Yes?")}
    jev.ask("text", q, env=DIRECT)
    usage = jev.JevUsage()
    jev.ask("text", q, env=VIA_OR, usage=usage)
    jev.ask("text", q, env={**DIRECT, "JEV_BASE_URL": "https://proxy.example/v1", "JEV_MODEL": "jev-1.13"})
    d, o, custom = http.calls
    assert d["url"] == jev.TYPESAFE_URL and d["json"]["model"] == "jev-latest" and d["json"]["state"] == "text"
    assert d["headers"]["Authorization"] == f"Bearer {KEY}"
    assert o["url"] == jev.OPENROUTER_URL and o["json"]["model"] == "~typesafe/jev-latest"
    assert o["json"]["state"] == ["text"]                     # OpenRouter's documented state is a list of items
    assert custom["url"] == "https://proxy.example/v1/systemone" and custom["json"]["model"] == "jev-1.13"
    snap = usage.snapshot()
    assert snap["ok"] == 1 and snap["cost_usd"] == 0.0004 and snap["input_tokens"] == 9


def test_routing_settings_never_contain_the_key():
    assert jev.settings({})["configured"] is False
    only_or = jev.settings({"OPENROUTER_API_KEY": KEY})
    assert only_or["configured"] is False and "JEV_VIA=openrouter" in only_or["reason"]
    cfg = jev.settings(VIA_OR)
    assert cfg["configured"] and cfg["route"] == "openrouter" and cfg["key_env"] == "OPENROUTER_API_KEY"
    assert KEY not in json.dumps(cfg) and KEY not in json.dumps(jev.settings(DIRECT))
    assert jev.settings({"TYPESAFE_API_KEY": KEY, "JEV_VIA": "somewhere"})["configured"] is False
    with pytest.raises(jev.JevUnavailable):
        jev.ask("x", {"q": jev.noul_question("?")}, env={})


def test_429_is_retried_after_retry_after(monkeypatch):
    waits = []
    monkeypatch.setattr(jev, "_sleep", waits.append)
    seq = [Resp(429, {"detail": "slow down"}, {"Retry-After": "7"}), Resp(503, None, text="busy")]
    http = fake(monkeypatch, lambda url, body: seq.pop(0) if seq else answered(body["questions"]))
    res = jev.ask("x", {"q": jev.noul_question("?")}, env=DIRECT)
    assert res["answers"]["q"]["noul"] == 0.7 and len(http.calls) == 3
    assert waits == [7.0, 2.0]                                # Retry-After honoured, then exponential backoff


def test_client_errors_are_not_retried_and_never_show_the_key(monkeypatch):
    usage = jev.JevUsage()
    http = fake(monkeypatch, lambda url, body: Resp(422, {"detail": [{"loc": ["body", "questions"], "msg": "field required", "type": "missing"}]}))
    with pytest.raises(jev.JevError) as e:
        jev.ask("x", {"q": jev.noul_question("?")}, env=DIRECT, usage=usage)
    assert len(http.calls) == 1 and "422" in str(e.value) and "body.questions: field required" in str(e.value)
    assert KEY not in str(e.value) and usage.snapshot()["failed"] == 1
    fake(monkeypatch, lambda url, body: Resp(500, {"error": {"message": "boom"}}))
    with pytest.raises(jev.JevError) as e:
        jev.ask("x", {"q": jev.noul_question("?")}, env={**DIRECT, "JEV_RETRIES": "1"})
    assert "after 2 attempts" in str(e.value)


def test_missing_answer_is_a_failure(monkeypatch):
    fake(monkeypatch, lambda url, body: Resp(200, {"model": "jev-1.14", "answers": {}, "usage": {}}))
    out = jev.ask_many([("x", {"q": jev.noul_question("?")})], env=DIRECT)
    assert out == [{"ok": False, "model": None, "answers": None, "error": "Jev returned no answer for q"}]


def test_score_probabilities_map_to_a_1_to_5_distribution():
    assert jev.score_pmf({"probabilities": {"0": 0.1, "1": 0.2, "2": 0.4, "3": 0.2, "4": 0.1}}, 5) == pytest.approx([0.1, 0.2, 0.4, 0.2, 0.1])
    assert jev.score_pmf({"probabilities": {"0": 2, "4": 2}}, 5) == pytest.approx([0.5, 0, 0, 0, 0.5])   # missing levels are 0
    assert jev.score_pmf({"probabilities": {"0": 0, "1": 0}}, 5) is None
    assert jev.score_pmf({"probabilities": {"0": -1}}, 5) is None and jev.score_pmf({}, 5) is None
    assert jev.choice_label({"choice": "price"}, ["price"]) == "price" and jev.choice_label({"choice": "x"}, ["price"]) is None


# --------------------------------------------------------------------------
# SSR engines
# --------------------------------------------------------------------------

class TinyEmbedder:
    model_name = "fake-emb"

    def embed(self, texts, *, query=False):
        out = []
        for t in texts:
            v = np.zeros(32, dtype=np.float32)
            for w in t.lower().split():
                v[hash(w) % 32] += 1
            out.append(v / (np.linalg.norm(v) or 1))
        return out


PROBS = {"0": 0.05, "1": 0.05, "2": 0.1, "3": 0.3, "4": 0.5}


def test_rate_jev_sends_one_score_question_per_answer_with_the_anchor_levels(monkeypatch):
    http = fake(monkeypatch, lambda url, body: answered(body["questions"], score=PROBS))
    rated, info = ssr.rate_jev([("purchase", "Probably yes: looks handy."), ("trust", ""), ("bogus", "x")], env=DIRECT)
    assert len(http.calls) == 1                                   # empty text and unknown scales are not sent
    q = http.calls[0]["json"]["questions"]["rating"]
    assert q["type"] == "score" and len(q["criteria"]) == 5
    assert http.calls[0]["json"]["state"] == "Probably yes: looks handy."     # the whole answer
    for k in range(5):
        for anchor_set in ssr.ANCHORS["purchase"]:
            assert anchor_set[k] in q["criteria"][k]            # level k carries every anchor for rating k+1
    assert rated[0]["pmf"] == pytest.approx([0.05, 0.05, 0.1, 0.3, 0.5])
    assert rated[0]["mean"] == pytest.approx(1 * .05 + 2 * .05 + 3 * .1 + 4 * .3 + 5 * .5)
    assert rated[1] is None and rated[2] is None
    assert info["model"] == "jev-1.14" and info["rated"] == 1 and info["failed"] == 0


def test_jev_failures_are_counted_not_substituted(monkeypatch):
    fake(monkeypatch, lambda url, body: Resp(400, {"detail": "bad"}) if "fail" in body["state"] else answered(body["questions"], score=PROBS))
    monkeypatch.setattr(ssr, "get_embedder", lambda: TinyEmbedder())
    items = [("purchase", "yes please"), ("purchase", "fail this one")]
    rated, engines, info = ssr.rate_engine(items, engine="jev", env=DIRECT)
    assert rated[1] is None and engines == ["jev", None]
    assert info["engine"] == "jev" and info["method"] == "jev (jev-1.14)" and info["input"] == "full answer"
    assert info["counts"] == {"jev": 1, "failed": 1} and info["usage"]["failed"] == 1


def test_auto_falls_back_to_embeddings_per_answer_and_records_it(monkeypatch):
    fake(monkeypatch, lambda url, body: Resp(400, {"detail": "bad"}) if "fail" in body["state"] else answered(body["questions"], score=PROBS))
    monkeypatch.setattr(ssr, "get_embedder", lambda: TinyEmbedder())
    rated, engines, info = ssr.rate_engine([("purchase", "yes please"), ("interest", "fail this one")], engine="auto", env=DIRECT)
    assert engines == ["jev", "embeddings"] and all(rated)
    assert info["counts"] == {"jev": 1, "embeddings": 1, "failed": 0, "jev_failed": 1}
    assert info["method"] == "auto: jev (jev-1.14) for 1, embeddings (fake-emb) for 1"
    # auto without a key: embeddings for everything, and the reason is recorded
    rated, engines, info = ssr.rate_engine([("purchase", "yes please")], engine="auto", env={})
    assert engines == ["embeddings"] and "TYPESAFE_API_KEY" in info["jev_unavailable"]


def test_engine_selection_defaults_to_embeddings(monkeypatch):
    monkeypatch.setattr(ssr, "get_embedder", lambda: TinyEmbedder())
    assert ssr.engine_name(None, env={}) == "embeddings"
    assert ssr.engine_name(None, env={"SSR_ENGINE": "jev"}) == "jev"
    assert ssr.engine_name("auto", env={"SSR_ENGINE": "jev"}) == "auto"
    with pytest.raises(ValueError):
        ssr.engine_name("magic", env={})
    rated, engines, info = ssr.rate_engine([("purchase", "I would definitely do it")], env={})
    assert info["engine"] == "embeddings" and info["method"] == "embeddings (fake-emb)" and engines == ["embeddings"]
    with pytest.raises(jev.JevUnavailable):
        ssr.rate_engine([("purchase", "yes")], engine="jev", env={})


def test_ssr_route_with_engine_jev(monkeypatch):
    from app import create_app
    app = create_app()
    app.config.update(TESTING=True)
    c = app.test_client()
    r = c.post("/api/simulation/ssr", json={"engine": "jev", "items": [{"id": "0:purchase", "scale": "purchase", "text": "yes"}]})
    assert r.status_code == 503 and "not configured" in r.get_json()["error"]
    monkeypatch.setenv("TYPESAFE_API_KEY", KEY)
    fake(monkeypatch, lambda url, body: answered(body["questions"], score=PROBS))
    r = c.post("/api/simulation/ssr", json={"engine": "jev", "items": [{"id": "0:purchase", "scale": "purchase", "text": "yes"}]})
    data = r.get_json()["data"]
    assert r.status_code == 200 and data["engine"] == "jev" and data["method"] == "jev (jev-1.14)"
    assert data["results"][0]["id"] == "0:purchase" and "engine" not in data["results"][0]
    assert c.post("/api/simulation/ssr", json={"engine": "magic", "items": []}).status_code == 400


# --------------------------------------------------------------------------
# concern classification and the survey objection check
# --------------------------------------------------------------------------

def test_voc_jev_classifier_labels_both_sides_with_one_question(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", KEY)

    def reply(url, body):
        s = body["state"]
        return answered(body["questions"], choice="none" if "love" in s else "trust" if "card" in s.lower() else "price")
    http = fake(monkeypatch, reply)
    run_data = {"research": {"quotes": [{"text": "I love it, the routines are short."},
                                        {"text": "It wants my card first, which I hate."}]},
                "survey": {"responses": [{"agent_id": 1, "answer": {"main_objection": "Card upfront scares me.", "objection_type": "trust"}},
                                         {"agent_id": 2, "answer": {"main_objection": "The price is steep.", "objection_type": "price"}}]}}
    res = sg.run_voc_grounding(None, "", run_data=run_data, classifier="jev")      # no chat model needed
    s = res["summary"]
    states = [c["json"]["state"] for c in http.calls]
    assert len(http.calls) == 4 and "Card upfront scares me." in states and "I love it, the routines are short." in states
    qs = {json.dumps(c["json"]["questions"], sort_keys=True) for c in http.calls}
    assert len(qs) == 1                                              # the same question for real and simulated text
    crit = http.calls[0]["json"]["questions"]["label"]["criteria"]
    assert set(crit) == set(sg.CONCERN_TYPES) | {"none"}
    assert s["classifier"] == "jev" and s["classifier_model"] == "jev (jev-1.14)" and s["classifier_usage"]["ok"] == 4
    rows = {c["concern"]: c for c in s["comparison"]}
    assert rows["none"]["real"]["k"] == 1 and rows["trust"]["real"]["k"] == 1 and rows["trust"]["simulated"]["k"] == 1
    assert s["real"]["classified"] == 2 and s["simulated"]["classified"] == 2 and s["phrases"] == []
    assert res["unit"] == "texts classified by the Jev decision model" and "Jev" in s["method"]


def test_voc_jev_needs_a_key_and_a_known_classifier():
    with pytest.raises(jev.JevUnavailable):
        sg.run_voc_grounding(None, "", raw_reviews=["Too expensive for what it is."], classifier="jev")
    with pytest.raises(ValueError):
        sg.run_voc_grounding(None, "", raw_reviews=["x" * 30], classifier="magic")


def test_objection_check_agreement_has_a_wilson_range(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", KEY)

    def reply(url, body):
        s = body["state"]
        if "broken" in s:
            return Resp(500, None, text="down")
        return answered(body["questions"], choice="trust" if "scam" in s else "price")
    fake(monkeypatch, reply)
    criteria = {"price": "Cost", "trust": "Scam worry", "none": "No objection", "other": "Other"}
    items = [{"id": "0", "text": "Costs too much.", "self_tag": "price"},
             {"id": "1", "text": "Looks like a scam.", "self_tag": "trust"},
             {"id": "2", "text": "Pricey.", "self_tag": "price"},
             {"id": "3", "text": "Feels like a scam to me.", "self_tag": "price"},
             {"id": "4", "text": "broken request", "self_tag": "price"},
             {"id": "5", "text": "", "self_tag": "none"}]
    res = sg.run_objection_check(items, criteria)
    assert res["asked"] == 5 and res["labelled"] == 4 and res["failed"] == 1        # empty text is not asked
    assert res["agreement"] == wilson(3, 4) and res["agreement"]["lo"] < 75 < res["agreement"]["hi"]
    assert res["disagreements"] == [{"id": "3", "text": "Feels like a scam to me.", "self_tag": "price", "jev": "trust"}]
    assert res["method"] == "jev (jev-1.14)" and res["usage"]["failed"] == 1


def test_objection_check_route_and_dashboard_line(monkeypatch):
    from app import create_app
    app = create_app()
    app.config.update(TESTING=True)
    c = app.test_client()
    body = {"items": [{"id": "0", "text": "Costs too much.", "self_tag": "price"}]}
    assert c.post("/api/simulation/objection-check", json=body).status_code == 503
    monkeypatch.setenv("TYPESAFE_API_KEY", KEY)
    http = fake(monkeypatch, lambda url, b: answered(b["questions"], choice="price"))
    r = c.post("/api/simulation/objection-check", json=body)
    data = r.get_json()["data"]
    assert r.status_code == 200 and data["agreement"]["pct"] == 100.0
    from claude_cli import marketing as mk
    assert set(http.calls[0]["json"]["questions"]["label"]["criteria"]) == set(mk.OBJECTION_TYPES)


def _bundle(objection_check=None, ssr_info=None):
    from claude_cli import marketing as mk
    people = [{"agent_id": i, "name": f"P{i}", "kind": "persona", "segment": "S"} for i in range(2)]
    responses = []
    for i in range(2):
        ans = mk.parse_answer(json.dumps({"purchase_text": "Maybe: if it is free.", "interest": 6, "trust": 5,
                                          "would_click": "yes", "would_convert": "maybe", "recommend": 5,
                                          "main_objection": "Not sure it is really free.", "objection_type": "price"}))
        ans["ssr"] = {"purchase": {"pmf": [0.1, 0.2, 0.4, 0.2, 0.1], "mean": 3.0, "sd": 1.1, "score10": 5.0}}
        responses.append({"agent_id": i, "name": f"P{i}", "answer": ans})
    survey = {"responses": responses, "ssr": ssr_info or {"used": True, "model": "fake-emb"}}
    if objection_check:
        survey["objection_check"] = objection_check
    return {"config": {"persona_index": people}, "survey": survey}


def test_dashboard_shows_the_objection_check_and_the_ssr_engine():
    from claude_cli import marketing as mk
    check = {"available": True, "model": "jev-1.14", "failed": 1, "agreement": wilson(3, 4)}
    secs = dict((k, h) for k, _, h in mk.render_sections(mk.analyze(_bundle(check))))
    assert "gave the same objection type as the person" in secs["objections"]
    assert "75% of 4 answers (95% range" in secs["objections"] and "1 not labelled" in secs["objections"]
    assert "Embedding model: fake-emb." in secs["ratings"]
    plain = mk.analyze(_bundle())
    assert plain["objection_check"] is None
    assert "Jev" not in dict((k, h) for k, _, h in mk.render_sections(plain))["objections"]
    jev_run = mk.analyze(_bundle(ssr_info={"used": True, "engine": "jev", "method": "jev (jev-1.14)", "model": "jev-1.14",
                                           "counts": {"jev": 2, "failed": 1}}))
    ratings = dict((k, h) for k, _, h in mk.render_sections(jev_run))["ratings"]
    assert "Rated by jev (jev-1.14). 1 answers could not be rated" in ratings and "Embedding model" not in ratings
    assert mk.summary_block(mk.analyze(_bundle(check)))["objection_check"]["agreement"]["n"] == 4


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def test_cli_jev_check_without_a_key_makes_no_call(monkeypatch):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "claude_cli"))
    import mirofish
    real_load = mirofish._load_jev

    def load():
        mod = real_load()
        monkeypatch.setattr(mod, "env_file_path", jev.env_file_path)
        monkeypatch.setattr(mod.requests, "post", jev.requests.post)        # the refusing stub
        return mod
    monkeypatch.setattr(mirofish, "_load_jev", load)
    buf = io.StringIO()
    with redirect_stdout(buf):
        assert mirofish.main(["jev", "check"]) == 0
    out = json.loads(buf.getvalue())
    assert out["configured"] is False and out["route"] == "typesafe" and "TYPESAFE_API_KEY is not set" in out["key"]
    assert "ping" not in out
    buf = io.StringIO()
    with redirect_stdout(buf):
        assert mirofish.main(["jev", "--ping"]) == 1                       # nothing to ping without a key
    monkeypatch.setenv("TYPESAFE_API_KEY", KEY)
    buf = io.StringIO()
    with redirect_stdout(buf):
        assert mirofish.main(["jev", "--check"]) == 0
    out = json.loads(buf.getvalue())
    assert out["configured"] is True and out["key"] == "TYPESAFE_API_KEY is set" and KEY not in buf.getvalue()


def test_cli_survey_passes_the_engine_and_stores_the_objection_check(tmp_path):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "claude_cli"))
    import mirofish
    sent = {}

    class Stub:
        def data(self, method, path, json=None, params=None, timeout=None):
            if path.endswith("/config"):
                return {"persona_index": [{"agent_id": i, "name": f"P{i}", "kind": "persona", "segment": "S"} for i in range(3)]}
            if path.endswith("/profiles"):
                return {"profiles": []}
            if path == "/api/simulation/interview/batch":
                reply = {"purchase_text": "Maybe: if free.", "would_convert": "maybe", "interest": 5,
                         "main_objection": "Not sure it is free.", "objection_type": "price"}
                return {"result": {"results": [{"agent_id": it["agent_id"], "response": mirofish.json.dumps(reply)}
                                               for it in json["interviews"]]}}
            if path == "/api/simulation/ssr":
                sent["ssr"] = json
                res = [{"id": it["id"], "scale": it["scale"], "pmf": [0, 0, 1, 0, 0], "mean": 3.0, "sd": 0.0, "score10": 5.0}
                       for it in json["items"][:2]]
                return {"engine": "jev", "method": "jev (jev-1.14)", "model": "jev-1.14", "counts": {"jev": 2, "failed": 1},
                        "usage": {"requests": 3, "ok": 2, "failed": 1, "input_tokens": 90, "output_tokens": 0,
                                  "cost_usd": None, "models": {"jev-1.14": 2}, "errors": []}, "results": res}
            if path == "/api/simulation/objection-check":
                sent["check"] = json
                return {"engine": "jev", "model": "jev-1.14", "labelled": 3, "failed": 0, "agreement": wilson(3, 3)}
            return {}

    mirofish.step_survey(Stub(), "sim_x", str(tmp_path), "offer", "sign up", [], ssr_engine="jev", objection_check=True)
    survey = json.load(open(tmp_path / "survey.json"))
    assert sent["ssr"]["engine"] == "jev" and len(sent["check"]["items"]) == 3
    assert sent["check"]["items"][0] == {"id": "0", "text": "Not sure it is free.", "self_tag": "price"}
    info = survey["ssr"]
    assert info["engine"] == "jev" and info["method"] == "jev (jev-1.14)" and info["counts"] == {"jev": 2, "failed": 1}
    assert info["usage"]["failed"] == 1 and info["mapped"] == 2
    assert survey["objection_check"]["agreement"]["pct"] == 100.0
