"""Short original music bed for a production that has a cue but no music file.

No provider call. A tanpura-style drone plus a slow pentatonic line. Temple places
get a lower, quieter line. Upbeat cues get a lighter, quicker one. The file is
deterministic for a given cue.
"""

from __future__ import annotations

import hashlib
import math
import struct
import wave
from dataclasses import dataclass
from pathlib import Path

SR = 48000
_PATTERN = (0, 2, 4, 2, 3, None, 1, 4, 2, None, 0, 3)


@dataclass(frozen=True)
class _Mood:
    root: float
    steps: tuple[int, ...]
    bpm: float
    drone: float
    melody: float
    layers: bool = False


def _mood(cue: str) -> _Mood:
    text = cue.lower()
    sacred = any(
        word in text
        for word in ("temple", "lepakshi", "shrine", "mandapa", "pillar", "nandi", "sacred")
    )
    bright = any(word in text for word in ("upbeat", "light", "playful", "warm", "vlog", "curious"))
    if sacred and bright:
        return _Mood(146.83, (0, 2, 4, 7, 9), 84, 0.22, 0.14, layers=True)
    if sacred:
        return _Mood(130.81, (0, 2, 3, 7, 8), 66, 0.26, 0.10, layers=True)
    if bright:
        return _Mood(196.00, (0, 2, 4, 7, 9), 102, 0.10, 0.18)
    return _Mood(174.61, (0, 2, 5, 7, 10), 80, 0.16, 0.12)


def _freq(root: float, semis: int) -> float:
    return root * (2 ** (semis / 12))


def write_theme_bed(path: Path, duration: float, cue: str) -> None:
    """Write a stereo 48 kHz wav of about ``duration`` seconds."""
    mood = _mood(cue)
    length = max(0.5, float(duration))
    count = int(SR * length)
    beat = 60.0 / mood.bpm
    seed = int.from_bytes(hashlib.sha256(cue.encode()).digest()[:4], "big")
    rng_step = 1 + (seed % 5)
    frames = bytearray()
    for i in range(count):
        t = i / SR
        drone = mood.drone * (
            0.55 * math.sin(2 * math.pi * (mood.root / 2) * t)
            + 0.30 * math.sin(2 * math.pi * mood.root * t)
            + 0.15 * math.sin(2 * math.pi * _freq(mood.root, 7) * t)
        )
        drone *= 0.82 + 0.18 * math.sin(2 * math.pi * 0.07 * t)
        beat_i = int(t / beat)
        local = t - beat_i * beat
        slot = _PATTERN[(beat_i * rng_step) % len(_PATTERN)]
        note = 0.0
        if slot is not None and local < beat * 0.7:
            semis = mood.steps[slot % len(mood.steps)]
            if beat_i % 8 >= 5:
                semis += 12
            freq = _freq(mood.root / 2, semis)
            note = mood.melody * math.exp(-local * 5.5) * math.sin(2 * math.pi * freq * t)
            note += (
                0.35
                * mood.melody
                * math.exp(-local * 5.5)
                * math.sin(2 * math.pi * freq * 1.003 * t)
            )
        extra = 0.0
        if mood.layers:
            if beat_i % 2 == 0 and local < 0.18:
                extra += 0.07 * math.exp(-local * 14) * math.sin(2 * math.pi * mood.root * 2 * t)
            extra += 0.035 * math.sin(2 * math.pi * _freq(mood.root, 12) * t)
        fade = min(1.0, t / 1.0, max(0.0, (length - t) / 1.6))
        sample = max(-1.0, min(1.0, (drone + note + extra) * fade))
        left = int(sample * 12000)
        right = int(max(-1.0, min(1.0, sample * 0.92)) * 12000)
        frames += struct.pack("<hh", left, right)
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(SR)
        handle.writeframes(frames)
