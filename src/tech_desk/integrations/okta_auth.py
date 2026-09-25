"""Okta OIDC login for the Tech Desk app itself (Authorization Code flow).

This is completely separate from the SharePoint integration
(`sharepoint_client.py`) — SharePoint uses its own Azure AD app-only
credentials regardless of how a user logs into this tool.

Inert unless `AUTH_ENABLED=true` and all `OKTA_*` settings are configured; see
`config.Settings.okta_configured`. No new third-party dependencies — uses
`httpx` (already required) for the OAuth calls and a small stdlib
HMAC-signed cookie for the session, keyed off `TECH_DESK_SECRET_KEY`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from urllib.parse import urlencode

import httpx

from tech_desk.config import get_settings

logger = logging.getLogger(__name__)

SESSION_MAX_AGE_SECONDS = 60 * 60 * 12  # 12 hours


class OktaAuthError(Exception):
    """Raised for any Okta configuration or OAuth exchange failure."""


def is_configured() -> bool:
    settings = get_settings()
    return settings.auth_enabled and settings.okta_configured


def _require_configured() -> None:
    if not is_configured():
        raise OktaAuthError(
            "Okta login is not enabled — set AUTH_ENABLED=true and OKTA_ISSUER, OKTA_CLIENT_ID, "
            "OKTA_CLIENT_SECRET, OKTA_REDIRECT_URI in .env."
        )


def build_authorize_url(state: str) -> str:
    _require_configured()
    settings = get_settings()
    params = {
        "client_id": settings.okta_client_id,
        "response_type": "code",
        "scope": "openid profile email",
        "redirect_uri": settings.okta_redirect_uri,
        "state": state,
    }
    return f"{settings.okta_issuer}/v1/authorize?{urlencode(params)}"


def exchange_code_for_token(code: str) -> dict:
    _require_configured()
    settings = get_settings()
    resp = httpx.post(
        f"{settings.okta_issuer}/v1/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.okta_redirect_uri,
        },
        auth=(settings.okta_client_id, settings.okta_client_secret),
        headers={"Accept": "application/json"},
        timeout=10.0,
    )
    if resp.status_code != 200:
        raise OktaAuthError(f"Okta token exchange failed ({resp.status_code}): {resp.text[:300]}")
    return resp.json()


def fetch_userinfo(access_token: str) -> dict:
    _require_configured()
    settings = get_settings()
    resp = httpx.get(
        f"{settings.okta_issuer}/v1/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10.0,
    )
    if resp.status_code != 200:
        raise OktaAuthError(f"Okta userinfo fetch failed ({resp.status_code}): {resp.text[:300]}")
    return resp.json()


def _signing_key() -> bytes:
    return get_settings().tech_desk_secret_key.encode("utf-8")


def create_session_cookie(user_info: dict) -> str:
    """HMAC-signed, base64-encoded session payload — not encrypted (no PII
    beyond what's already visible in the Okta userinfo response), but
    tamper-proof and expiring."""
    payload = {"user": user_info, "exp": int(time.time()) + SESSION_MAX_AGE_SECONDS}
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode("ascii")
    signature = hmac.new(_signing_key(), payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{signature}"


def verify_session_cookie(cookie_value: str) -> dict | None:
    try:
        payload_b64, signature = cookie_value.split(".", 1)
    except ValueError:
        return None
    expected = hmac.new(_signing_key(), payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(payload_b64.encode("ascii")))
    except (ValueError, json.JSONDecodeError):
        return None
    if payload.get("exp", 0) < time.time():
        return None
    return payload.get("user")
