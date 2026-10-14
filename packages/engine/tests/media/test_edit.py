from __future__ import annotations

import itertools
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from cineforge.config import Settings
from cineforge.contracts.agents import AgentRun, AgentRunStatus, AssetCandidate, AssetSelection
from cineforge.contracts.common import AgentId
from cineforge.contracts.manifest import AssetRef, AssetRole, ProductionManifest
from cineforge.contracts.media import (
    AssetKind,
    AssetOrigin,
    AssetRecord,
    LicenseInfo,
    RightsDecision,
    RightsStatus,
    storage_key,
)
from cineforge.contracts.workflow import ProductionState
from cineforge.media import edit, jobs
from cineforge.media.render import RenderError, probe, probe_summary, validate_master
from cineforge.runtime import Runtime, set_runtime
from fakes_d import fake_runtime, small_manifest

PID = "prod_sample0000000001"
TENANT = "tenant_demo"


def _ffmpeg(*args: str) -> None:
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True, timeout=60
    )


def _register(
    rt: Runtime, path: Path, kind: AssetKind, content_type: str, *, name: str, **extra
) -> AssetRecord:
    key = storage_key(TENANT, PID, kind, name)
    stored = rt.storage.put_file(key, path, content_type)
    return rt.assets.add(
        AssetRecord(
            tenant_id=TENANT,
            production_id=PID,
            kind=kind,
            origin=extra.pop("origin", AssetOrigin.GENERATED),
            storage_backend=stored.backend,
            storage_key=stored.key,
            uri=stored.uri,
            content_type=content_type,
            size_bytes=stored.size_bytes,
            sha256=stored.sha256,
            rights=RightsDecision(status=RightsStatus.APPROVED),
            **extra,
        )
    )


@pytest.fixture
def rt(tmp_path: Path) -> Iterator[Runtime]:
    runtime = fake_runtime(
        Settings(
            persistence_backend="memory",
            queue_backend="inline",
            storage_local_root=tmp_path / "media",
        )
    )
    set_runtime(runtime)
    yield runtime
    set_runtime(None)


@pytest.fixture
def media(tmp_path: Path, require_ffmpeg: None) -> dict[str, Path]:
    out = {
        "clip": tmp_path / "clip.mp4",
        "still": tmp_path / "still.png",
        "voice": tmp_path / "voice.wav",
    }
    _ffmpeg(
        "-f", "lavfi", "-i", "testsrc=s=160x90:r=24:d=0.8", "-pix_fmt", "yuv420p", str(out["clip"])
    )
    _ffmpeg("-f", "lavfi", "-i", "color=c=red:s=400x300:d=1", "-frames:v", "1", str(out["still"]))
    _ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=1.4", str(out["voice"]))
    return out


def _wire(rt: Runtime, media: dict[str, Path]) -> ProductionManifest:
    """scene 1: generated clip (synthetic) + licensed still; scene 2: narration audio."""
    clip = _register(
        rt, media["clip"], AssetKind.VIDEO, "video/mp4", name="clip.mp4", duration_sec=0.45,
        generation={"provider": "higgsfield", "model": "kling2_6"},
        metadata={"derived_from": {"attribution": "Square by A, CC BY 4.0"}},
    )  # fmt: skip
    _register(
        rt, media["still"], AssetKind.IMAGE, "image/png", name="still.png",
        origin=AssetOrigin.OPEN_LICENSE,
        license=LicenseInfo(license_type="CC-BY-4.0", attribution_text="Tower by B, CC BY 4.0"),
        metadata={"candidate_id": "asset_cand_x_02"},
    )  # fmt: skip
    voice = _register(
        rt, media["voice"], AssetKind.AUDIO, "audio/wav", name="voice.wav",
        generation={"provider": "higgsfield", "model": "seed_audio"},
    )  # fmt: skip
    mock = _register(
        rt, media["clip"], AssetKind.VIDEO, "video/mp4", name="mock.json",
        generation={"provider": "mock-video"},
    )  # fmt: skip
    rt.storage.delete(mock.storage_key)  # mock outputs have no file

    m = small_manifest()
    s1, s2 = m.scenes[0], m.scenes[1]
    s1.shots[0].assets = [
        AssetRef(asset_id=clip.id, role=AssetRole.GENERATED),
        AssetRef(asset_id=mock.id, role=AssetRole.GENERATED),
    ]
    s1.shots[0].disclosure.synthetic_media = True
    s1.shots[0].disclosure.label_text = "AI-generated"
    s1.shots[1].disclosure.synthetic_media = False
    s1.shots[1].disclosure.reconstruction = False
    s1.shots[1].assets = [
        AssetRef(
            asset_id="asset_cand_x_02",
            role=AssetRole.SOURCE,
            transform={"ken_burns": {"zoom": 1.1, "pan": "left"}},
        )
    ]
    s2.shots[0].assets = [AssetRef(asset_id=voice.id, role=AssetRole.AUDIO)]
    m.state = ProductionState.READY
    rt.productions.create(m)
    return m


def _plan(rt: Runtime, m: ProductionManifest) -> edit.EditPlan:
    assets = {a.id: a for a in rt.assets.list_for_production(PID, TENANT)}
    stills = {
        a.metadata["candidate_id"]: a for a in assets.values() if "candidate_id" in a.metadata
    }
    return edit.build_edit_plan(
        m, assets, stills=stills, local_path=lambda a: rt.storage.local_path(a.storage_key)
    )


# ----------------------------------------------------------------------------- planning
def test_caption_chunks_split_and_time() -> None:
    cues = edit.caption_chunks(
        "one two three four five six seven eight nine ten", 2.0, 4.0, max_words=4
    )
    assert [c.text for c in cues] == ["one two three four", "five six seven eight", "nine ten"]
    assert cues[0].start == 2.0 and cues[-1].end == 4.0
    assert all(a.end == b.start for a, b in itertools.pairwise(cues))
    assert edit.caption_chunks("", 0, 1) == [] and edit.caption_chunks("x", 1, 1) == []


@pytest.mark.ffmpeg
def test_plan_picks_clip_then_still_then_slate(rt: Runtime, media: dict[str, Path]) -> None:
    m = _wire(rt, media)
    plan = _plan(rt, m)

    kinds = [s.source.kind for s in plan.shots]
    assert kinds[:2] == ["clip", "still"] and set(kinds[2:]) == {"slate"}
    assert plan.shots[0].label == "AI-generated" and plan.shots[1].label is None
    assert plan.shots[1].source.zoom == pytest.approx(1.1) and plan.shots[1].source.pan == "left"
    assert plan.shots[0].source.clip_duration == pytest.approx(0.45)
    (track,) = plan.narration
    assert track.start == pytest.approx(1.0) and track.duration == pytest.approx(1.0)
    assert plan.total_sec == pytest.approx(5.0 + edit.END_CARD_SEC)
    assert plan.credits == [
        "Photo: Square by A, CC BY 4.0",
        "Animation: AI (higgsfield kling2_6)",
        "Photo: Tower by B, CC BY 4.0",
        "Narration: AI (higgsfield seed_audio)",
    ]
    assert [c.text for c in plan.captions][:1] == ["Narration for hook."]
    summary = plan.summary()
    assert (summary["clips"], summary["stills"], summary["narration_tracks"]) == (1, 1, 1)


def test_text_files_and_command_shape(tmp_path: Path) -> None:
    m = small_manifest()
    clip = edit.ShotSource("clip", tmp_path / "c.mp4", "x", 0.9)
    still = edit.ShotSource("still", tmp_path / "s.png", "y")
    plan = edit.EditPlan(
        shots=[
            edit.EditShot("scene_01", "a", 0.0, 1.0, clip, label="AI-generated"),
            edit.EditShot("scene_01", "b", 1.0, 1.0, still),
            edit.EditShot("scene_02", "c", 2.0, 1.0, edit.ShotSource("slate"), title="Arrival"),
        ],
        narration=[edit.EditAudio(tmp_path / "v.wav", 2.0, 1.0, "z")],
        captions=[edit.CaptionCue(0.0, 1.0, "Hello there")],
        credits=["Photo: Someone"],
    )  # fmt: skip
    files = edit.text_files(plan, m.output)
    assert set(files) == {"l0.txt", "t2.txt", "c0.txt", "credits.txt"}
    assert files["credits.txt"].startswith(edit.END_CARD_TITLE)
    cmd = edit.build_edit_command(plan, m.output, tmp_path / "o.mp4", text=True)
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "setpts=1.1111*PTS" in graph  # 0.9 s clip slowed to fill 1 s
    assert "tpad=stop_mode=clone" in graph and "zoompan=" in graph
    assert "textfile=l0.txt" in graph and "enable='between(t,0.000,1.000)'" in graph
    assert "adelay=2000|2000" in graph and "loudnorm=I=-14.0" in graph
    assert cmd[cmd.index("-movflags") - 1] == "6.000"  # output -t: 3 s timeline + end card
    plain = edit.build_edit_command(plan, m.output, tmp_path / "o.mp4", text=False)
    assert "drawtext" not in plain[plain.index("-filter_complex") + 1]


# ------------------------------------------------------------------------------- render
@pytest.mark.ffmpeg
def test_render_edit_master(rt: Runtime, media: dict[str, Path], tmp_path: Path) -> None:
    m = _wire(rt, media)
    plan = _plan(rt, m)
    out, text = edit.render_master_edit(plan, m.output, tmp_path / "master.mp4")
    info = probe(out)
    assert validate_master(info, m.output, plan.total_sec) == []
    summary = probe_summary(info)
    assert (summary["width"], summary["height"]) == (180, 320)
    assert summary["audio_codec"] == "aac"
    assert summary["duration_sec"] == pytest.approx(8.0, abs=0.3)
    assert isinstance(text, bool)


@pytest.mark.ffmpeg
def test_forced_rerender_creates_new_version(rt: Runtime, media: dict[str, Path]) -> None:
    m = _wire(rt, media)
    for shot in (m.scenes[2].shots[0], m.scenes[3].shots[0]):
        shot.assets.append(AssetRef(asset_id="asset_cand_mock", role=AssetRole.SOURCE))
    rt.productions.save(m)
    rt.agent_runs.runs["run_a3"] = AgentRun(
        id="run_a3",
        production_id=PID,
        tenant_id=TENANT,
        agent_id=AgentId.MEDIA_DISCOVERY,
        step=ProductionState.RESEARCHING,
        status=AgentRunStatus.SUCCEEDED,
        idempotency_key="a3",
        output=AssetSelection(
            candidates=[
                AssetCandidate(
                    candidate_id="asset_cand_mock",
                    provider="mock-media-search",
                    media_type="image",
                    title="mock",
                    source_url="https://example.invalid/x",
                )
            ]
        ).model_dump(mode="json"),
        output_model="AssetSelection",
    )
    first = jobs.render_master(
        production_id=PID, tenant_id=TENANT, idempotency_key="r1", force=True, requested_by="op"
    )
    again = jobs.render_master(
        production_id=PID, tenant_id=TENANT, idempotency_key="r1", force=True, requested_by="op"
    )
    second = jobs.render_master(
        production_id=PID, tenant_id=TENANT, idempotency_key="r2", force=True
    )
    assert first == again != second
    renders = [a for a in rt.assets.list_for_production(PID, TENANT) if a.kind == AssetKind.RENDER]
    assert [a.storage_key.rsplit("/", 1)[1] for a in renders] == ["master_v1.mp4", "master_v2.mp4"]
    assert renders[0].generation["edit"]["clips"] == 1
    manifest = rt.productions.get(PID, TENANT)
    assert manifest.master_render_asset_id == second
    assert manifest.state == ProductionState.READY
    rerenders = [a for a in manifest.audit if a.action == "master_rerendered"]
    assert rerenders[0].details["requested_by"] == "op"
    assert rerenders[1].details["previous_asset_id"] == first
    assert rt.queue.jobs == []  # no advance hand-off for a re-render


def test_forced_rerender_requires_ready(rt: Runtime) -> None:
    m = small_manifest()
    m.state = ProductionState.GENERATING
    rt.productions.create(m)
    with pytest.raises(RenderError, match="READY"):
        jobs.render_master(production_id=PID, tenant_id=TENANT, idempotency_key="r", force=True)
    assert rt.productions.get(PID, TENANT).state == ProductionState.GENERATING
