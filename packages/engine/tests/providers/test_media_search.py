"""Commons + Openverse media search, license mapping and rights-gate outcomes."""

from __future__ import annotations

import pytest
from cineforge.config import Settings
from cineforge.contracts.media import LicenseInfo, RightsStatus
from cineforge.contracts.providers import (
    MediaSearchItem,
    Provider,
    ProviderCapability,
    ProviderError,
)
from cineforge.media.rights import DefaultRightsGate
from cineforge.providers.commons import CommonsMediaProvider, commons_license, file_title
from cineforge.providers.licenses import normalize_open_license
from cineforge.providers.openverse import OpenverseMediaProvider
from provider_fakes import Recorder, json_response, request_for, wikimedia_handler

C = ProviderCapability
GATE = DefaultRightsGate()


def _commons(handler=wikimedia_handler):
    rec = Recorder(handler)
    return CommonsMediaProvider(Settings(), client=rec.client()), rec


def _openverse(handler=lambda r: json_response(200, "openverse_search.json")):
    rec = Recorder(handler)
    return OpenverseMediaProvider(Settings(), client=rec.client()), rec


def _items(response) -> list[MediaSearchItem]:
    return [MediaSearchItem.model_validate(i) for i in response.output_data["items"]]


@pytest.mark.parametrize(
    ("raw", "version", "expected", "recognized"),
    [
        ("cc0", None, "CC0", True),
        ("CC0 1.0", None, "CC0", True),
        ("pd", None, "public-domain", True),
        ("Public domain", None, "public-domain", True),
        ("pdm", "1.0", "public-domain", True),
        ("PD-old", None, "public-domain", True),
        ("CC BY 4.0", None, "CC-BY-4.0", True),
        ("cc-by-sa-3.0", None, "CC-BY-SA-3.0", True),
        ("by", "2.0", "CC-BY-2.0", True),
        ("by-sa", "2.0", "CC-BY-SA-2.0", True),
        ("by-nc", "4.0", "CC-BY-NC-4.0", True),
        ("by-nd", "4.0", "CC-BY-ND-4.0", True),
        ("CC BY-NC-SA 4.0", None, "CC-BY-NC-SA-4.0", True),
        ("by-nc-nd", "3.0", "CC-BY-NC-ND-3.0", True),
        ("CC BY-SA 2.0 de", None, "CC BY-SA 2.0 de", False),
        ("GFDL", None, "GFDL", False),
        ("sampling+", "1.0", "sampling+", False),
        ("", None, "unknown", False),
    ],
)
def test_normalize_open_license(raw, version, expected, recognized) -> None:
    lic = normalize_open_license(raw, version)
    assert (lic.license_type, lic.recognized) == (expected, recognized)


def test_license_flags() -> None:
    assert normalize_open_license("cc0").commercial_use_allowed is True
    assert normalize_open_license("by-sa", "4.0").commercial_use_allowed is True
    nc = normalize_open_license("by-nc", "4.0")
    assert nc.commercial_use_allowed is False and nc.modifications_allowed is True
    nd = normalize_open_license("by-nd", "4.0")
    assert nd.commercial_use_allowed is None and nd.modifications_allowed is False
    raw = normalize_open_license("GFDL")
    assert raw.commercial_use_allowed is None and raw.modifications_allowed is None


def test_commons_search_maps_items_and_licenses() -> None:
    provider, rec = _commons()
    assert isinstance(provider, Provider) and not provider.info.is_paid
    response = provider.invoke(
        request_for(
            C.MEDIA_SEARCH, "mediawiki-action-api", prompt="ignored", query="Eiffel", limit=5
        )
    )
    params = rec.requests[0].url.params
    assert rec.requests[0].url.host == "commons.wikimedia.org"
    assert params["generator"] == "search" and params["gsrsearch"] == "Eiffel filetype:bitmap"
    assert params["gsrnamespace"] == "6" and params["gsrlimit"] == "5"
    assert params["iiprop"] == "url|size|mime|extmetadata" and params["iiurlwidth"] == "640"
    assert len(rec.requests) == 1  # metadata only, nothing downloaded

    items = _items(response)
    assert [i.title for i in items] == [
        "Tour eiffel at sunrise from the trocadero",
        "Tour Eiffel Wikimedia Commons",
        "Eiffel Tower night lights",
        "Eiffel Tower logo sign",
        "Eiffel Tower 1900 postcard",
    ]  # sorted by search index
    sunrise, pd, nc, restricted, ported = items
    assert sunrise.provider == "wikimedia-commons" and sunrise.media_type == "image"
    assert sunrise.source_url == (
        "https://commons.wikimedia.org/wiki/File:Tour_eiffel_at_sunrise_from_the_trocadero.jpg"
    )
    assert sunrise.file_url.endswith("/Tour_eiffel_at_sunrise_from_the_trocadero.jpg")
    assert sunrise.thumbnail_url.startswith("https://upload.wikimedia.org/wikipedia/commons/thumb/")
    assert (sunrise.width, sunrise.height) == (2336, 3504)
    assert pd.description == "The Eiffel Tower seen from the Champ de Mars & gardens"

    lic = sunrise.license
    assert lic.license_type == "CC-BY-SA-3.0"
    assert lic.author == "Tristan Nitot"
    assert lic.attribution_required is True
    assert lic.attribution_text == (
        "Tour eiffel at sunrise from the trocadero by Tristan Nitot, CC BY-SA 3.0, "
        "via Wikimedia Commons"
    )
    assert lic.license_url == "http://creativecommons.org/licenses/by-sa/3.0/"
    assert lic.source_provider == "wikimedia-commons" and lic.source_url == sunrise.source_url
    assert lic.retrieved_at is not None
    assert pd.license.license_type == "public-domain"
    assert pd.license.attribution_required is False
    assert nc.license.license_type == "CC-BY-NC-4.0"
    assert nc.license.commercial_use_allowed is False
    assert restricted.license.restrictions == ["trademarked", "personality"]
    assert ported.license.license_type == "CC BY-SA 2.0 de"
    assert ported.thumbnail_url is None

    decisions = {i.title: GATE.evaluate(i.license).status for i in items}
    assert decisions == {
        "Tour eiffel at sunrise from the trocadero": RightsStatus.PENDING,  # share-alike
        "Tour Eiffel Wikimedia Commons": RightsStatus.APPROVED,
        "Eiffel Tower night lights": RightsStatus.BLOCKED,  # NC
        "Eiffel Tower logo sign": RightsStatus.PENDING,  # restrictions
        "Eiffel Tower 1900 postcard": RightsStatus.UNKNOWN,  # raw license, fail closed
    }


def test_commons_license_without_artist_and_fallback_to_short_name() -> None:
    lic = commons_license(
        {"LicenseShortName": {"value": "CC0"}, "License": {"value": ""}},
        title="Sky",
        source_url="https://commons.wikimedia.org/wiki/File:Sky.jpg",
    )
    assert lic.license_type == "CC0" and lic.attribution_text == "Sky, CC0, via Wikimedia Commons"
    assert GATE.evaluate(lic).status == RightsStatus.APPROVED
    assert file_title("File:A.b.c.jpeg") == "A.b.c"


def test_rights_gate_outcomes_for_mapped_licenses() -> None:
    def info(raw: str, version: str | None = None, **kw) -> LicenseInfo:
        from cineforge.providers.licenses import build_license_info

        return build_license_info(
            normalize_open_license(raw, version), source_provider="t", source_url="u", **kw
        )

    assert GATE.evaluate(info("cc0")).status == RightsStatus.APPROVED
    assert GATE.evaluate(info("pdm")).status == RightsStatus.APPROVED
    assert (
        GATE.evaluate(info("by", "4.0", attribution_text="X by Y, CC BY 4.0")).status
        == RightsStatus.APPROVED
    )
    assert GATE.evaluate(info("by", "4.0")).status == RightsStatus.PENDING  # no attribution
    assert GATE.evaluate(info("by-nc", "4.0", attribution_text="x")).status == (
        RightsStatus.BLOCKED
    )
    assert GATE.evaluate(info("by-nd", "4.0", attribution_text="x")).status == (
        RightsStatus.BLOCKED
    )
    assert GATE.evaluate(info("GFDL", attribution_text="x")).status == RightsStatus.UNKNOWN
    restricted = info("by", "4.0", attribution_text="x", restrictions=["trademarked"])
    assert GATE.evaluate(restricted).status == RightsStatus.PENDING


def test_commons_check_and_errors() -> None:
    provider, rec = _commons()
    assert provider.check() == (True, "reachable (Wikipedia)")
    assert rec.requests[0].url.host == "commons.wikimedia.org"
    with pytest.raises(ProviderError, match="empty"):
        provider.invoke(request_for(C.MEDIA_SEARCH, "mediawiki-action-api", prompt=None))
    failing, _ = _commons(lambda r: json_response(429, {}))
    with pytest.raises(ProviderError) as info:
        failing.invoke(request_for(C.MEDIA_SEARCH, "mediawiki-action-api"))
    assert info.value.retryable is True


def test_openverse_search_maps_items_and_licenses() -> None:
    provider, rec = _openverse()
    assert isinstance(provider, Provider) and provider.info.models == ["openverse-v1"]
    response = provider.invoke(request_for(C.MEDIA_SEARCH, "openverse-v1", limit=3))
    sent = rec.requests[0]
    assert str(sent.url).startswith("https://api.openverse.org/v1/images/?")
    assert sent.url.params["q"] == "Eiffel Tower"
    assert sent.url.params["page_size"] == "3"
    assert sent.url.params["license_type"] == "commercial,modification"
    assert sent.url.params["mature"] == "false"

    by, by_sa, cc0 = _items(response)
    assert by.title == "Eiffel Tower from the Hilton Hotel"
    assert by.source_url == "https://www.flickr.com/photos/59158146@N00/2672408424"
    assert by.file_url == "https://live.staticflickr.com/3206/2672408424_22d64c2e14_b.jpg"
    assert by.thumbnail_url.endswith("/thumb/") and (by.width, by.height) == (683, 1024)
    assert by.provider == "openverse" and by.description == "Source: flickr"
    assert by.license.license_type == "CC-BY-2.0"
    assert by.license.author == "johntrainor"
    assert by.license.attribution_text.startswith('"Eiffel Tower from the Hilton Hotel" by')
    assert by.license.source_provider == "openverse"
    assert by_sa.license.license_type == "CC-BY-SA-2.0"
    assert cc0.title == "Untitled" and cc0.license.license_type == "CC0"
    assert cc0.license.author is None
    assert [GATE.evaluate(i.license).status for i in (by, by_sa, cc0)] == [
        RightsStatus.APPROVED,
        RightsStatus.PENDING,
        RightsStatus.APPROVED,
    ]


def test_openverse_limit_cap_check_and_errors() -> None:
    provider, rec = _openverse()
    provider.invoke(request_for(C.MEDIA_SEARCH, "openverse-v1", limit=500))
    assert rec.requests[0].url.params["page_size"] == "20"
    ok, detail = provider.check()
    assert ok is True and "240 results" in detail
    assert rec.requests[1].url.params["page_size"] == "1"
    limited, _ = _openverse(lambda r: json_response(429, {"detail": "Request was throttled."}))
    with pytest.raises(ProviderError, match="throttled") as info:
        limited.invoke(request_for(C.MEDIA_SEARCH, "openverse-v1"))
    assert info.value.retryable is True
    ok, detail = limited.check()
    assert ok is False and "429" in detail
