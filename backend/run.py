"""
MiroFish Backend 启动入口

Development (default): Flask's built-in server, optional debug reloader.

Production (`MM_ENV=production` or `--prod`): one process, a bounded thread pool
(`MM_THREADS`, default 32) on Werkzeug's threaded WSGI server. It is deliberately
a single process: the SimulationRunner registry (OASIS subprocesses and their
monitor threads), background task threads and the live-environment IPC state
all live in this process's memory, so a second worker would not see them.
Put a reverse proxy (TLS, buffering, request size/time limits) in front of it.

SIGTERM / SIGINT: the handler does no work itself. A separate thread chains to
the handler that was installed before (SimulationRunner's cleanup handler, so
simulation subprocesses are stopped and graph writes drained), stops simulation
subprocesses explicitly as a fallback, then calls `server.shutdown()`. In-flight
requests get `MM_SHUTDOWN_GRACE` seconds (default 10) to finish; after that the
process exits even if worker threads are still busy.
"""

import os
import sys

# 解决 Windows 控制台中文乱码问题：在所有导入之前设置 UTF-8 编码
if sys.platform == 'win32':
    # 设置环境变量确保 Python 使用 UTF-8
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    # 重新配置标准输出流为 UTF-8
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import logging
import signal
import threading
import time

from werkzeug.serving import ThreadedWSGIServer

from app import create_app
from app.config import Config

log = logging.getLogger("mirofish.server")


def _env_int(name: str, default: int, minimum: int) -> int:
    try:
        return max(minimum, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float, minimum: float) -> float:
    try:
        return max(minimum, float(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


class BoundedThreadedWSGIServer(ThreadedWSGIServer):
    """Werkzeug's threaded server with at most `max_threads` requests in flight.

    When every slot is busy the accept loop waits (new connections queue in the
    listen backlog) instead of spawning unbounded threads. The wait polls the
    `stopping` flag so shutdown never blocks behind a saturated pool.
    """

    def __init__(self, host, port, app, max_threads: int, **kwargs):
        super().__init__(host, port, app, **kwargs)
        self.max_threads = max_threads
        self._slots = threading.BoundedSemaphore(max_threads)
        self._active = 0
        self._active_lock = threading.Lock()
        self.stopping = threading.Event()

    @property
    def active_requests(self) -> int:
        with self._active_lock:
            return self._active

    def process_request(self, request, client_address):
        while not self._slots.acquire(timeout=0.5):
            if self.stopping.is_set():
                self.shutdown_request(request)
                return
        with self._active_lock:
            self._active += 1
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._release()

    def _release(self):
        with self._active_lock:
            self._active -= 1
        self._slots.release()


def _cleanup_simulations() -> None:
    try:
        from app.services.simulation_runner import SimulationRunner
        SimulationRunner.cleanup_all_simulations()
    except Exception:  # noqa: BLE001 - shutdown must continue
        log.exception("simulation cleanup failed during shutdown")


def install_shutdown_handlers(server: BoundedThreadedWSGIServer, cleanup=_cleanup_simulations):
    """Install SIGTERM/SIGINT handlers that stop `server` from another thread.

    Returns the event that is set once a shutdown has been requested.
    """
    requested = threading.Event()
    previous = {}
    for sig in (signal.SIGTERM, signal.SIGINT):
        previous[sig] = signal.getsignal(sig)

    def _stop(signum, frame):
        log.info("signal %s received: stopping simulations and the HTTP server", signum)
        prev = previous.get(signum)
        if callable(prev):
            try:
                prev(signum, frame)   # e.g. SimulationRunner's cleanup handler
            except (KeyboardInterrupt, SystemExit):
                pass                  # that handler ends with "exit"; exiting is our job here
            except Exception:  # noqa: BLE001
                log.exception("previous signal handler failed")
        cleanup()                     # idempotent; covers a missing or failed previous handler
        server.stopping.set()
        server.shutdown()             # safe: called from a thread other than serve_forever's

    def _handler(signum, frame):
        if requested.is_set():
            log.warning("second signal %s: exiting now", signum)
            os._exit(128 + signum)
        requested.set()
        threading.Thread(target=_stop, args=(signum, frame), name="mm-shutdown", daemon=True).start()

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)
    return requested


def serve_production(app, host: str, port: int) -> None:
    threads = _env_int('MM_THREADS', 32, minimum=4)
    grace = _env_float('MM_SHUTDOWN_GRACE', 10.0, minimum=0.0)
    server = BoundedThreadedWSGIServer(host, port, app, max_threads=threads)
    install_shutdown_handlers(server)
    print(f"[Production WSGI] Listening on http://{host}:{port} "
          f"(single process, {threads} request threads, env=production)", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
    deadline = time.monotonic() + grace
    while server.active_requests and time.monotonic() < deadline:
        time.sleep(0.1)
    left = server.active_requests
    print(f"[Production WSGI] Stopped ({left} request(s) still running).", flush=True)
    logging.shutdown()
    # Worker pools (e.g. LLM ThreadPoolExecutors) are joined at interpreter exit and could hold
    # the process past the container's stop timeout; everything durable is already flushed.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


def main():
    """主函数"""
    # 验证配置
    errors = Config.validate()
    host = os.environ.get('FLASK_HOST', '127.0.0.1')
    production = Config.is_production() or '--prod' in sys.argv
    if production:
        os.environ['MM_ENV'] = 'production'
        errors = errors + Config.production_errors(host)
    if errors:
        print("配置错误:")
        for err in errors:
            print(f"  - {err}")
        print("\n请检查 .env 文件中的配置")
        sys.exit(1)

    # 创建应用
    app = create_app()

    port = int(os.environ.get('FLASK_PORT', 5001))
    if production:
        serve_production(app, host, port)
    else:
        # 启动服务
        app.run(host=host, port=port, debug=Config.DEBUG, threaded=True)


if __name__ == '__main__':
    main()
