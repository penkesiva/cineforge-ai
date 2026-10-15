"""Persona reference images: ingest into storage (never Git) and check what is present.

Reference images guide generators and document the persona's look. They are never used
as footage, so they skip the asset pipeline; provenance lives in the persona profile
(``ownership``) and each file is pinned by sha256 in ``references``.
"""

from __future__ import annotations

import hashlib
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path

from cineforge.contracts.media import StorageBackend, persona_storage_key
from cineforge.contracts.persona import PersonaProfile, ReferenceAngle, ReferenceImage

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
REF_ID_MAX = 40

_ANGLES: tuple[tuple[str, ReferenceAngle], ...] = (
    ("three-quarter", ReferenceAngle.THREE_QUARTER),
    ("three_quarter", ReferenceAngle.THREE_QUARTER),
    ("profile", ReferenceAngle.PROFILE),
    ("full-body", ReferenceAngle.FULL_BODY),
    ("full_body", ReferenceAngle.FULL_BODY),
    ("waist-up", ReferenceAngle.WAIST_UP),
    ("waist_up", ReferenceAngle.WAIST_UP),
    ("close-up", ReferenceAngle.CLOSE_UP),
    ("close_up", ReferenceAngle.CLOSE_UP),
    ("headshot", ReferenceAngle.CLOSE_UP),
    ("tight-crop", ReferenceAngle.CLOSE_UP),
    ("head-and-shoulders", ReferenceAngle.FRONT),
    ("portrait", ReferenceAngle.FRONT),
)


def guess_angle(name: str) -> ReferenceAngle:
    lowered = name.lower()
    for needle, angle in _ANGLES:
        if needle in lowered:
            return angle
    return ReferenceAngle.OTHER


def ref_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", Path(name).stem.lower()).strip("_")
    return f"ref_{slug[:REF_ID_MAX].rstrip('_') or 'image'}"


@dataclass(frozen=True)
class IngestResult:
    references: list[ReferenceImage]
    skipped_duplicates: list[str]


def ingest_references(
    storage: StorageBackend, *, tenant_id: str, persona_id: str, source: Path
) -> IngestResult:
    """Copy every image in ``source`` into storage; identical files (same sha256) once."""
    refs: list[ReferenceImage] = []
    skipped: list[str] = []
    seen: set[str] = set()
    taken: set[str] = set()
    for path in sorted(source.iterdir()):
        if path.suffix.lower() not in IMAGE_SUFFIXES or not path.is_file():
            continue
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest in seen:
            skipped.append(path.name)
            continue
        seen.add(digest)
        rid = ref_id(path.name)
        while rid in taken:
            rid = f"{rid}_{digest[:6]}"
        taken.add(rid)
        file = f"{rid.removeprefix('ref_')}{path.suffix.lower()}"
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        storage.put_bytes(persona_storage_key(tenant_id, persona_id, file), data, content_type)
        refs.append(
            ReferenceImage(
                id=rid,
                file=file,
                sha256=digest,
                angle=guess_angle(path.name),
                description=path.stem.replace("-", " ").strip(),
            )
        )
    return IngestResult(references=refs, skipped_duplicates=skipped)


def reference_available(
    storage: StorageBackend, *, tenant_id: str, persona: PersonaProfile, ref: ReferenceImage
) -> bool:
    return storage.exists(persona_storage_key(tenant_id, persona.id, ref.file))


def references_yaml(refs: list[ReferenceImage]) -> str:
    """The ``references:`` block to paste into ``persona.v<N>.yaml``."""
    lines = ["references:"]
    for r in refs:
        lines += [
            f"  - id: {r.id}",
            f"    file: {r.file}",
            f"    sha256: {r.sha256}",
            f"    angle: {r.angle.value}",
            f'    description: "{r.description}"',
        ]
    return "\n".join(lines) + "\n"
