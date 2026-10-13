"""Media worker entrypoint: ``python -m cineforge_media_worker``.

Consumes queue ``cineforge-media`` (JOB_RENDER_MASTER). Requires ffmpeg and ffprobe.
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from urllib.parse import urlsplit, urlunsplit

from cineforge.config import get_settings
from cineforge.contracts.jobs import QUEUE_MEDIA
from redis import Redis
from rq import Worker

REQUIRED_BINARIES = ("ffmpeg", "ffprobe")

log = logging.getLogger("cineforge_media_worker")


def redact_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.password is None:
        return url
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunsplit(parts._replace(netloc=f"{parts.username or ''}:***@{host}"))


def missing_binaries() -> list[str]:
    return [name for name in REQUIRED_BINARIES if shutil.which(name) is None]


def build_worker(connection: Redis, *, name: str | None = None) -> Worker:
    return Worker([QUEUE_MEDIA], connection=connection, name=name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cineforge_media_worker", description=__doc__)
    parser.add_argument("--burst", action="store_true", help="exit when the queue is empty")
    parser.add_argument("--name", default=None, help="RQ worker name")
    args = parser.parse_args(argv)

    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    missing = missing_binaries()
    if missing:
        print(
            f"cineforge-media-worker: required binaries not found on PATH: {', '.join(missing)}. "
            "Install FFmpeg (e.g. `apt-get install ffmpeg` or `brew install ffmpeg`).",
            file=sys.stderr,
        )
        return 2

    worker = build_worker(Redis.from_url(settings.redis_url), name=args.name)
    log.info("media worker listening on %s (redis %s)", QUEUE_MEDIA, redact_url(settings.redis_url))
    worker.work(burst=args.burst, with_scheduler=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
