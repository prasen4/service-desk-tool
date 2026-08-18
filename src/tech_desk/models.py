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


class VendorStatus(str, Enum):
    """Pipeline stage for a tracked vendor (Technology Desk CRM).

    Stages are intentionally granular so the status timeline reflects real
    chronology (how long a vendor sat in each stage). ``REJECTED`` and
    ``ON_HOLD`` are "branch" outcomes — they can happen from any stage and
    aren't part of the main left-to-right pipeline order below.
    """

    IDENTIFIED = "identified"
    OUTREACH_SENT = "outreach_sent"
    MEETING_SCHEDULED = "meeting_scheduled"
    PROPOSAL_RECEIVED = "proposal_received"
    POC_IN_PROGRESS = "poc_in_progress"
    EVALUATION = "evaluation"
    CONTRACT_NEGOTIATION = "contract_negotiation"
    SELECTED = "selected"
    IMPLEMENTATION = "implementation"
    REJECTED = "rejected"
    ON_HOLD = "on_hold"


VENDOR_STATUS_LABELS: dict[str, str] = {
    VendorStatus.IDENTIFIED.value: "Identified",
    VendorStatus.OUTREACH_SENT.value: "Outreach Sent",
    VendorStatus.MEETING_SCHEDULED.value: "Meeting Scheduled",
    VendorStatus.PROPOSAL_RECEIVED.value: "Proposal Received",
    VendorStatus.POC_IN_PROGRESS.value: "POC In Progress",
    VendorStatus.EVALUATION.value: "Evaluation",
    VendorStatus.CONTRACT_NEGOTIATION.value: "Contract Negotiation",
    VendorStatus.SELECTED.value: "Selected",
    VendorStatus.IMPLEMENTATION.value: "Implementation",
    VendorStatus.REJECTED.value: "Rejected",
    VendorStatus.ON_HOLD.value: "On Hold",
}

# The main left-to-right pipeline (chronological progression). REJECTED and
# ON_HOLD are branch/side outcomes reachable from any stage, so they're kept
# out of this ordered list and rendered separately in the UI.
VENDOR_STATUS_PIPELINE: list[str] = [
    VendorStatus.IDENTIFIED.value,
    VendorStatus.OUTREACH_SENT.value,
    VendorStatus.MEETING_SCHEDULED.value,
    VendorStatus.PROPOSAL_RECEIVED.value,
    VendorStatus.POC_IN_PROGRESS.value,
    VendorStatus.EVALUATION.value,
    VendorStatus.CONTRACT_NEGOTIATION.value,
    VendorStatus.SELECTED.value,
    VendorStatus.IMPLEMENTATION.value,
]

VENDOR_STATUS_BRANCH: list[str] = [
    VendorStatus.REJECTED.value,
    VendorStatus.ON_HOLD.value,
]


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
    vendors_added: list[str] = Field(default_factory=list)
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
    who_is_affected_first: str = ""
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


class CompetitorProfile(BaseModel):
    name: str
    why_relevant: str = ""
    key_differences: str = ""
    evidence: str = ""
    source_verified: bool = False


class ComparisonRow(BaseModel):
    """One row of a vendor-vs-competitor comparison table. ``values`` is keyed
    by product name (the evaluated vendor + each named competitor) so the
    table can have as many comparison columns as competitors were identified,
    matching how these tables read in practice (named products as columns,
    not generic "Competitor 1/2" placeholders)."""

    criterion: str
    values: dict[str, str] = Field(default_factory=dict)
    notes: str = ""


class ReferenceItem(BaseModel):
    label: str = ""
    type: str = ""
    url: str = ""


class PositionPaperResult(BaseModel):
    """Detached position-paper summary — safe to use after the DB session closes."""

    id: int
    vendor: str
    status: str
    custom_prompt: str = ""
    docx_path: str | None = None
    generated_at: datetime | None = None
    error_message: str | None = None
