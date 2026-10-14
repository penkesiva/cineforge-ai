"""Phase 1 reasoning: structured LLM output with validation/retry/fallback, research
citation check, federated media search, and deterministic guarantees around LLM drafts.

"Real" providers are ``ScriptedProvider`` fakes (offline, canned output) that route
before the mocks, exactly like a ready live provider would.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from cineforge.agents.base import NOTES, REASONING, inline_schema
from cineforge.agents.drafts import ResearchDraft, ScriptDraft
from cineforge.agents.factory import build_agent_registry
from cineforge.agents.planning import target_scene_count, word_budget
from cineforge.agents.research import excerpt_supported, normalize_text
from cineforge.config import Settings
from cineforge.configuration import get_theme, load_mode_policies
from cineforge.contracts.agents import (
    AgentContext,
    AssetSelection,
    AudioInput,
    AudioPackage,
    ClaimStatus,
    CreativeInput,
    CreativeTreatment,
    FactClaim,
    MediaDiscoveryInput,
    ResearchBrief,
    ResearchInput,
    SceneDirectionInput,
    SceneGraph,
    Script,
    ScriptInput,
    SourceCitation,
)
from cineforge.contracts.common import AgentId, ProductionMode, money
from cineforge.contracts.manifest import (
    BudgetSnapshot,
    CreativeBrief,
    OutputProfile,
    ProductionManifest,
    ThemeRef,
)
from cineforge.contracts.media import RightsStatus
from cineforge.contracts.providers import ProviderCapability, ProviderError
from fakes_b import make_runtime, scripted

C = ProviderCapability
SETTINGS = Settings(persistence_backend="memory", queue_backend="inline")
CFG = SETTINGS.configurations_dir
TOPIC = "Eiffel Tower"
PID = "prod_reasoning000001"

EIFFEL_SENTENCE = (
    "It was designed by the engineering company of Gustave Eiffel and built from 1887 to 1889."
)
WIKI_EXTRACT = (
    "The Eiffel Tower is a wrought-iron lattice tower on the Champ de Mars in Paris. "
    f"{EIFFEL_SENTENCE} "
    "The tower was the centrepiece of the 1889 World's Fair, and it was initially criticised "
    "by some of France's leading artists. It is 330 metres tall."
)


def _source(idx: int = 1, extract: str = WIKI_EXTRACT) -> dict:
    return {
        "url": f"https://en.wikipedia.org/wiki/Source_{idx}",
        "title": f"Source {idx}",
        "publisher": "Wikipedia",
        "extract": extract,
        "retrieved_at": datetime(2026, 10, 13, tzinfo=UTC).isoformat(),
    }


@dataclass
class Env:
    services: object
    registry: object
    manifest: ProductionManifest
    theme: object
    policy: object
    n: int = 0

    def ctx(self, agent: AgentId) -> AgentContext:
        self.n += 1
        return AgentContext(
            production_id=self.manifest.production_id,
            tenant_id=self.manifest.tenant_id,
            manifest=self.manifest,
            theme=self.theme,
            mode_policy=self.policy,
            providers=self.services.providers,
            paid_calls=self.services.guard,
            idempotency_key=f"{PID}:TEST:{agent.value}:production:{self.n}",
            extras={},
        )

    def run(self, agent: AgentId, payload, ctx: AgentContext | None = None):
        return self.registry.invoke(agent, ctx or self.ctx(agent), payload)


def _env(theme_id: str = "time-traveler") -> Env:
    _, services = make_runtime(install=False)
    theme = get_theme(CFG, theme_id)
    policy = load_mode_policies(CFG)[ProductionMode.BALANCED]
    manifest = ProductionManifest(
        production_id=PID,
        tenant_id="tenant_demo",
        theme_profile=ThemeRef(id=theme.id, version=theme.version),
        mode=ProductionMode.BALANCED,
        creative_brief=CreativeBrief(topic=TOPIC, genre=theme.genres[0]),
        output=OutputProfile(duration_target_sec=45),
        budget=BudgetSnapshot(limit=policy.default_budget_usd),
    )
    services.budget.create_budget(
        tenant_id=manifest.tenant_id, production_id=PID, limit=money(1000)
    )
    return Env(services, build_agent_registry(SETTINGS), manifest, theme, policy)


def _llm(env: Env, responses: list) -> object:
    return env.services.add_real(scripted("scripted-llm", C.LLM_TEXT, responses))


# --------------------------------------------------------------------------- helpers
def test_inline_schema_resolves_refs_and_drops_titles() -> None:
    schema = inline_schema(ResearchDraft.model_json_schema())
    text = str(schema)
    assert "$ref" not in text and "$defs" not in text and "'title'" not in text
    claim = schema["properties"]["claims"]["items"]
    assert {"text", "source_index", "excerpt", "status"} <= set(claim["properties"])


def test_excerpt_check_normalizes_quotes_and_whitespace() -> None:
    source = "It was  designed by \u201cGustave Eiffel\u201d\u2019s company."
    assert excerpt_supported('it was designed by "Gustave Eiffel"\'s company', source)
    assert not excerpt_supported("short", source)
    assert not excerpt_supported("It was designed by someone else entirely.", source)
    assert normalize_text("  A\u00a0B. ") == "a b"


# --------------------------------------------------------------------------- structured()
def test_mock_llm_keeps_deterministic_path() -> None:
    env = _env()
    ctx = env.ctx(AgentId.CREATIVE_DIRECTOR)
    out = env.run(
        AgentId.CREATIVE_DIRECTOR,
        CreativeInput(brief=env.manifest.creative_brief, theme=env.theme),
        ctx,
    )
    assert isinstance(out, CreativeTreatment)
    assert out.logline.startswith(env.theme.name)
    assert ctx.extras[REASONING] == "deterministic"
    llm_calls = [c for c in env.services.guard.calls if c[1].capability == C.LLM_TEXT]
    assert llm_calls and all("response_schema" not in c[1].parameters for c in llm_calls)


def test_structured_treatment_from_real_llm() -> None:
    env = _env()
    llm = _llm(
        env,
        [
            {
                "structured": {
                    "logline": "One night in 1889, Paris switched on the future.",
                    "narrative_style": "Second person, present tense, breathless.",
                    "visual_language": ["slow dolly through crowds", "gaslight glow"],
                    "director_notes": "Warm amber palette; brass and crowd murmur.",
                }
            }
        ],
    )
    ctx = env.ctx(AgentId.CREATIVE_DIRECTOR)
    out = env.run(
        AgentId.CREATIVE_DIRECTOR,
        CreativeInput(brief=env.manifest.creative_brief, theme=env.theme),
        ctx,
    )
    assert out.logline == "One night in 1889, Paris switched on the future."
    assert "gaslight glow" in out.visual_language
    assert out.style_bible["director_notes"].startswith("Warm amber")
    assert out.style_bible["disclosure_rules"] == env.theme.constraints.disclosure_rules
    assert ctx.extras[REASONING] == "structured:scripted-llm/scripted-llm-v1"
    request = llm.invocations[0]
    assert request.parameters["schema_name"] == "TreatmentDraft"
    assert "$defs" not in str(request.parameters["response_schema"])
    # Only the structured call: real LLMs are never called just for notes.
    assert len(llm.invocations) == 1


def test_invalid_output_retries_once_with_errors_then_succeeds() -> None:
    env = _env()
    good = {
        "logline": "A tower of light rises.",
        "narrative_style": "Calm, close narration.",
        "visual_language": ["dolly", "glow"],
    }
    llm = _llm(env, [{"structured": {"logline": "x"}}, {"structured": good}])
    out = env.run(
        AgentId.CREATIVE_DIRECTOR,
        CreativeInput(brief=env.manifest.creative_brief, theme=env.theme),
    )
    assert out.logline == "A tower of light rises."
    assert len(llm.invocations) == 2
    assert "previous answer was invalid" in llm.invocations[1].prompt
    assert llm.invocations[1].idempotency_key.endswith("llm-treatment-fix")


def test_invalid_twice_falls_back_with_note() -> None:
    env = _env()
    llm = _llm(env, [{"structured": {"nope": 1}}, {"text": "no tool call"}])
    ctx = env.ctx(AgentId.CREATIVE_DIRECTOR)
    out = env.run(
        AgentId.CREATIVE_DIRECTOR,
        CreativeInput(brief=env.manifest.creative_brief, theme=env.theme),
        ctx,
    )
    assert out.logline.startswith(env.theme.name)
    assert len(llm.invocations) == 2
    assert ctx.extras[REASONING] == "deterministic"
    assert any("failed validation" in n for n in ctx.extras[NOTES])


def test_provider_error_falls_back() -> None:
    env = _env()
    llm = _llm(env, [ProviderError("scripted-llm: 529 overloaded", retryable=True)])
    ctx = env.ctx(AgentId.CREATIVE_DIRECTOR)
    out = env.run(
        AgentId.CREATIVE_DIRECTOR,
        CreativeInput(brief=env.manifest.creative_brief, theme=env.theme),
        ctx,
    )
    assert out.logline.startswith(env.theme.name)
    assert len(llm.invocations) == 1
    assert any("LLM unavailable" in n for n in ctx.extras[NOTES])


# --------------------------------------------------------------------------- A2 research
def _research_input(env: Env) -> ResearchInput:
    return ResearchInput(
        brief=env.manifest.creative_brief, theme_id=env.theme.id, factual_rigor="strict"
    )


def test_live_research_citation_check() -> None:
    env = _env()
    env.services.add_real(scripted("scripted-wiki", C.WEB_RESEARCH, [{"sources": [_source()]}]))
    _llm(
        env,
        [
            {
                "structured": {
                    "summary": "The tower was built for the 1889 World's Fair.",
                    "claims": [
                        {
                            "text": "Built from 1887 to 1889 by Eiffel's company.",
                            "source_index": 1,
                            "excerpt": EIFFEL_SENTENCE,
                            "status": "verified",
                            "confidence": 0.9,
                        },
                        {
                            "text": "It is 500 metres tall.",
                            "source_index": 1,
                            "excerpt": "It is 500 metres tall.",
                            "status": "verified",
                            "confidence": 0.9,
                        },
                        {
                            "text": "Artists loved it from day one.",
                            "source_index": 7,
                            "excerpt": "Artists loved it.",
                            "status": "verified",
                            "confidence": 0.8,
                        },
                        {
                            "text": "You stand in the crowd as the lights come on.",
                            "status": "dramatized",
                            "confidence": 0.5,
                        },
                    ],
                    "unresolved_questions": ["Exact switch-on time?"],
                }
            }
        ],
    )
    brief: ResearchBrief = env.run(AgentId.RESEARCH, _research_input(env))
    statuses = [c.status for c in brief.claims]
    assert statuses == [
        ClaimStatus.VERIFIED,
        ClaimStatus.UNVERIFIED,
        ClaimStatus.UNVERIFIED,
        ClaimStatus.DRAMATIZED,
    ]
    first = brief.claims[0]
    assert first.sources[0].url == "https://en.wikipedia.org/wiki/Source_1"
    assert first.sources[0].excerpt and first.sources[0].excerpt in WIKI_EXTRACT
    assert "excerpt not found" in brief.claims[1].notes
    assert brief.claims[2].sources == [] and "unknown source" in brief.claims[2].notes
    assert brief.claims[1].confidence <= 0.4
    assert brief.unresolved_questions == ["Exact switch-on time?"]
    assert "1 verified" in brief.summary


def test_live_research_without_llm_extracts_verbatim_claims() -> None:
    env = _env()
    env.services.add_real(
        scripted("scripted-wiki", C.WEB_RESEARCH, [{"sources": [_source(1), _source(2)]}])
    )
    brief: ResearchBrief = env.run(AgentId.RESEARCH, _research_input(env))
    assert brief.claims
    for claim in brief.claims:
        assert claim.status == ClaimStatus.VERIFIED
        assert claim.sources and claim.sources[0].excerpt == claim.text
        assert excerpt_supported(claim.text, WIKI_EXTRACT)
    # Round-robin across sources.
    assert {c.sources[0].url for c in brief.claims[:2]} == {
        "https://en.wikipedia.org/wiki/Source_1",
        "https://en.wikipedia.org/wiki/Source_2",
    }


@pytest.mark.parametrize(
    "response", [{"sources": []}, ProviderError("scripted-wiki: 503", retryable=False)]
)
def test_live_research_without_sources_returns_no_claims(response) -> None:
    env = _env()
    env.services.add_real(scripted("scripted-wiki", C.WEB_RESEARCH, [response]))
    llm = _llm(env, [{"structured": {}}])
    brief: ResearchBrief = env.run(AgentId.RESEARCH, _research_input(env))
    assert brief.claims == []
    assert brief.unresolved_questions
    assert llm.invocations == []  # nothing to reason about: no LLM spend


# --------------------------------------------------------------------------- A3 media
def _item(provider: str, n: int, *, licensed: bool = True, w: int = 1080, h: int = 1920) -> dict:
    url = f"https://example.org/{provider}/{n}"
    lic = (
        {
            "license_type": "CC-BY-4.0",
            "source_provider": provider,
            "source_url": url,
            "commercial_use_allowed": True,
            "modifications_allowed": True,
            "attribution_required": True,
            "attribution_text": "Photo: A, CC BY 4.0",
        }
        if licensed
        else None
    )
    return {
        "provider": provider,
        "title": f"{provider} {n}",
        "source_url": url,
        "file_url": f"{url}/file.jpg",
        "thumbnail_url": f"{url}/thumb.jpg",
        "width": w,
        "height": h,
        "license": lic,
    }


def _media_input(env: Env) -> MediaDiscoveryInput:
    return MediaDiscoveryInput(brief=env.manifest.creative_brief, claims=[], max_candidates=6)


def test_federated_media_search_isolates_failures_and_ranks() -> None:
    env = _env()
    duplicate = _item("scripted-commons", 1)
    env.services.add_real(
        scripted(
            "scripted-commons",
            C.MEDIA_SEARCH,
            [
                {
                    "items": [
                        _item("scripted-commons", 1),
                        _item("scripted-commons", 2, licensed=False),
                        _item("scripted-commons", 3, w=1920, h=1080),
                        duplicate,
                    ]
                }
            ],
        )
    )
    env.services.add_real(
        scripted("scripted-openverse", C.MEDIA_SEARCH, [ProviderError("openverse: 500")])
    )
    ctx = env.ctx(AgentId.MEDIA_DISCOVERY)
    sel: AssetSelection = env.run(AgentId.MEDIA_DISCOVERY, _media_input(env), ctx)
    assert len(sel.candidates) == 3  # duplicate removed
    assert all(c.rights_status == RightsStatus.UNKNOWN for c in sel.candidates)
    by_id = {c.candidate_id: c for c in sel.candidates}
    ranked = [by_id[i].title for i in sel.selected_ids]
    assert ranked[0] == "scripted-commons 1"  # licensed + portrait + high-res
    assert ranked[-1] == "scripted-commons 2"  # unknown license ranks last
    assert any("openverse" in n for n in ctx.extras[NOTES])
    assert env.services.provider("mock-media-search") is not None
    assert not [c for c in env.services.guard.calls if c[0] == "mock-media-search"]


def test_media_search_with_no_ready_provider_returns_empty_selection() -> None:
    env = _env()
    env.services.providers.disabled.add("mock-media-search")
    sel: AssetSelection = env.run(AgentId.MEDIA_DISCOVERY, _media_input(env))
    assert sel.candidates == [] and sel.selected_ids == []


# --------------------------------------------------------------------------- A5 script
def _claims() -> list[FactClaim]:
    src = [SourceCitation(url="https://example.org/s", title="S", excerpt="e" * 30)]
    return [
        FactClaim(
            id="claim_01",
            text="Fact one about the tower.",
            status=ClaimStatus.VERIFIED,
            sources=src,
            confidence=0.9,
        ),
        FactClaim(
            id="claim_02",
            text="Fact two about the tower.",
            status=ClaimStatus.VERIFIED,
            sources=src,
            confidence=0.9,
        ),
        FactClaim(
            id="claim_03",
            text="Unchecked rumour.",
            status=ClaimStatus.UNVERIFIED,
            sources=src,
            confidence=0.3,
        ),
        FactClaim(
            id="claim_04",
            text="You stand in the crowd.",
            status=ClaimStatus.DRAMATIZED,
            confidence=0.5,
        ),
    ]


def _script_input(env: Env, **kw) -> ScriptInput:
    treatment = env.run(
        AgentId.CREATIVE_DIRECTOR,
        CreativeInput(brief=env.manifest.creative_brief, theme=env.theme),
    )
    research = ResearchBrief(topic=TOPIC, summary="s", claims=_claims())
    return ScriptInput(
        brief=env.manifest.creative_brief,
        treatment=treatment,
        research=research,
        assets=AssetSelection(candidates=[]),
        scene_count=target_scene_count(env.theme, 45),
        duration_target_sec=45,
        **kw,
    )


def test_llm_script_is_bounded_by_deterministic_rules() -> None:
    env = _env()
    payload = _script_input(env, excluded_claim_ids=["claim_02"])
    n = payload.scene_count
    long_line = " ".join(["word"] * 80)
    _llm(
        env,
        [
            {
                "structured": {
                    "hook": "What if the night sky caught fire over Paris?",
                    "lines": [
                        {"scene_order": 1, "text": "The crowd gasps.", "claim_ids": ["claim_04"]},
                        {
                            "scene_order": 2,
                            "text": "Fact two retold.",
                            "claim_ids": ["claim_02", "claim_01"],
                        },
                        {
                            "scene_order": 3,
                            "text": long_line,
                            "claim_ids": ["claim_03", "claim_99"],
                        },
                        {
                            "scene_order": 4,
                            "text": "A dramatized aside.",
                            "claim_ids": ["claim_04"],
                        },
                    ],
                }
            }
        ],
    )
    script: Script = env.run(AgentId.SCRIPTWRITER, payload)
    assert [line.scene_order for line in script.lines] == list(range(1, n + 1))
    lines = {line.scene_order: line for line in script.lines}
    assert script.hook == "What if the night sky caught fire over Paris?"
    assert lines[1].claim_ids == ["claim_04"] and lines[1].dramatized
    assert lines[2].claim_ids == ["claim_01"]  # rejected claim_02 dropped
    assert lines[3].claim_ids == []  # unverified + unknown dropped
    assert lines[4].claim_ids == [] and not lines[4].dramatized  # dramatized only in hook
    per_line = max(8, word_budget(45) // n)
    assert len(lines[3].text.split()) <= per_line
    cited = {cid for line in script.lines for cid in line.claim_ids}
    assert cited <= {"claim_01", "claim_04"}
    if env.theme.narrative.cta:
        assert script.lines[-1].text.endswith(f"{env.theme.narrative.cta}.")


def test_deterministic_script_never_cites_excluded_claims() -> None:
    env = _env()
    script: Script = env.run(
        AgentId.SCRIPTWRITER, _script_input(env, excluded_claim_ids=["claim_01", "claim_04"])
    )
    cited = {cid for line in script.lines for cid in line.claim_ids}
    assert cited and cited <= {"claim_02"}


def test_script_draft_schema_requires_lines() -> None:
    with pytest.raises(ValueError):
        ScriptDraft.model_validate({"hook": "Hello there", "lines": []})


# --------------------------------------------------------------------------- A6 storyboard
def _direction_input(env: Env) -> SceneDirectionInput:
    script: Script = env.run(AgentId.SCRIPTWRITER, _script_input(env))
    treatment = env.run(
        AgentId.CREATIVE_DIRECTOR,
        CreativeInput(brief=env.manifest.creative_brief, theme=env.theme),
    )
    return SceneDirectionInput(
        script=script,
        treatment=treatment,
        assets=AssetSelection(candidates=[]),
        output=env.manifest.output,
        mode_policy=env.policy,
        max_shots_per_scene=env.theme.production.max_shots_per_scene,
    )


def test_llm_storyboard_only_changes_creative_fields() -> None:
    env = _env()
    payload = _direction_input(env)
    baseline: SceneGraph = env.run(AgentId.SCENE_DIRECTOR, payload)
    _llm(
        env,
        [
            {
                "structured": {
                    "scenes": [
                        {
                            "order": 2,
                            "title": "Gaslight Crowds",
                            "shots": [
                                {
                                    "description": "Crowds in top hats look up at the tower.",
                                    "shot_type": "wide",
                                    "camera_motion": "crane up",
                                    "lighting": "gaslight",
                                },
                                {
                                    "description": "A child's face lit amber.",
                                    "shot_type": "extreme_close_up",
                                    "camera_motion": "static",
                                },
                            ],
                        },
                    ]
                }
            }
        ],
    )
    graph: SceneGraph = env.run(AgentId.SCENE_DIRECTOR, payload)
    assert graph.scenes[1].title == "Gaslight Crowds"
    first = graph.scenes[1].shots[0]
    assert first.description.startswith("Crowds in top hats")
    assert first.visual.lighting == "gaslight"
    for new, old in zip(graph.scenes, baseline.scenes, strict=True):
        assert new.duration_sec == old.duration_sec
        assert [s.duration_sec for s in new.shots] == [s.duration_sec for s in old.shots]
        assert [s.provider_plan.strategy for s in new.shots] == [
            s.provider_plan.strategy for s in old.shots
        ]
        assert [s.disclosure for s in new.shots] == [s.disclosure for s in old.shots]
    # Scenes the LLM skipped keep their deterministic content.
    assert graph.scenes[0].title == baseline.scenes[0].title


# --------------------------------------------------------------------------- A8 flags
def test_audio_flags_split_narration_and_music() -> None:
    env = _env()
    graph: SceneGraph = env.run(AgentId.SCENE_DIRECTOR, _direction_input(env))
    script: Script = env.run(AgentId.SCRIPTWRITER, _script_input(env))
    narration: AudioPackage = env.run(
        AgentId.AUDIO_PERFORMANCE,
        AudioInput(scenes=graph.scenes[:1], script=script, include_music=False),
    )
    assert [t.kind for t in narration.tracks] == ["narration"]
    music: AudioPackage = env.run(
        AgentId.AUDIO_PERFORMANCE,
        AudioInput(scenes=graph.scenes, script=script, include_narration=False),
    )
    assert [t.kind for t in music.tracks] == ["music"]
    assert music.alignments == []
