"""Deterministic FFmpeg edit of a production timeline (Phase 2 master renderer).

Per shot (first match wins):

1. the latest real generated clip (``AssetRole.GENERATED``, video file in storage):
   scaled/cropped to the output frame, gently slowed (max 1.25x) or last-frame frozen to
   fill the shot;
2. an ingested still (``SOURCE``/``REFERENCE`` ref -> image asset): Ken Burns zoompan;
3. a colour slate with the scene title.

Audio: each scene's latest real narration (``AssetRole.AUDIO`` on any of its shots) is
placed at the scene start and trimmed to the scene; an optional real music bed sits
under it; silence otherwise; loudness-normalized to the soundtrack target.

Text (needs drawtext + a font): burned-in captions, the disclosure label on synthetic
shots, and an end card with attributions (always rendered, counted in the duration).
ffmpeg runs in a private temp dir; every user text goes through files, never the graph.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import textwrap
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from cineforge.contracts.manifest import (
    AssetRole,
    OutputProfile,
    ProductionManifest,
    Shot,
)
from cineforge.contracts.media import AssetKind, AssetRecord
from cineforge.media.render import (
    PALETTE,
    RENDER_TIMEOUT_SEC,
    RenderError,
    _binary,
    find_font,
    has_drawtext,
)

RENDERER = "ffmpeg-edit-v1"
END_CARD_SEC = 3.0
MAX_SLOWDOWN = 1.25
DEFAULT_ZOOM = 1.08
STILL_OVERSCAN = 1.5
CAPTION_MAX_WORDS = 9
NARRATION_FADE_SEC = 0.15
MUSIC_VOLUME = 0.12
DEFAULT_AI_LABEL = "AI-generated"
END_CARD_TITLE = "Made with CineForge AI"

LocalPath = Callable[[AssetRecord], Path | None]


@dataclass(frozen=True)
class ShotSource:
    kind: Literal["clip", "still", "slate"]
    path: Path | None = None
    asset_id: str | None = None
    clip_duration: float | None = None
    zoom: float = DEFAULT_ZOOM
    pan: str = "center"


@dataclass(frozen=True)
class EditShot:
    scene_id: str
    shot_id: str
    start: float
    duration: float
    source: ShotSource
    title: str = ""
    label: str | None = None


@dataclass(frozen=True)
class EditAudio:
    path: Path
    start: float
    duration: float
    asset_id: str


@dataclass(frozen=True)
class CaptionCue:
    start: float
    end: float
    text: str


@dataclass
class EditPlan:
    shots: list[EditShot]
    narration: list[EditAudio] = field(default_factory=list)
    music: Path | None = None
    captions: list[CaptionCue] = field(default_factory=list)
    credits: list[str] = field(default_factory=list)
    end_card_sec: float = END_CARD_SEC
    loudness_lufs: float = -14.0

    @property
    def timeline_sec(self) -> float:
        return round(sum(s.duration for s in self.shots), 3)

    @property
    def total_sec(self) -> float:
        return round(self.timeline_sec + self.end_card_sec, 3)

    def summary(self) -> dict[str, Any]:
        kinds = [s.source.kind for s in self.shots]
        return {
            "clips": kinds.count("clip"),
            "stills": kinds.count("still"),
            "slates": kinds.count("slate"),
            "narration_tracks": len(self.narration),
            "music": self.music is not None,
            "captions": len(self.captions),
            "labeled_shots": sum(1 for s in self.shots if s.label),
            "credits": list(self.credits),
            "end_card_sec": self.end_card_sec,
            "shot_sources": {
                s.shot_id: {"kind": s.source.kind, "asset_id": s.source.asset_id}
                for s in self.shots
            },
        }


# ------------------------------------------------------------------------ edit plan
def _is_kind(asset: AssetRecord, kind: AssetKind, mime_prefix: str) -> bool:
    return asset.kind == kind and asset.content_type.startswith(mime_prefix)


def _real(asset: AssetRecord | None, kind: AssetKind, prefix: str, local: LocalPath) -> Path | None:
    if asset is None or not _is_kind(asset, kind, prefix):
        return None
    path = local(asset)
    return path if path is not None and path.is_file() else None


def _label(shot: Shot) -> str | None:
    if shot.disclosure.synthetic_media or shot.disclosure.reconstruction:
        return shot.disclosure.label_text or DEFAULT_AI_LABEL
    return None


def _shot_source(
    shot: Shot,
    assets: dict[str, AssetRecord],
    stills: dict[str, AssetRecord],
    local: LocalPath,
) -> ShotSource:
    for ref in reversed(shot.assets):
        if ref.role != AssetRole.GENERATED:
            continue
        asset = assets.get(ref.asset_id)
        path = _real(asset, AssetKind.VIDEO, "video/", local)
        if asset is not None and path is not None:
            return ShotSource("clip", path, asset.id, clip_duration=asset.duration_sec)
    for ref in shot.assets:
        if ref.role not in (AssetRole.SOURCE, AssetRole.REFERENCE, AssetRole.KEYFRAME):
            continue
        asset = assets.get(ref.asset_id) or stills.get(ref.asset_id)
        path = _real(asset, AssetKind.IMAGE, "image/", local)
        if asset is not None and path is not None:
            kb = ref.transform.get("ken_burns") or {}
            try:
                zoom = min(max(float(kb.get("zoom", DEFAULT_ZOOM)), 1.0), 1.5)
            except (TypeError, ValueError):
                zoom = DEFAULT_ZOOM
            pan = str(kb.get("pan", "center"))
            return ShotSource(
                "still",
                path,
                asset.id,
                zoom=zoom,
                pan=pan if pan in ("left", "right") else "center",
            )
    return ShotSource("slate")


def _narration(
    shots: list[Shot], assets: dict[str, AssetRecord], local: LocalPath
) -> tuple[Path, str] | None:
    for shot in reversed(shots):
        for ref in reversed(shot.assets):
            if ref.role != AssetRole.AUDIO:
                continue
            asset = assets.get(ref.asset_id)
            path = _real(asset, AssetKind.AUDIO, "audio/", local)
            if asset is not None and path is not None:
                return path, asset.id
    return None


def caption_chunks(
    text: str, start: float, end: float, *, max_words: int = CAPTION_MAX_WORDS
) -> list[CaptionCue]:
    """Split one cue into short on-screen chunks, timed by character share."""
    words = text.split()
    if not words or end <= start:
        return []
    groups = [" ".join(words[i : i + max_words]) for i in range(0, len(words), max_words)]
    total_chars = sum(len(g) for g in groups)
    cues, t = [], start
    for i, group in enumerate(groups):
        span = (end - start) * len(group) / total_chars
        stop = end if i == len(groups) - 1 else round(t + span, 3)
        cues.append(CaptionCue(round(t, 3), stop, group))
        t = stop
    return cues


def _captions(manifest: ProductionManifest) -> list[CaptionCue]:
    track = next((t for t in manifest.captions if t.burn_in and t.cues), None)
    cues: list[CaptionCue] = []
    if track is not None:
        for cue in track.cues:
            cues += caption_chunks(cue.text, cue.start_sec, cue.end_sec)
        return cues
    start = 0.0
    for scene in sorted(manifest.scenes, key=lambda s: s.order):
        if scene.narration:
            cues += caption_chunks(scene.narration, start, start + scene.duration_sec)
        start += scene.duration_sec
    return cues


def _credit_for(asset: AssetRecord) -> list[str]:
    lines: list[str] = []
    derived = asset.metadata.get("derived_from") or {}
    if derived.get("attribution"):
        lines.append(f"Photo: {derived['attribution']}")
    elif asset.license is not None and asset.license.attribution_text:
        lines.append(f"Photo: {asset.license.attribution_text}")
    elif asset.license is not None and asset.kind == AssetKind.IMAGE:
        lines.append(
            f"Photo: {asset.metadata.get('title') or asset.id} ({asset.license.license_type})"
        )
    gen = asset.generation or {}
    if gen.get("provider") and not str(gen["provider"]).startswith("mock"):
        what = "Narration" if asset.kind == AssetKind.AUDIO else "Animation"
        lines.append(f"{what}: AI ({gen['provider']} {gen.get('model', '')})".replace(" )", ")"))
    return lines


def build_edit_plan(
    manifest: ProductionManifest,
    assets: dict[str, AssetRecord],
    *,
    local_path: LocalPath,
    stills: dict[str, AssetRecord] | None = None,
) -> EditPlan:
    """Pure timeline decision. ``assets`` by asset id; ``stills`` maps A3 candidate ids to
    ingested image assets; ``local_path`` returns a readable file for an asset or None."""
    stills = stills or {}
    by_id = {**{a.id: a for a in stills.values()}, **assets}
    shots: list[EditShot] = []
    narration: list[EditAudio] = []
    credits: list[str] = []
    t = 0.0
    scenes = sorted(manifest.scenes, key=lambda s: s.order)
    if not scenes:
        title = manifest.title or manifest.creative_brief.topic
        shots.append(
            EditShot(
                "", "slate", 0.0, manifest.output.duration_target_sec, ShotSource("slate"), title
            )
        )
    for scene in scenes:
        scene_start = t
        ordered = sorted(scene.shots, key=lambda s: s.order)
        for shot in ordered:
            source = _shot_source(shot, assets, stills, local_path)
            shots.append(
                EditShot(
                    scene_id=scene.id,
                    shot_id=shot.id,
                    start=round(t, 3),
                    duration=shot.duration_sec,
                    source=source,
                    title=scene.title or f"Scene {scene.order}",
                    label=_label(shot),
                )
            )
            if source.asset_id:
                credits += _credit_for(by_id[source.asset_id])
            t += shot.duration_sec
        found = _narration(ordered, assets, local_path)
        if found is not None:
            path, asset_id = found
            narration.append(EditAudio(path, round(scene_start, 3), scene.duration_sec, asset_id))
            credits += _credit_for(assets[asset_id])
    music = None
    if manifest.soundtrack is not None and manifest.soundtrack.music_asset_id:
        music = _real(
            assets.get(manifest.soundtrack.music_asset_id), AssetKind.AUDIO, "audio/", local_path
        )
    return EditPlan(
        shots=shots,
        narration=narration,
        music=music,
        captions=_captions(manifest),
        credits=list(dict.fromkeys(credits)),
        loudness_lufs=manifest.soundtrack.loudness_target_lufs if manifest.soundtrack else -14.0,
    )


# -------------------------------------------------------------------------- ffmpeg
def _even(value: float) -> int:
    return max(2, round(value / 2) * 2)


def _wrap(text: str, width: int, max_lines: int = 3) -> str:
    lines = textwrap.wrap(" ".join(text.split()), width=width) or [""]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][: max(0, width - 3)] + "..."
    return "\n".join(lines)


def end_card_text(plan: EditPlan, width_chars: int) -> str:
    body = [END_CARD_TITLE, ""]
    for line in plan.credits[:8]:
        body.append(_wrap(line, width_chars, max_lines=2))
    if len(plan.credits) > 8:
        body.append(f"+{len(plan.credits) - 8} more in the production manifest")
    return "\n".join(body)


def text_files(plan: EditPlan, output: OutputProfile) -> dict[str, str]:
    """Relative file name -> content for every drawtext text used by the command."""
    w, h = output.width, output.height
    caption_size = max(10, h // 34)
    chars = max(12, int(w / (caption_size * 0.56)))
    files: dict[str, str] = {}
    for i, shot in enumerate(plan.shots):
        if shot.source.kind == "slate":
            files[f"t{i}.txt"] = _wrap(shot.title, max(8, chars // 2), max_lines=2)
        if shot.label:
            files[f"l{i}.txt"] = shot.label[:60]
    for j, cue in enumerate(plan.captions):
        files[f"c{j}.txt"] = _wrap(cue.text, chars)
    files["credits.txt"] = end_card_text(plan, int(chars * 1.2))
    return files


def _fit_clip(source: ShotSource, duration: float) -> str:
    clip = source.clip_duration
    if clip and clip < duration <= clip * MAX_SLOWDOWN:
        return f"setpts={duration / clip:.4f}*PTS,"
    return ""


def build_edit_command(
    plan: EditPlan, output: OutputProfile, out_path: Path, *, text: bool
) -> list[str]:
    """ffmpeg argv. Text inputs are relative files (see ``text_files``) and font.ttf in cwd."""
    w, h, fps = output.width, output.height, output.fps
    total = plan.total_sec
    label_size = max(8, h // 48)
    caption_size = max(10, h // 34)
    title_size = max(12, h // 18)
    credit_size = max(8, h // 52)
    margin = max(4, h // 40)
    font = "fontfile=font.ttf:expansion=none:fontcolor=white"
    inputs: list[str] = []
    chains: list[str] = []
    idx = 0

    def add_input(*args: str) -> int:
        nonlocal idx
        inputs.extend(args)
        idx += 1
        return idx - 1

    for i, shot in enumerate(plan.shots):
        d = shot.duration
        src = shot.source
        if src.kind == "clip":
            k = add_input("-i", str(src.path))
            chain = (
                f"[{k}:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
                f"setsar=1,{_fit_clip(src, d)}fps={fps},"
                f"tpad=stop_mode=clone:stop_duration={d:.3f},"
                f"trim=duration={d:.3f},setpts=PTS-STARTPTS"
            )
        elif src.kind == "still":
            k = add_input(
                "-loop", "1", "-framerate", str(fps), "-t", f"{d:.3f}", "-i", str(src.path)
            )
            frames = max(1, round(d * fps))
            ow, oh = _even(w * STILL_OVERSCAN), _even(h * STILL_OVERSCAN)
            pan_x = {
                "left": f"(iw-iw/zoom)*(1-on/{frames})",
                "right": f"(iw-iw/zoom)*on/{frames}",
            }.get(src.pan, "(iw-iw/zoom)/2")
            chain = (
                f"[{k}:v]scale={ow}:{oh}:force_original_aspect_ratio=increase,crop={ow}:{oh},"
                f"zoompan=z='1+{src.zoom - 1:.4f}*on/{frames}':x='{pan_x}':y='(ih-ih/zoom)/2'"
                f":d=1:s={w}x{h}:fps={fps},"
                f"trim=duration={d:.3f},setpts=PTS-STARTPTS,setsar=1"
            )
        else:
            color = PALETTE[i % len(PALETTE)]
            k = add_input("-f", "lavfi", "-i", f"color=c={color}:s={w}x{h}:r={fps}:d={d:.3f}")
            chain = f"[{k}:v]setsar=1"
            if text:
                chain += (
                    f",drawtext={font}:textfile=t{i}.txt:fontsize={title_size}"
                    ":x=(w-text_w)/2:y=(h-text_h)/2"
                )
        if text and shot.label:
            chain += (
                f",drawtext={font}:textfile=l{i}.txt:fontsize={label_size}"
                f":box=1:boxcolor=black@0.55:boxborderw={max(2, label_size // 3)}"
                f":x={margin}:y={margin}"
            )
        chains.append(f"{chain},format=yuv420p[s{i}]")

    n = len(plan.shots)
    k = add_input("-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r={fps}:d={plan.end_card_sec:.3f}")
    card = f"[{k}:v]setsar=1"
    if text:
        card += (
            f",drawtext={font}:textfile=credits.txt:fontsize={credit_size}"
            f":line_spacing={credit_size // 2}:x=(w-text_w)/2:y=(h-text_h)/2"
        )
    chains.append(f"{card},format=yuv420p[s{n}]")
    concat = "".join(f"[s{i}]" for i in range(n + 1))
    if text and plan.captions:
        chains.append(f"{concat}concat=n={n + 1}:v=1:a=0[vcat]")
        draws = [
            f"drawtext={font}:textfile=c{j}.txt:fontsize={caption_size}"
            f":line_spacing={caption_size // 4}:box=1:boxcolor=black@0.5"
            f":boxborderw={max(2, caption_size // 3)}:x=(w-text_w)/2:y=h*0.72"
            f":enable='between(t,{cue.start:.3f},{cue.end:.3f})'"
            for j, cue in enumerate(plan.captions)
        ]
        chains.append("[vcat]" + ",".join(draws) + "[vout]")
    else:
        chains.append(f"{concat}concat=n={n + 1}:v=1:a=0[vout]")

    base = add_input("-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo")
    mix = [f"[{base}:a]"]
    for j, track in enumerate(plan.narration):
        k = add_input("-i", str(track.path))
        delay = round(track.start * 1000)
        fade_at = max(0.0, track.duration - NARRATION_FADE_SEC)
        chains.append(
            f"[{k}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"atrim=duration={track.duration:.3f},"
            f"afade=t=out:st={fade_at:.3f}:d={NARRATION_FADE_SEC},"
            f"adelay={delay}|{delay}[n{j}]"
        )
        mix.append(f"[n{j}]")
    if plan.music is not None:
        k = add_input("-i", str(plan.music))
        chains.append(
            f"[{k}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"volume={MUSIC_VOLUME},atrim=duration={total:.3f}[mus]"
        )
        mix.append("[mus]")
    if len(mix) == 1:
        chains.append(f"{mix[0]}atrim=duration={total:.3f}[aout]")
    else:
        chains.append(
            "".join(mix)
            + f"amix=inputs={len(mix)}:duration=first:dropout_transition=0:normalize=0,"
            f"atrim=duration={total:.3f},"
            f"loudnorm=I={plan.loudness_lufs}:TP=-1.5:LRA=11,aresample=48000[aout]"
        )

    return [
        _binary("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
        *inputs,
        "-filter_complex", ";".join(chains),
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-r", str(fps),
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
        "-t", f"{total:.3f}",
        "-movflags", "+faststart",
        str(out_path),
    ]  # fmt: skip


def render_master_edit(
    plan: EditPlan,
    output: OutputProfile,
    out_path: Path,
    *,
    timeout: float = RENDER_TIMEOUT_SEC,
) -> tuple[Path, bool]:
    """Render ``plan`` to ``out_path``. Returns (absolute path, text overlays drawn)."""
    out_path = Path(out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    font = find_font()
    text = font is not None and has_drawtext()
    with tempfile.TemporaryDirectory(prefix="cineforge-edit-") as workdir:
        work = Path(workdir)
        if text:
            os.symlink(font, work / "font.ttf")
            for name, content in text_files(plan, output).items():
                (work / name).write_text(content, encoding="utf-8")
        cmd = build_edit_command(plan, output, out_path, text=text)
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
    return out_path, text
