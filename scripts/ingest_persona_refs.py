"""Copy a persona's reference images into the storage backend (never into Git).

Prints the ``references:`` block (file, sha256, guessed angle) to paste into
``packages/configurations/personas/<id>/persona.v<N>.yaml``; review the angles.

Usage:
    uv run python scripts/ingest_persona_refs.py lena-voss ~/Downloads/Lena-Voss
    uv run python scripts/ingest_persona_refs.py lena-voss DIR --tenant tenant_demo
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cineforge.config import get_settings
from cineforge.configuration import PersonaNotFoundError, get_persona
from cineforge.contracts.common import DEMO_TENANT_ID
from cineforge.media.factory import build_storage
from cineforge.media.persona_refs import ingest_references, references_yaml


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("persona_id")
    parser.add_argument("source", type=Path)
    parser.add_argument("--tenant", default=DEMO_TENANT_ID)
    args = parser.parse_args(argv)

    settings = get_settings()
    try:
        get_persona(settings.configurations_dir, args.persona_id)
    except PersonaNotFoundError:
        print(f"unknown persona {args.persona_id}; add its persona.v1.yaml first", file=sys.stderr)
        return 2
    source = args.source.expanduser()
    if not source.is_dir():
        print(f"not a folder: {source}", file=sys.stderr)
        return 2

    result = ingest_references(
        build_storage(settings), tenant_id=args.tenant, persona_id=args.persona_id, source=source
    )
    print(f"# stored {len(result.references)} images ({settings.storage_backend} storage)")
    for name in result.skipped_duplicates:
        print(f"# skipped duplicate: {name}")
    print(references_yaml(result.references), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
