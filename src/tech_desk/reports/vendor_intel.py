from __future__ import annotations

import logging
import re

from tech_desk.llm import LLMClient
from tech_desk.models import CuratedUpdate, TechDeskDefinition, VendorIntelSection
from tech_desk.research.images import resolve_update_image, resolve_vendor_image

logger = logging.getLogger(__name__)

VENDOR_INTEL_PROMPT = """You are a vendor intelligence analyst for Cotiviti's Technology Desk.
Write concise, evidence-based vendor intelligence for healthcare technology leadership.
Be specific about product names and partnerships. Reference only provided evidence."""


def _normalize_vendor(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def _match_vendor(update_vendor: str, tracked: list[str]) -> str | None:
    if not update_vendor or update_vendor.lower() == "other":
        return None
    norm = _normalize_vendor(update_vendor)
    for vendor in tracked:
        vnorm = _normalize_vendor(vendor)
        if norm == vnorm or vnorm in norm or norm in vnorm:
            return vendor
    return update_vendor


def group_updates_by_vendor(
    updates: list[CuratedUpdate],
    tracked_vendors: list[str],
) -> dict[str, list[CuratedUpdate]]:
    grouped: dict[str, list[CuratedUpdate]] = {v: [] for v in tracked_vendors}
    other: list[CuratedUpdate] = []

    for update in updates:
        matched = _match_vendor(update.vendor, tracked_vendors)
        if matched and matched in grouped:
            grouped[matched].append(update)
        elif matched:
            grouped.setdefault(matched, []).append(update)
        else:
            other.append(update)

    if other:
        grouped["Other Vendors"] = other

    return grouped


def _format_vendor_updates(updates: list[CuratedUpdate]) -> str:
    if not updates:
        return "No curated updates for this vendor in the reporting period."
    lines = []
    for i, u in enumerate(updates, 1):
        lines.append(
            f"{i}. [{u.relevance.value.upper()}] {u.title}\n"
            f"   Date: {u.published_date or u.discovered_at}\n"
            f"   Source: {u.source_url}\n"
            f"   Summary: {u.summary}"
        )
    return "\n\n".join(lines)


def _enrich_update_images(updates: list[CuratedUpdate]) -> list[CuratedUpdate]:
    from tech_desk.config import get_settings

    if not get_settings().image_fetch_enabled:
        return updates
    enriched: list[CuratedUpdate] = []
    for u in updates:
        if u.image_url:
            enriched.append(u)
            continue
        image = resolve_update_image(u.source_url, u.vendor, existing_image=u.image_url)
        if image:
            enriched.append(u.model_copy(update={"image_url": image}))
        else:
            enriched.append(u)
    return enriched


def _period_prompts(period: str) -> dict:
    if period == "daily":
        return {
            "json_schema": """{
  "activity_level": "high|moderate|low",
  "trend_summary": "1 sentence on this vendor's momentum",
  "latest_moves": ["2-3 short bullet points of recent moves"],
  "cotiviti_relevance": "1 sentence on Cotiviti implications (optional, empty string if low impact)"
}""",
            "max_tokens": 500,
            "include_strategic": False,
            "include_watch": False,
        }
    if period == "weekly":
        return {
            "json_schema": """{
  "activity_level": "high|moderate|low",
  "trend_summary": "1-2 sentences on vendor trajectory",
  "strategic_position": "1 sentence on competitive positioning",
  "latest_moves": ["2-4 bullet points"],
  "watch_items": ["1-2 items to monitor"],
  "cotiviti_relevance": "1 sentence on Cotiviti implications"
}""",
            "max_tokens": 800,
            "include_strategic": True,
            "include_watch": True,
        }
    return {
        "json_schema": """{
  "activity_level": "high|moderate|low",
  "trend_summary": "2-3 sentences on vendor trajectory and momentum",
  "strategic_position": "2 sentences on competitive positioning vs peers",
  "latest_moves": ["3-5 specific bullet points"],
  "watch_items": ["2-3 items to monitor next period"],
  "cotiviti_relevance": "1-2 sentences on Cotiviti healthcare analytics implications"
}""",
        "max_tokens": 1200,
        "include_strategic": True,
        "include_watch": True,
    }


class VendorIntelBuilder:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def build_vendor_sections(
        self,
        desk: TechDeskDefinition,
        updates: list[CuratedUpdate],
        *,
        max_per_vendor: int = 8,
        period: str = "monthly",
        only_active_vendors: bool = False,
    ) -> list[VendorIntelSection]:
        tracked = desk.key_vendors or []
        if not tracked:
            return []

        updates = _enrich_update_images(updates)
        grouped = group_updates_by_vendor(updates, tracked)
        sections: list[VendorIntelSection] = []

        for vendor in tracked:
            vendor_updates = grouped.get(vendor, [])[:max_per_vendor]
            if only_active_vendors and not vendor_updates:
                continue
            section = self._build_single_vendor_section(
                desk, vendor, vendor_updates, period=period
            )
            sections.append(section)

        if grouped.get("Other Vendors"):
            other_updates = grouped["Other Vendors"][:max_per_vendor]
            if not only_active_vendors or other_updates:
                sections.append(
                    self._build_single_vendor_section(
                        desk,
                        "Other Vendors",
                        other_updates,
                        period=period,
                    )
                )

        return sections

    def _build_single_vendor_section(
        self,
        desk: TechDeskDefinition,
        vendor: str,
        updates: list[CuratedUpdate],
        *,
        period: str,
    ) -> VendorIntelSection:
        image_url = ""
        from tech_desk.config import get_settings
        if get_settings().image_fetch_enabled:
            image_url = resolve_vendor_image(vendor) or ""
            if updates and not image_url:
                image_url = next((u.image_url for u in updates if u.image_url), "")

        if not updates:
            if period == "daily":
                return VendorIntelSection(
                    vendor=vendor,
                    activity_level="none",
                    image_url=image_url,
                    trend_summary="",
                )
            return VendorIntelSection(
                vendor=vendor,
                activity_level="none",
                image_url=image_url,
                trend_summary=f"No significant {period} activity for {vendor}.",
                watch_items=[f"Monitor {vendor} product and partnership announcements."],
            )

        prompts = _period_prompts(period)
        updates_text = _format_vendor_updates(updates)
        prompt = f"""Generate vendor intelligence for "{vendor}" in the "{desk.name}" desk ({period} report).

Evidence ({len(updates)} updates):
{updates_text}

Respond in JSON:
{prompts["json_schema"]}"""

        try:
            data = self.llm.chat_json(
                VENDOR_INTEL_PROMPT, prompt, temperature=0.35, max_tokens=prompts["max_tokens"]
            )
            return VendorIntelSection(
                vendor=vendor,
                activity_level=data.get("activity_level", "moderate"),
                image_url=image_url,
                trend_summary=data.get("trend_summary", ""),
                strategic_position=data.get("strategic_position", "") if prompts["include_strategic"] else "",
                latest_moves=data.get("latest_moves", []),
                updates=updates,
                watch_items=data.get("watch_items", []) if prompts["include_watch"] else [],
                cotiviti_relevance=data.get("cotiviti_relevance", ""),
            )
        except Exception as exc:
            logger.warning("Vendor intel failed for %s/%s: %s", desk.code, vendor, exc)
            return VendorIntelSection(
                vendor=vendor,
                activity_level="moderate",
                image_url=image_url,
                trend_summary=f"{len(updates)} updates for {vendor}.",
                latest_moves=[u.title for u in updates[:3]],
                updates=updates,
            )
