"""Small HTTP/JSON server that runs Meta's TRIBE v2 brain-response model and returns a compact summary.

TRIBE v2 (https://huggingface.co/facebook/tribev2, code https://github.com/facebookresearch/tribev2) predicts how
the cortex of an *average* person responds to a video, audio or text stimulus, about once per second, on the
fsaverage5 surface (~20k vertices). Its predictions are already shifted 5 s earlier to make up for the slow blood-flow
(hemodynamic) response, so the seconds line up with the stimulus. It predicts brain activity only: no attention,
feelings, memory, words or buying.

License: CC BY-NC 4.0 (noncommercial) for the code and the weights. The text encoder needs gated access to
meta-llama/Llama-3.2-3B. A GPU is needed in practice. This server is opt-in and never part of a default install.

Why a separate server: TRIBE needs torch, WhisperX, DINOv2, V-JEPA2 and a GPU, none of which belong in
``backend/.venv``. It runs in ``backend/brain_sidecar/.venv`` (``brain_sidecar.sh setup``), in a free Colab T4
(``colab/MarketMirror_TRIBE_v2.ipynb``) or in the owner's own private Hugging Face Space (``space/``).
MarketMirror talks to it over HTTP (``app/services/brain_response.py``, ``MM_BRAIN_RESPONSE_URL``).

API (JSON):

* ``GET  /health`` -> ``{"ok": true, "model", "license", "loaded", "device", "auth"}`` (no token needed)
* ``GET  /jobs/<id>`` -> ``{"ok": true, "status": "running"|"done"|"failed", "summary"?, "error"?}`` (token needed)
* ``POST /predict`` with ``Authorization: Bearer <MM_TRIBE_TOKEN>`` (or ``X-MM-Tribe-Token: <MM_TRIBE_TOKEN>``,
  for hosts such as a private Hugging Face Space whose Authorization header carries the HF token) when a token is
  set, body one of
  ``{"kind": "video"|"audio", "data_b64": "...", "filename": "ad.mp4"}`` (uploaded bytes),
  ``{"kind": "video"|"audio"|"text", "path": "/abs/file"}`` (a file on this machine; off unless
  ``MM_TRIBE_ALLOW_PATHS=1``) or ``{"kind": "text", "text": "caption"}``
  -> ``{"ok": true, "summary": {...}}``. Add ``"async": true`` to get ``{"ok": true, "job": id}`` at once and poll
  ``/jobs/<id>``: tunnels such as Cloudflare quick tunnels cut a request after about 100 s, and a video on a T4
  can take longer. Raw vertices are never returned.

Summary: per-second mean response of anatomical groups from nilearn's Destrieux surface atlas (fsaverage5):
visual areas (occipital), hearing areas (transverse and superior temporal), language areas (inferior frontal,
angular / supramarginal, middle temporal) and the whole cortex; each z-scored within the clip, with its peak seconds,
plus the duration, model id, license and the lag note.

Environment: ``MM_TRIBE_HOST`` (default 127.0.0.1), ``MM_TRIBE_PORT`` (7860), ``MM_TRIBE_TOKEN`` (required for a
non-loopback host), ``MM_TRIBE_MODEL`` (facebook/tribev2), ``MM_TRIBE_CACHE`` (./cache), ``MM_TRIBE_MAX_MB`` (200),
``MM_TRIBE_ALLOW_PATHS`` (0). Only the stdlib is imported at module level; numpy, nilearn and tribev2 load lazily,
so tests can drive this file with a fake predictor.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import json
import os
import re
import sys
import tempfile
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

MODEL_ID = os.environ.get("MM_TRIBE_MODEL", "facebook/tribev2")
LICENSE = "CC BY-NC 4.0 (noncommercial)"
LAG_NOTE = ("TRIBE v2 shifts its predictions 5 s earlier to make up for the slow blood-flow response, so the seconds "
            "line up with the ad; treat each peak as accurate to a few seconds.")
LABEL = ("Predicted for an average viewer by Meta's TRIBE v2 research model (noncommercial license). It predicts brain "
         "activity, not attention, feelings, memory or buying. Not validated for ads.")
PARCELLATION = "Destrieux surface atlas (nilearn, fsaverage5)"
KINDS = ("video", "audio", "text")
SUFFIX = {"video": (".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"),
          "audio": (".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac"),
          "text": (".txt",)}

# Destrieux label prefixes per group (names as nilearn spells them, without the hemisphere).
GROUPS: Dict[str, Dict[str, Any]] = {
    "visual": {"label": "visual areas", "prefixes": (
        "G_cuneus", "G_occipital_middle", "G_occipital_sup", "G_and_S_occipital_inf", "G_oc-temp_med-Lingual",
        "Pole_occipital", "S_calcarine", "S_oc_middle_and_Lunatus", "S_oc_sup_and_transversal", "S_occipital_ant",
        "S_oc-temp_med_and_Lingual")},
    "hearing": {"label": "hearing areas", "prefixes": (
        "G_temp_sup-G_T_transv", "S_temporal_transverse", "G_temp_sup-Plan_tempo", "G_temp_sup-Lateral")},
    "language": {"label": "language areas", "prefixes": (
        "G_front_inf-Opercular", "G_front_inf-Triangul", "G_front_inf-Orbital", "G_pariet_inf-Angular",
        "G_pariet_inf-Supramar", "G_temporal_middle")},
    "cortex": {"label": "whole cortex", "prefixes": None},
}
NON_CORTEX = ("Unknown", "Medial_wall")


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# Parcellation and summary (pure; numpy only)
# ---------------------------------------------------------------------------

def _label_name(raw: Any) -> str:
    return raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw)


def group_vertices(labels: Sequence[Any], map_left: Sequence[int], map_right: Sequence[int],
                   n_vertices: int) -> Tuple[Dict[str, List[int]], List[str]]:
    """Vertex indices per group, assuming TRIBE orders the left hemisphere first, then the right (fsaverage5:
    10242 + 10242). Returns ({group: indices}, notes)."""
    names = [_label_name(x) for x in labels]
    left, right = list(map_left), list(map_right)
    notes: List[str] = []
    if n_vertices == len(left) + len(right):
        parcel = left + right
    elif n_vertices == len(left):
        parcel = left
        notes.append("Only one hemisphere's worth of vertices; the left-hemisphere atlas was used.")
    else:
        notes.append(f"The prediction has {n_vertices} vertices, not the {len(left) + len(right)} of fsaverage5; "
                     "only the whole-cortex mean is reported.")
        return {"cortex": list(range(n_vertices))}, notes
    out: Dict[str, List[int]] = {}
    for key, spec in GROUPS.items():
        if spec["prefixes"] is None:
            idx = [i for i, lab in enumerate(parcel) if 0 <= lab < len(names) and names[lab] not in NON_CORTEX]
        else:
            wanted = {j for j, n in enumerate(names) if n.startswith(spec["prefixes"])}
            idx = [i for i, lab in enumerate(parcel) if lab in wanted]
        if idx:
            out[key] = idx
        else:
            notes.append(f"No atlas vertices matched {spec['label']}.")
    return out, notes


def _windows(z: Sequence[float], seconds: Sequence[float], threshold: float = 1.0, top: int = 3) -> List[Dict[str, Any]]:
    """Runs of seconds at or above `threshold` z, strongest first; the single top second when nothing clears it."""
    runs: List[Tuple[int, int]] = []
    start = None
    for i, v in enumerate(z):
        if v is not None and v >= threshold:
            start = i if start is None else start
        elif start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(z) - 1))
    if not runs and len(z):
        best = max(range(len(z)), key=lambda i: z[i])
        runs = [(best, best)]
    out = []
    for a, b in runs:
        peak = max(range(a, b + 1), key=lambda i: z[i])
        out.append({"start": float(seconds[a]), "end": float(seconds[b]), "peak": float(seconds[peak]),
                    "z": round(float(z[peak]), 2)})
    out.sort(key=lambda w: -w["z"])
    return out[:top]


def summarize(preds: Any, seconds: Optional[Sequence[float]], groups: Dict[str, List[int]], *,
              kind: str = "video", notes: Optional[List[str]] = None, hz: float = 1.0) -> Dict[str, Any]:
    """Compact summary of a (n_timesteps, n_vertices) prediction: group means z-scored within the clip."""
    import numpy as np
    arr = np.asarray(preds, dtype=float)
    if arr.ndim != 2 or arr.shape[0] < 1:
        raise ValueError("predictions must be a 2-D (timesteps, vertices) array")
    n_t, n_v = arr.shape
    secs = [float(s) for s in (seconds if seconds is not None and len(seconds) == n_t else [i / hz for i in range(n_t)])]
    step = (secs[1] - secs[0]) if n_t > 1 else 1.0 / hz
    out_groups: Dict[str, Any] = {}
    for key, idx in groups.items():
        idx = [i for i in idx if 0 <= i < n_v]
        if not idx:
            continue
        mean = arr[:, idx].mean(axis=1)
        sd = float(mean.std())
        z = (mean - mean.mean()) / sd if sd > 1e-12 else np.zeros_like(mean)
        zl = [round(float(v), 3) for v in z]
        out_groups[key] = {"label": GROUPS.get(key, {}).get("label", key), "vertices": len(idx), "z": zl,
                           "raw_mean": round(float(mean.mean()), 5), "raw_sd": round(sd, 5),
                           "peaks": _windows(zl, secs)}
    return {"model": MODEL_ID, "license": LICENSE, "lag_note": LAG_NOTE, "label": LABEL, "parcellation": PARCELLATION,
            "kind": kind, "duration_s": round(secs[-1] + step, 2) if secs else 0.0,
            "hz": round(1.0 / step, 3) if step else hz,
            "n_timesteps": n_t, "n_vertices": n_v, "seconds": [round(s, 2) for s in secs], "groups": out_groups,
            "scale": "z-scored within this clip: 0 is the clip's own average, so compare shapes, not levels across ads",
            "notes": list(notes or [])}


def segment_seconds(segments: Any, n: int) -> Optional[List[float]]:
    """Start times from TRIBE's `segments` when they carry them (attribute or key start/onset); else None."""
    try:
        items = list(segments)
    except TypeError:
        return None
    if len(items) != n:
        return None
    out = []
    for s in items:
        v = None
        for k in ("start", "onset", "time", "t"):
            v = s.get(k) if isinstance(s, dict) else getattr(s, k, None)
            if v is not None:
                break
        if v is None:
            return None
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            return None
    return out


# ---------------------------------------------------------------------------
# The real model (lazy) and the atlas (lazy)
# ---------------------------------------------------------------------------

class TribePredictor:
    """Loads TRIBE v2 on first use. predict(kind, path) -> (preds, seconds or None)."""

    def __init__(self, model_id: str = MODEL_ID, cache: Optional[str] = None):
        self.model_id = model_id
        self.cache = cache or os.environ.get("MM_TRIBE_CACHE", "./cache")
        self._model = None
        self._lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def device(self) -> str:
        try:
            import torch
            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:  # noqa: BLE001 - torch missing: not set up
            return "unknown"

    def _load(self):
        if self._model is None:
            from pathlib import Path
            try:
                from tribev2.demo_utils import TribeModel
            except ImportError:
                from tribev2 import TribeModel
            self._model = TribeModel.from_pretrained(self.model_id, cache_folder=Path(self.cache))
        return self._model

    def predict(self, kind: str, path: str):
        with self._lock:        # one GPU job at a time
            model = self._load()
            df = model.get_events_dataframe(**{f"{kind}_path": path})
            preds, segments = model.predict(events=df)
        try:
            preds = preds.detach().cpu().numpy()
        except AttributeError:
            pass
        return preds, segment_seconds(segments, len(preds))


_ATLAS: Dict[str, Any] = {}


def destrieux() -> Tuple[List[Any], List[int], List[int]]:
    if not _ATLAS:
        from nilearn import datasets
        atlas = datasets.fetch_atlas_surf_destrieux()
        _ATLAS.update(labels=list(atlas["labels"]), left=[int(x) for x in atlas["map_left"]],
                      right=[int(x) for x in atlas["map_right"]])
    return _ATLAS["labels"], _ATLAS["left"], _ATLAS["right"]


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _max_bytes() -> int:
    try:
        return int(float(os.environ.get("MM_TRIBE_MAX_MB", "200")) * 1024 * 1024)
    except ValueError:
        return 200 * 1024 * 1024


def _safe_suffix(kind: str, filename: str) -> str:
    ext = os.path.splitext(str(filename or ""))[1].lower()
    return ext if ext in SUFFIX[kind] else SUFFIX[kind][0]


def run_predict(body: Dict[str, Any], predictor,
                atlas: Callable[[], Tuple[List[Any], List[int], List[int]]]) -> Dict[str, Any]:
    kind = str(body.get("kind") or "").lower()
    if kind not in KINDS:
        raise ValueError("kind must be video, audio or text")
    tmp = None
    try:
        if body.get("path"):
            if not _env_flag("MM_TRIBE_ALLOW_PATHS"):
                raise ValueError("local paths are off on this server (MM_TRIBE_ALLOW_PATHS=1); upload the bytes instead")
            path = os.path.abspath(str(body["path"]))
            if not os.path.isfile(path) or not path.lower().endswith(SUFFIX[kind]):
                raise ValueError(f"no {kind} file at that path")
        elif kind == "text" and isinstance(body.get("text"), str):
            text = body["text"].strip()
            if not text:
                raise ValueError("text is empty")
            fd, tmp = tempfile.mkstemp(suffix=".txt")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text[:20000])
            path = tmp
        elif isinstance(body.get("data_b64"), str):
            try:
                data = base64.b64decode(body["data_b64"], validate=True)
            except (binascii.Error, ValueError):
                raise ValueError("data_b64 is not valid base64")
            if not data:
                raise ValueError("the upload is empty")
            if len(data) > _max_bytes():
                raise ValueError(f"upload larger than {_max_bytes() // (1024 * 1024)} MB")
            fd, tmp = tempfile.mkstemp(suffix=_safe_suffix(kind, body.get("filename") or ""))
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            path = tmp
        else:
            raise ValueError("send data_b64 (+ filename), text, or path")
        preds, seconds = predictor.predict(kind, path)
        labels, left, right = atlas()
        n_v = len(preds[0]) if len(preds) else 0
        groups, notes = group_vertices(labels, left, right, n_v)
        if seconds is None:
            notes.append("TRIBE gave no segment times; seconds assume 1 Hz from the start of the clip.")
        return summarize(preds, seconds, groups, kind=kind, notes=notes)
    finally:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)


class Jobs:
    """Background predictions for clients behind a tunnel with a short request timeout. Keeps the last 50."""

    def __init__(self, keep: int = 50):
        self.keep = keep
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def submit(self, fn: Callable[[], Dict[str, Any]]) -> str:
        import secrets
        job_id = secrets.token_hex(8)
        with self._lock:
            self._jobs[job_id] = {"status": "running"}
            while len(self._jobs) > self.keep:
                self._jobs.pop(next(iter(self._jobs)))

        def work():
            try:
                result = {"status": "done", "summary": fn()}
            except ValueError as e:
                result = {"status": "failed", "error": str(e)}
            except Exception as e:  # noqa: BLE001 - reported through the job
                traceback.print_exc()
                result = {"status": "failed", "error": f"{type(e).__name__}: {str(e)[:300]}"}
            with self._lock:
                if job_id in self._jobs:
                    self._jobs[job_id] = result

        threading.Thread(target=work, daemon=True).start()
        return job_id

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None


def make_handler(predictor, atlas, token: Optional[str]):
    expected = (token or "").strip()
    jobs = Jobs()

    class Handler(BaseHTTPRequestHandler):
        server_version = "MarketMirrorTribe/1"

        def log_message(self, fmt, *args):  # short lines; headers (which carry the token) are never logged
            sys.stderr.write(f"tribe: {getattr(self, 'command', '')} {str(getattr(self, 'path', '')).split('?')[0][:120]}\n")

        def _send(self, status: int, payload: Dict[str, Any]):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self) -> bool:
            if not expected:
                return True
            # X-MM-Tribe-Token for hosts whose Authorization header carries their own token (a private HF Space)
            candidates = [self.headers.get("X-MM-Tribe-Token") or ""]
            m = re.match(r"(?i)bearer\s+(.+)", (self.headers.get("Authorization") or "").strip())
            if m:
                candidates.append(m.group(1))
            return any(c.strip() and hmac.compare_digest(c.strip().encode(), expected.encode()) for c in candidates)

        def do_GET(self):  # noqa: N802
            route = self.path.split("?")[0]
            if route.startswith("/jobs/"):
                if not self._authorized():
                    return self._send(401, {"ok": False, "error": "missing or wrong bearer token"})
                job = jobs.get(route[len("/jobs/"):])
                return self._send(200, {"ok": True, **job}) if job else self._send(404, {"ok": False, "error": "no such job"})
            if route != "/health":
                return self._send(404, {"ok": False, "error": "not found"})
            self._send(200, {"ok": True, "model": predictor.model_id, "license": LICENSE, "loaded": predictor.loaded,
                             "device": predictor.device(), "auth": bool(expected), "label": LABEL})

        def do_POST(self):  # noqa: N802
            if self.path.split("?")[0] != "/predict":
                return self._send(404, {"ok": False, "error": "not found"})
            if not self._authorized():
                return self._send(401, {"ok": False, "error": "missing or wrong bearer token"})
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if length <= 0:
                return self._send(400, {"ok": False, "error": "empty body"})
            if length > _max_bytes() * 4 // 3 + 4096:
                return self._send(413, {"ok": False, "error": f"upload larger than {_max_bytes() // (1024 * 1024)} MB"})
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(body, dict):
                    raise ValueError("body must be a JSON object")
                if body.get("async"):
                    return self._send(202, {"ok": True, "job": jobs.submit(lambda: run_predict(body, predictor, atlas))})
                summary = run_predict(body, predictor, atlas)
            except ValueError as e:
                return self._send(400, {"ok": False, "error": str(e)})
            except Exception as e:  # noqa: BLE001 - report, keep serving
                traceback.print_exc()
                return self._send(500, {"ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}"})
            self._send(200, {"ok": True, "summary": summary})

    return Handler


def _loopback(host: str) -> bool:
    return host in ("127.0.0.1", "localhost", "::1")


def make_server(host: str = "127.0.0.1", port: int = 7860, predictor=None, atlas=None,
                token: Optional[str] = None) -> ThreadingHTTPServer:
    token = os.environ.get("MM_TRIBE_TOKEN", "") if token is None else token
    if not _loopback(host) and not token:
        raise SystemExit("refusing to listen on a non-loopback host without MM_TRIBE_TOKEN")
    return ThreadingHTTPServer((host, port), make_handler(predictor or TribePredictor(), atlas or destrieux, token))


def main() -> None:
    host = os.environ.get("MM_TRIBE_HOST", "127.0.0.1")
    port = int(os.environ.get("MM_TRIBE_PORT", "7860"))
    server = make_server(host, port)
    print(json.dumps({"ok": True, "url": f"http://{host}:{port}", "model": MODEL_ID, "license": LICENSE,
                      "auth": bool(os.environ.get("MM_TRIBE_TOKEN"))}), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
