"""Persona reference ingest: storage keys, duplicate skipping, angle guesses."""

from __future__ import annotations

import hashlib
from pathlib import Path

from cineforge.config import Settings
from cineforge.configuration import get_persona
from cineforge.contracts.media import persona_storage_key
from cineforge.contracts.persona import ReferenceAngle
from cineforge.media.persona_refs import (
    guess_angle,
    ingest_references,
    ref_id,
    reference_available,
    references_yaml,
)
from fakes_b import FakeStorage


def test_guess_angle_and_ref_id() -> None:
    assert guess_angle("Three-quarter-left-angle.png") == ReferenceAngle.THREE_QUARTER
    assert guess_angle("Left-profile-close-up.png") == ReferenceAngle.PROFILE
    assert guess_angle("Full-body-walking.png") == ReferenceAngle.FULL_BODY
    assert guess_angle("Lena-Voss.png") == ReferenceAngle.OTHER
    assert ref_id("Photo of the Woman (copy).PNG") == "ref_photo_of_the_woman_copy"


def test_ingest_stores_each_unique_image_once(tmp_path: Path) -> None:
    (tmp_path / "Close-up-a.png").write_bytes(b"a")
    (tmp_path / "Close-up-a copy.png").write_bytes(b"a")
    (tmp_path / "Waist-up-b.jpg").write_bytes(b"b")
    (tmp_path / "notes.txt").write_text("not an image")
    storage = FakeStorage()

    result = ingest_references(storage, tenant_id="t1", persona_id="p-1", source=tmp_path)

    assert len(result.references) == 2
    assert len(result.skipped_duplicates) == 1
    by_angle = {r.angle: r for r in result.references}
    waist = by_angle[ReferenceAngle.WAIST_UP]
    assert waist.file == "waist_up_b.jpg"
    assert waist.sha256 == hashlib.sha256(b"b").hexdigest()
    key = persona_storage_key("t1", "p-1", waist.file)
    assert key == "tenants/t1/personas/p-1/references/waist_up_b.jpg"
    assert storage.objects[key] == (b"b", "image/jpeg")
    assert "sha256: " + waist.sha256 in references_yaml(result.references)


def test_lena_references_are_pinned_and_checked_per_tenant() -> None:
    lena = get_persona(Settings().configurations_dir, "lena-voss")
    assert len(lena.references) == 19
    assert len({r.sha256 for r in lena.references}) == 19
    ref = lena.references[0]
    storage = FakeStorage()
    assert not reference_available(storage, tenant_id="t1", persona=lena, ref=ref)
    storage.put_bytes(persona_storage_key("t1", lena.id, ref.file), b"x", "image/png")
    assert reference_available(storage, tenant_id="t1", persona=lena, ref=ref)
    assert not reference_available(storage, tenant_id="t2", persona=lena, ref=ref)
