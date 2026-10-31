"""How a simulated person feels: stable affect traits, an appraisal per stimulus, a mood that fades back to baseline.

Layered like ALMA (Gebhard 2005): traits (stable) -> emotions (per stimulus) -> mood (pleasure/arousal/dominance,
decaying toward each person's own baseline, as in Kuppens et al.'s DynAffect). The model never invents the numbers on
its own: on calls we already make it adds a short appraisal of what it just saw ("feel": how pleasant, new, relevant,
controllable, fair and urgent it was, plus its own label and a few words). Fixed rules turn that appraisal into one
emotion and an intensity (OCC / Scherer-style checks), and plain arithmetic moves the mood. Everything here is
deterministic given the model's answers, so runs can be compared and audited.

Modes (MM_EMOTIONS, or `emotions` per request): "off" changes nothing anywhere; "observe" (default) records and
reports feelings without letting them steer behaviour; "on" also lets them colour prompts and nudge probabilities.

These are simulated appraisals, not measured human emotion. Reports must say so.

Stdlib only and no package-relative imports: the offline dashboard exporter loads this file by path.
"""

import math
import os
import random
import zlib
from typing import Any, Dict, Iterable, List, Optional

VERSION = "emo-v1"
MODES = ("off", "observe", "on")
DEFAULT_MODE = "observe"
EMO_SALT = 7

EMOTIONS = ("neutral", "interest", "joy", "trust", "surprise", "fomo", "irritation", "anxiety", "sadness",
            "disgust", "regret", "pressured")
POSITIVE = {"interest", "joy", "trust", "surprise", "fomo"}
NEGATIVE = {"irritation", "anxiety", "sadness", "disgust", "regret", "pressured"}

# valence, arousal, dominance per emotion (rough Russell / Mehrabian norms, -1..1)
VAD = {
    "neutral": (0.0, 0.0, 0.0), "interest": (0.5, 0.4, 0.3), "joy": (0.8, 0.5, 0.4), "trust": (0.6, -0.1, 0.3),
    "surprise": (0.4, 0.7, 0.0), "fomo": (0.2, 0.7, -0.2), "irritation": (-0.5, 0.6, 0.3),
    "anxiety": (-0.6, 0.6, -0.4), "sadness": (-0.6, -0.4, -0.3), "disgust": (-0.6, 0.3, 0.3),
    "regret": (-0.4, 0.1, -0.3), "pressured": (-0.4, 0.6, -0.5),
}

MAX_INTENSITY = 0.85      # no feeling is ever maxed out: guards against caricature
MOOD_CAP = 0.8            # |mood| never above this
K_PULL = 0.35             # how far one feeling pulls the mood toward its own valence/arousal/dominance
NEUTRAL_BAND = 0.15       # mood inside this band reads as "nothing much" and adds nothing to prompts
TEST_GAP_H = 24.0         # simulated hours between two different tests, unless the run says otherwise
STEP_HOURS = {            # simulated hours an event takes, when the event does not say
    "saw_ad": 6.0, "stopped_on_ad": 0.0, "clicked_ad": 0.0, "reacted_to_ad": 0.0, "commented_on_ad": 0.0,
    "hid_ad": 0.0, "landed_page": 0.0, "received_email": 24.0, "opened_email": 0.0, "clicked_email": 0.0,
    "answered_survey": 0.0, "heard_pitch": 0.0, "walked_away": 0.0, "posted": 1.0,
}


# ----------------------------------------------------------------------------------------------------------------
# modes and seeds

def mode(value: Any = None, env: Optional[Dict[str, str]] = None) -> str:
    """'off' | 'observe' | 'on' from an explicit value, else MM_EMOTIONS, else the default ('observe')."""
    for v in (value, (env if env is not None else os.environ).get("MM_EMOTIONS")):
        if v is None or v == "":
            continue
        if isinstance(v, bool):
            return "on" if v else "off"
        s = str(v).strip().lower()
        if s in MODES:
            return s
        if s in ("1", "true", "yes"):
            return "on"
        if s in ("0", "false", "no", "none"):
            return "off"
    return DEFAULT_MODE


def identity_seed(name: str, salt: int = 0) -> int:
    """Same as persona_planner.identity_seed (kept here so this file stays importable on its own)."""
    return (zlib.crc32(str(name or "").encode("utf-8")) ^ (salt * 2654435761)) & 0xFFFFFFFF


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _num(v: Any, lo: float, hi: float, default: float = 0.0) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if f != f:  # NaN
        return default
    return round(_clamp(f, lo, hi), 3)


# ----------------------------------------------------------------------------------------------------------------
# traits

def _field(person: Dict[str, Any], *keys: str) -> Any:
    attrs = person.get("attributes") if isinstance(person.get("attributes"), dict) else {}
    for k in keys:
        for src in (person, attrs):
            if src.get(k) not in (None, ""):
                return src.get(k)
    return None


def affect_traits(person: Dict[str, Any]) -> Dict[str, Any]:
    """A person's stable emotional make-up, derived from their decision card and background (no model call).

    base_v/base_a/base_d: the mood they drift back to; reactivity: how strongly events move them; tau_h: how fast a
    mood fades (hours); brand_tau_h: how long liking or irritation toward a brand lasts; neg_weight: extra weight on
    bad news; expressive: how much of what they feel they show in public."""
    if isinstance(person.get("affect_traits"), dict) and person["affect_traits"].get("tau_h"):
        return person["affect_traits"]
    name = str(_field(person, "name", "username") or person.get("agent_id") or "")
    rng = random.Random(identity_seed(name, EMO_SALT))
    bde = _field(person, "bde") or {}
    dp = bde.get("decision_procedure") if isinstance(bde, dict) else {}
    bg = bde.get("background") if isinstance(bde, dict) else {}
    dp = dp if isinstance(dp, dict) else {}
    bg = bg if isinstance(bg, dict) else {}
    base_v, base_a, base_d = 0.08, 0.0, 0.05
    reactivity, tau_h, neg_weight, expressive = 1.0, 24.0, 0.1, 0.8
    payday = str(_field(person, "payday_status") or "").lower()
    if "tight" in payday or "end_of_month" in payday:
        base_v -= 0.10
        base_d -= 0.05
    elif "just_paid" in payday:
        base_v += 0.05
    risk = str(dp.get("risk") or "").lower()
    if "averse" in risk:
        base_d -= 0.10
        neg_weight += 0.10
    elif "seeking" in risk:
        base_d += 0.10
    speed = str(dp.get("speed") or "").lower()
    patience = str(dp.get("patience") or "").lower()
    if "impulsive" in speed or patience.startswith("low") or "impatient" in patience:
        reactivity *= 1.15
        tau_h *= 0.8
    elif "slow" in speed:
        reactivity *= 0.85
    style = str(_field(person, "thinking_style") or "").lower()
    if "sceptic" in style or "skeptic" in style or "risk-averse" in style:
        neg_weight += 0.10
        base_v -= 0.05
    if "early adopter" in style or "novelty" in style:
        reactivity += 0.10
    if "busy" in style or "distracted" in style:
        base_a += 0.10
    for k in ("acquiescence", "social_desirability"):
        if str(bg.get(k) or "").lower().startswith("high"):
            expressive -= 0.12
    # small personal jitter, the same in every test and rerun
    base_v += rng.uniform(-0.08, 0.08)
    base_a += rng.uniform(-0.08, 0.08)
    base_d += rng.uniform(-0.06, 0.06)
    reactivity *= rng.uniform(0.9, 1.1)
    tau_h *= rng.uniform(0.75, 1.5)
    return {
        "base_v": round(_clamp(base_v, -0.3, 0.4), 3), "base_a": round(_clamp(base_a, -0.3, 0.4), 3),
        "base_d": round(_clamp(base_d, -0.3, 0.4), 3), "reactivity": round(_clamp(reactivity, 0.6, 1.4), 3),
        "tau_h": round(_clamp(tau_h, 12.0, 48.0), 1), "brand_tau_h": round(_clamp(tau_h * 7.0, 72.0, 336.0), 1),
        "neg_weight": round(_clamp(neg_weight, 0.0, 0.25), 3), "expressive": round(_clamp(expressive, 0.5, 1.0), 3),
        "source": "derived: decision card, background and identity seed (not measured)",
    }


# ----------------------------------------------------------------------------------------------------------------
# appraisal -> emotion

FEEL_KEYS = {"pleasant": (-1.0, 1.0), "novel": (0.0, 1.0), "relevant": (0.0, 1.0), "control": (0.0, 1.0),
             "fair": (-1.0, 1.0), "urgent": (0.0, 1.0), "intensity": (0.0, 1.0)}
_ALIASES = {"curious": "interest", "curiosity": "interest", "interested": "interest", "happy": "joy", "excited": "joy",
            "delight": "joy", "trusting": "trust", "confident": "trust", "surprised": "surprise", "urgency": "fomo",
            "fear of missing out": "fomo", "annoyed": "irritation", "annoyance": "irritation", "anger": "irritation",
            "angry": "irritation", "frustration": "irritation", "frustrated": "irritation", "worry": "anxiety",
            "worried": "anxiety", "fear": "anxiety", "afraid": "anxiety", "nervous": "anxiety", "sad": "sadness",
            "disgusted": "disgust", "contempt": "disgust", "regretful": "regret", "pressure": "pressured",
            "pushed": "pressured", "manipulated": "pressured", "calm": "neutral", "indifferent": "neutral",
            "bored": "neutral", "none": "neutral", "nothing": "neutral"}


def normalize_feel(raw: Any) -> Optional[Dict[str, Any]]:
    """Clamp and clean the model's 'feel' object; None when it carries nothing usable."""
    if not isinstance(raw, dict):
        return None
    out: Dict[str, Any] = {}
    for k, (lo, hi) in FEEL_KEYS.items():
        if raw.get(k) is not None:
            out[k] = _num(raw.get(k), lo, hi)
    label = str(raw.get("emotion") or "").strip().lower()
    label = _ALIASES.get(label, label)
    if label in EMOTIONS:
        out["emotion"] = label
    words = " ".join(str(raw.get("words") or "").split())[:60]
    if words:
        out["words"] = words
    if not any(k in out for k in ("pleasant", "relevant", "emotion")):
        return None
    return out


def _family(e: str) -> str:
    return "positive" if e in POSITIVE else "negative" if e in NEGATIVE else "neutral"


def _rule_label(f: Dict[str, Any]) -> str:
    p, r, n = f.get("pleasant", 0.0), f.get("relevant", 0.0), f.get("novel", 0.0)
    c, fa, u = f.get("control", 0.5), f.get("fair", 0.0), f.get("urgent", 0.0)
    if r < 0.25 and abs(p) < 0.3:
        return "neutral"                                    # relevance gate: most things just don't matter
    if fa < -0.4 and p < 0:
        return "pressured" if u > 0.5 else "disgust" if c >= 0.5 else "irritation"
    if p < -0.25:
        if c >= 0.4:
            return "irritation"
        return "anxiety" if (n > 0.4 or u > 0.5) else "sadness"
    if abs(p) <= 0.25:
        return "regret" if (r > 0.6 and c < 0.5) else "neutral"
    if u > 0.6 and fa >= 0:
        return "fomo"
    if n > 0.6:
        return "surprise"
    if fa > 0.4 and r > 0.5:
        return "trust"
    return "joy" if r >= 0.6 else "interest"


def appraise(feel: Optional[Dict[str, Any]], traits: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """One emotion and an intensity from an appraisal. The fixed rules decide; the model's own label is accepted
    only when it agrees in direction (positive / negative / neutral), else it is overridden and flagged."""
    traits = traits or {}
    f = feel or {}
    if not f:
        return {"emotion": "neutral", "intensity": 0.0, "vad": VAD["neutral"], "by": "none", "mismatch": False}
    rule = _rule_label(f)
    has_numbers = any(k in f for k in ("pleasant", "relevant"))
    own = f.get("emotion")
    mismatch = False
    if own and has_numbers:
        if _family(own) == _family(rule):
            label, by = own, "self_report"
        else:
            label, by, mismatch = rule, "rules", True
    elif own:
        label, by = own, "self_report"
    else:
        label, by = rule, "rules"
    p = float(f.get("pleasant", VAD[label][0]))
    if p < 0:
        p *= 1.0 + float(traits.get("neg_weight", 0.1))
    raw = 0.5 * abs(p) + 0.3 * float(f.get("relevant", 0.5)) + 0.2 * float(f.get("novel", 0.0))
    if not has_numbers and f.get("intensity") is not None:
        raw = float(f["intensity"])
    intensity = 0.0 if label == "neutral" else min(MAX_INTENSITY, float(traits.get("reactivity", 1.0)) * raw)
    return {"emotion": label, "intensity": round(intensity, 3), "vad": VAD[label], "by": by, "mismatch": mismatch}


# ----------------------------------------------------------------------------------------------------------------
# mood

def new_affect(traits: Optional[Dict[str, Any]] = None, now_h: float = 0.0) -> Dict[str, Any]:
    t = traits or {}
    return {"v": float(t.get("base_v", 0.0)), "a": float(t.get("base_a", 0.0)), "d": float(t.get("base_d", 0.0)),
            "brand_v": 0.0, "t_h": float(now_h), "last": None}


def current(affect: Optional[Dict[str, Any]], traits: Optional[Dict[str, Any]] = None,
            now_h: Optional[float] = None) -> Dict[str, Any]:
    """The mood as it stands at now_h: each dimension has faded toward the person's baseline since the last event."""
    traits = traits or {}
    a = dict(affect or new_affect(traits))
    t0 = float(a.get("t_h") or 0.0)
    now = t0 if now_h is None else max(t0, float(now_h))
    dt = now - t0
    if dt > 0:
        k = math.exp(-dt / max(1.0, float(traits.get("tau_h", 24.0))))
        kb = math.exp(-dt / max(1.0, float(traits.get("brand_tau_h", 168.0))))
        for dim, base in (("v", "base_v"), ("a", "base_a"), ("d", "base_d")):
            b = float(traits.get(base, 0.0))
            a[dim] = b + (float(a.get(dim, b)) - b) * k
        a["brand_v"] = float(a.get("brand_v", 0.0)) * kb
    a["t_h"] = now
    for dim in ("v", "a", "d", "brand_v"):
        a[dim] = round(_clamp(float(a.get(dim, 0.0)), -MOOD_CAP, MOOD_CAP), 4)
    return a


def update(affect: Optional[Dict[str, Any]], appraisal: Dict[str, Any], traits: Optional[Dict[str, Any]] = None,
           now_h: float = 0.0, brand_directed: bool = True, words: str = "", test: str = "", source: str = "") -> Dict[str, Any]:
    """Fade to now_h, then let the new feeling pull the mood toward its own coordinates (capped)."""
    a = current(affect, traits, now_h)
    i = float(appraisal.get("intensity", 0.0))
    emo = str(appraisal.get("emotion") or "neutral")
    if i > 0 and emo != "neutral":
        tv, ta, td = appraisal.get("vad") or VAD.get(emo, VAD["neutral"])
        for dim, target in (("v", tv), ("a", ta), ("d", td)):
            a[dim] = round(_clamp(a[dim] + K_PULL * i * (target - a[dim]), -MOOD_CAP, MOOD_CAP), 4)
        if brand_directed:
            sign = 1.0 if tv > 0 else -1.0 if tv < 0 else 0.0
            a["brand_v"] = round(_clamp(a["brand_v"] + 0.25 * i * sign, -MOOD_CAP, MOOD_CAP), 4)
    a["last"] = {"emotion": emo, "intensity": round(i, 3), "words": str(words or "")[:60], "test": str(test or ""),
                 "source": str(source or "")[:80], "t_h": a["t_h"], "by": appraisal.get("by", "rules")}
    return a


_OCTANTS = {(1, 1, 1): "eager", (1, 1, -1): "excited but unsure", (1, -1, 1): "relaxed", (1, -1, -1): "content",
            (-1, 1, 1): "annoyed", (-1, 1, -1): "on edge", (-1, -1, 1): "unimpressed", (-1, -1, -1): "flat"}


def mood_word(affect: Optional[Dict[str, Any]]) -> str:
    """Plain words for the mood ('a little annoyed'); '' when it is close to nothing much."""
    if not affect:
        return ""
    v, a, d = float(affect.get("v", 0)), float(affect.get("a", 0)), float(affect.get("d", 0))
    if abs(v) < NEUTRAL_BAND and abs(a) < NEUTRAL_BAND:
        return ""
    word = _OCTANTS[(1 if v >= 0 else -1, 1 if a >= 0 else -1, 1 if d >= 0 else -1)]
    strength = max(abs(v), abs(a))
    return ("quite " if strength >= 0.45 else "a little ") + word


def prompt_line(affect: Optional[Dict[str, Any]], traits: Optional[Dict[str, Any]] = None,
                now_h: Optional[float] = None, brand: str = "") -> str:
    """At most two mild lines on how the person feels now; '' when there is nothing worth saying."""
    if not affect:
        return ""
    cur = current(affect, traits, now_h)
    word = mood_word(cur)
    last = cur.get("last") or {}
    recent = ""
    tau = float((traits or {}).get("tau_h", 24.0))
    if last and last.get("emotion") not in (None, "neutral") and float(last.get("intensity", 0)) >= 0.3 \
            and cur["t_h"] - float(last.get("t_h") or 0) <= 3 * tau and last.get("words"):
        about = f" about {brand}" if brand else ""
        recent = f'Earlier you felt "{last["words"]}"{about}.'
    if not word and not recent:
        return ""
    head = f"How you feel right now: {word}." if word else ""
    tail = "Let it colour your reaction only as much as it would for a real person; feelings usually fade into the background."
    return " ".join(x for x in (head, recent) if x) + "\n" + tail


def snapshot(state: Optional[Dict[str, Any]], traits: Optional[Dict[str, Any]] = None,
             now_h: Optional[float] = None) -> Dict[str, Any]:
    """A read-only view of how someone feels now, for prompts, couplings and the dashboard."""
    aff = (state or {}).get("affect") if isinstance(state, dict) else None
    if not aff:
        return {}
    cur = current(aff, traits, now_h)
    last = cur.get("last") or {}
    return {"v": cur["v"], "a": cur["a"], "d": cur["d"], "brand_v": cur["brand_v"], "mood": mood_word(cur),
            "last_emotion": last.get("emotion"), "last_intensity": last.get("intensity"), "last_words": last.get("words")}


def sam9(v: float) -> float:
    """-1..1 onto the 1-9 Self-Assessment Manikin scale people answer in studies."""
    return round(1.0 + 4.0 * (float(v) + 1.0), 2)


# ----------------------------------------------------------------------------------------------------------------
# summaries for reports

def _stats(xs: List[float]) -> Dict[str, Any]:
    if not xs:
        return {}
    s = sorted(xs)
    m = sum(s) / len(s)
    sd = math.sqrt(sum((x - m) ** 2 for x in s) / len(s)) if len(s) > 1 else 0.0

    def q(p: float) -> float:
        return s[min(len(s) - 1, max(0, int(round(p * (len(s) - 1)))))]
    return {"mean": round(m, 3), "sd": round(sd, 3), "p10": round(q(0.1), 3), "p90": round(q(0.9), 3),
            "sam9_mean": sam9(m), "sam9_p10": sam9(q(0.1)), "sam9_p90": sam9(q(0.9))}


def quality_flags(feelings: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Warnings for the known ways simulated feelings go wrong (too uniform, too positive, caricatured)."""
    fs = [f for f in feelings if f]
    n = len(fs)
    if not n:
        return {"n": 0}
    emos = [f.get("emotion") or "neutral" for f in fs]
    neutral_share = sum(1 for e in emos if e == "neutral") / n
    non_neutral = [e for e in emos if e != "neutral"]
    pos_share = (sum(1 for e in non_neutral if e in POSITIVE) / len(non_neutral)) if non_neutral else 0.0
    pleasant = [float(f["pleasant"]) for f in fs if f.get("pleasant") is not None]
    sd_p = _stats(pleasant).get("sd", 0.0) if len(pleasant) > 1 else None
    inten = [float(f.get("intensity", 0)) for f in fs if (f.get("emotion") or "neutral") != "neutral"]
    mean_i = sum(inten) / len(inten) if inten else 0.0
    return {"n": n, "neutral_share": round(neutral_share, 3), "positive_share_of_feelings": round(pos_share, 3),
            "uniform": bool(sd_p is not None and n >= 10 and sd_p < 0.15),
            "positive_skew": bool(len(non_neutral) >= 10 and pos_share > 0.7),
            "caricature": bool(n >= 10 and (neutral_share < 0.25 or mean_i > 0.6))}


def summarize(data: Dict[str, Any], scope: str = "default") -> Dict[str, Any]:
    """Population view of simulated feelings from a behavior_state document."""
    agents = ((data or {}).get("scopes") or {}).get(scope or "default") or {}
    if not isinstance(agents, dict) or not agents:
        return {"people": 0}
    feelings, by_test, mismatches, n_judged = [], {}, 0, 0
    valence, arousal, with_feel = [], [], 0
    steps: Dict[int, List[float]] = {}
    for a in agents.values():
        if not isinstance(a, dict):
            continue
        mems = [m for m in a.get("memory") or [] if isinstance(m, dict) and isinstance(m.get("feel"), dict)]
        if mems:
            with_feel += 1
        for m in mems:
            f = m["feel"]
            feelings.append(f)
            t = m.get("test") or "other"
            row = by_test.setdefault(t, {"n": 0, "emotions": {}})
            row["n"] += 1
            e = f.get("emotion") or "neutral"
            row["emotions"][e] = row["emotions"].get(e, 0) + 1
            if f.get("by") in ("rules", "self_report"):
                n_judged += 1
                mismatches += 1 if f.get("mismatch") else 0
        st = a.get("state") if isinstance(a.get("state"), dict) else {}
        aff = st.get("affect")
        if isinstance(aff, dict):
            valence.append(float(aff.get("v", 0)))
            arousal.append(float(aff.get("a", 0)))
        for i, pt in enumerate(a.get("trajectory") or []):
            if isinstance(pt, dict) and pt.get("valence") is not None:
                steps.setdefault(i + 1, []).append(float(pt["valence"]))
    counts: Dict[str, int] = {}
    for f in feelings:
        e = f.get("emotion") or "neutral"
        counts[e] = counts.get(e, 0) + 1
    total = sum(counts.values()) or 1
    for row in by_test.values():
        row["emotions"] = {k: round(v / row["n"], 3) for k, v in sorted(row["emotions"].items(), key=lambda kv: -kv[1])}
    return {
        "people": len(agents), "with_feelings": with_feel, "feelings": len(feelings),
        "emotions": {k: round(v / total, 3) for k, v in sorted(counts.items(), key=lambda kv: -kv[1])},
        "valence": _stats(valence), "arousal": _stats(arousal), "by_test": by_test,
        "trajectory": [{"step": k, "avg_valence": round(sum(v) / len(v), 3)} for k, v in sorted(steps.items())[:15]],
        "mismatch_rate": round(mismatches / n_judged, 3) if n_judged else None,
        "flags": quality_flags(feelings), "version": VERSION,
        "basis": "simulated appraisal: model self-report mapped to emotions by fixed rules",
        "validated": False,
        "note": "Simulated feelings, not measured emotion. Use them to choose what to test with real people.",
    }
