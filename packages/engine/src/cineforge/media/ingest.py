"""Download rights-approved A3 stills into storage with their license metadata.

Only candidates from real open-license sources are ingested, and only when the rights
gate approves them *now* (re-evaluated, never trusted from the candidate). One asset per
candidate and production: a repeat call returns the existing record. Downloads are free
but still logged in the ledger (``<provider>/file-download``, unit ``request``) when the
production has a budget.
"""

from __future__ import annotations

import logging
import re
from decimal import Decimal
from urllib.parse import unquote, urlsplit

import httpx

from cineforge.contracts.agents import AgentRunStatus, AssetCandidate, AssetSelection
from cineforge.contracts.common import AgentId, money
from cineforge.contracts.cost import ReservationRequest
from cineforge.contracts.manifest import ProductionManifest
from cineforge.contracts.media import (
    AssetKind,
    AssetOrigin,
    AssetRecord,
    LicenseInfo,
    RightsStatus,
    storage_key,
)
from cineforge.contracts.providers import PriceUnit, ProviderCapability, ProviderError
from cineforge.media.download import DownloadError, Resolver, download, resolve_host
from cineforge.media.rights import PUBLIC_DOMAIN, normalize_license_type
from cineforge.providers import commons, openverse
from cineforge.providers.http import build_http_client, request_json
from cineforge.providers.mediawiki import mediawiki_get
from cineforge.runtime import Runtime

log = logging.getLogger(__name__)

INGESTABLE_PROVIDERS = frozenset({commons.NAME, openverse.NAME})
DOWNLOAD_MODEL = "file-download"
TARGET_WIDTH = 1920
MAX_IMAGE_BYTES = 25 * 1024 * 1024
IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp")
_EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
_OPENVERSE_ID = re.compile(r"/v1/images/([0-9a-fA-F-]{36})/")


def latest_selection(rt: Runtime, manifest: ProductionManifest) -> AssetSelection | None:
    """The newest succeeded A3 output for the production, if any."""
    runs = rt.agent_runs.list_for_production(manifest.production_id, manifest.tenant_id)
    for run in reversed(runs):
        if (
            run.status == AgentRunStatus.SUCCEEDED
            and run.output_model == AssetSelection.__name__
            and run.output is not None
        ):
            return AssetSelection.model_validate(run.output)
    return None


def candidates_by_id(selection: AssetSelection | None) -> dict[str, AssetCandidate]:
    return {c.candidate_id: c for c in selection.candidates} if selection else {}


def commons_file_title(source_url: str) -> str | None:
    """'https://commons.wikimedia.org/wiki/File:A_b.jpg' -> 'File:A b.jpg'."""
    path = unquote(urlsplit(source_url).path)
    if "/wiki/" not in path:
        return None
    title = path.split("/wiki/", 1)[1].replace("_", " ")
    return title if title.startswith("File:") else None


def resolve_image_url(client: httpx.Client, candidate: AssetCandidate) -> str | None:
    """Full-resolution (max ``TARGET_WIDTH`` wide) https URL for a candidate, or None."""
    try:
        if candidate.provider == commons.NAME:
            title = commons_file_title(candidate.source_url)
            if title is None:
                return None
            body = mediawiki_get(
                client,
                commons.API_URL,
                {"action": "query", "titles": title, "prop": "imageinfo",
                 "iiprop": "url", "iiurlwidth": TARGET_WIDTH},
                provider=commons.NAME,
            )  # fmt: skip
            pages = (body.get("query") or {}).get("pages") or []
            infos = (pages[0].get("imageinfo") or []) if pages else []
            if not infos:
                return None
            return infos[0].get("thumburl") or infos[0].get("url")
        if candidate.provider == openverse.NAME:
            match = _OPENVERSE_ID.search(candidate.thumbnail_url or "")
            if match is None:
                return candidate.thumbnail_url
            body = request_json(
                client, "GET", f"{openverse.API_URL}{match.group(1)}/", provider=openverse.NAME
            )
            return body.get("url") or candidate.thumbnail_url
    except ProviderError as exc:
        log.warning("could not resolve %s: %s", candidate.candidate_id, exc)
    return None


def find_ingested(
    rt: Runtime, manifest: ProductionManifest, candidate_id: str
) -> AssetRecord | None:
    for asset in rt.assets.list_for_production(manifest.production_id, manifest.tenant_id):
        if asset.kind == AssetKind.IMAGE and asset.metadata.get("candidate_id") == candidate_id:
            return asset
    return None


def _origin(license: LicenseInfo) -> AssetOrigin:
    return (
        AssetOrigin.PUBLIC_DOMAIN
        if normalize_license_type(license.license_type) in PUBLIC_DOMAIN
        else AssetOrigin.OPEN_LICENSE
    )


def _log_download(rt: Runtime, manifest: ProductionManifest, candidate: AssetCandidate) -> None:
    if rt.budget.get_budget(manifest.production_id) is None:
        return
    entry = rt.price_catalog.get(candidate.provider, DOWNLOAD_MODEL, PriceUnit.REQUEST)
    event = rt.budget.reserve(
        ReservationRequest(
            tenant_id=manifest.tenant_id,
            production_id=manifest.production_id,
            agent_id=AgentId.EDITOR_QC,
            provider=candidate.provider,
            model=DOWNLOAD_MODEL,
            capability=ProviderCapability.MEDIA_SEARCH,
            usage_units=Decimal(1),
            usage_unit=PriceUnit.REQUEST,
            unit_price_version=entry.version,
            estimated_cost=money(entry.unit_price),
            idempotency_key=f"{manifest.production_id}:ingest:{candidate.candidate_id}",
        )
    )
    rt.budget.commit(event.event_id, actual_cost=money(entry.unit_price))


def ingest_still(
    rt: Runtime,
    manifest: ProductionManifest,
    candidate: AssetCandidate,
    *,
    client: httpx.Client | None = None,
    resolver: Resolver = resolve_host,
) -> AssetRecord | None:
    """Download one approved still; returns None when it cannot or must not be used."""
    if candidate.media_type != "image" or candidate.provider not in INGESTABLE_PROVIDERS:
        return None
    existing = find_ingested(rt, manifest, candidate.candidate_id)
    if existing is not None:
        return existing
    decision = rt.rights_gate.evaluate(candidate.license)
    if decision.status != RightsStatus.APPROVED or candidate.license is None:
        log.info("skip %s: rights %s", candidate.candidate_id, decision.status.value)
        return None
    http = client or build_http_client(rt.settings)
    url = resolve_image_url(http, candidate)
    if not url:
        return None
    try:
        fetched = download(
            http, url, allowed_types=IMAGE_TYPES, max_bytes=MAX_IMAGE_BYTES, resolver=resolver
        )
    except DownloadError as exc:
        log.warning("download of %s failed: %s", candidate.candidate_id, exc)
        return None
    _log_download(rt, manifest, candidate)
    ext = _EXTENSIONS[fetched.content_type]
    key = storage_key(
        manifest.tenant_id,
        manifest.production_id,
        AssetKind.IMAGE,
        f"{candidate.candidate_id}.{ext}",
    )
    stored = rt.storage.put_bytes(key, fetched.data, fetched.content_type)
    record = AssetRecord(
        tenant_id=manifest.tenant_id,
        production_id=manifest.production_id,
        kind=AssetKind.IMAGE,
        origin=_origin(candidate.license),
        storage_backend=stored.backend,
        storage_key=stored.key,
        uri=stored.uri,
        content_type=stored.content_type,
        size_bytes=stored.size_bytes,
        sha256=stored.sha256,
        source_url=candidate.source_url,
        source_provider=candidate.provider,
        license=candidate.license,
        rights=decision,
        metadata={
            "candidate_id": candidate.candidate_id,
            "title": candidate.title,
            "download_url": fetched.final_url,
        },
    )
    return rt.assets.add(record)
