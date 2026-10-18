"""
Product understanding API (MarketMirror).

    POST /api/graph/project/<project_id>/profile   {url?, ads_summary?, refresh?}  -> product_profile.json (synchronous, one LLM call)
    GET  /api/graph/project/<project_id>/profile
    POST /api/graph/profile                        {text, url?, ads_summary?, name?}  -> a profile without a project (quickstart --from-docs)

The profile is saved next to the project's files. When a project has no graph yet, a short factual episode
built from the profile is appended to the extracted text, so the graph build creates Brand / Product /
Objection / Competitor / Channel nodes (the market map) from it.
"""

import traceback

from flask import jsonify, request

from . import graph_bp
from ..config import Config
from ..models.project import ProjectManager
from ..services import product_profile as pp
from ..utils.logger import get_logger

logger = get_logger('mirofish.api.product')
MARKER = "\n\n## Product profile (generated)\n"


def _client():
    from openai import OpenAI
    if not Config.LLM_API_KEY:
        raise ValueError("LLM_API_KEY is not configured")
    return OpenAI(api_key=Config.LLM_API_KEY, base_url=Config.LLM_BASE_URL)


def build_profile(text: str, url: str = "", ads_summary=None, requirement: str = "", name_hint: str = ""):
    url_text = pp.fetch_url_text(url) if url else ""
    material = pp.compact_material(text or "", url_text, ads_summary, requirement)
    if not material.strip():
        raise ValueError("nothing to read: upload documents or give a url")
    profile = pp.generate(_client(), Config.LLM_MODEL_NAME, material, name_hint)
    profile["sources"] = {"documents": bool(text), "url": url or None, "url_chars": len(url_text), "ads": bool(ads_summary)}
    return profile


@graph_bp.route('/project/<project_id>/profile', methods=['GET'])
def get_profile(project_id: str):
    project = ProjectManager.get_project(project_id)
    if not project:
        return jsonify({"success": False, "error": f"project not found: {project_id}"}), 404
    profile = pp.load(ProjectManager._get_project_dir(project_id))
    if not profile:
        return jsonify({"success": False, "error": "no product profile yet: POST to this URL to create it"}), 404
    return jsonify({"success": True, "data": profile})


@graph_bp.route('/project/<project_id>/profile', methods=['POST'])
def create_profile(project_id: str):
    project = ProjectManager.get_project(project_id)
    if not project:
        return jsonify({"success": False, "error": f"project not found: {project_id}"}), 404
    data = request.get_json(silent=True) or {}
    project_dir = ProjectManager._get_project_dir(project_id)
    existing = pp.load(project_dir)
    if existing and not data.get("refresh"):
        return jsonify({"success": True, "data": existing, "cached": True})
    try:
        text = ProjectManager.get_extracted_text(project_id) or ""
        if MARKER in text:
            text = text.split(MARKER, 1)[0]
        profile = build_profile(text, str(data.get("url") or ""), data.get("ads_summary"),
                                project.simulation_requirement or "", str(data.get("name") or project.name or ""))
        pp.save(project_dir, profile)
        # market-map nodes: add the profile's facts to the text the graph is built from (before the build)
        if not project.graph_id and text:
            ProjectManager.save_extracted_text(project_id, text + MARKER + pp.graph_episode(profile))
            profile["graph_episode_added"] = True
        return jsonify({"success": True, "data": profile})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:  # noqa: BLE001
        logger.error(f"profile failed: {e}\n{traceback.format_exc()}")
        return jsonify({"success": False, "error": str(e)}), 500


@graph_bp.route('/profile', methods=['POST'])
def profile_from_text():
    """Profile without a project: {text?, url?, ads_summary?, name?, requirement?}."""
    data = request.get_json(silent=True) or {}
    try:
        profile = build_profile(str(data.get("text") or ""), str(data.get("url") or ""), data.get("ads_summary"),
                                str(data.get("requirement") or ""), str(data.get("name") or ""))
        profile["quickstart_answers"] = pp.quickstart_answers(profile)
        return jsonify({"success": True, "data": profile})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:  # noqa: BLE001
        logger.error(f"profile failed: {e}\n{traceback.format_exc()}")
        return jsonify({"success": False, "error": str(e)}), 500
