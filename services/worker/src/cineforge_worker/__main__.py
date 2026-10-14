"""Agent worker: consumes ``cineforge-agents`` and runs ``advance_production`` jobs.

Run locally: ``uv run python -m cineforge_worker`` (needs ``REDIS_URL``).
``--simple`` runs jobs in-process (no fork), ``--burst`` exits when the queue is empty.
SIGTERM/SIGINT trigger RQ's warm shutdown: the current job finishes, then the worker exits.
A second signal forces a cold shutdown.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from typing import Any

from cineforge.config import Settings, get_settings
from cineforge.contracts.jobs import QUEUE_AGENTS
from rq import Queue, SimpleWorker, Worker

log = logging.getLogger("cineforge_worker")


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )


def build_worker(
    connection: Any,
    *,
    queues: Sequence[str] = (QUEUE_AGENTS,),
    simple: bool = False,
    name: str | None = None,
) -> Worker:
    worker_cls = SimpleWorker if simple else Worker
    return worker_cls(
        [Queue(q, connection=connection) for q in queues],
        connection=connection,
        name=name,
    )


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="cineforge_worker", description=__doc__)
    parser.add_argument("--redis-url", default=None, help="defaults to settings.redis_url")
    parser.add_argument(
        "--queue", action="append", dest="queues", help=f"queue name (default {QUEUE_AGENTS})"
    )
    parser.add_argument("--burst", action="store_true", help="exit when queues are empty")
    parser.add_argument("--simple", action="store_true", help="run jobs in-process (no fork)")
    parser.add_argument("--name", default=None, help="worker name")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None, *, settings: Settings | None = None) -> int:
    args = parse_args(argv)
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    from redis import Redis

    redis_url = args.redis_url or settings.redis_url
    connection = Redis.from_url(redis_url)
    queues = args.queues or [QUEUE_AGENTS]
    worker = build_worker(connection, queues=queues, simple=args.simple, name=args.name)
    log.info(
        "starting worker %s on queues=%s env=%s persistence=%s paid_providers=%s",
        worker.name,
        queues,
        settings.cineforge_env,
        settings.persistence_backend,
        settings.allow_paid_providers,
    )
    try:
        worker.work(burst=args.burst, logging_level=settings.log_level.upper())
    except KeyboardInterrupt:
        log.info("worker interrupted")
    finally:
        log.info("worker %s stopped", worker.name)
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
