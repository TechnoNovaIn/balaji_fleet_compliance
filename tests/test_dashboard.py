"""Challan landing and redirection tests (dashboard removed as requested)."""
from datetime import datetime, timezone
from app.extensions import db
from app.models.challan import Challan
from app.models.payment import Payment


def test_root_redirects_to_challans(client, admin_user):
    """Test that accessing root / redirects directly to challans."""
    client.post(
        "/auth/login",
        data={"username": "admin_ceo", "password": "SecureAdmin#2026"},
        follow_redirects=True,
    )
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/challans" in resp.location


def test_challans_page_displays_data(client, admin_user, sample_vehicle, sample_challan):
    """Test that challans page renders vehicle, violation, and penalty metrics."""
    client.post(
        "/auth/login",
        data={"username": "admin_ceo", "password": "SecureAdmin#2026"},
        follow_redirects=True,
    )
    resp = client.get("/challans/")
    assert resp.status_code == 200

    # Verify vehicle registration appears
    assert b"MH 12 AB 1234" in resp.data or b"MH12AB1234" in resp.data
    # Verify challan violation
    assert b"Over-speeding" in resp.data
    # Verify fine amount
    assert b"2,000.00" in resp.data


def test_check_live_endpoint(client, admin_user, sample_vehicle):
    """Test that triggering a live challan check works without error."""
    client.post(
        "/auth/login",
        data={"username": "admin_ceo", "password": "SecureAdmin#2026"},
        follow_redirects=True,
    )
    resp = client.post(
        f"/challans/check-live/{sample_vehicle.id}",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Live check for" in resp.data or b"Live check completed" in resp.data
