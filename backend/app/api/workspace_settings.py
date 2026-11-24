"""Local workspace settings. Provider keys are accepted but never serialized."""
from flask import Blueprint, jsonify, request
from .setup import _guard
from ..services import workspace_settings as service

workspace_settings_bp = Blueprint("workspace_settings", __name__)


@workspace_settings_bp.before_request
def protect():
    return _guard(write=request.method != "GET")


@workspace_settings_bp.after_request
def private(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@workspace_settings_bp.route("/api/workspace/settings", methods=["GET", "PUT"])
def settings():
    if request.method == "GET":
        return jsonify(success=True, data=service.state())
    if request.content_length and request.content_length > 20000:
        return jsonify(success=False, error="Settings are too large"), 413
    try:
        return jsonify(success=True, data=service.update(request.get_json(silent=True)))
    except (ValueError, TypeError) as error:
        return jsonify(success=False, error=str(error)), 400


@workspace_settings_bp.get("/api/workspace/local-models")
def local_models():
    from ..services.workspace_local_models import discover
    return jsonify(success=True, data=discover(refresh=request.args.get("refresh") == "1"))
