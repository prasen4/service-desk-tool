from __future__ import annotations

import logging
import re
from functools import lru_cache
from urllib.parse import urljoin

import httpx
from duckduckgo_search import DDGS

from tech_desk.config import get_settings

logger = logging.getLogger(__name__)

_OG_IMAGE_RE = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_OG_IMAGE_RE_ALT = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
    re.IGNORECASE,
)

_http_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    global _http_client
    if _http_client is None:
        settings = get_settings()
        _http_client = httpx.Client(
            timeout=settings.image_fetch_timeout,
            follow_redirects=True,
            headers={"User-Agent": "Cotiviti-TechDesk/1.0"},
        )
    return _http_client


def close_http_client() -> None:
    global _http_client
    if _http_client is not None:
        _http_client.close()
        _http_client = None


def _images_enabled() -> bool:
    return get_settings().image_fetch_enabled


def _extract_og_image(html: str, base_url: str) -> str | None:
    for pattern in (_OG_IMAGE_RE, _OG_IMAGE_RE_ALT):
        match = pattern.search(html)
        if match:
            return urljoin(base_url, match.group(1).strip())
    return None


def fetch_article_image(url: str) -> str | None:
    """Try to extract og:image from an article URL."""
    if not url or not _images_enabled():
        return None
    try:
        resp = _get_client().get(url)
        resp.raise_for_status()
        return _extract_og_image(resp.text[:50000], str(resp.url))
    except Exception as exc:
        logger.debug("Could not fetch og:image from %s: %s", url, exc)
        return None


@lru_cache(maxsize=256)
def search_image(query: str) -> str | None:
    """Search DuckDuckGo images and return the first result URL."""
    if not query.strip() or not _images_enabled():
        return None
    try:
        with DDGS() as ddgs:
            for item in ddgs.images(f"{query} logo", max_results=2, safesearch="moderate"):
                image_url = item.get("image") or item.get("thumbnail")
                if image_url and image_url.startswith("http"):
                    return image_url
    except Exception as exc:
        logger.debug("Image search failed for '%s': %s", query, exc)
    return None


def resolve_vendor_image(vendor: str) -> str | None:
    if not vendor or vendor.lower() in ("other vendors", "other", "unknown"):
        return None
    return search_image(vendor)


def resolve_update_image(
    source_url: str,
    vendor: str = "",
    *,
    existing_image: str = "",
    allow_og_fetch: bool = True,
) -> str | None:
    """Best-effort image: existing > og:image > vendor logo."""
    if not _images_enabled():
        return existing_image or None
    if existing_image:
        return existing_image
    if allow_og_fetch:
        image = fetch_article_image(source_url)
        if image:
            return image
    if vendor:
        return resolve_vendor_image(vendor)
    return None
