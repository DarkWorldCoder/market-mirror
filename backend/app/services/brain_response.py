"""Predicted brain response for each ad, from Meta's TRIBE v2 research model running in the owner's own sidecar.

Opt-in and off by default: nothing happens unless ``MM_BRAIN_RESPONSE_URL`` points at a running
``backend/brain_sidecar/tribe_server.py`` (local GPU, free Colab T4 through a tunnel, or a private Hugging Face
Space). ``MM_BRAIN_RESPONSE_TOKEN`` is the sidecar's bearer token (optional for a local sidecar without one);
``MM_BRAIN_RESPONSE_HF_TOKEN`` is only for a private Space or protected Inference Endpoint, whose ``Authorization``
header must carry a Hugging Face token (the sidecar token then goes in ``X-MM-Tribe-Token``).

What it is: for a video, an audio clip or a caption, TRIBE v2 predicts an *average* viewer's cortical activity
about once per second. The sidecar returns only a compact summary (per-second, clip-z-scored mean response of
visual, hearing and language areas and the whole cortex, with peak seconds). It is not attention, feelings,
memory or buying, and it is not validated for ads. This module never feeds it into persona prompts and changes no
simulated number; it stores the summary next to the feed test and adds one plain line per ad.

Results are cached by content hash in the run folder's ``brain_response.json``. Every failure (no URL, sidecar
down, timeout, file too large, image-only ad) is recorded as skipped with a reason; nothing here ever stops a run.

Stdlib only, so the CLI can load this file without the Flask app.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

FILE = "brain_response.json"
LABEL = ("Predicted for an average viewer by Meta's TRIBE v2 research model (noncommercial license). It predicts brain "
         "activity, not attention, feelings, memory or buying. Not validated for ads.")
LICENSE = "CC BY-NC 4.0 (noncommercial)"
MODEL = "facebook/tribev2"
VIDEO_EXT = (".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v")
AUDIO_EXT = (".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac")
GROUP_ORDER = ("visual", "hearing", "language", "cortex")
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ---------------------------------------------------------------------------
# settings
# ---------------------------------------------------------------------------

def _dotenv(path: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                out[k.strip()] = v.split(" #", 1)[0].strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def settings(env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """URL, tokens and timeouts from the environment, then the repo's .env or MIROFISH_ENV_FILE (the CLI does not
    load it itself)."""
    if env is None:
        file_env = _dotenv(os.environ.get("MIROFISH_ENV_FILE") or os.path.join(REPO_ROOT, ".env"))
        env = {**file_env, **{k: v for k, v in os.environ.items() if k.startswith("MM_BRAIN_RESPONSE")}}

    def num(key: str, default: float) -> float:
        try:
            return float(env.get(key) or default)
        except ValueError:
            return default

    return {"url": str(env.get("MM_BRAIN_RESPONSE_URL") or "").strip().rstrip("/"),
            "token": str(env.get("MM_BRAIN_RESPONSE_TOKEN") or "").strip(),
            "hf_token": str(env.get("MM_BRAIN_RESPONSE_HF_TOKEN") or "").strip(),
            "timeout": num("MM_BRAIN_RESPONSE_TIMEOUT", 900.0),        # total seconds per ad, polling included
            "request_timeout": num("MM_BRAIN_RESPONSE_REQUEST_TIMEOUT", 90.0),
            "max_mb": num("MM_BRAIN_RESPONSE_MAX_MB", 100.0),
            "poll": num("MM_BRAIN_RESPONSE_POLL", 5.0)}


def enabled(cfg: Optional[Dict[str, Any]] = None) -> bool:
    cfg = cfg if cfg is not None else settings()
    return bool(cfg.get("url"))


def _headers(cfg: Dict[str, Any]) -> Dict[str, str]:
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if cfg.get("hf_token"):
        h["Authorization"] = "Bearer " + cfg["hf_token"]
        if cfg.get("token"):
            h["X-MM-Tribe-Token"] = cfg["token"]
    elif cfg.get("token"):
        h["Authorization"] = "Bearer " + cfg["token"]
        h["X-MM-Tribe-Token"] = cfg["token"]
    return h


class SidecarError(RuntimeError):
    pass


def _call(cfg: Dict[str, Any], method: str, path: str, body: Optional[Dict[str, Any]] = None,
          timeout: Optional[float] = None) -> Dict[str, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(cfg["url"] + path, data=data, method=method, headers=_headers(cfg))
    try:
        with urllib.request.urlopen(req, timeout=timeout or cfg["request_timeout"]) as resp:
            payload = json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8")).get("error") or ""
        except Exception:  # noqa: BLE001 - a proxy page instead of JSON
            msg = ""
        if e.code == 401:
            msg = "the sidecar refused the token (check MM_BRAIN_RESPONSE_TOKEN)"
        raise SidecarError(f"sidecar answered {e.code}" + (f": {msg}" if msg else ""))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise SidecarError(f"sidecar not reachable at {cfg['url']} ({type(reason).__name__}: {str(reason)[:120]})")
    except json.JSONDecodeError:
        raise SidecarError("sidecar answered with something that is not JSON")
    if not isinstance(payload, dict):
        raise SidecarError("sidecar answered with something that is not a JSON object")
    return payload


def health(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = cfg if cfg is not None else settings()
    if not enabled(cfg):
        return {"ok": False, "enabled": False, "reason": "MM_BRAIN_RESPONSE_URL is not set"}
    try:
        return {"enabled": True, **_call(cfg, "GET", "/health", timeout=min(15.0, cfg["request_timeout"]))}
    except SidecarError as e:
        return {"ok": False, "enabled": True, "reason": str(e)}


# ---------------------------------------------------------------------------
# what to send for one creative
# ---------------------------------------------------------------------------

def caption_text(creative: Dict[str, Any]) -> str:
    parts = [str(creative.get(k) or "").strip() for k in ("headline", "text", "primary_text", "body", "cta")]
    return "\n".join(p for p in parts if p)


def _has_image(creative: Dict[str, Any]) -> bool:
    if creative.get("image") or creative.get("frames") or creative.get("visual") or creative.get("media_brief"):
        return True
    fmt = str(creative.get("format") or "").lower()
    return fmt in ("image", "carousel", "photo", "static") and bool(str(creative.get("media") or "").strip())


def _local(path: str, base_dir: Optional[str]) -> str:
    if os.path.isabs(path) or not base_dir:
        return path
    return os.path.join(base_dir, path)


def plan(creative: Dict[str, Any], base_dir: Optional[str] = None) -> Tuple[str, Optional[str], Optional[str]]:
    """(kind, source, skip_reason): video, then audio, then caption text; an ad with a picture and no video or audio
    is skipped, since TRIBE v2 has no image input and the caption alone is not what the viewer sees."""
    for kind, key, exts in (("video", "video", VIDEO_EXT), ("audio", "audio", AUDIO_EXT)):
        src = creative.get(key)
        if isinstance(src, str) and src.strip():
            src = src.strip()
            if src.startswith(("http://", "https://", "data:")):
                return kind, None, (f"the {kind} is a web address or inline data; download it and give a local file path "
                                    "(only local files are sent to your sidecar)")
            path = _local(src, base_dir)
            if not os.path.isfile(path):
                return kind, None, f"no {kind} file at {src}"
            if not path.lower().endswith(exts):
                return kind, None, f"{os.path.basename(path)} is not a {kind} type TRIBE reads ({', '.join(exts)})"
            return kind, path, None
    if _has_image(creative):
        return "image", None, "TRIBE v2 has no image input; give a video or audio version to get a prediction"
    text = caption_text(creative)
    if not text:
        return "text", None, "no video, audio or caption text"
    return "text", text, None


def content_hash(kind: str, payload: bytes) -> str:
    return hashlib.sha256(kind.encode() + b"\0" + payload).hexdigest()


# ---------------------------------------------------------------------------
# plain line and timing check
# ---------------------------------------------------------------------------

def clock(seconds: Any) -> str:
    s = max(0, int(round(float(seconds or 0))))
    return f"{s // 60}:{s % 60:02d}"


def _top_peak(summary: Dict[str, Any]) -> Optional[Tuple[str, Dict[str, Any]]]:
    best = None
    for key in ("visual", "hearing", "language"):
        g = (summary.get("groups") or {}).get(key) or {}
        for p in g.get("peaks") or []:
            if best is None or (p.get("z") or 0) > (best[1].get("z") or 0):
                best = (g.get("label") or key, p)
    return best


def plain_line(summary: Dict[str, Any]) -> str:
    head = "Predicted brain response for an average viewer (TRIBE v2, research model)"
    top = _top_peak(summary or {})
    if not top:
        return head + ": no clear peak in this clip."
    label, p = top
    span = clock(p["start"]) if clock(p["start"]) == clock(p["end"]) else f"{clock(p['start'])}-{clock(p['end'])}"
    return f"{head}: {label} peak at {span}."


_TIME_PATTERNS = [
    (re.compile(r"\b(\d{1,2}):([0-5]\d)\b"), lambda m: int(m.group(1)) * 60 + int(m.group(2))),
    (re.compile(r"\b(\d{1,3})\s*(?:s|sec|secs|second|seconds)\b", re.I), lambda m: int(m.group(1))),
    (re.compile(r"\b(?:at the|in the|from the)\s+(?:very\s+)?(?:start|beginning|opening|first (?:few )?seconds?)\b", re.I),
     lambda m: 0),
    (re.compile(r"\b(?:at the|in the|by the)\s+(?:very\s+)?end(?:ing)?\b", re.I), lambda m: -1),
]


def time_refs(text: str) -> List[int]:
    """Seconds a reaction refers to (-1 = 'at the end'), in the order found."""
    out: List[int] = []
    for pattern, value in _TIME_PATTERNS:
        out.extend(value(m) for m in pattern.finditer(text or ""))
    return out


def timing_check(feed_test: Optional[Dict[str, Any]], rows: List[Dict[str, Any]], tolerance: float = 2.0) -> Dict[str, Any]:
    """Observational: do the simulated people's feed reactions that name a moment in the ad fall near a predicted peak?
    Neither side is a measurement; agreement says only that they point at the same moment."""
    per = ((feed_test or {}).get("summary") or {}).get("per_creative") or {}
    by_id = {r.get("id"): r for r in rows if r.get("status") == "ok"}
    checked, near, refs_seen, details = 0, 0, 0, []
    for cid, row in by_id.items():
        m = per.get(cid) or {}
        texts = [t.get("text") for t in (m.get("thoughts") or []) if isinstance(t, dict)]
        texts += [t.get("text") for t in (m.get("comments_list") or []) if isinstance(t, dict)]
        summary = row.get("summary") or {}
        duration = float(summary.get("duration_s") or 0)
        peaks = [p for g in (summary.get("groups") or {}).values() for p in (g.get("peaks") or [])]
        for text in texts:
            for sec in time_refs(str(text or "")):
                refs_seen += 1
                at = max(0.0, duration - 3) if sec < 0 else float(sec)
                hit = any(p["start"] - tolerance <= at <= p["end"] + tolerance for p in peaks)
                checked += 1
                near += int(hit)
                if len(details) < 20:
                    details.append({"creative": cid, "text": str(text)[:160], "second": at, "near_peak": hit})
    if not by_id:
        return {"status": "no_predictions", "note": "No ad has a prediction yet, so there is nothing to compare."}
    if not refs_seen:
        return {"status": "needs_timestamps",
                "note": ("The simulated feed reactions name no moment in the ads, so they cannot be lined up with the "
                         "predicted peaks. This check needs reactions tied to video timestamps.")}
    return {"status": "ok", "references": checked, "near_peak": near, "share_near_peak": round(near / checked, 3),
            "tolerance_s": tolerance, "examples": details,
            "note": ("Observational: how many reactions that name a moment fall within "
                     f"{tolerance:g} s of a predicted peak. Both sides are model outputs; this is not validation.")}


# ---------------------------------------------------------------------------
# prediction
# ---------------------------------------------------------------------------

def _request_body(kind: str, source: str) -> Tuple[Dict[str, Any], bytes]:
    if kind == "text":
        raw = source.encode("utf-8")
        return {"kind": "text", "text": source}, raw
    with open(source, "rb") as f:
        raw = f.read()
    return {"kind": kind, "filename": os.path.basename(source), "data_b64": base64.b64encode(raw).decode("ascii")}, raw


def _predict_remote(cfg: Dict[str, Any], body: Dict[str, Any]) -> Dict[str, Any]:
    started = time.monotonic()
    first = _call(cfg, "POST", "/predict", {**body, "async": True})
    if isinstance(first.get("summary"), dict):           # a sidecar that answers at once
        return first["summary"]
    job = first.get("job")
    if not job:
        raise SidecarError(first.get("error") or "the sidecar gave no job id")
    while True:
        if time.monotonic() - started > cfg["timeout"]:
            raise SidecarError(f"no prediction after {int(cfg['timeout'])} s (MM_BRAIN_RESPONSE_TIMEOUT)")
        time.sleep(max(0.05, cfg["poll"]))
        state = _call(cfg, "GET", f"/jobs/{job}")
        if state.get("status") == "done" and isinstance(state.get("summary"), dict):
            return state["summary"]
        if state.get("status") == "failed":
            raise SidecarError("the sidecar could not predict: " + str(state.get("error") or "unknown error"))


def _check_summary(summary: Dict[str, Any]) -> Dict[str, Any]:
    groups = summary.get("groups")
    if not isinstance(groups, dict) or not groups or not isinstance(summary.get("seconds"), list):
        raise SidecarError("the sidecar summary has no groups or seconds")
    n = len(summary["seconds"])
    for key, g in groups.items():
        if not isinstance(g, dict) or len(g.get("z") or []) != n:
            raise SidecarError(f"the sidecar summary for {key} does not match its seconds")
    summary.setdefault("label", LABEL)
    summary.setdefault("license", LICENSE)
    return summary


def predict_for_creative(creative: Dict[str, Any], base_dir: Optional[str] = None,
                         cache: Optional[Dict[str, Any]] = None, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """One row: {id, name, kind, status: ok|skipped, reason?, hash?, cached?, summary?, line?}. Never raises."""
    cfg = cfg if cfg is not None else settings()
    cache = cache if cache is not None else {}
    row: Dict[str, Any] = {"id": str(creative.get("id") or ""), "name": str(creative.get("name") or creative.get("headline") or "")[:80]}
    kind, source, reason = plan(creative, base_dir)
    row["kind"] = kind
    if reason:
        return {**row, "status": "skipped", "reason": reason}
    if not enabled(cfg):
        return {**row, "status": "skipped", "reason": "brain response is off (MM_BRAIN_RESPONSE_URL is not set)"}
    try:
        if kind != "text" and os.path.getsize(source) > cfg["max_mb"] * 1024 * 1024:
            return {**row, "status": "skipped", "reason": f"file larger than {cfg['max_mb']:g} MB (MM_BRAIN_RESPONSE_MAX_MB)"}
        body, raw = _request_body(kind, source)
    except OSError as e:
        return {**row, "status": "skipped", "reason": f"could not read the {kind}: {e.strerror or e}"}
    digest = content_hash(kind, raw)
    row["hash"] = digest
    if isinstance(cache.get(digest), dict):
        summary = cache[digest]
        return {**row, "status": "ok", "cached": True, "summary": summary, "line": plain_line(summary)}
    try:
        summary = _check_summary(_predict_remote(cfg, body))
    except SidecarError as e:
        return {**row, "status": "skipped", "reason": str(e)}
    except Exception as e:  # noqa: BLE001 - never fails a run
        return {**row, "status": "skipped", "reason": f"{type(e).__name__}: {str(e)[:200]}"}
    cache[digest] = summary
    return {**row, "status": "ok", "cached": False, "summary": summary, "line": plain_line(summary)}


# ---------------------------------------------------------------------------
# a whole run
# ---------------------------------------------------------------------------

def _read(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _write(path: str, data: Dict[str, Any]) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def attach_to_feed_test(feed_test: Dict[str, Any], rows: List[Dict[str, Any]]) -> int:
    """Store each ok summary as `brain_response` on its feed-test creative row. Adds keys only; no number changes."""
    by_id = {r["id"]: r for r in rows if r.get("status") == "ok"}
    n = 0
    for cr in feed_test.get("creatives") or []:
        r = by_id.get(str(cr.get("id")))
        if isinstance(cr, dict) and r:
            cr["brain_response"] = {"line": r["line"], "label": LABEL, "summary": r["summary"]}
            n += 1
    return n


def run(creatives: List[Dict[str, Any]], run_dir: str, base_dir: Optional[str] = None,
        progress: Optional[Callable[[int, int], None]] = None, cfg: Optional[Dict[str, Any]] = None,
        log: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Predict every creative, cache by content hash in run_dir/brain_response.json, attach to feed_test.json when it
    is there, and add the timing check. Returns the saved result. Never raises for a sidecar problem."""
    cfg = cfg if cfg is not None else settings()
    os.makedirs(run_dir, exist_ok=True)
    path = os.path.join(run_dir, FILE)
    previous = _read(path) or {}
    cache = previous.get("cache") if isinstance(previous.get("cache"), dict) else {}
    rows: List[Dict[str, Any]] = []
    sidecar = health(cfg) if enabled(cfg) else {"ok": False, "enabled": False, "reason": "MM_BRAIN_RESPONSE_URL is not set"}
    items = [c for c in creatives or [] if isinstance(c, dict)]
    for i, creative in enumerate(items):
        if enabled(cfg) and not sidecar.get("ok"):
            kind, _src, reason = plan(creative, base_dir)
            rows.append({"id": str(creative.get("id") or ""), "name": str(creative.get("name") or "")[:80], "kind": kind,
                         "status": "skipped", "reason": reason or sidecar.get("reason") or "sidecar not available"})
        else:
            rows.append(predict_for_creative(creative, base_dir, cache, cfg))
        if log:
            r = rows[-1]
            log(f"brain-response: {r['id']}: " + (r["line"] if r["status"] == "ok" else "skipped, " + r["reason"]))
        if progress:
            progress(i + 1, len(items))
    feed_path = os.path.join(run_dir, "feed_test.json")
    feed = _read(feed_path)
    attached = 0
    if feed is not None:
        attached = attach_to_feed_test(feed, rows)
        if attached:
            _write(feed_path, feed)
    result = {"model": MODEL, "license": LICENSE, "label": LABEL, "enabled": enabled(cfg),
              "sidecar": {k: sidecar.get(k) for k in ("ok", "model", "device", "loaded", "reason") if k in sidecar},
              "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "creatives": rows, "ok": sum(1 for r in rows if r["status"] == "ok"),
              "skipped": sum(1 for r in rows if r["status"] != "ok"), "attached_to_feed_test": attached,
              "timing_check": timing_check(feed, rows),
              "use": ("Shown next to the feed test as a research view. It is never given to the simulated people and "
                      "changes no simulated number."),
              "cache": cache}
    _write(path, result)
    return result


def creatives_from_run(run_dir: str) -> List[Dict[str, Any]]:
    feed = _read(os.path.join(run_dir, "feed_test.json")) or {}
    return [c for c in feed.get("creatives") or [] if isinstance(c, dict)]
