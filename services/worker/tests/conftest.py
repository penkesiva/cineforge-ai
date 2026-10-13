from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

_ENGINE_TESTS = str(Path(__file__).resolve().parents[3] / "packages" / "engine" / "tests")
if _ENGINE_TESTS not in sys.path:
    sys.path.insert(0, _ENGINE_TESTS)


@pytest.fixture
def fake_redis() -> Iterator[object]:
    import fakeredis

    server = fakeredis.FakeServer()
    conn = fakeredis.FakeStrictRedis(server=server)
    yield conn
    conn.flushall()


@pytest.fixture(autouse=True)
def _reset_runtime() -> Iterator[None]:
    from cineforge.runtime import set_runtime

    yield
    set_runtime(None)
