"""Shared primitives for all CineForge contracts."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

SCHEMA_VERSION = "1.0"
DEMO_TENANT_ID = "tenant_demo"
DEFAULT_CURRENCY = "USD"

MONEY_QUANTUM = Decimal("0.000001")

# Decimal in Python (exact budget math), plain JSON number on the wire.
Money = Annotated[
    Decimal,
    Field(ge=0, max_digits=18, decimal_places=6),
    PlainSerializer(lambda v: float(v), return_type=float, when_used="json"),
]


def money(value: Decimal | float | int | str) -> Decimal:
    """Normalize any numeric input to a 6-decimal-place Decimal."""
    return Decimal(str(value)).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    """Opaque, prefixed identifier, e.g. ``prod_3f9c1a7b2d4e5f60``."""
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class ContractModel(BaseModel):
    """Base for every inter-service / inter-agent contract. Unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ProductionMode(StrEnum):
    ECONOMY = "economy"
    BALANCED = "balanced"
    PREMIUM = "premium"


class AgentId(StrEnum):
    """The 10 logical agents (PRD 3 section 3). Roles, not containers."""

    MASTER_ORCHESTRATOR = "a1_master_orchestrator"
    RESEARCH = "a2_research"
    MEDIA_DISCOVERY = "a3_media_discovery"
    CREATIVE_DIRECTOR = "a4_creative_director"
    SCRIPTWRITER = "a5_scriptwriter"
    SCENE_DIRECTOR = "a6_scene_director"
    VISUAL_PRODUCTION = "a7_visual_production"
    AUDIO_PERFORMANCE = "a8_audio_performance"
    EDITOR_QC = "a9_editor_qc"
    COST_OPTIMIZER = "a10_cost_optimizer"


class GenerationStrategy(StrEnum):
    LICENSED_STILL_MOTION = "licensed_still_motion"
    GENERATIVE = "generative"
    HYBRID = "hybrid"
    REUSE = "reuse"
