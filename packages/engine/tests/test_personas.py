"""Persona packs: versioned profiles, template, canon, legacy field names."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from cineforge.config import Settings
from cineforge.configuration import (
    PersonaNotFoundError,
    get_persona,
    load_canon,
    load_personas,
)
from cineforge.contracts.manifest import ProductionManifest
from cineforge.contracts.persona import PersonaCanon, PersonaProfile
from cineforge.contracts.theme import PerformanceRules

CONFIG = Settings().configurations_dir
SAMPLE_MANIFEST = CONFIG.parent / "schemas" / "fixtures" / "sample-manifest.json"


def test_lena_has_two_versions_and_latest_is_v2() -> None:
    personas = load_personas(CONFIG)
    assert set(personas["lena-voss"]) == {1, 2}
    assert get_persona(CONFIG, "lena-voss").version == 2
    v1 = get_persona(CONFIG, "lena-voss", 1)
    assert v1.voice.voice_id is None
    lena = get_persona(CONFIG, "lena-voss")
    assert lena.identity.age == 23
    assert lena.voice.voice_name == "Juno"
    assert lena.element_for("higgsfield") == "01288044-0746-4b24-8fa8-bea17c4a9233"
    assert "small gold hoop earrings" in lena.look.locks


def test_template_is_skipped_by_loader_but_valid() -> None:
    assert "template" not in load_personas(CONFIG)
    folder = CONFIG / "personas" / "_template"
    PersonaProfile.model_validate(yaml.safe_load((folder / "persona.v1.yaml").read_text()))
    PersonaCanon.model_validate(yaml.safe_load((folder / "canon.yaml").read_text()))


def test_unknown_persona_and_version_raise() -> None:
    with pytest.raises(PersonaNotFoundError):
        get_persona(CONFIG, "nobody")
    with pytest.raises(PersonaNotFoundError):
        get_persona(CONFIG, "lena-voss", 99)


def test_canon_loads_or_defaults_empty(tmp_path: Path) -> None:
    canon = load_canon(CONFIG, "lena-voss")
    assert canon.persona_id == "lena-voss" and canon.facts
    assert load_canon(tmp_path, "new-host") == PersonaCanon(persona_id="new-host")


def test_folder_and_id_must_match(tmp_path: Path) -> None:
    src = CONFIG / "personas" / "lena-voss" / "persona.v2.yaml"
    (tmp_path / "personas" / "someone-else").mkdir(parents=True)
    (tmp_path / "personas" / "someone-else" / "persona.v2.yaml").write_text(src.read_text())
    with pytest.raises(ValueError, match="someone-else"):
        load_personas(tmp_path)


def test_rows_saved_before_the_rename_still_load() -> None:
    rules = PerformanceRules.model_validate({"voice": "v", "character_id": "lena-voss"})
    assert rules.persona_id == "lena-voss"
    sample = json.loads(SAMPLE_MANIFEST.read_text())
    sample.pop("persona_id", None)
    sample["character_id"] = "lena-voss"
    assert ProductionManifest.model_validate(sample).persona_id == "lena-voss"
    assert "character_id" not in ProductionManifest.model_json_schema()["properties"]


def test_file_version_must_match_profile(tmp_path: Path) -> None:
    src = CONFIG / "personas" / "lena-voss" / "persona.v2.yaml"
    (tmp_path / "personas" / "lena-voss").mkdir(parents=True)
    (tmp_path / "personas" / "lena-voss" / "persona.v3.yaml").write_text(src.read_text())
    with pytest.raises(ValueError, match="version 2"):
        load_personas(tmp_path)
