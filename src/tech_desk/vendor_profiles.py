"""Vendor CRM service layer — profiles, notes, file attachments, and the
status pipeline history (identified -> outreach -> ... -> selected/rejected).

This sits alongside ``tech_desk.vendors`` (which derives read-only vendor news
feeds from discovered updates). ``VendorORM`` is the durable, analyst-owned
profile; this module is where notes/attachments/status transitions live.
"""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from tech_desk.config import get_settings
from tech_desk.database import (
    VendorAttachmentORM,
    VendorNoteORM,
    VendorORM,
    VendorStatusEventORM,
)
from tech_desk.models import VENDOR_STATUS_LABELS, VENDOR_STATUS_BRANCH, VENDOR_STATUS_PIPELINE, VendorStatus
from tech_desk.vendors import build_vendor_registry, get_vendor_updates, resolve_canonical_vendor

logger = logging.getLogger(__name__)

# Allow-list, not a deny-list — the safe default for user-uploaded files (OWASP
# unrestricted file upload). Anything not on this list is rejected outright.
ALLOWED_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".txt", ".md", ".csv",
}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB


class VendorProfileError(Exception):
    """Base error for vendor-profile operations that should map to a 4xx response."""


class VendorNotFoundError(VendorProfileError):
    pass


class InvalidAttachmentError(VendorProfileError):
    pass


def _sanitize_filename(name: str) -> str:
    """Strip directory components and unsafe characters (path traversal defense)."""
    base = Path(name or "file").name
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base).strip("._ ") or "file"
    return base[:200]


def _validate_extension(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise InvalidAttachmentError(f"File type '{ext or '(none)'}' is not allowed. Allowed types: {allowed}")
    return ext


def _attachments_dir(vendor_id: int) -> Path:
    settings = get_settings()
    d = settings.tech_desk_data_dir / "attachments" / str(vendor_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def valid_statuses() -> list[dict]:
    """Pipeline stages in chronological order, followed by branch outcomes.

    ``stage_order`` lets the frontend render an ordered stepper (1-indexed,
    ``None`` for branch statuses like Rejected/On Hold which can happen from
    any stage and aren't part of the main sequence).
    """
    ordered: list[dict] = []
    for i, value in enumerate(VENDOR_STATUS_PIPELINE, start=1):
        ordered.append({"value": value, "label": VENDOR_STATUS_LABELS[value], "stage_order": i, "is_branch": False})
    for value in VENDOR_STATUS_BRANCH:
        ordered.append({"value": value, "label": VENDOR_STATUS_LABELS[value], "stage_order": None, "is_branch": True})
    return ordered


def get_or_create_vendor(session: Session, name: str) -> VendorORM:
    canonical = name.strip()
    if not canonical:
        raise VendorProfileError("Vendor name is required.")
    vendor = session.query(VendorORM).filter(func.lower(VendorORM.name) == canonical.lower()).first()
    if vendor:
        return vendor
    vendor = VendorORM(name=canonical, status=VendorStatus.IDENTIFIED.value)
    session.add(vendor)
    session.flush()
    logger.info("Created vendor CRM profile: %s", canonical)
    return vendor


def _find_vendor(session: Session, name: str) -> VendorORM | None:
    """Resolve a possibly-aliased vendor name to its canonical CRM row, if one exists."""
    registry = build_vendor_registry()
    tracked = list(registry.keys())
    canonical = resolve_canonical_vendor(name, tracked) or name.strip()
    vendor = session.query(VendorORM).filter(func.lower(VendorORM.name) == canonical.lower()).first()
    if vendor:
        return vendor
    # Fall back to an exact match on the raw name (covers untracked/ad hoc vendors).
    return session.query(VendorORM).filter(func.lower(VendorORM.name) == name.strip().lower()).first()


def _serialize_note(note: VendorNoteORM, attachments: list[VendorAttachmentORM]) -> dict:
    return {
        "id": note.id,
        "body": note.body,
        "author": note.author,
        "created_at": note.created_at.isoformat(),
        "attachments": [_serialize_attachment(a) for a in attachments if a.note_id == note.id],
    }


def _serialize_status_event(event: VendorStatusEventORM, *, duration_label: str | None = None) -> dict:
    return {
        "id": event.id,
        "status": event.status,
        "status_label": VENDOR_STATUS_LABELS.get(event.status, event.status),
        "note": event.note,
        "changed_by": event.changed_by,
        "created_at": event.created_at.isoformat(),
        "duration_label": duration_label,
    }


def _format_duration(delta) -> str:
    total_seconds = max(delta.total_seconds(), 0)
    days = total_seconds / 86400
    if days >= 1:
        rounded = round(days)
        return f"{rounded} day{'s' if rounded != 1 else ''}"
    hours = total_seconds / 3600
    if hours >= 1:
        rounded = round(hours)
        return f"{rounded} hour{'s' if rounded != 1 else ''}"
    return "< 1 hour"


def _annotate_status_durations(events_desc: list[VendorStatusEventORM]) -> list[dict]:
    """Compute how long the vendor spent in each stage from a descending
    (newest-first) list of status events — i.e. the chronology/duration the
    plain timeline was missing."""
    from tech_desk.timeutils import now_utc

    serialized: list[dict] = []
    for i, event in enumerate(events_desc):
        end = now_utc() if i == 0 else events_desc[i - 1].created_at
        label = _format_duration(end - event.created_at) + (" (ongoing)" if i == 0 else "")
        serialized.append(_serialize_status_event(event, duration_label=label))
    return serialized


def _serialize_attachment(attachment: VendorAttachmentORM) -> dict:
    return {
        "id": attachment.id,
        "note_id": attachment.note_id,
        "filename": attachment.original_filename,
        "content_type": attachment.content_type,
        "size_bytes": attachment.size_bytes,
        "uploaded_at": attachment.uploaded_at.isoformat(),
    }


def get_vendor_profile(session: Session, vendor_name: str, *, news_limit: int = 50) -> dict | None:
    """Unified vendor view: CRM profile (status/notes/attachments) + news feed."""
    news = get_vendor_updates(session, vendor_name, limit=news_limit)
    vendor = _find_vendor(session, vendor_name)

    if vendor is None and news is None:
        return None

    if vendor is None:
        return {
            "id": None,
            "name": news["vendor"],
            "status": None,
            "status_label": None,
            "owner": "",
            "created_at": None,
            "updated_at": None,
            "is_tracked": news["is_tracked"],
            "tracked_desks": news["tracked_desks"],
            "news": news["updates"],
            "news_count": news["update_count"],
            "notes": [],
            "status_history": [],
            "attachments": [],
        }

    notes = (
        session.query(VendorNoteORM)
        .filter(VendorNoteORM.vendor_id == vendor.id)
        .order_by(VendorNoteORM.created_at.desc())
        .all()
    )
    status_events = (
        session.query(VendorStatusEventORM)
        .filter(VendorStatusEventORM.vendor_id == vendor.id)
        .order_by(VendorStatusEventORM.created_at.desc())
        .all()
    )
    attachments = (
        session.query(VendorAttachmentORM)
        .filter(VendorAttachmentORM.vendor_id == vendor.id)
        .order_by(VendorAttachmentORM.uploaded_at.desc())
        .all()
    )

    return {
        "id": vendor.id,
        "name": vendor.name,
        "status": vendor.status,
        "status_label": VENDOR_STATUS_LABELS.get(vendor.status, vendor.status),
        "owner": vendor.owner,
        "created_at": vendor.created_at.isoformat(),
        "updated_at": vendor.updated_at.isoformat(),
        "is_tracked": (news or {}).get("is_tracked", False),
        "tracked_desks": (news or {}).get("tracked_desks", []),
        "news": (news or {}).get("updates", []),
        "news_count": (news or {}).get("update_count", 0),
        "notes": [_serialize_note(n, attachments) for n in notes],
        "status_history": _annotate_status_durations(status_events),
        "attachments": [_serialize_attachment(a) for a in attachments],
    }


def get_recent_notes_text(session: Session, vendor_name: str, *, limit: int = 5) -> str:
    """Short digest of a vendor's most recent analyst notes, formatted as plain
    text for inclusion in an LLM prompt. Empty string if there's no CRM
    profile or no notes yet — callers should treat that as "no extra context".
    """
    vendor = _find_vendor(session, vendor_name)
    if vendor is None:
        return ""
    notes = (
        session.query(VendorNoteORM)
        .filter(VendorNoteORM.vendor_id == vendor.id)
        .order_by(VendorNoteORM.created_at.desc())
        .limit(limit)
        .all()
    )
    if not notes:
        return ""
    lines = []
    for n in notes:
        if not n.body:
            continue
        author = f" ({n.author})" if n.author else ""
        lines.append(f"- [{n.created_at.strftime('%Y-%m-%d')}]{author} {n.body}")
    return "\n".join(lines)


def add_note(
    session: Session,
    vendor_name: str,
    *,
    body: str,
    author: str = "",
    upload: UploadFile | None = None,
) -> dict:
    body = (body or "").strip()
    if not body and upload is None:
        raise VendorProfileError("A note must include text or a file attachment.")

    vendor = get_or_create_vendor(session, vendor_name)
    note = VendorNoteORM(vendor_id=vendor.id, body=body, author=(author or "").strip())
    session.add(note)
    session.flush()

    attachment_orm = None
    if upload is not None and upload.filename:
        attachment_orm = save_attachment(session, vendor, upload, note=note)

    session.commit()
    return _serialize_note(note, [attachment_orm] if attachment_orm else [])


def save_attachment(
    session: Session,
    vendor: VendorORM,
    upload: UploadFile,
    *,
    note: VendorNoteORM | None = None,
) -> VendorAttachmentORM:
    original_name = _sanitize_filename(upload.filename or "file")
    _validate_extension(original_name)

    stored_name = f"{uuid.uuid4().hex}{Path(original_name).suffix.lower()}"
    dest = _attachments_dir(vendor.id) / stored_name

    size = 0
    with dest.open("wb") as out:
        while chunk := upload.file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                out.close()
                dest.unlink(missing_ok=True)
                raise InvalidAttachmentError(
                    f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit."
                )
            out.write(chunk)

    attachment = VendorAttachmentORM(
        vendor_id=vendor.id,
        note_id=note.id if note else None,
        original_filename=original_name,
        stored_filename=stored_name,
        content_type=upload.content_type or "application/octet-stream",
        size_bytes=size,
    )
    session.add(attachment)
    session.flush()
    return attachment


def attachment_path(attachment: VendorAttachmentORM) -> Path:
    return _attachments_dir(attachment.vendor_id) / attachment.stored_filename


def delete_note(session: Session, vendor_name: str, note_id: int) -> bool:
    vendor = _find_vendor(session, vendor_name)
    if vendor is None:
        return False
    note = (
        session.query(VendorNoteORM)
        .filter(VendorNoteORM.id == note_id, VendorNoteORM.vendor_id == vendor.id)
        .first()
    )
    if note is None:
        return False
    for attachment in list(note.attachments):
        attachment_path(attachment).unlink(missing_ok=True)
    session.delete(note)
    session.commit()
    return True


def delete_attachment(session: Session, vendor_name: str, attachment_id: int) -> bool:
    vendor = _find_vendor(session, vendor_name)
    if vendor is None:
        return False
    attachment = (
        session.query(VendorAttachmentORM)
        .filter(VendorAttachmentORM.id == attachment_id, VendorAttachmentORM.vendor_id == vendor.id)
        .first()
    )
    if attachment is None:
        return False
    attachment_path(attachment).unlink(missing_ok=True)
    session.delete(attachment)
    session.commit()
    return True


def get_attachment(session: Session, vendor_name: str, attachment_id: int) -> VendorAttachmentORM | None:
    vendor = _find_vendor(session, vendor_name)
    if vendor is None:
        return None
    return (
        session.query(VendorAttachmentORM)
        .filter(VendorAttachmentORM.id == attachment_id, VendorAttachmentORM.vendor_id == vendor.id)
        .first()
    )


def add_status_event(
    session: Session,
    vendor_name: str,
    *,
    status: str,
    note: str = "",
    changed_by: str = "",
) -> dict:
    valid = {s.value for s in VendorStatus}
    if status not in valid:
        raise VendorProfileError(f"Invalid status '{status}'. Valid options: {', '.join(sorted(valid))}")

    vendor = get_or_create_vendor(session, vendor_name)
    vendor.status = status
    event = VendorStatusEventORM(
        vendor_id=vendor.id,
        status=status,
        note=(note or "").strip(),
        changed_by=(changed_by or "").strip(),
    )
    session.add(event)
    session.commit()
    return _serialize_status_event(event)


def list_vendor_profiles(
    session: Session,
    *,
    status: str | None = None,
    owner: str | None = None,
) -> list[dict]:
    """CRM-tracked vendors only (i.e. vendors with an explicit profile/status)."""
    q = session.query(VendorORM)
    if status:
        q = q.filter(VendorORM.status == status)
    if owner:
        q = q.filter(func.lower(VendorORM.owner) == owner.lower())
    vendors = q.order_by(VendorORM.updated_at.desc()).all()
    return [
        {
            "id": v.id,
            "name": v.name,
            "status": v.status,
            "status_label": VENDOR_STATUS_LABELS.get(v.status, v.status),
            "owner": v.owner,
            "updated_at": v.updated_at.isoformat(),
        }
        for v in vendors
    ]
