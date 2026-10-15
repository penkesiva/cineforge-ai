"""Fully generative (vlog) productions: staged gates, shot redo, credit cap, live blockers."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import pytest
from cineforge.contracts.api import (
    ApproveProductionRequest,
    CreateProductionRequest,
    RegenerateShotRequest,
)
from cineforge.contracts.common import ProductionMode, money
from cineforge.contracts.manifest import (
    ApprovalStage,
    AssetRole,
    AuthoredScript,
    ProductionLook,
    ProductionReference,
    ScriptLine,
    ShotKind,
    WorkStatus,
)
from cineforge.contracts.media import (
    AssetKind,
    AssetOrigin,
    AssetRecord,
    LicenseInfo,
    RightsDecision,
    RightsStatus,
)
from cineforge.contracts.providers import (
    PriceUnit,
    ProviderCapability,
    ProviderError,
    ProviderInfo,
    ProviderRequest,
    ProviderResponse,
    ProviderStatus,
    ProviderUsage,
)
from cineforge.contracts.workflow import ProductionState
from cineforge.cost.factory import load_price_catalog
from cineforge.orchestration import external, studio
from cineforge.orchestration.studio import pilot_shots, stage_state
from cineforge.orchestration.workflow import (
    ApprovalBlockedError,
    InvalidProductionInputError,
    RegenerateError,
    WorkflowEngine,
)
from fakes_b import make_runtime

S = ProductionState
C = ProviderCapability
TENANT = "tenant_demo"
TOPIC = "A day at the 1889 World's Fair in Paris"


def _engine(**settings: Any):
    rt, fx = make_runtime(**settings)
    catalog = load_price_catalog(rt.settings)
    rt.__dict__["price_catalog"] = catalog
    fx.guard.catalog = catalog
    return rt, fx, WorkflowEngine(rt)


def _create(wf: WorkflowEngine, **kw: Any):
    req = CreateProductionRequest(
        topic=TOPIC, theme_id="lena-vlog", mode=ProductionMode.PREMIUM, duration_target_sec=75, **kw
    )
    return wf.create_production(req, TENANT)


def m_rules(wf: WorkflowEngine, m):
    return wf.theme_for(m).production.generative


def _approve(wf: WorkflowEngine, pid: str):
    return wf.approve(pid, TENANT, ApproveProductionRequest(approved_by="qa"))


@dataclass
class FakeHiggsfield:
    """Signed-in Higgsfield stand-in: credit-priced, returns CDN URLs and job ids."""

    info: ProviderInfo = field(
        default_factory=lambda: ProviderInfo(
            name="higgsfield",
            display_name="Higgsfield",
            capabilities=[C.IMAGE_GENERATION, C.IMAGE_TO_VIDEO, C.VOICE_TTS],
            models=["nano_banana_2"],
            is_mock=False,
            is_paid=True,
        )
    )
    invocations: list[ProviderRequest] = field(default_factory=list)

    def estimate_usage(self, request: ProviderRequest) -> ProviderUsage:
        if request.capability == C.IMAGE_GENERATION:
            credits = Decimal(2)
        elif request.capability == C.VOICE_TTS:
            credits = Decimal("0.6")
        else:
            credits = Decimal(str(round(2 * float(request.parameters["duration_sec"]), 2)))
        return ProviderUsage(units=credits, unit=PriceUnit.CREDIT, credits=credits)

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        self.invocations.append(request)
        n = len(self.invocations)
        ext = {C.IMAGE_GENERATION: "png", C.VOICE_TTS: "mp3"}.get(request.capability, "mp4")
        return ProviderResponse(
            provider="higgsfield",
            model=request.model,
            capability=request.capability,
            provider_request_id=f"job_{n}",
            output_data={
                "result_url": f"https://cdn.higgsfield.ai/r/{n}.{ext}",
                "job_id": f"job_{n}",
            },
            usage=self.estimate_usage(request),
        )


def _fake_store(rt):
    def store(rt_, manifest, *, url, kind, event, job_id, prompt, parameters, **kw):
        record = AssetRecord(
            tenant_id=manifest.tenant_id,
            production_id=manifest.production_id,
            kind=kind,
            origin=AssetOrigin.GENERATED,
            storage_backend="local",
            storage_key=f"tenants/{manifest.tenant_id}/{job_id}",
            uri=url,
            content_type="application/octet-stream",
            size_bytes=1,
            sha256="0" * 64,
            license=LicenseInfo(license_type="generated", commercial_use_allowed=True),
            rights=RightsDecision(status=RightsStatus.APPROVED),
            generation={"provider": event.provider, "job_id": job_id, "prompt": prompt},
            metadata={"ledger_event_id": event.event_id, **(kw.get("metadata") or {})},
        )
        return rt.assets.add(record)

    return store


# --------------------------------------------------------------------------- mock flow
def test_vlog_runs_script_preview_pilot_final_gates_in_mock_mode() -> None:
    rt, _, wf = _engine()
    assert _create(wf).budget.limit == money(Decimal(300) * Decimal("0.043") + 1)
    m = _create(wf, budget_limit_usd=Decimal(100))  # mock prices are not credit-sized
    pid = m.production_id
    assert m.persona_id == "lena-voss"

    wf.start(pid, TENANT)
    m = rt.productions.get(pid, TENANT)
    assert m.state == S.AWAITING_APPROVAL and m.approval_stage == ApprovalStage.SCRIPT
    shots = list(m.iter_shots())
    a_roll = [s for s in shots if s.kind == ShotKind.A_ROLL]
    b_roll = [s for s in shots if s.kind == ShotKind.B_ROLL]
    assert a_roll and b_roll
    assert all(s.audio.dialogue_text for s in a_roll)
    assert all(s.disclosure.synthetic_media for s in shots)
    assert all(s.estimated_cost > 0 for s in shots)
    assert m.captions and m.captions[0].cues
    assert all(len(c.text.split()) <= 6 for c in m.captions[0].cues)
    quote = wf.stage_quote(pid, TENANT)
    assert quote.stage == "preview"
    assert quote.items == len(shots) + len(a_roll)

    _approve(wf, pid)
    m = rt.productions.get(pid, TENANT)
    assert m.state == S.AWAITING_APPROVAL and m.approval_stage == ApprovalStage.PREVIEW
    for shot in m.iter_shots():
        assert stage_state(shot, "still").get("done")
        assert not stage_state(shot, "clip").get("done")
    assert all(stage_state(s, "voice").get("done") for s in m.iter_shots() if s.kind == "a_roll")

    _approve(wf, pid)
    m = rt.productions.get(pid, TENANT)
    assert m.approval_stage == ApprovalStage.PILOT
    clipped = [s for s in m.iter_shots() if stage_state(s, "clip").get("done")]
    assert {s.kind for s in clipped} == {ShotKind.A_ROLL, ShotKind.B_ROLL}
    assert len(clipped) == 2

    _approve(wf, pid)
    m = rt.productions.get(pid, TENANT)
    assert m.state == S.READY, [e.message for e in rt.productions.events(pid, TENANT)][-5:]
    assert all(s.status == WorkStatus.COMPLETE for s in m.iter_shots())


# --------------------------------------------------------------------------- live path
def test_signed_in_provider_chains_still_and_voice_into_clips(monkeypatch) -> None:
    rt, fx, wf = _engine()
    higgs = FakeHiggsfield()
    fx.providers.register(higgs)
    monkeypatch.setattr(external, "store_result", _fake_store(rt))
    m = _create(wf)
    pid = m.production_id
    wf.start(pid, TENANT)
    _approve(wf, pid)  # preview
    m = rt.productions.get(pid, TENANT)
    shot = next(s for s in m.iter_shots() if s.kind == ShotKind.A_ROLL)
    still, voice = stage_state(shot, "still"), stage_state(shot, "voice")
    assert still["provider"] == "higgsfield" and still["job"].startswith("job_")
    assert any(a.role == AssetRole.KEYFRAME for a in shot.assets)
    assert shot.audio.dialogue_ref and any(a.role == AssetRole.AUDIO for a in shot.assets)
    still_calls = [r for r in higgs.invocations if r.capability == C.IMAGE_GENERATION]
    assert all("<<<" in (r.prompt or "") for r in still_calls if "selfie" in (r.prompt or ""))
    voice_calls = [r for r in higgs.invocations if r.capability == C.VOICE_TTS]
    assert len(voice_calls) == sum(1 for s in m.iter_shots() if s.kind == ShotKind.A_ROLL)

    _approve(wf, pid)  # pilot
    clips = [r for r in higgs.invocations if r.capability == C.IMAGE_TO_VIDEO]
    assert len(clips) == 2
    a_clip = next(r for r in clips if r.shot_id == shot.id)
    medias = {m_["role"]: m_["value"] for m_ in a_clip.parameters["medias"]}
    assert medias == {"start_image": still["job"], "audio_references": voice["job"]}
    assert a_clip.model == "wan2_7"
    b_clip = next(r for r in clips if r.shot_id != shot.id)
    assert b_clip.model == "kling3_0"
    assert [x["role"] for x in b_clip.parameters["medias"]] == ["start_image"]

    m = rt.productions.get(pid, TENANT)
    quote = wf.stage_quote(pid, TENANT)
    assert quote.stage == "final"
    assert quote.credits_used > 0
    assert quote.credit_cap == 300
    kinds = {r.kind for r in rt.assets.list_for_production(pid, TENANT)}
    assert {AssetKind.IMAGE, AssetKind.AUDIO, AssetKind.VIDEO} <= kinds


def test_credit_cap_pauses_generation(monkeypatch) -> None:
    rt, fx, wf = _engine()
    fx.providers.register(FakeHiggsfield())
    monkeypatch.setattr(external, "store_result", _fake_store(rt))
    monkeypatch.setattr(studio.VlogStudio, "credits_used", lambda self, m, rules: Decimal(299))
    m = _create(wf)
    wf.start(m.production_id, TENANT)
    _approve(wf, m.production_id)
    m = rt.productions.get(m.production_id, TENANT)
    assert m.state == S.PAUSED_BUDGET
    assert "credit cap" in rt.productions.events(m.production_id, TENANT)[-1].message


# --------------------------------------------------------------------------- redo
def test_voice_redo_changes_line_and_marks_clip_stale() -> None:
    rt, _, wf = _engine()
    m = _create(wf)
    pid = m.production_id
    wf.start(pid, TENANT)
    shot = next(s for s in rt.productions.get(pid, TENANT).iter_shots() if s.kind == "a_roll")
    with pytest.raises(RegenerateError):
        wf.regenerate_shot(pid, TENANT, shot.id, RegenerateShotRequest(target="voice"))
    _approve(wf, pid)  # preview
    _approve(wf, pid)  # pilot: the first A-roll shot gets a clip

    req = RegenerateShotRequest(target="voice", dialogue_text="Okay, this is the new line.")
    result = wf.regenerate_shot(pid, TENANT, shot.id, req)
    assert result.job_id.endswith(f"{shot.id}:voice:2")
    m = rt.productions.get(pid, TENANT)
    redone = m.find_shot(shot.id)
    assert redone.audio.dialogue_text == "Okay, this is the new line."
    assert stage_state(redone, "voice")["attempt"] == 2
    assert stage_state(redone, "clip")["stale"] is True
    assert redone.status == WorkStatus.PLANNED
    assert any(c.text.startswith("Okay, this is the") for c in m.captions[0].cues)
    assert m.state == S.AWAITING_APPROVAL
    assert rt.productions.events(pid, TENANT)[-1].event_type == "regenerate_finished"

    with pytest.raises(RegenerateError):
        b = next(s for s in m.iter_shots() if s.kind == "b_roll")
        wf.regenerate_shot(pid, TENANT, b.id, RegenerateShotRequest(target="voice"))


def test_still_redo_adds_note_to_prompt() -> None:
    rt, fx, wf = _engine()
    m = _create(wf)
    pid = m.production_id
    wf.start(pid, TENANT)
    _approve(wf, pid)
    shot = next(rt.productions.get(pid, TENANT).iter_shots())
    req = RegenerateShotRequest(target="still", note="warmer light, she smiles")
    wf.regenerate_shot(pid, TENANT, shot.id, req)
    prompts = [r.prompt for _, r, _, _ in fx.guard.calls if r.shot_id == shot.id]
    assert "warmer light, she smiles" in prompts[-1]
    assert stage_state(rt.productions.get(pid, TENANT).find_shot(shot.id), "still")["attempt"] == 2


# --------------------------------------------------------------------------- live blockers
def test_live_mode_blocks_approval_without_sign_in() -> None:
    rt, _, wf = _engine(provider_mode="live")
    m = _create(wf)
    wf.start(m.production_id, TENANT)
    with pytest.raises(ApprovalBlockedError) as exc:
        _approve(wf, m.production_id)
    assert "higgsfield is not ready" in str(exc.value)
    assert "sign in on the Sources page" in str(exc.value)
    assert "choose a voice" not in str(exc.value)
    assert rt.productions.get(m.production_id, TENANT).approval_stage == ApprovalStage.SCRIPT


def test_live_mode_names_a_disabled_provider(monkeypatch) -> None:
    _, fx, wf = _engine(provider_mode="live")
    disabled = (ProviderStatus.DISABLED, "Disabled on the Sources page")
    monkeypatch.setattr(type(fx.providers), "status", lambda self, name, tenant: disabled)
    m = _create(wf)
    wf.start(m.production_id, TENANT)
    with pytest.raises(ApprovalBlockedError, match="enable higgsfield on the Sources page"):
        _approve(wf, m.production_id)


def test_live_mode_blocks_approval_without_a_voice(monkeypatch) -> None:
    _, _, wf = _engine(provider_mode="live")
    m = _create(wf)
    wf.start(m.production_id, TENANT)
    voiceless = wf.persona_for(m)
    voiceless = voiceless.model_copy(
        update={"voice": voiceless.voice.model_copy(update={"voice_id": None})}
    )
    monkeypatch.setattr(studio.VlogStudio, "persona", lambda self, m: voiceless)
    with pytest.raises(ApprovalBlockedError, match="choose a voice for Lena Voss"):
        _approve(wf, m.production_id)


def test_lena_speaks_with_juno_on_elevenlabs(monkeypatch) -> None:
    rt, fx, wf = _engine()
    higgs = FakeHiggsfield()
    fx.providers.register(higgs)
    monkeypatch.setattr(external, "store_result", _fake_store(rt))
    m = _create(wf)
    wf.start(m.production_id, TENANT)
    _approve(wf, m.production_id)
    lines = [r for r in higgs.invocations if r.capability == C.VOICE_TTS]
    assert lines
    for r in lines:
        assert r.model == "text2speech_v2"
        assert r.parameters["variant"] == "elevenlabs"
        assert r.parameters["voice_id"] == "a3ce02fe-4d3e-55bc-b4d4-a4801b9acdb4"


def test_production_pins_persona_version_and_remembers_past_trips() -> None:
    rt, _, wf = _engine()
    m = _create(wf)
    assert (m.persona_id, m.persona_version) == ("lena-voss", 2)
    assert wf.persona_for(m).version == 2

    done = m.model_copy(
        update={"production_id": "prod_pastrip0000001", "title": "Pompeii", "state": S.DELIVERED}
    )
    rt.productions.create(done)
    other = done.model_copy(
        update={"production_id": "prod_otherhost00001", "title": "Other", "persona_id": "x"}
    )
    rt.productions.create(other)

    canon = wf.canon_for(m)
    titles = [e.title for e in canon.episodes]
    assert titles == ["Pompeii"]
    assert canon.episodes[0].production_id == "prod_pastrip0000001"
    assert canon.facts
    assert wf.canon_for(done).episodes == []


# --------------------------------------------------------------------------- authored brief
PILLAR = "ref_hanging_pillar"


def _reference(rt, *, approved: bool = True) -> str:
    key = f"tenants/{TENANT}/library/reference/pillar.png"
    rt.storage.put_bytes(key, b"png-bytes", "image/png")
    record = AssetRecord(
        tenant_id=TENANT,
        kind=AssetKind.REFERENCE,
        origin=AssetOrigin.UPLOADED,
        storage_backend="fake",
        storage_key=key,
        uri=f"local://{key}",
        content_type="image/png",
        size_bytes=9,
        sha256="0" * 64,
        license=LicenseInfo(
            license_type="customer-upload", commercial_use_allowed=True if approved else None
        ),
        rights=RightsDecision(status=RightsStatus.APPROVED if approved else RightsStatus.BLOCKED),
    )
    return rt.assets.add(record).id


def _brief(asset_id: str, **line_overrides: Any) -> dict[str, Any]:
    look = ProductionLook(
        wardrobe="an ivory Kalamkari kurta over light-wash jeans",
        location="a 16th-century granite temple hall",
        references=[ProductionReference(id=PILLAR, asset_id=asset_id, description="pillar")],
    )
    lines = [
        ScriptLine(
            scene_order=1,
            kind="dialogue",
            text="Wait. How is this pillar not touching the floor?!",
            visual="she crouches by the pillar",
            on_screen_text="A 500-YEAR-OLD MYSTERY",
            refs=[PILLAR],
        ),
        ScriptLine(
            scene_order=1,
            kind="broll",
            voiceover=True,
            text="No strings. No tricks.",
            visual="a scarf slides under the pillar base",
            motion="the scarf slides through the gap",
            refs=[PILLAR],
            duration_sec=6,
        ),
        ScriptLine(scene_order=2, kind="broll", text="silent", visual="wide temple courtyard"),
        ScriptLine(
            **{"scene_order": 3, "kind": "dialogue", "text": "Would you trust it?"} | line_overrides
        ),
    ]
    return {"look": look, "script": AuthoredScript(lines=lines)}


def test_authored_script_skips_the_writer_and_voices_the_cutaway() -> None:
    rt, _, wf = _engine()
    m = _create(wf, **_brief(_reference(rt)))
    pid = m.production_id
    assert m.look is not None and m.authored_script is not None
    wf.start(pid, TENANT)
    m = rt.productions.get(pid, TENANT)
    assert m.approval_stage == ApprovalStage.SCRIPT
    shots = list(m.iter_shots())
    assert [s.kind for s in shots] == ["a_roll", "b_roll", "b_roll", "a_roll"]
    talk, over, silent, outro = shots
    assert talk.audio.dialogue_text == "Wait. How is this pillar not touching the floor?!"
    assert talk.on_screen_text == "A 500-YEAR-OLD MYSTERY"
    assert talk.provider_plan.parameters["refs"] == [PILLAR]
    assert "Outfit: an ivory Kalamkari kurta" in talk.provider_plan.parameters["still_prompt"]
    assert over.audio.voiceover and over.audio.dialogue_text == "No strings. No tricks."
    assert over.duration_sec == 6
    assert silent.audio.dialogue_text is None
    assert outro.audio.dialogue_text == "Would you trust it? Follow for the next trip."
    quote = wf.stage_quote(pid, TENANT)
    assert quote.items == len(shots) + 3  # stills + voice for both talks and the voice-over

    _approve(wf, pid)
    m = rt.productions.get(pid, TENANT)
    assert stage_state(m.find_shot(over.id), "voice").get("done")
    assert stage_state(m.find_shot(silent.id), "voice") == {}


def test_shot_references_upload_once_and_feed_the_still(monkeypatch) -> None:
    rt, fx, wf = _engine()
    higgs = FakeHiggsfield()
    uploads: list[tuple[str, bytes]] = []

    def upload_media(tenant_id, *, filename, data, content_type):
        uploads.append((filename, data))
        return "media_pillar"

    higgs.upload_media = upload_media  # type: ignore[attr-defined]
    fx.providers.register(higgs)
    monkeypatch.setattr(external, "store_result", _fake_store(rt))
    m = _create(wf, **_brief(_reference(rt)))
    wf.start(m.production_id, TENANT)
    _approve(wf, m.production_id)
    assert uploads == [("pillar.png", b"png-bytes")]
    stills = {r.shot_id: r for r in higgs.invocations if r.capability == C.IMAGE_GENERATION}
    m = rt.productions.get(m.production_id, TENANT)
    talk, over, silent, _ = m.iter_shots()
    for shot in (talk, over):
        assert stills[shot.id].parameters["medias"] == [
            {"value": "media_pillar", "role": "image_references"}
        ]
        assert stage_state(shot, "still")["context"] == [PILLAR]
    assert "medias" not in stills[silent.id].parameters
    voiced = {r.shot_id for r in higgs.invocations if r.capability == C.VOICE_TTS}
    assert over.id in voiced and silent.id not in voiced


def test_create_rejects_unapproved_or_unknown_references_and_long_lines() -> None:
    rt, _, wf = _engine()
    with pytest.raises(InvalidProductionInputError, match="not approved"):
        _create(wf, **_brief(_reference(rt, approved=False)))
    with pytest.raises(InvalidProductionInputError, match="asset not found"):
        _create(wf, **_brief("asset_missing0000000"))
    with pytest.raises(InvalidProductionInputError, match="unknown references"):
        _create(wf, **_brief(_reference(rt), refs=["ref_nope"]))
    with pytest.raises(InvalidProductionInputError, match="line 4"):
        _create(wf, **_brief(_reference(rt), text=" ".join(["word"] * 40)))
    req = CreateProductionRequest(
        topic=TOPIC, mode=ProductionMode.PREMIUM, **_brief(_reference(rt))
    )
    with pytest.raises(InvalidProductionInputError, match="not fully generative"):
        wf.create_production(req, TENANT)


def test_failed_clip_returns_to_the_gate_and_keeps_finished_work(monkeypatch) -> None:
    rt, fx, wf = _engine()
    higgs = FakeHiggsfield()
    real_invoke = higgs.invoke
    fail = {"b_roll_clip": True}

    def flaky(request: ProviderRequest) -> ProviderResponse:
        if request.model == "kling3_0" and fail["b_roll_clip"]:
            fail["b_roll_clip"] = False
            raise ProviderError("higgsfield: quote returned no credit amount")
        return real_invoke(request)

    higgs.invoke = flaky  # type: ignore[method-assign]
    fx.providers.register(higgs)
    monkeypatch.setattr(external, "store_result", _fake_store(rt))
    m = _create(wf)
    pid = m.production_id
    wf.start(pid, TENANT)
    _approve(wf, pid)  # preview
    _approve(wf, pid)  # pilot: the A-roll clip works, the B-roll clip fails
    m = rt.productions.get(pid, TENANT)
    assert m.state == S.AWAITING_APPROVAL and m.approval_stage == ApprovalStage.PREVIEW
    event = rt.productions.events(pid, TENANT)[-1]
    assert event.event_type == "stage_failed" and "Approve again to retry" in event.message
    a_roll, b_roll = pilot_shots(m, m_rules(wf, m))
    assert stage_state(a_roll, "clip").get("done") and not stage_state(b_roll, "clip").get("done")
    assert wf.stage_quote(pid, TENANT).items == 1

    _approve(wf, pid)  # retry: only the missing clip runs
    m = rt.productions.get(pid, TENANT)
    assert m.approval_stage == ApprovalStage.PILOT
    clips = [r for r in higgs.invocations if r.capability == C.IMAGE_TO_VIDEO]
    assert [r.model for r in clips] == ["wan2_7", "kling3_0"]
