"""Loopback-only workflow API; all operations require the existing setup token."""
from pathlib import Path
import tempfile

from flask import Blueprint, jsonify, request, Response, send_from_directory

from .setup import _guard, _loopback
from ..services import workflows as service

workflows_bp = Blueprint("workflows", __name__)
DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"


@workflows_bp.before_request
def protect():
    if request.path.startswith("/api/workflows"):
        return _guard(write=request.method != "GET")


@workflows_bp.errorhandler(ValueError)
def bad_input(error):
    return jsonify(success=False, error=str(error)), 409 if isinstance(error, service.Conflict) else 400


@workflows_bp.errorhandler(FileNotFoundError)
def missing(error):
    return jsonify(success=False, error="Workflow not found"), 404


def body():
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise ValueError("Request body must be a JSON object")
    return value


def ok(value):
    response = jsonify(success=True, data=value)
    response.headers["Cache-Control"] = "no-store"
    return response


@workflows_bp.get("/api/workflows/meta")
def meta():
    return ok({"recipes": service.RECIPES, "provider": service.provider(),
               "demo_url": "https://darkworldcoder.github.io/market-mirror/demo/"})


@workflows_bp.post("/api/workflows/events")
def local_event():
    value = body()
    return ok(service.event(value.get("name"), value.get("workflow_id"), value.get("seconds")))


@workflows_bp.get("/api/workflows/metrics")
def local_metrics():
    return ok(service.metrics())


@workflows_bp.route("/api/workflows", methods=["GET", "POST"])
def collection():
    if request.method == "GET":
        return ok(service.listing())
    data = body()
    return ok(service.create(data.get("inputs", {}), data.get("parent_id")))


@workflows_bp.route("/api/workflows/<wid>", methods=["GET", "PUT"])
def workflow(wid):
    return ok(service.get(wid) if request.method == "GET" else service.update(wid, body().get("inputs", {})))


@workflows_bp.post("/api/workflows/<wid>/estimate")
def estimate(wid):
    return ok(service.estimate(wid, body().get("phase")))


@workflows_bp.post("/api/workflows/<wid>/approve")
def approve(wid):
    data = body()
    if data.get("approved") is not True:
        raise ValueError("Explicit approval is required")
    return ok(service.approve(wid, data.get("phase"), data.get("digest"), data.get("call_limit"),
                              retry=data.get("retry") is True))


@workflows_bp.get("/api/workflows/<wid>/results")
def results(wid):
    return ok(service.result(service.get(wid)))


@workflows_bp.put("/api/workflows/<wid>/worksheet")
def worksheet(wid):
    value = service.text(body(), "text", 30000)
    with service.locked(wid) as record:
        record["worksheet"] = value
        service.save(record)
    return ok({"saved": True})


@workflows_bp.get("/api/workflows/<wid>/evidence")
def evidence(wid):
    return Response(service.evidence_html(service.get(wid)), mimetype="text/html",
                    headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                             "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"})


@workflows_bp.post("/api/workflows/source")
def source():
    """Extract source text only: no model call, inferred facts or paid operation."""
    from ..services.cro_and_sparring import fetch_url_snapshot
    from ..utils.file_parser import FileParser
    if request.is_json:
        url = service.text(body(), "url", 2000)
        try:
            page = fetch_url_snapshot(url)
        except ValueError:
            raise ValueError("Use a public HTTP(S) product page. Private addresses are not supported.")
        except Exception:
            raise ValueError("Could not read that public page. Paste the product details instead.")
        return ok({"text": page["text"][:24000], "url": url, "method": "extracted page text; review and correct before testing"})
    upload = request.files.get("file")
    if upload is None:
        raise ValueError("Choose a PDF, Markdown or text document")
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in (".pdf", ".md", ".txt"):
        raise ValueError("Use a PDF, Markdown or text file")
    content = upload.stream.read(5 * 1024 * 1024 + 1)
    if len(content) > 5 * 1024 * 1024:
        raise ValueError("The document must be smaller than 5 MB")
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix) as stream:
            stream.write(content)
            stream.flush()
            extracted = FileParser.extract_text(stream.name)
    except Exception:
        raise ValueError("Could not read this document. Paste its text instead.")
    return ok({"text": extracted[:24000], "method": "document text; review and correct before testing"})


@workflows_bp.get("/")
@workflows_bp.get("/app")
@workflows_bp.get("/workflows/<wid>")
@workflows_bp.get("/legacy")
@workflows_bp.get("/process/<wid>")
@workflows_bp.get("/simulation/<wid>")
@workflows_bp.get("/simulation/<wid>/start")
@workflows_bp.get("/report/<wid>")
@workflows_bp.get("/interaction/<wid>")
def web_app(wid=None):
    if not _loopback():
        return Response("The MarketMirror app is available only on this computer.", status=403)
    if not (DIST / "index.html").is_file():
        return Response("Build the local app with ./mm app, then reopen it.", status=503)
    return send_from_directory(DIST, "index.html", max_age=0)


@workflows_bp.get("/assets/<path:name>")
def assets(name):
    return send_from_directory(DIST / "assets", name)


@workflows_bp.get("/icon.png")
def icon():
    return send_from_directory(DIST, "icon.png")
