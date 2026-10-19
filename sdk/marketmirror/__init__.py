"""marketmirror - a thin Python client for the MarketMirror backend and CLI.

    from marketmirror import MarketMirror
    mm = MarketMirror("http://localhost:5001", repo="/path/to/market-mirror")
    profile = mm.understand(text=open("brief.md").read(), url="https://brand.example")
    run = mm.market_test("scenarios/acme/market_test.json")        # wraps the CLI (background-safe, prints JSON)
    print(mm.results("mirofish_runs/acme")["decision"])
    pred = mm.predict(summary=..., feed_test=..., brand="Acme", targets={"ctr": 2})

REST methods map 1:1 to docs/API.md; CLI wrappers run `backend/claude_cli/mirofish.py` from the repo. Only `requests` is needed.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from typing import Any, Dict, List, Optional

import requests

__version__ = "0.3.0"


class MarketMirrorError(RuntimeError):
    pass


class MarketMirror:
    def __init__(self, base_url: str = "http://localhost:5001", repo: Optional[str] = None, timeout: float = 120):
        self.base_url = base_url.rstrip("/")
        self.repo = repo or os.environ.get("MARKET_MIRROR_HOME") or os.getcwd()
        self.timeout = timeout
        self.s = requests.Session()

    # ---- transport ----
    def _call(self, method: str, path: str, **kw) -> Any:
        kw.setdefault("timeout", self.timeout)
        r = self.s.request(method, self.base_url + path, **kw)
        try:
            body = r.json()
        except ValueError:
            raise MarketMirrorError(f"{method} {path}: HTTP {r.status_code}: {r.text[:200]}")
        if not body.get("success"):
            raise MarketMirrorError(f"{method} {path}: {body.get('error')}")
        return body.get("data")

    def wait(self, task_id: str, interval: float = 3, timeout: float = 3600) -> Dict[str, Any]:
        t0 = time.time()
        while True:
            st = self._call("POST", "/api/simulation/market-task/status", json={"task_id": task_id})
            if st.get("status") in ("completed", "failed"):
                if st["status"] == "failed":
                    raise MarketMirrorError(f"task {task_id} failed: {st.get('error') or st.get('message')}")
                return st
            if time.time() - t0 > timeout:
                raise MarketMirrorError(f"task {task_id} timed out")
            time.sleep(interval)

    # ---- understanding and research ----
    def understand(self, text: str = "", url: str = "", ads_summary: Optional[Dict[str, Any]] = None, name: str = "",
                   project_id: Optional[str] = None) -> Dict[str, Any]:
        if project_id:
            return self._call("POST", f"/api/graph/project/{project_id}/profile", json={"url": url, "ads_summary": ads_summary, "name": name})
        return self._call("POST", "/api/graph/profile", json={"text": text, "url": url, "ads_summary": ads_summary, "name": name})

    def attach_voices(self, project_id: str, voices: List[Dict[str, Any]]) -> Dict[str, Any]:
        return self._call("PUT", f"/api/graph/project/{project_id}/voices", json={"voices": voices})

    # ---- tests on a prepared simulation ----
    def website_test(self, simulation_id: str, spec: Dict[str, Any], wait: bool = True) -> Dict[str, Any]:
        """Real-browser synthetic visitor journeys; supplied DOM checks verify outcomes."""
        task = self._call("POST", "/api/simulation/website-test", json={"simulation_id": simulation_id, "spec": spec})
        if not wait:
            return task
        self.wait(task["task_id"])
        return self._call("GET", f"/api/simulation/{simulation_id}/website-test", params={"run_id": task["run_id"]})

    def feed_test(self, simulation_id: str, creatives: List[Dict[str, Any]], landing: Optional[Dict[str, Any]] = None,
                  benchmarks: Optional[Dict[str, Any]] = None, seeds: int = 1, exposures: int = 2, wait: bool = True) -> Dict[str, Any]:
        t = self._call("POST", "/api/simulation/feed-test", json={"simulation_id": simulation_id, "creatives": creatives, "landing": landing,
                                                                 "benchmarks": benchmarks, "seeds": seeds, "exposures": exposures})
        if not wait:
            return t
        self.wait(t["task_id"])
        return self._call("GET", f"/api/simulation/{simulation_id}/feed-test")

    def email_test(self, simulation_id: str, emails: List[Dict[str, Any]], list_size: Optional[int] = None,
                   benchmarks: Optional[Dict[str, Any]] = None, wait: bool = True) -> Dict[str, Any]:
        t = self._call("POST", "/api/simulation/email-test", json={"simulation_id": simulation_id, "emails": emails, "list_size": list_size, "benchmarks": benchmarks})
        if not wait:
            return t
        self.wait(t["task_id"])
        return self._call("GET", f"/api/simulation/{simulation_id}/email-test")

    def pitch(self, simulation_id: str, script: str, rebuttals: Optional[Dict[str, str]] = None, product: str = "", channel: str = "message",
              wait: bool = True) -> Dict[str, Any]:
        t = self._call("POST", "/api/simulation/pitch", json={"simulation_id": simulation_id, "script": script, "rebuttals": rebuttals, "product": product, "channel": channel})
        if not wait:
            return t
        self.wait(t["task_id"])
        return self._call("GET", f"/api/simulation/{simulation_id}/pitch")

    def interview(self, simulation_id: str, interviews: List[Dict[str, Any]], platform: str = "reddit", timeout: int = 600) -> Dict[str, Any]:
        return self._call("POST", "/api/simulation/interview/batch", json={"simulation_id": simulation_id, "interviews": interviews, "platform": platform, "timeout": timeout},
                          timeout=timeout + 60)

    def events(self, simulation_id: str, posts: Optional[List[Dict[str, Any]]] = None, events: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        return self._call("PUT", f"/api/simulation/{simulation_id}/events", json={"posts": posts or [], "events": events or []})

    def push_context(self, simulation_id: str, text: str, source: str = "", round_: Optional[int] = None) -> Dict[str, Any]:
        body: Dict[str, Any] = {"text": text, "source": source}
        if round_ is not None:
            body["round"] = round_
        return self._call("PUT", f"/api/simulation/{simulation_id}/context", json=body)

    def feed_story(self, simulation_id: str) -> Dict[str, Any]:
        return self._call("GET", f"/api/simulation/{simulation_id}/feed-story")

    # ---- analysis and reliability ----
    def ideas(self, brand: str = "", ads: Optional[List[Dict[str, Any]]] = None, run_summary: Optional[Dict[str, Any]] = None,
              profile: Optional[Dict[str, Any]] = None, n: int = 8) -> Dict[str, Any]:
        return self._call("POST", "/api/simulation/ideas", json={"brand": brand, "ads": ads or [], "run_summary": run_summary or {}, "profile": profile, "n": n}, timeout=300)

    def captions(self, brief: str, platform: str = "instagram", n: int = 6, objections: Optional[List[str]] = None) -> Dict[str, Any]:
        return self._call("POST", "/api/simulation/captions", json={"brief": brief, "platform": platform, "n": n, "objections": objections or []}, timeout=300)

    def calibrate(self, synthetic: List[Dict[str, Any]], real: List[Dict[str, Any]], key: str = "segment", field: str = "would_convert", brand: str = "") -> Dict[str, Any]:
        return self._call("POST", "/api/simulation/calibrate", json={"synthetic": synthetic, "real": real, "key": key, "field": field, "brand": brand})

    def predict(self, summary: Dict[str, Any], feed_test: Optional[Dict[str, Any]] = None, brand: str = "", targets: Optional[Dict[str, float]] = None,
                email_test: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._call("POST", "/api/simulation/predict", json={"brand": brand, "summary": summary, "feed_test": feed_test or {}, "email_test": email_test or {}, "targets": targets or {}})

    def campaign_plan(self, goal: str, budget: Dict[str, Any], profile: Optional[Dict[str, Any]] = None,
                      project_id: str = "", channels: Optional[List[str]] = None,
                      research: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._call("POST", "/api/graph/campaign-plan", json={"goal": goal, "budget": budget,
                          "profile": profile, "project_id": project_id, "channels": channels, "research": research})

    def actuals_import(self, file: str, source_type: str, mapping: Optional[Dict[str, str]] = None,
                       source: str = "", market: str = "", date: str = "", quality: str = "") -> Dict[str, Any]:
        return self._call("POST", "/api/simulation/actuals-import", json={"file": file, "source_type": source_type,
                          "mapping": mapping or {}, "source": source, "market": market, "date": date, "quality": quality})

    def holdout_backtest(self, pairs: List[Dict[str, Any]]) -> Dict[str, Any]:
        return self._call("POST", "/api/simulation/holdout-backtest", json={"pairs": pairs})

    def forecast(self, feed_test: Dict[str, Any], feed_story: Optional[Dict[str, Any]] = None, spend: Optional[float] = None, days: int = 90) -> Dict[str, Any]:
        return self._call("POST", "/api/simulation/forecast", json={"feed_test": feed_test, "feed_story": feed_story or {}, "spend": spend, "days": days})

    def store_pairs(self, brand: str, metric: str, pairs: List[Dict[str, Any]], source: str = "sdk") -> Dict[str, Any]:
        return self._call("POST", "/api/simulation/calibration-pairs", json={"brand": brand, "metric": metric, "pairs": pairs, "source": source})

    # ---- CLI wrappers (everything else: quickstart, market-test, study, research, export...) ----
    def cli(self, *args: str, timeout: float = 6 * 3600) -> Any:
        py = os.path.join(self.repo, "backend", ".venv", "bin", "python")
        if not os.path.exists(py):
            py = "python3"
        cmd = [py, os.path.join(self.repo, "backend", "claude_cli", "mirofish.py"), "--base-url", self.base_url, *args]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=self.repo)
        out = p.stdout.strip()
        try:
            data = json.loads(out) if out else {}
        except ValueError:
            data = {"raw": out}
        if p.returncode != 0:
            raise MarketMirrorError(f"mirofish {' '.join(args[:2])}: {data.get('error') or p.stderr[-400:]}")
        return data

    def quickstart(self, answers: Dict[str, Any], out: Optional[str] = None, run: bool = True) -> Any:
        path = os.path.join(self.repo, "scenarios", "_sdk_answers.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(answers, f)
        args = ["quickstart", "--answers", "@" + path] + (["--out", out] if out else []) + ([] if run else ["--no-run"])
        return self.cli(*args)

    def market_test(self, config_path: str) -> Any:
        return self.cli("market-test", config_path)

    def study(self, spec_path: str, out: Optional[str] = None) -> Any:
        return self.cli("study", "--spec", spec_path, *(["--out", out] if out else []))

    def run_test(self, simulation_id: str, spec_path: str, brand: str = "") -> Any:
        return self.cli("test", "--simulation", simulation_id, "--spec", "@" + spec_path, *(["--brand", brand] if brand else []))

    def research(self, query: str, country: str = "us", out: Optional[str] = None) -> Any:
        return self.cli("research", "--query", query, "--country", country, *(["--out", out] if out else []))

    def results(self, run_dir: str) -> Dict[str, Any]:
        """Read a marketing summary or a standalone website journey and its evidence."""
        base = run_dir if os.path.isabs(run_dir) else os.path.join(self.repo, run_dir)
        website = os.path.join(base, "website_test.json")
        if not os.path.exists(os.path.join(base, "summary.json")) and os.path.exists(website):
            with open(website, encoding="utf-8") as f:
                return json.load(f)
        with open(os.path.join(base, "summary.json"), encoding="utf-8") as f:
            out = json.load(f)
        for name in ("market_report", "pitch", "email_test", "predictions", "forecast", "ideas", "website_test"):
            p = os.path.join(base, f"{name}.json")
            if os.path.exists(p):
                with open(p, encoding="utf-8") as f:
                    out[name] = json.load(f)
        return out
