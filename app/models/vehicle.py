"""Vehicle model for managing fleet vehicles and normalized registrations."""
import re
from datetime import datetime, timezone
from app.extensions import db


class Vehicle(db.Model):
    __tablename__ = "vehicles"

    TYPE_TRUCK = "Truck"
    TYPE_CAR = "Car"
    TYPE_BUS = "Bus"
    TYPE_OTHER = "Other"

    VEHICLE_TYPES = [TYPE_TRUCK, TYPE_CAR, TYPE_BUS, TYPE_OTHER]

    id = db.Column(db.Integer, primary_key=True)
    # Registration number stored strictly in normalized alphanumeric uppercase (e.g., MH12AB1234)
    registration_number = db.Column(db.String(20), unique=True, nullable=False, index=True)
    # Formatted display version (e.g. MH 12 AB 1234)
    display_reg_number = db.Column(db.String(30), nullable=True)
    vehicle_type = db.Column(db.String(30), nullable=False, default=TYPE_TRUCK)
    make_model = db.Column(db.String(100), nullable=True)
    registered_owner = db.Column(db.String(150), nullable=True)
    department = db.Column(db.String(100), nullable=True, index=True)  # Branch or Department
    assigned_manager = db.Column(db.String(120), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    challans = db.relationship(
        "Challan",
        backref="vehicle",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
    monitoring_logs = db.relationship(
        "MonitoringLog",
        backref="vehicle",
        lazy="dynamic",
    )

    @staticmethod
    def normalize_registration(raw_reg: str) -> str:
        """Normalize vehicle registration number:

        Removes spaces, hyphens, slashes, special characters and converts to uppercase.
        Example: 'mh-12 / ab 1234' -> 'MH12AB1234'
        """
        if not raw_reg:
            return ""
        return re.sub(r"[^A-Za-z0-9]", "", raw_reg).upper()

    @staticmethod
    def format_registration(normalized: str) -> str:
        """Formats normalized Indian registration number for human readability.

        Example: 'MH12AB1234' -> 'MH 12 AB 1234'
        """
        match = re.match(r"^([A-Z]{2})(\d{2})([A-Z]{1,3})?(\d{1,4})$", normalized)
        if match:
            parts = [p for p in match.groups() if p]
            return " ".join(parts)
        return normalized

    @property
    def formatted_registration(self) -> str:
        return self.display_reg_number or self.format_registration(self.registration_number)

    @property
    def pending_challans_count(self) -> int:
        return self.challans.filter(
            db.or_(
                Challan.status == "pending",
                Challan.payment_status.in_(["unpaid", "partially_paid"]),
            )
        ).count()

    @property
    def total_outstanding_penalty(self) -> float:
        unpaid = self.challans.filter(
            Challan.payment_status.in_(["unpaid", "partially_paid"])
        ).all()
        return sum(c.remaining_penalty for c in unpaid)

    def __repr__(self) -> str:
        return f"<Vehicle {self.registration_number} ({self.vehicle_type})>"


# Import Challan reference for relationships
from app.models.challan import Challan  # noqa: E402
