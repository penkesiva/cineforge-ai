"""YouTube-first trending discovery. References are not assets and not research claims."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from cineforge.contracts.common import ContractModel, new_id, utcnow


class DiscoveryMode(StrEnum):
    POPULAR = "popular"
    RECENT = "recent"


class Freshness(StrEnum):
    FRESH = "fresh"
    CACHED = "cached"


class InspirationReference(ContractModel):
    """Identity of a source video. No title, thumbnail, or statistics."""

    platform: Literal["youtube"] = "youtube"
    video_id: str = Field(min_length=6, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    watch_url: str
    retrieved_at: datetime

    @model_validator(mode="after")
    def _canonical_url(self) -> InspirationReference:
        expected = f"https://www.youtube.com/watch?v={self.video_id}"
        if self.watch_url != expected:
            raise ValueError("watch_url must be the canonical YouTube watch URL for video_id")
        return self


class DiscoveryFilters(ContractModel):
    mode: DiscoveryMode = DiscoveryMode.POPULAR
    region_code: str = Field(default="US", min_length=2, max_length=2, pattern=r"^[A-Z]{2}$")
    video_category_id: str | None = Field(default=None, pattern=r"^[0-9]{1,4}$")
    query: str | None = Field(default=None, max_length=200)
    lookback_days: Literal[1, 7, 30] | None = None
    relevance_language: str | None = Field(default=None, pattern=r"^[a-z]{2}(-[A-Za-z]{2})?$")
    page_size: int = Field(default=25, ge=1, le=50)

    @model_validator(mode="after")
    def _mode_filters(self) -> DiscoveryFilters:
        if self.mode == DiscoveryMode.POPULAR:
            extra = [
                name
                for name, value in (
                    ("query", self.query),
                    ("lookback_days", self.lookback_days),
                    ("relevance_language", self.relevance_language),
                )
                if value not in (None, "")
            ]
            if extra:
                raise ValueError("popular chart does not take search filters: " + ", ".join(extra))
        else:
            if self.video_category_id:
                raise ValueError("recent search does not take video_category_id")
            text = (self.query or "").strip()
            if not text:
                raise ValueError("recent search needs a query")
            self.query = text
            if self.lookback_days is None:
                self.lookback_days = 7
        return self


class TrendCandidate(ContractModel):
    platform: Literal["youtube"] = "youtube"
    video_id: str
    watch_url: str
    title: str
    channel_id: str
    channel_name: str
    published_at: datetime | None = None
    duration_sec: int | None = None
    category_id: str | None = None
    thumbnail_url: str | None = None
    view_count: int | None = None
    like_count: int | None = None
    comment_count: int | None = None
    retrieved_at: datetime
    source_mode: DiscoveryMode


class DiscoveryRun(ContractModel):
    id: str = Field(default_factory=lambda: new_id("disc"))
    tenant_id: str
    filters: DiscoveryFilters
    provider: str
    is_mock: bool
    freshness: Freshness
    partial: bool = False
    warnings: list[str] = Field(default_factory=list)
    candidates: list[TrendCandidate] = Field(default_factory=list)
    next_cursor: str | None = None
    retrieved_at: datetime = Field(default_factory=utcnow)
    idempotency_key: str
    search_pages: int = 0
    seen_cursors: list[str] = Field(default_factory=list)


class StartDiscoveryRequest(ContractModel):
    mode: DiscoveryMode = DiscoveryMode.POPULAR
    region_code: str = "US"
    video_category_id: str | None = None
    query: str | None = None
    lookback_days: Literal[1, 7, 30] | None = None
    relevance_language: str | None = None
    page_size: int = Field(default=25, ge=1, le=50)
    idempotency_key: str = Field(min_length=8, max_length=200)

    def to_filters(self) -> DiscoveryFilters:
        return DiscoveryFilters(
            mode=self.mode,
            region_code=self.region_code.strip().upper(),
            video_category_id=self.video_category_id,
            query=self.query,
            lookback_days=self.lookback_days,
            relevance_language=self.relevance_language,
            page_size=self.page_size,
        )


class DiscoveryPageRequest(ContractModel):
    cursor: str = Field(min_length=8, max_length=2000)
