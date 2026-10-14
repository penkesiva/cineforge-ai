from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest
from cineforge.config import Settings
from cineforge.contracts.common import AgentId
from cineforge.contracts.cost import LedgerStatus
from cineforge.contracts.providers import (
    PriceUnit,
    Provider,
    ProviderCapability,
    ProviderError,
    UsageLine,
)
from cineforge.cost.factory import load_price_catalog
from cineforge.cost.memory import InMemoryBudgetService
from cineforge.providers.anthropic import AnthropicProvider
from cineforge.providers.factory import anthropic_models, build_paid_call_guard
from provider_fakes import Recorder, json_response, request_for

C = ProviderCapability
KEY = "sk-ant-test-0000000000001234"
SCHEMA = {
    "type": "object",
    "properties": {"topic": {"type": "string"}, "claims": {"type": "array"}},
    "required": ["topic", "claims"],
}


def _provider(handler, *, key: str | None = KEY, settings: Settings | None = None):
    settings = settings or Settings()
    rec = Recorder(handler)
    keys: list[str] = []

    def resolver(tenant_id: str) -> str | None:
        keys.append(tenant_id)
        return key

    provider = AnthropicProvider(
        settings,
        key_resolver=resolver,
        models=anthropic_models(settings),
        client=rec.client(settings),
    )
    return provider, rec, keys


def test_info_matches_price_catalog() -> None:
    provider, _, _ = _provider(lambda r: json_response(200, "anthropic_text.json"))
    assert isinstance(provider, Provider)
    info = provider.info
    assert info.name == "anthropic" and info.capabilities == [C.LLM_TEXT]
    assert info.is_paid and not info.is_mock and info.requires_key
    assert info.key_env_var == "ANTHROPIC_API_KEY"
    assert info.docs_url == "https://docs.anthropic.com"
    assert info.models == ["claude-sonnet-4-5", "claude-haiku-4-5"]
    haiku_first = Settings(anthropic_model="claude-haiku-4-5")
    assert anthropic_models(haiku_first) == ["claude-haiku-4-5", "claude-sonnet-4-5"]
    catalog = load_price_catalog(Settings())
    for model in info.models:
        for unit in (PriceUnit.INPUT_TOKENS_1K, PriceUnit.OUTPUT_TOKENS_1K):
            assert catalog.get("anthropic", model, unit).unit_price > 0


def test_structured_output_via_forced_tool() -> None:
    provider, rec, keys = _provider(lambda r: json_response(200, "anthropic_tool_use.json"))
    req = request_for(
        C.LLM_TEXT,
        "claude-sonnet-4-5",
        prompt="Summarize the sources",
        response_schema=SCHEMA,
        schema_name="research_digest",
        system="You are a careful researcher.",
        max_tokens=2000,
        temperature=0.2,
    )
    response = provider.invoke(req)
    sent = rec.requests[0]
    assert sent.method == "POST"
    assert str(sent.url) == "https://api.anthropic.com/v1/messages"
    assert sent.headers["x-api-key"] == KEY
    assert sent.headers["anthropic-version"] == "2023-06-01"
    body = json.loads(sent.content)
    assert body["model"] == "claude-sonnet-4-5"
    assert body["max_tokens"] == 2000 and body["temperature"] == 0.2
    assert body["system"] == "You are a careful researcher."
    assert body["messages"] == [{"role": "user", "content": "Summarize the sources"}]
    assert body["tools"] == [
        {
            "name": "research_digest",
            "description": "Return the result as structured data",
            "input_schema": SCHEMA,
        }
    ]
    assert body["tool_choice"] == {"type": "tool", "name": "research_digest"}
    assert keys == ["tenant_demo"]

    assert response.output_data["structured"]["topic"] == "Eiffel Tower"
    assert response.output_data["stop_reason"] == "tool_use"
    assert response.output_text == "Here is the structured result."
    assert response.provider_request_id == "msg_01ToolUseFixture"
    assert response.model == "claude-sonnet-4-5"
    usage = response.usage
    assert usage.unit == PriceUnit.TOKENS_1K and usage.units == Decimal("1.801")
    assert usage.breakdown == [
        UsageLine(unit=PriceUnit.INPUT_TOKENS_1K, units=Decimal("1.234")),
        UsageLine(unit=PriceUnit.OUTPUT_TOKENS_1K, units=Decimal("0.567")),
    ]


def test_plain_text_defaults() -> None:
    provider, rec, _ = _provider(lambda r: json_response(200, "anthropic_text.json"))
    response = provider.invoke(request_for(C.LLM_TEXT, "claude-haiku-4-5", prompt="Hook?"))
    body = json.loads(rec.requests[0].content)
    assert body["max_tokens"] == 1024 and body["temperature"] == 0.4
    assert "system" not in body and "tools" not in body and "tool_choice" not in body
    assert (
        response.output_text == "In 1889 the Eiffel Tower was the tallest structure in the world."
    )
    assert "structured" not in response.output_data
    assert response.output_data["stop_reason"] == "end_turn"
    assert response.usage.units == Decimal("0.055")


def test_custom_base_url() -> None:
    settings = Settings(anthropic_base_url="https://proxy.example.test/anthropic/")
    provider, rec, _ = _provider(
        lambda r: json_response(200, "anthropic_text.json"), settings=settings
    )
    provider.invoke(request_for(C.LLM_TEXT, "claude-sonnet-4-5"))
    assert str(rec.requests[0].url) == "https://proxy.example.test/anthropic/v1/messages"


def test_estimate_usage_shape() -> None:
    provider, rec, keys = _provider(lambda r: json_response(200, "anthropic_text.json"))
    plain = provider.estimate_usage(request_for(C.LLM_TEXT, "claude-sonnet-4-5", prompt="x" * 400))
    assert plain.breakdown == [
        UsageLine(unit=PriceUnit.INPUT_TOKENS_1K, units=Decimal("0.1")),
        UsageLine(unit=PriceUnit.OUTPUT_TOKENS_1K, units=Decimal("1.024")),
    ]
    assert plain.unit == PriceUnit.TOKENS_1K and plain.units == Decimal("1.124")
    structured = provider.estimate_usage(
        request_for(
            C.LLM_TEXT,
            "claude-sonnet-4-5",
            prompt="x" * 400,
            system="y" * 40,
            response_schema=SCHEMA,
            max_tokens=500,
        )
    )
    expected_in = (400 + 40 + len(json.dumps(SCHEMA)) + 3) // 4 + 300
    assert structured.breakdown[0].units == Decimal(expected_in) / 1000
    assert structured.breakdown[1].units == Decimal("0.5")
    assert rec.requests == [] and keys == []  # estimating never calls out or needs a key


def test_missing_key_fails_without_calling() -> None:
    provider, rec, _ = _provider(lambda r: json_response(200, "anthropic_text.json"), key=None)
    with pytest.raises(ProviderError, match="no API key") as info:
        provider.invoke(request_for(C.LLM_TEXT, "claude-sonnet-4-5"))
    assert info.value.retryable is False and rec.requests == []


def test_401_and_429() -> None:
    provider, _, _ = _provider(lambda r: json_response(401, "anthropic_401.json"))
    with pytest.raises(ProviderError, match="invalid or unauthorized API key") as info:
        provider.invoke(request_for(C.LLM_TEXT, "claude-sonnet-4-5"))
    assert info.value.retryable is False and KEY not in str(info.value)
    provider, _, _ = _provider(lambda r: json_response(429, "anthropic_429.json"))
    with pytest.raises(ProviderError, match="rate limited") as info:
        provider.invoke(request_for(C.LLM_TEXT, "claude-sonnet-4-5"))
    assert info.value.retryable is True
    provider, _, _ = _provider(lambda r: httpx.Response(529, json={"error": {"message": "x"}}))
    with pytest.raises(ProviderError, match="overloaded") as info:
        provider.invoke(request_for(C.LLM_TEXT, "claude-sonnet-4-5"))
    assert info.value.retryable is True


def test_check_uses_free_models_endpoint() -> None:
    provider, rec, _ = _provider(lambda r: json_response(200, "anthropic_models.json"))
    ok, detail = provider.check("tenant_demo")
    assert ok is True and "key valid" in detail and "not among" not in detail
    sent = rec.requests[0]
    assert sent.method == "GET" and sent.url.path == "/v1/models"
    assert sent.headers["x-api-key"] == KEY
    bad, _, _ = _provider(lambda r: json_response(401, "anthropic_401.json"))
    ok, detail = bad.check("tenant_demo")
    assert ok is False and "invalid or unauthorized API key" in detail
    missing, rec, _ = _provider(lambda r: json_response(200, "anthropic_models.json"), key=None)
    ok, detail = missing.check("tenant_demo")
    assert ok is False and "no API key" in detail and rec.requests == []


def test_through_guard_prices_input_and_output() -> None:
    provider, _, _ = _provider(lambda r: json_response(200, "anthropic_tool_use.json"))
    budget = InMemoryBudgetService()
    budget.create_budget(tenant_id="tenant_demo", production_id="prod_t", limit=Decimal("5"))
    settings = Settings(allow_paid_providers=True)
    guard = build_paid_call_guard(settings, budget, load_price_catalog(settings))
    req = request_for(
        C.LLM_TEXT, "claude-sonnet-4-5", response_schema=SCHEMA, schema_name="research_digest"
    )
    response, event = guard.call(provider, req, agent_id=AgentId.RESEARCH)
    # 1234 in x $0.003/1k + 567 out x $0.015/1k
    assert event.actual_cost == Decimal("0.012207")
    assert event.status == LedgerStatus.COMMITTED
    assert event.provider_request_id == "msg_01ToolUseFixture"
    assert event.usage_unit == PriceUnit.TOKENS_1K and event.usage_units == Decimal("1.801")
    assert event.unit_price_version == "anthropic-2026-10"
    assert response.output_data["structured"]["claims"]
