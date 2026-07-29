from __future__ import annotations

from datetime import datetime

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


def list_vendor_summaries(session: Session) -> list[dict]:
    registry = build_vendor_registry()
    tracked_names = list(registry.keys())

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

    updates = session.query(UpdateORM).order_by(UpdateORM.discovered_at.desc()).all()
    for orm in updates:
        canon = resolve_canonical_vendor(orm.vendor, tracked_names) or (orm.vendor.strip() if orm.vendor else "Other")
        if canon not in summaries:
            summaries[canon] = {
                "name": canon,
                "is_tracked": False,
                "tracked_desks": [],
                "update_count": 0,
                "latest_at": None,
            }
        entry = summaries[canon]
        entry["update_count"] += 1
        sort_at = _update_sort_date(orm)
        latest = entry["latest_at"]
        if latest is None or sort_at > datetime.fromisoformat(latest):
            entry["latest_at"] = sort_at.isoformat()

    result = list(summaries.values())
    result.sort(
        key=lambda v: (
            v["latest_at"] is None,
            -(datetime.fromisoformat(v["latest_at"]).timestamp() if v["latest_at"] else 0),
            -v["update_count"],
            v["name"].lower(),
        )
    )
    return result


def get_vendor_updates(session: Session, vendor_name: str, *, limit: int = 100) -> dict | None:
    registry = build_vendor_registry()
    tracked_names = list(registry.keys())
    desk_map = desk_lookup()

    canonical = vendor_name
    if canonical not in registry and canonical != "Other":
        matched = resolve_canonical_vendor(vendor_name, tracked_names)
        if matched:
            canonical = matched

    updates = session.query(UpdateORM).all()
    matched_updates: list[UpdateORM] = []
    for orm in updates:
        raw = orm.vendor or ""
        canon = resolve_canonical_vendor(raw, tracked_names) or (raw.strip() if raw else "Other")
        if canon.lower() == canonical.lower() or raw.lower() == vendor_name.lower():
            matched_updates.append(orm)

    if not matched_updates and canonical not in registry and canonical != "Other":
        return None

    matched_updates.sort(key=_update_sort_date, reverse=True)
    limited = matched_updates[:limit]

    meta = registry.get(canonical, {
        "name": canonical,
        "is_tracked": False,
        "tracked_desks": [],
    })

    return {
        "vendor": canonical,
        "is_tracked": meta.get("is_tracked", False),
        "tracked_desks": meta.get("tracked_desks", []),
        "update_count": len(matched_updates),
        "updates": [serialize_update(u, desk_map) for u in limited],
    }
