"""SharePoint browse/import endpoints — lets users pull an existing document
from SharePoint (e.g. a vendor's position paper or notes doc) and attach it
to a vendor's CRM profile.

Inert (400s) unless `sharepoint_client.is_configured()` — see config.Settings.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from tech_desk import vendor_profiles
from tech_desk.api.rate_limit import rate_limit, upload_limiter
from tech_desk.database import get_db_session

router = APIRouter(prefix="/api/sharepoint", tags=["sharepoint"])


class SharePointImportRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=1024, description="SharePoint file path (as returned by /browse)")
    author: str = Field(default="", max_length=128)


@router.get("/status")
async def sharepoint_status():
    from tech_desk.integrations import sharepoint_client

    return {"enabled": sharepoint_client.is_configured()}


@router.get("/browse")
async def browse_sharepoint(path: str = "Shared Documents"):
    from tech_desk.integrations import sharepoint_client

    if not sharepoint_client.is_configured():
        raise HTTPException(status_code=400, detail="SharePoint is not configured.")
    try:
        entries = sharepoint_client.list_folder(path)
    except sharepoint_client.SharePointError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"path": path, "entries": entries}


@router.post(
    "/import/{vendor_name}",
    dependencies=[Depends(rate_limit(upload_limiter, "sharepoint-import"))],
)
async def import_from_sharepoint(
    vendor_name: str,
    req: SharePointImportRequest,
    session: Session = Depends(get_db_session),
):
    from tech_desk.integrations import sharepoint_client

    if not sharepoint_client.is_configured():
        raise HTTPException(status_code=400, detail="SharePoint is not configured.")
    try:
        content = sharepoint_client.download_file(req.path)
    except sharepoint_client.SharePointError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    filename = req.path.rstrip("/").rsplit("/", 1)[-1] or "file"
    try:
        note = vendor_profiles.import_attachment_from_sharepoint(
            session, vendor_name, filename=filename, content=content, author=req.author
        )
    except vendor_profiles.VendorProfileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return note
