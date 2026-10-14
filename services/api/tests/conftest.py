from __future__ import annotations

import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

_ENGINE_TESTS = str(Path(__file__).resolve().parents[3] / "packages" / "engine" / "tests")
if _ENGINE_TESTS not in sys.path:
    sys.path.insert(0, _ENGINE_TESTS)


@dataclass
class Api:
    client: Any
    rt: Any
    fx: Any


@pytest.fixture
def api() -> Iterator[Api]:
    from cineforge.runtime import set_runtime
    from cineforge_api.main import create_app
    from fakes_b import make_runtime
    from fastapi.testclient import TestClient

    rt, fx = make_runtime()
    with TestClient(create_app(rt.settings)) as client:
        yield Api(client, rt, fx)
    set_runtime(None)
