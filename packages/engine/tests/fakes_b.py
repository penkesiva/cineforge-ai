"""Workstream B test fakes for Workstream D's contract Protocols.

BudgetService, PaidCallGuard, ProviderRegistry/Provider, CostEstimator, PriceCatalog,
StorageBackend, AssetRepository, RightsGate and a fake ``render_master`` media job.
They follow the contract docstrings closely so the orchestrator is exercised the same
way the real implementations will exercise it.
"""

from __future__ import annotations

import hashlib
import io
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, BinaryIO

import yaml
from cineforge.config import Settings
from cineforge.contracts.agents import AgentRun, AgentRunStatus, MasterRender
from cineforge.contracts.common import AgentId, ProductionMode, money, new_id, utcnow
from cineforge.contracts.cost import (
    Budget,
    BudgetExceededError,
    CostBreakdownRow,
    CostEstimate,
    CostLineItem,
    CostOverview,
    CostSummary,
    CreditBalance,
    LedgerEvent,
    LedgerStatus,
    PriceCatalogEntry,
    ReservationRequest,
    UnknownPriceError,
)
from cineforge.contracts.jobs import JOB_ADVANCE_PRODUCTION, JOB_RENDER_MASTER, QUEUE_AGENTS
from cineforge.contracts.manifest import ProductionManifest
from cineforge.contracts.media import (
    AssetKind,
    AssetOrigin,
    AssetRecord,
    LicenseInfo,
    RightsDecision,
    RightsStatus,
    StoredObject,
    storage_key,
)
from cineforge.contracts.providers import (
    PriceUnit,
    Provider,
    ProviderCapability,
    ProviderError,
    ProviderInfo,
    ProviderRequest,
    ProviderResponse,
    ProviderUsage,
    UnsupportedCapabilityError,
)
from cineforge.contracts.theme import ProductionModePolicy
from cineforge.contracts.workflow import ProductionState
from cineforge.orchestration.queue import InlineTaskQueue
from cineforge.persistence.serde import dump
from cineforge.runtime import Runtime, get_runtime, set_runtime

C = ProviderCapability


# --------------------------------------------------------------------------- pricing
class FakePriceCatalog:
    def __init__(self, entries: list[PriceCatalogEntry], version: str) -> None:
        self.version = version
        self._entries = entries

    @classmethod
    def load(cls, settings: Settings) -> FakePriceCatalog:
        version = settings.price_catalog_version.split(",")[0].strip()
        path = Path(settings.configurations_dir) / "pricing" / f"{version}.yaml"
        raw = yaml.safe_load(path.read_text())
        entries = [
            PriceCatalogEntry(
                **e,
                currency=raw.get("currency", "USD"),
                version=raw["version"],
                effective_from=raw["effective_from"],
            )
            for e in raw["entries"]
        ]
        return cls(entries, raw["version"])

    def get(self, provider: str, model: str, unit: PriceUnit) -> PriceCatalogEntry:
        for e in self._entries:
            if e.provider == provider and e.model == model and e.unit == unit:
                return e
        raise UnknownPriceError(f"no price for {provider}/{model}/{unit}")

    def entries(self) -> list[PriceCatalogEntry]:
        return list(self._entries)

    def unit_for(self, provider: str, model: str) -> PriceUnit:
        for e in self._entries:
            if e.provider == provider and e.model == model:
                return e.unit
        raise UnknownPriceError(f"no price for {provider}/{model}")


# --------------------------------------------------------------------------- providers
@dataclass
class FakeProvider:
    info: ProviderInfo
    catalog: FakePriceCatalog
    # shot_id (or "*") -> number of failures to raise before succeeding
    fail_times: dict[str, int] = field(default_factory=dict)
    retryable: bool = True
    invocations: list[ProviderRequest] = field(default_factory=list)

    def estimate_usage(self, request: ProviderRequest) -> ProviderUsage:
        unit = self.catalog.unit_for(self.info.name, request.model)
        p = request.parameters
        if unit == PriceUnit.TOKENS_1K:
            units = Decimal(len(request.prompt or "") // 4 + int(p.get("max_tokens", 500))) / 1000
        elif unit in (PriceUnit.VIDEO_SECOND, PriceUnit.AUDIO_SECOND):
            units = Decimal(str(p.get("duration_sec", 5)))
        elif unit == PriceUnit.CHARACTERS_1K:
            units = Decimal(len(request.prompt or "")) / 1000
        else:
            units = Decimal(1)
        return ProviderUsage(units=units.quantize(Decimal("0.000001")), unit=unit)

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        self.invocations.append(request)
        for target in (request.shot_id, "*"):
            if target and self.fail_times.get(target, 0) > 0:
                self.fail_times[target] -= 1
                raise ProviderError(
                    f"{self.info.name}: simulated failure", retryable=self.retryable
                )
        digest = hashlib.sha256(request.idempotency_key.encode()).hexdigest()[:16]
        is_text = request.capability in (C.LLM_TEXT, C.WEB_RESEARCH, C.MEDIA_SEARCH)
        return ProviderResponse(
            provider=self.info.name,
            model=request.model,
            capability=request.capability,
            provider_request_id=f"req_{digest}",
            output_text="Mock notes: keep it vivid and accurate." if is_text else None,
            output_asset_id=None if is_text else f"asset_gen{digest}",
            usage=self.estimate_usage(request),
        )


_PROVIDERS: tuple[tuple[str, list[ProviderCapability], list[str]], ...] = (
    ("mock-llm", [C.LLM_TEXT], ["mock-llm-standard", "mock-llm-premium"]),
    ("mock-research", [C.WEB_RESEARCH], ["mock-search-v1"]),
    ("mock-media-search", [C.MEDIA_SEARCH], ["mock-media-v1"]),
    ("mock-image", [C.IMAGE_GENERATION], ["mock-image-v1"]),
    (
        "mock-video",
        [C.IMAGE_TO_VIDEO, C.VIDEO_GENERATION],
        ["mock-video-draft", "mock-video-cinematic"],
    ),
    ("mock-voice", [C.VOICE_TTS], ["mock-tts-v1"]),
    ("mock-music", [C.MUSIC_GENERATION], ["mock-music-v1"]),
    ("mock-sfx", [C.SFX_GENERATION], ["mock-sfx-v1"]),
    ("mock-lipsync", [C.LIP_SYNC], ["mock-lipsync-v1"]),
)


class FakeProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, Provider] = {}

    @classmethod
    def mock(cls, catalog: FakePriceCatalog) -> FakeProviderRegistry:
        reg = cls()
        for name, caps, models in _PROVIDERS:
            info = ProviderInfo(
                name=name,
                display_name=name.replace("-", " ").title(),
                capabilities=caps,
                models=models,
                is_mock=True,
                is_paid=False,
            )
            reg.register(FakeProvider(info=info, catalog=catalog))
        return reg

    def register(self, provider: Provider) -> None:
        self._providers[provider.info.name] = provider

    def get(self, name: str) -> Provider:
        try:
            return self._providers[name]
        except KeyError as exc:
            raise LookupError(f"provider {name} not registered") from exc

    def for_capability(self, capability: ProviderCapability) -> Provider:
        for p in self._providers.values():
            if capability in p.info.capabilities:
                return p
        raise UnsupportedCapabilityError(capability)

    def list(self) -> list[ProviderInfo]:
        return [p.info for p in self._providers.values()]


# --------------------------------------------------------------------------- budget
class FakeBudget:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.budgets: dict[tuple[str, str | None], Budget] = {}
        self.events: dict[str, LedgerEvent] = {}
        self.by_key: dict[str, str] = {}
        self.tenants: dict[str, str] = {}
        self.create_calls = 0

    def create_budget(
        self,
        *,
        tenant_id: str,
        production_id: str,
        limit: Decimal,
        currency: str = "USD",
        scene_limits: dict[str, Decimal] | None = None,
    ) -> Budget:
        with self._lock:
            self.create_calls += 1
            self.tenants[production_id] = tenant_id
            b = Budget(
                tenant_id=tenant_id,
                production_id=production_id,
                currency=currency,
                limit_amount=money(limit),
            )
            self.budgets[(production_id, None)] = b
            for sid, lim in (scene_limits or {}).items():
                self.set_limit(production_id, lim, sid)
            return b.model_copy()

    def get_budget(self, production_id: str, scene_id: str | None = None) -> Budget | None:
        b = self.budgets.get((production_id, scene_id))
        return b.model_copy() if b else None

    def set_limit(self, production_id: str, limit: Decimal, scene_id: str | None = None) -> Budget:
        with self._lock:
            b = self.budgets.get((production_id, scene_id))
            if b is None:
                b = Budget(
                    tenant_id=self.tenants[production_id],
                    production_id=production_id,
                    scene_id=scene_id,
                    limit_amount=money(limit),
                )
            floor = b.reserved_amount + b.actual_amount
            b = b.model_copy(
                update={"limit_amount": max(money(limit), floor), "updated_at": utcnow()}
            )
            self.budgets[(production_id, scene_id)] = b
            return b.model_copy()

    def _scopes(self, production_id: str, scene_id: str | None) -> list[tuple[str, str | None]]:
        scopes = [(production_id, None)]
        if scene_id and (production_id, scene_id) in self.budgets:
            scopes.append((production_id, scene_id))
        return scopes

    def reserve(self, request: ReservationRequest) -> LedgerEvent:
        with self._lock:
            if request.idempotency_key in self.by_key:
                return self.events[self.by_key[request.idempotency_key]].model_copy()
            amount = money(request.estimated_cost)
            for scope in self._scopes(request.production_id, request.scene_id):
                b = self.budgets[scope]
                if amount > b.available:
                    raise BudgetExceededError(
                        production_id=request.production_id,
                        scene_id=scope[1],
                        requested=amount,
                        available=b.available,
                    )
            for scope in self._scopes(request.production_id, request.scene_id):
                b = self.budgets[scope]
                self.budgets[scope] = b.model_copy(
                    update={"reserved_amount": b.reserved_amount + amount}
                )
            event = LedgerEvent(
                tenant_id=request.tenant_id,
                production_id=request.production_id,
                scene_id=request.scene_id,
                shot_id=request.shot_id,
                agent_id=request.agent_id,
                provider=request.provider,
                model=request.model,
                capability=request.capability,
                usage_units=request.usage_units,
                usage_unit=request.usage_unit,
                unit_price_version=request.unit_price_version,
                estimated_cost=amount,
                reserved_cost=amount,
                attempt=request.attempt,
                retry_reason=request.retry_reason,
                idempotency_key=request.idempotency_key,
            )
            self.events[event.event_id] = event
            self.by_key[request.idempotency_key] = event.event_id
            return event.model_copy()

    def _settle(self, event: LedgerEvent, actual: Decimal) -> None:
        for scope in self._scopes(event.production_id, event.scene_id):
            b = self.budgets[scope]
            self.budgets[scope] = b.model_copy(
                update={
                    "reserved_amount": max(Decimal(0), b.reserved_amount - event.reserved_cost),
                    "actual_amount": b.actual_amount + actual,
                }
            )

    def commit(
        self,
        event_id: str,
        *,
        actual_cost: Decimal,
        usage_units: Decimal | None = None,
        provider_request_id: str | None = None,
        cache_hit: bool = False,
        credits_used: Decimal | None = None,
    ) -> LedgerEvent:
        with self._lock:
            event = self.events[event_id]
            if event.status != LedgerStatus.RESERVED:
                return event.model_copy()
            self._settle(event, money(actual_cost))
            event = event.model_copy(
                update={
                    "status": LedgerStatus.COMMITTED,
                    "actual_cost": money(actual_cost),
                    "usage_units": usage_units if usage_units is not None else event.usage_units,
                    "provider_request_id": provider_request_id,
                    "cache_hit": cache_hit,
                    "credits_used": credits_used,
                    "updated_at": utcnow(),
                }
            )
            self.events[event_id] = event
            return event.model_copy()

    def release(
        self, event_id: str, *, reason: str, failed: bool = False, actual_cost: Decimal = Decimal(0)
    ) -> LedgerEvent:
        with self._lock:
            event = self.events[event_id]
            if event.status != LedgerStatus.RESERVED:
                return event.model_copy()
            self._settle(event, money(actual_cost))
            event = event.model_copy(
                update={
                    "status": LedgerStatus.FAILED if failed else LedgerStatus.RELEASED,
                    "actual_cost": money(actual_cost),
                    "retry_reason": event.retry_reason or reason,
                    "updated_at": utcnow(),
                }
            )
            self.events[event_id] = event
            return event.model_copy()

    def ledger(self, production_id: str) -> list[LedgerEvent]:
        return [e.model_copy() for e in self.events.values() if e.production_id == production_id]

    def summary(self, production_id: str, *, estimate: CostEstimate | None = None) -> CostSummary:
        b = self.budgets.get((production_id, None))
        events = self.ledger(production_id)
        by_agent: dict[str, CostBreakdownRow] = {}
        for e in events:
            row = by_agent.setdefault(
                e.agent_id.value, CostBreakdownRow(key=e.agent_id.value, label=e.agent_id.value)
            )
            row.actual += e.actual_cost
            row.event_count += 1
        limit = b.limit_amount if b else money(0)
        actual = b.actual_amount if b else money(0)
        reserved = b.reserved_amount if b else money(0)
        return CostSummary(
            production_id=production_id,
            limit=limit,
            estimated=estimate.total_estimated if estimate else money(0),
            reserved=reserved,
            actual=actual,
            remaining=max(money(0), limit - actual - reserved),
            by_agent=list(by_agent.values()),
            retry_count=sum(1 for e in events if e.attempt > 1),
            event_count=len(events),
        )

    def overview(self, tenant_id: str) -> CostOverview:
        pids = sorted({pid for pid, t in self.tenants.items() if t == tenant_id})
        totals = defaultdict(Decimal)
        for pid in pids:
            b = self.budgets[(pid, None)]
            totals["limit"] += b.limit_amount
            totals["actual"] += b.actual_amount
            totals["reserved"] += b.reserved_amount
        return CostOverview(
            tenant_id=tenant_id,
            production_count=len(pids),
            total_limit=money(totals["limit"]),
            total_actual=money(totals["actual"]),
            total_reserved=money(totals["reserved"]),
        )

    def credit_balances(self, tenant_id: str) -> list[CreditBalance]:
        return []


# --------------------------------------------------------------------------- guard
class FakeGuard:
    def __init__(self, budget: FakeBudget, catalog: FakePriceCatalog) -> None:
        self.budget = budget
        self.catalog = catalog
        self.calls: list[tuple[str, ProviderRequest, AgentId, int]] = []

    def call(
        self,
        provider: Provider,
        request: ProviderRequest,
        *,
        agent_id: AgentId,
        attempt: int = 1,
        retry_reason: str | None = None,
    ) -> tuple[ProviderResponse, LedgerEvent]:
        usage = provider.estimate_usage(request)
        entry = self.catalog.get(provider.info.name, request.model, usage.unit)
        estimated = money(entry.unit_price * usage.units)
        event = self.budget.reserve(
            ReservationRequest(
                tenant_id=request.tenant_id,
                production_id=request.production_id,
                scene_id=request.scene_id,
                shot_id=request.shot_id,
                agent_id=agent_id,
                provider=provider.info.name,
                model=request.model,
                capability=request.capability,
                usage_units=usage.units,
                usage_unit=usage.unit,
                unit_price_version=self.catalog.version,
                estimated_cost=estimated,
                attempt=attempt,
                retry_reason=retry_reason,
                idempotency_key=f"{request.idempotency_key}:{provider.info.name}:{request.model}",
            )
        )
        self.calls.append((provider.info.name, request, agent_id, attempt))
        try:
            response = provider.invoke(request)
        except ProviderError as exc:
            self.budget.release(event.event_id, reason=str(exc), failed=True)
            raise
        actual = money(entry.unit_price * response.usage.units)
        committed = self.budget.commit(
            event.event_id,
            actual_cost=actual,
            usage_units=response.usage.units,
            provider_request_id=response.provider_request_id,
        )
        return response, committed


# --------------------------------------------------------------------------- estimator
class FakeEstimator:
    def __init__(self, catalog: FakePriceCatalog, scale: Decimal | float = 1) -> None:
        self.catalog = catalog
        self.scale = Decimal(str(scale))

    def estimate(
        self, manifest: ProductionManifest, mode_policy: ProductionModePolicy
    ) -> CostEstimate:
        items: list[CostLineItem] = []
        retries = Decimal(1) + Decimal(str(mode_policy.expected_retry_rate))
        for scene in manifest.scenes:
            for shot in scene.shots:
                plan = shot.provider_plan
                entry = self.catalog.get(plan.provider, plan.model, PriceUnit.VIDEO_SECOND)
                qty = Decimal(str(shot.duration_sec))
                items.append(
                    CostLineItem(
                        key=f"{scene.id}/{shot.id}/a7_visual_production",
                        scene_id=scene.id,
                        shot_id=shot.id,
                        agent_id=AgentId.VISUAL_PRODUCTION,
                        provider=plan.provider,
                        model=plan.model,
                        capability=plan.capability or C.IMAGE_TO_VIDEO,
                        unit=PriceUnit.VIDEO_SECOND,
                        quantity=qty,
                        unit_price=entry.unit_price,
                        expected_attempts=retries,
                        estimated_cost=money(entry.unit_price * qty * retries * self.scale),
                    )
                )
        total = money(sum((i.estimated_cost for i in items), Decimal(0)))
        by_scene: dict[str, Decimal] = defaultdict(Decimal)
        for i in items:
            by_scene[i.scene_id or "production"] += i.estimated_cost
        return CostEstimate(
            production_id=manifest.production_id,
            mode=manifest.mode or ProductionMode.BALANCED,
            price_catalog_version=self.catalog.version,
            line_items=items,
            total_estimated=total,
            by_scene={k: money(v) for k, v in by_scene.items()},
            by_agent={AgentId.VISUAL_PRODUCTION.value: total},
        )


# --------------------------------------------------------------------------- media
class FakeStorage:
    name = "fake"

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    def put_bytes(self, key: str, data: bytes, content_type: str) -> StoredObject:
        self.objects[key] = (data, content_type)
        return StoredObject(
            backend=self.name,
            key=key,
            uri=f"local://{key}",
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            content_type=content_type,
        )

    def put_file(self, key: str, path: Path, content_type: str) -> StoredObject:
        return self.put_bytes(key, Path(path).read_bytes(), content_type)

    def open(self, key: str) -> BinaryIO:
        if key not in self.objects:
            raise FileNotFoundError(key)
        return io.BytesIO(self.objects[key][0])

    def exists(self, key: str) -> bool:
        return key in self.objects

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    def local_path(self, key: str) -> Path | None:
        return None


class FakeAssets:
    def __init__(self) -> None:
        self.records: dict[str, AssetRecord] = {}

    def add(self, record: AssetRecord) -> AssetRecord:
        self.records[record.id] = record
        return record.model_copy()

    def get(self, asset_id: str, tenant_id: str) -> AssetRecord | None:
        r = self.records.get(asset_id)
        return r.model_copy() if r and r.tenant_id == tenant_id else None

    def list_for_production(self, production_id: str, tenant_id: str) -> list[AssetRecord]:
        return [
            r.model_copy()
            for r in self.records.values()
            if r.production_id == production_id and r.tenant_id == tenant_id
        ]


class FakeRightsGate:
    """Fail closed: only clearly commercial-safe licenses are approved."""

    APPROVED = {"CC0", "public-domain", "commercial", "CC-BY-4.0", "CC-BY-SA-4.0"}

    def evaluate(
        self, license: LicenseInfo | None, *, intended_use: str = "commercial"
    ) -> RightsDecision:
        if license is None:
            return RightsDecision(status=RightsStatus.UNKNOWN, reasons=["no license information"])
        if intended_use == "commercial" and license.commercial_use_allowed is False:
            return RightsDecision(status=RightsStatus.BLOCKED, reasons=["non-commercial license"])
        if license.license_type in self.APPROVED:
            if license.attribution_required and not license.attribution_text:
                return RightsDecision(status=RightsStatus.PENDING, reasons=["attribution missing"])
            return RightsDecision(status=RightsStatus.APPROVED, reasons=[license.license_type])
        return RightsDecision(status=RightsStatus.UNKNOWN, reasons=["unrecognized license"])


# --------------------------------------------------------------------------- media job
def make_render_job(
    *,
    width: int | None = None,
    height: int | None = None,
    duration_sec: float | None = None,
    codec: str = "h264",
):
    """Fake ``cineforge.media.jobs.render_master``: stores a tiny fake master, records the
    MasterRender AgentRun (EDITOR_QC / ASSEMBLING), sets master_render_asset_id, then
    enqueues the next advance - the behaviour expected from Workstream D."""

    def render_master(*, production_id: str, tenant_id: str, idempotency_key: str) -> None:
        rt = get_runtime()
        m = rt.productions.get(production_id, tenant_id)
        assert m is not None
        if m.master_render_asset_id is None:
            data = b"FAKE-MP4:" + production_id.encode()
            key = storage_key(tenant_id, production_id, AssetKind.RENDER, "master.mp4")
            stored = rt.storage.put_bytes(key, data, "video/mp4")
            w, h = width or m.output.width, height or m.output.height
            dur = duration_sec if duration_sec is not None else m.output.duration_target_sec
            record = rt.assets.add(
                AssetRecord(
                    tenant_id=tenant_id,
                    production_id=production_id,
                    kind=AssetKind.RENDER,
                    origin=AssetOrigin.RENDERED,
                    storage_backend=stored.backend,
                    storage_key=stored.key,
                    uri=stored.uri,
                    content_type="video/mp4",
                    size_bytes=stored.size_bytes,
                    sha256=stored.sha256,
                    width=w,
                    height=h,
                    duration_sec=dur,
                    rights=RightsDecision(status=RightsStatus.APPROVED, reasons=["rendered"]),
                )
            )
            master = MasterRender(
                asset_id=record.id,
                uri=record.uri,
                duration_sec=dur,
                width=w,
                height=h,
                fps=m.output.fps,
                codec=codec,
                audio_codec="aac",
                size_bytes=record.size_bytes,
                sha256=record.sha256,
            )
            run = rt.agent_runs.start(
                AgentRun(
                    id=new_id("run"),
                    production_id=production_id,
                    tenant_id=tenant_id,
                    agent_id=AgentId.EDITOR_QC,
                    step=ProductionState.ASSEMBLING,
                    status=AgentRunStatus.RUNNING,
                    idempotency_key=f"{production_id}:ASSEMBLING:a9_editor_qc:render:1",
                )
            )
            rt.agent_runs.finish(
                run.id,
                status=AgentRunStatus.SUCCEEDED,
                output=dump(master),
                output_model="MasterRender",
            )
            m.master_render_asset_id = record.id
            rt.productions.save(m)
        job_id = f"{production_id}:ASSEMBLING:rendered"
        rt.queue.enqueue(
            QUEUE_AGENTS,
            JOB_ADVANCE_PRODUCTION,
            {"production_id": production_id, "tenant_id": tenant_id, "idempotency_key": job_id},
            job_id=job_id,
        )

    return render_master


fake_render_master = make_render_job()


# --------------------------------------------------------------------------- runtime
@dataclass
class FakeServices:
    catalog: FakePriceCatalog
    budget: FakeBudget
    providers: FakeProviderRegistry
    guard: FakeGuard
    estimator: FakeEstimator
    storage: FakeStorage
    assets: FakeAssets
    rights: FakeRightsGate
    queue: Any

    def provider(self, name: str) -> FakeProvider:
        return self.providers.get(name)  # type: ignore[return-value]


def make_runtime(
    *,
    estimator_scale: float = 1.0,
    render_job=None,
    queue: Any = None,
    raise_errors: bool = True,
    install: bool = True,
    **settings_overrides: Any,
) -> tuple[Runtime, FakeServices]:
    settings = Settings(
        **(
            {"persistence_backend": "memory", "queue_backend": "inline", "mock_step_delay_sec": 0}
            | settings_overrides
        )
    )
    rt = Runtime(settings)
    catalog = FakePriceCatalog.load(settings)
    budget = FakeBudget()
    providers = FakeProviderRegistry.mock(catalog)
    if queue is None:
        queue = InlineTaskQueue(
            overrides={JOB_RENDER_MASTER: render_job or fake_render_master},
            raise_errors=raise_errors,
        )
    services = FakeServices(
        catalog=catalog,
        budget=budget,
        providers=providers,
        guard=FakeGuard(budget, catalog),
        estimator=FakeEstimator(catalog, estimator_scale),
        storage=FakeStorage(),
        assets=FakeAssets(),
        rights=FakeRightsGate(),
        queue=queue,
    )
    rt.__dict__.update(
        price_catalog=catalog,
        budget=budget,
        cost_estimator=services.estimator,
        storage=services.storage,
        assets=services.assets,
        rights_gate=services.rights,
        providers=providers,
        paid_calls=services.guard,
        queue=queue,
    )
    if install:
        set_runtime(rt)
    return rt, services
