"""Sign in with ChatGPT Responses adapter: completed stream, usage, and failures."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "gateway"))
import local_gateway as gw


class Response:
    def __init__(self, events, status=200):
        self.events = events
        self.status_code = status
        self.ok = status == 200
        self.encoding = "utf-8"

    def iter_lines(self, decode_unicode=False):
        return iter("data: " + json.dumps(event) for event in self.events)

    def close(self):
        pass


def test_siwc_completed_stream_uses_provider_usage(monkeypatch):
    monkeypatch.setattr(gw.siwc_auth, "status", lambda: {"model": "gpt-test", "registered": True,
                        "eligible_scope": True, "needs_login": False})
    monkeypatch.setattr(gw.siwc_auth, "access_token", lambda: ("fake-token", "gpt-test"))
    seen = {}

    def post(url, json, headers, stream, timeout):
        seen.update({"url": url, "body": json, "headers": headers})
        return Response([{"type": "response.output_text.delta", "delta": "hello"},
                         {"type": "response.completed", "response": {"usage": {"input_tokens": 10,
                          "output_tokens": 2, "total_tokens": 12}}}])

    monkeypatch.setattr(gw.requests, "post", post)
    g = gw.Gateway(gw.SignInBackend(), workers=1)
    result = g.complete({"messages": [{"role": "user", "content": "hi"}]})
    assert result["choices"][0]["message"]["content"] == "hello"
    assert result["usage"]["total_tokens"] == 12 and result["usage_source"] == "provider"
    assert seen["url"] == "https://api.openai.com/v1/responses"
    assert seen["body"]["store"] is False and seen["body"]["stream"] is True


def test_siwc_rate_limit_and_incomplete_stream(monkeypatch):
    monkeypatch.setattr(gw.siwc_auth, "status", lambda: {"model": "gpt-test"})
    monkeypatch.setattr(gw.siwc_auth, "access_token", lambda: ("fake-token", "gpt-test"))
    backend = gw.SignInBackend()
    monkeypatch.setattr(gw.requests, "post", lambda *a, **k: Response([], 429))
    with pytest.raises(gw.GatewayError) as exc:
        backend.complete("", "hi")
    assert exc.value.status == 429 and exc.value.kind == "rate_limit"
    monkeypatch.setattr(gw.requests, "post", lambda *a, **k: Response([{"type": "response.output_text.delta", "delta": "x"}]))
    with pytest.raises(gw.GatewayError) as exc:
        backend.complete("", "hi")
    assert exc.value.kind == "incomplete"
