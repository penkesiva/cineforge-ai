# syntax=docker/dockerfile:1.7
# CineForge Python image for api, worker and media-worker (build context = repo root).
#
# Targets:
#   app    - Python 3.12 + the whole uv workspace (api, worker, engine) in /opt/venv
#   media  - app + ffmpeg/ffprobe + DejaVu fonts (drawtext) for the media worker
#
# Build args:
#   INSTALL_DEV=true|false  include the `dev` dependency group (pytest, ruff, ...).
#                           Default true so `docker compose run --rm api pytest` works.
#
# The venv lives OUTSIDE /app so dev bind mounts (./packages, ./services, ./scripts)
# never hide it. Workspace members are installed editable, so mounted sources are live.

ARG PYTHON_VERSION=3.12
ARG UV_VERSION=0.13

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

FROM python:${PYTHON_VERSION}-slim-bookworm AS base

COPY --from=uv /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH

ARG APP_UID=1000
ARG APP_GID=1000
RUN groupadd --gid "${APP_GID}" cineforge \
    && useradd --uid "${APP_UID}" --gid cineforge --create-home --shell /bin/bash cineforge \
    && mkdir -p /app /data/media \
    && chown cineforge:cineforge /app /data/media

WORKDIR /app

# ---------------------------------------------------------------------------
# Dependencies only (cached until pyproject.toml / uv.lock change).
# ---------------------------------------------------------------------------
FROM base AS deps

ARG INSTALL_DEV=true

COPY pyproject.toml uv.lock .python-version ./
COPY packages/engine/pyproject.toml packages/engine/pyproject.toml
COPY services/api/pyproject.toml services/api/pyproject.toml
COPY services/worker/pyproject.toml services/worker/pyproject.toml
COPY services/media-worker/pyproject.toml services/media-worker/pyproject.toml

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --all-packages --no-install-workspace \
        $([ "${INSTALL_DEV}" = "true" ] || echo --no-dev)

# ---------------------------------------------------------------------------
# app: sources + editable workspace members.
# ---------------------------------------------------------------------------
FROM deps AS app

ARG INSTALL_DEV=true

COPY packages/ packages/
COPY services/ services/
COPY scripts/ scripts/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --all-packages \
        $([ "${INSTALL_DEV}" = "true" ] || echo --no-dev)

USER cineforge

EXPOSE 8000
CMD ["uvicorn", "cineforge_api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ---------------------------------------------------------------------------
# media: app + FFmpeg for the media worker.
# ---------------------------------------------------------------------------
FROM app AS media

USER root
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean \
    && apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core \
    && ffmpeg -hide_banner -version >/dev/null \
    && ffprobe -hide_banner -version >/dev/null
USER cineforge

CMD ["python", "-m", "cineforge_media_worker"]
