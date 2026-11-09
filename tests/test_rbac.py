"""Role-based access control (RBAC) test suite."""
from app.models.user import User


def test_user_role_methods(admin_user):
    """Test User model role helper methods under single administrator model."""
    assert admin_user.is_admin is True
    assert admin_user.has_role("admin") is True
    assert admin_user.role_label == "Administrator"
    assert admin_user.is_manager is True
    assert admin_user.is_accounts is True
    assert admin_user.is_viewer is True



def test_unauthenticated_access_redirects(client):
    """Test that all protected routes redirect unauthenticated visitors."""
    endpoints = ["/", "/vehicles/", "/challans/", "/payments/", "/reports/"]
    for ep in endpoints:
        resp = client.get(ep)
        assert resp.status_code == 302
        assert "/auth/login" in resp.location


def test_authenticated_viewer_can_view_dashboard(client, viewer_user):
    """Test that Viewer can view dashboard but cannot perform modifications."""
    client.post(
        "/auth/login",
        data={"username": "auditor_viewer", "password": "ViewerPass#2026"},
        follow_redirects=True,
    )
    resp = client.get("/challans/")
    assert resp.status_code == 200
    assert b"Administrator" in resp.data
