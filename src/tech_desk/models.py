from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from tech_desk.timeutils import now_utc


class RelevanceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class UpdateCategory(str, Enum):
    PRODUCT_LAUNCH = "product_launch"
    PARTNERSHIP = "partnership"
    FUNDING = "funding"
    RESEARCH = "research"
    REGULATION = "regulation"
    EVENT = "event"
    TREND = "trend"
    VENDOR_MOVE = "vendor_move"
    OTHER = "other"


class TechDeskDefinition(BaseModel):
    id: str
    code: str
    name: str
    priority: bool = False
    description: str = ""
    areas: list[str] = Field(default_factory=list)
    sub_areas: dict[str, list[str]] = Field(default_factory=dict)
    search_queries: list[str] = Field(default_factory=list)
    key_vendors: list[str] = Field(default_factory=list)


class ResearchRunResult(BaseModel):
    """Detached research run summary — safe to use after the DB session closes."""

    id: int
    status: str
    period: str
    desks_processed: int = 0
    updates_found: int = 0
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ResearchResult(BaseModel):
    title: str
    url: str
    snippet: str = ""
    source_domain: str = ""
    published_date: str | None = None
    query: str = ""
    target_vendor: str = ""
    image_url: str = ""


class CuratedUpdate(BaseModel):
    desk_id: str
    title: str
    summary: str
    source_url: str
    source_name: str = ""
    vendor: str = ""
    published_date: datetime | None = None
    discovered_at: datetime = Field(default_factory=now_utc)
    category: UpdateCategory = UpdateCategory.OTHER
    relevance: RelevanceLevel = RelevanceLevel.MEDIUM
    tags: list[str] = Field(default_factory=list)
    key_takeaways: list[str] = Field(default_factory=list)
    stakeholder_impact: str = ""
    raw_snippet: str = ""
    image_url: str = ""


class VendorIntelSection(BaseModel):
    vendor: str
    activity_level: str = "moderate"  # high | moderate | low | none
    image_url: str = ""
    trend_summary: str = ""
    strategic_position: str = ""
    latest_moves: list[str] = Field(default_factory=list)
    updates: list[CuratedUpdate] = Field(default_factory=list)
    watch_items: list[str] = Field(default_factory=list)
    cotiviti_relevance: str = ""


class DeskReportSection(BaseModel):
    desk_id: str
    desk_name: str
    desk_code: str
    priority: bool
    executive_summary: str = ""
    highlights: list[str] = Field(default_factory=list)
    updates: list[CuratedUpdate] = Field(default_factory=list)
    vendor_sections: list[VendorIntelSection] = Field(default_factory=list)
    trend_analysis: str = ""
    vendor_landscape: str = ""
    recommendations: list[str] = Field(default_factory=list)
    sub_area_coverage: dict[str, list[str]] = Field(default_factory=dict)


class GeneratedReport(BaseModel):
    id: str | None = None
    period: str
    title: str
    generated_at: datetime = Field(default_factory=now_utc)
    period_start: datetime
    period_end: datetime
    executive_summary: str = ""
    sections: list[DeskReportSection] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
