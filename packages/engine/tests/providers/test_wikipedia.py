from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from cineforge.config import Settings
from cineforge.contracts.providers import (
    PriceUnit,
    Provider,
    ProviderCapability,
    ProviderError,
    ResearchSource,
)
from cineforge.providers.wikipedia import WikipediaResearchProvider, wiki_language
from provider_fakes import Recorder, json_response, request_for, wikimedia_handler

C = ProviderCapability


def _provider(handler=wikimedia_handler):
    rec = Recorder(handler)
    return WikipediaResearchProvider(Settings(), client=rec.client()), rec


def test_info() -> None:
    provider, _ = _provider()
    assert isinstance(provider, Provider)
    info = provider.info
    assert (info.name, info.models, info.capabilities) == (
        "wikipedia",
        ["mediawiki-action-api"],
        [C.WEB_RESEARCH],
    )
    assert not info.is_paid and not info.is_mock and not info.requires_key


def test_search_then_one_extract_call_per_page() -> None:
    provider, rec = _provider()
    req = request_for(C.WEB_RESEARCH, "mediawiki-action-api", max_results=3, language="en-US")
    response = provider.invoke(req)

    search, *pages = rec.requests
    assert search.url.host == "en.wikipedia.org" and search.url.path == "/w/api.php"
    assert search.url.params["list"] == "search"
    assert search.url.params["srsearch"] == "Eiffel Tower"
    assert search.url.params["srlimit"] == "3"
    assert search.url.params["formatversion"] == "2"
    assert [p.url.params["pageids"] for p in pages] == ["9232", "12886", "404404"]
    for page in pages:
        assert page.url.params["prop"] == "extracts|info"
        assert page.url.params["explaintext"] == "1"
        assert page.url.params["inprop"] == "url"

    sources = [ResearchSource.model_validate(s) for s in response.output_data["sources"]]
    assert [s.title for s in sources] == ["Eiffel Tower", "Gustave Eiffel"]  # missing page dropped
    first = sources[0]
    assert first.url == "https://en.wikipedia.org/wiki/Eiffel_Tower"
    assert first.publisher == "Wikipedia"
    assert first.extract.startswith("The Eiffel Tower is a lattice tower")
    assert first.published_at == date(2026, 10, 13)
    assert sources[1].published_at is None
    assert response.usage.units == Decimal(1) and response.usage.unit == PriceUnit.REQUEST
    assert response.provider_request_id.startswith("wikipedia_")
    assert response.output_data["language"] == "en"


def test_extract_truncated_and_results_capped() -> None:
    long_page = {
        "query": {
            "pages": [
                {
                    "pageid": 1,
                    "title": "Long",
                    "extract": "a" * 9000,
                    "canonicalurl": "https://fr.wikipedia.org/wiki/Long",
                }
            ]
        }
    }
    hits = {"query": {"search": [{"title": f"T{i}", "pageid": i} for i in range(20)]}}

    def handler(request):
        if request.url.params.get("list") == "search":
            return json_response(200, hits)
        return json_response(200, long_page)

    provider, rec = _provider(handler)
    response = provider.invoke(
        request_for(C.WEB_RESEARCH, "mediawiki-action-api", max_results=50, language="fr")
    )
    assert rec.requests[0].url.host == "fr.wikipedia.org"
    assert rec.requests[0].url.params["srlimit"] == "8"
    assert len(response.output_data["sources"]) == 8
    assert len(response.output_data["sources"][0]["extract"]) == 6000


def test_language_is_sanitized() -> None:
    assert wiki_language("en-US") == "en"
    assert wiki_language("pt_BR") == "pt"
    assert wiki_language(None) == "en"
    assert wiki_language("evil.example.com/") == "en"


def test_empty_query_rejected() -> None:
    provider, rec = _provider()
    with pytest.raises(ProviderError, match="empty"):
        provider.estimate_usage(request_for(C.WEB_RESEARCH, "mediawiki-action-api", prompt=" "))
    assert rec.requests == []


def test_http_errors_propagate_as_provider_errors() -> None:
    provider, _ = _provider(lambda r: json_response(503, {"error": "busy"}))
    with pytest.raises(ProviderError) as info:
        provider.invoke(request_for(C.WEB_RESEARCH, "mediawiki-action-api"))
    assert info.value.retryable is True


def test_check() -> None:
    provider, rec = _provider()
    assert provider.check() == (True, "reachable (Wikipedia)")
    assert rec.requests[0].url.params["meta"] == "siteinfo"
    down, _ = _provider(lambda r: json_response(500, {}))
    ok, detail = down.check()
    assert ok is False and "HTTP 500" in detail
