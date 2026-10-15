"""Print the exact prompts a vlog brief would send, shot by shot, before any credits.

A brief is a ``CreateProductionRequest`` in YAML (theme, topic, look, authored script).
The sheet uses the same code as the engine: the persona's latest version, the theme's
generative rules and credit rates.

Usage:
    uv run python scripts/shot_sheet.py var/briefs/lepakshi.yaml            # Markdown
    uv run python scripts/shot_sheet.py var/briefs/lepakshi.yaml --json     # API body
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

import yaml
from cineforge.agents.vlog import (
    AuthoredScriptError,
    build_vlog_scenes,
    clip_prompt,
    script_from_authored,
)
from cineforge.config import get_settings
from cineforge.configuration import get_persona, load_themes
from cineforge.contracts.api import CreateProductionRequest
from cineforge.contracts.manifest import ShotKind
from cineforge.cost.vlog import STAGES, credits_for


def _theme(cfg: Path, theme_id: str, version: int | None):
    themes = load_themes(cfg)
    wanted = version or max(v for (i, v) in themes if i == theme_id)
    return themes[(theme_id, wanted)]


def sheet(req: CreateProductionRequest) -> str:
    cfg = get_settings().configurations_dir
    theme = _theme(cfg, req.theme_id, req.theme_version)
    rules = theme.production.generative
    if rules is None or req.script is None or theme.performance.persona_id is None:
        raise SystemExit("brief needs a fully generative theme with a host and a script")
    persona = get_persona(cfg, theme.performance.persona_id)
    script = script_from_authored(req.script, logline=req.topic, theme=theme, persona=persona)
    graph = build_vlog_scenes(script=script, theme=theme, persona=persona, look=req.look)
    lines = dict(enumerate(sorted(script.lines, key=lambda ln: ln.scene_order)))
    refs = {r.id: r.description for r in (req.look.references if req.look else [])}

    totals = dict.fromkeys(STAGES, Decimal(0))
    out: list[str] = []
    clock, n = 0.0, 0
    for scene in graph.scenes:
        for shot in scene.shots:
            line = lines[n]
            n += 1
            costs = {stage: credits_for(rules, shot, stage) for stage in STAGES}
            for stage, value in costs.items():
                totals[stage] += value
            a_roll = shot.kind == ShotKind.A_ROLL
            kind = (
                "TALK (lip-sync)"
                if a_roll
                else ("CUTAWAY + VOICE-OVER" if shot.audio.voiceover else "CUTAWAY")
            )
            model = rules.a_roll.model if a_roll else rules.b_roll.model
            start = f"{int(clock // 60)}:{clock % 60:04.1f}"
            clock += shot.duration_sec
            out += [
                f"### Shot {n}: {start} | {shot.duration_sec:g}s | {kind}",
                "",
                f"- **Voice ({persona.voice.voice_name}):** {shot.audio.dialogue_text or '-'}",
                f"- **On-screen text:** {shot.on_screen_text or '-'}",
                "- **References:** "
                + (", ".join(f"{r} ({refs.get(r, '?')})" for r in line.refs) or "-"),
                f"- **Credits:** still {costs['still']}, voice {costs['voice']}, "
                f"clip {costs['clip']} ({model})",
                "",
                f"**Still prompt ({rules.still.model}):**",
                "",
                f"> {shot.provider_plan.parameters['still_prompt']}",
                "",
                f"**Motion prompt ({model}):**",
                "",
                f"> {clip_prompt(line, persona)}",
                "",
            ]
    total = sum(totals.values())
    head = [
        f"# Shot sheet: {req.title or req.topic}",
        "",
        f"Theme {theme.id} v{theme.version}, host {persona.name} v{persona.version}, "
        f"{n} shots, {clock:.0f}s.",
        "",
        f"Credits: stills {totals['still']}, voice {totals['voice']}, clips {totals['clip']}, "
        f"**total {total}** (cap {rules.credit_cap}).",
        "",
    ]
    return "\n".join(head + out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("brief", type=Path)
    parser.add_argument("--json", action="store_true", help="print the API request body")
    args = parser.parse_args(argv)
    req = CreateProductionRequest.model_validate(yaml.safe_load(args.brief.read_text()))
    if args.json:
        print(json.dumps(req.model_dump(mode="json", exclude_none=True), indent=2))
        return 0
    try:
        print(sheet(req))
    except AuthoredScriptError as exc:
        print(f"script does not fit: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
