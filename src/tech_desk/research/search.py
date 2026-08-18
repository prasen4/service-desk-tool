from __future__ import annotations

import logging
import random
import time
from datetime import datetime
from urllib.parse import urlparse

from duckduckgo_search import DDGS

from tech_desk.config import get_settings
from tech_desk.models import ResearchResult, TechDeskDefinition

logger = logging.getLogger(__name__)

# DDG's anti-bot system rate-limits/blocks automated requests, especially from
# cloud/datacenter IP ranges (AWS, GCP, Azure). A short retry with backoff
# recovers from transient blocks without hammering the endpoint further.
_MAX_RETRIES = 2
_BASE_DELAY_SECONDS = 2.0


def _is_rate_limited(exc: Exception) -> bool:
    text = str(exc).lower()
    return "ratelimit" in text or "403" in text or "429" in text


def _run_with_retry(fn, *, label: str, query: str):
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return list(fn())
        except Exception as exc:  # noqa: BLE001 - DDGS raises various exception types
            last_exc = exc
            if attempt < _MAX_RETRIES and _is_rate_limited(exc):
                delay = _BASE_DELAY_SECONDS * (2**attempt) + random.uniform(0, 1)
                logger.info(
                    "%s rate-limited for '%s' (attempt %d/%d) — retrying in %.1fs",
                    label,
                    query,
                    attempt + 1,
                    _MAX_RETRIES + 1,
                    delay,
                )
                time.sleep(delay)
                continue
            raise
    if last_exc is not None:
        raise last_exc
    return []


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
                news_items = _run_with_retry(
                    lambda: ddgs.news(query, max_results=self.max_results, timelimit=timelimit),
                    label="News search",
                    query=query,
                )
            for item in news_items:
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
            # Small pause before the fallback call so we don't immediately
            # double up on requests right after a rate-limited news search.
            time.sleep(random.uniform(0.5, 1.5))
            try:
                with DDGS() as ddgs:
                    text_items = _run_with_retry(
                        lambda: ddgs.text(query, max_results=self.max_results, timelimit=timelimit),
                        label="Text search",
                        query=query,
                    )
                for item in text_items:
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

        for i, (query, vendor) in enumerate(queries):
            if i > 0:
                # Pace requests out so the query burst doesn't look like
                # automated scraping to DDG's rate limiter.
                time.sleep(random.uniform(0.75, 2.0))
            for result in self.search(query, timelimit=timelimit):
                if result.url not in seen_urls:
                    seen_urls.add(result.url)
                    result.target_vendor = vendor
                    all_results.append(result)

        return all_results
