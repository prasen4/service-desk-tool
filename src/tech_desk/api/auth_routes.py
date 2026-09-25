"""Okta login routes. All routes are safe to mount unconditionally — they
check `okta_auth.is_configured()` internally and return a clear 400 if Okta
login isn't set up yet, so mounting this router is a no-op until AUTH_ENABLED
and the OKTA_* settings are all provided."""

from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from tech_desk.config import get_settings
from tech_desk.integrations import okta_auth

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])

SESSION_COOKIE = "techdesk_session"
STATE_COOKIE = "techdesk_oauth_state"


@router.get("/status")
async def auth_status(request: Request):
    settings = get_settings()
    if not okta_auth.is_configured():
        return {"enabled": False, "logged_in": False, "user": None}

    cookie = request.cookies.get(SESSION_COOKIE)
    user = okta_auth.verify_session_cookie(cookie) if cookie else None
    return {"enabled": True, "logged_in": user is not None, "user": user}


@router.get("/login")
async def login():
    if not okta_auth.is_configured():
        raise HTTPException(status_code=400, detail="Okta login is not configured.")
    state = secrets.token_urlsafe(24)
    response = RedirectResponse(okta_auth.build_authorize_url(state))
    response.set_cookie(STATE_COOKIE, state, httponly=True, max_age=600, samesite="lax")
    return response


@router.get("/callback")
async def callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
    if not okta_auth.is_configured():
        raise HTTPException(status_code=400, detail="Okta login is not configured.")
    if error:
        raise HTTPException(status_code=400, detail=f"Okta login failed: {error}")

    expected_state = request.cookies.get(STATE_COOKIE)
    if not code or not state or not expected_state or state != expected_state:
        raise HTTPException(status_code=400, detail="Invalid or missing OAuth state.")

    try:
        token_data = okta_auth.exchange_code_for_token(code)
        user_info = okta_auth.fetch_userinfo(token_data["access_token"])
    except okta_auth.OktaAuthError as exc:
        logger.warning("Okta login failed: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    session_cookie = okta_auth.create_session_cookie(user_info)
    response = RedirectResponse("/")
    response.set_cookie(
        SESSION_COOKIE, session_cookie, httponly=True, max_age=okta_auth.SESSION_MAX_AGE_SECONDS, samesite="lax"
    )
    response.delete_cookie(STATE_COOKIE)
    return response


@router.post("/logout")
async def logout():
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response
