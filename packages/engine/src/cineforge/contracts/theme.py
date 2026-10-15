"""Theme profiles and production-mode policies (PRD 3 sections 5 and 9)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from cineforge.contracts.common import ContractModel, GenerationStrategy, Money, ProductionMode


class NarrativeRules(ContractModel):
    hook_strategy: str
    story_beats: list[str] = Field(min_length=1)
    factual_rigor: Literal["strict", "moderate", "creative"] = "strict"
    narration_style: str
    cta: str | None = None


class PerformanceRules(ContractModel):
    recurring_character: str | None = None
    character_id: str | None = Field(
        default=None, description="CharacterProfile id of the on-camera host, if any"
    )
    voice: str
    language: str = "en-US"
    accent: str | None = None
    camera_relationship: str = "narrator off-camera"


class GenerativeModel(ContractModel):
    model: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    min_sec: float | None = Field(default=None, gt=0)
    max_sec: float | None = Field(default=None, gt=0)


class GenerativeRules(ContractModel):
    """Fully generative productions: every frame is generated; licensed or public media
    only steer the generator as context references and never appear on screen."""

    provider: str = "higgsfield"
    still: GenerativeModel = Field(description="Storyboard frame (start image) per shot")
    a_roll: GenerativeModel = Field(description="Host talking to camera, lip-synced")
    b_roll: GenerativeModel = Field(description="POV / cutaway footage with ambience")
    words_per_sec: float = Field(default=2.4, gt=0, le=5)
    pilot_shots: int = Field(default=2, ge=0, le=4)
    credit_cap: int = Field(default=300, gt=0, description="Provider credits per production")
    max_context_refs: int = Field(default=2, ge=0, le=6)


class DirectionRules(ContractModel):
    camera_grammar: list[str] = Field(default_factory=list)
    lighting: list[str] = Field(default_factory=list)
    atmosphere: list[str] = Field(default_factory=list)
    vfx_intensity: Literal["none", "low", "medium", "high"] = "low"
    crowd_rules: str | None = None
    sound_palette: list[str] = Field(default_factory=list)


class ProductionRules(ContractModel):
    preferred_strategies: list[GenerationStrategy] = Field(min_length=1)
    min_scenes: int = Field(default=4, ge=1)
    max_scenes: int = Field(default=6, ge=1)
    max_shots_per_scene: int = Field(default=2, ge=1)
    duration_target_sec: float = Field(default=45, gt=0)
    aspect_ratio: Literal["9:16", "1:1", "16:9"] = "9:16"
    resolution: str = "1080x1920"
    default_mode: ProductionMode = ProductionMode.BALANCED
    qc_thresholds: dict[str, float] = Field(default_factory=dict)
    generative: GenerativeRules | None = Field(
        default=None, description="Set for fully generative themes (host-led vlogs)"
    )

    @property
    def fully_generative(self) -> bool:
        return self.generative is not None


class ConstraintRules(ContractModel):
    prohibited_claims: list[str] = Field(default_factory=list)
    rights_policy: str = "fail_closed"
    disclosure_rules: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)


class ThemeProfile(ContractModel):
    """Versioned, editable creative configuration. Loaded from packages/configurations/themes."""

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    version: int = Field(ge=1)
    name: str
    purpose: str
    audience: str
    genres: list[str] = Field(min_length=1)
    tone: str
    visual_style: str
    pacing: str
    narrative: NarrativeRules
    performance: PerformanceRules
    direction: DirectionRules
    production: ProductionRules
    constraints: ConstraintRules


class ThemeSummary(ContractModel):
    id: str
    version: int
    name: str
    purpose: str
    genres: list[str]
    default_mode: ProductionMode


class ProductionModePolicy(ContractModel):
    """Economy / Balanced / Premium behaviour (PRD 3 section 9)."""

    mode: ProductionMode
    description: str
    default_budget_usd: Money
    max_attempts_per_shot: int = Field(ge=1, le=10)
    expected_retry_rate: float = Field(ge=0, le=1, description="Used by preflight estimates")
    generative_shot_ratio: float = Field(ge=0, le=1)
    draft_first: bool
    storyboard_preflight: bool
    quality_tier: Literal["draft", "standard", "high"]
    allowed_strategies: list[GenerationStrategy] = Field(min_length=1)
