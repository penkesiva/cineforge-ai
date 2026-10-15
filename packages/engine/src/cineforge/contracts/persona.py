"""Personas: recurring AI hosts (influencers) used by fully generative themes.

A persona is a versioned, text-only profile in Git plus owned reference media outside Git:

- ``packages/configurations/personas/<id>/persona.v<N>.yaml`` -> ``PersonaProfile``
  (identity, look locks, wardrobe, personality, voice and delivery, content rules,
  camera style, provider reference elements, ownership, reference image manifest).
- ``packages/configurations/personas/<id>/canon.yaml`` -> ``PersonaCanon`` (curated
  continuity: established facts, running jokes, past trips).
- Reference images live in the storage backend under
  ``tenants/<tenant>/personas/<id>/references/<file>``; the profile lists them by file
  name and sha256 only. They guide generators (and built the provider element) and are
  never shown as footage.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import Field

from cineforge.contracts.common import ContractModel

PERSONA_ID_PATTERN = r"^[a-z0-9][a-z0-9-]*$"


class VoiceOption(ContractModel):
    voice_id: str
    name: str
    model: str | None = None
    variant: str | None = None
    note: str | None = None


class PersonaVoice(ContractModel):
    provider: str = "higgsfield"
    model: str = "seed_audio"
    variant: str | None = Field(
        default=None, description="Speech engine for text2speech_v2, e.g. elevenlabs"
    )
    voice_type: Literal["preset", "element"] = "preset"
    voice_id: str | None = Field(default=None, description="None until a voice is chosen")
    voice_name: str | None = None
    candidates: list[VoiceOption] = Field(
        default_factory=list, description="Voices sampled or saved for later"
    )


class PersonaDelivery(ContractModel):
    """How the persona speaks; fed to the scriptwriter, not to the TTS engine."""

    pace: str = "natural"
    energy: str = "warm"
    catchphrases: list[str] = Field(default_factory=list)
    greeting: str | None = None
    sign_off: str | None = None
    avoid_words: list[str] = Field(default_factory=list)


class PersonaIdentity(ContractModel):
    age: int = Field(ge=18, le=99, description="Personas are adults")
    pronouns: str = "she/her"
    origin: str | None = None
    based_in: str | None = None
    occupation: str | None = None
    backstory: str = ""
    values: list[str] = Field(default_factory=list)


class PersonaLook(ContractModel):
    description: str = Field(description="Appearance bible used in every image prompt")
    locks: list[str] = Field(
        default_factory=list, description="Traits that must never change between shots"
    )
    avoid: list[str] = Field(default_factory=list, description="Never show (negative prompt)")
    signature_items: list[str] = Field(default_factory=list)


class PersonaWardrobe(ContractModel):
    default: str
    rules: list[str] = Field(default_factory=list)


class PersonaPersonality(ContractModel):
    summary: str
    traits: list[str] = Field(default_factory=list)
    humor: str | None = None


class PersonaContent(ContractModel):
    niches: list[str] = Field(default_factory=list)
    topics_avoid: list[str] = Field(default_factory=list)
    tone: str | None = None


class PersonaCamera(ContractModel):
    framing: str = "selfie close-up at arm's length"
    lighting: str = "natural light"
    color: str | None = None
    notes: list[str] = Field(default_factory=list)


class Ownership(ContractModel):
    """Who owns the persona and its reference media; required before any use."""

    owner: str
    created_by: str
    created_with: str | None = Field(default=None, description="Tool used to create images")
    created_on: date | None = None
    commercial_use: bool = False
    statement: str = Field(description="Rights statement, e.g. owner-created AI images")


class ReferenceAngle(StrEnum):
    FRONT = "front"
    THREE_QUARTER = "three_quarter"
    PROFILE = "profile"
    CLOSE_UP = "close_up"
    WAIST_UP = "waist_up"
    FULL_BODY = "full_body"
    OTHER = "other"


class ReferenceImage(ContractModel):
    id: str = Field(pattern=r"^ref_[a-z0-9_]+$")
    file: str = Field(description="File name under the persona's references/ folder")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    angle: ReferenceAngle = ReferenceAngle.OTHER
    description: str | None = None
    usage: Literal["reference_only"] = "reference_only"


class PersonaProfile(ContractModel):
    id: str = Field(pattern=PERSONA_ID_PATTERN)
    version: int = Field(ge=1)
    name: str
    handle: str | None = None
    identity: PersonaIdentity
    look: PersonaLook
    wardrobe: PersonaWardrobe
    personality: PersonaPersonality
    voice: PersonaVoice = Field(default_factory=PersonaVoice)
    delivery: PersonaDelivery = Field(default_factory=PersonaDelivery)
    content: PersonaContent = Field(default_factory=PersonaContent)
    camera: PersonaCamera = Field(default_factory=PersonaCamera)
    provider_refs: dict[str, str] = Field(
        default_factory=dict,
        description="Provider -> reference element id, e.g. {'higgsfield': '<uuid>'}",
    )
    references: list[ReferenceImage] = Field(default_factory=list)
    ownership: Ownership
    disclosure: str = "AI-generated character"

    def element_for(self, provider: str) -> str | None:
        return self.provider_refs.get(provider)


class Episode(ContractModel):
    """One past trip, curated in canon.yaml or derived from a finished production."""

    title: str
    place: str | None = None
    era: str | None = None
    summary: str | None = None
    production_id: str | None = None
    on: date | None = None


class PersonaCanon(ContractModel):
    persona_id: str = Field(pattern=PERSONA_ID_PATTERN)
    facts: list[str] = Field(default_factory=list, description="Established, never contradict")
    running_jokes: list[str] = Field(default_factory=list)
    episodes: list[Episode] = Field(default_factory=list)
