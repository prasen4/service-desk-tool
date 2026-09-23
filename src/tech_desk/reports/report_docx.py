"""Renders a generated Technology Desk Report as a Cotiviti-branded .docx,
using the exact same cover-page/header/footer/table chrome as Position
Papers (see docx_theme.py) so both document types read as the same family
of stakeholder deliverable.
"""

from __future__ import annotations

from pathlib import Path

from tech_desk.config import get_settings
from tech_desk.models import GeneratedReport
from tech_desk.reports import docx_theme as theme
from tech_desk.timeutils import now_utc


def _slugify(text: str) -> str:
    import re

    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "report"


def render_report_docx(
    report: GeneratedReport,
    *,
    desk_label: str,
    report_type_label: str,
    date_range: str,
) -> Path:
    settings = get_settings()
    out_dir = settings.tech_desk_data_dir / "exports" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = now_utc().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"{_slugify(desk_label)}_{report.period}_{stamp}.docx"

    doc = theme.new_branded_document(
        title=report_type_label,
        subtitle=desk_label,
        prepared_for="Prepared for: Cotiviti Technology Leadership",
        delivery_label="Reporting Period",
        delivery_value=date_range,
        date_line=now_utc().strftime("Prepared %B %d, %Y"),
    )

    theme.add_heading(doc, "Executive Summary")
    if report.executive_summary_sections:
        es = report.executive_summary_sections
        if es.overview:
            theme.add_heading(doc, "High-Level Overview", level=2)
            theme.add_body(doc, es.overview)
        if es.clearest_signal:
            theme.add_heading(doc, "Clearest Signal for Cotiviti", level=2)
            theme.add_body(doc, es.clearest_signal)
        if es.implications:
            theme.add_heading(doc, "Implications for Cotiviti", level=2)
            theme.add_body(doc, es.implications)
        if es.vendors_mentioned:
            theme.add_heading(doc, "Vendors Mentioned", level=2)
            theme.add_body(doc, ", ".join(es.vendors_mentioned))
        if not any([es.overview, es.clearest_signal, es.implications]):
            theme.add_body(doc, "", empty_text="No significant developments this period.")
    else:
        theme.add_body(doc, report.executive_summary, empty_text="No significant developments this period.")

    for section in report.sections:
        heading = f"{section.desk_name} (Priority Desk)" if section.priority else section.desk_name
        theme.add_heading(doc, heading)
        theme.add_body(doc, section.executive_summary, empty_text="No significant developments this period.")

        if section.highlights:
            theme.add_heading(doc, "Highlights", level=2)
            theme.add_bullets(doc, section.highlights)

        if section.vendor_sections:
            theme.add_heading(doc, "Vendor Intelligence", level=2)
            for vs in section.vendor_sections:
                p = doc.add_paragraph()
                p.add_run(vs.vendor + " ").bold = True
                p.add_run(f"({vs.activity_level} activity)").italic = True
                if vs.trend_summary:
                    doc.add_paragraph(vs.trend_summary)
                if vs.strategic_position:
                    doc.add_paragraph(f"Strategic position: {vs.strategic_position}")
                if vs.latest_moves:
                    theme.add_bullets(doc, vs.latest_moves)
                if vs.cotiviti_relevance:
                    doc.add_paragraph(f"Cotiviti relevance: {vs.cotiviti_relevance}")

        if section.trend_analysis:
            theme.add_heading(doc, "Trend Analysis", level=2)
            theme.add_body(doc, section.trend_analysis)

        if section.vendor_landscape:
            theme.add_heading(doc, "Vendor Landscape", level=2)
            theme.add_body(doc, section.vendor_landscape)

        if section.recommendations:
            theme.add_heading(doc, "Recommendations", level=2)
            theme.add_bullets(doc, section.recommendations)

        if section.updates:
            theme.add_heading(doc, "Source Updates", level=2)
            table = doc.add_table(rows=1, cols=3)
            table.autofit = True
            headers = ["Update", "Source", "Relevance"]
            for i, htext in enumerate(headers):
                theme.set_cell(table.rows[0].cells[i], htext, header=True)
            for update in section.updates:
                row = table.add_row()
                theme.set_cell(row.cells[0], update.title)
                theme.set_cell(row.cells[1], update.source_name or update.source_url)
                theme.set_cell(row.cells[2], update.relevance.value.title())

    doc.save(str(out_path))
    return out_path
