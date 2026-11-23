"""Token-protected prompt templates; no code download or execution."""
from flask import Blueprint, jsonify, request
from .setup import _guard
from ..services import workspace_skills as service

workspace_skills_bp = Blueprint("workspace_skills", __name__)


@workspace_skills_bp.before_request
def protect():
    denied = _guard(write=request.method != "GET")
    if denied:
        return denied
    if request.content_length and request.content_length > 200000:
        return jsonify(success=False, error="Skill is too large"), 413


@workspace_skills_bp.after_request
def private(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@workspace_skills_bp.errorhandler(ValueError)
def invalid(error):
    return jsonify(success=False, error=str(error)), 400


@workspace_skills_bp.errorhandler(LookupError)
def missing(error):
    return jsonify(success=False, error=str(error)), 404


@workspace_skills_bp.route("/api/workspace/skills", methods=["GET", "POST"])
def skills():
    if request.method == "GET":
        return jsonify(success=True, data=service.list_skills())
    return jsonify(success=True, data=service.create_skill(request.get_json(silent=True))), 201


@workspace_skills_bp.route("/api/workspace/skills/<skill_id>", methods=["GET", "PATCH", "DELETE"])
def skill(skill_id):
    if request.method == "GET":
        return jsonify(success=True, data=service.get_skill(skill_id))
    if request.method == "DELETE":
        service.delete_skill(skill_id)
        return jsonify(success=True, data={"id": skill_id, "deleted": True})
    return jsonify(success=True, data=service.update_skill(skill_id, request.get_json(silent=True)))
