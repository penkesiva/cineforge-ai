"""BaseAgent: common plumbing for the 10 logical agents.

Phase 0 rule: agents never parse provider output text. They build typed artifacts
deterministically from the brief/theme (mock reasoning). Provider calls exist for
cost accounting and to attach optional notes, and they ALWAYS go through
``ctx.paid_calls`` (``PaidCallGuard``: price lookup -> budget reservation -> invoke).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, ClassVar

from pydantic import BaseModel

from cineforge.agents.prompts import PromptLibrary, PromptTemplate
from cineforge.contracts.agents import AgentContext, AgentDefinition, agent_definition
from cineforge.contracts.common import AgentId
from cineforge.contracts.cost import LedgerEvent
from cineforge.contracts.providers import (
    Provider,
    ProviderCapability,
    ProviderError,
    ProviderRequest,
    ProviderResponse,
)

log = logging.getLogger(__name__)

# Keys agents write into ``AgentContext.extras`` (read by the orchestrator).
LEDGER_EVENTS = "ledger_events"
PROMPT_TEMPLATES = "prompt_templates"
NOTES = "notes"


class BaseAgent(ABC):
    agent_id: ClassVar[AgentId]
    input_model: ClassVar[type[BaseModel]]
    output_model: ClassVar[type[BaseModel]]

    def __init__(self, prompts: PromptLibrary) -> None:
        self.definition: AgentDefinition = agent_definition(self.agent_id)
        self.prompts = prompts

    # ------------------------------------------------------------------ Agent protocol
    def run(self, ctx: AgentContext, payload: BaseModel) -> BaseModel:
        if not isinstance(payload, self.input_model):
            payload = self.input_model.model_validate(payload.model_dump())
        return self.execute(ctx, payload)

    @abstractmethod
    def execute(self, ctx: AgentContext, payload: Any) -> BaseModel: ...

    # ------------------------------------------------------------------ helpers
    @property
    def template(self) -> PromptTemplate:
        return self.prompts.get_or_fallback(
            self.definition.prompt_template_id, self.definition.prompt_template_version
        )

    def render_prompt(self, ctx: AgentContext, **values: Any) -> str:
        template = self.template
        refs = ctx.extras.setdefault(PROMPT_TEMPLATES, [])
        if template.ref not in refs:
            refs.append(template.ref)
        return template.render(**values)

    def call_provider(
        self,
        ctx: AgentContext,
        capability: ProviderCapability,
        *,
        sub_scope: str | None = None,
        provider_name: str | None = None,
        model: str | None = None,
        prompt: str | None = None,
        negative_prompt: str | None = None,
        seed: int | None = None,
        scene_id: str | None = None,
        shot_id: str | None = None,
        reference_asset_ids: list[str] | None = None,
        parameters: dict[str, Any] | None = None,
        attempt: int | None = None,
        retry_reason: str | None = None,
    ) -> tuple[ProviderResponse, LedgerEvent]:
        """Route a provider and call it through the PaidCallGuard (budget reserved first)."""
        provider = self._resolve_provider(ctx, capability, provider_name)
        key = ctx.idempotency_key if sub_scope is None else f"{ctx.idempotency_key}/{sub_scope}"
        request = ProviderRequest(
            tenant_id=ctx.tenant_id,
            production_id=ctx.production_id,
            scene_id=scene_id,
            shot_id=shot_id,
            capability=capability,
            model=model or self._default_model(ctx, provider),
            prompt=prompt,
            negative_prompt=negative_prompt,
            seed=seed,
            reference_asset_ids=list(reference_asset_ids or []),
            parameters=dict(parameters or {}),
            idempotency_key=key,
        )
        response, event = ctx.paid_calls.call(
            provider,
            request,
            agent_id=self.agent_id,
            attempt=attempt or ctx.attempt,
            retry_reason=retry_reason,
        )
        ctx.extras.setdefault(LEDGER_EVENTS, []).append(event)
        return response, event

    def _llm(
        self,
        ctx: AgentContext,
        prompt: str,
        scope: str,
        *,
        scene_id: str | None = None,
        max_tokens: int = 800,
    ) -> ProviderResponse | None:
        """LLM call for notes only. Provider failures are non-fatal (text is never parsed);
        budget errors propagate so the orchestrator can pause."""
        try:
            response, _ = self.call_provider(
                ctx,
                ProviderCapability.LLM_TEXT,
                sub_scope=f"llm-{scope}",
                prompt=prompt,
                scene_id=scene_id,
                parameters={"max_tokens": max_tokens, "temperature": 0.7},
            )
        except ProviderError as exc:
            log.warning("%s: LLM note call failed (%s); continuing", self.agent_id, exc)
            return None
        if response.output_text:
            ctx.extras.setdefault(NOTES, []).append(_one_line(response.output_text))
        return response

    @staticmethod
    def _resolve_provider(
        ctx: AgentContext, capability: ProviderCapability, provider_name: str | None
    ) -> Provider:
        if provider_name and provider_name != "unassigned":
            try:
                provider = ctx.providers.get(provider_name)
                if capability in provider.info.capabilities:
                    return provider
            except LookupError:
                log.info("provider %s not registered; routing by capability", provider_name)
        return ctx.providers.for_capability(capability)

    @staticmethod
    def _default_model(ctx: AgentContext, provider: Provider) -> str:
        models = provider.info.models
        if not models:
            return "default"
        if ctx.mode_policy.quality_tier == "high":
            premium = [m for m in models if "premium" in m or "cinematic" in m]
            if premium:
                return premium[0]
        return models[0]


def _one_line(text: str, limit: int = 280) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "\u2026"


def note(text: str | None, limit: int = 280) -> str | None:
    return _one_line(text, limit) if text else None
