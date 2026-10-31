"""Creative vision: let the simulated buyers see the real ad, not a description of it.

Until now a feed-test creative was words only: `media` said "(image: a woman running at sunrise)" and every persona
reacted to the copywriter's description. With an image (or video keyframes) attached, two things happen:

1. One describe pass per creative (`describe`): a vision call writes what the ad actually shows, the words on it,
   whether the brand and the call to action are visible, and a pre-flight checklist for the platform (text density,
   brand in the first frame or seconds, captions for video, aspect ratio and safe zones, CTA). The aspect ratio is
   read from the file in code, not guessed. The result replaces `media` (the brief's own words are kept as
   `media_brief`), so every provider, including text-only gateways, sees the real visual in words. Cached by the
   image's sha256 in the simulation folder.
2. Optional direct mode (`vision: "direct"`): each persona's scroll call also carries the image. The image sits in
   the shared, cached part of the prompt (one cache entry per platform and creative), so a crowd pays for it about
   once on Claude's native API.

Commercial pre-testing tools (Kantar LINK AI, Neurons, Yabble Vision, DAIVID) score the visual itself. Here the
checklist is a model's reading of the image plus fixed platform rules: a pre-flight check, not a measured
attention or recall score. Whether vision changes the simulated ranking's accuracy is an open question for the
backtest and the bench.

Stdlib only.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import struct
from typing import Any, Callable, Dict, List, Optional, Tuple

VERSION = 1
MAX_FRAMES = 4
MAX_IMAGE_BYTES = 4_000_000

# Complete = (system, user_parts) -> (text, usage); user_parts is an OpenAI-style content list with image_url parts
CompleteVision = Callable[[str, List[Dict[str, Any]]], Tuple[str, Dict[str, Any]]]

# preferred aspect ratios (width / height) per platform placement, with a tolerance
ASPECTS: Dict[str, List[Tuple[str, float]]] = {
    "facebook": [("1:1", 1.0), ("4:5", 0.8), ("1.91:1", 1.91), ("9:16", 0.5625)],
    "instagram": [("1:1", 1.0), ("4:5", 0.8), ("9:16", 0.5625)],
    "tiktok": [("9:16", 0.5625)],
    "reddit": [("1:1", 1.0), ("4:3", 1.333), ("16:9", 1.778), ("4:5", 0.8)],
    "linkedin": [("1.91:1", 1.91), ("1:1", 1.0), ("4:5", 0.8)],
    "x": [("16:9", 1.778), ("1:1", 1.0)],
}

CHECKS: Dict[str, str] = {
    "brand_early": "The brand or product is recognisable in the image (for video: within the first 2 seconds)",
    "text_light": "Text covers a small part of the image (roughly under a fifth); the picture carries the message",
    "words_legible": "Any words on the image are large enough to read on a phone at a glance",
    "message_clear": "Someone scrolling past in one second can tell what is offered",
    "cta_visible": "The next step (button, offer, link) is clear from the image or the copy",
    "safe_zones": "Nothing important sits where the app covers it (top and bottom ~15% on vertical video, edges)",
    "captions": "For video: the key message works with the sound off (captions or on-screen text)",
}
VIDEO_ONLY = {"captions"}

SYSTEM = ("You check ad creatives before launch. You describe only what is visible; you do not guess the brief. "
          "Reply with JSON only.")


# --------------------------------------------------------------------------
# sources
# --------------------------------------------------------------------------

def sources(creative: Dict[str, Any]) -> List[str]:
    """The creative's image and video keyframes as data URIs or https URLs (max MAX_FRAMES)."""
    out = []
    img = creative.get("image")
    if isinstance(img, str) and (img.startswith("data:image/") or img.startswith("https://")):
        out.append(img)
    for f in creative.get("frames") or []:
        if isinstance(f, str) and (f.startswith("data:image/") or f.startswith("https://")) and f not in out:
            out.append(f)
    return out[:MAX_FRAMES]


def has_visual(creative: Dict[str, Any]) -> bool:
    return bool(sources(creative))


def fingerprint(creative: Dict[str, Any]) -> str:
    h = hashlib.sha256()
    for s in sources(creative):
        h.update(s.encode("utf-8"))
    h.update(str(creative.get("platform") or "").encode())
    h.update(str(VERSION).encode())
    return h.hexdigest()[:24]


def image_parts(creative: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [{"type": "image_url", "image_url": {"url": s}} for s in sources(creative)]


def _decode(uri: str) -> Optional[bytes]:
    m = re.match(r"^data:image/[\w.+-]+;base64,(.+)$", uri, re.S)
    if not m:
        return None
    try:
        return base64.b64decode(m.group(1), validate=False)
    except (ValueError, TypeError):
        return None


def dimensions(uri: str) -> Optional[Tuple[int, int]]:
    """(width, height) of a PNG, JPEG, GIF or WebP data URI, read from the header; None when unknown."""
    data = _decode(uri) or b""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
        return struct.unpack("<HH", data[6:10])
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP" and len(data) >= 30:
        chunk = data[12:16]
        if chunk == b"VP8X":
            w = 1 + int.from_bytes(data[24:27], "little")
            h = 1 + int.from_bytes(data[27:30], "little")
            return w, h
        if chunk == b"VP8 " and len(data) >= 30:
            w, h = struct.unpack("<HH", data[26:30])
            return w & 0x3FFF, h & 0x3FFF
        if chunk == b"VP8L" and len(data) >= 25:
            b = data[21:25]
            w = 1 + (((b[1] & 0x3F) << 8) | b[0])
            h = 1 + (((b[3] & 0xF) << 10) | (b[2] << 2) | ((b[1] & 0xC0) >> 6))
            return w, h
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return w, h
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            seg = struct.unpack(">H", data[i + 2:i + 4])[0]
            i += 2 + seg
    return None


def aspect_check(creative: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Measured aspect ratio vs the platform's preferred placements (code, not the model)."""
    src = sources(creative)
    dims = dimensions(src[0]) if src else None
    if not dims or not dims[1]:
        return None
    w, h = dims
    ratio = w / h
    prefs = ASPECTS.get(str(creative.get("platform") or ""), [])
    best = min(prefs, key=lambda p: abs(p[1] - ratio)) if prefs else None
    ok = bool(best) and abs(best[1] - ratio) / best[1] <= 0.06
    note = (f"{w}x{h} ({ratio:.2f}:1)" + (f", fits {best[0]}" if ok and best else
                                          f"; the platform prefers {', '.join(p[0] for p in prefs)}" if prefs else ""))
    return {"check": "aspect_ratio", "label": "Aspect ratio fits the placement", "pass": ok, "note": note,
            "source": "measured"}


# --------------------------------------------------------------------------
# describe
# --------------------------------------------------------------------------

def describe_prompt(creative: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]]]:
    video = bool(creative.get("frames")) or str(creative.get("format") or "").lower() in ("video", "reel", "story")
    checks = {k: v for k, v in CHECKS.items() if video or k not in VIDEO_ONLY}
    frames_note = (f"These are {len(sources(creative))} keyframes of a video ad, in order (first frame first). "
                   if video and len(sources(creative)) > 1 else "")
    copy = "\n".join(f"{k}: {creative.get(k)}" for k in ("page", "headline", "text", "cta") if creative.get(k))
    schema = {"description": "2-3 sentences: what the ad shows, as a viewer would see it (people, product, setting, mood)",
              "on_image_text": "the words printed on the image or frames, verbatim, or empty",
              "brand_visible": True, "brand_where": "where the brand or logo appears, or empty",
              "first_glance": "what a person scrolling past in one second takes away, one sentence",
              "checks": {k: {"pass": True, "note": "short reason"} for k in checks}}
    text = (f"{frames_note}This ad runs on {creative.get('platform')}. The ad copy around it:\n{copy}\n\n"
            "Describe the creative and run the pre-flight checks. Use pass=null when you cannot tell.\nChecks:\n"
            + "\n".join(f"- {k}: {v}" for k, v in checks.items())
            + "\n\nReply with only this JSON:\n" + json.dumps(schema))
    return SYSTEM, [{"type": "text", "text": text}] + image_parts(creative)


def _json_block(text: str) -> Any:
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    a, b = text.find("{"), text.rfind("}")
    if a != -1 and b > a:
        try:
            return json.loads(text[a:b + 1])
        except ValueError:
            return None
    return None


def parse(text: str, creative: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    d = _json_block(text)
    if not isinstance(d, dict) or not str(d.get("description") or "").strip():
        return None
    video = bool(creative.get("frames")) or str(creative.get("format") or "").lower() in ("video", "reel", "story")
    raw_checks = d.get("checks") if isinstance(d.get("checks"), dict) else {}
    checks = []
    for k, label in CHECKS.items():
        if k in VIDEO_ONLY and not video:
            continue
        c = raw_checks.get(k) if isinstance(raw_checks.get(k), dict) else {}
        p = c.get("pass")
        checks.append({"check": k, "label": label, "pass": p if isinstance(p, bool) else None,
                       "note": str(c.get("note") or "")[:200], "source": "model"})
    measured = aspect_check(creative)
    if measured:
        checks.append(measured)
    return {"version": VERSION, "description": str(d["description"]).strip()[:600],
            "on_image_text": str(d.get("on_image_text") or "").strip()[:400],
            "brand_visible": d.get("brand_visible") if isinstance(d.get("brand_visible"), bool) else None,
            "brand_where": str(d.get("brand_where") or "").strip()[:200],
            "first_glance": str(d.get("first_glance") or "").strip()[:240],
            "frames": len(sources(creative)), "checks": checks,
            "passed": sum(1 for c in checks if c["pass"] is True),
            "failed": [c["check"] for c in checks if c["pass"] is False]}


def describe(creative: Dict[str, Any], complete: CompleteVision, cache_dir: Optional[str] = None) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """One vision call per creative (cached by image hash). Returns (visual or None, usage)."""
    if not has_visual(creative):
        return None, {}
    key = fingerprint(creative)
    path = os.path.join(cache_dir, f"vision_{key}.json") if cache_dir else None
    if path and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                return {**json.load(f), "cached": True}, {}
        except (OSError, ValueError):
            pass
    system, parts = describe_prompt(creative)
    text, usage = complete(system, parts)
    visual = parse(text, creative)
    if visual and path:
        os.makedirs(cache_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(visual, f, ensure_ascii=False, indent=2)
    return visual, usage or {}


def apply(creative: Dict[str, Any], visual: Dict[str, Any]) -> Dict[str, Any]:
    """The creative with what the image shows as its `media` (the brief's own words kept as `media_brief`)."""
    out = dict(creative)
    if creative.get("media") and "media_brief" not in out:
        out["media_brief"] = creative["media"]
    words = f' Words on it: "{visual["on_image_text"]}".' if visual.get("on_image_text") else ""
    out["media"] = (visual["description"] + words)[:700]
    out["visual"] = visual
    return out


def prepare(creatives: List[Dict[str, Any]], complete: CompleteVision, cache_dir: Optional[str] = None,
            log: Optional[Callable[[str], None]] = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Describe every creative that has an image; a failed call leaves that creative's words as they were."""
    usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
    out, failed = [], []
    for cr in creatives:
        if not has_visual(cr):
            out.append(cr)
            continue
        try:
            visual, u = describe(cr, complete, cache_dir)
        except Exception as e:  # noqa: BLE001 - a provider without vision keeps the text description
            visual, u = None, {}
            if log:
                log(f"creative vision: {cr.get('id')} not described ({str(e)[:160]}); using its text description")
        if u:
            usage["calls"] += 1
            for k in ("input_tokens", "output_tokens"):
                usage[k] += int(u.get(k) or 0)
        if visual:
            out.append(apply(cr, visual))
        else:
            failed.append(cr.get("id"))
            out.append(cr)
    return out, {"usage": usage, "failed": failed, "described": sum(1 for c in out if c.get("visual"))}


def strip_sources(creative: Dict[str, Any]) -> Dict[str, Any]:
    """The creative without image bytes (results stay small; the CLI re-attaches a thumbnail)."""
    return {k: v for k, v in creative.items() if k not in ("image", "frames")}
