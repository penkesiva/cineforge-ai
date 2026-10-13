"""Deterministic FFmpeg rendering (Phase 0: per-scene title slates) and ffprobe QC (ENG-10).

Pipeline: one ``lavfi color`` input per scene (background colour by scene index,
duration = scene duration) -> optional ``drawtext`` title + "Scene N" -> ``concat``
-> H.264 (libx264 ultrafast, yuv420p, +faststart) with a quiet AAC sine bed so the
master always has an audio stream. ffmpeg runs in a private temp dir with the
font symlinked and texts in files, so no user text reaches the filtergraph.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
from pathlib import Path
from typing import Any

from cineforge.contracts.manifest import OutputProfile, ProductionManifest
from cineforge.contracts.review import RetryScope, ReviewFinding, ReviewGate, Severity

FONT_CANDIDATES: tuple[str, ...] = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
)
PALETTE: tuple[str, ...] = ("0x1d2b53", "0x7e2553", "0x008751", "0xab5236", "0x5f574f", "0x29adff")
DURATION_TOLERANCE_SEC = 0.5
RENDER_TIMEOUT_SEC = 600
MAX_TITLE_CHARS = 32

# Codec names as reported by ffprobe for OutputProfile values.
_CODEC_ALIASES = {"h264": {"h264"}, "avc": {"h264"}, "hevc": {"hevc"}, "h265": {"hevc"}}


class RenderError(RuntimeError):
    pass


@dataclass(frozen=True)
class SlateSegment:
    title: str
    subtitle: str
    duration_sec: float


def find_font() -> Path | None:
    return next((Path(p) for p in FONT_CANDIDATES if Path(p).is_file()), None)


def _binary(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise RenderError(f"{name} not found on PATH")
    return path


@lru_cache(maxsize=1)
def has_drawtext() -> bool:
    try:
        out = subprocess.run(
            [_binary("ffmpeg"), "-hide_banner", "-filters"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        ).stdout
    except (RenderError, OSError, subprocess.SubprocessError):
        return False
    return any(line.split()[1:2] == ["drawtext"] for line in out.splitlines() if line.strip())


@lru_cache(maxsize=1)
def ffmpeg_version() -> str:
    out = subprocess.run(
        [_binary("ffmpeg"), "-version"], capture_output=True, text=True, timeout=30, check=False
    ).stdout
    first = out.splitlines()[0] if out else ""
    parts = first.split()
    return parts[2] if len(parts) > 2 and parts[0] == "ffmpeg" else first


def slate_segments(manifest: ProductionManifest) -> list[SlateSegment]:
    if not manifest.scenes:
        title = manifest.title or manifest.creative_brief.topic
        return [SlateSegment(title, "CineForge AI", manifest.output.duration_target_sec)]
    return [
        SlateSegment(
            scene.title or f"Scene {scene.order}", f"Scene {scene.order}", scene.duration_sec
        )
        for scene in sorted(manifest.scenes, key=lambda s: s.order)
    ]


def expected_duration(manifest: ProductionManifest) -> float:
    return sum(s.duration_sec for s in slate_segments(manifest))


def _truncate(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= MAX_TITLE_CHARS else text[: MAX_TITLE_CHARS - 1] + "..."


def build_slate_command(
    segments: list[SlateSegment], output: OutputProfile, out_path: Path, *, text: bool
) -> list[str]:
    """ffmpeg argv; text inputs are relative files (t<i>.txt, s<i>.txt, font.ttf) in cwd."""
    w, h, fps = output.width, output.height, output.fps
    total = sum(s.duration_sec for s in segments)
    title_size = max(12, h // 16)
    sub_size = max(10, h // 28)
    inputs: list[str] = []
    chains: list[str] = []
    for i, seg in enumerate(segments):
        color = PALETTE[i % len(PALETTE)]
        inputs += [
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s={w}x{h}:r={fps}:d={seg.duration_sec:.3f}",
        ]
        filters = []
        if text:
            common = "fontfile=font.ttf:expansion=none:fontcolor=white:x=(w-text_w)/2"
            filters.append(
                f"drawtext={common}:textfile=t{i}.txt:fontsize={title_size}:y=(h-text_h)/2"
            )
            filters.append(
                f"drawtext={common}:textfile=s{i}.txt:fontsize={sub_size}"
                f":y=(h/2)+{title_size}:alpha=0.8"
            )
        filters.append("setsar=1")
        chains.append(f"[{i}:v]{','.join(filters)}[v{i}]")
    audio_index = len(segments)
    inputs += ["-f", "lavfi", "-i", f"sine=frequency=220:sample_rate=48000:duration={total:.3f}"]
    concat = "".join(f"[v{i}]" for i in range(len(segments)))
    graph = ";".join(
        [
            *chains,
            f"{concat}concat=n={len(segments)}:v=1:a=0[vout]",
            f"[{audio_index}:a]volume=0.03,aformat=channel_layouts=stereo[aout]",
        ]
    )
    return [
        _binary("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
        *inputs,
        "-filter_complex", graph,
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-r", str(fps),
        "-c:a", "aac", "-b:a", "96k", "-ar", "48000",
        "-t", f"{total:.3f}",
        "-movflags", "+faststart",
        str(out_path),
    ]  # fmt: skip


def render_master_slate(
    manifest: ProductionManifest, out_path: Path, *, timeout: float = RENDER_TIMEOUT_SEC
) -> Path:
    """Render the Phase 0 slate master to ``out_path`` (absolute path returned)."""
    out_path = Path(out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    segments = slate_segments(manifest)
    font = find_font()
    text = font is not None and has_drawtext()
    with tempfile.TemporaryDirectory(prefix="cineforge-ffmpeg-") as workdir:
        work = Path(workdir)
        if text:
            os.symlink(font, work / "font.ttf")
            for i, seg in enumerate(segments):
                (work / f"t{i}.txt").write_text(_truncate(seg.title), encoding="utf-8")
                (work / f"s{i}.txt").write_text(seg.subtitle, encoding="utf-8")
        cmd = build_slate_command(segments, manifest.output, out_path, text=text)
        try:
            result = subprocess.run(
                cmd, cwd=work, capture_output=True, text=True, timeout=timeout, check=False
            )
        except subprocess.TimeoutExpired as exc:
            out_path.unlink(missing_ok=True)
            raise RenderError(f"ffmpeg timed out after {timeout}s") from exc
    if result.returncode != 0 or not out_path.is_file():
        out_path.unlink(missing_ok=True)
        raise RenderError(f"ffmpeg failed ({result.returncode}): {result.stderr.strip()[-2000:]}")
    return out_path


def probe(path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [_binary("ffprobe"), "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, timeout=60, check=False,
    )  # fmt: skip
    if result.returncode != 0:
        raise RenderError(f"ffprobe failed: {result.stderr.strip()[-2000:]}")
    return json.loads(result.stdout)


def _stream(info: dict[str, Any], kind: str) -> dict[str, Any] | None:
    return next((s for s in info.get("streams", []) if s.get("codec_type") == kind), None)


def _fps(rate: str | None) -> float:
    try:
        return float(Fraction(rate)) if rate and rate != "0/0" else 0.0
    except (ValueError, ZeroDivisionError):
        return 0.0


def probe_summary(info: dict[str, Any]) -> dict[str, Any]:
    """Flat technical summary used for AssetRecord / MasterRender fields."""
    video = _stream(info, "video") or {}
    audio = _stream(info, "audio")
    fmt = info.get("format", {})
    duration = fmt.get("duration") or video.get("duration") or 0
    return {
        "width": video.get("width"),
        "height": video.get("height"),
        "fps": _fps(video.get("avg_frame_rate") or video.get("r_frame_rate")),
        "codec": video.get("codec_name"),
        "pix_fmt": video.get("pix_fmt"),
        "audio_codec": audio.get("codec_name") if audio else None,
        "duration_sec": float(duration),
        "format_name": fmt.get("format_name"),
        "bit_rate": int(fmt["bit_rate"]) if fmt.get("bit_rate") else None,
    }


def _finding(severity: Severity, message: str, evidence: str, fix: str) -> ReviewFinding:
    return ReviewFinding(
        gate=ReviewGate.MASTER,
        severity=severity,
        message=message,
        evidence=[evidence],
        recommended_fix=fix,
        retry_scope=RetryScope.PRODUCTION,
    )


def validate_master(
    info: dict[str, Any], output: OutputProfile, expected_duration: float
) -> list[ReviewFinding]:
    """Technical QC of a rendered master against the output profile (ENG-10)."""
    findings: list[ReviewFinding] = []
    s = probe_summary(info)
    crit, major = Severity.CRITICAL, Severity.MAJOR
    rerender = "re-render the master with the production output profile"
    if _stream(info, "video") is None:
        return [_finding(crit, "master has no video stream", "streams: no video", rerender)]
    if (s["width"], s["height"]) != (output.width, output.height):
        findings.append(
            _finding(
                crit,
                "master resolution does not match the output profile",
                f"expected {output.width}x{output.height}, got {s['width']}x{s['height']}",
                rerender,
            )
        )
    allowed = _CODEC_ALIASES.get(output.codec.lower(), {output.codec.lower()})
    if s["codec"] not in allowed:
        findings.append(
            _finding(
                crit,
                "master video codec does not match the output profile",
                f"expected {output.codec}, got {s['codec']}",
                rerender,
            )
        )
    if s["audio_codec"] is None:
        findings.append(
            _finding(crit, "master has no audio stream", "streams: no audio", "mux an audio track")
        )
    elif s["audio_codec"] != output.audio_codec.lower():
        findings.append(
            _finding(
                major,
                "master audio codec does not match the output profile",
                f"expected {output.audio_codec}, got {s['audio_codec']}",
                rerender,
            )
        )
    drift = abs(s["duration_sec"] - expected_duration)
    if drift > DURATION_TOLERANCE_SEC:
        findings.append(
            _finding(
                crit,
                "master duration is off by more than 0.5 s",
                f"expected {expected_duration:.3f}s, got {s['duration_sec']:.3f}s",
                "check the timeline and re-render",
            )
        )
    if s["fps"] and abs(s["fps"] - output.fps) > 0.01:
        findings.append(
            _finding(
                major,
                "master frame rate does not match the output profile",
                f"expected {output.fps}, got {s['fps']:.3f}",
                rerender,
            )
        )
    containers = (s["format_name"] or "").split(",")
    if output.container.lower() not in containers:
        findings.append(
            _finding(
                major,
                "master container does not match the output profile",
                f"expected {output.container}, got {s['format_name']}",
                rerender,
            )
        )
    if s["pix_fmt"] and s["pix_fmt"] != "yuv420p":
        findings.append(
            _finding(
                major,
                "master pixel format is not yuv420p (player compatibility)",
                f"got {s['pix_fmt']}",
                rerender,
            )
        )
    return findings
