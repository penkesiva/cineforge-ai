"""Versioned price catalog loaded from packages/configurations/pricing/<version>.yaml."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from cineforge.contracts.common import DEFAULT_CURRENCY, money
from cineforge.contracts.cost import PriceCatalogEntry, UnknownPriceError
from cineforge.contracts.providers import PriceUnit


class YamlPriceCatalog:
    """Immutable, in-memory view of one catalog version."""

    def __init__(
        self,
        entries: list[PriceCatalogEntry],
        *,
        version: str,
        simulated: bool = True,
        currency: str = DEFAULT_CURRENCY,
    ) -> None:
        self.version = version
        self.simulated = simulated
        self.currency = currency
        self._entries = list(entries)
        self._index: dict[tuple[str, str, PriceUnit], PriceCatalogEntry] = {}
        for entry in self._entries:
            key = (entry.provider, entry.model, entry.unit)
            if key in self._index:
                raise ValueError(f"duplicate price catalog entry {key} in {version}")
            self._index[key] = entry

    @classmethod
    def from_file(cls, path: Path) -> YamlPriceCatalog:
        if not path.is_file():
            raise FileNotFoundError(f"price catalog not found: {path}")
        return cls.from_mapping(yaml.safe_load(path.read_text()))

    @classmethod
    def load(cls, configurations_dir: Path, version: str) -> YamlPriceCatalog:
        return cls.from_file(configurations_dir / "pricing" / f"{version}.yaml")

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> YamlPriceCatalog:
        version = str(raw["version"])
        currency = str(raw.get("currency", DEFAULT_CURRENCY))
        effective_from = _as_date(raw["effective_from"])
        effective_to = _as_date(raw["effective_to"]) if raw.get("effective_to") else None
        entries = []
        for item in raw.get("entries", []):
            credits = item.get("credits_per_unit")
            entries.append(
                PriceCatalogEntry(
                    provider=item["provider"],
                    model=item["model"],
                    capability=item["capability"],
                    unit=item["unit"],
                    unit_price=money(item["unit_price"]),
                    currency=item.get("currency", currency),
                    credits_per_unit=Decimal(str(credits)) if credits is not None else None,
                    version=version,
                    effective_from=_as_date(item.get("effective_from", effective_from)),
                    effective_to=effective_to,
                    notes=item.get("notes", ""),
                )
            )
        return cls(
            entries, version=version, simulated=bool(raw.get("simulated", True)), currency=currency
        )

    def get(self, provider: str, model: str, unit: PriceUnit) -> PriceCatalogEntry:
        try:
            return self._index[(provider, model, PriceUnit(unit))]
        except (KeyError, ValueError):
            raise UnknownPriceError(
                f"no price for provider={provider!r} model={model!r} unit={unit!s} "
                f"in catalog {self.version}"
            ) from None

    def find(self, provider: str, model: str) -> list[PriceCatalogEntry]:
        """All units priced for a provider/model (usually exactly one)."""
        return [e for e in self._entries if e.provider == provider and e.model == model]

    def entries(self) -> list[PriceCatalogEntry]:
        return list(self._entries)


def _as_date(value: Any) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))
