# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

# Install uv (pinned to a recent release).
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv

# ReportLab uses this packaged font for Unicode cover-letter PDFs. Installing
# it explicitly keeps rendering identical on the slim production image and on
# developer machines instead of depending on whatever fonts happen to exist.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first so Docker can cache this layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Now copy the application source.
COPY app ./app
RUN uv sync --frozen --no-dev

EXPOSE 8080

# Fly.io routes public traffic to $PORT. Default to 8080 locally.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
