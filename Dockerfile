# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

# Install uv (pinned to a recent release).
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies first so Docker can cache this layer.
COPY pyproject.toml ./
RUN uv sync --no-dev --frozen || uv sync --no-dev

# Now copy the application source.
COPY app ./app

EXPOSE 8080

# Fly.io routes public traffic to $PORT. Default to 8080 locally.
CMD ["sh", "-c", "uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
