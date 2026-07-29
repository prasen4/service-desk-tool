from __future__ import annotations

import hashlib
import json
import logging

from sqlalchemy.orm import Session

from tech_desk.config import ReportPeriod, get_settings, resolve_desks
from tech_desk.database import ResearchRunORM, UpdateORM, init_db, research_run_from_orm, tags_to_json
from tech_desk.llm import LLMClient
from tech_desk.models import ResearchRunResult
from tech_desk.research.analyzer import UpdateAnalyzer
from tech_desk.research.images import resolve_update_image
from tech_desk.research.search import WebSearcher
from tech_desk.timeutils import now_utc

logger = logging.getLogger(__name__)


def _dedup_hash(desk_id: str, url: str) -> str:
    return hashlib.sha256(f"{desk_id}:{url}".encode()).hexdigest()


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
    ) -> ResearchRunResult:
        init_db()
        session = self._get_session()
        desks = resolve_desks(desk_keys)

        run = ResearchRunORM(period=period, status="running")
        session.add(run)
        session.flush()

        total_updates = 0
        desks_processed = 0
        result: ResearchRunResult | None = None

        try:
            for desk in desks:
                depth = self.settings.priority_desk_depth_multiplier if desk.priority else 1
                logger.info("Researching desk: %s (%s) depth=%s", desk.name, desk.code, depth)

                results = self.searcher.search_desk(desk, depth_multiplier=depth)
                logger.info("Found %d raw results for %s", len(results), desk.name)

                for result_item in results:
                    curated = self.analyzer.analyze_result(desk, result_item)
                    if curated is None:
                        continue

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
                        raw_snippet=curated.raw_snippet,
                        vendor=curated.vendor,
                        image_url=curated.image_url,
                        dedup_hash=dhash,
                    )
                    session.add(orm)
                    total_updates += 1

                desks_processed += 1
                session.flush()

            run.status = "completed"
            run.completed_at = now_utc()
            run.desks_processed = desks_processed
            run.updates_found = total_updates
            if desk_keys:
                meta = {"desk_ids": [d.id for d in desks], "desk_codes": [d.code for d in desks]}
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
