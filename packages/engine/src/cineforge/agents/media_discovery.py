"""A3 Media Discovery Agent: federated search across the ready media providers.

Real providers (e.g. Wikimedia Commons, Openverse) are queried one by one with error
isolation: one failing source never fails the search. Results are de-duplicated and
ranked deterministically (known license, commercial use, portrait aspect, resolution).
The mock catalog is used only when no real media provider is ready.

Rights are NOT decided here: every candidate keeps ``rights_status=UNKNOWN`` and the
orchestrator applies ``RightsGate`` afterwards (fail closed).
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import ValidationError

from cineforge.agents.base import BaseAgent
from cineforge.agents.planning import slugify
from cineforge.contracts.agents import (
    AgentContext,
    AssetCandidate,
    AssetSelection,
    MediaDiscoveryInput,
)
from cineforge.contracts.common import AgentId
from cineforge.contracts.media import LicenseInfo
from cineforge.contracts.providers import (
    MediaSearchItem,
    Provider,
    ProviderCapability,
    ProviderError,
)

log = logging.getLogger(__name__)

SOURCES = ("mock-wikimedia", "mock-openverse", "mock-stock")

MediaType = Literal["image", "video", "audio"]


def _license(kind: str | None, source: str, url: str) -> LicenseInfo | None:
    if kind is None:
        return None
    common = {"source_provider": source, "source_url": url}
    if kind == "CC0":
        return LicenseInfo(
            license_type="CC0",
            license_url="https://creativecommons.org/publicdomain/zero/1.0/",
            commercial_use_allowed=True,
            modifications_allowed=True,
            **common,
        )
    if kind == "public-domain":
        return LicenseInfo(
            license_type="public-domain",
            commercial_use_allowed=True,
            modifications_allowed=True,
            **common,
        )
    if kind == "CC-BY-4.0":
        return LicenseInfo(
            license_type="CC-BY-4.0",
            license_url="https://creativecommons.org/licenses/by/4.0/",
            author="Example Photographer",
            attribution_text="Photo: Example Photographer, CC BY 4.0, via mock-openverse",
            attribution_required=True,
            commercial_use_allowed=True,
            modifications_allowed=True,
            **common,
        )
    if kind == "CC-BY-NC-4.0":
        return LicenseInfo(
            license_type="CC-BY-NC-4.0",
            license_url="https://creativecommons.org/licenses/by-nc/4.0/",
            author="Example Archivist",
            attribution_text="Image: Example Archivist, CC BY-NC 4.0",
            attribution_required=True,
            commercial_use_allowed=False,
            modifications_allowed=True,
            restrictions=["non-commercial"],
            **common,
        )
    if kind == "commercial":
        return LicenseInfo(
            license_type="commercial",
            author="Mock Stock Contributor",
            commercial_use_allowed=True,
            modifications_allowed=True,
            restrictions=["no standalone redistribution"],
            **common,
        )
    raise ValueError(kind)


# (source, media type, title suffix, license kind, score)
_CATALOG: tuple[tuple[str, MediaType, str, str | None, float], ...] = (
    ("mock-wikimedia", "image", "archival photograph", "public-domain", 0.93),
    ("mock-wikimedia", "image", "engraving", "CC0", 0.86),
    ("mock-openverse", "image", "wide view", "CC-BY-4.0", 0.84),
    ("mock-openverse", "image", "historic postcard", "CC-BY-NC-4.0", 0.81),
    ("mock-stock", "video", "aerial establishing clip", "commercial", 0.79),
    ("mock-openverse", "image", "detail close-up", None, 0.77),
    ("mock-stock", "image", "golden hour still", "CC0", 0.74),
    ("mock-wikimedia", "image", "street scene", "CC-BY-4.0", 0.7),
)


class MediaDiscoveryAgent(BaseAgent):
    agent_id = AgentId.MEDIA_DISCOVERY
    input_model = MediaDiscoveryInput
    output_model = AssetSelection

    def execute(self, ctx: AgentContext, payload: MediaDiscoveryInput) -> AssetSelection:
        self.render_prompt(
            ctx,
            topic=payload.brief.topic,
            claims="; ".join(c.id for c in payload.claims) or "none",
            max_candidates=payload.max_candidates,
            intended_use=payload.intended_use,
        )
        ready = ctx.providers.route_all(ProviderCapability.MEDIA_SEARCH, tenant_id=ctx.tenant_id)
        real = [p for p in ready if not p.info.is_mock]
        if real:
            return self._federated(ctx, payload, real)
        if ready:
            return self._mock_catalog(ctx, payload)
        self._note(ctx, "no media search provider is ready; scenes fall back to generation")
        return AssetSelection(candidates=[], selected_ids=[])

    # ------------------------------------------------------------------ live
    def _federated(
        self, ctx: AgentContext, payload: MediaDiscoveryInput, providers: list[Provider]
    ) -> AssetSelection:
        topic = payload.brief.topic
        per_provider = max(4, payload.max_candidates // len(providers) + 2)
        items: list[tuple[int, MediaSearchItem]] = []
        failures: list[str] = []
        for provider in providers:
            name = provider.info.name
            try:
                response, _ = self.call_provider(
                    ctx,
                    ProviderCapability.MEDIA_SEARCH,
                    sub_scope=f"search-{name}",
                    provider_name=name,
                    prompt=topic,
                    parameters={"query": topic, "limit": per_provider, "media_type": "image"},
                )
            except ProviderError as exc:
                log.warning("media search via %s failed: %s", name, exc)
                failures.append(f"{name}: {exc}")
                continue
            for rank, raw in enumerate(response.output_data.get("items", [])):
                try:
                    items.append((rank, MediaSearchItem.model_validate(raw)))
                except ValidationError:
                    continue
        if failures:
            self._note(ctx, "media sources failed: " + "; ".join(failures))
        prefix = ctx.production_id.removeprefix("prod_")[-12:]
        seen: set[str] = set()
        candidates: list[AssetCandidate] = []
        for rank, item in items:
            key = _dedupe_key(item)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                AssetCandidate(
                    candidate_id=f"asset_cand_{prefix}_{len(candidates) + 1:02d}",
                    provider=item.provider,
                    media_type=item.media_type,
                    title=item.title[:200],
                    source_url=item.source_url,
                    thumbnail_url=item.thumbnail_url or item.file_url,
                    width=item.width,
                    height=item.height,
                    license=item.license,
                    score=score_item(item, rank, payload.intended_use),
                )
            )
        ranked = sorted(candidates, key=lambda c: (-c.score, c.candidate_id))
        kept = ranked[: payload.max_candidates]
        kept_ids = {c.candidate_id for c in kept}
        return AssetSelection(
            candidates=[c for c in candidates if c.candidate_id in kept_ids],
            selected_ids=[c.candidate_id for c in kept],
        )

    # ------------------------------------------------------------------ mock
    def _mock_catalog(self, ctx: AgentContext, payload: MediaDiscoveryInput) -> AssetSelection:
        topic = payload.brief.topic
        slug = slugify(topic, 32)
        for source in SOURCES:
            self.call_provider(
                ctx,
                ProviderCapability.MEDIA_SEARCH,
                sub_scope=f"search-{source}",
                prompt=topic,
                parameters={"source": source, "query": topic, "limit": payload.max_candidates},
            )
        prefix = ctx.production_id.removeprefix("prod_")[-12:]
        candidates: list[AssetCandidate] = []
        for idx, (source, media_type, suffix, kind, score) in enumerate(_CATALOG, 1):
            if idx > payload.max_candidates:
                break
            url = f"https://example.org/{source}/{slug}/{idx:02d}"
            candidates.append(
                AssetCandidate(
                    candidate_id=f"asset_cand_{prefix}_{idx:02d}",
                    provider=source,
                    media_type=media_type,
                    title=f"{topic} - {suffix}",
                    source_url=url,
                    thumbnail_url=f"{url}/thumb",
                    width=1920 if media_type == "video" else 1600,
                    height=1080 if media_type == "video" else 2400,
                    license=_license(kind, source, url),
                    score=score,
                )
            )
        ranked = sorted(candidates, key=lambda c: c.score, reverse=True)
        return AssetSelection(candidates=candidates, selected_ids=[c.candidate_id for c in ranked])


def _dedupe_key(item: MediaSearchItem) -> str:
    url = (item.file_url or item.source_url).split("?", 1)[0].rstrip("/").lower()
    return url or item.title.strip().lower()


def score_item(item: MediaSearchItem, rank: int, intended_use: str) -> float:
    """Deterministic ranking: rights first, then fit for a 9:16 short, then provider rank."""
    score = 0.4
    lic = item.license
    if lic is not None and lic.license_type:
        score += 0.2
        if intended_use != "commercial" or lic.commercial_use_allowed:
            score += 0.1
    if item.width and item.height:
        if item.height >= item.width:
            score += 0.1
        if min(item.width, item.height) >= 1080:
            score += 0.1
    score += max(0.0, 0.1 - 0.02 * rank)
    return round(min(1.0, score), 3)
