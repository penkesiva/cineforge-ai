from __future__ import annotations

from decimal import Decimal

import pytest
from cineforge.config import Settings
from cineforge.contracts.cost import PriceCatalog, UnknownPriceError
from cineforge.contracts.providers import PriceUnit, ProviderCapability
from cineforge.cost.catalog import YamlPriceCatalog
from cineforge.cost.factory import load_price_catalog


@pytest.fixture
def catalog() -> YamlPriceCatalog:
    return load_price_catalog(Settings())


def test_loads_all_entries(catalog: YamlPriceCatalog) -> None:
    assert isinstance(catalog, PriceCatalog)
    assert catalog.version == "mock-2026-10"
    assert catalog.simulated is True
    entries = catalog.entries()
    assert len(entries) == 11
    assert {e.version for e in entries} == {"mock-2026-10"}
    assert all(isinstance(e.unit_price, Decimal) for e in entries)


def test_get_returns_exact_price(catalog: YamlPriceCatalog) -> None:
    entry = catalog.get("mock-video", "mock-video-cinematic", PriceUnit.VIDEO_SECOND)
    assert entry.unit_price == Decimal("0.25")
    assert entry.capability == ProviderCapability.VIDEO_GENERATION
    assert catalog.get("mock-llm", "mock-llm-standard", "1k_tokens").unit_price == Decimal("0.002")


@pytest.mark.parametrize(
    ("provider", "model", "unit"),
    [
        ("mock-video", "mock-video-cinematic", PriceUnit.IMAGE),  # wrong unit
        ("mock-video", "nope", PriceUnit.VIDEO_SECOND),  # unknown model
        ("real-vendor", "x", PriceUnit.REQUEST),  # unknown provider
        ("mock-llm", "mock-llm-standard", "bogus-unit"),  # not a PriceUnit
    ],
)
def test_unknown_price_raises(
    catalog: YamlPriceCatalog, provider: str, model: str, unit: PriceUnit
) -> None:
    with pytest.raises(UnknownPriceError):
        catalog.get(provider, model, unit)


def test_missing_version_file(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        load_price_catalog(Settings(configurations_dir=tmp_path, price_catalog_version="nope"))


def test_duplicate_entries_rejected() -> None:
    raw = {
        "version": "t",
        "effective_from": "2026-10-01",
        "entries": [
            {"provider": "p", "model": "m", "capability": "llm_text", "unit": "request",
             "unit_price": 1},
        ]
        * 2,
    }  # fmt: skip
    with pytest.raises(ValueError, match="duplicate"):
        YamlPriceCatalog.from_mapping(raw)
