from __future__ import annotations

import logging
from datetime import datetime
from urllib.parse import urlparse

from duckduckgo_search import DDGS

from tech_desk.config import get_settings
from tech_desk.models import ResearchResult, TechDeskDefinition

logger = logging.getLogger(__name__)


def _extract_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""


def _parse_result_date(date_str: str | None) -> str | None:
    if not date_str:
        return None
    return date_str.strip() or None


class WebSearcher:
    """Performs web searches using DuckDuckGo (no extra API key required)."""

    def __init__(self, max_results: int | None = None):
        settings = get_settings()
        self.max_results = max_results or settings.research_max_results_per_query

    def search(self, query: str, *, timelimit: str | None = "m") -> list[ResearchResult]:
        """Search the web. timelimit: d=day, w=week, m=month, y=year."""
        results: list[ResearchResult] = []
        seen_urls: set[str] = set()

        try:
            with DDGS() as ddgs:
                for item in ddgs.news(query, max_results=self.max_results, timelimit=timelimit):
                    url = item.get("url", "")
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    results.append(
                        ResearchResult(
                            title=item.get("title", "Untitled"),
                            url=url,
                            snippet=item.get("body", ""),
                            source_domain=_extract_domain(url),
                            published_date=_parse_result_date(item.get("date")),
                            query=query,
                            image_url=item.get("image", "") or "",
                        )
                    )
        except Exception as exc:
            logger.warning("News search failed for '%s': %s — falling back to text search", query, exc)

        if len(results) < self.max_results // 2:
            try:
                with DDGS() as ddgs:
                    for item in ddgs.text(query, max_results=self.max_results, timelimit=timelimit):
                        url = item.get("href", "")
                        if not url or url in seen_urls:
                            continue
                        seen_urls.add(url)
                        results.append(
                            ResearchResult(
                                title=item.get("title", "Untitled"),
                                url=url,
                                snippet=item.get("body", ""),
                                source_domain=_extract_domain(url),
                                query=query,
                            )
                        )
            except Exception as exc:
                logger.error("Text search failed for '%s': %s", query, exc)

        return results[: self.max_results]

    def search_desk(self, desk: TechDeskDefinition, *, depth_multiplier: int = 1) -> list[ResearchResult]:
        all_results: list[ResearchResult] = []
        seen_urls: set[str] = set()
        queries: list[tuple[str, str]] = [(q, "") for q in desk.search_queries]

        # Vendor-targeted queries — primary source of vendor-specific intelligence
        current_year = datetime.now().year
        for vendor in desk.key_vendors:
            queries.append((f"{vendor} generative AI news announcement {current_year}", vendor))
            queries.append((f"{vendor} AI product launch partnership", vendor))

        if depth_multiplier > 1:
            queries = queries * depth_multiplier

        timelimit = "m"

        for query, vendor in queries:
            for result in self.search(query, timelimit=timelimit):
                if result.url not in seen_urls:
                    seen_urls.add(result.url)
                    result.target_vendor = vendor
                    all_results.append(result)

        return all_results
