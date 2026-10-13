"""A2 Research & Fact Agent: claims with citations (mock sources in Phase 0)."""

from __future__ import annotations

from datetime import date

from cineforge.agents.base import BaseAgent, note
from cineforge.agents.planning import slugify
from cineforge.contracts.agents import (
    AgentContext,
    ClaimStatus,
    FactClaim,
    ResearchBrief,
    ResearchInput,
    SourceCitation,
)
from cineforge.contracts.common import AgentId
from cineforge.contracts.providers import ProviderCapability

# (angle, claim template, status, confidence) - deterministic mock research.
_CLAIM_PATTERNS: tuple[tuple[str, str, ClaimStatus, float], ...] = (
    ("origin", "The story of {topic} begins with a documented founding event.",
     ClaimStatus.VERIFIED, 0.92),
    ("scale", "Contemporary records describe the scale of {topic} as unprecedented for its time.",
     ClaimStatus.VERIFIED, 0.88),
    ("people", "Eyewitness accounts of {topic} were published in newspapers of the period.",
     ClaimStatus.VERIFIED, 0.85),
    ("legacy", "{topic} still shapes how the place is remembered and visited today.",
     ClaimStatus.VERIFIED, 0.8),
    ("scene", "A visitor's first-person moment at {topic} is recreated for the hook.",
     ClaimStatus.DRAMATIZED, 0.5),
    ("detail", "Archival photographs show details of {topic} that most people never notice.",
     ClaimStatus.VERIFIED, 0.78),
    ("debate", "Historians still debate one popular anecdote about {topic}.",
     ClaimStatus.DISPUTED, 0.4),
    ("numbers", "Visitor numbers linked to {topic} have been reported by official sources.",
     ClaimStatus.UNVERIFIED, 0.45),
)  # fmt: skip

_PUBLISHERS = ("Example Historical Society", "Example Archive", "Example University Press")


class ResearchAgent(BaseAgent):
    agent_id = AgentId.RESEARCH
    input_model = ResearchInput
    output_model = ResearchBrief

    def execute(self, ctx: AgentContext, payload: ResearchInput) -> ResearchBrief:
        topic = payload.brief.topic
        slug = slugify(topic)
        count = min(5, payload.max_claims)
        prompt = self.render_prompt(
            ctx,
            topic=topic,
            theme_id=payload.theme_id,
            factual_rigor=payload.factual_rigor,
            max_claims=count,
            prohibited_claims="; ".join(ctx.theme.constraints.prohibited_claims) or "none",
        )
        self.call_provider(
            ctx,
            ProviderCapability.WEB_RESEARCH,
            sub_scope="search",
            prompt=f"sources for: {topic}",
            parameters={"max_results": count * 2},
        )
        response = self._llm(ctx, prompt, "claims")

        claims: list[FactClaim] = []
        for idx, (angle, text, status, confidence) in enumerate(_CLAIM_PATTERNS[:count], 1):
            sources: list[SourceCitation] = []
            if status != ClaimStatus.DRAMATIZED:
                sources = [
                    SourceCitation(
                        url=f"https://example.org/sources/{slug}-{angle}",
                        title=f"{topic}: {angle} (mock source)",
                        publisher=_PUBLISHERS[idx % len(_PUBLISHERS)],
                        published_at=date(2001 + idx, 1 + idx % 12, 1 + idx),
                    )
                ]
            claims.append(
                FactClaim(
                    id=f"claim_{idx:02d}",
                    text=text.format(topic=topic),
                    status=status,
                    sources=sources,
                    confidence=confidence,
                    notes=(
                        "Dramatization: label on screen; not presented as documentary fact."
                        if status == ClaimStatus.DRAMATIZED
                        else f"Mock citation ({payload.factual_rigor} rigor)."
                    ),
                )
            )
        summary = (
            f"{len(claims)} claims about {topic}: "
            f"{sum(c.status == ClaimStatus.VERIFIED for c in claims)} verified, "
            f"{sum(c.status == ClaimStatus.DRAMATIZED for c in claims)} dramatized."
        )
        llm_note = note(response.output_text if response else None, 160)
        if llm_note:
            summary += f" Notes: {llm_note}"
        return ResearchBrief(
            topic=topic,
            summary=summary,
            claims=claims,
            unresolved_questions=[
                f"Which primary source gives the exact date for the key moment of {topic}?",
                f"Are there period photographs of {topic} with clear licensing?",
            ],
        )
