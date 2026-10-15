"""Recurring on-camera characters (hosts) for fully generative themes.

A character is identity, not media: the face lives in a provider-side reference element
built from images the tenant owns, so no character image is stored in Git or shown as
footage. Loaded from ``packages/configurations/characters/<id>.yaml``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from cineforge.contracts.common import ContractModel


class VoiceOption(ContractModel):
    voice_id: str
    name: str


class CharacterVoice(ContractModel):
    provider: str = "higgsfield"
    model: str = "seed_audio"
    voice_type: Literal["preset", "element"] = "preset"
    voice_id: str | None = Field(default=None, description="None until a voice is chosen")
    voice_name: str | None = None
    candidates: list[VoiceOption] = Field(
        default_factory=list, description="Voices offered as samples before one is chosen"
    )


class CharacterProfile(ContractModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    version: int = Field(ge=1)
    name: str
    look: str = Field(description="Appearance bible used in every prompt")
    wardrobe: str | None = None
    personality: str = ""
    provider_refs: dict[str, str] = Field(
        default_factory=dict,
        description="Provider -> reference element id, e.g. {'higgsfield': '<uuid>'}",
    )
    voice: CharacterVoice = Field(default_factory=CharacterVoice)
    disclosure: str = "AI-generated character"

    def element_for(self, provider: str) -> str | None:
        return self.provider_refs.get(provider)
