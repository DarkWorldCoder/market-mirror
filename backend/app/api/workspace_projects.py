"""Workspace project CRUD: viewers read, editors create and edit, owners or the creator archive."""
from flask import Blueprint, g, jsonify, request
from .. import auth
from ..services import workspace_projects as service

workspace_projects_bp = Blueprint("workspace_projects", __name__)


@workspace_projects_bp.before_request
def protect():
    return auth.require("viewer" if request.method == "GET" else "editor")


@workspace_projects_bp.after_request
def private(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@workspace_projects_bp.errorhandler(ValueError)
def invalid(error):
    return jsonify(success=False, error=str(error)), 400


@workspace_projects_bp.errorhandler(LookupError)
def missing(error):
    return jsonify(success=False, error=str(error)), 404


@workspace_projects_bp.route("/api/workspace/projects", methods=["GET", "POST"])
def projects():
    if request.method == "GET":
        return jsonify(success=True, data=service.list_projects())
    if request.content_length and request.content_length > 50000:
        return jsonify(success=False, error="Project is too large"), 413
    return jsonify(success=True, data=service.create_project(request.get_json(silent=True))), 201


@workspace_projects_bp.route("/api/workspace/projects/<project_id>", methods=["GET", "PATCH", "DELETE"])
def project(project_id):
    if request.method == "GET":
        return jsonify(success=True, data=service.get_project(project_id))
    if request.method == "DELETE":
        scope = g.mm_scope
        if not scope.can("owner") and service.project_creator(project_id) != scope.user_id:
            return jsonify(success=False, error="Only the person who made this project or an owner can archive it.",
                           code="role"), 403
        service.archive_project(project_id)
        return jsonify(success=True, data={"id": project_id, "archived": True})
    if request.content_length and request.content_length > 50000:
        return jsonify(success=False, error="Project is too large"), 413
    return jsonify(success=True, data=service.update_project(project_id, request.get_json(silent=True)))



@workspace_projects_bp.post("/api/workspace/projects/<project_id>/sources")
def add_source(project_id):
    if request.content_length and request.content_length > 30000:
        return jsonify(success=False, error="Source request exceeds 30 KB. Shorten or split the text."), 413
    return jsonify(success=True, data=service.add_source(project_id, request.get_json(silent=True))), 201


@workspace_projects_bp.delete("/api/workspace/projects/<project_id>/sources/<source_id>")
def remove_source(project_id, source_id):
    return jsonify(success=True, data=service.remove_source(project_id, source_id))
