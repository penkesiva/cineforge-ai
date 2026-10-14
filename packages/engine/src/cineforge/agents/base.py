"""BaseAgent: common plumbing for the 10 logical agents.

Every provider call goes through ``ctx.paid_calls`` (``PaidCallGuard``: price lookup ->
budget reservation -> invoke) and providers are routed per tenant
(``ProviderRegistry.route``).

Reasoning modes:

- **Structured (Phase 1):** ``structured()`` asks the routed LLM for JSON matching a
  Pydantic draft model, validates it, retries once with the validation errors, and
  returns ``None`` when the LLM is a mock or the output stays invalid. Agents then
  apply deterministic checks before building the contract artifact.
- **Deterministic fallback (Phase 0 behaviour):** artifacts are built from the brief,
  theme and mode. Mock LLM calls still run for cost accounting (``_llm`` notes); real
  LLMs are never called just for notes.
"""

from __future__ import annotations

import copy
import json
import logging
from abc import ABC, abstractmethod
from typing import Any, ClassVar, TypeVar

from pydantic import BaseModel, ValidationError

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
    UnsupportedCapabilityError,
)

log = logging.getLogger(__name__)

# Keys agents write into ``AgentContext.extras`` (read by the orchestrator).
LEDGER_EVENTS = "ledger_events"
PROMPT_TEMPLATES = "prompt_templates"
NOTES = "notes"
REASONING = "reasoning"  # "structured:<provider>/<model>" or "deterministic"

DraftT = TypeVar("DraftT", bound=BaseModel)
MAX_VALIDATION_ERRORS_IN_PROMPT = 8


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

    def structured(
        self,
        ctx: AgentContext,
        draft_model: type[DraftT],
        prompt: str,
        *,
        scope: str,
        system: str | None = None,
        max_tokens: int = 2000,
        scene_id: str | None = None,
    ) -> DraftT | None:
        """Typed LLM output or ``None`` (mock LLM, no ready LLM, provider error, or output
        still invalid after one corrective retry). Budget errors propagate."""
        provider = self._llm_provider(ctx)
        if provider is None or provider.info.is_mock:
            ctx.extras.setdefault(REASONING, "deterministic")
            return None
        schema = inline_schema(draft_model.model_json_schema())
        base_system = system or (
            f"You are the {self.definition.name} of a cinematic short-video studio. "
            "Answer only through the provided tool, in the brief's language."
        )
        attempt_prompt = prompt
        for round_no in (1, 2):
            sub = f"llm-{scope}" if round_no == 1 else f"llm-{scope}-fix"
            try:
                response, _ = self.call_provider(
                    ctx,
                    ProviderCapability.LLM_TEXT,
                    sub_scope=sub,
                    provider_name=provider.info.name,
                    prompt=attempt_prompt,
                    scene_id=scene_id,
                    parameters={
                        "response_schema": schema,
                        "schema_name": draft_model.__name__,
                        "system": base_system,
                        "max_tokens": max_tokens,
                        "temperature": 0.4,
                    },
                )
            except ProviderError as exc:
                log.warning("%s: structured LLM call failed (%s); falling back", self.agent_id, exc)
                self._note(ctx, f"LLM unavailable ({exc}); deterministic fallback used")
                ctx.extras[REASONING] = "deterministic"
                return None
            data = response.output_data.get("structured")
            try:
                if not isinstance(data, dict):
                    raise ValueError("no structured output returned")
                draft = draft_model.model_validate(data)
            except (ValidationError, ValueError) as exc:
                log.info(
                    "%s: structured output invalid (round %s): %s", self.agent_id, round_no, exc
                )
                attempt_prompt = (
                    f"{prompt}\n\nYour previous answer was invalid:\n{_errors(exc)}\n"
                    "Return a corrected, complete answer that satisfies the schema."
                )
                continue
            ctx.extras[REASONING] = f"structured:{response.provider}/{response.model}"
            return draft
        self._note(ctx, "LLM output failed validation twice; deterministic fallback used")
        ctx.extras[REASONING] = "deterministic"
        return None

    def _llm_provider(self, ctx: AgentContext) -> Provider | None:
        try:
            return self._resolve_provider(ctx, ProviderCapability.LLM_TEXT, None)
        except UnsupportedCapabilityError:
            return None

    @staticmethod
    def _note(ctx: AgentContext, text: str) -> None:
        ctx.extras.setdefault(NOTES, []).append(_one_line(text))

    def _llm(
        self,
        ctx: AgentContext,
        prompt: str,
        scope: str,
        *,
        scene_id: str | None = None,
        max_tokens: int = 800,
    ) -> ProviderResponse | None:
        """Mock-LLM call for notes and cost accounting only. Provider failures are
        non-fatal (text is never parsed); budget errors propagate so the orchestrator
        can pause. Real (possibly paid) LLMs are skipped: they only run via ``structured``."""
        provider = self._llm_provider(ctx)
        if provider is None or not provider.info.is_mock:
            return None
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
        return ctx.providers.route(capability, tenant_id=ctx.tenant_id)

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


def inline_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Resolve local ``$ref``s into one self-contained JSON Schema (tool input schemas
    are simpler for LLMs without ``$defs``) and drop titles to save tokens."""
    defs = schema.get("$defs", {})

    def resolve(node: Any, depth: int = 0) -> Any:
        if depth > 20:
            return {}
        if isinstance(node, list):
            return [resolve(n, depth) for n in node]
        if not isinstance(node, dict):
            return node
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            target = copy.deepcopy(defs.get(ref.removeprefix("#/$defs/"), {}))
            merged = {**target, **{k: v for k, v in node.items() if k != "$ref"}}
            return resolve(merged, depth + 1)
        return {k: resolve(v, depth) for k, v in node.items() if k not in ("$defs", "title")}

    return resolve(schema)


def _errors(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        items = exc.errors()[:MAX_VALIDATION_ERRORS_IN_PROMPT]
        return "\n".join(
            f"- {'.'.join(str(p) for p in e.get('loc', ())) or 'root'}: {e.get('msg')}"
            for e in items
        )
    return f"- {exc}"


def dump_json(value: Any, limit: int = 4000) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


def _one_line(text: str, limit: int = 280) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "\u2026"


def note(text: str | None, limit: int = 280) -> str | None:
    return _one_line(text, limit) if text else None
