from __future__ import annotations

from unittest.mock import MagicMock

from tech_desk.models import ResearchResult
from tech_desk.research.search import WebSearcher


def _searcher(*, backend: str, searxng_url: str | None) -> WebSearcher:
    """Build a WebSearcher with explicit backend/url, bypassing real Settings
    (which reads the repo's actual .env file) so tests are deterministic."""
    searcher = WebSearcher.__new__(WebSearcher)
    searcher.max_results = 8
    searcher.searxng_url = searxng_url
    searcher.backend = backend
    return searcher


def test_search_backend_ddg_forces_skip_of_searxng(monkeypatch):
    """SEARCH_BACKEND=ddg must never call SearXNG, even if configured."""
    searcher = _searcher(backend="ddg", searxng_url="http://localhost:8888")
    searcher._search_searxng = MagicMock(side_effect=AssertionError("SearXNG should not be queried"))
    expected = [ResearchResult(title="t", url="https://example.com/1")]
    searcher._search_ddg = MagicMock(return_value=expected)

    results = searcher.search("test query")

    searcher._search_searxng.assert_not_called()
    searcher._search_ddg.assert_called_once()
    assert results == expected


def test_search_backend_forced_searxng_has_no_ddg_fallback(monkeypatch):
    """SEARCH_BACKEND=searxng must not fall back to DDG when SearXNG fails."""
    searcher = _searcher(backend="searxng", searxng_url="http://localhost:8888")
    searcher._search_searxng = MagicMock(return_value=None)
    searcher._search_ddg = MagicMock(side_effect=AssertionError("DDG should not be queried"))

    results = searcher.search("test query")

    searcher._search_ddg.assert_not_called()
    assert results == []


def test_search_backend_forced_searxng_returns_results():
    searcher = _searcher(backend="searxng", searxng_url="http://localhost:8888")
    expected = [ResearchResult(title="t", url="https://example.com/1")]
    searcher._search_searxng = MagicMock(return_value=expected)
    searcher._search_ddg = MagicMock(side_effect=AssertionError("DDG should not be queried"))

    results = searcher.search("test query")

    assert results == expected


def test_search_backend_auto_falls_back_to_ddg_when_searxng_empty():
    searcher = _searcher(backend="auto", searxng_url="http://localhost:8888")
    searcher._search_searxng = MagicMock(return_value=None)
    expected = [ResearchResult(title="t", url="https://example.com/1")]
    searcher._search_ddg = MagicMock(return_value=expected)

    results = searcher.search("test query")

    assert results == expected


def test_search_backend_auto_prefers_searxng_when_available():
    searcher = _searcher(backend="auto", searxng_url="http://localhost:8888")
    expected = [ResearchResult(title="t", url="https://example.com/1")]
    searcher._search_searxng = MagicMock(return_value=expected)
    searcher._search_ddg = MagicMock(side_effect=AssertionError("DDG should not be queried"))

    results = searcher.search("test query")

    assert results == expected
