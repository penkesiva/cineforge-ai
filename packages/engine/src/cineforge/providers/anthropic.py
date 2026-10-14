"""Anthropic Messages API adapter (``llm_text``, paid, key required).

Structured output: when ``parameters["response_schema"]`` is set the request forces a
single tool call (``tool_choice``) whose ``input`` is returned in
``output_data["structured"]``. The key is looked up per tenant on every call through
``key_resolver`` (the registry: env ``ANTHROPIC_API_KEY`` beats a stored key).
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from decimal import Decimal
from typing import Any

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
    UsageLine,
)
from cineforge.providers.http import build_http_client, int_param, request_json

NAME = "anthropic"
API_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 1024
MAX_TOKENS_CAP = 64000
DEFAULT_TEMPERATURE = 0.4
DEFAULT_SCHEMA_NAME = "emit"
TOOL_OVERHEAD_TOKENS = 300
CHARS_PER_TOKEN = 4

KeyResolver = Callable[[str], str | None]


def token_usage(input_tokens: int, output_tokens: int) -> ProviderUsage:
    tokens_in = Decimal(max(0, input_tokens)) / 1000
    tokens_out = Decimal(max(0, output_tokens)) / 1000
    return ProviderUsage(
        units=tokens_in + tokens_out,
        unit=PriceUnit.TOKENS_1K,
        breakdown=[
            UsageLine(unit=PriceUnit.INPUT_TOKENS_1K, units=tokens_in),
            UsageLine(unit=PriceUnit.OUTPUT_TOKENS_1K, units=tokens_out),
        ],
    )


class AnthropicProvider:
    def __init__(
        self,
        settings: Settings,
        *,
        key_resolver: KeyResolver,
        models: list[str] | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings
        self.key_resolver = key_resolver
        self.base_url = settings.anthropic_base_url.rstrip("/")
        self._client = client
        ordered = [settings.anthropic_model, *(models or [])]
        self.info = ProviderInfo(
            name=NAME,
            display_name="Anthropic Claude",
            capabilities=[ProviderCapability.LLM_TEXT],
            models=list(dict.fromkeys(m for m in ordered if m)),
            is_mock=False,
            is_paid=True,
            description="Claude models for research synthesis, planning and scripts "
            "(structured output via tool use). Billed per input/output token.",
            requires_key=True,
            key_env_var="ANTHROPIC_API_KEY",
            docs_url="https://docs.anthropic.com",
        )

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = build_http_client(self.settings)
        return self._client

    # ------------------------------------------------------------------ helpers
    def _key(self, tenant_id: str) -> str:
        key = self.key_resolver(tenant_id)
        if not key:
            raise ProviderError(
                f"{NAME}: no API key for tenant {tenant_id!r}; add one on the Sources page "
                "or set ANTHROPIC_API_KEY",
                retryable=False,
            )
        return key

    def _headers(self, key: str) -> dict[str, str]:
        return {"x-api-key": key, "anthropic-version": API_VERSION}

    @staticmethod
    def _schema(request: ProviderRequest) -> dict[str, Any] | None:
        schema = request.parameters.get("response_schema")
        if schema is None:
            return None
        if not isinstance(schema, dict):
            raise ProviderError(f"{NAME}: response_schema must be a JSON Schema object")
        return schema

    @staticmethod
    def _schema_name(request: ProviderRequest) -> str:
        return str(request.parameters.get("schema_name") or DEFAULT_SCHEMA_NAME)

    @staticmethod
    def _max_tokens(request: ProviderRequest) -> int:
        return int_param(
            request.parameters,
            "max_tokens",
            DEFAULT_MAX_TOKENS,
            low=1,
            high=MAX_TOKENS_CAP,
            provider=NAME,
        )

    def build_body(self, request: ProviderRequest) -> dict[str, Any]:
        params = request.parameters
        body: dict[str, Any] = {
            "model": request.model,
            "max_tokens": self._max_tokens(request),
            "temperature": float(params.get("temperature", DEFAULT_TEMPERATURE)),
            "messages": [{"role": "user", "content": request.prompt or ""}],
        }
        if params.get("system"):
            body["system"] = str(params["system"])
        schema = self._schema(request)
        if schema is not None:
            name = self._schema_name(request)
            body["tools"] = [
                {
                    "name": name,
                    "description": "Return the result as structured data",
                    "input_schema": schema,
                }
            ]
            body["tool_choice"] = {"type": "tool", "name": name}
        return body

    # ------------------------------------------------------------------ Provider
    def estimate_usage(self, request: ProviderRequest) -> ProviderUsage:
        if request.capability != ProviderCapability.LLM_TEXT:
            raise ProviderError(f"{NAME} does not support {request.capability}")
        schema = self._schema(request)
        chars = len(request.prompt or "") + len(str(request.parameters.get("system") or ""))
        if schema is not None:
            chars += len(json.dumps(schema))
        tokens_in = math.ceil(chars / CHARS_PER_TOKEN)
        if schema is not None:
            tokens_in += TOOL_OVERHEAD_TOKENS
        return token_usage(tokens_in, self._max_tokens(request))

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        if request.capability != ProviderCapability.LLM_TEXT:
            raise ProviderError(f"{NAME} does not support {request.capability}")
        key = self._key(request.tenant_id)
        body = self.build_body(request)
        started = time.monotonic()
        data = request_json(
            self.client,
            "POST",
            f"{self.base_url}/v1/messages",
            provider=NAME,
            headers=self._headers(key),
            json=body,
        )
        latency_ms = int((time.monotonic() - started) * 1000)
        texts: list[str] = []
        structured: dict[str, Any] | None = None
        tool_name = self._schema_name(request) if "tools" in body else None
        for block in data.get("content") or []:
            kind = block.get("type")
            if kind == "text":
                texts.append(str(block.get("text", "")))
            elif (
                kind == "tool_use"
                and structured is None
                and (tool_name is None or block.get("name") == tool_name)
            ):
                payload = block.get("input")
                structured = payload if isinstance(payload, dict) else {}
        usage = data.get("usage") or {}
        output_data: dict[str, Any] = {
            "stop_reason": data.get("stop_reason"),
            "resolved_model": data.get("model"),
        }
        if structured is not None:
            output_data["structured"] = structured
        return ProviderResponse(
            provider=NAME,
            model=request.model,
            capability=ProviderCapability.LLM_TEXT,
            provider_request_id=str(data.get("id") or ""),
            output_text="".join(texts),
            output_data=output_data,
            usage=token_usage(
                int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)
            ),
            latency_ms=latency_ms,
        )

    # ------------------------------------------------------------------ check
    def check(self, tenant_id: str | None = None) -> tuple[bool, str]:
        """Free key validation: ``GET /v1/models`` (no tokens billed)."""
        key = self.key_resolver(tenant_id or "")
        if not key:
            return False, "no API key: add one on the Sources page or set ANTHROPIC_API_KEY"
        try:
            data = request_json(
                self.client,
                "GET",
                f"{self.base_url}/v1/models",
                provider=NAME,
                headers=self._headers(key),
                params={"limit": 100},
            )
        except ProviderError as exc:
            return False, str(exc)
        available = [str(m.get("id")) for m in data.get("data") or [] if isinstance(m, dict)]
        model = self.settings.anthropic_model
        # The list holds dated snapshots (e.g. claude-sonnet-4-5-20250929); aliases match by prefix.
        if available and not any(a == model or a.startswith(f"{model}-") for a in available):
            return True, f"key valid; model {model!r} not among {len(available)} listed models"
        return True, f"key valid ({len(available)} models visible)"
