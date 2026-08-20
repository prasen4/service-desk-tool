"""Deploy-readiness / health checks, shared by the `tech-desk doctor` CLI
command and the `/api/ready` HTTP endpoint so both surfaces stay in sync."""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


def check_database() -> dict[str, Any]:
    from sqlalchemy import text

    from tech_desk.config import get_settings
    from tech_desk.database import get_engine

    settings = get_settings()
    try:
        t0 = time.perf_counter()
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return {
            "ok": True,
            "backend": settings.db_backend,
            "latency_ms": round((time.perf_counter() - t0) * 1000),
        }
    except Exception as exc:
        return {"ok": False, "backend": settings.db_backend, "error": str(exc)}


def check_migrations() -> dict[str, Any]:
    """Read-only check that the DB's stamped Alembic revision(s) match the
    latest migration head — does NOT run migrations itself (that already
    happens once at startup via ``init_db()``).

    Specifically catches a bug class seen in this repo: a migration file's
    ``revision`` id changed (e.g. renamed/shortened) without re-stamping
    existing local/deployed databases, which otherwise surfaces as a cryptic
    ``CommandError: Can't locate revision identified by '<old-id>'`` crash on
    server startup instead of a clear pre-deploy check failure.
    """
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    from tech_desk.database import _alembic_config, get_engine

    cfg = _alembic_config()
    script = ScriptDirectory.from_config(cfg)
    heads = set(script.get_heads())

    try:
        with get_engine().connect() as conn:
            context = MigrationContext.configure(conn)
            current = set(context.get_current_heads())
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "head_revisions": sorted(heads),
        }

    if not current:
        return {
            "ok": False,
            "error": "No alembic_version stamp found — migrations have not been run",
            "head_revisions": sorted(heads),
        }

    try:
        script.get_revisions(current)
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "hint": (
                "The database's alembic_version table points at a revision id "
                "that no longer exists under migrations/versions/ (e.g. a "
                "migration was renamed/rewritten without re-stamping). Fix: "
                "UPDATE alembic_version SET version_num='<head>' to one of the "
                "head_revisions below."
            ),
            "current_revisions": sorted(current),
            "head_revisions": sorted(heads),
        }

    up_to_date = current == heads
    return {
        "ok": up_to_date,
        "current_revisions": sorted(current),
        "head_revisions": sorted(heads),
        "error": None if up_to_date else "Database is stamped but not at the latest migration head",
    }


def check_api_key() -> dict[str, Any]:
    from tech_desk.config import get_settings

    settings = get_settings()
    return {"ok": bool(settings.openai_api_key)}


def check_disk_writable() -> dict[str, Any]:
    from tech_desk.config import get_settings

    settings = get_settings()
    data_dir = settings.tech_desk_data_dir
    return {"ok": data_dir.exists() and data_dir.is_dir()}


def check_desk_config() -> dict[str, Any]:
    """Sanity-check tech_desks.yaml: every desk needs search queries or the
    research pipeline silently produces zero results for it."""
    from tech_desk.config import list_desk_definitions

    try:
        desks = list_desk_definitions()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    if not desks:
        return {"ok": False, "error": "No tech desks configured"}

    missing_queries = [d.id for d in desks if not d.search_queries]
    return {
        "ok": not missing_queries,
        "desks": len(desks),
        "desks_missing_search_queries": missing_queries,
    }


def check_search_backend() -> dict[str, Any]:
    """SearXNG reachability. In "auto" mode (default) this is informational
    only, since DuckDuckGo is always available as a fallback. In forced
    "searxng" mode (SEARCH_BACKEND=searxng) there is no fallback, so an
    unreachable or unconfigured SearXNG IS a blocking failure there. Forced
    "ddg" mode never touches SearXNG."""
    from tech_desk.config import get_settings

    settings = get_settings()
    backend = settings.search_backend
    url = (settings.searxng_url or "").strip()

    if backend == "ddg":
        return {"ok": True, "backend": "ddg", "note": "SearXNG not used (SEARCH_BACKEND=ddg)"}

    if not url:
        if backend == "searxng":
            return {
                "ok": False,
                "backend": "searxng",
                "configured": False,
                "error": "SEARCH_BACKEND=searxng but SEARXNG_URL is not set",
            }
        return {"ok": True, "backend": "auto", "configured": False, "note": "Using DuckDuckGo fallback only"}

    try:
        import httpx

        t0 = time.perf_counter()
        resp = httpx.get(f"{url}/search", params={"q": "healthcheck", "format": "json"}, timeout=5.0)
        resp.raise_for_status()
        return {
            "ok": True,
            "backend": backend,
            "configured": True,
            "reachable": True,
            "latency_ms": round((time.perf_counter() - t0) * 1000),
        }
    except Exception as exc:
        if backend == "searxng":
            return {
                "ok": False,
                "backend": "searxng",
                "configured": True,
                "reachable": False,
                "error": str(exc),
                "hint": (
                    "SEARCH_BACKEND=searxng has no DuckDuckGo fallback — fix "
                    "SearXNG or switch SEARCH_BACKEND to 'auto' or 'ddg'"
                ),
            }
        return {
            "ok": True,
            "backend": "auto",
            "configured": True,
            "reachable": False,
            "error": str(exc),
            "note": "Falls back to DuckDuckGo automatically",
        }


def run_all_checks() -> dict[str, Any]:
    """Aggregate all readiness checks."""
    checks: dict[str, Any] = {
        "database": check_database(),
        "migrations": check_migrations(),
        "disk_writable": check_disk_writable(),
        "api_key_configured": check_api_key(),
        "desk_config": check_desk_config(),
        "search_backend": check_search_backend(),
    }
    all_ok = all(c.get("ok", False) for c in checks.values())
    return {"status": "ready" if all_ok else "degraded", "checks": checks}
