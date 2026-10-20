"""Gunicorn production configuration for MarketMirror Backend."""

import multiprocessing
import os

bind = f"{os.environ.get('FLASK_HOST', '0.0.0.0')}:{os.environ.get('FLASK_PORT', '5001')}"
workers = int(os.environ.get("GUNICORN_WORKERS", min(4, max(2, multiprocessing.cpu_count()))))
threads = int(os.environ.get("GUNICORN_THREADS", "8"))
worker_class = "gthread"
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "300"))
graceful_timeout = 30
keepalive = 5
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info").lower()
