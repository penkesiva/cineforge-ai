"""A2 Research & Fact Agent: claims with citations (ENG-04).

Paths, chosen by the routed providers:

- **Live sources + LLM:** fetch sources (e.g. Wikipedia), ask the LLM for claims that
  cite a numbered source with a verbatim excerpt, then run the deterministic citation
  check: an unknown source or an excerpt not found in that source downgrades the claim
  to ``unverified``.
- **Live sources, no LLM:** extractive claims (verbatim sentences from the sources).
- **Mock research provider:** deterministic mock claims (Phase 0 behaviour).

Nothing is ever presented as verified without a fetched source that contains it.
"""

from __future__ import annotations

import re
from datetime import date

from pydantic import ValidationError

from cineforge.agents.base import BaseAgent, note
from cineforge.agents.drafts import ClaimDraft, ResearchDraft
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
from cineforge.contracts.providers import ProviderCapability, ProviderError, ResearchSource

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
MAX_LIVE_CLAIMS = 6
MAX_SOURCES = 4
SOURCE_CHARS_IN_PROMPT = 2500
MIN_EXCERPT_CHARS = 20
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")
_QUOTES = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
                         "\u2013": "-", "\u2014": "-", "\u00a0": " "})  # fmt: skip


def normalize_text(text: str) -> str:
    flat = " ".join(text.translate(_QUOTES).lower().split())
    return flat.strip(" .,;:!?\"'")


def excerpt_supported(excerpt: str, source_text: str) -> bool:
    """True when the excerpt (normalized) appears verbatim in the source text."""
    needle = normalize_text(excerpt)
    return len(needle) >= MIN_EXCERPT_CHARS and needle in normalize_text(source_text)


def _citation(source: ResearchSource, excerpt: str | None) -> SourceCitation:
    return SourceCitation(
        url=source.url,
        title=source.title,
        publisher=source.publisher,
        published_at=source.published_at,
        retrieved_at=source.retrieved_at,
        excerpt=excerpt,
    )


def verify_claims(
    drafts: list[ClaimDraft], sources: list[ResearchSource], *, limit: int
) -> list[FactClaim]:
    """Deterministic citation check for LLM claims (ENG-04)."""
    claims: list[FactClaim] = []
    for draft in drafts[:limit]:
        idx = len(claims) + 1
        source = (
            sources[draft.source_index - 1]
            if draft.source_index is not None and 1 <= draft.source_index <= len(sources)
            else None
        )
        if draft.status == "dramatized":
            claims.append(
                FactClaim(
                    id=f"claim_{idx:02d}",
                    text=draft.text,
                    status=ClaimStatus.DRAMATIZED,
                    sources=[_citation(source, draft.excerpt or None)] if source else [],
                    confidence=min(draft.confidence, 0.6),
                    notes="Dramatization: label on screen; not presented as documentary fact.",
                )
            )
            continue
        supported = source is not None and excerpt_supported(draft.excerpt, source.extract)
        if supported:
            status = ClaimStatus(draft.status)
            notes = "Citation check passed: excerpt found in the cited source."
            confidence = draft.confidence
        else:
            status = ClaimStatus.UNVERIFIED
            notes = (
                "Citation check failed: "
                + ("unknown source." if source is None else "excerpt not found in the source.")
                + " Needs human review before use."
            )
            confidence = min(draft.confidence, 0.4)
        claims.append(
            FactClaim(
                id=f"claim_{idx:02d}",
                text=draft.text,
                status=status,
                sources=[_citation(source, draft.excerpt or None)] if source else [],
                confidence=confidence,
                notes=notes,
            )
        )
    return claims


def extractive_claims(sources: list[ResearchSource], *, limit: int) -> list[FactClaim]:
    """No-LLM fallback: verbatim, citable sentences taken round-robin from the sources."""
    per_source: list[list[str]] = []
    for source in sources:
        sentences = [
            s.strip()
            for s in _SENTENCE.split(" ".join(source.extract.split()))
            if 40 <= len(s.strip()) <= 300
        ]
        per_source.append(sentences)
    claims: list[FactClaim] = []
    depth = 0
    while len(claims) < limit and any(depth < len(s) for s in per_source):
        for source, sentences in zip(sources, per_source, strict=True):
            if depth < len(sentences) and len(claims) < limit:
                sentence = sentences[depth]
                claims.append(
                    FactClaim(
                        id=f"claim_{len(claims) + 1:02d}",
                        text=sentence,
                        status=ClaimStatus.VERIFIED,
                        sources=[_citation(source, sentence)],
                        confidence=0.7,
                        notes="Extracted verbatim from the cited source (no LLM).",
                    )
                )
        depth += 1
    return claims


class ResearchAgent(BaseAgent):
    agent_id = AgentId.RESEARCH
    input_model = ResearchInput
    output_model = ResearchBrief

    def execute(self, ctx: AgentContext, payload: ResearchInput) -> ResearchBrief:
        provider = self._resolve_provider(ctx, ProviderCapability.WEB_RESEARCH, None)
        if provider.info.is_mock:
            return self._mock_research(ctx, payload)
        return self._live_research(ctx, payload, provider.info.name)

    # ------------------------------------------------------------------ live
    def _live_research(
        self, ctx: AgentContext, payload: ResearchInput, provider_name: str
    ) -> ResearchBrief:
        topic = payload.brief.topic
        limit = min(MAX_LIVE_CLAIMS, payload.max_claims)
        sources: list[ResearchSource] = []
        error: str | None = None
        try:
            response, _ = self.call_provider(
                ctx,
                ProviderCapability.WEB_RESEARCH,
                sub_scope="search",
                provider_name=provider_name,
                prompt=topic,
                parameters={"max_results": MAX_SOURCES, "language": payload.brief.language},
            )
            for raw in response.output_data.get("sources", [])[:MAX_SOURCES]:
                try:
                    source = ResearchSource.model_validate(raw)
                except ValidationError:
                    continue
                if source.extract.strip():
                    sources.append(source)
        except ProviderError as exc:
            error = str(exc)
            self._note(ctx, f"research provider failed: {exc}")

        if not sources:
            return ResearchBrief(
                topic=topic,
                summary=f"No usable sources found for {topic}"
                + (f" ({note(error, 120)})." if error else "."),
                claims=[],
                unresolved_questions=[f"Which reliable sources document {topic}?"],
            )

        numbered = "\n\n".join(
            f"[{i}] {s.title} ({s.url})\n{s.extract[:SOURCE_CHARS_IN_PROMPT]}"
            for i, s in enumerate(sources, 1)
        )
        prompt = self.render_prompt(
            ctx,
            topic=topic,
            theme_id=payload.theme_id,
            factual_rigor=payload.factual_rigor,
            max_claims=limit,
            prohibited_claims="; ".join(ctx.theme.constraints.prohibited_claims) or "none",
            sources=numbered,
        )
        draft = self.structured(ctx, ResearchDraft, prompt, scope="claims", max_tokens=2500)
        if draft is not None:
            claims = verify_claims(draft.claims, sources, limit=limit)
            summary = draft.summary
            questions = list(draft.unresolved_questions)
        else:
            claims = extractive_claims(sources, limit=limit)
            summary = f"{len(claims)} claims extracted verbatim from {len(sources)} sources."
            questions = [f"Which primary source gives exact dates for the key moments of {topic}?"]
        verified = sum(c.status == ClaimStatus.VERIFIED for c in claims)
        flagged = sum(c.status in (ClaimStatus.UNVERIFIED, ClaimStatus.DISPUTED) for c in claims)
        summary = f"{summary} ({verified} verified, {flagged} need review.)"
        return ResearchBrief(
            topic=topic, summary=summary[:1000], claims=claims, unresolved_questions=questions
        )

    # ------------------------------------------------------------------ mock
    def _mock_research(self, ctx: AgentContext, payload: ResearchInput) -> ResearchBrief:
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
            sources="(mock research: no live sources)",
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


__all__ = [
    "ResearchAgent",
    "excerpt_supported",
    "extractive_claims",
    "normalize_text",
    "verify_claims",
]
