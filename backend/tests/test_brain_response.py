"""Brain response (Meta TRIBE v2 via the owner's sidecar): tested with the real sidecar server and a fake predictor.
No model, weights, GPU or network beyond 127.0.0.1."""
import importlib.util
import json
import math
import os
import subprocess
import sys
import threading

import pytest

from app.services import brain_response as br

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(BACKEND)
SIDECAR = os.path.join(BACKEND, "brain_sidecar")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ts = _load("tribe_server_under_test", os.path.join(SIDECAR, "tribe_server.py"))

LABELS = [b"Unknown", b"G_cuneus", b"S_calcarine", b"G_temp_sup-G_T_transv", b"G_front_inf-Triangul_part",
          b"G_temporal_middle", b"G_precentral", b"Medial_wall"]
LEFT = [0, 1, 2, 3, 4, 5, 6, 7, 1, 3, 4, 6]
RIGHT = list(LEFT)


class FakePredictor:
    model_id = "fake/tribev2"
    loaded = True

    def __init__(self, fail=False, seconds=12):
        self.calls, self.fail, self.seconds = [], fail, seconds

    def device(self):
        return "cpu"

    def predict(self, kind, path):
        assert os.path.exists(path)
        self.calls.append(kind)
        if self.fail:
            raise RuntimeError("CUDA out of memory")
        n_v = len(LEFT) + len(RIGHT)
        # hearing vertices (label 3) peak at seconds 4-6; others are a slow wave
        rows = []
        for t in range(self.seconds):
            row = []
            for v in range(n_v):
                lab = (LEFT + RIGHT)[v]
                row.append(3.0 if lab == 3 and 4 <= t <= 6 else math.sin(t / 2 + v) * 0.3)
            rows.append(row)
        return rows, None


@pytest.fixture
def sidecar():
    started = []

    def start(token="s3cret", predictor=None):
        pred = predictor or FakePredictor()
        srv = ts.make_server("127.0.0.1", 0, pred, lambda: (LABELS, LEFT, RIGHT), token=token)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        started.append(srv)
        cfg = br.settings({"MM_BRAIN_RESPONSE_URL": f"http://127.0.0.1:{srv.server_address[1]}",
                           "MM_BRAIN_RESPONSE_TOKEN": token, "MM_BRAIN_RESPONSE_POLL": "0.02",
                           "MM_BRAIN_RESPONSE_TIMEOUT": "20"})
        return cfg, pred

    yield start
    for srv in started:
        srv.shutdown()
        srv.server_close()


def _video(tmp_path, name="ad.mp4", data=b"\x00\x00fake-mp4"):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


def test_off_without_url(tmp_path):
    cfg = br.settings({})
    assert not br.enabled(cfg)
    row = br.predict_for_creative({"id": "t1", "text": "Stretch in five minutes"}, cfg=cfg)
    assert row["status"] == "skipped" and "MM_BRAIN_RESPONSE_URL" in row["reason"]
    res = br.run([{"id": "t1", "text": "x"}], str(tmp_path), cfg=cfg)
    assert res["enabled"] is False and res["ok"] == 0 and res["skipped"] == 1
    assert br.health(cfg)["enabled"] is False


def test_settings_read_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / "mm.env"
    env_file.write_text("MM_BRAIN_RESPONSE_URL=https://example.trycloudflare.com/\nMM_BRAIN_RESPONSE_TOKEN=abc\n")
    monkeypatch.setenv("MIROFISH_ENV_FILE", str(env_file))
    monkeypatch.delenv("MM_BRAIN_RESPONSE_URL", raising=False)
    cfg = br.settings()
    assert cfg["url"] == "https://example.trycloudflare.com" and cfg["token"] == "abc" and br.enabled(cfg)
    assert br._headers(cfg)["Authorization"] == "Bearer abc"
    hf = br._headers({**cfg, "hf_token": "hfx"})
    assert hf["Authorization"] == "Bearer hfx" and hf["X-MM-Tribe-Token"] == "abc"


def test_sidecar_summary_shape_and_token(sidecar, tmp_path):
    cfg, pred = sidecar()
    assert br.health(cfg)["ok"] is True and br.health(cfg)["auth"] is True
    bad = {**cfg, "token": "wrong"}
    with pytest.raises(br.SidecarError, match="token"):
        br._call(bad, "POST", "/predict", {"kind": "text", "text": "hi"})
    with pytest.raises(br.SidecarError, match="401|token"):
        br._call({**cfg, "token": ""}, "POST", "/predict", {"kind": "text", "text": "hi"})
    out = br._call(cfg, "POST", "/predict", {"kind": "text", "text": "hi"})
    s = out["summary"]
    assert set(s["groups"]) == {"visual", "hearing", "language", "cortex"}
    for g in s["groups"].values():
        assert len(g["z"]) == len(s["seconds"]) == 12 and g["peaks"] and g["vertices"] > 0
        assert abs(sum(g["z"]) / len(g["z"])) < 1e-3          # z-scored within the clip (3 decimals)
    assert s["groups"]["hearing"]["peaks"][0]["start"] == 4.0 and s["groups"]["hearing"]["peaks"][0]["end"] == 6.0
    assert s["license"].startswith("CC BY-NC") and "5 s" in s["lag_note"] and s["duration_s"] == 12.0
    assert "attention" in s["label"] and s["n_vertices"] == 24
    assert not any(isinstance(v, list) and v and isinstance(v[0], list) for v in s.values())   # no raw vertices
    # paths are off by default; bad input is a 400
    with pytest.raises(br.SidecarError, match="paths are off"):
        br._call(cfg, "POST", "/predict", {"kind": "video", "path": _video(tmp_path)})
    with pytest.raises(br.SidecarError, match="kind"):
        br._call(cfg, "POST", "/predict", {"kind": "image", "data_b64": "AAAA"})


def test_server_refuses_public_host_without_token():
    with pytest.raises(SystemExit):
        ts.make_server("0.0.0.0", 0, FakePredictor(), lambda: (LABELS, LEFT, RIGHT), token="")


def test_group_vertices_unknown_mesh_falls_back_to_cortex():
    groups, notes = ts.group_vertices(LABELS, LEFT, RIGHT, 7)
    assert list(groups) == ["cortex"] and "fsaverage5" in notes[0]


def test_video_prediction_cache_and_feed_attach(sidecar, tmp_path):
    cfg, pred = sidecar()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    feed = {"creatives": [{"id": "v1", "name": "Launch video", "platform": "instagram", "format": "video", "text": "x"}],
            "summary": {"per_creative": {"v1": {"ctr": 1.2, "thoughts": [{"segment": "A", "text": "liked it"}]}}}}
    (run_dir / "feed_test.json").write_text(json.dumps(feed))
    creatives = [{"id": "v1", "video": "ad.mp4", "text": "x"}]
    _video(tmp_path)
    res = br.run(creatives, str(run_dir), str(tmp_path), cfg=cfg)
    row = res["creatives"][0]
    assert row["status"] == "ok" and row["kind"] == "video" and row["cached"] is False
    assert row["line"] == ("Predicted brain response for an average viewer (TRIBE v2, research model): "
                           "hearing areas peak at 0:04-0:06.")
    saved = json.loads((run_dir / "feed_test.json").read_text())
    assert saved["creatives"][0]["brain_response"]["line"] == row["line"]
    assert saved["summary"]["per_creative"]["v1"]["ctr"] == 1.2          # simulated numbers untouched
    assert res["timing_check"]["status"] == "needs_timestamps" and "timestamps" in res["timing_check"]["note"]
    again = br.run(creatives, str(run_dir), str(tmp_path), cfg=cfg)
    assert again["creatives"][0]["cached"] is True and pred.calls == ["video"]
    on_disk = json.loads((run_dir / "brain_response.json").read_text())
    assert row["hash"] in on_disk["cache"] and on_disk["label"] == br.LABEL


def test_image_and_remote_media_are_skipped(sidecar, tmp_path):
    cfg, pred = sidecar()
    rows = br.run([{"id": "img", "image": "data:image/png;base64,AAAA", "text": "caption"},
                   {"id": "web", "video": "https://cdn.example.com/ad.mp4"},
                   {"id": "missing", "video": "/nope/ad.mp4"},
                   {"id": "cap", "headline": "Stretch daily", "text": "Five minutes"}], str(tmp_path), cfg=cfg)["creatives"]
    by = {r["id"]: r for r in rows}
    assert by["img"]["status"] == "skipped" and "no image input" in by["img"]["reason"]
    assert by["web"]["status"] == "skipped" and "local file" in by["web"]["reason"]
    assert by["missing"]["status"] == "skipped" and "no video file" in by["missing"]["reason"]
    assert by["cap"]["status"] == "ok" and by["cap"]["kind"] == "text"
    assert pred.calls == ["text"]


def test_sidecar_down_and_failures_never_raise(sidecar, tmp_path):
    down = br.settings({"MM_BRAIN_RESPONSE_URL": "http://127.0.0.1:9", "MM_BRAIN_RESPONSE_REQUEST_TIMEOUT": "2"})
    res = br.run([{"id": "t", "text": "hello"}], str(tmp_path), cfg=down)
    assert res["creatives"][0]["status"] == "skipped" and "not reachable" in res["creatives"][0]["reason"]
    cfg, _ = sidecar(predictor=FakePredictor(fail=True))
    res = br.run([{"id": "t", "text": "hello"}], str(tmp_path / "b"), cfg=cfg)
    assert res["creatives"][0]["status"] == "skipped" and "out of memory" in res["creatives"][0]["reason"]
    big = {**cfg, "max_mb": 0.000001}
    row = br.predict_for_creative({"id": "v", "video": _video(tmp_path, data=b"x" * 100)}, cfg=big)
    assert row["status"] == "skipped" and "larger than" in row["reason"]


def test_timing_check_compares_named_moments(sidecar, tmp_path):
    cfg, _ = sidecar()
    feed = {"summary": {"per_creative": {"cap": {"thoughts": [{"text": "the voice at 0:05 got me"},
                                                              {"text": "lost me at the end"}],
                                                 "comments_list": [{"text": "around 20 seconds it drags"}]}}}}
    (tmp_path / "feed_test.json").write_text(json.dumps(feed))
    res = br.run([{"id": "cap", "text": "caption"}], str(tmp_path), cfg=cfg)
    tc = res["timing_check"]
    assert tc["status"] == "ok" and tc["references"] == 3 and tc["near_peak"] >= 1
    assert "not validation" in tc["note"]
    assert br.time_refs("at 1:05 and 3 seconds in") == [65, 3]


def test_notebook_is_valid_and_current():
    path = os.path.join(SIDECAR, "colab", "MarketMirror_TRIBE_v2.ipynb")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    nb = json.loads(text)
    assert nb["nbformat"] == 4 and all(c["cell_type"] in ("markdown", "code") for c in nb["cells"])
    src = "\n".join("".join(c["source"]) for c in nb["cells"])
    for needle in ("CC BY-NC 4.0", "T4", 'uv pip install --system "tribev2[plotting] @ git+https://github.com/facebookresearch/tribev2.git"',
                   "notebook_login()", "DarkWorldCoder/market-mirror", "feat/codex-workspace-features",
                   "secrets.token_urlsafe", "github.com/cloudflare/cloudflared/releases", "tunnel", "--url",
                   "MM_BRAIN_RESPONSE_URL=", "MM_BRAIN_RESPONSE_TOKEN=", "sintel_trailer-480p.mp4", "Restart session"):
        assert needle in src, needle
    assert "hf_" not in src.replace("huggingface_hub", "")       # no token is ever written into the notebook
    for c in nb["cells"]:
        if c["cell_type"] == "code":
            compile("".join(line for line in c["source"] if not line.startswith("!")), "cell", "exec")
    builder = _load("build_notebook_under_test", os.path.join(SIDECAR, "colab", "build_notebook.py"))
    assert builder.render() == text, "run backend/brain_sidecar/colab/build_notebook.py"


def test_setup_refuses_without_license_acceptance():
    env = {k: v for k, v in os.environ.items() if k != "MM_TRIBE_ACCEPT_NONCOMMERCIAL"}
    p = subprocess.run(["bash", os.path.join(SIDECAR, "brain_sidecar.sh"), "setup"], capture_output=True, text=True,
                       env=env, timeout=30)
    assert p.returncode == 3
    assert "CC BY-NC 4.0" in p.stderr and "huggingface-cli login" in p.stderr and "Llama-3.2-3B" in p.stderr
    assert not os.path.exists(os.path.join(SIDECAR, ".venv"))


def _summary_row():
    s = ts.summarize([[math.sin(t / 2 + v) for v in range(6)] for t in range(10)], None,
                     {"visual": [0, 1], "hearing": [2], "language": [3, 4], "cortex": list(range(6))})
    return {"id": "v1", "name": "Launch", "status": "ok", "kind": "video", "summary": s, "line": br.plain_line(s)}


def test_exporter_block(tmp_path):
    sys.path.insert(0, os.path.join(BACKEND, "claude_cli"))
    import exporter
    run = tmp_path / "run"
    run.mkdir()
    (run / "brain_response.json").write_text(json.dumps({
        "creatives": [_summary_row(), {"id": "img", "status": "skipped", "kind": "image", "reason": "TRIBE v2 has no image input"}],
        "timing_check": {"status": "needs_timestamps", "note": "This check needs reactions tied to video timestamps."}}))
    paths = exporter.export_run_dir(str(run))
    html = open(paths["html"], encoding="utf-8").read()
    assert "Predicted brain response (research)" in html and "<polyline" in html
    assert "not attention, feelings, memory or buying" in html and "no image input" in html
    assert "video timestamps" in html
    # without brain_response.json the block comes from the feed-test rows, and is absent when neither exists
    import brain_view
    row = _summary_row()
    sec = brain_view.section(None, {"creatives": [{"id": "v1", "brain_response": {"summary": row["summary"], "line": row["line"]}}]})
    assert sec and sec[0] == "brain" and "polyline" in sec[2]
    assert brain_view.section(None, {"creatives": [{"id": "v1"}]}) is None


def test_api_route(sidecar, tmp_path, monkeypatch):
    from app import create_app
    from app.api import market
    monkeypatch.setattr(market, "_sim_dir", lambda sid: str(tmp_path))
    ran = {}

    def start(kind, sid, work, *a, **k):
        ran["kind"], ran["result"] = kind, work(lambda done, total: None)
        return "task_brain"

    monkeypatch.setattr(market, "_start", start)
    app = create_app()
    app.config.update(TESTING=True)
    c = app.test_client()
    monkeypatch.delenv("MM_BRAIN_RESPONSE_URL", raising=False)
    r = c.post("/api/simulation/brain-response", json={"simulation_id": "sim_x", "creatives": [{"id": "a", "text": "x"}]})
    assert r.status_code == 400 and "MM_BRAIN_RESPONSE_URL" in r.get_json()["error"]
    cfg, _ = sidecar()
    monkeypatch.setenv("MM_BRAIN_RESPONSE_URL", cfg["url"])
    monkeypatch.setenv("MM_BRAIN_RESPONSE_TOKEN", cfg["token"])
    monkeypatch.setenv("MM_BRAIN_RESPONSE_POLL", "0.02")
    r = c.post("/api/simulation/brain-response", json={"simulation_id": "sim_x"})
    assert r.status_code == 400                               # no creatives and no feed test yet
    r = c.post("/api/simulation/brain-response", json={"simulation_id": "sim_x", "creatives": [{"id": "a", "text": "Stretch"}]})
    assert r.status_code == 200, r.get_json()
    d = r.get_json()["data"]
    assert d["task_id"] == "task_brain" and "TRIBE v2" in d["label"]
    assert ran["kind"] == "brain-response" and ran["result"]["ok"] == 1
    assert (tmp_path / "brain_response.json").exists()
    assert market.RESULT_FILES["brain-response"] == "brain_response.json"
    from app.api.registry import ENDPOINTS
    assert any(e["path"] == "/api/simulation/brain-response" for e in ENDPOINTS)


def test_cli_command(sidecar, tmp_path, monkeypatch, capsys):
    sys.path.insert(0, os.path.join(BACKEND, "claude_cli"))
    import mirofish
    run = tmp_path / "run"
    monkeypatch.delenv("MM_BRAIN_RESPONSE_URL", raising=False)
    assert mirofish.main(["brain-response", "--run-dir", str(run)]) == 1
    assert "MM_BRAIN_RESPONSE_URL" in capsys.readouterr().out
    cfg, pred = sidecar()
    monkeypatch.setenv("MM_BRAIN_RESPONSE_URL", cfg["url"])
    monkeypatch.setenv("MM_BRAIN_RESPONSE_TOKEN", cfg["token"])
    monkeypatch.setenv("MM_BRAIN_RESPONSE_POLL", "0.02")
    _video(tmp_path, "spot.mp4")
    spec = tmp_path / "creatives.json"
    spec.write_text(json.dumps({"creatives": [{"id": "v1", "video": "spot.mp4"}, {"id": "i1", "image": "pic.png", "text": "x"}]}))
    assert mirofish.main(["brain-response", "--run-dir", str(run), "--creatives", "@" + str(spec)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] == 1 and out["skipped"] == 1 and "cache" not in out
    assert (run / "brain_response.json").exists() and pred.calls == ["video"]


def test_mcp_lists_the_tool_and_chat_agent_marks_it_outside(tmp_path):
    mcp = os.path.join(REPO, "plugin", "skills", "market-mirror", "scripts", "mcp_server.py")
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]
    p = subprocess.run([sys.executable, mcp], input="\n".join(json.dumps(m) for m in msgs) + "\n",
                       capture_output=True, text=True, timeout=60, env={**os.environ, "MARKET_MIRROR_HOME": str(tmp_path)})
    out = {m["id"]: m for m in map(json.loads, p.stdout.splitlines())}
    tool = next(t for t in out[2]["result"]["tools"] if t["name"] == "brain_response")
    assert "noncommercial" in tool["description"] and "not attention" in tool["description"]
    assert tool["inputSchema"]["required"] == ["run"]
    from app.services.chat_agent import tools as T
    assert T.classify("brain_response", {})["cost"] == T.OUTSIDE
    assert "brain_response" in T.phase_tools("review") and T.LABELS["brain_response"]
