# MarketMirror backend (API + CLI). The Vue frontend of upstream MiroFish is not needed: the dashboard is a static HTML export.
#
# Production settings (MM_ENV=production is set below): the server refuses to start on a
# non-loopback host without MM_API_AUTH_TOKEN, an explicit CORS_ORIGINS and a real SECRET_KEY.
# See .env.production.example. It runs as the unprivileged user `mm` (uid APP_UID, default 10001);
# bind-mounted folders must be writable by that uid (see docker-compose.yml).
FROM python:3.12-slim

ARG APP_UID=10001
ARG APP_GID=10001

RUN apt-get update && apt-get install -y --no-install-recommends curl git && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/

RUN groupadd --system --gid "${APP_GID}" mm \
 && useradd --system --uid "${APP_UID}" --gid mm --home-dir /home/mm --create-home --shell /usr/sbin/nologin mm

WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./backend/
RUN cd backend && uv sync --frozen --python 3.12

COPY . .
# Only the runtime data folders are writable by the app user; code and the venv stay root-owned.
RUN mkdir -p backend/uploads backend/logs mirofish_runs scenarios \
 && chown -R mm:mm backend/uploads backend/logs mirofish_runs scenarios

ENV FLASK_HOST=0.0.0.0 \
    FLASK_DEBUG=False \
    MM_ENV=production \
    MM_THREADS=32 \
    MM_SHUTDOWN_GRACE=10 \
    MIROFISH_URL=http://127.0.0.1:5001 \
    MEMORY_BACKEND=local \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/home/mm

USER mm

EXPOSE 5001 5050
# Liveness only (no auth needed); /ready is the readiness probe for an orchestrator.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 CMD curl -fsS http://127.0.0.1:5001/health || exit 1
# Exec form: run.py is PID 1 and receives SIGTERM directly from `docker stop`.
STOPSIGNAL SIGTERM
CMD ["backend/.venv/bin/python", "backend/run.py", "--prod"]
