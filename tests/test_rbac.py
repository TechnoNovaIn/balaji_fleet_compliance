"""Role-based access control (RBAC) and production hardening test suite."""
import pytest
from app import create_app
from app.models.user import User


def test_user_role_methods(admin_user, manager_user, accounts_user, viewer_user):
    """Test User model role helper methods across all 4 RBAC roles."""
    assert admin_user.is_admin is True
    assert admin_user.has_role("admin") is True
    assert admin_user.role_label == "Administrator"
    assert admin_user.is_manager is True
    assert admin_user.is_accounts is True
    assert admin_user.is_viewer is False

    assert manager_user.is_admin is False
    assert manager_user.is_manager is True
    assert manager_user.is_accounts is False
    assert manager_user.role_label == "Transport Manager"

    assert accounts_user.is_admin is False
    assert accounts_user.is_accounts is True
    assert accounts_user.is_manager is False
    assert accounts_user.role_label == "Accounts Team"

    assert viewer_user.is_admin is False
    assert viewer_user.is_viewer is True
    assert viewer_user.is_manager is False
    assert viewer_user.is_accounts is False
    assert viewer_user.role_label == "Viewer"


def test_unauthenticated_access_redirects(client):
    """Test that all protected routes redirect unauthenticated visitors."""
    endpoints = ["/", "/vehicles/", "/challans/", "/payments/", "/reports/"]
    for ep in endpoints:
        resp = client.get(ep)
        assert resp.status_code == 302
        assert "/auth/login" in resp.location


def test_authenticated_viewer_can_view_dashboard_but_cannot_modify(client, viewer_user):
    """Test that Viewer can view pages but receives 403 on mutating endpoints."""
    client.post(
        "/auth/login",
        data={"username": "auditor_viewer", "password": "ViewerPass#2026"},
        follow_redirects=True,
    )
    resp = client.get("/challans/")
    assert resp.status_code == 200
    assert b"Viewer" in resp.data

    assert client.post("/challans/acknowledge-all").status_code == 403
    assert client.post("/vehicles/scan-fleet", data={"batch_size": "all"}).status_code == 403
    assert client.post("/payments/record", data={}).status_code == 403
    assert client.post("/reports/import-signoff", data={}).status_code == 403


def test_production_requires_non_default_secret_key(monkeypatch):
    """Verify ProductionConfig refuses to boot without an explicit non-default SECRET_KEY."""
    from config import ProductionConfig, DEFAULT_DEV_SECRET_KEY

    monkeypatch.setattr(ProductionConfig, "SECRET_KEY", None)
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app("production")

    monkeypatch.setattr(ProductionConfig, "SECRET_KEY", DEFAULT_DEV_SECRET_KEY)
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app("production")
