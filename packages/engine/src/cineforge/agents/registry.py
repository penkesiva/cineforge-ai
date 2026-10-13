"""DefaultAgentRegistry: schema-validated agent invocation."""

from __future__ import annotations

import threading

from pydantic import BaseModel, ValidationError

from cineforge.contracts.agents import (
    AGENT_DEFINITIONS,
    Agent,
    AgentContext,
    AgentDefinition,
    AgentSchemaError,
)
from cineforge.contracts.common import AgentId
from cineforge.persistence.serde import strip_computed


class AgentNotFoundError(LookupError):
    pass


def _as_dict(value: BaseModel | dict) -> dict:
    if isinstance(value, BaseModel):
        return value.model_dump(exclude_computed_fields=True)
    if isinstance(value, dict):
        return value
    raise TypeError(f"expected a pydantic model or dict, got {type(value).__name__}")


class DefaultAgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[AgentId, Agent] = {}
        self._lock = threading.Lock()

    def register(self, agent: Agent) -> None:
        if not isinstance(agent, Agent):
            raise TypeError(f"{agent!r} does not implement the Agent protocol")
        with self._lock:
            self._agents[agent.definition.id] = agent

    def get(self, agent_id: AgentId) -> Agent:
        try:
            return self._agents[AgentId(agent_id)]
        except (KeyError, ValueError) as exc:
            raise AgentNotFoundError(f"agent {agent_id} is not registered") from exc

    def definitions(self) -> list[AgentDefinition]:
        order = {d.id: i for i, d in enumerate(AGENT_DEFINITIONS)}
        defs = [a.definition for a in self._agents.values()]
        return sorted(defs, key=lambda d: order.get(d.id, len(order)))

    def invoke(self, agent_id: AgentId, ctx: AgentContext, payload: BaseModel | dict) -> BaseModel:
        agent = self.get(agent_id)
        try:
            data = _as_dict(payload)
            validated_input = agent.input_model.model_validate(
                strip_computed(agent.input_model, data)
            )
        except (ValidationError, TypeError) as exc:
            raise AgentSchemaError(
                f"{agent_id}: input does not match {agent.input_model.__name__}: {exc}"
            ) from exc

        result = agent.run(ctx, validated_input)

        try:
            if isinstance(result, BaseModel) and not isinstance(result, agent.output_model):
                raise TypeError(
                    f"returned {type(result).__name__}, expected {agent.output_model.__name__}"
                )
            out = _as_dict(result)
            return agent.output_model.model_validate(strip_computed(agent.output_model, out))
        except (ValidationError, TypeError) as exc:
            raise AgentSchemaError(
                f"{agent_id}: output does not match {agent.output_model.__name__}: {exc}"
            ) from exc
