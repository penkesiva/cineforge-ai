"""Media worker jobs (queue ``cineforge-media``). Keyword-only and idempotent."""

from __future__ import annotations

import logging
import tempfile
from contextlib import suppress
from pathlib import Path

from cineforge.contracts.agents import AgentRun, AgentRunStatus, MasterRender
from cineforge.contracts.common import AgentId, money, new_id
from cineforge.contracts.jobs import JOB_ADVANCE_PRODUCTION, QUEUE_AGENTS
from cineforge.contracts.manifest import AssetRole, AuditEntry, ProductionManifest
from cineforge.contracts.media import (
    AssetKind,
    AssetOrigin,
    AssetRecord,
    LicenseInfo,
    storage_key,
)
from cineforge.contracts.repositories import ConcurrentUpdateError, NotFoundError
from cineforge.contracts.review import RetryScope, ReviewFinding, ReviewGate, Severity
from cineforge.contracts.workflow import ProductionState
from cineforge.media.edit import RENDERER, EditPlan, build_edit_plan, render_master_edit
from cineforge.media.ingest import candidates_by_id, ingest_still, latest_selection
from cineforge.media.render import (
    RenderError,
    ffmpeg_version,
    probe,
    probe_summary,
    validate_master,
)
from cineforge.providers.http import build_http_client
from cineforge.runtime import Runtime, get_runtime

log = logging.getLogger(__name__)

SAVE_RETRIES = 3
STILL_ROLES = (AssetRole.SOURCE, AssetRole.REFERENCE, AssetRole.KEYFRAME)


def render_run_key(production_id: str) -> str:
    return f"{production_id}:{ProductionState.ASSEMBLING.value}:{AgentId.EDITOR_QC.value}:render:1"


def advance_job_id(production_id: str) -> str:
    return f"{production_id}:{ProductionState.ASSEMBLING.value}:rendered"


def _enqueue_advance(rt: Runtime, production_id: str, tenant_id: str) -> None:
    job_id = advance_job_id(production_id)
    rt.queue.enqueue(
        QUEUE_AGENTS,
        JOB_ADVANCE_PRODUCTION,
        {"production_id": production_id, "tenant_id": tenant_id, "idempotency_key": job_id},
        job_id=job_id,
    )


def _attach_master(
    rt: Runtime,
    production_id: str,
    tenant_id: str,
    master: MasterRender,
    findings: list,
    *,
    action: str = "master_rendered",
    extra: dict | None = None,
) -> None:
    """Re-read the manifest right before saving; retry on optimistic-lock conflicts."""
    for attempt in range(1, SAVE_RETRIES + 1):
        manifest = rt.productions.get(production_id, tenant_id)
        if manifest is None:
            raise NotFoundError(f"production {production_id} not found")
        if manifest.master_render_asset_id == master.asset_id:
            return
        manifest.master_render_asset_id = master.asset_id
        manifest.review_findings.extend(findings)
        manifest.audit.append(
            AuditEntry(
                actor=AgentId.EDITOR_QC.value,
                action=action,
                details={
                    "asset_id": master.asset_id,
                    "uri": master.uri,
                    "duration_sec": master.duration_sec,
                    "renderer": RENDERER,
                    **(extra or {}),
                },
            )
        )
        try:
            rt.productions.save(manifest)
            return
        except ConcurrentUpdateError:
            if attempt == SAVE_RETRIES:
                raise
            log.info("manifest %s changed concurrently; retrying save", production_id)


def _local_path(rt: Runtime, asset: AssetRecord) -> Path | None:
    if asset.storage_backend != rt.storage.name:
        return None
    return rt.storage.local_path(asset.storage_key)


def _ingest_stills(rt: Runtime, manifest: ProductionManifest) -> dict[str, AssetRecord]:
    """Ingest every A3 candidate a shot points at; failures fall back to slates."""
    candidates = candidates_by_id(latest_selection(rt, manifest))
    wanted = dict.fromkeys(
        ref.asset_id
        for scene in manifest.scenes
        for shot in scene.shots
        for ref in shot.assets
        if ref.role in STILL_ROLES and ref.asset_id in candidates
    )
    stills: dict[str, AssetRecord] = {}
    if not wanted:
        return stills
    with build_http_client(rt.settings) as client:
        for candidate_id in wanted:
            candidate = candidates[candidate_id]
            try:
                record = ingest_still(rt, manifest, candidate, client=client)
            except Exception:
                log.exception("ingest of %s failed", candidate.candidate_id)
                continue
            if record is not None:
                stills[candidate.candidate_id] = record
    return stills


def edit_plan_for(rt: Runtime, manifest: ProductionManifest) -> EditPlan:
    assets = {
        a.id: a for a in rt.assets.list_for_production(manifest.production_id, manifest.tenant_id)
    }
    return build_edit_plan(
        manifest,
        assets,
        stills=_ingest_stills(rt, manifest),
        local_path=lambda a: _local_path(rt, a),
    )


def _label_finding() -> ReviewFinding:
    return ReviewFinding(
        gate=ReviewGate.MASTER,
        severity=Severity.MAJOR,
        message="AI disclosure labels were not burned in (drawtext or font missing)",
        evidence=["synthetic shots present; text overlays disabled"],
        recommended_fix="install a drawtext-enabled ffmpeg and DejaVu fonts, then re-render",
        retry_scope=RetryScope.PRODUCTION,
    )


def _render_and_register(
    rt: Runtime, manifest: ProductionManifest, workdir: Path
) -> tuple[MasterRender, list]:
    production_id, tenant_id = manifest.production_id, manifest.tenant_id
    plan = edit_plan_for(rt, manifest)
    out, text = render_master_edit(plan, manifest.output, workdir / "master.mp4")
    info = probe(out)
    findings = validate_master(info, manifest.output, plan.total_sec)
    if not text and any(s.label for s in plan.shots):
        findings.append(_label_finding())
    blocking = [f for f in findings if f.blocking]
    if blocking:
        raise RenderError(
            "master failed technical QC: "
            + "; ".join(f"{f.message} ({f.evidence[0]})" for f in blocking)
        )
    summary = probe_summary(info)

    version = (
        sum(
            1
            for a in rt.assets.list_for_production(production_id, tenant_id)
            if a.kind == AssetKind.RENDER
        )
        + 1
    )
    key = storage_key(tenant_id, production_id, AssetKind.RENDER, f"master_v{version}.mp4")
    stored = rt.storage.put_file(key, out, "video/mp4")
    license_info = LicenseInfo(
        license_type="rendered",
        commercial_use_allowed=True,
        modifications_allowed=True,
        source_provider="cineforge-media-worker",
    )
    record = AssetRecord(
        tenant_id=tenant_id,
        production_id=production_id,
        kind=AssetKind.RENDER,
        origin=AssetOrigin.RENDERED,
        storage_backend=stored.backend,
        storage_key=stored.key,
        uri=stored.uri,
        content_type=stored.content_type,
        size_bytes=stored.size_bytes,
        sha256=stored.sha256,
        width=summary["width"],
        height=summary["height"],
        duration_sec=summary["duration_sec"],
        license=license_info,
        rights=rt.rights_gate.evaluate(license_info),
        generation={
            "renderer": RENDERER,
            "ffmpeg_version": ffmpeg_version(),
            "version": version,
            "scene_ids": [s.id for s in manifest.scenes],
            "edit": plan.summary(),
            "text_overlays": text,
        },
        metadata={"probe": summary},
    )
    try:
        asset = rt.assets.add(record)
    except Exception:
        with suppress(Exception):
            rt.storage.delete(key)
        raise
    master = MasterRender(
        asset_id=asset.id,
        uri=asset.uri,
        duration_sec=summary["duration_sec"],
        width=summary["width"],
        height=summary["height"],
        fps=summary["fps"],
        codec=summary["codec"],
        audio_codec=summary["audio_codec"],
        size_bytes=asset.size_bytes,
        sha256=asset.sha256,
        probe={**summary, "end_card_sec": plan.end_card_sec},
    )
    return master, [f for f in findings if not f.blocking]


def rerender_run_key(production_id: str, idempotency_key: str) -> str:
    return f"{production_id}:rerender:{AgentId.EDITOR_QC.value}:{idempotency_key}"


def _rerender(
    rt: Runtime, manifest: ProductionManifest, idempotency_key: str, requested_by: str
) -> str:
    """Render a new master version for a READY production; no state change on failure."""
    production_id, tenant_id = manifest.production_id, manifest.tenant_id
    if manifest.state != ProductionState.READY:
        raise RenderError(f"re-render needs a READY production, not {manifest.state.value}")
    previous = manifest.master_render_asset_id
    run = rt.agent_runs.start(
        AgentRun(
            id=new_id("run"),
            production_id=production_id,
            tenant_id=tenant_id,
            agent_id=AgentId.EDITOR_QC,
            step=manifest.state,
            status=AgentRunStatus.RUNNING,
            idempotency_key=rerender_run_key(production_id, idempotency_key),
            input_summary={
                "renderer": RENDERER,
                "job_idempotency_key": idempotency_key,
                "force": True,
                "requested_by": requested_by,
                "previous_asset_id": previous,
            },
        )
    )
    if run.status == AgentRunStatus.SUCCEEDED and run.output:
        master, findings = MasterRender.model_validate(run.output), []
    else:
        try:
            with tempfile.TemporaryDirectory(prefix="cineforge-render-") as workdir:
                master, findings = _render_and_register(rt, manifest, Path(workdir))
        except Exception as exc:
            log.exception("re-render failed for %s", production_id)
            with suppress(Exception):
                rt.agent_runs.finish(run.id, status=AgentRunStatus.FAILED, error=str(exc)[:2000])
            raise
        rt.agent_runs.finish(
            run.id,
            status=AgentRunStatus.SUCCEEDED,
            output=master.model_dump(mode="json"),
            output_model="MasterRender",
            actual_cost=money(0),
        )
    _attach_master(
        rt,
        production_id,
        tenant_id,
        master,
        findings,
        action="master_rerendered",
        extra={"previous_asset_id": previous, "requested_by": requested_by},
    )
    return master.asset_id


def render_master(
    *,
    production_id: str,
    tenant_id: str,
    idempotency_key: str,
    force: bool = False,
    requested_by: str = "system",
) -> str:
    """Render, validate, store and register the master, then hand back to the orchestrator.

    Returns the master asset id. Safe to run more than once: an existing
    ``master_render_asset_id`` (or a succeeded render run) short-circuits to the
    advance hand-off without re-rendering. ``force=True`` renders a new version of a
    READY production instead (see ``_rerender``).
    """
    rt = get_runtime()
    manifest = rt.productions.get(production_id, tenant_id)
    if manifest is None:
        raise NotFoundError(f"production {production_id} not found for tenant {tenant_id}")
    if force:
        return _rerender(rt, manifest, idempotency_key, requested_by)
    if manifest.master_render_asset_id:
        _enqueue_advance(rt, production_id, tenant_id)
        return manifest.master_render_asset_id

    run = rt.agent_runs.start(
        AgentRun(
            id=new_id("run"),
            production_id=production_id,
            tenant_id=tenant_id,
            agent_id=AgentId.EDITOR_QC,
            step=ProductionState.ASSEMBLING,
            status=AgentRunStatus.RUNNING,
            idempotency_key=render_run_key(production_id),
            input_summary={
                "renderer": RENDERER,
                "job_idempotency_key": idempotency_key,
                "scene_count": len(manifest.scenes),
                "output": f"{manifest.output.width}x{manifest.output.height}@{manifest.output.fps}",
            },
        )
    )
    try:
        if run.status == AgentRunStatus.SUCCEEDED and run.output:
            # Rendered earlier but the manifest was never updated (crash in between).
            master, findings = MasterRender.model_validate(run.output), []
        else:
            with tempfile.TemporaryDirectory(prefix="cineforge-render-") as workdir:
                master, findings = _render_and_register(rt, manifest, Path(workdir))
            rt.agent_runs.finish(
                run.id,
                status=AgentRunStatus.SUCCEEDED,
                output=master.model_dump(mode="json"),
                output_model="MasterRender",
                actual_cost=money(0),
            )
        _attach_master(rt, production_id, tenant_id, master, findings)
    except Exception as exc:
        log.exception("master render failed for %s", production_id)
        with suppress(Exception):
            rt.agent_runs.finish(run.id, status=AgentRunStatus.FAILED, error=str(exc)[:2000])
        try:
            rt.productions.transition(
                production_id,
                tenant_id,
                ProductionState.FAILED,
                reason=f"master render failed: {exc}"[:500],
                payload={"job": "render_master", "error_type": type(exc).__name__},
            )
        except Exception:
            log.exception("could not mark production %s as FAILED", production_id)
        raise
    _enqueue_advance(rt, production_id, tenant_id)
    return master.asset_id
