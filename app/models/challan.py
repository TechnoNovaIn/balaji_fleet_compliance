"""Challan model representing traffic violation challans and penalties."""
from datetime import datetime, timezone
from app.extensions import db


class Challan(db.Model):
    __tablename__ = "challans"

    STATUS_PENDING = "pending"
    STATUS_PAID = "paid"
    STATUS_DISPUTED = "disputed"
    STATUS_UNDER_REVIEW = "under_review"
    STATUS_CANCELLED = "cancelled"

    STATUSES = [
        STATUS_PENDING,
        STATUS_PAID,
        STATUS_DISPUTED,
        STATUS_UNDER_REVIEW,
        STATUS_CANCELLED,
    ]

    PAYMENT_UNPAID = "unpaid"
    PAYMENT_PARTIALLY_PAID = "partially_paid"
    PAYMENT_PAID = "paid"
    PAYMENT_WAIVED = "waived"

    PAYMENT_STATUSES = [
        PAYMENT_UNPAID,
        PAYMENT_PARTIALLY_PAID,
        PAYMENT_PAID,
        PAYMENT_WAIVED,
    ]

    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True)

    # Official Challan Number from Parivahan/State e-Challan portal. Unique when present.
    challan_number = db.Column(db.String(80), unique=True, nullable=True, index=True)

    # Violation details
    violation_type = db.Column(db.String(150), nullable=False, index=True)
    violation_description = db.Column(db.Text, nullable=True)
    violation_location = db.Column(db.String(255), nullable=True)  # Where violation occurred (Highway KM, Toll Plaza, Signal)
    violation_date = db.Column(db.DateTime, nullable=False, index=True)
    issue_date = db.Column(db.DateTime, nullable=True)
    issuing_authority = db.Column(db.String(150), nullable=True, index=True)  # e.g. Mumbai Traffic Police

    # Financial details
    penalty_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)

    # Status tracking
    status = db.Column(db.String(30), nullable=False, default=STATUS_PENDING, index=True)
    payment_status = db.Column(db.String(30), nullable=False, default=PAYMENT_UNPAID, index=True)

    # Traffic Camera Evidence Photo (Speed Cam / CCTV surveillance snapshot)
    evidence_image_url = db.Column(db.String(500), nullable=True)

    # Live Notification Alert Status
    is_acknowledged = db.Column(db.Boolean, default=False, server_default=db.text('0'), nullable=True, index=True)

    # Driver Tagging (Option 1: Tag-on-Challan without 1000+ driver profiles)
    driver_name = db.Column(db.String(120), nullable=True, index=True)  # Name of responsible driver
    driver_mobile = db.Column(db.String(20), nullable=True)             # Driver phone number
    trip_reference = db.Column(db.String(100), nullable=True)           # LR No. / Trip Sheet No.

    # Salary / Trip Settlement Deduction Workflow
    DEDUCTION_PENDING = "pending"
    DEDUCTION_DEDUCTED = "deducted"
    DEDUCTION_COMPANY_BORNE = "company_borne"
    DEDUCTION_DISPUTED = "disputed"

    DEDUCTION_STATUSES = [
        DEDUCTION_PENDING,
        DEDUCTION_DEDUCTED,
        DEDUCTION_COMPANY_BORNE,
        DEDUCTION_DISPUTED,
    ]

    deduction_status = db.Column(
        db.String(40),
        nullable=True,
        default=DEDUCTION_PENDING,
        server_default=DEDUCTION_PENDING,
        index=True,
    )
    deduction_reference = db.Column(db.String(120), nullable=True)  # Voucher No / Salary Month (e.g. "Oct 2026 Salary")
    deducted_amount = db.Column(db.Numeric(10, 2), nullable=True, default=0.0, server_default="0.0")
    deducted_at = db.Column(db.DateTime, nullable=True)

    # Source & Verification
    source = db.Column(db.String(100), nullable=False, default="Manual Entry")
    last_verified_at = db.Column(db.DateTime, nullable=True)
    assigned_staff = db.Column(db.String(120), nullable=True)
    notes = db.Column(db.Text, nullable=True)

    # Flag for potential duplicate or uncertain match requiring human review
    flagged_for_review = db.Column(db.Boolean, default=False, nullable=False, index=True)
    review_reason = db.Column(db.String(255), nullable=True)

    # Timestamps
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    payments = db.relationship(
        "Payment",
        backref="challan",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    @property
    def total_paid(self) -> float:
        """Sum of all verified payments for this challan."""
        from app.models.payment import Payment

        verified_payments = self.payments.filter_by(
            verification_status=Payment.VERIFICATION_VERIFIED
        ).all()
        return sum(float(p.amount_paid) for p in verified_payments)

    @property
    def remaining_penalty(self) -> float:
        """Outstanding penalty balance."""
        if self.payment_status == self.PAYMENT_WAIVED:
            return 0.0
        rem = float(self.penalty_amount or 0.0) - self.total_paid
        return max(0.0, rem)

    def sync_payment_status(self) -> None:
        """Update payment_status based on current verified payments."""
        paid = self.total_paid
        original = float(self.penalty_amount or 0.0)
        if original > 0 and paid >= original:
            self.payment_status = self.PAYMENT_PAID
            self.status = self.STATUS_PAID
        elif paid > 0:
            self.payment_status = self.PAYMENT_PARTIALLY_PAID
        else:
            self.payment_status = self.PAYMENT_UNPAID

    def __repr__(self) -> str:
        return f"<Challan {self.challan_number or self.id} (Vehicle: {self.vehicle_id}, ₹{self.penalty_amount})>"
