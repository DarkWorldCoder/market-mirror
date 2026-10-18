"""
Feed story API: the post-by-post social feed of a simulation.

    GET /api/simulation/<simulation_id>/feed-story[?platform=twitter|reddit&round=N&refresh=1]

The story is built from the OASIS databases and actions.jsonl on first request and cached
as <sim>/feed_story.json. The cache is rebuilt when any database or actions.jsonl is newer
than it, or when ?refresh=1 is passed. `platform` and `round` filter the response only;
the cache always holds every platform and round.
"""

import json
import os

from flask import jsonify, request

from . import simulation_bp
from ..services.feed_story import DB_FILES, PLATFORMS, build_feed_story
from ..services.simulation_manager import SimulationManager
from ..utils.logger import get_logger

logger = get_logger('mirofish.api.feed')

FEED_STORY_FILE = "feed_story.json"


def _sim_dir(simulation_id: str) -> str:
    manager = SimulationManager()
    if not manager.get_simulation(simulation_id):
        raise LookupError(f"simulation not found: {simulation_id}")
    return manager._get_simulation_dir(simulation_id)


def _sources(sim_dir: str):
    for platform in PLATFORMS:
        for rel in (DB_FILES[platform], os.path.join(platform, "actions.jsonl")):
            path = os.path.join(sim_dir, rel)
            if os.path.exists(path):
                yield path


def _cache_is_fresh(sim_dir: str) -> bool:
    cache = os.path.join(sim_dir, FEED_STORY_FILE)
    if not os.path.exists(cache):
        return False
    try:
        cached_at = os.path.getmtime(cache)
        return all(os.path.getmtime(p) <= cached_at for p in _sources(sim_dir))
    except OSError:
        return False


def load_or_build(simulation_id: str, refresh: bool = False):
    """The cached story, rebuilt when a source is newer. Raises LookupError for an unknown
    simulation and FileNotFoundError when no platform database exists yet."""
    sim_dir = _sim_dir(simulation_id)
    cache = os.path.join(sim_dir, FEED_STORY_FILE)
    if not refresh and _cache_is_fresh(sim_dir):
        try:
            with open(cache, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
    if not any(os.path.exists(os.path.join(sim_dir, DB_FILES[p])) for p in PLATFORMS):
        raise FileNotFoundError("no simulation database yet: start the simulation first")
    config = SimulationManager().get_simulation_config(simulation_id) or {}
    story = build_feed_story(sim_dir, config)
    tmp = cache + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(story, f, ensure_ascii=False, indent=2)
        os.replace(tmp, cache)
    except OSError as e:  # still answer the request
        logger.warning(f"could not cache feed story for {simulation_id}: {e}")
    return story


def _filter(story, platform, rnd):
    if platform:
        story = {**story, "platforms": {k: v for k, v in story["platforms"].items() if k == platform},
                 "brand_posts": [b for b in story["brand_posts"] if b.get("platform") == platform]}
    if rnd is not None:
        platforms = {}
        for k, v in story["platforms"].items():
            platforms[k] = {**v, "posts": [p for p in v["posts"] if p.get("round") == rnd],
                            "rounds": [r for r in v["rounds"] if r.get("round") == rnd]}
        story = {**story, "platforms": platforms,
                 "brand_posts": [b for b in story["brand_posts"] if b.get("round") == rnd]}
    return story


@simulation_bp.route('/<simulation_id>/feed-story', methods=['GET'])
def feed_story(simulation_id: str):
    platform = (request.args.get("platform") or "").strip().lower() or None
    if platform and platform not in PLATFORMS:
        return jsonify({"success": False, "error": f"platform must be one of {', '.join(PLATFORMS)}"}), 400
    rnd = request.args.get("round")
    if rnd not in (None, ""):
        try:
            rnd = int(rnd)
        except ValueError:
            return jsonify({"success": False, "error": "round must be an integer"}), 400
    else:
        rnd = None
    refresh = str(request.args.get("refresh") or "").lower() in ("1", "true", "yes")
    try:
        story = load_or_build(simulation_id, refresh=refresh)
    except LookupError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    except FileNotFoundError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    except Exception as e:  # noqa: BLE001 - reported to the client
        logger.error(f"feed story failed for {simulation_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    return jsonify({"success": True, "data": _filter(story, platform, rnd)})
