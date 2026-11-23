"""A queue worker process: `cd backend && uv run --no-sync python -m app.jobs.worker [--threads 4]`.

Point it at the server's database (the same MM_TASK_DB_PATH / MIROFISH_UPLOAD_DIR and .env) and start the server
with MM_JOB_EXTERNAL_WORKERS=1, so endpoint jobs (feed test, survey, pitch, focus group, questionnaire, choice
tests, email test, analyst panel, report...) are left for workers. Start as many as the host can carry; limits per
provider and workspace hold across all of them. The `oasis` lane (OASIS starts) stays with the server, which owns the
simulation subprocesses.

SIGTERM/SIGINT: stop claiming, wait up to MM_JOB_STOP_GRACE seconds (default 30) for running jobs, and exit. A job
still running then is settled by the next sweep of a live process: requeued if it made no model call, otherwise
held for approval.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="MarketMirror job queue worker")
    parser.add_argument("--threads", type=int, default=None, help="jobs at a time (default MM_JOB_WORKERS or 4)")
    parser.add_argument("--lanes", default="", help="only these lanes (comma-separated); default every lane but oasis")
    args = parser.parse_args(argv)

    os.environ["MM_JOB_ROLE"] = "worker"
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

    from app import create_app, jobs
    app = create_app()
    from app.jobs.replay import set_app
    set_app(app)
    lanes = {x.strip() for x in args.lanes.split(",") if x.strip()} or None
    runner = jobs.start_runner(role="worker", threads=args.threads, lanes=lanes, exclude_lanes={"oasis"},
                               accept_unbound=lambda lane: lane != "oasis")
    print(f"[jobs worker] {runner.worker} running {runner.threads} thread(s) on {jobs.store().path}", flush=True)

    done = threading.Event()

    def _stop(signum, frame):
        done.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    while not done.wait(1.0):
        pass
    try:
        grace = float(os.environ.get("MM_JOB_STOP_GRACE", 30))
    except ValueError:
        grace = 30.0
    print("[jobs worker] stopping", flush=True)
    jobs.stop_runner(timeout=grace)
    return 0


if __name__ == "__main__":
    sys.exit(main())
