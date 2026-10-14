"""Real network calls. Skipped unless RUN_LIVE_TESTS=1 (see repo conftest.py).

Free APIs only, except one tiny Anthropic call that also needs ANTHROPIC_API_KEY
(costs a fraction of a cent: haiku, 16 output tokens).
"""

from __future__ import annotations

import os

import pytest
from cineforge.config import Settings
from cineforge.contracts.providers import MediaSearchItem, ProviderCapability, ResearchSource
from cineforge.providers.anthropic import AnthropicProvider
from cineforge.providers.commons import CommonsMediaProvider
from cineforge.providers.openverse import OpenverseMediaProvider
from cineforge.providers.wikipedia import WikipediaResearchProvider
from provider_fakes import request_for

pytestmark = pytest.mark.live
C = ProviderCapability


def test_wikipedia_live() -> None:
    provider = WikipediaResearchProvider(Settings())
    assert provider.check()[0]
    response = provider.invoke(
        request_for(C.WEB_RESEARCH, "mediawiki-action-api", prompt="Eiffel Tower", max_results=2)
    )
    sources = [ResearchSource.model_validate(s) for s in response.output_data["sources"]]
    assert sources and sources[0].url.startswith("https://en.wikipedia.org/wiki/")
    assert 0 < len(sources[0].extract) <= 6000


def test_commons_live() -> None:
    provider = CommonsMediaProvider(Settings())
    assert provider.check()[0]
    response = provider.invoke(
        request_for(C.MEDIA_SEARCH, "mediawiki-action-api", prompt="Eiffel Tower", limit=3)
    )
    items = [MediaSearchItem.model_validate(i) for i in response.output_data["items"]]
    assert items and all(i.license and i.license.license_type for i in items)
    assert all(i.source_url.startswith("https://commons.wikimedia.org/") for i in items)


def test_openverse_live() -> None:
    provider = OpenverseMediaProvider(Settings())
    assert provider.check()[0]
    response = provider.invoke(
        request_for(C.MEDIA_SEARCH, "openverse-v1", prompt="Eiffel Tower", limit=3)
    )
    items = [MediaSearchItem.model_validate(i) for i in response.output_data["items"]]
    assert items and all(i.license and i.license.attribution_text for i in items)


@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY not set")
def test_anthropic_live_tiny_call() -> None:
    settings = Settings()
    key = settings.anthropic_api_key or os.environ["ANTHROPIC_API_KEY"]
    provider = AnthropicProvider(settings, key_resolver=lambda _tenant: key)
    assert provider.check("tenant_demo")[0]
    response = provider.invoke(
        request_for(
            C.LLM_TEXT,
            "claude-haiku-4-5",
            prompt="Reply with the single word: ok",
            max_tokens=16,
            temperature=0,
        )
    )
    assert response.output_text and response.usage.breakdown
