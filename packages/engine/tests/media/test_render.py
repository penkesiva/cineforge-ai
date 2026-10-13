from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from cineforge.contracts.review import ReviewGate, Severity
from cineforge.media import render
from cineforge.media.render import (
    RenderError,
    expected_duration,
    probe,
    probe_summary,
    render_master_slate,
    slate_segments,
    validate_master,
)
from fakes_d import SMALL_OUTPUT as SMALL
from fakes_d import small_manifest


def _probe_dict(**overrides: Any) -> dict[str, Any]:
    video = {"codec_type": "video", "codec_name": "h264", "width": 180, "height": 320,
             "avg_frame_rate": "24/1", "pix_fmt": "yuv420p"}  # fmt: skip
    audio = {"codec_type": "audio", "codec_name": "aac"}
    fmt = {"duration": "5.0", "format_name": "mov,mp4,m4a,3gp,3g2,mj2"}
    video.update(overrides.pop("video", {}))
    fmt.update(overrides.pop("format", {}))
    streams = [video] + ([] if overrides.pop("no_audio", False) else [audio])
    return {"streams": streams, "format": fmt}


def test_segments() -> None:
    m = small_manifest()
    segs = slate_segments(m)
    assert [s.subtitle for s in segs] == [f"Scene {i}" for i in range(1, 6)]
    assert segs[0].title == "Hook"
    assert expected_duration(m) == pytest.approx(5.0)
    single = slate_segments(small_manifest(with_scenes=False))
    assert len(single) == 1 and single[0].duration_sec == 2


def test_validate_clean_probe_has_no_findings() -> None:
    assert validate_master(_probe_dict(), SMALL, 5.0) == []


@pytest.mark.parametrize(
    ("probe_overrides", "expected_duration_sec", "message"),
    [
        ({"video": {"width": 1080}}, 5.0, "resolution"),
        ({"video": {"codec_name": "vp9"}}, 5.0, "video codec"),
        ({"no_audio": True}, 5.0, "no audio"),
        ({}, 6.0, "duration"),
        ({"format": {"duration": "4.2"}}, 5.0, "duration"),
    ],
)
def test_validate_flags_critical(
    probe_overrides: dict[str, Any], expected_duration_sec: float, message: str
) -> None:
    findings = validate_master(_probe_dict(**probe_overrides), SMALL, expected_duration_sec)
    critical = [f for f in findings if f.severity == Severity.CRITICAL]
    assert critical and any(message in f.message for f in critical)
    assert all(f.gate == ReviewGate.MASTER and f.blocking for f in critical)


def test_validate_minor_mismatches_are_major_not_blocking() -> None:
    findings = validate_master(
        _probe_dict(video={"avg_frame_rate": "30/1", "pix_fmt": "yuv444p"}), SMALL, 5.0
    )
    assert findings and all(f.severity == Severity.MAJOR for f in findings)
    assert not any(f.blocking for f in findings)


def test_validate_no_video_stream() -> None:
    findings = validate_master({"streams": [], "format": {"duration": "5"}}, SMALL, 5.0)
    assert len(findings) == 1 and findings[0].blocking


def test_missing_ffmpeg_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(render.shutil, "which", lambda name: None)
    with pytest.raises(RenderError, match="not found"):
        render_master_slate(small_manifest(), tmp_path / "m.mp4")


@pytest.mark.ffmpeg
def test_slate_matches_output_profile(require_ffmpeg: None, tmp_path: Path) -> None:
    m = small_manifest()
    out = render_master_slate(m, tmp_path / "out" / "master.mp4")
    assert out.is_file() and out.is_absolute()
    info = probe(out)
    s = probe_summary(info)
    assert (s["width"], s["height"]) == (180, 320)
    assert s["codec"] == "h264" and s["pix_fmt"] == "yuv420p"
    assert s["audio_codec"] == "aac"
    assert s["fps"] == pytest.approx(24)
    assert s["duration_sec"] == pytest.approx(5.0, abs=0.5)
    assert validate_master(info, m.output, expected_duration(m)) == []
    assert sorted(p.name for p in out.parent.iterdir()) == ["master.mp4"]


@pytest.mark.ffmpeg
def test_validate_flags_deliberate_mismatch(require_ffmpeg: None, tmp_path: Path) -> None:
    m = small_manifest()
    info = probe(render_master_slate(m, tmp_path / "m.mp4"))
    wrong = m.output.model_copy(update={"width": 1080, "height": 1920})
    findings = validate_master(info, wrong, expected_duration(m) + 2.0)
    critical = [f.message for f in findings if f.severity == Severity.CRITICAL]
    assert any("resolution" in msg for msg in critical)
    assert any("duration" in msg for msg in critical)


@pytest.mark.ffmpeg
def test_no_scenes_and_no_font(
    require_ffmpeg: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(render, "find_font", lambda: None)
    m = small_manifest(with_scenes=False)
    info = probe(render_master_slate(m, tmp_path / "m.mp4"))
    assert probe_summary(info)["duration_sec"] == pytest.approx(2.0, abs=0.5)
    assert validate_master(info, m.output, 2.0) == []


@pytest.mark.ffmpeg
def test_ffmpeg_failure_raises_render_error(
    require_ffmpeg: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    m = small_manifest()
    m.output = m.output.model_copy(update={"width": 181})  # odd width: libx264/yuv420p rejects
    with pytest.raises(RenderError, match="ffmpeg failed"):
        render_master_slate(m, tmp_path / "m.mp4")
    assert not (tmp_path / "m.mp4").exists()
