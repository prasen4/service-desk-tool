from __future__ import annotations

from tech_desk import __version__


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert body["api_key_configured"] is True  # dummy key set in conftest


def test_ready_reports_checks(client):
    resp = client.get("/api/ready")
    assert resp.status_code == 200
    checks = resp.json()["checks"]
    assert checks["database"]["ok"] is True
    assert checks["disk_writable"]["ok"] is True


def test_list_desks(client):
    resp = client.get("/api/desks")
    assert resp.status_code == 200
    desks = resp.json()["desks"]
    assert len(desks) == 5
    assert {d["code"] for d in desks} == {"I", "M", "ET", "APPS", "HCLS"}


def test_models_catalog(client):
    resp = client.get("/api/models")
    assert resp.status_code == 200
    body = resp.json()
    assert body["desk_count"] == 5
    assert any(p["id"] == "openai" for p in body["providers"])
    assert body["current"]["configured"] is True


def test_cost_estimate_endpoint(client):
    resp = client.post("/api/cost-estimate", json={"model": "gpt-4o", "horizon": "monthly", "desk_count": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["desk_count"] == 5
    assert body["horizon"] == "monthly"
    assert body["cost_per_run"] > 0


def test_jobs_endpoint_empty_ok(client):
    resp = client.get("/api/jobs")
    assert resp.status_code == 200
    assert "jobs" in resp.json()


def test_vendor_updates_404_for_unknown(client):
    resp = client.get("/api/vendors/DefinitelyNotARealVendor/updates")
    assert resp.status_code == 404


def test_unknown_desk_returns_400(client):
    resp = client.post("/api/research/run", json={"period": "daily", "desk_ids": ["not-a-desk"]})
    assert resp.status_code == 400
    assert "Unknown desk" in resp.json()["detail"]


def test_add_desk_vendor_success(client, monkeypatch):
    """Route wiring only — the actual file mutation is covered against a tmp
    config copy in test_config.py, so this test never touches the real
    config/tech_desks.yaml on disk."""
    import tech_desk.api.main as main_module

    calls = {}

    def fake_add(desk_id, vendor):
        calls["desk_id"] = desk_id
        calls["vendor"] = vendor
        from tech_desk.config import list_desk_definitions

        return next(d for d in list_desk_definitions() if d.id == desk_id)

    monkeypatch.setattr(main_module, "add_vendor_to_desk", fake_add)

    resp = client.post("/api/desks/applications/vendors", json={"vendor": "Snowflake"})
    assert resp.status_code == 200
    assert resp.json()["desk"]["id"] == "applications"
    assert calls == {"desk_id": "applications", "vendor": "Snowflake"}


def test_add_desk_vendor_unknown_desk_404(client, monkeypatch):
    import tech_desk.api.main as main_module

    def fake_add(desk_id, vendor):
        raise LookupError(f"Unknown desk id: '{desk_id}'")

    monkeypatch.setattr(main_module, "add_vendor_to_desk", fake_add)
    resp = client.post("/api/desks/not-real/vendors", json={"vendor": "Snowflake"})
    assert resp.status_code == 404


def test_add_desk_vendor_duplicate_400(client, monkeypatch):
    import tech_desk.api.main as main_module

    def fake_add(desk_id, vendor):
        raise ValueError("already tracked")

    monkeypatch.setattr(main_module, "add_vendor_to_desk", fake_add)
    resp = client.post("/api/desks/applications/vendors", json={"vendor": "Snowflake"})
    assert resp.status_code == 400


def test_add_desk_vendor_requires_name(client):
    resp = client.post("/api/desks/applications/vendors", json={"vendor": ""})
    assert resp.status_code == 422


def test_download_unknown_format_400(client):
    # Report 999999 doesn't exist -> 404 before format check
    resp = client.get("/api/reports/999999/download/pdf")
    assert resp.status_code == 404
