from __future__ import annotations

import logging

from tech_desk.llm import LLMClient
from tech_desk.models import (
    CuratedUpdate,
    RelevanceLevel,
    ResearchResult,
    TechDeskDefinition,
    UpdateCategory,
)
from dateutil import parser as date_parser

logger = logging.getLogger(__name__)

ANALYSIS_SYSTEM_PROMPT = """You are a senior technology analyst at Cotiviti, a healthcare technology and analytics company,
producing a technical prospecting report — a curated feed of concrete vendor developments for
enterprise stakeholders, not a general web digest. Be selective and concise.

Judge relevance against the desk's focus areas below — NOT against any vendor list. This
desk's "tracked vendors" are just vendors already being watched; they are not an allow-list.
Genuinely new or emerging vendors, startups, and market entrants relevant to the focus areas
are just as relevant as tracked ones, and should be surfaced under their own vendor name so
they can be picked up for tracking too. Only mark relevant if it represents meaningful vendor
developments: product launches, partnerships, funding, research, regulations, or major vendor moves.

STRICT quality bar — set "specific_event": false (even if otherwise topically relevant) for:
- Generic "market trends", "industry forecast/report", or "X in <year>" pieces with no
  specific vendor action tied to one real, dateable event.
- SEO listicles / buyer's guides ("Top N tools", "Best X for Y", "How to choose a...") and
  pricing/comparison round-ups written as evergreen marketing content rather than news of an
  actual vendor price or plan CHANGE.
- Vendor marketing/landing pages restating existing product capabilities with no new
  announcement.
- Opinion/analyst commentary with no concrete, attributable vendor action.
Only set "specific_event": true for content describing one specific, attributable event: a
launch, release, partnership, acquisition, funding round, executive/regulatory decision,
outage/incident, or a concrete pricing/product change — something you could put a date on and
name the actor(s) of.

Respond in JSON:
{
  "relevant": true/false,
  "specific_event": true/false,
  "title": "refined title (max 12 words)",
  "summary": "1 sentence summary — direct and factual (the WHAT/description)",
  "vendor": "primary vendor name or Other",
  "category": "product_launch|partnership|funding|research|regulation|event|trend|vendor_move|other",
  "relevance": "high|medium|low",
  "tags": ["tag1"],
  "key_takeaways": ["one short takeaway"],
  "stakeholder_impact": "one sentence on WHY this matters to Cotiviti leadership",
  "who_is_affected_first": "short phrase naming the Cotiviti team/function/client segment affected first (e.g. 'Payment integrity analysts', 'HCLS clients on legacy EHR integrations')",
  "published_date": "YYYY-MM-DD or null if unknown"
}"""


class UpdateAnalyzer:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def analyze_result(
        self,
        desk: TechDeskDefinition,
        result: ResearchResult,
        *,
        vendor_notes: str = "",
        custom_instructions: str = "",
    ) -> CuratedUpdate | None:
        areas_text = ", ".join(desk.areas)
        sub_areas_text = ""
        if desk.sub_areas:
            parts = [f"{k}: {', '.join(v)}" for k, v in desk.sub_areas.items()]
            sub_areas_text = "\nSub-areas: " + "; ".join(parts)

        vendors_text = ", ".join(desk.key_vendors) if desk.key_vendors else "N/A"
        hint_vendor = result.target_vendor or "unknown"
        notes_block = f"\nAnalyst notes on {hint_vendor} (context only, not a relevance filter):\n{vendor_notes}\n" if vendor_notes else ""
        instructions_block = f"\nAdditional guidance for this run: {custom_instructions}\n" if custom_instructions else ""
        user_prompt = f"""Tech Desk: {desk.name} ({desk.code})
Description: {desk.description}
Focus areas: {areas_text}{sub_areas_text}
Vendors already tracked on this desk (for reference only — not exhaustive, not a filter): {vendors_text}
Search target vendor (if any): {hint_vendor}
{notes_block}{instructions_block}
Evaluate this search result:
Title: {result.title}
URL: {result.url}
Source: {result.source_domain}
Published: {result.published_date or 'unknown'}
Snippet: {result.snippet}
"""

        try:
            data = self.llm.chat_json(ANALYSIS_SYSTEM_PROMPT, user_prompt, temperature=0.2, max_tokens=1024)
        except Exception as exc:
            logger.warning("LLM analysis failed for %s: %s", result.url, exc)
            return None

        if not data.get("relevant", False):
            return None

        # Quality gate: reject generic/evergreen "trends", buyer's-guide, or
        # marketing content even when the LLM judged it topically relevant —
        # a technical prospecting report should only surface concrete,
        # attributable vendor events. Default True (permissive) if the model
        # omits the field, since "relevant" is still the primary gate.
        if not data.get("specific_event", True):
            logger.info(
                "Discarding non-specific/evergreen result for %s: %s", desk.name, result.title
            )
            return None

        title = (data.get("title") or result.title or "").strip()
        summary = (data.get("summary") or "").strip()
        if not title or not summary:
            logger.info("Discarding incomplete analysis for %s (missing title/summary)", result.url)
            return None

        category_str = data.get("category", "other")
        try:
            category = UpdateCategory(category_str)
        except ValueError:
            category = UpdateCategory.OTHER

        relevance_str = data.get("relevance", "medium")
        try:
            relevance = RelevanceLevel(relevance_str)
        except ValueError:
            relevance = RelevanceLevel.MEDIUM

        pub_date = None
        raw_date = data.get("published_date") or result.published_date
        if raw_date:
            try:
                pub_date = date_parser.parse(str(raw_date))
            except (ValueError, TypeError):
                pass

        vendor = data.get("vendor") or result.target_vendor or ""
        if vendor.lower() == "other":
            vendor = result.target_vendor or "Other"

        return CuratedUpdate(
            desk_id=desk.id,
            title=title,
            summary=summary,
            source_url=result.url,
            source_name=result.source_domain,
            vendor=vendor,
            published_date=pub_date,
            category=category,
            relevance=relevance,
            tags=data.get("tags", []),
            key_takeaways=data.get("key_takeaways", [])[:1],
            stakeholder_impact=data.get("stakeholder_impact", ""),
            who_is_affected_first=data.get("who_is_affected_first", ""),
            raw_snippet=result.snippet,
            image_url=result.image_url or "",
        )
