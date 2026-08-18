from __future__ import annotations

from typing import Any, Callable

import logging

from tech_desk.config import ReportPeriod
from tech_desk.llm import LLMClient
from tech_desk.reports.generator import ReportGenerator
from tech_desk.research.collector import ResearchCollector

logger = logging.getLogger(__name__)


def _record_token_usage(period: str, desk_count: int, llm: LLMClient) -> None:
    """Persist measured token usage so cost projections calibrate to real runs."""
    try:
        from tech_desk.database import record_token_sample

        usage = getattr(llm, "usage", None) or {}
        record_token_sample(
            period,
            max(1, desk_count or 1),
            int(usage.get("input", 0)),
            int(usage.get("output", 0)),
        )
    except Exception as exc:  # never fail a pipeline over telemetry
        logger.debug("Token usage recording skipped: %s", exc)


def run_research_job(
    period: ReportPeriod,
    desk_keys: list[str] | None,
    *,
    custom_instructions: str | None = None,
    progress: Callable[[str, int], None] | None = None,
) -> dict[str, Any]:
    def _p(msg: str, pct: int) -> None:
        if progress:
            progress(msg, pct)

    _p("Initializing research...", 5)
    llm = LLMClient()
    try:
        collector = ResearchCollector(llm=llm)
        _p("Searching web and curating updates...", 15)
        run = collector.run(period=period, desk_keys=desk_keys, custom_instructions=custom_instructions)
        _p("Research complete", 100)
        return {
            "run_id": run.id,
            "status": run.status,
            "desks_processed": run.desks_processed,
            "updates_found": run.updates_found,
            "vendors_added": run.vendors_added,
        }
    finally:
        llm.close()


def run_report_job(
    period: ReportPeriod,
    desk_keys: list[str] | None,
    *,
    custom_instructions: str | None = None,
    progress: Callable[[str, int], None] | None = None,
) -> dict[str, Any]:
    def _p(msg: str, pct: int) -> None:
        if progress:
            progress(msg, pct)

    _p("Generating report...", 10)
    llm = LLMClient()
    try:
        generator = ReportGenerator(llm=llm)
        _p("Synthesizing vendor intelligence...", 30)
        report = generator.generate(period=period, desk_keys=desk_keys, custom_instructions=custom_instructions)
        _p("Report ready", 100)
        return {
            "report_id": report.id,
            "title": report.title,
            "period": report.period,
            "total_updates": report.metadata.get("total_updates", 0),
            "desk_codes": report.metadata.get("desk_codes"),
        }
    finally:
        llm.close()


def run_pipeline_job(
    period: ReportPeriod,
    desk_keys: list[str] | None,
    *,
    custom_instructions: str | None = None,
    progress: Callable[[str, int], None] | None = None,
) -> dict[str, Any]:
    def _p(msg: str, pct: int) -> None:
        if progress:
            progress(msg, pct)

    _p("Starting pipeline...", 2)
    llm = LLMClient()
    try:
        collector = ResearchCollector(llm=llm)
        _p("Phase 1/2: Web research & AI curation...", 10)
        run = collector.run(period=period, desk_keys=desk_keys, custom_instructions=custom_instructions)
        research = {
            "run_id": run.id,
            "updates_found": run.updates_found,
            "desks_processed": run.desks_processed,
            "status": run.status,
        }
        _p(f"Found {research['updates_found']} updates — generating report...", 55)
        generator = ReportGenerator(llm=llm)
        report = generator.generate(period=period, desk_keys=desk_keys, custom_instructions=custom_instructions)
        _record_token_usage(period, run.desks_processed, llm)
        _p("Pipeline complete", 100)
        return {
            "research": research,
            "report": {
                "report_id": report.id,
                "title": report.title,
                "total_updates": report.metadata.get("total_updates", 0),
                "desk_codes": report.metadata.get("desk_codes"),
            },
        }
    finally:
        llm.close()


def run_position_paper_job(
    vendor_name: str,
    *,
    custom_prompt: str = "",
    progress: Callable[[str, int], None] | None = None,
) -> dict[str, Any]:
    from tech_desk.reports.position_paper import PositionPaperGenerator

    def _p(msg: str, pct: int) -> None:
        if progress:
            progress(msg, pct)

    llm = LLMClient()
    try:
        gen = PositionPaperGenerator(llm=llm)
        result = gen.generate(vendor_name, custom_prompt=custom_prompt, progress=_p)
        return {
            "position_paper_id": result.id,
            "vendor": result.vendor,
            "status": result.status,
            "docx_path": result.docx_path,
        }
    finally:
        llm.close()
