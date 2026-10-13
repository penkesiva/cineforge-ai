"""Agent tests: each of the 10 agents returns a schema-valid artifact through the registry."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest
from cineforge.agents.base import LEDGER_EVENTS, PROMPT_TEMPLATES
from cineforge.agents.factory import build_agent_registry
from cineforge.agents.planning import beats_for_scenes, split_centis, target_scene_count
from cineforge.agents.prompts import PromptLibrary, PromptTemplateNotFoundError
from cineforge.agents.registry import AgentNotFoundError, DefaultAgentRegistry
from cineforge.agents.scene_director import SHOT_PROMPT_TEMPLATE_ID
from cineforge.config import Settings
from cineforge.configuration import get_theme, load_mode_policies
from cineforge.contracts.agents import (
    AGENT_DEFINITIONS,
    AgentContext,
    AgentSchemaError,
    AssetSelection,
    AudioInput,
    AudioPackage,
    ClaimStatus,
    CostPlan,
    CostPlanningInput,
    CreativeInput,
    CreativeTreatment,
    MasterRender,
    MediaDiscoveryInput,
    PlanningInput,
    ProductionPlan,
    RenderedShotRef,
    ResearchBrief,
    ResearchInput,
    ReviewInput,
    SceneDirectionInput,
    SceneGraph,
    Script,
    ScriptInput,
    ShotProductionInput,
)
from cineforge.contracts.common import AgentId, GenerationStrategy, ProductionMode, money
from cineforge.contracts.manifest import (
    BudgetSnapshot,
    CreativeBrief,
    OutputProfile,
    ProductionManifest,
    ThemeRef,
    WorkStatus,
)
from cineforge.contracts.media import RightsStatus
from cineforge.contracts.providers import ProviderCapability
from cineforge.contracts.review import ReviewGate, ReviewStatus, Severity
from fakes_b import FakeEstimator, FakeGuard, make_runtime
from pydantic import BaseModel

SETTINGS = Settings(persistence_backend="memory", queue_backend="inline")
CFG = SETTINGS.configurations_dir
TOPIC = "The night the Eiffel Tower first lit up for the 1889 World's Fair"


@dataclass
class Chain:
    plan: ProductionPlan
    treatment: CreativeTreatment
    research: ResearchBrief
    media: AssetSelection
    script: Script
    graph: SceneGraph
    ctx: AgentContext
    registry: DefaultAgentRegistry
    guard: FakeGuard
    services: object


def _manifest(mode: ProductionMode = ProductionMode.BALANCED, theme_id: str = "time-traveler"):
    theme = get_theme(CFG, theme_id)
    policy = load_mode_policies(CFG)[mode]
    manifest = ProductionManifest(
        production_id="prod_agenttest000001",
        tenant_id="tenant_demo",
        theme_profile=ThemeRef(id=theme.id, version=theme.version),
        mode=mode,
        creative_brief=CreativeBrief(topic=TOPIC, genre=theme.genres[0]),
        output=OutputProfile(duration_target_sec=45),
        budget=BudgetSnapshot(limit=policy.default_budget_usd),
    )
    return manifest, theme, policy


def _ctx(manifest, theme, policy, services, key: str) -> AgentContext:
    return AgentContext(
        production_id=manifest.production_id,
        tenant_id=manifest.tenant_id,
        manifest=manifest,
        theme=theme,
        mode_policy=policy,
        providers=services.providers,
        paid_calls=services.guard,
        idempotency_key=key,
    )


def _chain(
    mode: ProductionMode = ProductionMode.BALANCED, theme_id: str = "time-traveler"
) -> Chain:
    _, services = make_runtime(install=False)
    manifest, theme, policy = _manifest(mode, theme_id)
    services.budget.create_budget(
        tenant_id=manifest.tenant_id, production_id=manifest.production_id, limit=money(1000)
    )
    registry = build_agent_registry(SETTINGS)
    pid = manifest.production_id

    def ctx(agent: AgentId) -> AgentContext:
        return _ctx(manifest, theme, policy, services, f"{pid}:TEST:{agent.value}:production:1")

    brief = manifest.creative_brief
    plan = registry.invoke(
        AgentId.MASTER_ORCHESTRATOR,
        ctx(AgentId.MASTER_ORCHESTRATOR),
        PlanningInput(
            production_id=pid,
            brief=brief,
            mode=mode,
            budget_limit=manifest.budget.limit,
            duration_target_sec=45,
        ),
    )
    treatment = registry.invoke(
        AgentId.CREATIVE_DIRECTOR,
        ctx(AgentId.CREATIVE_DIRECTOR),
        CreativeInput(brief=brief, theme=theme),
    )
    research = registry.invoke(
        AgentId.RESEARCH,
        ctx(AgentId.RESEARCH),
        ResearchInput(brief=brief, theme_id=theme.id, factual_rigor="strict"),
    )
    media = registry.invoke(
        AgentId.MEDIA_DISCOVERY,
        ctx(AgentId.MEDIA_DISCOVERY),
        MediaDiscoveryInput(brief=brief, claims=research.claims),
    )
    script = registry.invoke(
        AgentId.SCRIPTWRITER,
        ctx(AgentId.SCRIPTWRITER),
        ScriptInput(
            brief=brief,
            treatment=treatment,
            research=research,
            assets=media,
            scene_count=target_scene_count(theme, 45),
            duration_target_sec=45,
        ),
    )
    a6_ctx = ctx(AgentId.SCENE_DIRECTOR)
    graph = registry.invoke(
        AgentId.SCENE_DIRECTOR,
        a6_ctx,
        SceneDirectionInput(
            script=script,
            treatment=treatment,
            assets=media,
            output=manifest.output,
            mode_policy=policy,
            max_shots_per_scene=theme.production.max_shots_per_scene,
        ),
    )
    return Chain(
        plan, treatment, research, media, script, graph, a6_ctx, registry, services.guard, services
    )


@pytest.fixture(scope="module")
def chain() -> Chain:
    return _chain()


# --------------------------------------------------------------------------- registry
def test_registry_has_all_ten_agents_in_contract_order() -> None:
    registry = build_agent_registry(SETTINGS)
    assert [d.id for d in registry.definitions()] == [d.id for d in AGENT_DEFINITIONS]
    for d in AGENT_DEFINITIONS:
        agent = registry.get(d.id)
        assert agent.input_model.__name__ == d.input_model
        assert agent.output_model.__name__ == d.output_model
    with pytest.raises(AgentNotFoundError):
        DefaultAgentRegistry().get(AgentId.RESEARCH)


def test_registry_rejects_invalid_input(chain: Chain) -> None:
    with pytest.raises(AgentSchemaError, match="input"):
        chain.registry.invoke(AgentId.RESEARCH, chain.ctx, {"brief": {"topic": "x"}})
    with pytest.raises(AgentSchemaError, match="input"):
        chain.registry.invoke(AgentId.RESEARCH, chain.ctx, chain.script)  # wrong model


def test_registry_accepts_dict_payload(chain: Chain) -> None:
    out = chain.registry.invoke(
        AgentId.CREATIVE_DIRECTOR,
        chain.ctx,
        {"brief": {"topic": TOPIC}, "theme": get_theme(CFG, "time-traveler").model_dump()},
    )
    assert isinstance(out, CreativeTreatment)


class _BrokenAgent:
    def __init__(self, result: object) -> None:
        self.definition = next(d for d in AGENT_DEFINITIONS if d.id == AgentId.RESEARCH)
        self.input_model = ResearchInput
        self.output_model = ResearchBrief
        self.result = result

    def run(self, ctx: AgentContext, payload: BaseModel) -> BaseModel:
        return self.result  # type: ignore[return-value]


@pytest.mark.parametrize(
    "bad",
    [
        {"topic": "x", "summary": "y", "claims": [{"id": "not-a-claim"}]},
        CreativeTreatment(
            theme_id="t", theme_version=1, logline="l", genre="g", tone="t",
            narrative_style="n", visual_language=[],
        ),
    ],
)  # fmt: skip
def test_registry_rejects_invalid_output(chain: Chain, bad: object) -> None:
    registry = DefaultAgentRegistry()
    registry.register(_BrokenAgent(bad))
    payload = ResearchInput(brief=CreativeBrief(topic=TOPIC), theme_id="x", factual_rigor="strict")
    with pytest.raises(AgentSchemaError, match="output"):
        registry.invoke(AgentId.RESEARCH, chain.ctx, payload)


# --------------------------------------------------------------------------- A1-A5
def test_a1_plan(chain: Chain) -> None:
    assert chain.plan.scene_count_target == 5
    assert chain.plan.budget_envelope == money(10)
    states = [s.state.value for s in chain.plan.steps]
    assert states[:3] == ["RESEARCHING", "SCRIPTING", "STORYBOARDING"]
    assert any(n.startswith("LLM:") for n in chain.plan.notes)


def test_a2_research(chain: Chain) -> None:
    claims = chain.research.claims
    assert len(claims) == 5
    assert all(c.id.startswith("claim_") for c in claims)
    statuses = [c.status for c in claims]
    assert statuses.count(ClaimStatus.DRAMATIZED) == 1
    assert statuses.count(ClaimStatus.VERIFIED) == 4
    for c in claims:
        if c.status == ClaimStatus.VERIFIED:
            assert c.sources and c.sources[0].url.startswith("https://example.org/sources/")
    assert chain.research.unresolved_questions


def test_a3_media_leaves_rights_unknown(chain: Chain) -> None:
    cands = chain.media.candidates
    assert len(cands) == 8
    assert all(c.rights_status == RightsStatus.UNKNOWN for c in cands)
    assert all(c.candidate_id.startswith("asset_") for c in cands)
    licenses = {c.license.license_type if c.license else None for c in cands}
    assert {"CC0", "public-domain", "CC-BY-4.0", "CC-BY-NC-4.0", None} <= licenses
    nc = next(c for c in cands if c.license and c.license.license_type == "CC-BY-NC-4.0")
    assert nc.license.commercial_use_allowed is False
    by = next(c for c in cands if c.license and c.license.license_type == "CC-BY-4.0")
    assert by.license.attribution_text
    assert {c.provider for c in cands} == {"mock-wikimedia", "mock-openverse", "mock-stock"}
    assert chain.media.blocked == {}


def test_a4_treatment(chain: Chain) -> None:
    t = chain.treatment
    assert (t.theme_id, t.theme_version) == ("time-traveler", 1)
    assert t.style_bible["character"]["ref"] == "asset://characters/host-v1"
    assert "slow_push" in t.visual_language


def test_a5_script(chain: Chain) -> None:
    s = chain.script
    assert len(s.lines) == 5
    assert [b.beat for b in s.beats][-1] == "legacy and call-to-action"
    assert s.word_count == sum(len(line.text.split()) for line in s.lines)
    assert s.word_count <= 45 * 2.5 + 20
    assert s.lines[0].dramatized is True
    claim_ids = {c.id for c in chain.research.claims}
    assert all(set(line.claim_ids) <= claim_ids for line in s.lines)
    assert s.cta and s.cta in s.lines[-1].text


# --------------------------------------------------------------------------- A6
def _assert_graph_invariants(graph: SceneGraph, theme_id: str, mode: ProductionMode) -> None:
    theme = get_theme(CFG, theme_id)
    policy = load_mode_policies(CFG)[mode]
    scenes = graph.scenes
    assert theme.production.min_scenes <= len(scenes) <= theme.production.max_scenes
    assert sum(s.duration_sec for s in scenes) == pytest.approx(45, abs=1e-6)
    shots = [sh for s in scenes for sh in s.shots]
    for s in scenes:
        assert 1 <= len(s.shots) <= theme.production.max_shots_per_scene
        assert sum(sh.duration_sec for sh in s.shots) == pytest.approx(s.duration_sec, abs=1e-6)
    for sh in shots:
        assert sh.provider_plan.strategy in policy.allowed_strategies
        assert sh.provider_plan.prompt and len(sh.provider_plan.prompt) <= 480
        assert sh.provider_plan.prompt_template_id == SHOT_PROMPT_TEMPLATE_ID
        assert sh.provider_plan.prompt_template_version == 1
        assert sh.provider_plan.provider == "mock-video"
        if sh.provider_plan.strategy == GenerationStrategy.GENERATIVE:
            assert sh.provider_plan.capability == ProviderCapability.VIDEO_GENERATION
            assert sh.provider_plan.model == "mock-video-cinematic"
            assert sh.disclosure.synthetic_media and sh.disclosure.label_text
        else:
            assert sh.provider_plan.capability == ProviderCapability.IMAGE_TO_VIDEO
            assert sh.provider_plan.model == "mock-video-draft"
            assert not sh.disclosure.synthetic_media
    generative = sum(sh.provider_plan.strategy == GenerationStrategy.GENERATIVE for sh in shots)
    assert generative == round(len(shots) * policy.generative_shot_ratio)
    # The graph must also pass full manifest validation (dependency ids etc.).
    manifest, _, _ = _manifest(mode, theme_id)
    ProductionManifest.model_validate(
        {**manifest.model_dump(), "scenes": [s.model_dump() for s in scenes]}
    )


def test_a6_scene_graph_balanced(chain: Chain) -> None:
    graph = chain.graph
    _assert_graph_invariants(graph, "time-traveler", ProductionMode.BALANCED)
    assert len(graph.scenes) == 5
    hook = graph.scenes[0].shots[-1]
    assert hook.visual.shot_type == "close_up"
    assert hook.performance.lip_sync_required is True
    assert hook.performance.character_ref == "asset://characters/host-v1"
    assert hook.disclosure.label_text == "Reconstruction"
    approved_like = set(chain.media.selected_ids)
    refs = {a.asset_id for s in graph.scenes for sh in s.shots for a in sh.assets}
    assert refs and refs <= approved_like
    assert all(set(s.facts) <= {c.id for c in chain.research.claims} for s in graph.scenes)


@pytest.mark.parametrize(
    ("mode", "theme_id"),
    [
        (ProductionMode.ECONOMY, "time-traveler"),
        (ProductionMode.PREMIUM, "time-traveler"),
        (ProductionMode.BALANCED, "mystery-explorer"),
        (ProductionMode.BALANCED, "fascinating-places"),
    ],
)
def test_a6_respects_mode_policy(mode: ProductionMode, theme_id: str) -> None:
    c = _chain(mode, theme_id)
    _assert_graph_invariants(c.graph, theme_id, mode)
    if mode == ProductionMode.ECONOMY:
        assert all(
            sh.provider_plan.strategy == GenerationStrategy.LICENSED_STILL_MOTION
            for s in c.graph.scenes
            for sh in s.shots
        )
    if theme_id == "mystery-explorer":  # no recurring character -> no lip sync
        assert not any(sh.performance.lip_sync_required for s in c.graph.scenes for sh in s.shots)


# --------------------------------------------------------------------------- A7, A8, A10
def test_a7_one_guarded_call_per_attempt(chain: Chain) -> None:
    scene = chain.graph.scenes[0]
    shot = scene.shots[0]
    manifest, theme, policy = _manifest()
    ctx = _ctx(
        manifest, theme, policy, chain.services, f"{manifest.production_id}:G:a7:{shot.id}:2"
    )
    before = len(chain.guard.calls)
    ref = chain.registry.invoke(
        AgentId.VISUAL_PRODUCTION,
        ctx,
        ShotProductionInput(scene_id=scene.id, shot=shot, attempt=2, retry_reason="artifact"),
    )
    assert isinstance(ref, RenderedShotRef)
    assert len(chain.guard.calls) == before + 1
    name, request, agent_id, attempt = chain.guard.calls[-1]
    assert (name, agent_id, attempt) == ("mock-video", AgentId.VISUAL_PRODUCTION, 2)
    assert request.capability == shot.provider_plan.capability
    assert request.model == shot.provider_plan.model
    assert request.idempotency_key.endswith(":2")
    assert ref.attempt == 2 and ref.asset_id and ref.ledger_event_id
    assert ref.cost > 0
    assert ctx.extras[LEDGER_EVENTS][0].event_id == ref.ledger_event_id


def test_a8_audio(chain: Chain) -> None:
    manifest, theme, policy = _manifest()
    ctx = _ctx(manifest, theme, policy, chain.services, f"{manifest.production_id}:G:a8:prod:1")
    before = len(chain.guard.calls)
    pkg = chain.registry.invoke(
        AgentId.AUDIO_PERFORMANCE,
        ctx,
        AudioInput(scenes=chain.graph.scenes, script=chain.script),
    )
    assert isinstance(pkg, AudioPackage)
    narration = [t for t in pkg.tracks if t.kind == "narration"]
    music = [t for t in pkg.tracks if t.kind == "music"]
    assert len(narration) == len(chain.graph.scenes)
    assert len(music) == 1
    lip = [a for a in pkg.alignments if a.method == "lip_sync"]
    assert [a.shot_id for a in lip] == [chain.graph.scenes[0].shots[-1].id]
    caps = [req.capability for _, req, _, _ in chain.guard.calls[before:]]
    assert caps.count(ProviderCapability.VOICE_TTS) == 5
    assert caps.count(ProviderCapability.MUSIC_GENERATION) == 1
    assert caps.count(ProviderCapability.LIP_SYNC) == 1
    keys = [req.idempotency_key for _, req, _, _ in chain.guard.calls[before:]]
    assert len(keys) == len(set(keys))


def test_a10_cost_plan(chain: Chain) -> None:
    manifest, theme, policy = _manifest()
    manifest = manifest.model_copy(update={"scenes": chain.graph.scenes})
    estimate = FakeEstimator(chain.services.catalog).estimate(manifest, policy)
    ctx = _ctx(manifest, theme, policy, chain.services, "k:a10")
    plan = chain.registry.invoke(
        AgentId.COST_OPTIMIZER,
        ctx,
        CostPlanningInput(manifest=manifest, mode_policy=policy, estimate=estimate),
    )
    assert isinstance(plan, CostPlan)
    assert plan.within_budget == (estimate.total_estimated <= manifest.budget.limit)
    assert any("draft model" in r for r in plan.recommendations)
    tight = manifest.model_copy(update={"budget": BudgetSnapshot(limit=money("0.5"))})
    over = chain.registry.invoke(
        AgentId.COST_OPTIMIZER,
        ctx,
        CostPlanningInput(manifest=tight, mode_policy=policy, estimate=estimate),
    )
    assert over.within_budget is False
    assert any("Over budget" in r for r in over.recommendations)


# --------------------------------------------------------------------------- A9
def _review_manifest(chain: Chain) -> ProductionManifest:
    manifest, _, _ = _manifest()
    scenes = [s.model_copy(deep=True) for s in chain.graph.scenes]
    for s in scenes:
        for sh in s.shots:
            sh.status = WorkStatus.COMPLETE
    return manifest.model_copy(update={"scenes": scenes, "master_render_asset_id": "asset_m"})


def _master(**overrides) -> MasterRender:
    data = {
        "asset_id": "asset_m",
        "uri": "local://x",
        "duration_sec": 45.2,
        "width": 1080,
        "height": 1920,
        "fps": 30,
        "codec": "h264",
        "size_bytes": 10,
        "sha256": "0" * 64,
    }
    return MasterRender(**(data | overrides))


def _review(chain: Chain, manifest: ProductionManifest, master: MasterRender | None):
    _, theme, policy = _manifest()
    ctx = _ctx(manifest, theme, policy, chain.services, f"k:a9:{id(master)}")
    return chain.registry.invoke(
        AgentId.EDITOR_QC,
        ctx,
        ReviewInput(manifest=manifest, research=chain.research, master=master),
    )


def test_a9_passes_matching_master(chain: Chain) -> None:
    report = _review(chain, _review_manifest(chain), _master())
    assert report.status == ReviewStatus.PASSED
    assert report.passed
    assert not any(f.blocking for f in report.findings)
    assert {s.dimension for s in report.scores} >= {"technical", "continuity", "compliance"}


def test_a9_flags_mismatched_master_as_critical(chain: Chain) -> None:
    report = _review(chain, _review_manifest(chain), _master(width=720, height=1280, codec="vp9"))
    assert report.status == ReviewStatus.FAILED
    master_findings = [f for f in report.findings if f.gate == ReviewGate.MASTER]
    assert master_findings and master_findings[0].severity == Severity.CRITICAL
    assert any("resolution" in e for e in master_findings[0].evidence)
    assert any("codec" in e for e in master_findings[0].evidence)
    long = _review(chain, _review_manifest(chain), _master(duration_sec=46.0))
    assert long.status == ReviewStatus.FAILED


def test_a9_flags_missing_master_incomplete_shots_labels_claims_budget(chain: Chain) -> None:
    m = _review_manifest(chain)
    m.scenes[1].shots[0].status = WorkStatus.FAILED
    gen = next(sh for s in m.scenes for sh in s.shots if sh.disclosure.synthetic_media)
    gen.disclosure.label_text = None
    m.scenes[2].facts = ["claim_99"]
    research = chain.research.model_copy(deep=True)
    research.claims[1].status = ClaimStatus.DISPUTED
    m.scenes[3].facts = [research.claims[1].id]
    m.budget.actual = m.budget.limit + Decimal(1)
    _, theme, policy = _manifest()
    report = chain.registry.invoke(
        AgentId.EDITOR_QC,
        _ctx(m, theme, policy, chain.services, "k:a9:bad"),
        ReviewInput(manifest=m, research=research, master=None),
    )
    critical_gates = {f.gate for f in report.findings if f.severity == Severity.CRITICAL}
    assert critical_gates == {
        ReviewGate.MASTER,
        ReviewGate.SCENE,
        ReviewGate.MEDIA,
        ReviewGate.RESEARCH,
        ReviewGate.BUDGET,
    }
    assert any(f.severity == Severity.MAJOR and "missing" in f.message for f in report.findings)


# --------------------------------------------------------------------------- guard + prompts
def test_every_provider_call_goes_through_guard(chain: Chain) -> None:
    invoked = sum(len(p.invocations) for p in chain.services.providers._providers.values())
    assert invoked == len(chain.guard.calls) > 0
    assert chain.ctx.extras[PROMPT_TEMPLATES][0] == "a6_scene_director@v1"


def test_prompt_templates_exist_and_render() -> None:
    lib = PromptLibrary(SETTINGS.prompts_dir)
    for d in AGENT_DEFINITIONS:
        t = lib.get(d.prompt_template_id, d.prompt_template_version)
        assert not t.body.lstrip().startswith("<!--")
        assert t.placeholders()
        rendered = t.render(**{name: "X" for name in t.placeholders()})
        assert "$" not in rendered
    assert lib.get(SHOT_PROMPT_TEMPLATE_ID, 1).placeholders() >= {"shot_type", "description"}
    with pytest.raises(PromptTemplateNotFoundError):
        lib.get("a1_master_orchestrator", 99)
    assert lib.get_or_fallback("nope", 1).render(task="t", context="c") == "t\n\nc"


def test_planning_helpers() -> None:
    parts = split_centis(45, [0.8, 1, 1, 1, 1])
    assert round(sum(parts), 2) == 45 and all(round(p, 2) == p for p in parts)
    beats = ["hook", "arrival", "context", "reveal", "legacy", "call-to-action"]
    assert beats_for_scenes(beats, 5)[-1] == "legacy and call-to-action"
    assert len(beats_for_scenes(beats[:3], 5)) == 5
    theme = get_theme(CFG, "time-traveler")
    assert target_scene_count(theme, 45) == 5
    assert target_scene_count(theme, 10) == theme.production.min_scenes
    assert target_scene_count(theme, 170) == theme.production.max_scenes
