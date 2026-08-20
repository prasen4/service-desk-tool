from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import timedelta
from difflib import SequenceMatcher

from sqlalchemy.orm import Session

from tech_desk import vendor_profiles
from tech_desk.config import ReportPeriod, add_vendor_to_desk, get_settings, resolve_desks
from tech_desk.database import ResearchRunORM, UpdateORM, init_db, research_run_from_orm, tags_to_json
from tech_desk.llm import LLMClient
from tech_desk.models import ResearchRunResult
from tech_desk.research.analyzer import UpdateAnalyzer
from tech_desk.research.images import resolve_update_image
from tech_desk.research.search import WebSearcher
from tech_desk.timeutils import now_utc

logger = logging.getLogger(__name__)

_NEAR_DUPLICATE_THRESHOLD = 0.82


def _dedup_hash(desk_id: str, url: str) -> str:
    return hashlib.sha256(f"{desk_id}:{url}".encode()).hexdigest()


def _normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9\s]", "", title.lower()).strip()


def _is_near_duplicate_title(title: str, seen_normalized_titles: list[str]) -> bool:
    """Multiple sources often cover the exact same underlying event with
    slightly different headlines — a technical prospecting report shouldn't
    repeat the same story. Fuzzy-match against titles already accepted for
    this desk in this run and drop later near-duplicates."""
    norm = _normalize_title(title)
    for other in seen_normalized_titles:
        if SequenceMatcher(None, norm, other).ratio() >= _NEAR_DUPLICATE_THRESHOLD:
            return True
    return False


class ResearchCollector:
    """Orchestrates web search, LLM analysis, and database persistence."""

    def __init__(self, llm: LLMClient | None = None, session: Session | None = None):
        self.settings = get_settings()
        self.llm = llm or LLMClient()
        self.searcher = WebSearcher()
        self.analyzer = UpdateAnalyzer(self.llm)
        self._session = session
        self._owns_session = session is None

    def _get_session(self) -> Session:
        if self._session is None:
            from tech_desk.database import get_session_factory

            self._session = get_session_factory()()
            self._owns_session = True
        return self._session

    def close(self) -> None:
        if self._owns_session and self._session is not None:
            self._session.close()
            self._session = None

    def run(
        self,
        period: ReportPeriod = "daily",
        *,
        desk_keys: list[str] | None = None,
        custom_instructions: str | None = None,
    ) -> ResearchRunResult:
        init_db()
        session = self._get_session()
        desks = resolve_desks(desk_keys)
        custom_instructions = (custom_instructions or "").strip()

        run = ResearchRunORM(period=period, status="running", custom_instructions=custom_instructions or None)
        session.add(run)
        session.flush()

        total_updates = 0
        desks_processed = 0
        vendors_added_overall: list[str] = []
        notes_cache: dict[str, str] = {}
        result: ResearchRunResult | None = None

        try:
            for desk in desks:
                depth = self.settings.priority_desk_depth_multiplier if desk.priority else 1
                logger.info("Researching desk: %s (%s) depth=%s", desk.name, desk.code, depth)

                results = self.searcher.search_desk(desk, depth_multiplier=depth)
                logger.info("Found %d raw results for %s", len(results), desk.name)

                # Research isn't limited to already-tracked vendors — the analyzer
                # surfaces any relevant vendor for the desk's focus areas. Any newly
                # discovered vendor not yet tracked gets auto-added to key_vendors,
                # so it's picked up by future research runs and report generation too.
                tracked_lower = {v.lower() for v in desk.key_vendors}
                newly_tracked_this_desk: set[str] = set()
                seen_titles_this_desk: list[str] = []

                for result_item in results:
                    vendor_notes = ""
                    if result_item.target_vendor:
                        vendor_notes = notes_cache.setdefault(
                            result_item.target_vendor.lower(),
                            vendor_profiles.get_recent_notes_text(session, result_item.target_vendor),
                        )
                    curated = self.analyzer.analyze_result(
                        desk,
                        result_item,
                        vendor_notes=vendor_notes,
                        custom_instructions=custom_instructions,
                    )
                    if curated is None:
                        continue

                    # Search engines (especially general-web SearXNG engines that
                    # don't strictly honor the time_range filter) can surface old,
                    # evergreen pages that are still topically relevant, which the
                    # LLM has no reason to reject on relevance alone. Hard-filter on
                    # the extracted publish date as a backstop against stale results
                    # showing up in reports (e.g. a 2022 product launch page in 2026).
                    if curated.published_date is not None:
                        pub_date = curated.published_date
                        if pub_date.tzinfo is not None:
                            pub_date = pub_date.replace(tzinfo=None)
                        cutoff = now_utc() - timedelta(days=self.settings.research_lookback_days)
                        if pub_date < cutoff:
                            logger.info(
                                "Discarding stale result for %s: published %s is older than the %d-day lookback window",
                                desk.name,
                                pub_date.date(),
                                self.settings.research_lookback_days,
                            )
                            continue

                    if _is_near_duplicate_title(curated.title, seen_titles_this_desk):
                        logger.info(
                            "Discarding near-duplicate story for %s: %s", desk.name, curated.title
                        )
                        continue
                    seen_titles_this_desk.append(_normalize_title(curated.title))

                    vendor_name = (curated.vendor or "").strip()
                    if (
                        vendor_name
                        and vendor_name.lower() not in ("other", "unknown", "n/a")
                        and len(vendor_name) <= 128
                        and vendor_name.lower() not in tracked_lower
                    ):
                        try:
                            add_vendor_to_desk(desk.id, vendor_name)
                        except (ValueError, LookupError) as exc:
                            logger.debug(
                                "Skipped auto-tracking vendor '%s' on %s: %s", vendor_name, desk.name, exc
                            )
                        else:
                            tracked_lower.add(vendor_name.lower())
                            newly_tracked_this_desk.add(vendor_name)
                            logger.info("Auto-tracked new vendor '%s' discovered on %s", vendor_name, desk.name)

                    if self.settings.image_fetch_during_research and not curated.image_url:
                        curated.image_url = resolve_update_image(
                            curated.source_url,
                            curated.vendor,
                            existing_image=result_item.image_url,
                            allow_og_fetch=False,
                        ) or result_item.image_url or ""

                    dhash = _dedup_hash(desk.id, curated.source_url)
                    existing = session.query(UpdateORM).filter_by(dedup_hash=dhash).first()
                    if existing:
                        continue

                    orm = UpdateORM(
                        research_run_id=run.id,
                        desk_id=curated.desk_id,
                        title=curated.title,
                        summary=curated.summary,
                        source_url=curated.source_url,
                        source_name=curated.source_name,
                        published_date=curated.published_date,
                        discovered_at=curated.discovered_at,
                        category=curated.category.value,
                        relevance=curated.relevance.value,
                        tags_json=tags_to_json(curated.tags),
                        key_takeaways_json=tags_to_json(curated.key_takeaways),
                        stakeholder_impact=curated.stakeholder_impact,
                        who_is_affected_first=curated.who_is_affected_first,
                        raw_snippet=curated.raw_snippet,
                        vendor=curated.vendor,
                        image_url=curated.image_url,
                        dedup_hash=dhash,
                    )
                    session.add(orm)
                    total_updates += 1

                vendors_added_overall.extend(f"{v} ({desk.code})" for v in sorted(newly_tracked_this_desk))
                desks_processed += 1
                session.flush()

            run.status = "completed"
            run.completed_at = now_utc()
            run.desks_processed = desks_processed
            run.updates_found = total_updates
            meta = {"vendors_added": vendors_added_overall}
            if desk_keys:
                meta["desk_ids"] = [d.id for d in desks]
                meta["desk_codes"] = [d.code for d in desks]
            run.metadata_json = json.dumps(meta)
            session.commit()
            logger.info("Research run complete: %d new updates across %d desks", total_updates, desks_processed)
            session.refresh(run)
            result = research_run_from_orm(run)

        except Exception as exc:
            run.status = "failed"
            run.error_message = str(exc)
            run.completed_at = now_utc()
            session.commit()
            logger.exception("Research run failed")
            raise
        finally:
            if self._owns_session:
                self.close()

        if result is None:
            raise RuntimeError("Research run finished without producing a result")
        return result
