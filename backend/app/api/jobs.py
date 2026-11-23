"""Job queue API (app/jobs): list, inspect, cancel and approve retries of background jobs.

    GET  /api/jobs                       ?status=&kind=&workspace=&subject=&limit=
    GET  /api/jobs/stats                 counts, running per provider/workspace/lane, queue wait p50/p95, workers, limits
    GET  /api/jobs/<job_id>
    POST /api/jobs/<job_id>/cancel
    POST /api/jobs/<job_id>/retry        {"approve_spend": true}   one more attempt that may spend again

A job's id is the task id the starting endpoint returned, so existing task polling keeps working.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from .. import jobs

jobs_bp = Blueprint("jobs", __name__, url_prefix="/api/jobs")

_HIDDEN = ("payload", "owner", "worker")


def _public(job: dict) -> dict:
    out = {k: v for k, v in job.items() if k not in _HIDDEN}
    out["queue_position"] = jobs.store().position(job["job_id"])
    out["can_retry"] = job["status"] in (jobs.NEEDS_APPROVAL, jobs.FAILED) and bool(job.get("handler"))
    return out


@jobs_bp.route("", methods=["GET"])
def list_jobs():
    args = request.args
    try:
        limit = int(args.get("limit") or 100)
    except ValueError:
        return jsonify({"success": False, "error": "limit must be an integer"}), 400
    status = args.get("status") or None
    if status and status not in (*jobs.ACTIVE, *jobs.TERMINAL):
        return jsonify({"success": False, "error": f"unknown status {status}"}), 400
    rows = jobs.store().list(status=status, kind=args.get("kind") or None, workspace=args.get("workspace") or None,
                             subject=args.get("subject") or None, limit=limit)
    return jsonify({"success": True, "data": [_public(j) for j in rows]})


@jobs_bp.route("/stats", methods=["GET"])
def job_stats():
    from ..jobs.limits import from_env
    data = jobs.store().stats(stale_after_s=jobs.lease_s() * 2)
    data["limits"] = from_env().to_dict()
    data["oasis"] = {"max_concurrent_runs": jobs.oasis_limit()}
    data["external_workers"] = jobs.external_workers()
    return jsonify({"success": True, "data": data})


@jobs_bp.route("/<job_id>", methods=["GET"])
def get_job(job_id: str):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"success": False, "error": "job not found"}), 404
    return jsonify({"success": True, "data": _public(job)})


@jobs_bp.route("/<job_id>/cancel", methods=["POST"])
def cancel_job(job_id: str):
    job = jobs.cancel(job_id)
    if not job:
        return jsonify({"success": False, "error": "job not found"}), 404
    return jsonify({"success": True, "data": _public(job)})


@jobs_bp.route("/<job_id>/retry", methods=["POST"])
def retry_job(job_id: str):
    body = request.get_json(silent=True) or {}
    if body.get("approve_spend") is not True:
        return jsonify({"success": False, "error": "a retry may make model calls again: send {\"approve_spend\": true}"}), 400
    job = jobs.get(job_id)
    if not job:
        return jsonify({"success": False, "error": "job not found"}), 404
    try:
        updated = jobs.approve(job_id)
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 409
    if updated is None:
        return jsonify({"success": False, "error": f"a {job['status']} job cannot be retried"}), 409
    return jsonify({"success": True, "data": _public(updated)})
