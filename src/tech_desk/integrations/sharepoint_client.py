"""SharePoint read/write integration via Microsoft Graph-compatible SharePoint
REST API, using Azure AD app-only auth (client credentials grant).

Inert unless all four `SHAREPOINT_*` settings are configured (see
`config.Settings`). Requires the optional `sharepoint` extra
(`pip install tech-desk[sharepoint]` — pulls in `msal` + `office365-rest-python-client`);
imports are done lazily inside functions so the rest of the app works fine
without that extra installed.

Usage once configured:
    from tech_desk.integrations import sharepoint_client as sp
    sp.upload_file("weekly", "report.docx", pathlib.Path("report.docx").read_bytes())
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from tech_desk.config import get_settings

logger = logging.getLogger(__name__)


class SharePointError(Exception):
    """Raised for any SharePoint configuration or API failure."""


def is_configured() -> bool:
    return get_settings().sharepoint_configured


def _require_configured() -> None:
    if not is_configured():
        raise SharePointError(
            "SharePoint is not configured — set SHAREPOINT_SITE_URL, SHAREPOINT_CLIENT_ID, "
            "SHAREPOINT_CLIENT_SECRET, and SHAREPOINT_TENANT_ID in .env."
        )


def _acquire_token() -> str:
    settings = get_settings()
    try:
        import msal
    except ImportError as exc:
        raise SharePointError(
            "The 'sharepoint' optional dependency isn't installed — run "
            "`pip install tech-desk[sharepoint]` (or rebuild the Docker image)."
        ) from exc

    site_netloc = urlparse(settings.sharepoint_site_url).netloc  # e.g. yourtenant.sharepoint.com
    resource_scope = f"https://{site_netloc}/.default"
    authority = f"https://login.microsoftonline.com/{settings.sharepoint_tenant_id}"

    app = msal.ConfidentialClientApplication(
        client_id=settings.sharepoint_client_id,
        client_credential=settings.sharepoint_client_secret,
        authority=authority,
    )
    result = app.acquire_token_for_client(scopes=[resource_scope])
    if "access_token" not in result:
        raise SharePointError(
            f"Failed to acquire SharePoint app-only token: "
            f"{result.get('error')}: {result.get('error_description')}"
        )
    return result["access_token"]


def _get_client_context():
    _require_configured()
    settings = get_settings()
    try:
        from office365.sharepoint.client_context import ClientContext
    except ImportError as exc:
        raise SharePointError(
            "The 'sharepoint' optional dependency isn't installed — run "
            "`pip install tech-desk[sharepoint]` (or rebuild the Docker image)."
        ) from exc

    return ClientContext(settings.sharepoint_site_url).with_access_token(_acquire_token)


def upload_file(folder_relative_path: str, filename: str, content: bytes) -> str:
    """Uploads `content` as `filename` into
    `<SHAREPOINT_REPORTS_FOLDER>/<folder_relative_path>` (folders are created
    automatically if they don't exist). Returns the file's server-relative URL.
    """
    settings = get_settings()
    ctx = _get_client_context()
    target_folder_url = "/".join(
        part.strip("/") for part in (settings.sharepoint_reports_folder, folder_relative_path) if part
    )
    try:
        folder = ctx.web.ensure_folder_path(target_folder_url).execute_query()
        uploaded = folder.upload_file(filename, content).execute_query()
        return uploaded.serverRelativeUrl
    except Exception as exc:
        raise SharePointError(f"SharePoint upload failed for {filename}: {exc}") from exc


def list_files(folder_relative_path: str = "") -> list[dict]:
    """Lists files in `<SHAREPOINT_REPORTS_FOLDER>/<folder_relative_path>`."""
    settings = get_settings()
    ctx = _get_client_context()
    target_folder_url = "/".join(
        part.strip("/") for part in (settings.sharepoint_reports_folder, folder_relative_path) if part
    )
    try:
        folder = ctx.web.get_folder_by_server_relative_url(target_folder_url)
        files = folder.files.get().execute_query()
        return [{"name": f.name, "url": f.serverRelativeUrl, "size": f.length} for f in files]
    except Exception as exc:
        raise SharePointError(f"SharePoint list failed for {target_folder_url}: {exc}") from exc


def list_folder(folder_path: str) -> list[dict]:
    """Lists both files and subfolders at an arbitrary server-relative folder
    path anywhere in the configured site (unlike `list_files`, this is not
    scoped to `SHAREPOINT_REPORTS_FOLDER`) — used for browsing/importing
    existing vendor documents (position papers, notes, etc.) into the CRM.
    """
    ctx = _get_client_context()
    folder_path = folder_path.strip("/")
    try:
        folder = ctx.web.get_folder_by_server_relative_url(folder_path)
        folder.expand(["Folders", "Files"]).get().execute_query()
        entries = [
            {"name": f.name, "url": f.serverRelativeUrl, "is_folder": True, "size": None} for f in folder.folders
        ]
        entries += [
            {"name": f.name, "url": f.serverRelativeUrl, "is_folder": False, "size": f.length}
            for f in folder.files
        ]
        return entries
    except Exception as exc:
        raise SharePointError(f"SharePoint browse failed for '{folder_path or '/'}': {exc}") from exc


def download_file(server_relative_url: str) -> bytes:
    """Downloads a file by its SharePoint server-relative URL (as returned by
    `upload_file`/`list_files`)."""
    ctx = _get_client_context()
    try:
        from io import BytesIO

        buf = BytesIO()
        ctx.web.get_file_by_server_relative_url(server_relative_url).download(buf).execute_query()
        return buf.getvalue()
    except Exception as exc:
        raise SharePointError(f"SharePoint download failed for {server_relative_url}: {exc}") from exc
