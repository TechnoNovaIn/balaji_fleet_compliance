"""Database models unit tests."""
import pytest
from datetime import datetime, timezone, date
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.challan import Challan
from app.models.payment import Payment
from app.models.monitoring_log import MonitoringLog
from app.models.audit_log import AuditLog


def test_user_password_hashing(app):
    """Test secure password hashing and verification."""
    user = User(username="test_hasher", full_name="Hasher", role="viewer")
    user.set_password("SecurePassword#123")
    assert user.password_hash != "SecurePassword#123"
    assert user.check_password("SecurePassword#123") is True
    assert user.check_password("WrongPassword") is False


def test_vehicle_registration_normalization():
    """Test normalization of Indian vehicle registration numbers."""
    assert Vehicle.normalize_registration("KA 06 aB 1234") == "KA06AB1234"
    assert Vehicle.normalize_registration("DL 01 / XY 9999") == "DL01XY9999"
    assert Vehicle.normalize_registration("ka.04-m.4321") == "KA04M4321"
    assert Vehicle.format_registration("KA06AB1234") == "KA 06 AB 1234"


def test_vehicle_duplicate_prevention(app, sample_vehicle):
    """Test that duplicate active vehicles with same normalized registration are prevented."""
    dup_veh = Vehicle(
        registration_number="MH12AB1234",  # Same as sample_vehicle
        vehicle_type="Truck",
        is_active=True,
    )
    db.session.add(dup_veh)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_challan_penalty_and_payment_sync(app, sample_challan, accounts_user, admin_user):
    """Test challan remaining penalty calculation and payment status sync."""
    assert sample_challan.remaining_penalty == 2000.00
    assert sample_challan.payment_status == Challan.PAYMENT_UNPAID

    # Record partial payment (₹1200)
    p1 = Payment(
        challan_id=sample_challan.id,
        amount_paid=1200.00,
        payment_date=date.today(),
        payment_reference="UPI-REF-001",
        recorded_by_user_id=accounts_user.id,
        verification_status=Payment.VERIFICATION_PENDING,
    )
    db.session.add(p1)
    db.session.commit()

    # Before verification, total_paid does not increase (only verified payments count)
    assert sample_challan.total_paid == 0.00

    # Mark verified by admin
    p1.mark_verified(admin_user, notes="Bank statement verified")
    db.session.commit()

    assert sample_challan.total_paid == 1200.00
    assert sample_challan.remaining_penalty == 800.00
    assert sample_challan.payment_status == Challan.PAYMENT_PARTIALLY_PAID

    # Record remaining settlement (₹800)
    p2 = Payment(
        challan_id=sample_challan.id,
        amount_paid=800.00,
        payment_date=date.today(),
        payment_reference="UPI-REF-002",
        recorded_by_user_id=accounts_user.id,
        verification_status=Payment.VERIFICATION_PENDING,
    )
    db.session.add(p2)
    db.session.commit()
    p2.mark_verified(admin_user)
    db.session.commit()

    assert sample_challan.total_paid == 2000.00
    assert sample_challan.remaining_penalty == 0.00
    assert sample_challan.payment_status == Challan.PAYMENT_PAID
    assert sample_challan.status == Challan.STATUS_PAID


def test_monitoring_log_failed_check(app, sample_vehicle):
    """Test that a failed monitoring check records error details and is never considered successful."""
    log = MonitoringLog(
        vehicle_id=sample_vehicle.id,
        check_start_time=datetime.now(timezone.utc),
        check_completion_time=datetime.now(timezone.utc),
        status=MonitoringLog.STATUS_FAILED,
        data_source="State e-Challan Gateway",
        error_details="Connection timeout: 504 Gateway Timeout from endpoint",
    )
    db.session.add(log)
    db.session.commit()

    assert log.is_successful is False
    assert "504 Gateway Timeout" in log.error_details


def test_audit_log_recording(app, admin_user):
    """Test that audit log records user actions immutably."""
    entry = AuditLog.record(
        action="VEHICLE_CREATED",
        user=admin_user,
        entity_type="Vehicle",
        entity_id="MH12AB1234",
        details={"owner": "Balaji Transports", "type": "Truck"},
        ip_address="127.0.0.1",
    )
    db.session.commit()

    saved = AuditLog.query.filter_by(action="VEHICLE_CREATED").first()
    assert saved is not None
    assert saved.user_id == admin_user.id
    assert saved.entity_id == "MH12AB1234"
    assert "Balaji Transports" in saved.details
