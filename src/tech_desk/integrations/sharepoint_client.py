"""SharePoint read/write integration via Microsoft Graph API, using Azure AD
app-only auth (client credentials grant).

Inert unless all four `SHAREPOINT_*` settings are configured (see
`config.Settings`). Requires the optional `sharepoint` extra (`msal`; HTTP
calls use `httpx`, already a core dependency); the `msal` import is done
lazily inside `_acquire_token` so the rest of the app works fine without it
installed.

Deliberately uses Microsoft Graph rather than the legacy SharePoint REST/CSOM
API (`_api/...`, as used by `office365-rest-python-client`), because:
  - the legacy REST/CSOM app-only auth model requires a **certificate** for
    Entra ID app registrations — a plain client secret is rejected outright
    ("Access Denied") — whereas Graph works fine with a secret.
  - Graph is the surface that the narrowly-scoped `Sites.Selected`
    application permission (typically what's granted for this kind of
    single-site integration) actually authorizes.

IMPORTANT — `Sites.Selected` needs a *second* grant step: admin-consenting
the permission in Entra ID is not sufficient on its own. An admin must also
explicitly grant this app access to the specific site via
`POST https://graph.microsoft.com/v1.0/sites/{siteId}/permissions`
(see https://learn.microsoft.com/graph/permissions-selected-overview) —
without that, every call below fails with 403 even though the app looks
fully consented in the Azure Portal.

Usage once configured:
    from tech_desk.integrations import sharepoint_client as sp
    sp.upload_file("weekly", "report.docx", pathlib.Path("report.docx").read_bytes())
"""

from __future__ import annotations

import logging
from urllib.parse import quote, urlparse

from tech_desk.config import get_settings

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_DEFAULT_LIBRARY_NAMES = {"shared documents", "documents"}

# Process-lifetime caches for Graph site/drive IDs — these rarely change, and
# re-resolving them on every call would double the number of Graph requests.
_site_id_cache: dict[str, str] = {}
_drive_id_cache: dict[tuple[str, str], str] = {}


class SharePointError(Exception):
    """Raised for any SharePoint configuration or API failure."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


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

    authority = f"https://login.microsoftonline.com/{settings.sharepoint_tenant_id}"
    app = msal.ConfidentialClientApplication(
        client_id=settings.sharepoint_client_id,
        client_credential=settings.sharepoint_client_secret,
        authority=authority,
    )
    result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if "access_token" not in result:
        raise SharePointError(
            f"Failed to acquire SharePoint app-only token: "
            f"{result.get('error')}: {result.get('error_description')}"
        )
    return result["access_token"]


def _graph_call(method: str, path: str, **kwargs):
    """Calls Microsoft Graph and returns the raw response, raising
    `SharePointError` on any non-2xx status (with a specific hint on 403,
    the most common misconfiguration for `Sites.Selected` apps)."""
    import httpx

    url = path if path.startswith("http") else f"{GRAPH_BASE}{path}"
    headers = kwargs.pop("headers", {}) or {}
    headers["Authorization"] = f"Bearer {_acquire_token()}"
    response = httpx.request(method, url, headers=headers, timeout=60, **kwargs)
    if response.status_code == 403:
        raise SharePointError(
            "SharePoint access was denied (403). The app's Sites.Selected permission is likely "
            "consented in Entra ID but not yet granted access to this specific site — an admin "
            "must additionally call POST /sites/{site-id}/permissions to grant this app access "
            "(see https://learn.microsoft.com/graph/permissions-selected-overview).",
            status_code=403,
        )
    if response.status_code >= 400:
        raise SharePointError(
            f"Graph API request failed ({response.status_code}) for {url}: {response.text[:500]}",
            status_code=response.status_code,
        )
    return response


def _graph_json(method: str, path: str, **kwargs) -> dict:
    response = _graph_call(method, path, **kwargs)
    return response.json() if response.content else {}


def _site_id() -> str:
    settings = get_settings()
    cache_key = settings.sharepoint_site_url or ""
    if cache_key in _site_id_cache:
        return _site_id_cache[cache_key]
    parsed = urlparse(settings.sharepoint_site_url)
    site_path = parsed.path.strip("/")  # e.g. "sites/PortfolioProspecting"
    encoded_path = "/".join(quote(seg, safe="") for seg in site_path.split("/") if seg)
    data = _graph_json("GET", f"/sites/{parsed.netloc}:/{encoded_path}")
    site_id = data["id"]
    _site_id_cache[cache_key] = site_id
    return site_id


def _drive_base(library_name: str) -> str:
    """Returns the Graph API path prefix (`/sites/{id}/drive` or
    `/drives/{drive-id}`) addressing the named document library."""
    site_id = _site_id()
    if not library_name or library_name.strip().lower() in _DEFAULT_LIBRARY_NAMES:
        return f"/sites/{site_id}/drive"
    cache_key = (site_id, library_name.lower())
    if cache_key in _drive_id_cache:
        return f"/drives/{_drive_id_cache[cache_key]}"
    data = _graph_json("GET", f"/sites/{site_id}/drives")
    for drive in data.get("value", []):
        if drive.get("name", "").lower() == library_name.lower():
            _drive_id_cache[cache_key] = drive["id"]
            return f"/drives/{drive['id']}"
    raise SharePointError(f"No document library named '{library_name}' found on the configured SharePoint site.")


def _split_library_and_path(path: str) -> tuple[str, str]:
    """Splits a friendly path like 'Shared Documents/Vendor X/notes.docx'
    into (drive_base, item_path), where item_path is relative to that
    library's root ('Vendor X/notes.docx' in the example)."""
    parts = [p for p in path.strip("/").split("/") if p]
    if not parts:
        return _drive_base(""), ""
    return _drive_base(parts[0]), "/".join(parts[1:])


def _item_path_segment(item_path: str) -> str:
    """Graph's path-addressing syntax: `root:/a/b/c:` for a non-empty path,
    or plain `root` for the library root."""
    item_path = item_path.strip("/")
    if not item_path:
        return "root"
    encoded = "/".join(quote(seg, safe="") for seg in item_path.split("/"))
    return f"root:/{encoded}:"


def _ensure_folder_path(drive_base: str, path: str) -> None:
    """Creates each missing folder segment of `path` (relative to the given
    drive), tolerating segments that already exist."""
    accumulated = ""
    for segment in (s for s in path.strip("/").split("/") if s):
        parent = accumulated
        accumulated = f"{accumulated}/{segment}" if accumulated else segment
        parent_segment = _item_path_segment(parent)
        try:
            _graph_json(
                "POST",
                f"{drive_base}/{parent_segment}/children",
                json={"name": segment, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"},
            )
        except SharePointError as exc:
            if exc.status_code != 409:  # 409 Conflict = folder already exists
                raise


def upload_file(folder_relative_path: str, filename: str, content: bytes) -> str:
    """Uploads `content` as `filename` into
    `<SHAREPOINT_REPORTS_FOLDER>/<folder_relative_path>` (folders are created
    automatically if they don't exist). Returns a full, clickable URL to the
    uploaded file.
    """
    _require_configured()
    settings = get_settings()
    full_path = "/".join(
        part.strip("/") for part in (settings.sharepoint_reports_folder, folder_relative_path) if part
    )
    try:
        drive_base, item_path = _split_library_and_path(full_path)
        _ensure_folder_path(drive_base, item_path)
        upload_path = f"{item_path}/{filename}" if item_path else filename
        seg = _item_path_segment(upload_path)
        data = _graph_json(
            "PUT",
            f"{drive_base}/{seg}/content",
            content=content,
            headers={"Content-Type": "application/octet-stream"},
        )
        return data.get("webUrl") or f"{settings.sharepoint_site_url.rstrip('/')}/{full_path}/{filename}"
    except SharePointError:
        raise
    except Exception as exc:
        logger.exception("SharePoint upload failed for %s at %s", filename, full_path)
        raise SharePointError(f"SharePoint upload failed for {filename}: {exc}") from exc


def _list(full_path: str) -> list[dict]:
    drive_base, item_path = _split_library_and_path(full_path)
    seg = _item_path_segment(item_path)
    try:
        data = _graph_json("GET", f"{drive_base}/{seg}/children")
    except SharePointError:
        raise
    except Exception as exc:
        logger.exception("SharePoint list failed for %s", full_path)
        raise SharePointError(f"SharePoint list failed for {full_path}: {exc}") from exc
    entries = []
    for child in data.get("value", []):
        child_path = f"{full_path}/{child['name']}" if full_path else child["name"]
        entries.append(
            {
                "name": child["name"],
                "url": child_path,
                "is_folder": "folder" in child,
                "size": child.get("size"),
            }
        )
    return entries


def list_files(folder_relative_path: str = "") -> list[dict]:
    """Lists files in `<SHAREPOINT_REPORTS_FOLDER>/<folder_relative_path>`."""
    _require_configured()
    settings = get_settings()
    full_path = "/".join(
        part.strip("/") for part in (settings.sharepoint_reports_folder, folder_relative_path) if part
    )
    return [
        {"name": e["name"], "url": e["url"], "size": e["size"]} for e in _list(full_path) if not e["is_folder"]
    ]


def list_folder(folder_path: str) -> list[dict]:
    """Lists both files and subfolders at an arbitrary friendly folder path
    anywhere in the configured site (unlike `list_files`, this is not scoped
    to `SHAREPOINT_REPORTS_FOLDER`) — used for browsing/importing existing
    vendor documents (position papers, notes, etc.) into the CRM.
    """
    _require_configured()
    try:
        return _list(folder_path.strip("/"))
    except SharePointError as exc:
        raise SharePointError(f"SharePoint browse failed for '{folder_path or '/'}': {exc}") from exc


def download_file(path: str) -> bytes:
    """Downloads a file by the friendly path returned in `list_folder`'s or
    `list_files`'s `url` field."""
    _require_configured()
    try:
        drive_base, item_path = _split_library_and_path(path)
        seg = _item_path_segment(item_path)
        response = _graph_call("GET", f"{drive_base}/{seg}/content", follow_redirects=True)
        return response.content
    except SharePointError:
        raise
    except Exception as exc:
        raise SharePointError(f"SharePoint download failed for {path}: {exc}") from exc
