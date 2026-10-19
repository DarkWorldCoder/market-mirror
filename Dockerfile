# MarketMirror backend (API + CLI). The Vue frontend of upstream MiroFish is not needed: the dashboard is a static HTML export.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl git && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/

WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./backend/
RUN cd backend && uv sync --frozen --python 3.12

COPY . .
ENV FLASK_HOST=0.0.0.0 \
    MIROFISH_URL=http://127.0.0.1:5001 \
    MEMORY_BACKEND=local \
    PYTHONUNBUFFERED=1

EXPOSE 5001 5050
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s CMD curl -fsS http://127.0.0.1:5001/health || exit 1
CMD ["backend/.venv/bin/python", "backend/run.py"]
