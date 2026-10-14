"""Repo-wide pytest hooks. CI and default runs never touch the network."""

from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("RUN_LIVE_TESTS") == "1":
        return
    skip_live = pytest.mark.skip(reason="live test: set RUN_LIVE_TESTS=1 to run")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)
