"""Composition-root factory: registry with all 10 logical agents."""

from __future__ import annotations

from cineforge.agents.audio_performance import AudioPerformanceAgent
from cineforge.agents.base import BaseAgent
from cineforge.agents.cost_optimizer import CostOptimizerAgent
from cineforge.agents.creative_director import CreativeDirectorAgent
from cineforge.agents.editor_qc import EditorQCAgent
from cineforge.agents.master_orchestrator import MasterOrchestratorAgent
from cineforge.agents.media_discovery import MediaDiscoveryAgent
from cineforge.agents.prompts import PromptLibrary
from cineforge.agents.registry import DefaultAgentRegistry
from cineforge.agents.research import ResearchAgent
from cineforge.agents.scene_director import SceneDirectorAgent
from cineforge.agents.scriptwriter import ScriptwriterAgent
from cineforge.agents.visual_production import VisualProductionAgent
from cineforge.config import Settings

AGENT_CLASSES: tuple[type[BaseAgent], ...] = (
    MasterOrchestratorAgent,
    ResearchAgent,
    MediaDiscoveryAgent,
    CreativeDirectorAgent,
    ScriptwriterAgent,
    SceneDirectorAgent,
    VisualProductionAgent,
    AudioPerformanceAgent,
    EditorQCAgent,
    CostOptimizerAgent,
)


def build_agent_registry(settings: Settings) -> DefaultAgentRegistry:
    prompts = PromptLibrary(settings.prompts_dir)
    registry = DefaultAgentRegistry()
    for cls in AGENT_CLASSES:
        registry.register(cls(prompts))
    return registry
