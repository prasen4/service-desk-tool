"""Tests for the Vendor CRM feature: profiles, notes, attachments, status pipeline."""

from __future__ import annotations

import io

import pytest


def _unique_vendor(name: str) -> str:
    # Each test uses its own vendor name so runs don't interfere with each other.
    return name


def test_list_statuses(client):
    resp = client.get("/api/vendors/statuses")
    assert resp.status_code == 200
    statuses = resp.json()["statuses"]
    values = {s["value"] for s in statuses}
    assert "identified" in values
    assert "selected" in values
    assert all("label" in s for s in statuses)


def test_add_note_creates_vendor_and_appears_in_profile(client):
    vendor = _unique_vendor("Test Vendor Alpha")
    resp = client.post(
        f"/api/vendors/{vendor}/notes",
        data={"body": "First contact made.", "author": "alice"},
    )
    assert resp.status_code == 200
    note = resp.json()
    assert note["body"] == "First contact made."
    assert note["author"] == "alice"
    assert note["attachments"] == []

    profile_resp = client.get(f"/api/vendors/{vendor}/profile")
    assert profile_resp.status_code == 200
    profile = profile_resp.json()
    assert profile["name"] == vendor
    assert profile["status"] == "identified"
    assert len(profile["notes"]) == 1
    assert profile["notes"][0]["body"] == "First contact made."


def test_note_requires_body_or_file(client):
    vendor = _unique_vendor("Test Vendor NoBody")
    resp = client.post(f"/api/vendors/{vendor}/notes", data={"body": "", "author": ""})
    assert resp.status_code == 400


def test_note_with_attachment_upload_and_download(client):
    vendor = _unique_vendor("Test Vendor Attach")
    file_content = b"hello attachment content"
    resp = client.post(
        f"/api/vendors/{vendor}/notes",
        data={"body": "See attached.", "author": "bob"},
        files={"file": ("notes.txt", io.BytesIO(file_content), "text/plain")},
    )
    assert resp.status_code == 200
    note = resp.json()
    assert len(note["attachments"]) == 1
    attachment_id = note["attachments"][0]["id"]
    assert note["attachments"][0]["filename"] == "notes.txt"

    download = client.get(f"/api/vendors/{vendor}/attachments/{attachment_id}")
    assert download.status_code == 200
    assert download.content == file_content


def test_attachment_rejects_disallowed_extension(client):
    vendor = _unique_vendor("Test Vendor BadExt")
    resp = client.post(
        f"/api/vendors/{vendor}/notes",
        data={"body": "Malicious upload attempt.", "author": "eve"},
        files={"file": ("payload.exe", io.BytesIO(b"MZ..."), "application/octet-stream")},
    )
    assert resp.status_code == 400
    assert "not allowed" in resp.json()["detail"]


def test_attachment_rejects_oversized_file(client, monkeypatch):
    from tech_desk import vendor_profiles

    monkeypatch.setattr(vendor_profiles, "MAX_UPLOAD_BYTES", 10)
    vendor = _unique_vendor("Test Vendor TooBig")
    resp = client.post(
        f"/api/vendors/{vendor}/notes",
        data={"body": "Big file.", "author": "carl"},
        files={"file": ("big.txt", io.BytesIO(b"x" * 1000), "text/plain")},
    )
    assert resp.status_code == 400
    assert "exceeds" in resp.json()["detail"]


def test_status_transition_recorded_in_history(client):
    vendor = _unique_vendor("Test Vendor Status")
    # Creating a note first establishes the vendor row.
    client.post(f"/api/vendors/{vendor}/notes", data={"body": "Kickoff.", "author": "dana"})

    resp = client.post(
        f"/api/vendors/{vendor}/status",
        json={"status": "outreach_sent", "note": "Sent intro email", "changed_by": "dana"},
    )
    assert resp.status_code == 200
    event = resp.json()
    assert event["status"] == "outreach_sent"
    assert event["status_label"] == "Outreach Sent"

    profile = client.get(f"/api/vendors/{vendor}/profile").json()
    assert profile["status"] == "outreach_sent"
    assert len(profile["status_history"]) == 1
    assert profile["status_history"][0]["note"] == "Sent intro email"


def test_status_transition_rejects_invalid_status(client):
    vendor = _unique_vendor("Test Vendor BadStatus")
    resp = client.post(
        f"/api/vendors/{vendor}/status",
        json={"status": "not-a-real-status", "note": "", "changed_by": ""},
    )
    assert resp.status_code == 400


def test_delete_note_removes_it_and_its_attachment(client):
    vendor = _unique_vendor("Test Vendor DeleteNote")
    create = client.post(
        f"/api/vendors/{vendor}/notes",
        data={"body": "Temporary note.", "author": "erin"},
        files={"file": ("temp.txt", io.BytesIO(b"temp content"), "text/plain")},
    )
    note_id = create.json()["id"]
    attachment_id = create.json()["attachments"][0]["id"]

    delete_resp = client.delete(f"/api/vendors/{vendor}/notes/{note_id}")
    assert delete_resp.status_code == 200

    second_delete = client.delete(f"/api/vendors/{vendor}/notes/{note_id}")
    assert second_delete.status_code == 404

    download = client.get(f"/api/vendors/{vendor}/attachments/{attachment_id}")
    assert download.status_code == 404

    profile = client.get(f"/api/vendors/{vendor}/profile").json()
    assert profile["notes"] == []


def test_delete_attachment_standalone(client):
    vendor = _unique_vendor("Test Vendor DeleteAttachment")
    create = client.post(
        f"/api/vendors/{vendor}/notes",
        data={"body": "Has a file.", "author": "frank"},
        files={"file": ("keep-note.txt", io.BytesIO(b"data"), "text/plain")},
    )
    attachment_id = create.json()["attachments"][0]["id"]

    delete_resp = client.delete(f"/api/vendors/{vendor}/attachments/{attachment_id}")
    assert delete_resp.status_code == 200

    profile = client.get(f"/api/vendors/{vendor}/profile").json()
    assert len(profile["notes"]) == 1
    assert profile["notes"][0]["attachments"] == []


def test_vendor_not_found_returns_404(client):
    resp = client.get("/api/vendors/Definitely Not A Vendor XYZ/profile")
    assert resp.status_code == 404


def test_list_vendor_profiles_filters_by_status(client):
    vendor = _unique_vendor("Test Vendor FilterStatus")
    client.post(f"/api/vendors/{vendor}/notes", data={"body": "Init.", "author": ""})
    client.post(
        f"/api/vendors/{vendor}/status",
        json={"status": "selected", "note": "", "changed_by": ""},
    )

    resp = client.get("/api/vendors/profiles", params={"status": "selected"})
    assert resp.status_code == 200
    names = {v["name"] for v in resp.json()["vendors"]}
    assert vendor in names

    resp_other = client.get("/api/vendors/profiles", params={"status": "rejected"})
    names_other = {v["name"] for v in resp_other.json()["vendors"]}
    assert vendor not in names_other


def test_vendors_summary_endpoint_shape(client):
    resp = client.get("/api/vendors")
    assert resp.status_code == 200
    body = resp.json()
    assert "vendors" in body
    assert "total" in body
    assert isinstance(body["vendors"], list)
