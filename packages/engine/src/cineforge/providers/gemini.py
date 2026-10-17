"""Google Gemini video (Veo) on the Sources page.

The key is ``GEMINI_API_KEY`` or a key saved on Sources. Paid, so it starts disabled.
Priority sits behind the mock video provider, so turning it on does not steal
text-to-video routing. Lena's vlog still calls Higgsfield by name.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

import httpx

from cineforge.config import Settings
from cineforge.contracts.providers import (
    PriceUnit,
    ProviderCapability,
    ProviderError,
    ProviderInfo,
    ProviderRequest,
    ProviderResponse,
    ProviderUsage,
)
from cineforge.providers.http import build_http_client, int_param, request_json

NAME = "gemini"
MODEL = "veo-3.1-generate-preview"
# Mock video is 100. Stay behind it until a production path opts in.
DEFAULT_PRIORITY = 200

KeyResolver = Callable[[str], str | None]


class GeminiProvider:
    default_priority = DEFAULT_PRIORITY

    def __init__(
        self,
        settings: Settings,
        *,
        key_resolver: KeyResolver,
        client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings
        self.key_resolver = key_resolver
        self.base_url = settings.gemini_base_url.rstrip("/")
        self._client = client
        self.info = ProviderInfo(
            name=NAME,
            display_name="Google Gemini",
            capabilities=[ProviderCapability.VIDEO_GENERATION],
            models=[MODEL],
            is_mock=False,
            is_paid=True,
            description="Veo text-to-video with its own audio. Starts off, and it does not "
            "replace Higgsfield on Lena's vlog. Test checks the key for free.",
            requires_key=True,
            key_env_var="GEMINI_API_KEY",
            docs_url="https://ai.google.dev/gemini-api/docs/video",
        )

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = build_http_client(self.settings)
        return self._client

    def estimate_usage(self, request: ProviderRequest) -> ProviderUsage:
        if request.capability != ProviderCapability.VIDEO_GENERATION:
            raise ProviderError(f"{NAME} does not support {request.capability}")
        seconds = int_param(request.parameters, "duration_sec", 6, low=4, high=8, provider=NAME)
        return ProviderUsage(units=Decimal(seconds), unit=PriceUnit.VIDEO_SECOND)

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        raise ProviderError(
            f"{NAME}: listed on Sources. Productions are not switched to Veo yet.",
            retryable=False,
        )

    def check(self, tenant_id: str | None = None) -> tuple[bool, str]:
        """Free key check: list models. Does not start a video."""
        key = self.key_resolver(tenant_id or "")
        if not key:
            return False, "no API key: add one on the Sources page or set GEMINI_API_KEY"
        try:
            data = request_json(
                self.client,
                "GET",
                f"{self.base_url}/v1beta/models",
                provider=NAME,
                headers={"x-goog-api-key": key},
                params={"pageSize": 100},
            )
        except ProviderError as exc:
            return False, str(exc)
        names = [
            str(row.get("name", "")) for row in data.get("models") or [] if isinstance(row, dict)
        ]
        veo = [name for name in names if "veo" in name.lower()]
        if veo:
            return True, f"key valid; video model listed ({veo[0]})"
        return True, f"key valid ({len(names)} models visible)"
