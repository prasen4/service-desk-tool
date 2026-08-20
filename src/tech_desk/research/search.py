from __future__ import annotations

import logging
import random
import time
from datetime import datetime
from urllib.parse import urlparse

import httpx
from duckduckgo_search import DDGS

from tech_desk.config import get_settings
from tech_desk.models import ResearchResult, TechDeskDefinition

logger = logging.getLogger(__name__)

_SEARXNG_TIMELIMIT = {"d": "day", "w": "week", "m": "month", "y": "year"}

# DDG's anti-bot system rate-limits/blocks automated requests, especially from
# cloud/datacenter IP ranges (AWS, GCP, Azure). A single quick retry catches
# transient blocks; when the block is IP-wide (consistent 403s), it's not
# worth burning much time on backoff since every query will hit the same wall.
_MAX_RETRIES = 1
_BASE_DELAY_SECONDS = 1.0


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
    """Searches the web, preferring a self-hosted SearXNG instance (if
    configured via SEARXNG_URL) and falling back to DuckDuckGo otherwise.

    DDG's unofficial scraping library gets IP-blocked from cloud/datacenter
    ranges (AWS, GCP, Azure), so SearXNG — which fans a query out across many
    upstream engines — is meaningfully more resilient there. DDG remains the
    default when SearXNG isn't set up (e.g. plain local dev).
    """

    def __init__(self, max_results: int | None = None):
        settings = get_settings()
        self.max_results = max_results or settings.research_max_results_per_query
        self.searxng_url = (settings.searxng_url or "").rstrip("/") or None
        self.backend = settings.search_backend

    def _query_searxng(self, query: str, *, timelimit: str | None, categories: str | None) -> list[ResearchResult]:
        """Single SearXNG HTTP call. Raises on failure (caller decides fallback)."""
        params = {"q": query, "format": "json"}
        if timelimit and timelimit in _SEARXNG_TIMELIMIT:
            params["time_range"] = _SEARXNG_TIMELIMIT[timelimit]
        if categories:
            params["categories"] = categories
        resp = httpx.get(f"{self.searxng_url}/search", params=params, timeout=15.0)
        resp.raise_for_status()
        data = resp.json()

        results: list[ResearchResult] = []
        seen_urls: set[str] = set()
        for item in data.get("results", [])[: self.max_results]:
            url = item.get("url", "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            results.append(
                ResearchResult(
                    title=item.get("title", "Untitled"),
                    url=url,
                    snippet=item.get("content", ""),
                    source_domain=_extract_domain(url),
                    published_date=_parse_result_date(item.get("publishedDate")),
                    query=query,
                    image_url=item.get("img_src", "") or "",
                )
            )
        return results

    def _search_searxng(self, query: str, *, timelimit: str | None) -> list[ResearchResult] | None:
        """Query SearXNG. Returns None (not []) on failure, so callers can
        distinguish "SearXNG is unreachable" from "SearXNG found nothing"."""
        if not self.searxng_url:
            return None

        # Prefer the "news" category: dedicated news engines return discrete,
        # dated articles instead of general-web-search's best-ranked evergreen
        # pages (buyer's guides, "2026 trends" blog posts, product pages),
        # which usually have no publish date and can't be filtered for
        # staleness. Fall back to general web search only if news turns up
        # nothing for this query, so narrower topics still get results.
        try:
            results = self._query_searxng(query, timelimit=timelimit, categories="news")
            if not results:
                results = self._query_searxng(query, timelimit=timelimit, categories=None)
        except Exception as exc:
            logger.warning("SearXNG search failed for '%s': %s — falling back to DuckDuckGo", query, exc)
            return None

        return results

    def search(self, query: str, *, timelimit: str | None = "m") -> list[ResearchResult]:
        """Search the web. timelimit: d=day, w=week, m=month, y=year.

        Behavior is controlled by SEARCH_BACKEND (default "auto"):
        - "auto": try SearXNG first (if configured), fall back to DuckDuckGo.
        - "searxng": SearXNG only — no DuckDuckGo fallback (useful for
          isolating/testing SearXNG behavior).
        - "ddg": DuckDuckGo only — SearXNG is never queried, even if
          SEARXNG_URL is configured.
        """
        if self.backend == "ddg":
            return self._search_ddg(query, timelimit=timelimit)

        if self.backend == "searxng":
            results = self._search_searxng(query, timelimit=timelimit)
            if results is None:
                logger.warning(
                    "SEARCH_BACKEND=searxng but SearXNG is unreachable/unconfigured for "
                    "'%s' — returning no results (no DuckDuckGo fallback in forced mode)",
                    query,
                )
                return []
            return results[: self.max_results]

        # "auto" (default): prefer SearXNG, fall back to DuckDuckGo.
        searxng_results = self._search_searxng(query, timelimit=timelimit)
        if searxng_results is not None:
            if searxng_results:
                return searxng_results[: self.max_results]
            logger.info("SearXNG returned 0 results for '%s' — falling back to DuckDuckGo", query)

        return self._search_ddg(query, timelimit=timelimit)

    def _search_ddg(self, query: str, *, timelimit: str | None) -> list[ResearchResult]:
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
                # Small pause so the query burst doesn't look like automated
                # scraping, without adding significant runtime.
                time.sleep(random.uniform(0.2, 0.5))
            for result in self.search(query, timelimit=timelimit):
                if result.url not in seen_urls:
                    seen_urls.add(result.url)
                    result.target_vendor = vendor
                    all_results.append(result)

        return all_results
