from __future__ import annotations

import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from tech_desk.config import get_settings
from tech_desk.models import GeneratedReport

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


class ReportRenderer:
    def __init__(self):
        self.settings = get_settings()
        self.env = Environment(
            loader=FileSystemLoader(str(TEMPLATES_DIR)),
            autoescape=select_autoescape(["html", "xml"]),
        )

    def render_all(self, report: GeneratedReport) -> dict[str, Path]:
        stamp = report.generated_at.strftime("%Y%m%d_%H%M%S")
        desk_suffix = ""
        codes = report.metadata.get("desk_codes") or []
        if report.metadata.get("scoped") and codes:
            desk_suffix = "_" + "_".join(codes)
        base_name = f"{report.period}{desk_suffix}_{stamp}"
        out_dir = self.settings.tech_desk_data_dir / "reports" / report.period
        out_dir.mkdir(parents=True, exist_ok=True)

        paths: dict[str, Path] = {}

        md_path = out_dir / f"{base_name}.md"
        md_content = self.render_markdown(report)
        md_path.write_text(md_content, encoding="utf-8")
        paths["markdown"] = md_path

        html_path = out_dir / f"{base_name}.html"
        html_content = self.render_html(report)
        html_path.write_text(html_content, encoding="utf-8")
        paths["html"] = html_path

        try:
            pdf_path = out_dir / f"{base_name}.pdf"
            self.render_pdf(html_content, pdf_path)
            paths["pdf"] = pdf_path
        except Exception as exc:
            logger.warning("PDF generation skipped: %s", exc)

        return paths

    def render_markdown(self, report: GeneratedReport) -> str:
        compact = report.period == "daily"
        lines = [
            f"# {report.title}",
            "",
            f"**Cotiviti Technology Desk** · {report.period.title()} · "
            f"{report.period_start.strftime('%b %d')} — {report.period_end.strftime('%b %d, %Y')}",
            "",
            "---",
            "",
        ]

        if report.executive_summary:
            lines.extend(["## Executive Summary", "", report.executive_summary, "", "---", ""])

        for section in report.sections:
            priority_badge = " ⭐" if section.priority else ""
            lines.extend([
                f"## {section.desk_name} ({section.desk_code}){priority_badge}",
                "",
            ])
            if section.executive_summary:
                lines.append(section.executive_summary)
                lines.append("")

            if section.highlights:
                lines.append("### Highlights")
                for h in section.highlights:
                    lines.append(f"- {h}")
                lines.append("")

            if section.vendor_sections:
                for vs in section.vendor_sections:
                    if vs.activity_level == "none" and not vs.updates:
                        continue
                    activity = vs.activity_level.upper()
                    img = f" ![{vs.vendor}]({vs.image_url})" if vs.image_url else ""
                    lines.extend([f"### {vs.vendor} `{activity}`{img}", ""])
                    if vs.trend_summary:
                        lines.extend([vs.trend_summary, ""])
                    if vs.strategic_position and not compact:
                        lines.extend([f"**Position:** {vs.strategic_position}", ""])
                    if vs.latest_moves:
                        for m in vs.latest_moves:
                            lines.append(f"- {m}")
                        lines.append("")
                    if vs.updates:
                        for u in vs.updates:
                            date_str = (u.published_date or u.discovered_at).strftime("%Y-%m-%d")
                            img_md = f"![thumb]({u.image_url}) " if u.image_url else ""
                            lines.append(
                                f"- {img_md}[{u.title}]({u.source_url}) — {date_str} — {u.summary}"
                            )
                        lines.append("")
                    if vs.cotiviti_relevance and not compact:
                        lines.extend([f"**Cotiviti:** {vs.cotiviti_relevance}", ""])

            elif section.updates:
                for u in section.updates:
                    date_str = (u.published_date or u.discovered_at).strftime("%Y-%m-%d")
                    if u.image_url:
                        lines.append(f"![{u.title}]({u.image_url})")
                    lines.extend([
                        f"#### {u.title}",
                        f"- {date_str} · [{u.source_name or 'Source'}]({u.source_url})",
                        f"- {u.summary}",
                        "",
                    ])

            if section.trend_analysis:
                lines.extend(["### Trend Analysis", "", section.trend_analysis, ""])
            if section.vendor_landscape:
                lines.extend(["### Vendor Landscape", "", section.vendor_landscape, ""])
            if section.recommendations:
                lines.append("### Recommendations")
                for r in section.recommendations:
                    lines.append(f"- {r}")
                lines.append("")

            lines.extend(["---", ""])

        lines.append("*Confidential — Cotiviti Technology Desk Intelligence*")
        return "\n".join(lines)

    def render_html(self, report: GeneratedReport) -> str:
        template = self.env.get_template("report.html")
        return template.render(report=report, generated_at=report.generated_at)

    def render_pdf(self, html_content: str, output_path: Path) -> None:
        from weasyprint import HTML

        HTML(string=html_content).write_pdf(str(output_path))
