from __future__ import annotations

import sys
from pathlib import Path

ENGINE_TESTS = Path(__file__).resolve().parents[3] / "packages" / "engine" / "tests"
sys.path.insert(0, str(ENGINE_TESTS))
