"""External generations: media produced outside the engine by an operator (Phase 2 step
one: Higgsfield through MCP), kept under the same money and rights rules as provider
calls inside the engine.

Flow: ``generation_pack`` -> ``reserve_external`` (budget first, fails closed) -> the
operator generates -> ``complete_external`` (allowlisted download, asset + provenance,
manifest binding, ledger commit with credits) or ``release_external`` on failure.
``request_rerender`` queues a new master version once outputs are attached.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx

from cineforge.contracts.agents import AssetCandidate
from cineforge.contracts.api import (
    ExternalGenerationComplete,
    ExternalGenerationRelease,
    ExternalGenerationRequest,
    GenerationPack,
    GenerationPackScene,
    GenerationPackShot,
    GenerationPackStill,
    RenderRequest,
)
from cineforge.contracts.common import AgentId, money, new_id
from cineforge.contracts.cost import LedgerEvent, LedgerStatus, ReservationRequest
from cineforge.contracts.jobs import JOB_RENDER_MASTER, QUEUE_MEDIA
from cineforge.contracts.manifest import (
    AssetRef,
    AssetRole,
    AuditEntry,
    ProductionManifest,
    ProviderAttempt,
    Scene,
    Shot,
)
from cineforge.contracts.media import (
    AssetKind,
    AssetOrigin,
    AssetRecord,
    LicenseInfo,
    RightsStatus,
    storage_key,
)
from cineforge.contracts.providers import PriceUnit
from cineforge.contracts.repositories import ConcurrentUpdateError
from cineforge.contracts.workflow import ProductionState
from cineforge.media.download import Downloaded, DownloadError, Resolver, download, resolve_host
from cineforge.media.ingest import candidates_by_id, latest_selection, resolve_image_url
from cineforge.media.render import RenderError, probe, probe_summary
from cineforge.providers import higgsfield
from cineforge.providers.http import build_http_client
from cineforge.runtime import Runtime

log = logging.getLogger(__name__)

S = ProductionState
EXTERNAL_STATES = frozenset({S.AWAITING_APPROVAL, S.PAUSED_BUDGET, S.NEEDS_REVIEW, S.READY})
STILL_ROLES = (AssetRole.SOURCE, AssetRole.REFERENCE, AssetRole.KEYFRAME)
AI_LABEL = "AI-generated"
MAX_PROMPT_CHARS = 1000
SAVE_RETRIES = 3
VIA = "mcp-cursor"

RESULT_HOSTS: dict[str, tuple[str, ...]] = {higgsfield.NAME: higgsfield.RESULT_HOSTS}
MAX_RESULT_BYTES: dict[str, int] = {higgsfield.NAME: higgsfield.MAX_RESULT_BYTES}
_ACCEPTED_TYPES: dict[AssetKind, tuple[str, ...]] = {
    AssetKind.VIDEO: ("video/", "application/octet-stream", "binary/octet-stream"),
    AssetKind.AUDIO: ("audio/", "application/octet-stream", "binary/octet-stream"),
    AssetKind.IMAGE: ("image/", "application/octet-stream", "binary/octet-stream"),
}
_SUFFIX_TYPES = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}
_EXT = {v: k for k, v in reversed(_SUFFIX_TYPES.items())} | {
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/mp3": ".mp3",
}
_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]+")


class ExternalGenerationError(ValueError):
    """Bad request for this production/ledger state (HTTP 422)."""


class PaidProvidersDisabledError(PermissionError):
    """ALLOW_PAID_PROVIDERS is false: no paid spend may be reserved (HTTP 403)."""


class CreditCapExceededError(RuntimeError):
    """The provider's credits in this production would exceed the operator's cap (409)."""

    def __init__(self, provider: str, used: Decimal, quoted: Decimal, cap: Decimal) -> None:
        super().__init__(f"{provider}: {used} credits used/reserved + {quoted} quoted > cap {cap}")
        self.used, self.quoted, self.cap = used, quoted, cap


class ExternalStateError(RuntimeError):
    """Production is in a state where this action is not allowed (HTTP 409)."""


class SourceRightsError(RuntimeError):
    """The source still of a generated output is not rights-approved (HTTP 409)."""


# ---------------------------------------------------------------------------- helpers
def _check_state(manifest: ProductionManifest, allowed: frozenset[ProductionState]) -> None:
    if manifest.state not in allowed:
        names = ", ".join(sorted(s.value for s in allowed))
        raise ExternalStateError(
            f"{manifest.production_id} is {manifest.state.value}; allowed: {names}"
        )


def _scene_and_shot(
    manifest: ProductionManifest, scene_id: str | None, shot_id: str | None
) -> tuple[Scene, Shot | None]:
    scene = manifest.find_scene(scene_id) if scene_id else None
    if scene is None:
        raise ExternalGenerationError(f"scene {scene_id!r} not found")
    if shot_id is None:
        return scene, None
    shot = next((s for s in scene.shots if s.id == shot_id), None)
    if shot is None:
        raise ExternalGenerationError(f"shot {shot_id!r} not found in {scene.id}")
    return scene, shot


def _audit(manifest: ProductionManifest, actor: str, action: str, details: dict) -> None:
    manifest.audit.append(AuditEntry(actor=actor, action=action, details=details))


def _save(
    rt: Runtime, manifest: ProductionManifest, mutate: Callable[[ProductionManifest], None]
) -> ProductionManifest:
    """Apply ``mutate`` to a fresh copy and save, retrying optimistic-lock conflicts."""
    for attempt in range(1, SAVE_RETRIES + 1):
        fresh = rt.productions.get(manifest.production_id, manifest.tenant_id) or manifest
        mutate(fresh)
        try:
            return rt.productions.save(fresh)
        except ConcurrentUpdateError:
            if attempt == SAVE_RETRIES:
                raise
    raise AssertionError("unreachable")  # pragma: no cover


def _owned_event(rt: Runtime, manifest: ProductionManifest, event_id: str) -> LedgerEvent:
    for event in rt.budget.ledger(manifest.production_id):
        if event.event_id == event_id and event.tenant_id == manifest.tenant_id:
            return event
    raise ExternalGenerationError(f"ledger event {event_id!r} not found for this production")


def credits_in_use(rt: Runtime, production_id: str, provider: str) -> Decimal:
    """Credits reserved, spent or burned by failed calls for ``provider``."""
    total = Decimal(0)
    for e in rt.budget.ledger(production_id):
        if e.provider != provider or e.usage_unit != PriceUnit.CREDIT:
            continue
        if e.status == LedgerStatus.RESERVED:
            total += e.usage_units
        elif e.status in (LedgerStatus.COMMITTED, LedgerStatus.FAILED):
            total += e.credits_used if e.credits_used is not None else e.usage_units
    return total


def compile_prompt(shot: Shot) -> str:
    if shot.provider_plan.prompt:
        return shot.provider_plan.prompt[:MAX_PROMPT_CHARS]
    v = shot.visual
    parts = [shot.description.strip().rstrip(".")]
    parts.append(f"Camera: {v.camera_motion.replace('_', ' ')}, {v.shot_type.replace('_', ' ')}")
    if v.lighting:
        parts.append(f"Lighting: {v.lighting}")
    if v.atmosphere:
        parts.append(f"Atmosphere: {v.atmosphere}")
    if v.color_grade:
        parts.append(f"Look: {v.color_grade}")
    parts.append("Photorealistic, subtle natural motion, no text, no watermark")
    return ". ".join(p for p in parts if p)[:MAX_PROMPT_CHARS]


def _real_asset(
    rt: Runtime, assets: dict[str, AssetRecord], asset_id: str, kind: AssetKind
) -> AssetRecord | None:
    asset = assets.get(asset_id)
    if asset is None or asset.kind != kind or asset.origin != AssetOrigin.GENERATED:
        return None
    provider = str((asset.generation or {}).get("provider") or "")
    if provider.startswith("mock") or not rt.storage.exists(asset.storage_key):
        return None
    return asset


def _still_for(
    shot: Shot, candidates: dict[str, AssetCandidate]
) -> tuple[AssetCandidate, float] | None:
    for ref in shot.assets:
        if ref.role in STILL_ROLES and ref.asset_id in candidates:
            candidate = candidates[ref.asset_id]
            return candidate, candidate.score
    return None


# ---------------------------------------------------------------------- generation pack
def generation_pack(
    rt: Runtime, manifest: ProductionManifest, *, client: httpx.Client | None = None
) -> GenerationPack:
    candidates = candidates_by_id(latest_selection(rt, manifest))
    assets = {
        a.id: a for a in rt.assets.list_for_production(manifest.production_id, manifest.tenant_id)
    }
    ingested = {
        a.metadata.get("candidate_id"): a for a in assets.values() if a.kind == AssetKind.IMAGE
    }
    resolved: dict[str, str | None] = {}
    http = client
    shots: list[GenerationPackShot] = []
    scenes: list[GenerationPackScene] = []
    try:
        for scene in sorted(manifest.scenes, key=lambda s: s.order):
            narration_id = None
            for shot in scene.shots:
                for ref in shot.assets:
                    if ref.role == AssetRole.AUDIO and _real_asset(
                        rt, assets, ref.asset_id, AssetKind.AUDIO
                    ):
                        narration_id = ref.asset_id
            scenes.append(
                GenerationPackScene(
                    scene_id=scene.id,
                    order=scene.order,
                    duration_sec=scene.duration_sec,
                    narration=scene.narration,
                    narration_asset_id=narration_id,
                )
            )
            for shot in sorted(scene.shots, key=lambda s: s.order):
                still, score = None, 0.0
                found = _still_for(shot, candidates)
                if found is not None:
                    candidate, score = found
                    decision = rt.rights_gate.evaluate(candidate.license)
                    if decision.status == RightsStatus.APPROVED:
                        cid = candidate.candidate_id
                        if cid not in resolved:
                            done = ingested.get(cid)
                            if done is not None and done.metadata.get("download_url"):
                                resolved[cid] = done.metadata["download_url"]
                            else:
                                http = http or build_http_client(rt.settings)
                                resolved[cid] = resolve_image_url(http, candidate)
                        still = GenerationPackStill(
                            candidate_id=cid,
                            provider=candidate.provider,
                            title=candidate.title,
                            image_url=resolved[cid],
                            source_url=candidate.source_url,
                            license=candidate.license,
                            rights_status=decision.status,
                        )
                generated = next(
                    (
                        ref.asset_id
                        for ref in reversed(shot.assets)
                        if ref.role == AssetRole.GENERATED
                        and _real_asset(rt, assets, ref.asset_id, AssetKind.VIDEO)
                    ),
                    None,
                )
                shots.append(
                    GenerationPackShot(
                        scene_id=scene.id,
                        scene_order=scene.order,
                        shot_id=shot.id,
                        shot_order=shot.order,
                        duration_sec=shot.duration_sec,
                        prompt=compile_prompt(shot),
                        camera_motion=shot.visual.camera_motion,
                        still=still,
                        score=score if still else 0.0,
                        generated_asset_id=generated,
                    )
                )
    finally:
        if http is not None and client is None:
            http.close()
    out = manifest.output
    return GenerationPack(
        production_id=manifest.production_id,
        state=manifest.state,
        width=out.width,
        height=out.height,
        aspect_ratio=out.aspect_ratio,
        scenes=scenes,
        shots=shots,
    )


# --------------------------------------------------------------------------- reserve
def reservation_key(manifest: ProductionManifest, req: ExternalGenerationRequest) -> str:
    target = req.shot_id or req.scene_id
    return f"{manifest.production_id}:{target}:{req.provider}:{req.model}:{req.attempt}"


def reserve_external(
    rt: Runtime, manifest: ProductionManifest, req: ExternalGenerationRequest
) -> LedgerEvent:
    _check_state(manifest, EXTERNAL_STATES)
    if not rt.settings.allow_paid_providers:
        raise PaidProvidersDisabledError(
            "ALLOW_PAID_PROVIDERS is false: external paid generations are disabled"
        )
    scene, shot = _scene_and_shot(manifest, req.scene_id, req.shot_id)
    kind = higgsfield.OUTPUT_KINDS.get(req.capability)
    if kind is None:
        raise ExternalGenerationError(f"capability {req.capability.value} is not supported")
    if kind != AssetKind.AUDIO and shot is None:
        raise ExternalGenerationError("visual generations need a shot_id")
    if req.provider not in RESULT_HOSTS:
        raise ExternalGenerationError(f"no result host allowlist for provider {req.provider!r}")
    key = reservation_key(manifest, req)
    for event in rt.budget.ledger(manifest.production_id):
        if event.idempotency_key == key:
            return event
    entry = rt.price_catalog.get(req.provider, req.model, PriceUnit.CREDIT)
    if req.credit_cap is not None:
        used = credits_in_use(rt, manifest.production_id, req.provider)
        if used + req.quoted_credits > req.credit_cap:
            raise CreditCapExceededError(req.provider, used, req.quoted_credits, req.credit_cap)
    agent = AgentId.AUDIO_PERFORMANCE if kind == AssetKind.AUDIO else AgentId.VISUAL_PRODUCTION
    event = rt.budget.reserve(
        ReservationRequest(
            tenant_id=manifest.tenant_id,
            production_id=manifest.production_id,
            scene_id=scene.id,
            shot_id=shot.id if shot else None,
            agent_id=agent,
            provider=req.provider,
            model=req.model,
            capability=req.capability,
            usage_units=req.quoted_credits,
            usage_unit=PriceUnit.CREDIT,
            unit_price_version=entry.version,
            estimated_cost=money(req.quoted_credits * entry.unit_price),
            attempt=req.attempt,
            retry_reason="operator retry" if req.attempt > 1 else None,
            idempotency_key=key,
        )
    )

    def mutate(m: ProductionManifest) -> None:
        _audit(
            m,
            req.requested_by,
            "external_generation_reserved",
            {
                "ledger_event_id": event.event_id,
                "provider": req.provider,
                "model": req.model,
                "scene_id": scene.id,
                "shot_id": shot.id if shot else None,
                "quoted_credits": str(req.quoted_credits),
                "reserved_cost": str(event.reserved_cost),
            },
        )

    _save(rt, manifest, mutate)
    return event


# -------------------------------------------------------------------------- complete
def _content_type(fetched: Downloaded, kind: AssetKind) -> str:
    if fetched.content_type.split("/", 1)[0] == kind.value:
        return fetched.content_type
    suffix = Path(fetched.final_url.split("?", 1)[0]).suffix.lower()
    guessed = _SUFFIX_TYPES.get(suffix)
    if guessed is None or guessed.split("/", 1)[0] != kind.value:
        raise ExternalGenerationError(
            f"result is {fetched.content_type!r}, expected {kind.value} output"
        )
    return guessed


def _derived_from(
    rt: Runtime, manifest: ProductionManifest, candidate_id: str | None
) -> dict | None:
    if not candidate_id:
        return None
    candidate = candidates_by_id(latest_selection(rt, manifest)).get(candidate_id)
    if candidate is None:
        raise ExternalGenerationError(f"source candidate {candidate_id!r} not found")
    decision = rt.rights_gate.evaluate(candidate.license)
    if decision.status != RightsStatus.APPROVED:
        raise SourceRightsError(
            f"source {candidate_id} is {decision.status.value}: {'; '.join(decision.reasons)}"
        )
    lic = candidate.license
    return {
        "candidate_id": candidate.candidate_id,
        "provider": candidate.provider,
        "title": candidate.title,
        "source_url": candidate.source_url,
        "license_type": lic.license_type if lic else None,
        "license_url": lic.license_url if lic else None,
        "author": lic.author if lic else None,
        "attribution": lic.attribution_text if lic else None,
    }


def _media_info(data: bytes, ext: str) -> dict:
    try:
        with TemporaryDirectory(prefix="cineforge-probe-") as tmp:
            path = Path(tmp) / f"result{ext}"
            path.write_bytes(data)
            return probe_summary(probe(path))
    except (RenderError, OSError, ValueError) as exc:
        log.warning("could not probe external result: %s", exc)
        return {}


def _find_completed_asset(
    rt: Runtime, manifest: ProductionManifest, event_id: str
) -> AssetRecord | None:
    for asset in rt.assets.list_for_production(manifest.production_id, manifest.tenant_id):
        if asset.metadata.get("ledger_event_id") == event_id:
            return asset
    return None


def complete_external(
    rt: Runtime,
    manifest: ProductionManifest,
    event_id: str,
    req: ExternalGenerationComplete,
    *,
    client: httpx.Client | None = None,
    resolver: Resolver | None = None,
) -> tuple[LedgerEvent, AssetRecord]:
    _check_state(manifest, EXTERNAL_STATES)
    event = _owned_event(rt, manifest, event_id)
    if event.status == LedgerStatus.COMMITTED:
        done = _find_completed_asset(rt, manifest, event_id)
        if done is not None:
            return event, done
    if event.status != LedgerStatus.RESERVED:
        raise ExternalGenerationError(f"ledger event {event_id} is {event.status.value}")
    kind = higgsfield.OUTPUT_KINDS[event.capability]
    scene, shot = _scene_and_shot(manifest, event.scene_id, event.shot_id)
    price = rt.price_catalog.get(event.provider, event.model, PriceUnit.CREDIT).unit_price
    actual = money(req.credits_used * price)
    try:
        derived = _derived_from(rt, manifest, req.source_candidate_id)
    except SourceRightsError:
        rt.budget.release(
            event_id, reason="source still not rights-approved", failed=True, actual_cost=actual
        )
        raise
    http = client or build_http_client(rt.settings)
    try:
        fetched = download(
            http,
            req.result_url,
            allowed_types=_ACCEPTED_TYPES[kind],
            max_bytes=MAX_RESULT_BYTES[event.provider],
            allowed_hosts=RESULT_HOSTS[event.provider],
            resolver=resolver or resolve_host,
        )
    except DownloadError as exc:
        raise ExternalGenerationError(f"result download refused: {exc}") from None
    finally:
        if client is None:
            http.close()
    content_type = _content_type(fetched, kind)
    ext = _EXT.get(content_type, ".bin")
    info = _media_info(fetched.data, ext) if kind != AssetKind.IMAGE else {}
    name = _UNSAFE.sub("_", f"{event.provider}_{req.provider_request_id}")[:120]
    key = storage_key(manifest.tenant_id, manifest.production_id, kind, f"{name}{ext}")
    stored = rt.storage.put_bytes(key, fetched.data, content_type)
    license = LicenseInfo(
        license_type="generated",
        commercial_use_allowed=True,
        modifications_allowed=True,
        attribution_text=(derived or {}).get("attribution"),
        source_provider=event.provider,
    )
    record = rt.assets.add(
        AssetRecord(
            tenant_id=manifest.tenant_id,
            production_id=manifest.production_id,
            kind=kind,
            origin=AssetOrigin.GENERATED,
            storage_backend=stored.backend,
            storage_key=stored.key,
            uri=stored.uri,
            content_type=content_type,
            size_bytes=stored.size_bytes,
            sha256=stored.sha256,
            width=info.get("width"),
            height=info.get("height"),
            duration_sec=info.get("duration_sec") or None,
            source_provider=event.provider,
            license=license,
            rights=rt.rights_gate.evaluate(license),
            generation={
                "provider": event.provider,
                "model": event.model,
                "job_id": req.provider_request_id,
                "prompt": req.prompt,
                "via": VIA,
                "parameters": req.parameters,
                "credits_used": str(req.credits_used),
            },
            usage_cost=actual,
            metadata={
                "ledger_event_id": event_id,
                "derived_from": derived,
                "result_host": fetched.final_url.split("/", 3)[2],
                "probe": info,
            },
        )
    )
    committed = rt.budget.commit(
        event_id,
        actual_cost=actual,
        usage_units=req.credits_used,
        provider_request_id=req.provider_request_id,
        credits_used=req.credits_used,
    )

    def mutate(m: ProductionManifest) -> None:
        sc, sh = _scene_and_shot(m, scene.id, shot.id if shot else None)
        target = sh if sh is not None else sorted(sc.shots, key=lambda s: s.order)[0]
        role = AssetRole.AUDIO if kind == AssetKind.AUDIO else AssetRole.GENERATED
        target.assets.append(AssetRef(asset_id=record.id, role=role, uri=record.uri))
        if kind != AssetKind.AUDIO:
            target.disclosure.synthetic_media = True
            target.disclosure.label_text = target.disclosure.label_text or AI_LABEL
            target.artifact_hash = record.sha256
        target.attempts.append(
            ProviderAttempt(
                attempt=event.attempt,
                provider=event.provider,
                model=event.model,
                status="succeeded",
                provider_request_id=req.provider_request_id,
                ledger_event_id=event_id,
                cost=actual,
                output_asset_id=record.id,
            )
        )
        target.actual_cost = money(target.actual_cost + actual)
        sc.actual_cost = money(sc.actual_cost + actual)
        _audit(
            m,
            "operator",
            "external_generation_completed",
            {
                "ledger_event_id": event_id,
                "asset_id": record.id,
                "provider": event.provider,
                "model": event.model,
                "job_id": req.provider_request_id,
                "credits_used": str(req.credits_used),
                "actual_cost": str(actual),
                "derived_from": (derived or {}).get("candidate_id"),
            },
        )

    _save(rt, manifest, mutate)
    return committed, record


# --------------------------------------------------------------------------- release
def release_external(
    rt: Runtime, manifest: ProductionManifest, event_id: str, req: ExternalGenerationRelease
) -> LedgerEvent:
    event = _owned_event(rt, manifest, event_id)
    if event.status != LedgerStatus.RESERVED:
        raise ExternalGenerationError(f"ledger event {event_id} is {event.status.value}")
    price = rt.price_catalog.get(event.provider, event.model, PriceUnit.CREDIT).unit_price
    burned = money(req.credits_used * price)
    released = rt.budget.release(event_id, reason=req.reason, failed=req.failed, actual_cost=burned)

    def mutate(m: ProductionManifest) -> None:
        if event.shot_id:
            shot = m.find_shot(event.shot_id)
            if shot is not None:
                shot.attempts.append(
                    ProviderAttempt(
                        attempt=event.attempt,
                        provider=event.provider,
                        model=event.model,
                        status="failed",
                        ledger_event_id=event_id,
                        cost=burned,
                        error=req.reason[:500],
                    )
                )
        _audit(
            m,
            "operator",
            "external_generation_released",
            {"ledger_event_id": event_id, "reason": req.reason, "failed": req.failed},
        )

    _save(rt, manifest, mutate)
    return released


# -------------------------------------------------------------------------- re-render
def request_rerender(rt: Runtime, manifest: ProductionManifest, req: RenderRequest) -> str:
    _check_state(manifest, frozenset({S.READY}))
    job_id = f"{manifest.production_id}:rerender:{new_id('job')}"

    def mutate(m: ProductionManifest) -> None:
        _audit(
            m,
            req.requested_by,
            "rerender_requested",
            {"job_id": job_id, "reason": req.reason, "previous_asset_id": m.master_render_asset_id},
        )

    _save(rt, manifest, mutate)
    rt.queue.enqueue(
        QUEUE_MEDIA,
        JOB_RENDER_MASTER,
        {
            "production_id": manifest.production_id,
            "tenant_id": manifest.tenant_id,
            "idempotency_key": job_id,
            "force": True,
            "requested_by": req.requested_by,
        },
        job_id=job_id,
    )
    return job_id
