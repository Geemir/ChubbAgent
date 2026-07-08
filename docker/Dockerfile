# ChubbAgent — Phase 1 MVP image.
# Base image ships uv; we install locked deps then run the APScheduler loop.
FROM python:3.12-slim

# System deps: poppler-utils gives `pdftotext` for `chubb-ci ingest-pdf`.
RUN apt-get update && apt-get install -y --no-install-recommends \
        poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# uv (fast, reproducible installs)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first (better layer caching).
COPY pyproject.toml README.md ./
COPY chubb_ci ./chubb_ci
RUN uv sync --no-dev

# Runtime config (sources + domain context) — override via a mounted volume.
COPY config ./config

# Persist DB, raw HTML and reports on a volume.
VOLUME ["/app/data"]

# Default: run the scheduler (daily + weekly jobs). Override for one-off commands, e.g.
#   docker compose run --rm app uv run chubb-ci crawl --demo
CMD ["uv", "run", "chubb-ci", "serve"]
