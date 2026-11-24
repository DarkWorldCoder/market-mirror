"""Real, isolated, read-only browser snapshots with a pinned public HTTP fetch boundary."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
import shutil
import socket
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urljoin

import urllib3

from ..config import Config
from .website_test import validate_url
from .workspace_connectors import _is_public

_ACTIVE = threading.Semaphore(1)
_ID = re.compile(r"^br_[a-f0-9]{24}$")
_INSTALL = "Browser support is not installed or unavailable. Install the backend browser extra and Chromium with: uv sync --extra browser && uv run python -m playwright install chromium. The server must support Chromium sandboxing."


@contextmanager
def _deny_proxy():
    """Native Chromium traffic, including speculative connections, has no forwarding path."""
    class Deny(BaseHTTPRequestHandler):
        def reject(self):
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()
        do_CONNECT = do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = reject
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Deny)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield {"server": f"http://127.0.0.1:{server.server_port}", "bypass": "<-loopback>"}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def _root():
    return Path(Config.UPLOAD_FOLDER) / "workspace_browser"


def _cleanup():
    root = _root()
    root.mkdir(parents=True, exist_ok=True)
    folders = [path for path in root.iterdir() if _ID.fullmatch(path.name) and path.is_dir() and not path.is_symlink()]
    folders.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    size = 0
    for index, path in enumerate(folders):
        size += sum(item.stat().st_size for item in path.iterdir() if item.is_file() and not item.is_symlink())
        if index >= 10 or time.time() - path.stat().st_mtime > 86400 or size > 32 * 1024 * 1024:
            shutil.rmtree(path)


def _public_target(url):
    validate_url(url)
    parsed = urlsplit(url)
    addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)}
    if not addresses or any(not _is_public(address) for address in addresses):
        raise ValueError("Browser destinations must resolve only to public addresses")
    return parsed, sorted(addresses)[0]


def _fetch(url, budget):
    """No browser-supplied cookies or headers; the browser itself never opens a destination socket."""
    if time.monotonic() >= budget["deadline"] or budget["requests"] >= 40:
        raise ValueError("Observation reached its network time or request limit")
    parsed, address = _public_target(url)
    budget["requests"] += 1
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    common = {"port": port, "timeout": urllib3.Timeout(connect=2, read=2), "retries": False}
    pool = urllib3.HTTPSConnectionPool(address, server_hostname=parsed.hostname, assert_hostname=parsed.hostname, cert_reqs="CERT_REQUIRED", **common) if parsed.scheme == "https" else urllib3.HTTPConnectionPool(address, **common)
    response = None
    try:
        target = parsed.path or "/"
        if parsed.query:
            target += "?" + parsed.query
        response = pool.urlopen("GET", target, headers={"Host": parsed.netloc, "User-Agent": "MarketMirror-ReadOnly-Observation/1.0", "Accept": "*/*"}, redirect=False, preload_content=False)
        headers = {"Content-Type": response.headers.get("Content-Type", "application/octet-stream")}
        if response.status in (301, 302, 303, 307, 308):
            destination = urljoin(url, response.headers.get("Location", ""))
            _public_target(destination)
            headers["Location"] = destination
        raw = bytearray()
        while len(raw) <= 2 * 1024 * 1024:
            if time.monotonic() >= budget["deadline"]:
                raise ValueError("Observation reached its network time limit")
            chunk = response.read1(8192, decode_content=True)
            if not chunk:
                break
            raw.extend(chunk)
        if len(raw) > 2 * 1024 * 1024 or budget["bytes"] + len(raw) > 10 * 1024 * 1024:
            raise ValueError("Observation reached its response size limit")
        budget["bytes"] += len(raw)
        headers["Content-Security-Policy"] = "default-src http: https: data:; script-src 'none'; style-src 'unsafe-inline' http: https:; connect-src 'none'; object-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'"
        return response.status, headers, bytes(raw)
    except ValueError:
        raise
    except Exception:
        raise ValueError("Public page resource could not be retrieved") from None
    finally:
        if response is not None:
            response.close()
        pool.close()


def _route(route, budget, events):
    request = route.request
    if request.method != "GET" or request.resource_type not in {"document", "stylesheet", "image", "font"}:
        route.abort()
        return
    try:
        status, headers, body = _fetch(request.url, budget)
        route.fulfill(status=status, headers=headers, body=body)
    except ValueError:
        if len(events) < 50:
            events.append({"type": "blocked", "detail": "A resource was blocked by public-network or observation limits."})
        route.abort()


def observe(value):
    if not isinstance(value, dict) or set(value) - {"url"} or not isinstance(value.get("url"), str) or len(value["url"]) > 2048:
        raise ValueError("Provide a public page URL of at most 2048 characters")
    url = validate_url(value["url"], resolve=False)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise ValueError(_INSTALL) from None
    _public_target(url)
    if not _ACTIVE.acquire(blocking=False):
        raise ValueError("Another browser observation is in progress. Try again shortly.")
    folder = None
    try:
        _cleanup()
        session_id = "br_" + uuid.uuid4().hex[:24]
        folder = _root() / session_id
        folder.mkdir(mode=0o700)
        events = []
        budget = {"deadline": time.monotonic() + 25, "requests": 0, "bytes": 0}
        with _deny_proxy() as proxy, sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(headless=True, chromium_sandbox=True, channel="chrome" if shutil.which("google-chrome") else None, proxy=proxy, args=["--disable-background-networking", "--disable-component-update", "--disable-sync"])
            except Exception:
                raise ValueError(_INSTALL) from None
            try:
                context = browser.new_context(java_script_enabled=False, service_workers="block", accept_downloads=False,
                                              viewport={"width": 1280, "height": 800}, ignore_https_errors=False)
                context.route("**/*", lambda route: _route(route, budget, events))
                if hasattr(context, "route_web_socket"):
                    context.route_web_socket("**/*", lambda socket_route: socket_route.close())
                page = context.new_page()
                page.set_default_timeout(5000)
                try:
                    navigation = page.goto(url, wait_until="domcontentloaded", timeout=20000)
                except Exception:
                    raise ValueError("The public page could not be opened within browser observation limits. It may block automated access.") from None
                final_url = page.url
                _public_target(final_url)
                events.append({"type": "navigate", "detail": "Opened the public page with JavaScript disabled."})
                title = page.title()[:300]
                text = page.locator("body").inner_text(timeout=5000)
                text_truncated = len(text) > 16000
                text = text[:16000]
                events.append({"type": "extract", "detail": "Read the rendered page title and bounded DOM text."})
                links = page.locator("a[href]").evaluate_all("nodes => nodes.slice(0,40).map(a => ({text:(a.innerText||'').slice(0,160),url:a.href}))")
                links = [item for item in links if isinstance(item.get("url"), str) and len(item["url"]) <= 2048 and urlsplit(item["url"]).scheme in {"http", "https"}][:30]
                screenshots = []
                def capture(frame, label):
                    path = folder / f"frame-{frame}.png"
                    page.screenshot(path=str(path), full_page=False, timeout=5000)
                    os.chmod(path, 0o600)
                    if path.stat().st_size > 4 * 1024 * 1024:
                        raise ValueError("Browser screenshot exceeded its size limit")
                    screenshots.append({"label": label, "url": f"/api/workspace/browser/{session_id}/image?frame={frame}"})
                    events.append({"type": "capture", "detail": f"Captured {label.lower()} screenshot."})
                capture(0, "Page top")
                height = page.evaluate("document.documentElement.scrollHeight")
                if height > 800:
                    page.evaluate("window.scrollTo(0,640)")
                    position = page.evaluate("window.scrollY")
                    events.append({"type": "scroll", "detail": f"Scrolled down {int(position)} pixels."})
                    capture(1, "After scrolling")
            finally:
                browser.close()
        result = {"session_id": session_id, "url": final_url, "title": title, "text": text, "text_truncated": text_truncated,
                  "screenshot": screenshots[0]["url"], "screenshots": screenshots, "events": events, "links": links,
                  "mode": "read_only_snapshot", "javascript": False, "status_code": navigation.status if navigation else None, "created_at": time.time(), "requests": budget["requests"]}
        path = folder / "observation.json"
        path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        os.chmod(path, 0o600)
        _cleanup()
        return result
    except ValueError:
        if folder and folder.exists():
            shutil.rmtree(folder)
        raise
    except Exception:
        if folder and folder.exists():
            shutil.rmtree(folder)
        raise ValueError("Browser observation failed. Check the page and optional browser installation.") from None
    finally:
        _ACTIVE.release()


def image_path(session_id, frame=0):
    if not isinstance(session_id, str) or not _ID.fullmatch(session_id) or frame not in (0, 1):
        raise LookupError("Browser screenshot not found")
    folder = _root() / session_id
    if folder.is_symlink() or not (folder / "observation.json").is_file() or time.time() - folder.stat().st_mtime > 86400:
        raise LookupError("Browser screenshot expired or was not found")
    path = folder / f"frame-{frame}.png"
    if not path.is_file() or path.is_symlink():
        raise LookupError("Browser screenshot not found")
    return path
