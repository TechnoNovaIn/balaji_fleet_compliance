"""Pytest fixtures for Balaji Fleet Compliance System test suite."""
import pytest
from datetime import datetime, timezone, date
from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.challan import Challan
from app.models.payment import Payment
from app.models.monitoring_log import MonitoringLog


@pytest.fixture
def app():
    """Create test application instance with in-memory database."""
    application = create_app("testing")

    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    """Test HTTP client."""
    return app.test_client()


@pytest.fixture
def runner(app):
    """Test CLI runner."""
    return app.test_cli_runner()


@pytest.fixture
def admin_user(app):
    """Fixture providing a CEO / Administrator user."""
    user = User(
        username="admin_ceo",
        full_name="Balaji Admin CEO",
        email="ceo@balajitransports.com",
        role=User.ROLE_ADMIN,
        is_active=True,
    )
    user.set_password("SecureAdmin#2026")
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def manager_user(app):
    """Fixture providing a Transport Manager user."""
    user = User(
        username="transport_mgr",
        full_name="Fleet Manager Rajesh",
        email="manager@balajitransports.com",
        role=User.ROLE_MANAGER,
        is_active=True,
    )
    user.set_password("ManagerPass#2026")
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def accounts_user(app):
    """Fixture providing an Accounts Team user."""
    user = User(
        username="accounts_officer",
        full_name="Accounts Executive Pooja",
        email="accounts@balajitransports.com",
        role=User.ROLE_ACCOUNTS,
        is_active=True,
    )
    user.set_password("AccountsPass#2026")
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def viewer_user(app):
    """Fixture providing a read-only Viewer user."""
    user = User(
        username="auditor_viewer",
        full_name="External Auditor Suresh",
        email="auditor@balajitransports.com",
        role=User.ROLE_VIEWER,
        is_active=True,
    )
    user.set_password("ViewerPass#2026")
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def sample_vehicle(app):
    """Fixture providing a sample active Truck."""
    veh = Vehicle(
        registration_number="MH12AB1234",
        display_reg_number="MH 12 AB 1234",
        vehicle_type=Vehicle.TYPE_TRUCK,
        make_model="Tata Prima 4028.S",
        registered_owner="Balaji Transports Pvt Ltd",
        department="Pune Logistics Hub",
        assigned_manager="Fleet Manager Rajesh",
        is_active=True,
    )
    db.session.add(veh)
    db.session.commit()
    return veh


@pytest.fixture
def sample_challan(app, sample_vehicle):
    """Fixture providing a sample pending traffic challan."""
    challan = Challan(
        vehicle_id=sample_vehicle.id,
        challan_number="MH-PUN-2026-0091",
        violation_type="Over-speeding",
        violation_description="Exceeded 80 km/h expressway limit (detected: 94 km/h)",
        violation_date=datetime.now(timezone.utc),
        issuing_authority="Highway Police Maharashtra",
        penalty_amount=2000.00,
        status=Challan.STATUS_PENDING,
        payment_status=Challan.PAYMENT_UNPAID,
        source="Manual Verification (Speed Camera Notice)",
    )
    db.session.add(challan)
    db.session.commit()
    return challan
