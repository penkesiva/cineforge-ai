"""A3 Media Discovery Agent: federated search across mock media providers.

Rights are NOT decided here: every candidate keeps ``rights_status=UNKNOWN`` and the
orchestrator applies ``RightsGate`` afterwards (fail closed).
"""

from __future__ import annotations

from typing import Literal

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
from cineforge.contracts.providers import ProviderCapability

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
        topic = payload.brief.topic
        slug = slugify(topic, 32)
        self.render_prompt(
            ctx,
            topic=topic,
            claims="; ".join(c.id for c in payload.claims) or "none",
            max_candidates=payload.max_candidates,
            intended_use=payload.intended_use,
        )
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
