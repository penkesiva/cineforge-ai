"""Shared Postgres connection pool (psycopg 3). Used only by Postgres-backed implementations."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


@lru_cache(maxsize=4)
def get_pool(database_url: str) -> ConnectionPool:
    pool = ConnectionPool(
        database_url,
        min_size=1,
        max_size=10,
        kwargs={"row_factory": dict_row, "autocommit": False},
        open=False,
    )
    pool.open(wait=True, timeout=15)
    return pool


@contextmanager
def connection(database_url: str) -> Iterator[psycopg.Connection]:
    """Transaction-scoped connection: commits on success, rolls back on error."""
    with get_pool(database_url).connection() as conn, conn.transaction():
        yield conn


def ping(database_url: str) -> bool:
    try:
        with psycopg.connect(database_url, connect_timeout=3) as conn:
            conn.execute("select 1")
        return True
    except psycopg.Error:
        return False
