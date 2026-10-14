"""Providers shown on the Sources page (status ``planned``) but not implemented yet."""

from __future__ import annotations

from cineforge.contracts.providers import ProviderCapability
from cineforge.providers.registry import PlannedProvider

C = ProviderCapability

PLANNED_PROVIDERS: tuple[PlannedProvider, ...] = (
    PlannedProvider(
        "pexels", "Pexels", (C.MEDIA_SEARCH,), is_paid=False, requires_key=True,
        description="Free stock photos and videos (free API key).",
        docs_url="https://www.pexels.com/api/", planned_phase="Phase 1.5",
    ),
    PlannedProvider(
        "unsplash", "Unsplash", (C.MEDIA_SEARCH,), is_paid=False, requires_key=True,
        description="Free high-resolution stock photos (free API key).",
        docs_url="https://unsplash.com/developers", planned_phase="Phase 1.5",
    ),
    PlannedProvider(
        "pixabay", "Pixabay", (C.MEDIA_SEARCH,), is_paid=False, requires_key=True,
        description="Free stock images, video and music (free API key).",
        docs_url="https://pixabay.com/api/docs/", planned_phase="Phase 1.5",
    ),
    PlannedProvider(
        "tavily", "Tavily", (C.WEB_RESEARCH,), is_paid=True, requires_key=True,
        description="Web search API built for LLM research agents.",
        docs_url="https://docs.tavily.com",
    ),
    PlannedProvider(
        "brave-search", "Brave Search", (C.WEB_RESEARCH,), is_paid=True, requires_key=True,
        description="Independent web search index API.",
        docs_url="https://brave.com/search/api/",
    ),
    PlannedProvider(
        "openai-images", "OpenAI Images", (C.IMAGE_GENERATION, C.IMAGE_EDIT), is_paid=True,
        requires_key=True, description="Image generation and editing.",
        docs_url="https://platform.openai.com/docs/guides/images",
    ),
    PlannedProvider(
        "stability", "Stability AI", (C.IMAGE_GENERATION, C.IMAGE_EDIT), is_paid=True,
        requires_key=True, description="Stable Diffusion image generation and editing.",
        docs_url="https://platform.stability.ai/docs",
    ),
    PlannedProvider(
        "higgsfield", "Higgsfield", (C.IMAGE_TO_VIDEO, C.VOICE_TTS), is_paid=True,
        requires_key=False,
        description="Kling / Seedance image-to-video and Seed Audio voices on your plan "
        "credits (MCP sign-in, no API key). Today: operator-run external generations.",
        docs_url="https://higgsfield.ai/creator-hub/help-center/integrations/what-is-higgsfield-mcp",
        planned_phase="Phase 2",
    ),
    PlannedProvider(
        "runway", "Runway", (C.VIDEO_GENERATION, C.IMAGE_TO_VIDEO), is_paid=True,
        requires_key=True, description="Text- and image-to-video generation.",
        docs_url="https://docs.dev.runwayml.com",
    ),
    PlannedProvider(
        "luma", "Luma Dream Machine", (C.VIDEO_GENERATION, C.IMAGE_TO_VIDEO), is_paid=True,
        requires_key=True, description="Text- and image-to-video generation.",
        docs_url="https://docs.lumalabs.ai",
    ),
    PlannedProvider(
        "elevenlabs", "ElevenLabs", (C.VOICE_TTS, C.SFX_GENERATION), is_paid=True,
        requires_key=True, description="Narration voices and sound effects.",
        docs_url="https://elevenlabs.io/docs",
    ),
    PlannedProvider(
        "stable-audio", "Stable Audio", (C.MUSIC_GENERATION,), is_paid=True,
        requires_key=True, description="Generated music beds.",
        docs_url="https://platform.stability.ai/docs",
    ),
    PlannedProvider(
        "sync-labs", "Sync Labs", (C.LIP_SYNC,), is_paid=True, requires_key=True,
        description="Lip-sync for on-camera characters.",
        docs_url="https://docs.sync.so",
    ),
)  # fmt: skip
