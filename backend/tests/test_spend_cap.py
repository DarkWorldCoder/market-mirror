"""The hard dollar cap: prices, the run ledger, the stop before a call, retries, the API and the dashboard row."""

import os
import sys
from types import SimpleNamespace

import pytest

from app.utils import openai_chat_compat, retry, spend_cap


@pytest.fixture(autouse=True)
def ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("MM_SPEND_FILE", str(tmp_path / "spend_cap.json"))
    monkeypatch.delenv("MM_MAX_SPEND_USD", raising=False)
    monkeypatch.delenv("MM_USD_PER_MTOK", raising=False)
    monkeypatch.setitem(spend_cap._PROCESS, "spent_usd", 0.0)
    monkeypatch.setitem(spend_cap._PROCESS, "calls", 0)
    return tmp_path / "spend_cap.json"


class FakeClient:
    def __init__(self):
        self.sent = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.sent += 1
        return SimpleNamespace(model=kw.get("model"), choices=[], usage=SimpleNamespace(
            prompt_tokens=100_000, completion_tokens=10_000, prompt_tokens_details=SimpleNamespace(cached_tokens=40_000)))


def test_prices_and_cache_discount(monkeypatch):
    assert spend_cap.price_for("claude-haiku-4-5")[0] == (1.0, 5.0)
    assert spend_cap.price_for("claude-opus-4-1")[0] == (15.0, 75.0)
    assert spend_cap.price_for("something-new")[1].startswith("default")
    assert spend_cap.cost_usd("claude-haiku-4-5", 1_000_000, 0) == pytest.approx(1.0)
    assert spend_cap.cost_usd("claude-haiku-4-5", 1_000_000, 0, cache_read=1_000_000) == pytest.approx(0.1)
    monkeypatch.setenv("MM_USD_PER_MTOK", "2,4")
    assert spend_cap.cost_usd("claude-haiku-4-5", 1_000_000, 1_000_000) == pytest.approx(6.0)


def test_no_cap_means_no_ledger_and_no_stop(ledger):
    client = FakeClient()
    for _ in range(3):
        openai_chat_compat.create_chat_completion(client, model="claude-haiku-4-5", messages=[{"role": "user", "content": "hi"}])
    assert client.sent == 3 and not ledger.exists() and spend_cap.status() is None


def test_run_cap_stops_new_calls_and_records_spend():
    spend_cap.arm(0.1, "run-a")
    client = FakeClient()
    msgs = [{"role": "user", "content": "hi"}]
    openai_chat_compat.create_chat_completion(client, model="claude-haiku-4-5", messages=msgs)
    st = spend_cap.status()
    # 60k plain input at $1 + 40k cached at $0.10 + 10k output at $5 per million = $0.114
    assert st["calls"] == 1 and st["spent_usd"] == pytest.approx(0.114) and st["reached"]
    with pytest.raises(spend_cap.SpendCapReached, match="max_spend_usd"):
        openai_chat_compat.create_chat_completion(client, model="claude-haiku-4-5", messages=msgs)
    assert client.sent == 1                       # nothing was sent once the cap was reached
    final = spend_cap.disarm()
    assert final["label"] == "run-a" and spend_cap.status() is None
    openai_chat_compat.create_chat_completion(client, model="claude-haiku-4-5", messages=msgs)
    assert client.sent == 2


def test_bad_limits_are_refused():
    for bad in (0, -1, "abc", None):
        with pytest.raises(ValueError):
            spend_cap.arm(bad)


def test_stale_cap_lapses(monkeypatch):
    spend_cap.arm(0.01)
    spend_cap.charge_tokens("claude-haiku-4-5", 1_000_000, 0)
    with pytest.raises(spend_cap.SpendCapReached):
        spend_cap.check()
    monkeypatch.setattr(spend_cap, "TTL_S", 0)
    spend_cap.check()                               # a cap left by a killed run no longer blocks
    assert spend_cap.status() is None


def test_process_cap(monkeypatch):
    monkeypatch.setenv("MM_MAX_SPEND_USD", "0.5")
    spend_cap.charge_tokens("claude-haiku-4-5", 400_000, 0)
    spend_cap.check()
    spend_cap.charge_tokens("claude-haiku-4-5", 200_000, 0)
    with pytest.raises(spend_cap.SpendCapReached, match="MM_MAX_SPEND_USD"):
        spend_cap.check()


def test_retry_does_not_retry_a_reached_cap():
    calls = []

    @retry.retry_with_backoff(max_retries=3, initial_delay=0)
    def call():
        calls.append(1)
        raise spend_cap.SpendCapReached("cap")
    with pytest.raises(spend_cap.SpendCapReached):
        call()
    assert len(calls) == 1


def test_api_arms_reads_and_lifts_the_cap():
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    headers = {}
    token = os.environ.get("MM_API_AUTH_TOKEN") or os.environ.get("API_AUTH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    c = app.test_client()
    assert c.post("/api/simulation/spend-cap", json={"max_spend_usd": "x"}, headers=headers).status_code == 400
    assert c.post("/api/simulation/spend-cap", json={"max_spend_usd": 2, "label": "r"}, headers=headers).get_json()["data"]["limit_usd"] == 2
    assert c.get("/api/simulation/spend-cap", headers=headers).get_json()["data"]["label"] == "r"
    assert c.delete("/api/simulation/spend-cap", headers=headers).get_json()["data"]["label"] == "r"
    assert c.get("/api/simulation/spend-cap", headers=headers).get_json()["data"] is None


def test_dashboard_row():
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "claude_cli"))
    import exporter
    assert exporter.spend_cap_row({}) == ""
    row = exporter.spend_cap_row({"spend_cap": {"limit_usd": 5, "spent_usd": 5.2, "calls": 300, "reached": True}})
    assert "$5.20 of $5.00" in row and "300 model calls" in row and "reached" in row
