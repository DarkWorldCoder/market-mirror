"""
MarketMirror API: marketing tests that run on a prepared simulation's personas.

    POST /api/simulation/feed-test             {simulation_id, creatives:[...], organic_per_feed?, max_personas?, parallel?}
    POST /api/simulation/market-task/status    {task_id}
    GET  /api/simulation/<simulation_id>/feed-test
    POST /api/simulation/analyst-panel         {simulation_id, material:{...}, analysts?, brief?}
    GET  /api/simulation/<simulation_id>/analyst-panel
    POST /api/simulation/ssr                   {items:[{id, scale, text}], temperature?}  (synchronous)

The feed test takes `seeds` (repeat with different seeds and report the spread)
or `seed` (one run with that seed).

Long work runs in a background thread tracked by the shared TaskManager; results
are saved as JSON in the simulation folder so exports can pick them up later.
"""

import json
import os
import threading
import traceback

from flask import jsonify, request

from . import simulation_bp
from ..config import Config
from ..models.task import TaskManager, TaskStatus
from ..services.simulation_manager import SimulationManager
from ..utils.logger import get_logger

logger = get_logger('mirofish.api.market')

RESULT_FILES = {"feed-test": "feed_test.json", "analyst-panel": "analyst_panel.json"}


def _client():
    from openai import OpenAI
    if not Config.LLM_API_KEY:
        raise ValueError("LLM_API_KEY is not configured")
    return OpenAI(api_key=Config.LLM_API_KEY, base_url=Config.LLM_BASE_URL)


def _sim_dir(simulation_id: str) -> str:
    manager = SimulationManager()
    if not manager.get_simulation(simulation_id):
        raise LookupError(f"simulation not found: {simulation_id}")
    return manager._get_simulation_dir(simulation_id)


def _people(simulation_id: str):
    from ..services.feed_test import people_from_simulation
    manager = SimulationManager()
    cfg = manager.get_simulation_config(simulation_id) or {}
    profiles = []
    for platform in ("reddit", "twitter"):
        try:
            profiles = manager.get_profiles(simulation_id, platform)
        except ValueError:
            profiles = []
        if profiles:
            break
    return people_from_simulation(profiles, cfg.get("persona_index") or []), cfg


def _start(kind: str, simulation_id: str, work):
    tm = TaskManager()
    task_id = tm.create_task(task_type=f"market_{kind}", metadata={"simulation_id": simulation_id})

    def run():
        try:
            tm.update_task(task_id, status=TaskStatus.PROCESSING, progress=1, message=f"{kind} started")
            result = work(lambda done, total: tm.update_task(
                task_id, progress=int(100 * done / max(total, 1)), message=f"{kind}: {done}/{total}"))
            path = os.path.join(_sim_dir(simulation_id), RESULT_FILES[kind])
            with open(path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            tm.complete_task(task_id, {"simulation_id": simulation_id, "file": path})
        except Exception as e:  # noqa: BLE001 - reported through the task
            logger.error(f"{kind} failed: {e}\n{traceback.format_exc()}")
            tm.fail_task(task_id, str(e))

    threading.Thread(target=run, daemon=True).start()
    return task_id


@simulation_bp.route('/feed-test', methods=['POST'])
def start_feed_test():
    from ..services import feed_test
    data = request.get_json() or {}
    sid = data.get("simulation_id")
    try:
        _sim_dir(sid or "")
        creatives = feed_test.normalize_creatives(data.get("creatives"))
        landing = feed_test.normalize_landing(data.get("landing"))
        people, cfg = _people(sid)
    except LookupError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    if not people:
        return jsonify({"success": False, "error": "no personas yet: prepare the simulation first"}), 400
    try:
        seed = int(data.get("seed") or 5)
        n_seeds = max(1, min(int(data.get("seeds") or 1), 10))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "seed and seeds must be integers"}), 400
    limit = data.get("max_personas")
    if isinstance(limit, int) and limit > 0:
        people = people[:limit]
    organic = max(2, min(int(data.get("organic_per_feed") or 5), 12))
    parallel = max(1, min(int(data.get("parallel") or 8), 16))
    context = json.dumps((cfg.get("persona_spec") or {}).get("segments") or [], ensure_ascii=False)[:2000]

    def work(progress):
        return feed_test.run_multi_seed(_client(), Config.LLM_MODEL_NAME, creatives, people,
                                        seeds=feed_test.seed_list(seed, n_seeds), context=context,
                                        organic_per_feed=organic, parallel=parallel, progress=progress,
                                        waves=int(data.get("waves") or 3), landing=landing,
                                        exposures=int(data.get("exposures") or 2),
                                        attention_gate=data.get("attention_gate", True) is not False,
                                        benchmarks=data.get("benchmarks") if isinstance(data.get("benchmarks"), dict) else None)

    task_id = _start("feed-test", sid, work)
    feeds = len(feed_test.assign(creatives, people))
    return jsonify({"success": True, "data": {"task_id": task_id, "simulation_id": sid, "personas": len(people),
                                              "feeds": feeds, "creatives": len(creatives), "seeds": n_seeds}})


@simulation_bp.route('/ssr', methods=['POST'])
def semantic_similarity_rating():
    """Map free-text survey answers to 5-point rating distributions (arXiv 2510.08338)."""
    from ..services import ssr
    data = request.get_json() or {}
    items = data.get("items")
    if not isinstance(items, list) or len(items) > 5000:
        return jsonify({"success": False, "error": "items must be a list of {id, scale, text} (max 5000)"}), 400
    rows = [it if isinstance(it, dict) else {} for it in items]
    try:
        temperature = float(data.get("temperature") or 1.0)
        rated = ssr.rate([(str(r.get("scale") or ""), r.get("text")) for r in rows], temperature=temperature)
    except ssr.SSRUnavailable as e:
        return jsonify({"success": False, "error": str(e)}), 503
    except (TypeError, ValueError) as e:
        return jsonify({"success": False, "error": str(e)}), 400
    embedder = ssr.get_embedder()
    return jsonify({"success": True, "data": {
        "model": getattr(embedder, "model_name", None), "anchors_version": ssr.ANCHORS_VERSION,
        "scales": list(ssr.SCALES), "temperature": temperature,
        "results": [{"id": r.get("id"), "scale": r.get("scale"), **res} for r, res in zip(rows, rated) if res]}})


@simulation_bp.route('/analyst-panel', methods=['POST'])
def start_analyst_panel():
    from ..services import analyst_panel
    data = request.get_json() or {}
    sid = data.get("simulation_id")
    try:
        _sim_dir(sid or "")
        material = analyst_panel.normalize_material(data.get("material"))
    except LookupError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    analysts = max(2, min(int(data.get("analysts") or 5), 9))
    brief = str(data.get("brief") or "")[:4000]

    def work(progress):
        return analyst_panel.run_panel(_client(), Config.LLM_MODEL_NAME, material, brief, analysts, progress=progress)

    task_id = _start("analyst-panel", sid, work)
    return jsonify({"success": True, "data": {"task_id": task_id, "simulation_id": sid, "analysts": analysts}})


@simulation_bp.route('/market-task/status', methods=['POST'])
def market_task_status():
    task_id = (request.get_json() or {}).get("task_id")
    task = TaskManager().get_task(task_id) if task_id else None
    if not task:
        return jsonify({"success": False, "error": "task not found"}), 404
    return jsonify({"success": True, "data": task.to_dict()})


@simulation_bp.route('/<simulation_id>/feed-test', methods=['GET'], defaults={"kind": "feed-test"})
@simulation_bp.route('/<simulation_id>/analyst-panel', methods=['GET'], defaults={"kind": "analyst-panel"})
def market_result(simulation_id: str, kind: str):
    if kind not in RESULT_FILES:
        return jsonify({"success": False, "error": "not found"}), 404
    try:
        path = os.path.join(_sim_dir(simulation_id), RESULT_FILES[kind])
    except LookupError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    if not os.path.exists(path):
        return jsonify({"success": False, "error": f"no {kind} result yet"}), 404
    with open(path, encoding="utf-8") as f:
        return jsonify({"success": True, "data": json.load(f)})
