"""Email campaign testing on simulated buyers: subject lines, senders, send times and multi-step sequences.

Each person gets an inbox for the day: filler mail that someone like them really gets (work, bank, promos,
family; generated once per country/segment and cached) plus the test email(s). An attention gate in code decides
whether the mail is even opened (inbox crowding, sender familiarity, send time against the person's day,
ad avoidance), then one Claude call per noticed mail: skim / read / click / reply / unsubscribe / spam, honest
probabilities, a one-line reason in the person's voice. Sequences run over simulated days with memory of the
earlier steps. Metrics per variant and audience: open, click, click-to-open, unsubscribe, spam, replies;
a subject-line split test; a projection from list size to opens, clicks, leads and revenue (reusing the feed
test's economics); deliverability warnings from a spam-word heuristic.
"""

import random
import re
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..utils.logger import get_logger
from . import emotion
from .feed_test import FEEL_HINT, FEEL_JSON, UsageMeter, _llm_json, behaviour_traits, economics, person_habits

logger = get_logger('mirofish.email_test')

SYSTEM = ("You simulate one specific person reading their email on their phone. Stay in character: their money, their "
          "day, their habits, their language mix. Most marketing mail is ignored or deleted; be honest, not polite. "
          "Return only JSON.")
FILLER_SYSTEM = "You write realistic, varied inbox contents for a market simulation. Return only JSON."

OPEN_BASE = {"morning": 0.28, "midday": 0.22, "evening": 0.32, "night": 0.12}      # base open chance by send time
SPAM_WORDS = ["free money", "act now", "100% free", "guarantee", "winner", "urgent", "limited time", "click here", "no cost",
              "risk-free", "$$$", "!!!", "congratulations", "cash bonus", "double your", "earn extra"]
FALLBACK_FILLER = [
    {"from": "Bank", "subject": "Your statement is ready", "kind": "bank"},
    {"from": "HR", "subject": "Reminder: timesheet due Friday", "kind": "work"},
    {"from": "Shopee", "subject": "Flash sale: up to 70% off today", "kind": "promo"},
    {"from": "Mom", "subject": "Fwd: photos from Sunday", "kind": "family"},
    {"from": "Netflix", "subject": "New this week", "kind": "promo"},
    {"from": "Google", "subject": "Security alert: new sign-in", "kind": "system"},
    {"from": "LinkedIn", "subject": "5 jobs you may be interested in", "kind": "promo"},
    {"from": "Telco", "subject": "Your data pack expires tomorrow", "kind": "system"},
]


# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------

def normalize_emails(spec: Any) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """{"emails": [...], "list_size"?, "benchmarks"?} or a bare list -> (emails, options).
    An email: {id, from_name, subject, preheader?, body, cta?, send_time? (morning|midday|evening|night),
    segments?[], countries?[], sequence?: [{step, delay_days, subject, body, cta?}]}"""
    opts: Dict[str, Any] = {}
    if isinstance(spec, dict):
        emails = spec.get("emails") or spec.get("variants") or []
        opts = {k: v for k, v in spec.items() if k not in ("emails", "variants")}
    else:
        emails = spec or []
    out = []
    for i, e in enumerate(emails):
        if not isinstance(e, dict) or not (e.get("subject") or e.get("body")):
            continue
        send = str(e.get("send_time") or "morning").lower()
        out.append({"id": str(e.get("id") or f"email_{i + 1}"), "from_name": str(e.get("from_name") or e.get("from") or "The brand")[:80],
                    "subject": str(e.get("subject") or "")[:200], "preheader": str(e.get("preheader") or "")[:200],
                    "body": str(e.get("body") or "")[:2500], "cta": str(e.get("cta") or "")[:80],
                    "send_time": send if send in OPEN_BASE else "morning",
                    "segments": [str(x) for x in (e.get("segments") or [])], "countries": [str(x) for x in (e.get("countries") or [])],
                    "sequence": [{"step": int(s.get("step") or k + 2), "delay_days": int(s.get("delay_days") or 2),
                                  "subject": str(s.get("subject") or "")[:200], "body": str(s.get("body") or "")[:2500],
                                  "cta": str(s.get("cta") or e.get("cta") or "")[:80]}
                                 for k, s in enumerate(e.get("sequence") or []) if isinstance(s, dict) and (s.get("subject") or s.get("body"))]})
    if not out:
        raise ValueError("no emails: each needs at least a subject or a body")
    return out, opts


def spam_warnings(email: Dict[str, Any]) -> List[str]:
    text = f"{email.get('subject', '')} {email.get('preheader', '')} {email.get('body', '')}".lower()
    hits = [w for w in SPAM_WORDS if w in text]
    out = [f"spam-trigger phrase: '{w}'" for w in hits]
    subj = email.get("subject") or ""
    if subj.isupper() and len(subj) > 8:
        out.append("subject in all caps")
    if subj.count("!") >= 2:
        out.append("several exclamation marks in the subject")
    if len(subj) > 70:
        out.append(f"subject is {len(subj)} characters; most phones show about 40")
    if re.search(r"https?://\S+", text) and text.count("http") > 4:
        out.append("many links in the body")
    return out


def targets(email: Dict[str, Any], person: Dict[str, Any]) -> bool:
    from .feed_test import segment_matches
    if email.get("segments") and not any(segment_matches(w, person.get("segment") or "") for w in email["segments"]):
        return False
    if email.get("countries"):
        c = str(person.get("country") or "").lower()
        return any(x.lower() in c or c in x.lower() for x in email["countries"]) if c else False
    return True


# --------------------------------------------------------------------------
# Inbox and attention gate (code, no LLM)
# --------------------------------------------------------------------------

def filler_pool(client, model: str, country: str, segment: str, n: int = 8) -> List[Dict[str, Any]]:
    prompt = (f"List {n} emails that a typical person in {country or 'this market'} ({segment or 'general public'}) finds in "
              f"their inbox on an ordinary weekday: work, bank, telecom, shopping promos, family, apps. Realistic sender names "
              f"and subjects in the languages people there get mail in.\nReturn JSON: {{\"emails\": [{{\"from\": \"...\", "
              f"\"subject\": \"...\", \"kind\": \"work|bank|promo|family|system|news\"}}]}}")
    try:
        data = _llm_json(client, model, FILLER_SYSTEM, prompt, temperature=0.9, max_tokens=1200)
        rows = [r for r in ((data.get("emails") if isinstance(data, dict) else data) or []) if isinstance(r, dict) and r.get("subject")]
        if len(rows) >= 4:
            return rows[:12]
    except Exception as e:  # noqa: BLE001
        logger.warning(f"filler inbox for {country}/{segment} failed, using fallback: {e}")
    return list(FALLBACK_FILLER)


def day_phase_fit(send_time: str, person: Dict[str, Any]) -> float:
    """How well the send time fits this person's day (0.6-1.2), from their stated habits when known."""
    habits = str(person.get("platform_habits") or "").lower()
    if send_time == "night" and ("night" in habits or "shift" in str(person.get("occupation") or "").lower()):
        return 1.1
    if send_time == "morning" and ("commute" in habits or "morning" in habits):
        return 1.15
    if send_time == "evening" and ("evening" in habits or "after work" in habits):
        return 1.15
    return 1.0 if send_time in ("morning", "evening") else 0.9


def open_probability(email: Dict[str, Any], person: Dict[str, Any], traits: Dict[str, Any], inbox_size: int,
                     familiarity: float, step: int = 1) -> float:
    """Chance the mail is opened at all, decided in code: base by send time x day fit x crowding x familiarity x ad avoidance."""
    base = OPEN_BASE.get(email.get("send_time") or "morning", 0.25)
    crowd = max(0.55, 1.0 - 0.03 * max(0, inbox_size - 6))
    fam = 0.8 + 0.5 * max(0.0, min(1.0, familiarity))                 # unknown sender 0.8, known brand up to 1.3
    avoid = 1.0 - 0.5 * float(traits.get("ad_avoidance") or 0.5)
    subj = email.get("subject") or ""
    subj_pen = 0.85 if len(subj) > 60 else 1.0
    spam_pen = 0.75 if spam_warnings(email) else 1.0
    fatigue = 0.85 ** max(0, step - 1)                                 # later steps of a sequence open less
    return max(0.02, min(0.9, base * day_phase_fit(email.get("send_time") or "morning", person) * crowd * fam * avoid * subj_pen * spam_pen * fatigue))


# --------------------------------------------------------------------------
# One person reads one mail (LLM)
# --------------------------------------------------------------------------

def read_prompt(person: Dict[str, Any], email: Dict[str, Any], inbox: List[Dict[str, Any]], traits: Dict[str, Any],
                step: int, earlier: List[Dict[str, Any]], product: str = "", feel: bool = False) -> str:
    others = "\n".join(f"- {f.get('from')}: {f.get('subject')}" for f in inbox[:8])
    hist = ""
    if earlier:
        hist = "Earlier mails from the same sender and what you did:\n" + "\n".join(
            f"- day {h['day']}: '{h['subject']}' -> {h['action']}" + (f" ({h['reason']})" if h.get("reason") else "") for h in earlier) + "\n"
    return (
        f"Who you are:\n{person['persona']}\n(Age {person.get('age')}, {person.get('gender')}, {person.get('country')}.)\n"
        f"Your habits (facts): you ignore most ads (ad avoidance {traits['ad_avoidance']} on 0-1); you {traits['clicks_ads']} click promotional mail.\n"
        + (f"What the sender sells: {product}\n" if product else "")
        + (f"{person['history']}" if person.get("history") else "")
        + f"\nIt is {email.get('send_time')} and you open your inbox on your phone. Other mail today:\n{others}\n\n{hist}"
        f"You just opened this one (step {step} of a series):\nFrom: {email['from_name']}\nSubject: {email['subject']}\n"
        + (f"Preview: {email['preheader']}\n" if email.get("preheader") else "")
        + f"\n{email['body']}\n" + (f"[Button: {email['cta']}]\n" if email.get("cta") else "")
        + "\nWhat do you actually do? Options, most common first: skim and close, read, click the button/link, reply, "
          "unsubscribe, mark as spam, forward to someone. Then your honest probabilities (0-1) for a normal day.\n"
          "Return JSON: {\"action\": \"skim|read|click|reply|unsubscribe|spam|forward\", \"seconds\": 4, "
          "\"reason\": \"your inner reaction in under 15 words, your own language mix\", \"reply_text\": \"if you reply, what you write, else empty\", "
          "\"would_buy_now\": \"yes|maybe|no\", \"p_click\": 0.0, \"p_reply\": 0.0, \"p_unsubscribe\": 0.0, \"p_spam\": 0.0, "
          + ("\"what_would_make_you_click\": \"one short sentence\"}" if not feel else
             "\"what_would_make_you_click\": \"one short sentence\", " + FEEL_JSON + "}\nFor \"feel\", say how this email made you feel. "
             + FEEL_HINT)
    )


ACTIONS = ("skim", "read", "click", "reply", "unsubscribe", "spam", "forward")


def normalize_read(d: Dict[str, Any]) -> Dict[str, Any]:
    def num(v, lo=0.0, hi=1.0):
        try:
            return max(lo, min(hi, float(v)))
        except (TypeError, ValueError):
            return lo
    action = str(d.get("action") or "skim").strip().lower()
    if action not in ACTIONS:
        action = "skim"
    wb = str(d.get("would_buy_now") or "no").strip().lower()
    wb = "yes" if wb.startswith("y") else "maybe" if wb.startswith(("m", "p")) else "no"
    out = {"action": action, "seconds": round(num(d.get("seconds"), 0, 600), 1), "reason": str(d.get("reason") or "")[:200],
           "reply_text": str(d.get("reply_text") or "")[:400], "would_buy_now": wb,
           "what_would_make_you_click": str(d.get("what_would_make_you_click") or "")[:200]}
    feel = emotion.normalize_feel(d.get("feel"))
    if feel:
        out["feel"] = feel
    for key, did in (("p_click", action == "click"), ("p_reply", action == "reply"), ("p_unsubscribe", action == "unsubscribe"),
                     ("p_spam", action == "spam")):
        v = d.get(key)
        out[key] = round(num(v), 3) if v is not None else (1.0 if did else 0.0)
    return out


# --------------------------------------------------------------------------
# Run
# --------------------------------------------------------------------------

def assign(emails: List[Dict[str, Any]], people: List[Dict[str, Any]], seed: int) -> Dict[int, str]:
    """Split test: each person gets one eligible email (balanced, seeded)."""
    rng = random.Random(seed)
    plan: Dict[int, str] = {}
    counts: Counter = Counter()
    order = list(people)
    rng.shuffle(order)
    for p in order:
        elig = [e for e in emails if targets(e, p)]
        if not elig:
            continue
        best = min(counts[e["id"]] for e in elig)
        pick = rng.choice([e for e in elig if counts[e["id"]] == best])
        plan[p["agent_id"]] = pick["id"]
        counts[pick["id"]] += 1
    return plan


def run_email_test(client, model: str, emails: List[Dict[str, Any]], people: List[Dict[str, Any]], context: str = "",
                   product: str = "", seed: int = 5, parallel: int = 8, list_size: Optional[int] = None,
                   benchmarks: Optional[Dict[str, Any]] = None, familiarity: float = 0.2,
                   progress: Optional[Callable[[int, int], None]] = None, emotions: Optional[str] = None) -> Dict[str, Any]:
    emo_mode = emotion.mode(emotions)
    want_feel = emo_mode != "off"
    meter = client if isinstance(client, UsageMeter) else UsageMeter(client)
    client = meter
    start = meter.snapshot()
    rng = random.Random(seed)
    plan = assign(emails, people, seed)
    if not plan:
        raise ValueError("no simulated person matches the emails' targeting")
    by_id = {p["agent_id"]: p for p in people}
    by_email = {e["id"]: e for e in emails}
    traits = {aid: person_habits(by_id[aid]) for aid in plan}         # stable per person, not per seed
    emo_w = emotion.weights()
    fx = {aid: emotion.effects(by_id[aid].get("affect_now"), emo_mode, emo_w) for aid in plan}   # 1.0 unless "on"
    keys = sorted({(str(by_id[a].get("country") or ""), str(by_id[a].get("segment") or "")) for a in plan})
    pools: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    lock = threading.Lock()

    def make_pool(key):
        pools[key] = filler_pool(client, model, key[0], key[1])
    with ThreadPoolExecutor(max_workers=max(1, min(parallel, 8))) as pool:
        list(pool.map(make_pool, keys))

    # steps: step 1 = the email itself, then its sequence
    sessions: List[Dict[str, Any]] = []
    history: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    unsubscribed: set = set()
    total_steps = sum(1 + len(by_email[eid].get("sequence") or []) for eid in plan.values())
    done = 0

    def one(aid: int, email: Dict[str, Any], step_mail: Dict[str, Any], step: int, day: int) -> Dict[str, Any]:
        person = by_id[aid]
        tr = traits[aid]
        key = (str(person.get("country") or ""), str(person.get("segment") or ""))
        inbox = pools.get(key) or FALLBACK_FILLER
        inbox_n = len(inbox) + 1
        p_open = open_probability({**email, **step_mail}, person, tr, inbox_n, familiarity, step)
        if fx[aid]["email_open"] != 1.0:
            p_open = max(0.02, min(0.9, p_open * fx[aid]["email_open"]))
        r = random.Random(seed * 104729 + aid * 31 + step)
        rec: Dict[str, Any] = {"agent_id": aid, "name": person.get("name"), "segment": person.get("segment"), "country": person.get("country"),
                               "email_id": email["id"], "step": step, "day": day, "subject": step_mail.get("subject") or email["subject"],
                               "p_open": round(p_open, 3), "inbox_size": inbox_n}
        if fx[aid]["email_open"] != 1.0:
            rec["emotion_effects"] = {"email_open": fx[aid]["email_open"]}
        if aid in unsubscribed:
            rec.update({"opened": False, "action": "unsubscribed_earlier"})
            return rec
        if r.random() > p_open:
            rec.update({"opened": False, "action": "ignored"})
            return rec
        mail = {**email, **{k: v for k, v in step_mail.items() if v}}
        try:
            data = _llm_json(client, model, SYSTEM, read_prompt(person, mail, inbox, tr, step, history[aid], product, feel=want_feel),
                             temperature=0.8, max_tokens=600)
            act = normalize_read(data if isinstance(data, dict) else {})
        except Exception as e:  # noqa: BLE001
            logger.warning(f"email read failed for agent {aid}: {e}")
            act = normalize_read({"action": "skim", "reason": "(no answer)"})
        rec.update({"opened": True, **act})
        return rec

    for step_idx in range(0, 1 + max((len(e.get("sequence") or []) for e in emails), default=0)):
        jobs = []
        day = 0
        for aid, eid in plan.items():
            email = by_email[eid]
            if step_idx == 0:
                jobs.append((aid, email, {}, 1, 0))
            else:
                seq = email.get("sequence") or []
                if step_idx - 1 < len(seq):
                    s_ = seq[step_idx - 1]
                    day = sum(x["delay_days"] for x in seq[:step_idx])
                    jobs.append((aid, email, s_, step_idx + 1, day))
        if not jobs:
            break
        with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
            results = list(pool.map(lambda j: one(*j), jobs))
        for rec in results:
            sessions.append(rec)
            if rec.get("opened"):
                history[rec["agent_id"]].append({"day": rec["day"], "subject": rec["subject"], "action": rec["action"], "reason": rec.get("reason")})
                if rec["action"] in ("unsubscribe", "spam"):
                    unsubscribed.add(rec["agent_id"])
        done += len(jobs)
        if progress:
            progress(done, total_steps)

    summary = summarize(emails, sessions, people, list_size, benchmarks)
    end = meter.snapshot()
    usage = {k: end[k] - start.get(k, 0) for k in end}
    if want_feel:
        from .feed_test import feelings_summary
        feelings = {}
        for e in emails:
            rows = [{"feel": x["feel"], "click": x.get("action") == "click"} for x in sessions
                    if x.get("email_id") == e["id"] and x.get("feel")]
            fs = feelings_summary(rows)
            if fs:
                feelings[e["id"]] = fs
        if feelings:
            summary["feelings"] = feelings
    return {"emails": emails, "plan": {str(k): v for k, v in plan.items()}, "sessions": sessions, "summary": summary,
            "usage": usage, "seed": seed, "list_size": list_size, "benchmarks": benchmarks, "familiarity": familiarity,
            "emotion": emotion.run_info(emo_mode, emo_w, sessions)}


# --------------------------------------------------------------------------
# Aggregate
# --------------------------------------------------------------------------

def _pct(n: float, d: float) -> Optional[float]:
    return round(100.0 * n / d, 1) if d else None


def _variant_stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    sent = len(rows)
    opened = [r for r in rows if r.get("opened")]
    clicks = sum(1 for r in opened if r.get("action") == "click")
    replies = sum(1 for r in opened if r.get("action") == "reply")
    unsub = sum(1 for r in opened if r.get("action") == "unsubscribe")
    spam = sum(1 for r in opened if r.get("action") == "spam")
    p_click = [r["p_click"] for r in opened if r.get("p_click") is not None]
    exp_open = sum(r.get("p_open") or 0 for r in rows)
    exp_click = sum((r.get("p_open") or 0) * (r.get("p_click") or 0) for r in opened) + 0.0
    buy = Counter(r.get("would_buy_now") for r in opened)
    return {"sent": sent, "opened": len(opened), "open_rate": _pct(len(opened), sent), "expected_open_rate": _pct(exp_open, sent),
            "clicks": clicks, "click_rate": _pct(clicks, sent), "click_to_open": _pct(clicks, len(opened)),
            "expected_click_rate": _pct(sum(p_click) * (len(opened) / sent) if sent else 0, len(opened)) if opened else None,
            "replies": replies, "reply_rate": _pct(replies, sent), "unsubscribes": unsub, "unsubscribe_rate": _pct(unsub, sent),
            "spam": spam, "spam_rate": _pct(spam, sent),
            "would_buy_now_yes_pct": _pct(buy.get("yes", 0), len(opened)), "would_buy_now_maybe_pct": _pct(buy.get("maybe", 0), len(opened)),
            "reasons": [r.get("reason") for r in opened if r.get("reason")][:6],
            "reply_samples": [r.get("reply_text") for r in opened if r.get("reply_text")][:3],
            "what_would_make_them_click": [r.get("what_would_make_you_click") for r in opened if r.get("what_would_make_you_click")][:4]}


def summarize(emails: List[Dict[str, Any]], sessions: List[Dict[str, Any]], people: List[Dict[str, Any]],
              list_size: Optional[int], benchmarks: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    per: Dict[str, Any] = {}
    for e in emails:
        rows = [s for s in sessions if s["email_id"] == e["id"]]
        first = [s for s in rows if s["step"] == 1]
        stats = _variant_stats(first)
        stats["warnings"] = spam_warnings(e)
        stats["sequence"] = [{"step": st, **_variant_stats([s for s in rows if s["step"] == st])}
                             for st in sorted({s["step"] for s in rows}) if st > 1]
        stats["by_segment"] = [{"segment": seg, **{k: v for k, v in _variant_stats(rs).items() if k in ("sent", "open_rate", "click_rate", "unsubscribe_rate", "would_buy_now_yes_pct")}}
                               for seg, rs in sorted(_group(first, "segment").items(), key=lambda kv: -len(kv[1]))]
        if list_size:
            opens = list_size * (stats["open_rate"] or 0) / 100
            clicks = list_size * (stats["click_rate"] or 0) / 100
            leads = clicks * ((stats["would_buy_now_yes_pct"] or 0) / 100 + 0.5 * (stats["would_buy_now_maybe_pct"] or 0) / 100)
            proj = {"list_size": list_size, "opens": round(opens), "clicks": round(clicks), "leads": round(leads, 1),
                    "unsubscribes": round(list_size * (stats["unsubscribe_rate"] or 0) / 100)}
            b = benchmarks or {}
            cost = float(b.get("cost_per_send") or 0) * list_size + float(b.get("cost_fixed") or 0)
            if cost or b.get("lead_value") or b.get("deal_value"):
                proj["cost"] = round(cost, 2)
                proj.update({k: v for k, v in economics(cost, leads, b).items() if v is not None})
            stats["projection"] = proj
        per[e["id"]] = stats
    ranked = sorted(per, key=lambda k: (-(per[k]["click_rate"] or 0), -(per[k]["open_rate"] or 0), per[k]["unsubscribe_rate"] or 0))
    unsub_total = sum(1 for s in sessions if s.get("action") in ("unsubscribe", "spam"))
    return {"ranked": ranked, "per_email": per, "people": len({s["agent_id"] for s in sessions}),
            "steps": max((s["step"] for s in sessions), default=0), "lost_to_unsubscribe_or_spam": unsub_total,
            "subject_lines": [{"id": e["id"], "subject": e["subject"], "open_rate": per[e["id"]]["open_rate"], "click_rate": per[e["id"]]["click_rate"]} for e in emails]}


def _group(rows: List[Dict[str, Any]], key: str) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        out[str(r.get(key) or "Everyone")].append(r)
    return out
