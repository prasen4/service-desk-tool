from __future__ import annotations

from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from tech_desk.config import list_desk_definitions
from tech_desk.database import UpdateORM
from tech_desk.reports.vendor_intel import _match_vendor


def desk_lookup() -> dict[str, dict]:
    return {
        d.id: {"id": d.id, "code": d.code, "name": d.name}
        for d in list_desk_definitions()
    }


def build_vendor_registry() -> dict[str, dict]:
    """Map canonical vendor name -> desks that track it."""
    registry: dict[str, dict] = {}
    for desk in list_desk_definitions():
        desk_info = {"id": desk.id, "code": desk.code, "name": desk.name}
        for vendor in desk.key_vendors:
            entry = registry.setdefault(
                vendor,
                {"name": vendor, "tracked_desks": [], "is_tracked": True},
            )
            if desk_info not in entry["tracked_desks"]:
                entry["tracked_desks"].append(desk_info)
    return registry


def resolve_canonical_vendor(raw_vendor: str, tracked: list[str]) -> str | None:
    if not raw_vendor or raw_vendor.lower() in ("other", "unknown"):
        return None
    return _match_vendor(raw_vendor, tracked)


def _update_sort_date(orm: UpdateORM) -> datetime:
    return orm.published_date or orm.discovered_at


def serialize_update(orm: UpdateORM, desk_map: dict[str, dict]) -> dict:
    desk = desk_map.get(orm.desk_id, {"id": orm.desk_id, "code": orm.desk_id.upper(), "name": orm.desk_id})
    sort_at = _update_sort_date(orm)
    return {
        "id": orm.id,
        "title": orm.title,
        "summary": orm.summary,
        "vendor": orm.vendor or "",
        "source_url": orm.source_url,
        "source_name": orm.source_name,
        "image_url": getattr(orm, "image_url", "") or "",
        "published_date": orm.published_date.isoformat() if orm.published_date else None,
        "discovered_at": orm.discovered_at.isoformat(),
        "sort_at": sort_at.isoformat(),
        "desk_id": desk["id"],
        "desk_code": desk["code"],
        "desk_name": desk["name"],
        "category": orm.category,
        "relevance": orm.relevance,
    }


def list_vendor_summaries(session: Session, *, limit: int | None = None, offset: int = 0) -> dict:
    """Vendor news-feed summaries, aggregated at the SQL level.

    Previously this loaded every ``updates`` row into Python just to group by
    vendor — fine at hundreds of rows, a real memory/latency problem once the
    table grows into the tens of thousands. Instead we let the database do the
    GROUP BY (cheap, indexed on ``vendor``) and only bring back one row per
    distinct raw vendor string, then merge aliases in Python over that much
    smaller set.
    """
    registry = build_vendor_registry()
    tracked_names = list(registry.keys())

    sort_expr = func.coalesce(UpdateORM.published_date, UpdateORM.discovered_at)
    rows = (
        session.query(UpdateORM.vendor, func.count(UpdateORM.id), func.max(sort_expr))
        .filter(UpdateORM.vendor != "")
        .group_by(UpdateORM.vendor)
        .all()
    )

    summaries: dict[str, dict] = {
        name: {
            "name": name,
            "is_tracked": True,
            "tracked_desks": data["tracked_desks"],
            "update_count": 0,
            "latest_at": None,
        }
        for name, data in registry.items()
    }

    for raw_vendor, count, latest in rows:
        canon = resolve_canonical_vendor(raw_vendor, tracked_names) or raw_vendor.strip()
        if canon not in summaries:
            summaries[canon] = {
                "name": canon,
                "is_tracked": canon in registry,
                "tracked_desks": registry.get(canon, {}).get("tracked_desks", []),
                "update_count": 0,
                "latest_at": None,
            }
        entry = summaries[canon]
        entry["update_count"] += count
        if latest is not None and (entry["latest_at"] is None or latest > entry["latest_at"]):
            entry["latest_at"] = latest

    result = list(summaries.values())
    result.sort(
        key=lambda v: (
            v["latest_at"] is None,
            -(v["latest_at"].timestamp() if v["latest_at"] else 0),
            -v["update_count"],
            v["name"].lower(),
        )
    )
    for entry in result:
        entry["latest_at"] = entry["latest_at"].isoformat() if entry["latest_at"] else None

    total = len(result)
    if limit is not None:
        result = result[offset : offset + limit]
    return {"vendors": result, "total": total}


def get_vendor_updates(
    session: Session,
    vendor_name: str,
    *,
    limit: int = 100,
    offset: int = 0,
) -> dict | None:
    registry = build_vendor_registry()
    tracked_names = list(registry.keys())
    desk_map = desk_lookup()

    canonical = vendor_name
    if canonical not in registry and canonical != "Other":
        matched = resolve_canonical_vendor(vendor_name, tracked_names)
        if matched:
            canonical = matched

    # SQL-level prefilter: narrows the scan to rows whose raw vendor string
    # plausibly matches, instead of pulling the entire updates table into
    # Python. The precise (fuzzy) canonicalization still runs afterward on
    # this much smaller candidate set.
    candidates = (
        session.query(UpdateORM)
        .filter(UpdateORM.vendor.ilike(f"%{canonical}%"))
        .all()
    )
    if not candidates:
        # Fall back to an exact (case-insensitive) match in case the fuzzy
        # substring filter above missed a differently-worded alias.
        candidates = session.query(UpdateORM).filter(func.lower(UpdateORM.vendor) == vendor_name.lower()).all()

    matched_updates: list[UpdateORM] = []
    for orm in candidates:
        raw = orm.vendor or ""
        canon = resolve_canonical_vendor(raw, tracked_names) or (raw.strip() if raw else "Other")
        if canon.lower() == canonical.lower() or raw.lower() == vendor_name.lower():
            matched_updates.append(orm)

    if not matched_updates and canonical not in registry and canonical != "Other":
        return None

    matched_updates.sort(key=_update_sort_date, reverse=True)
    total = len(matched_updates)
    limited = matched_updates[offset : offset + limit]

    meta = registry.get(canonical, {
        "name": canonical,
        "is_tracked": False,
        "tracked_desks": [],
    })

    return {
        "vendor": canonical,
        "is_tracked": meta.get("is_tracked", False),
        "tracked_desks": meta.get("tracked_desks", []),
        "update_count": total,
        "updates": [serialize_update(u, desk_map) for u in limited],
    }
