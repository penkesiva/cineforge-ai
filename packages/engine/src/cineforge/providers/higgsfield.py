"""Higgsfield constants shared by external generations (operator-run via MCP) and the
Phase 2 connector. Results are downloaded from the provider CDN only (allowlist)."""

from __future__ import annotations

from cineforge.contracts.media import AssetKind
from cineforge.contracts.providers import ProviderCapability

NAME = "higgsfield"
MCP_URL = "https://mcp.higgsfield.ai/mcp"

# Generation results (video and audio) are served from this CloudFront distribution.
RESULT_HOSTS: tuple[str, ...] = ("d8j0ntlcm91z4.cloudfront.net", ".higgsfield.ai")
MAX_RESULT_BYTES = 200 * 1024 * 1024

OUTPUT_KINDS: dict[ProviderCapability, AssetKind] = {
    ProviderCapability.IMAGE_TO_VIDEO: AssetKind.VIDEO,
    ProviderCapability.VIDEO_GENERATION: AssetKind.VIDEO,
    ProviderCapability.VOICE_TTS: AssetKind.AUDIO,
    ProviderCapability.IMAGE_GENERATION: AssetKind.IMAGE,
}
