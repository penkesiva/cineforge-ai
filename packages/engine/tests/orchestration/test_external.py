from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from cineforge.config import Settings
from cineforge.contracts.agents import AgentRun, AgentRunStatus, AssetCandidate, AssetSelection
from cineforge.contracts.api import (
    ExternalGenerationComplete,
    ExternalGenerationRelease,
    ExternalGenerationRequest,
    RenderRequest,
)
from cineforge.contracts.common import AgentId
from cineforge.contracts.cost import BudgetExceededError, LedgerStatus, UnknownPriceError
from cineforge.contracts.jobs import JOB_RENDER_MASTER, QUEUE_MEDIA
from cineforge.contracts.manifest import AssetRef, AssetRole, ProductionManifest
from cineforge.contracts.media import AssetKind, AssetOrigin, LicenseInfo, RightsStatus
from cineforge.contracts.providers import ProviderCapability
from cineforge.contracts.workflow import ProductionState
from cineforge.orchestration import external
from cineforge.runtime import Runtime
from fakes_d import fake_runtime, small_manifest

PUBLIC = lambda host: ["93.184.216.34"]  # noqa: E731
CDN = "https://d8j0ntlcm91z4.cloudfront.net/user_x/hf_20261014_clip.mp4"
MP3 = "https://d8j0ntlcm91z4.cloudfront.net/user_x/hf_20261014_voice.mp3"
COMMONS_PAGE = "https://commons.wikimedia.org/wiki/File:Old_Town_Square.jpg"
FULL_URL = "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/x.jpg/1920px-x.jpg"
CLIP = b"\x00\x00\x00\x18ftypmp42" + b"0" * 64


def _candidate(cid: str, license_type: str = "CC-BY-4.0") -> AssetCandidate:
    return AssetCandidate(
        candidate_id=cid,
        provider="wikimedia-commons",
        media_type="image",
        title="Old Town Square",
        source_url=COMMONS_PAGE,
        thumbnail_url="https://upload.wikimedia.org/thumb/640px-x.jpg",
        license=LicenseInfo(
            license_type=license_type,
            attribution_text="Photo by A",
            attribution_required=True,
            source_provider="wikimedia-commons",
            source_url=COMMONS_PAGE,
        ),
        rights_status=RightsStatus.APPROVED,
        score=0.9,
    )


def _handler(request: httpx.Request) -> httpx.Response:
    host = request.url.host
    if host == "commons.wikimedia.org":
        return httpx.Response(
            200, json={"query": {"pages": [{"imageinfo": [{"thumburl": FULL_URL}]}]}}
        )
    if host == "d8j0ntlcm91z4.cloudfront.net":
        if request.url.path.endswith(".mp3"):
            mp3 = b"ID3" + b"0" * 32
            return httpx.Response(200, content=mp3, headers={"content-type": "audio/mpeg"})
        return httpx.Response(200, content=CLIP, headers={"content-type": "video/mp4"})
    if host == "evil.example":
        return httpx.Response(200, content=CLIP, headers={"content-type": "video/mp4"})
    return httpx.Response(404)


def _client() -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(_handler))


@pytest.fixture
def rt(tmp_path: Path) -> Runtime:
    return fake_runtime(
        Settings(
            persistence_backend="memory",
            queue_backend="inline",
            storage_local_root=tmp_path / "media",
            allow_paid_providers=True,
        )
    )


def _setup(
    rt: Runtime, *, state: ProductionState = ProductionState.READY, budget: str = "5"
) -> ProductionManifest:
    m = small_manifest()
    m.state = state
    m.scenes[0].shots[0].assets.append(AssetRef(asset_id="asset_cand_by", role=AssetRole.SOURCE))
    m.scenes[1].shots[0].assets.append(AssetRef(asset_id="asset_cand_nd", role=AssetRole.SOURCE))
    m.scenes[1].shots[1].assets.append(AssetRef(asset_id="asset_cand_sa", role=AssetRole.SOURCE))
    rt.productions.create(m)
    rt.budget.create_budget(
        tenant_id=m.tenant_id, production_id=m.production_id, limit=Decimal(budget)
    )
    rt.agent_runs.runs["run_a3"] = AgentRun(
        id="run_a3",
        production_id=m.production_id,
        tenant_id=m.tenant_id,
        agent_id=AgentId.MEDIA_DISCOVERY,
        step=ProductionState.RESEARCHING,
        status=AgentRunStatus.SUCCEEDED,
        idempotency_key="a3",
        output=AssetSelection(
            candidates=[
                _candidate("asset_cand_by"),
                _candidate("asset_cand_nd", "CC-BY-ND-4.0"),
                _candidate("asset_cand_sa", "CC-BY-SA-4.0"),
            ]
        ).model_dump(mode="json"),
        output_model="AssetSelection",
    )
    return rt.productions.get(m.production_id, m.tenant_id)


def _video_req(m: ProductionManifest, shot: int = 0, **kw) -> ExternalGenerationRequest:
    scene = m.scenes[0]
    data = {
        "scene_id": scene.id,
        "shot_id": scene.shots[shot].id,
        "provider": "higgsfield",
        "model": "kling2_6",
        "capability": ProviderCapability.IMAGE_TO_VIDEO,
        "quoted_credits": Decimal(5),
    }
    return ExternalGenerationRequest(**(data | kw))


def _done(**kw) -> ExternalGenerationComplete:
    data = {
        "result_url": CDN,
        "provider_request_id": "hf_job_1",
        "credits_used": Decimal(5),
        "prompt": "slow push",
        "source_candidate_id": "asset_cand_by",
        "parameters": {"duration": 5, "aspect_ratio": "9:16"},
    }
    return ExternalGenerationComplete(**(data | kw))


def _fresh(rt: Runtime, m: ProductionManifest) -> ProductionManifest:
    return rt.productions.get(m.production_id, m.tenant_id)


# --------------------------------------------------------------------------- reserve
def test_reserve_fails_closed_without_paid_flag(tmp_path: Path) -> None:
    rt = fake_runtime(Settings(persistence_backend="memory", storage_local_root=tmp_path))
    m = _setup(rt)
    with pytest.raises(external.PaidProvidersDisabledError):
        external.reserve_external(rt, m, _video_req(m))
    assert rt.budget.ledger(m.production_id) == []


def test_reserve_needs_price_state_and_targets(rt: Runtime) -> None:
    m = _setup(rt)
    with pytest.raises(UnknownPriceError):
        external.reserve_external(rt, m, _video_req(m, model="veo9"))
    with pytest.raises(external.ExternalGenerationError, match="shot_id"):
        external.reserve_external(rt, m, _video_req(m, shot_id=None))
    with pytest.raises(external.ExternalGenerationError, match="not found"):
        external.reserve_external(rt, m, _video_req(m, scene_id="scene_nope"))
    with pytest.raises(external.ExternalGenerationError, match="allowlist"):
        external.reserve_external(rt, m, _video_req(m, provider="runway"))
    m.state = ProductionState.GENERATING
    with pytest.raises(external.ExternalStateError):
        external.reserve_external(rt, m, _video_req(m))
    assert rt.budget.ledger(m.production_id) == []


def test_reserve_records_ledger_and_is_idempotent(rt: Runtime) -> None:
    m = _setup(rt)
    event = external.reserve_external(rt, m, _video_req(m))
    assert event.status == LedgerStatus.RESERVED
    assert (event.provider, event.model, event.agent_id) == (
        "higgsfield",
        "kling2_6",
        AgentId.VISUAL_PRODUCTION,
    )
    assert event.usage_units == 5 and event.reserved_cost == Decimal("0.215")
    assert external.reserve_external(rt, m, _video_req(m)).event_id == event.event_id
    assert len(rt.budget.ledger(m.production_id)) == 1
    (entry,) = [a for a in _fresh(rt, m).audit if a.action == "external_generation_reserved"]
    assert entry.details["ledger_event_id"] == event.event_id


def test_credit_cap_and_budget_return_errors(rt: Runtime) -> None:
    m = _setup(rt)
    external.reserve_external(rt, m, _video_req(m, credit_cap=Decimal(8)))
    with pytest.raises(external.CreditCapExceededError) as cap:
        external.reserve_external(rt, m, _video_req(m, shot=1, credit_cap=Decimal(8)))
    assert cap.value.used == 5 and cap.value.cap == 8

    poor = fake_runtime(rt.settings)
    pm = _setup(poor, budget="0.1")
    with pytest.raises(BudgetExceededError):
        external.reserve_external(poor, pm, _video_req(pm))


# -------------------------------------------------------------------------- complete
def test_complete_registers_asset_and_binds_shot(rt: Runtime) -> None:
    m = _setup(rt)
    event = external.reserve_external(rt, m, _video_req(m))
    committed, asset = external.complete_external(
        rt, m, event.event_id, _done(), client=_client(), resolver=PUBLIC
    )
    assert committed.status == LedgerStatus.COMMITTED
    assert committed.credits_used == 5 and committed.actual_cost == Decimal("0.215")
    assert committed.provider_request_id == "hf_job_1"

    assert asset.kind == AssetKind.VIDEO and asset.origin == AssetOrigin.GENERATED
    assert asset.storage_key.endswith("/video/higgsfield_hf_job_1.mp4")
    assert rt.storage.local_path(asset.storage_key).read_bytes() == CLIP
    assert asset.generation["via"] == "mcp-cursor" and asset.generation["job_id"] == "hf_job_1"
    assert asset.metadata["derived_from"]["attribution"] == "Photo by A"
    assert asset.license.attribution_text == "Photo by A"
    assert asset.rights.status == RightsStatus.APPROVED

    shot = _fresh(rt, m).scenes[0].shots[0]
    assert shot.assets[-1].asset_id == asset.id and shot.assets[-1].role == AssetRole.GENERATED
    assert shot.disclosure.synthetic_media and shot.disclosure.label_text == "AI-generated"
    (attempt,) = shot.attempts
    assert attempt.status == "succeeded" and attempt.output_asset_id == asset.id
    assert shot.actual_cost == Decimal("0.215")

    again, same = external.complete_external(
        rt, m, event.event_id, _done(), client=_client(), resolver=PUBLIC
    )
    assert same.id == asset.id and again.status == LedgerStatus.COMMITTED
    assert len(_fresh(rt, m).scenes[0].shots[0].attempts) == 1


def test_complete_refuses_other_hosts(rt: Runtime) -> None:
    m = _setup(rt)
    event = external.reserve_external(rt, m, _video_req(m))
    with pytest.raises(external.ExternalGenerationError, match="allowlist"):
        external.complete_external(
            rt,
            m,
            event.event_id,
            _done(result_url="https://evil.example/x.mp4"),
            client=_client(),
            resolver=PUBLIC,
        )
    (row,) = rt.budget.ledger(m.production_id)
    assert row.status == LedgerStatus.RESERVED
    assert rt.assets.list_for_production(m.production_id, m.tenant_id) == []


def test_complete_blocks_unapproved_source(rt: Runtime) -> None:
    m = _setup(rt)
    event = external.reserve_external(rt, m, _video_req(m))
    with pytest.raises(external.SourceRightsError, match="pending"):
        external.complete_external(
            rt,
            m,
            event.event_id,
            _done(source_candidate_id="asset_cand_sa"),
            client=_client(),
            resolver=PUBLIC,
        )
    (row,) = rt.budget.ledger(m.production_id)
    assert row.status == LedgerStatus.FAILED and row.actual_cost == Decimal("0.215")
    assert rt.assets.list_for_production(m.production_id, m.tenant_id) == []


def test_narration_binds_audio_without_label(rt: Runtime) -> None:
    m = _setup(rt)
    scene = m.scenes[1]
    event = external.reserve_external(
        rt,
        m,
        ExternalGenerationRequest(
            scene_id=scene.id,
            provider="higgsfield",
            model="seed_audio",
            capability=ProviderCapability.VOICE_TTS,
            quoted_credits=Decimal(1),
        ),
    )
    assert event.agent_id == AgentId.AUDIO_PERFORMANCE and event.shot_id is None
    _, asset = external.complete_external(
        rt,
        m,
        event.event_id,
        _done(
            result_url=MP3, provider_request_id="hf_v1", credits_used=1, source_candidate_id=None
        ),
        client=_client(),
        resolver=PUBLIC,
    )
    assert asset.kind == AssetKind.AUDIO and asset.storage_key.endswith(".mp3")
    first = min(_fresh(rt, m).scenes[1].shots, key=lambda s: s.order)
    assert first.assets[-1].role == AssetRole.AUDIO and first.assets[-1].asset_id == asset.id
    assert not first.disclosure.synthetic_media


def test_release_marks_failed_attempt(rt: Runtime) -> None:
    m = _setup(rt)
    event = external.reserve_external(rt, m, _video_req(m))
    released = external.release_external(
        rt, m, event.event_id, ExternalGenerationRelease(reason="nsfw filter", credits_used=0)
    )
    assert released.status == LedgerStatus.FAILED and released.actual_cost == 0
    (attempt,) = _fresh(rt, m).scenes[0].shots[0].attempts
    assert attempt.status == "failed" and attempt.error == "nsfw filter"
    with pytest.raises(external.ExternalGenerationError, match="failed"):
        external.release_external(rt, m, event.event_id, ExternalGenerationRelease(reason="again"))
    with pytest.raises(external.ExternalGenerationError, match="not found"):
        external.release_external(rt, m, "ledger_nope", ExternalGenerationRelease(reason="x"))


# --------------------------------------------------------------------------- pack
def test_generation_pack_lists_only_approved_stills(rt: Runtime) -> None:
    m = _setup(rt)
    pack = external.generation_pack(rt, m, client=_client())
    assert pack.aspect_ratio == "9:16" and pack.width == 180
    assert len(pack.shots) == sum(len(s.shots) for s in m.scenes)
    assert len(pack.scenes) == len(m.scenes)
    by_shot = {s.shot_id: s for s in pack.shots}
    first = by_shot[m.scenes[0].shots[0].id]
    assert first.still is not None and first.still.image_url == FULL_URL
    assert first.still.rights_status == RightsStatus.APPROVED and first.score == 0.9
    assert "Camera:" in first.prompt and first.generated_asset_id is None
    assert by_shot[m.scenes[1].shots[0].id].still is None
    assert by_shot[m.scenes[1].shots[1].id].still is None

    event = external.reserve_external(rt, m, _video_req(m))
    _, asset = external.complete_external(
        rt, m, event.event_id, _done(), client=_client(), resolver=PUBLIC
    )
    pack = external.generation_pack(rt, _fresh(rt, m), client=_client())
    first = next(s for s in pack.shots if s.shot_id == m.scenes[0].shots[0].id)
    assert first.generated_asset_id == asset.id


# ------------------------------------------------------------------------- rerender
def test_rerender_enqueues_forced_job(rt: Runtime) -> None:
    m = _setup(rt)
    job_id = external.request_rerender(rt, m, RenderRequest(reason="clips attached"))
    (queue, path, kwargs, jid) = rt.queue.jobs[-1]
    assert (queue, path, jid) == (QUEUE_MEDIA, JOB_RENDER_MASTER, job_id)
    assert kwargs["force"] is True and kwargs["idempotency_key"] == job_id
    assert kwargs["requested_by"] == "operator"
    assert any(a.action == "rerender_requested" for a in _fresh(rt, m).audit)

    m.state = ProductionState.AWAITING_APPROVAL
    with pytest.raises(external.ExternalStateError):
        external.request_rerender(rt, m, RenderRequest())
