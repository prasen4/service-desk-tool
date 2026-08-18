"""Vendor CRM endpoints — profile, notes (with optional file attachment),
status pipeline transitions, and attachment download/delete.

Kept in its own router (rather than growing ``main.py`` further) since this
is a distinct, cohesive feature area.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from tech_desk import vendor_profiles
from tech_desk.api.jobs import job_manager
from tech_desk.api.rate_limit import rate_limit, upload_limiter
from tech_desk.api.services import run_position_paper_job
from tech_desk.database import PositionPaperORM, get_db_session

router = APIRouter(prefix="/api/vendors", tags=["vendors"])


class StatusChangeRequest(BaseModel):
    status: str
    note: str = ""
    changed_by: str = Field(default="", max_length=128)


class PositionPaperRequest(BaseModel):
    custom_prompt: str = Field(default="", max_length=4000)
    async_mode: bool = Field(default=True)


@router.get("/statuses")
async def list_statuses():
    return {"statuses": vendor_profiles.valid_statuses()}


@router.get("/profiles")
async def list_vendor_profiles(
    status: str | None = None,
    owner: str | None = None,
    session: Session = Depends(get_db_session),
):
    """CRM-tracked vendors (those with a profile: status/notes/attachments)."""
    return {"vendors": vendor_profiles.list_vendor_profiles(session, status=status, owner=owner)}


@router.get("/{vendor_name}/profile")
async def get_vendor_profile(
    vendor_name: str,
    news_limit: int = 50,
    session: Session = Depends(get_db_session),
):
    profile = vendor_profiles.get_vendor_profile(session, vendor_name, news_limit=min(news_limit, 200))
    if profile is None:
        raise HTTPException(status_code=404, detail=f"No vendor found: {vendor_name}")
    return profile


@router.post("/{vendor_name}/notes", dependencies=[Depends(rate_limit(upload_limiter, "vendor-notes"))])
async def add_vendor_note(
    vendor_name: str,
    body: str = Form(default=""),
    author: str = Form(default=""),
    file: UploadFile | None = File(default=None),
    session: Session = Depends(get_db_session),
):
    try:
        note = vendor_profiles.add_note(session, vendor_name, body=body, author=author, upload=file)
    except vendor_profiles.VendorProfileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return note


@router.delete("/{vendor_name}/notes/{note_id}")
async def delete_vendor_note(vendor_name: str, note_id: int, session: Session = Depends(get_db_session)):
    if not vendor_profiles.delete_note(session, vendor_name, note_id):
        raise HTTPException(status_code=404, detail="Note not found")
    return {"status": "deleted"}


@router.post("/{vendor_name}/status")
async def change_vendor_status(
    vendor_name: str,
    req: StatusChangeRequest,
    session: Session = Depends(get_db_session),
):
    try:
        event = vendor_profiles.add_status_event(
            session, vendor_name, status=req.status, note=req.note, changed_by=req.changed_by
        )
    except vendor_profiles.VendorProfileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return event


@router.get("/{vendor_name}/attachments/{attachment_id}")
async def download_attachment(vendor_name: str, attachment_id: int, session: Session = Depends(get_db_session)):
    attachment = vendor_profiles.get_attachment(session, vendor_name, attachment_id)
    if attachment is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    path = vendor_profiles.attachment_path(attachment)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Attachment file missing on disk")
    return FileResponse(
        path,
        media_type=attachment.content_type or "application/octet-stream",
        filename=attachment.original_filename,
    )


@router.delete("/{vendor_name}/attachments/{attachment_id}")
async def delete_attachment(vendor_name: str, attachment_id: int, session: Session = Depends(get_db_session)):
    if not vendor_profiles.delete_attachment(session, vendor_name, attachment_id):
        raise HTTPException(status_code=404, detail="Attachment not found")
    return {"status": "deleted"}


def _serialize_position_paper(p: "PositionPaperORM") -> dict:
    return {
        "id": p.id,
        "vendor": p.vendor,
        "status": p.status,
        "custom_prompt": p.custom_prompt,
        "docx_path": p.docx_path,
        "error_message": p.error_message,
        "created_at": p.created_at.isoformat(),
        "generated_at": p.generated_at.isoformat() if p.generated_at else None,
    }


@router.post(
    "/{vendor_name}/position-paper",
    dependencies=[Depends(rate_limit(upload_limiter, "position-paper"))],
)
async def generate_position_paper(vendor_name: str, req: PositionPaperRequest):
    """Kick off per-vendor Position Paper generation (research brief + docx).

    Combines CRM notes/attachments/prior research (DB) with a fresh web
    search, then drafts the paper via a two-stage LLM pipeline.
    """
    if req.async_mode:
        job_id = job_manager.submit(
            "position_paper",
            run_position_paper_job,
            vendor_name=vendor_name,
            custom_prompt=req.custom_prompt,
        )
        return {"job_id": job_id, "status": "pending"}

    try:
        return run_position_paper_job(vendor_name=vendor_name, custom_prompt=req.custom_prompt)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{vendor_name}/position-papers")
async def list_position_papers(vendor_name: str, limit: int = 20, session: Session = Depends(get_db_session)):
    papers = (
        session.query(PositionPaperORM)
        .filter(PositionPaperORM.vendor == vendor_name)
        .order_by(PositionPaperORM.created_at.desc())
        .limit(min(limit, 100))
        .all()
    )
    return {"position_papers": [_serialize_position_paper(p) for p in papers]}


@router.get("/position-papers/{position_paper_id}/download")
async def download_position_paper(position_paper_id: int, session: Session = Depends(get_db_session)):
    paper = session.query(PositionPaperORM).filter_by(id=position_paper_id).first()
    if paper is None:
        raise HTTPException(status_code=404, detail="Position paper not found")
    if paper.status != "completed" or not paper.docx_path:
        raise HTTPException(status_code=409, detail=f"Position paper is not ready (status: {paper.status})")
    from pathlib import Path

    path = Path(paper.docx_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Position paper file missing on disk")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"{paper.vendor}_position_paper.docx",
    )
