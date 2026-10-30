"""Creative vision: image headers, the describe pass and its cache, the checklist, the native image blocks, the
feed test in describe / direct mode, and the creative-check API."""

import base64
import importlib.util
import json
import os
import struct
import zlib
from types import SimpleNamespace

from app.services import creative_vision as cv
from app.services import feed_test as ft
from app.utils import anthropic_native as an

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("feed_test_fixtures", os.path.join(HERE, "test_feed_test.py"))
fx = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fx)


def png(w, h):
    raw = b"".join(b"\x00" + b"\xff\xff\xff" * w for _ in range(h))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    data = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return "data:image/png;base64," + base64.b64encode(data).decode()


def jpeg(w, h):
    data = (b"\xff\xd8" + b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
            + b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, h, w, 1) + b"\x01\x11\x00" + b"\xff\xd9")
    return "data:image/jpeg;base64," + base64.b64encode(data).decode()


VISUAL = {"description": "A woman stretching on a yoga mat beside a phone showing the app.",
          "on_image_text": "7 minutes a day", "brand_visible": True, "brand_where": "logo bottom right",
          "first_glance": "A quick daily stretch app.",
          "checks": {"brand_early": {"pass": True, "note": "logo visible"}, "text_light": {"pass": True},
                     "words_legible": {"pass": False, "note": "small subtitle"}, "message_clear": {"pass": True},
                     "cta_visible": {"pass": None}, "safe_zones": {"pass": True}, "captions": {"pass": True}}}


def fake_complete(calls, body=None):
    def complete(system, parts):
        calls.append(parts)
        return json.dumps(body or VISUAL), {"input_tokens": 1200, "output_tokens": 80}
    return complete


# ---------------------------------------------------------------- headers, checks, cache

def test_dimensions_and_aspect_check():
    assert cv.dimensions(png(40, 50)) == (40, 50)
    assert cv.dimensions(jpeg(1080, 1920)) == (1080, 1920)
    assert cv.dimensions("data:image/png;base64,bm90IGFuIGltYWdl") is None
    ok = cv.aspect_check({"platform": "instagram", "image": png(40, 50)})
    assert ok["pass"] is True and "4:5" in ok["note"] and ok["source"] == "measured"
    bad = cv.aspect_check({"platform": "tiktok", "image": png(60, 30)})
    assert bad["pass"] is False and "9:16" in bad["note"]
    assert cv.aspect_check({"platform": "x", "image": "https://cdn.example.com/a.png"}) is None


def test_describe_parses_checks_and_caches_by_image(tmp_path):
    cr = {"id": "ig1", "platform": "instagram", "text": "Stretch daily", "image": png(40, 50), "media": "a yoga photo"}
    calls = []
    v, u = cv.describe(cr, fake_complete(calls), str(tmp_path))
    assert len(calls) == 1 and calls[0][1]["type"] == "image_url" and u["input_tokens"] == 1200
    assert "captions" not in [c["check"] for c in v["checks"]]                 # a still image has no captions check
    assert v["failed"] == ["words_legible"] and v["checks"][-1]["check"] == "aspect_ratio"
    again, u2 = cv.describe(cr, fake_complete(calls), str(tmp_path))
    assert len(calls) == 1 and again["cached"] and u2 == {}
    applied = cv.apply(cr, v)
    assert applied["media_brief"] == "a yoga photo" and "7 minutes a day" in applied["media"]
    video = {**cr, "image": None, "frames": [png(9, 16), png(18, 32)], "format": "video"}
    vv, _ = cv.describe(video, fake_complete(calls), str(tmp_path))
    assert "captions" in [c["check"] for c in vv["checks"]] and vv["frames"] == 2
    assert "keyframes of a video" in calls[-1][0]["text"]


def test_prepare_keeps_text_when_vision_fails():
    def boom(system, parts):
        raise RuntimeError("model does not accept images")
    crs = [{"id": "a", "platform": "facebook", "text": "x", "image": png(10, 10)}, {"id": "b", "platform": "facebook", "text": "y"}]
    logs = []
    out, info = cv.prepare(crs, boom, None, logs.append)
    assert out == crs and info["failed"] == ["a"] and info["described"] == 0 and logs
    out, info = cv.prepare(crs, fake_complete([], {"no": "description"}), None)
    assert info["failed"] == ["a"] and "visual" not in out[0]


# ---------------------------------------------------------------- native image blocks

def test_native_translation_carries_images_and_caches_up_to_them():
    img = png(4, 4)
    parts = [{"type": "text", "text": "Shared instructions"}, {"type": "image_url", "image_url": {"url": img}},
             {"type": "text", "text": an.CACHE_BREAK + "Who you are: Ana"}]
    system, native = an._to_native([{"role": "system", "content": "sys"}, {"role": "user", "content": parts}])
    blocks = native[0]["content"]
    assert [b["type"] for b in blocks] == ["text", "image", "text"]
    assert blocks[1]["source"]["type"] == "base64" and blocks[1]["source"]["media_type"] == "image/png"
    assert "cache_control" in blocks[1] and "cache_control" not in blocks[2]
    assert an.CACHE_BREAK not in blocks[2]["text"] and "cache_control" not in system[-1]
    _, native = an._to_native([{"role": "user", "content": [{"type": "text", "text": "see"},
                                                             {"type": "image_url", "image_url": {"url": "https://x.io/a.jpg"}}]}])
    assert native[0]["content"][1]["source"] == {"type": "url", "url": "https://x.io/a.jpg"}
    stripped = an.strip_cache_break([{"role": "user", "content": parts}])[0]["content"]
    assert all(an.CACHE_BREAK not in str(p.get("text", "")) for p in stripped) and stripped[1] == parts[1]


# ---------------------------------------------------------------- feed test

class SeeingLLM(fx.FakeLLM):
    """The feed-test fake, plus a record of which scroll calls carried a picture."""

    def __init__(self):
        super().__init__()
        self.with_image = 0
        self.text_only = 0

    def create(self, **kw):
        user = kw["messages"][1]["content"]
        if isinstance(user, list):
            self.with_image += 1
            text = "".join(p.get("text", "") for p in user if p.get("type") == "text")
            kw = {**kw, "messages": [kw["messages"][0], {"role": "user", "content": text}]}
        elif kw["messages"][0]["content"] == ft.SYSTEM_PROMPT:
            self.text_only += 1
        return super().create(**kw)


def test_normalize_keeps_pictures_and_refuses_local_paths():
    out = ft.normalize_creatives([{"text": "a", "image": png(4, 4), "frames": [png(4, 4)] * 6}])
    assert out[0]["image"].startswith("data:image/png") and len(out[0]["frames"]) == 4
    for bad in ({"text": "a", "image": "pics/ad.png"}, {"text": "a", "frames": ["http://x/a.png"]}):
        try:
            ft.normalize_creatives([bad])
        except ValueError:
            continue
        raise AssertionError(bad)


def test_feed_test_direct_mode_sends_the_picture_and_results_stay_small():
    crs = ft.normalize_creatives([{**fx.CREATIVES[0], "image": png(40, 50)}, fx.CREATIVES[1]])
    llm = SeeingLLM()
    res = ft.run_feed_test(llm, "m", crs, fx.people(12), attention_gate=False, exposures=1, waves=1, vision="direct")
    assert llm.with_image > 0 and llm.text_only > 0          # ig1 viewers see the picture; ig2 has none
    assert res["vision"] == "direct" and all("image" not in c for c in res["creatives"])
    llm = SeeingLLM()
    res = ft.run_feed_test(llm, "m", crs, fx.people(12), attention_gate=False, exposures=1, waves=1, vision="describe")
    assert llm.with_image == 0 and res["vision"] == "describe"


# ---------------------------------------------------------------- API

class VisionClient:
    def __init__(self):
        self.seen = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.seen.append(kw["messages"][1]["content"])
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(VISUAL)), finish_reason="stop")],
                               usage=SimpleNamespace(prompt_tokens=900, completion_tokens=60))


def test_creative_check_api(tmp_path, monkeypatch):
    from app import create_app
    from app.api import market
    from app.config import Config
    client = VisionClient()
    monkeypatch.setattr(market, "_client", lambda: client)
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path))
    app = create_app()
    app.config.update(TESTING=True)
    c = app.test_client()
    assert c.post("/api/simulation/creative-check", json={"creatives": [{"text": "no picture"}]}).status_code == 400
    assert c.post("/api/simulation/creative-check", json={"creatives": [{"text": "x", "image": "a.png"}]}).status_code == 400
    r = c.post("/api/simulation/creative-check", json={"creatives": [{"id": "ig1", "platform": "instagram", "text": "Stretch",
                                                                       "image": png(40, 50)}]})
    assert r.status_code == 200, r.get_json()
    d = r.get_json()["data"]
    assert d["described"] == 1 and d["usage"]["calls"] == 1 and "not a measured attention" in d["note"]
    v = d["creatives"][0]["visual"]
    assert v["first_glance"] and any(ch["check"] == "aspect_ratio" and ch["pass"] for ch in v["checks"])
    assert isinstance(client.seen[0], list) and client.seen[0][1]["type"] == "image_url"
    assert os.listdir(os.path.join(str(tmp_path), "creative_vision"))
