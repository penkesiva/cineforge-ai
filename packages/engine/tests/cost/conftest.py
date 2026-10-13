from __future__ import annotations

import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cineforge.contracts.cost import BudgetService
from cineforge.cost.memory import InMemoryBudgetService
from fakes_d import DATABASE_URL, PgScratch, db_available


@dataclass
class BudgetBackend:
    name: str
    service: BudgetService
    tenant_id: str
    pg: PgScratch | None = None
    _counter: list[int] = field(default_factory=lambda: [0])

    def new_production(
        self,
        limit: str | Decimal = "10.00",
        *,
        tenant_id: str | None = None,
        scene_limits: dict[str, Decimal] | None = None,
    ) -> str:
        tenant_id = tenant_id or self.tenant_id
        if self.pg is not None:
            production_id = self.pg.add_production(tenant_id=tenant_id)
        else:
            self._counter[0] += 1
            production_id = f"prod_mem_{self._counter[0]:04d}"
        self.service.create_budget(
            tenant_id=tenant_id,
            production_id=production_id,
            limit=Decimal(limit),
            scene_limits=scene_limits,
        )
        return production_id

    def new_tenant(self) -> str:
        if self.pg is not None:
            return self.pg.add_tenant()
        self._counter[0] += 1
        return f"tenant_mem_{self._counter[0]:04d}"


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.integration)])
def backend(request: pytest.FixtureRequest) -> Iterator[BudgetBackend]:
    if request.param == "memory":
        yield BudgetBackend("memory", InMemoryBudgetService(), "tenant_mem_main")
        return
    if not db_available():
        pytest.skip("Postgres not reachable")
    from cineforge.cost.postgres import PostgresBudgetService

    pg = PgScratch()
    try:
        yield BudgetBackend("postgres", PostgresBudgetService(DATABASE_URL), pg.tenant_id, pg)
    finally:
        pg.cleanup()
