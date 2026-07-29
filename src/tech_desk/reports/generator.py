from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta

from tech_desk.config import ReportPeriod, get_settings, list_desk_definitions, load_desk_config, resolve_desks
from tech_desk.database import ReportORM, UpdateORM, get_session_factory, init_db, json_to_tags
from tech_desk.export.renderer import ReportRenderer
from tech_desk.llm import LLMClient
from tech_desk.models import (
    CuratedUpdate,
    DeskReportSection,
    GeneratedReport,
    RelevanceLevel,
    TechDeskDefinition,
    UpdateCategory,
)
from tech_desk.reports.vendor_intel import VendorIntelBuilder
from tech_desk.research.images import resolve_update_image
from tech_desk.timeutils import now_utc

logger = logging.getLogger(__name__)

REPORT_SYSTEM_PROMPT = """You are the lead author of Cotiviti's Technology Desk intelligence reports.
Write for C-suite and senior technology leadership at Cotiviti, a healthcare technology and analytics company.
Be precise, concise, and actionable. Lead with vendor names and concrete moves.
Connect activity to Cotiviti's payer analytics, payment integrity, and healthcare AI mission."""


def _period_bounds(period: ReportPeriod, end: datetime | None = None) -> tuple[datetime, datetime]:
    end = end or now_utc()
    if period == "daily":
        start = end - timedelta(days=1)
    elif period == "weekly":
        start = end - timedelta(days=7)
    else:
        start = end - relativedelta(months=1)
    return start, end


def _orm_to_update(orm: UpdateORM) -> CuratedUpdate:
    image_url = getattr(orm, "image_url", "") or ""
    settings = get_settings()
    if settings.image_fetch_enabled and not image_url:
        image_url = resolve_update_image(
            orm.source_url,
            getattr(orm, "vendor", "") or "",
            existing_image=image_url,
        ) or ""
    return CuratedUpdate(
        desk_id=orm.desk_id,
        title=orm.title,
        summary=orm.summary,
        source_url=orm.source_url,
        source_name=orm.source_name,
        published_date=orm.published_date,
        discovered_at=orm.discovered_at,
        category=UpdateCategory(orm.category),
        relevance=RelevanceLevel(orm.relevance),
        tags=json_to_tags(orm.tags_json),
        key_takeaways=json_to_tags(orm.key_takeaways_json),
        stakeholder_impact=orm.stakeholder_impact,
        raw_snippet=orm.raw_snippet,
        vendor=getattr(orm, "vendor", "") or "",
        image_url=image_url,
    )


class ReportGenerator:
    def __init__(self, llm: LLMClient | None = None):
        self.llm = llm or LLMClient()
        self.settings = get_settings()
        self.renderer = ReportRenderer()
        self.vendor_builder = VendorIntelBuilder(self.llm)

    def generate(
        self,
        period: ReportPeriod,
        *,
        end_date: datetime | None = None,
        desk_keys: list[str] | None = None,
    ) -> GeneratedReport:
        init_db()
        session = get_session_factory()()
        config = load_desk_config()
        reporting_cfg = config.get("reporting", {}).get(period, {})
        max_per_desk = reporting_cfg.get("max_items_per_desk", 20)

        desks = resolve_desks(desk_keys)
        period_start, period_end = _period_bounds(period, end_date)
        title = self._report_title(period, period_start, period_end, desks)
        sections: list[DeskReportSection] = []

        try:
            for desk in desks:
                updates_orm = (
                    session.query(UpdateORM)
                    .filter(
                        UpdateORM.desk_id == desk.id,
                        UpdateORM.discovered_at >= period_start,
                        UpdateORM.discovered_at <= period_end,
                    )
                    .order_by(UpdateORM.relevance.desc(), UpdateORM.discovered_at.desc())
                    .limit(max_per_desk)
                    .all()
                )
                updates = [_orm_to_update(u) for u in updates_orm]
                section = self._build_desk_section(desk, updates, period, reporting_cfg)
                sections.append(section)

            executive_summary = self._build_executive_summary(period, sections, reporting_cfg, desks)

            report = GeneratedReport(
                id=str(uuid.uuid4()),
                period=period,
                title=title,
                period_start=period_start,
                period_end=period_end,
                executive_summary=executive_summary,
                sections=sections,
                metadata={
                    "organization": config.get("organization", "Cotiviti"),
                    "total_updates": sum(len(s.updates) for s in sections),
                    "priority_desks": [s.desk_code for s in sections if s.priority],
                    "desk_ids": [d.id for d in desks],
                    "desk_codes": [d.code for d in desks],
                    "scoped": bool(desk_keys),
                },
            )

            paths = self.renderer.render_all(report)
            orm = ReportORM(
                period=period,
                title=title,
                period_start=period_start,
                period_end=period_end,
                executive_summary=executive_summary,
                content_json=report.model_dump_json(),
                html_path=str(paths.get("html", "")),
                markdown_path=str(paths.get("markdown", "")),
                pdf_path=str(paths.get("pdf")) if paths.get("pdf") else None,
            )
            session.add(orm)
            session.commit()
            report.id = str(orm.id)
            return report

        finally:
            session.close()

    def _report_title(
        self,
        period: ReportPeriod,
        start: datetime,
        end: datetime,
        desks: list[TechDeskDefinition],
    ) -> str:
        labels = {"daily": "Daily Brief", "weekly": "Weekly Intelligence", "monthly": "Monthly Technology Desk Report"}
        date_range = f"{start.strftime('%b %d')} to {end.strftime('%b %d, %Y')}"
        if len(desks) == 1:
            return f"{desks[0].name} — {labels[period]} — {date_range}"
        if len(desks) < len(list_desk_definitions()):
            codes = ", ".join(d.code for d in desks)
            return f"Gen AI {labels[period]} ({codes}) — {date_range}"
        return f"Gen AI {labels[period]} — {date_range}"

    def _build_desk_section(
        self,
        desk: TechDeskDefinition,
        updates: list[CuratedUpdate],
        period: ReportPeriod,
        cfg: dict,
    ) -> DeskReportSection:
        section = DeskReportSection(
            desk_id=desk.id,
            desk_name=desk.name,
            desk_code=desk.code,
            priority=desk.priority,
            updates=updates,
        )

        if not updates:
            section.executive_summary = f"No significant {period} developments for {desk.name}."
            if desk.key_vendors and not cfg.get("only_active_vendors", period == "daily"):
                section.vendor_sections = self.vendor_builder.build_vendor_sections(
                    desk, [], max_per_vendor=cfg.get("max_items_per_vendor", 5),
                    period=period, only_active_vendors=cfg.get("only_active_vendors", period == "daily"),
                )
            return section

        # Build vendor-centric intelligence sections
        max_per_vendor = cfg.get("max_items_per_vendor", 8)
        only_active = cfg.get("only_active_vendors", period == "daily")
        vendor_sections = self.vendor_builder.build_vendor_sections(
            desk, updates, max_per_vendor=max_per_vendor, period=period,
            only_active_vendors=only_active,
        )
        section.vendor_sections = vendor_sections

        vendor_digest = "\n".join(
            f"- {vs.vendor} ({vs.activity_level}): {vs.trend_summary}" for vs in vendor_sections if vs.trend_summary
        )
        updates_text = self._format_updates_for_llm(updates)
        vendors_list = ", ".join(desk.key_vendors) if desk.key_vendors else "N/A"

        prompt = self._desk_section_prompt(desk, period, vendor_digest, updates_text, vendors_list, len(updates), cfg)

        include_trends = cfg.get("include_trend_analysis", period == "monthly")
        include_recs = cfg.get("include_recommendations", period != "daily")
        max_tokens = cfg.get("max_llm_tokens", 800 if period == "daily" else 3000)
        try:
            data = self.llm.chat_json(REPORT_SYSTEM_PROMPT, prompt, temperature=0.4, max_tokens=max_tokens)
            section.executive_summary = data.get("executive_summary", "")
            section.highlights = data.get("highlights", [])[: cfg.get("max_highlights", 5)]
            if include_trends:
                section.trend_analysis = data.get("trend_analysis", "")
                section.vendor_landscape = data.get("vendor_landscape", "")
            if include_recs:
                section.recommendations = data.get("recommendations", [])
            section.sub_area_coverage = data.get("sub_area_coverage", {}) if period != "daily" else {}
        except Exception as exc:
            logger.warning("LLM section generation failed for %s: %s", desk.name, exc)
            section.executive_summary = f"{len(updates)} updates collected for {desk.name}."
            section.highlights = [u.title for u in updates[: cfg.get("max_highlights", 3)]]

        return section

    def _desk_section_prompt(
        self,
        desk: TechDeskDefinition,
        period: ReportPeriod,
        vendor_digest: str,
        updates_text: str,
        vendors_list: str,
        update_count: int,
        cfg: dict,
    ) -> str:
        if period == "daily":
            max_highlights = cfg.get("max_highlights", 3)
            return f"""Generate a concise DAILY BRIEF section for Cotiviti's "{desk.name}" tech desk.
Keep it scannable — leadership reads this in under 2 minutes.

Desk focus: {desk.description}
Key vendors: {vendors_list}

Vendor snapshot:
{vendor_digest}

Updates ({update_count}):
{updates_text}

Respond in JSON:
{{
  "executive_summary": "1-2 sentences — name the 1-2 most active vendors and why they matter to Cotiviti",
  "highlights": ["{max_highlights} short bullet highlights, each naming a vendor and the key move"],
  "trend_analysis": "",
  "vendor_landscape": "",
  "recommendations": [],
  "sub_area_coverage": {{}}
}}"""

        if period == "weekly":
            return f"""Generate a weekly intelligence section for Cotiviti's "{desk.name}" tech desk.

Desk focus: {desk.description}
Key vendors: {vendors_list}

Vendor snapshot:
{vendor_digest}

Updates ({update_count}):
{updates_text}

Respond in JSON:
{{
  "executive_summary": "2-3 sentence vendor-focused overview",
  "highlights": ["top 4 vendor-specific highlights"],
  "trend_analysis": "",
  "vendor_landscape": "",
  "recommendations": ["1-2 Cotiviti-specific recommendations"],
  "sub_area_coverage": {{}}
}}"""

        return f"""Generate a monthly VENDOR-CENTRIC intelligence section for Cotiviti's "{desk.name}" tech desk.

Desk focus: {desk.description}
Areas: {', '.join(desk.areas)}
Key vendors: {vendors_list}

Vendor snapshot:
{vendor_digest}

Updates ({update_count}):
{updates_text}

Respond in JSON:
{{
  "executive_summary": "3-4 sentence vendor-focused overview",
  "highlights": ["top 5 vendor-specific highlights"],
  "trend_analysis": "paragraph on cross-vendor trends",
  "vendor_landscape": "paragraph comparing vendor positions",
  "recommendations": ["2-4 Cotiviti-specific recommendations"],
  "sub_area_coverage": {{"area_name": ["brief vendor note"]}}
}}"""

    def _build_executive_summary(
        self,
        period: ReportPeriod,
        sections: list[DeskReportSection],
        cfg: dict,
        desks: list[TechDeskDefinition],
    ) -> str:
        if not cfg.get("include_executive_summary", True):
            return ""

        focus_sections = sections
        if len(desks) > 1:
            priority_sections = [s for s in sections if s.priority]
            focus_sections = priority_sections if priority_sections else sections

        digest = "\n".join(
            f"- {s.desk_name}: {s.executive_summary or 'No updates'}" for s in focus_sections
        )

        if len(desks) == 1:
            sentences = "2-3 sentences" if period == "daily" else "4-6 sentences"
            prompt = f"""Write a {period} executive summary ({sentences}) for Cotiviti leadership on the "{desks[0].name}" desk.
Focus on what matters for Cotiviti's healthcare analytics mission.

Desk summary:
{digest}

Write only the paragraph, no JSON."""
        else:
            sentences = "2-3 sentences" if period == "daily" else "4-6 sentences"
            prompt = f"""Write a {period} executive summary ({sentences}) for Cotiviti leadership.
Lead with the most strategically significant vendor developments.

Desk summaries:
{digest}

Write only the paragraph, no JSON."""

        try:
            return self.llm.chat(REPORT_SYSTEM_PROMPT, prompt, temperature=0.4, max_tokens=800)
        except Exception:
            return digest

    def _format_updates_for_llm(self, updates: list[CuratedUpdate]) -> str:
        lines = []
        for i, u in enumerate(updates, 1):
            takeaways = "; ".join(u.key_takeaways) if u.key_takeaways else "N/A"
            lines.append(
                f"{i}. [{u.relevance.value.upper()}] {u.title}\n"
                f"   Vendor: {u.vendor or 'Unknown'}\n"
                f"   Date: {u.published_date or u.discovered_at}\n"
                f"   Source: {u.source_url}\n"
                f"   Summary: {u.summary}\n"
                f"   Impact: {u.stakeholder_impact}\n"
                f"   Takeaways: {takeaways}"
            )
        return "\n\n".join(lines)
