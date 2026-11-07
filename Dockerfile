# syntax=docker/dockerfile:1
# Python image for the pipeline, review app and API.
# SLIM=1 builds the public API only (fly.toml): no OCR, no Chromium.
FROM python:3.12-slim-bookworm

ARG SLIM=0

# System packages: Tesseract OCR with Vietnamese data, and libs for PDF table extraction.
RUN apt-get update \
    && if [ "$SLIM" = "1" ]; then \
        apt-get install -y --no-install-recommends curl ca-certificates; \
    else \
        apt-get install -y --no-install-recommends \
            tesseract-ocr tesseract-ocr-vie \
            libgl1 libglib2.0-0 \
            make curl ca-certificates; \
    fi \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /uvx /usr/local/bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright

WORKDIR /app

# Install dependencies first so this layer stays cached across code changes.
# The uv download cache is a build-time cache mount, so it never ends up in the image.
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project

# Chromium for the few pages that need JS (not needed by the API).
RUN if [ "$SLIM" != "1" ]; then playwright install --with-deps chromium; fi

COPY . .

CMD ["sleep", "infinity"]
