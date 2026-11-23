"""Guarded public browser observations and private screenshot artifacts."""
from flask import Blueprint, jsonify, request, send_file
from .setup import _guard
from ..services import workspace_browser as service

workspace_browser_bp = Blueprint("workspace_browser", __name__)


@workspace_browser_bp.before_request
def protect():
    denied = _guard(write=request.method != "GET")
    if denied:
        return denied
    if request.content_length and request.content_length > 4000:
        return jsonify(success=False, error="Browser observation request is too large"), 413


@workspace_browser_bp.after_request
def private(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@workspace_browser_bp.post("/api/workspace/browser/observe")
def observe():
    try:
        return jsonify(success=True, data=service.observe(request.get_json(silent=True)))
    except ValueError as error:
        return jsonify(success=False, error=str(error)), 400


@workspace_browser_bp.get("/api/workspace/browser/<session_id>/image")
def image(session_id):
    try:
        frame = int(request.args.get("frame", "0"))
        return send_file(service.image_path(session_id, frame), mimetype="image/png")
    except (LookupError, ValueError):
        return jsonify(success=False, error="Browser screenshot expired or was not found"), 404
