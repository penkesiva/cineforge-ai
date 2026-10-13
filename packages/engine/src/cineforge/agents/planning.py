"""Deterministic planning helpers shared by agents and the orchestrator."""

from __future__ import annotations

import hashlib
import re

from cineforge.contracts.theme import ThemeProfile

SECONDS_PER_SCENE = 9.0
WORDS_PER_SECOND = 2.5


def slugify(text: str, max_len: int = 48) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-") or "topic"


def stable_int(*parts: object, modulo: int = 2**31 - 1) -> int:
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
    return int(digest[:12], 16) % modulo


def target_scene_count(theme: ThemeProfile, duration_sec: float) -> int:
    """~9 s per scene, clamped to the theme's min/max (45 s -> 5 scenes)."""
    raw = round(duration_sec / SECONDS_PER_SCENE)
    return max(theme.production.min_scenes, min(theme.production.max_scenes, raw))


def split_centis(total_sec: float, weights: list[float]) -> list[float]:
    """Split ``total_sec`` by weights in 0.01 s units; the parts sum exactly to the total."""
    total_cs = round(total_sec * 100)
    weight_sum = sum(weights)
    raw = [total_cs * w / weight_sum for w in weights]
    parts = [int(r) for r in raw]
    remainder = total_cs - sum(parts)
    order = sorted(range(len(raw)), key=lambda i: raw[i] - parts[i], reverse=True)
    for i in order[:remainder]:
        parts[i] += 1
    return [p / 100 for p in parts]


def beats_for_scenes(beats: list[str], scene_count: int) -> list[str]:
    """Map theme story beats onto ``scene_count`` scenes.

    Extra beats are merged into the final scene ("legacy and call-to-action");
    missing beats repeat the middle beat as a continuation.
    """
    if scene_count <= 0:
        return []
    if len(beats) >= scene_count:
        head = beats[: scene_count - 1]
        tail = beats[scene_count - 1 :]
        return [*head, " and ".join(tail)]
    out = list(beats)
    filler = beats[len(beats) // 2] if beats else "development"
    while len(out) < scene_count:
        out.insert(len(out) - 1, f"{filler} (continued)")
    return out


def word_budget(duration_sec: float) -> int:
    return int(duration_sec * WORDS_PER_SECOND)
