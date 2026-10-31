"""Feelings travel through the tests: feed (ad + landing page), email, pitch walk-away, the report's fact sheet."""

import json
import re
from types import SimpleNamespace

from app.services import email_test as et
from app.services import feed_test as ft
from app.services import market_report as mr
from app.services import pitch

import importlib.util as _ilu
import os as _os

_spec = _ilu.spec_from_file_location("_feed_fakes", _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "test_feed_test.py"))
_fakes = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_fakes)
CREATIVES, FakeLLM, people = _fakes.CREATIVES, _fakes.FakeLLM, _fakes.people


class FeelLLM(FakeLLM):
    """The feed FakeLLM, plus a 'feel' on the sponsored item and on the landing page when the prompt asks for one."""

    def create(self, **kw):
        resp = super().create(**kw)
        system, user = kw["messages"][0]["content"], kw["messages"][1]["content"]
        if '"feel"' not in user:
            return resp
        body = json.loads(resp.choices[0].message.content)
        if system == ft.SYSTEM_PROMPT:
            ad_line = next(l for l in user.splitlines() if "· Sponsored" in l or "· Promoted" in l)
            ad_id = re.match(r"\[(i\d+)\]", ad_line).group(1)
            for it in body["items"]:
                if it["id"] == ad_id:
                    neg = it.get("hide")
                    it["feel"] = {"emotion": "irritation" if neg else "interest", "pleasant": -0.6 if neg else 0.4,
                                  "relevant": 0.7, "control": 0.7, "fair": -0.2 if neg else 0.3, "words": "spam again" if neg else "looks handy"}
        elif system == ft.LANDING_SYSTEM:
            body["feel"] = {"emotion": "anxiety", "pleasant": -0.5, "relevant": 0.8, "control": 0.2, "urgent": 0.6,
                            "words": "why my phone"}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(body)), finish_reason="stop")])


def _run(mode, gate=True):
    cs = ft.normalize_creatives(CREATIVES)
    landing = ft.normalize_landing({"load_seconds": 1.0, "language": "English", "form_fields": ["name", "phone"]})
    return ft.run_feed_test(FeelLLM(), "m", cs, people(12), waves=2, landing=landing, parallel=4, exposures=2,
                            attention_gate=gate, seed=9, emotions=mode)


def test_feed_test_records_feelings_and_keeps_attention_draws_identical():
    off, obs = _run("off"), _run("observe")
    key = lambda r: sorted((s["agent_id"], s["creative_id"], s["exposure"], s["ad"]["noticed"]) for s in r["sessions"])
    assert key(off) == key(obs)                          # same random draws: modes are comparable
    assert not any(s["ad"].get("feel") for s in off["sessions"])
    noticed = [s for s in obs["sessions"] if s["ad"]["noticed"]]
    assert noticed and all(s["ad"].get("feel") for s in noticed)
    assert not any(s["ad"].get("feel") for s in obs["sessions"] if not s["ad"]["noticed"])
    rd = obs["summary"]["per_creative"]["rd1"]["feelings"]
    assert rd is None or rd["emotions"].get("irritation")
    assert obs["emotion"]["mode"] == "observe" and obs["realism"]["emotions"] == "observe"
    landed = [s for s in obs["sessions"] if (s.get("landing") or {}).get("feel")]
    assert all(s["landing"]["feel"]["emotion"] == "anxiety" for s in landed)


def test_pitch_walk_away_and_resistance():
    def batch(items):
        out = {}
        for it in items:
            if "Same conversation" in it["prompt"]:
                out[it["agent_id"]] = json.dumps({"reply": "still no", "verdict": "no", "moved": "no",
                                                  "feel": {"emotion": "pressured", "pleasant": -0.6, "fair": -0.6, "urgent": 0.7, "relevant": 0.8}})
            else:
                walk = it["agent_id"] % 2 == 0
                out[it["agent_id"]] = json.dumps({"reply": "not now", "verdict": "no" if walk else "maybe",
                                                  "objection_type": "price", "objection": "too pricey", "walk_away": walk,
                                                  "feel": {"emotion": "irritation", "pleasant": -0.4, "relevant": 0.6, "control": 0.7}})
        return out
    ppl = [{"agent_id": i, "name": f"P{i}", "segment": "S"} for i in range(6)]
    on = pitch.run(batch, ppl, "Buy now", {"price": "It pays for itself"}, emotions="on")
    obs = pitch.run(batch, ppl, "Buy now", {"price": "It pays for itself"}, emotions="observe")
    assert on["resistance"]["walk_away_pct"] == 50.0 and on["resistance"]["resistance_pct"] == 50.0
    heard_on = sum(1 for r in on["people"] if r["turn2"])
    heard_obs = sum(1 for r in obs["people"] if r["turn2"])
    assert heard_on == 3 and heard_obs == 6              # 'on' does not argue with people who walked away
    assert on["feelings"]["after_pitch"]["emotions"].get("irritation") and on["backfire_pct"] == 100.0
    assert on["emotion"]["mode"] == "on"
    off = pitch.run(batch, ppl, "Buy now", {}, emotions="off")
    assert "walk_away" not in pitch.pitch_prompt("Buy now")
    plain = pitch.resistance_and_feelings([{"turn1": {"verdict": "no"}}, {"turn1": {"verdict": "maybe"}}])
    assert "resistance" not in plain                     # never asked about walking away: no resistance claim


def test_email_reads_carry_feelings():
    d = et.normalize_read({"action": "read", "feel": {"emotion": "trust", "pleasant": 0.5, "relevant": 0.7, "fair": 0.6}})
    assert d["feel"]["emotion"] == "trust"
    assert "feel" not in et.normalize_read({"action": "read"})


def test_report_fact_sheet_and_number_guard_for_feelings():
    bundle = {"summary": {"marketing": {}}, "config": {}, "feed_test": {"creatives": [{"id": "a1"}],
              "summary": {"ranked": ["a1"], "per_creative": {"a1": {"feelings": {"n": 10, "neutral_share": 0.5,
                          "emotions": {"neutral": 0.5, "irritation": 0.3, "interest": 0.2}, "words": ["pushy"]}}}}},
              "pitch": {"answered": 4, "resistance": {"resistance_pct": 10.0, "low_resistance_flag": True, "no_pct": 10.0}},
              "emotion_summary": {"feelings": 10, "with_feelings": 8, "emotions": {"neutral": 0.5, "irritation": 0.3},
                                  "valence": {"sam9_mean": 4.6, "sam9_p10": 3.8, "sam9_p90": 5.4}, "flags": {"positive_skew": False}}}
    m = mr.compact_material(bundle)
    e = m["emotions"]
    assert e["per_ad"][0]["top_feelings_pct"]["irritation"] == 30.0 and e["pitch_resistance"]["low_resistance_flag"] is True
    assert "not measured" in e["basis"]
    fb = mr.fallback_sections(m)["emotional_response"]
    assert "irritation 30.0%" in fb["summary"] and "pushed back" in fb["watch_out"]
    allowed = mr._fact_numbers(m)
    assert "Customers felt 87% excited." not in mr._check_numbers("Customers felt 87% excited.", allowed)
    md = mr.render_markdown(mr.fallback_sections(m), m)
    assert "How people felt (simulated)" in md and "not measured emotion" in md
