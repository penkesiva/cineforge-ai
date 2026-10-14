from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import psycopg
import pytest
from cineforge.contracts.common import DEMO_TENANT_ID
from cineforge.cost.credits import SIMULATED_CREDIT_BALANCES
from fakes_d import DATABASE_URL, db_available

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts" / "generate_seed.py"
SEED = ROOT / "supabase" / "seed.sql"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("generate_seed", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_seed_is_current() -> None:
    assert SEED.read_text() == _load_script().render(), (
        "supabase/seed.sql is stale: run `uv run python scripts/generate_seed.py`"
    )


def test_check_mode_cli() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_seed_content() -> None:
    sql = SEED.read_text()
    assert sql.startswith("-- GENERATED")
    assert sql.count("on conflict") == 4
    assert "on conflict (tenant_id, provider) do nothing" in sql
    for provider in SIMULATED_CREDIT_BALANCES:
        assert f"'{provider}'" in sql


def test_quoting() -> None:
    q = _load_script().q
    assert q("O'Brien") == "'O''Brien'"
    assert q(None) == "null" and q(True) == "true" and q(3) == "3"


@pytest.mark.integration
def test_seed_applies_twice_without_breaking_rows() -> None:
    if not db_available():
        pytest.skip("Postgres not reachable")
    sql = SEED.read_text()
    with psycopg.connect(DATABASE_URL) as conn:
        balances_before = dict(
            conn.execute(
                "select provider, balance from credit_balances where tenant_id = %s",
                (DEMO_TENANT_ID,),
            ).fetchall()
        )
    for _ in range(2):
        with psycopg.connect(DATABASE_URL) as conn, conn.transaction():
            conn.execute(sql)
    with psycopg.connect(DATABASE_URL) as conn:
        themes = conn.execute(
            "select id, version, config ->> 'id' from theme_profiles order by id"
        ).fetchall()
        prices = conn.execute(
            "select count(*), bool_and(simulated) from price_catalog where version = 'mock-2026-10'"
        ).fetchone()
        balances = dict(
            conn.execute(
                "select provider, balance from credit_balances where tenant_id = %s",
                (DEMO_TENANT_ID,),
            ).fetchall()
        )
        tenant = conn.execute(
            "select name from tenants where id = %s", (DEMO_TENANT_ID,)
        ).fetchone()
    assert {(t[0], t[1]) for t in themes} >= {
        ("fascinating-places", 1),
        ("mystery-explorer", 1),
        ("time-traveler", 1),
    }
    assert all(t[0] == t[2] for t in themes)
    assert prices == (11, True)
    assert set(balances) >= set(SIMULATED_CREDIT_BALANCES)
    # Existing (possibly spent-down) balances are preserved, never reset.
    for provider, value in balances_before.items():
        assert balances[provider] == value
    assert tenant is not None
