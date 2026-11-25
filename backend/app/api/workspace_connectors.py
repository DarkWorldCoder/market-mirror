"""Authenticated owner-managed remote MCP configuration."""
from flask import Blueprint, jsonify, request
from .setup import _guard
from ..services import workspace_connectors as service

workspace_connectors_bp = Blueprint("workspace_connectors", __name__)


@workspace_connectors_bp.before_request
def protect():
    denied = _guard(write=request.method != "GET")
    if denied:
        return denied
    if request.content_length and request.content_length > 30000:
        return jsonify(success=False, error="Connector settings are too large"), 413


@workspace_connectors_bp.after_request
def private(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@workspace_connectors_bp.errorhandler(ValueError)
def invalid(error):
    return jsonify(success=False, error=str(error)), 400


@workspace_connectors_bp.errorhandler(LookupError)
def missing(error):
    return jsonify(success=False, error=str(error)), 404


@workspace_connectors_bp.route("/api/workspace/connectors", methods=["GET", "POST"])
def connectors():
    if request.method == "GET":
        return jsonify(success=True, data=service.list_connectors())
    return jsonify(success=True, data=service.save(request.get_json(silent=True))), 201


@workspace_connectors_bp.route("/api/workspace/connectors/<connector_id>", methods=["PATCH", "DELETE"])
def connector(connector_id):
    if request.method == "DELETE":
        service.remove(connector_id)
        return jsonify(success=True, data={"id": connector_id, "deleted": True})
    return jsonify(success=True, data=service.save(request.get_json(silent=True), connector_id))


@workspace_connectors_bp.post("/api/workspace/connectors/test")
def test_draft():
    """Check a server before saving it. With ?connector=<id>, a blank token reuses that connector's saved token."""
    return jsonify(success=True, data=service.test_draft(request.get_json(silent=True), request.args.get("connector") or None))


@workspace_connectors_bp.get("/api/workspace/mcp-setup")
def mcp_setup():
    """Copy-ready settings for adding MarketMirror's own MCP server to other AI apps. Paths only, no secrets."""
    from ..services.workspace_mcp_setup import snippets
    return jsonify(success=True, data=snippets())


@workspace_connectors_bp.post("/api/workspace/connectors/<connector_id>/discover")
def discover(connector_id):
    return jsonify(success=True, data=service.discover(connector_id))
