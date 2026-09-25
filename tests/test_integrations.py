"""Regression tests for the Okta login + SharePoint integration scaffolding.
These must all pass with zero configuration (the default state) — the
features are strictly opt-in via .env and must never break existing behavior.
"""
from __future__ import annotations

from tech_desk.config import get_settings
from tech_desk.integrations import okta_auth, sharepoint_client


def test_okta_not_configured_by_default():
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.auth_enabled is False
    assert settings.okta_configured is False
    assert okta_auth.is_configured() is False


def test_sharepoint_not_configured_by_default():
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.sharepoint_configured is False
    assert sharepoint_client.is_configured() is False


def test_okta_helpers_raise_clear_error_when_unconfigured():
    import pytest

    with pytest.raises(okta_auth.OktaAuthError):
        okta_auth.build_authorize_url("state")
    with pytest.raises(okta_auth.OktaAuthError):
        okta_auth.exchange_code_for_token("code")


def test_sharepoint_helpers_raise_clear_error_when_unconfigured():
    import pytest

    with pytest.raises(sharepoint_client.SharePointError):
        sharepoint_client.upload_file("weekly", "report.docx", b"data")


def test_session_cookie_round_trip():
    cookie = okta_auth.create_session_cookie({"email": "user@example.com", "name": "Test User"})
    user = okta_auth.verify_session_cookie(cookie)
    assert user == {"email": "user@example.com", "name": "Test User"}


def test_session_cookie_rejects_tampered_value():
    cookie = okta_auth.create_session_cookie({"email": "user@example.com"})
    payload_b64, _sig = cookie.split(".", 1)
    tampered = f"{payload_b64}.deadbeef"
    assert okta_auth.verify_session_cookie(tampered) is None


def test_auth_status_endpoint_disabled_by_default(client):
    resp = client.get("/api/auth/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"enabled": False, "logged_in": False, "user": None}


def test_login_route_400_when_unconfigured(client):
    resp = client.get("/api/auth/login", follow_redirects=False)
    assert resp.status_code == 400
