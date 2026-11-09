"""Payment model for tracking challan settlements, receipts, and verification workflow."""
from datetime import datetime, timezone
from app.extensions import db


class Payment(db.Model):
    __tablename__ = "payments"

    VERIFICATION_PENDING = "pending_verification"
    VERIFICATION_VERIFIED = "verified"
    VERIFICATION_REJECTED = "rejected"

    VERIFICATION_STATUSES = [
        VERIFICATION_PENDING,
        VERIFICATION_VERIFIED,
        VERIFICATION_REJECTED,
    ]

    MODE_UPI = "UPI"
    MODE_NET_BANKING = "Net Banking"
    MODE_CARD = "Debit / Credit Card"
    MODE_RTGS_NEFT = "RTGS / NEFT"
    MODE_CASH = "Cash"
    MODE_CHEQUE = "Demand Draft / Cheque"

    PAYMENT_MODES = [
        MODE_UPI,
        MODE_NET_BANKING,
        MODE_CARD,
        MODE_RTGS_NEFT,
        MODE_CASH,
        MODE_CHEQUE,
    ]

    id = db.Column(db.Integer, primary_key=True)
    challan_id = db.Column(db.Integer, db.ForeignKey("challans.id", ondelete="CASCADE"), nullable=False, index=True)

    amount_paid = db.Column(db.Numeric(10, 2), nullable=False)
    payment_date = db.Column(db.Date, nullable=False, index=True)
    payment_mode = db.Column(db.String(50), nullable=True, default=MODE_UPI, server_default=MODE_UPI, index=True)
    payment_reference = db.Column(db.String(100), nullable=False, index=True)  # Reference ID (UTR, Txn ID, Receipt No.)
    receipt_file = db.Column(db.String(255), nullable=True)  # Safe stored filename / relative path

    recorded_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    # Verification workflow
    verification_status = db.Column(
        db.String(30),
        nullable=False,
        default=VERIFICATION_PENDING,
        index=True,
    )
    verified_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    verified_at = db.Column(db.DateTime, nullable=True)
    verification_notes = db.Column(db.Text, nullable=True)

    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    @property
    def reference_id(self) -> str:
        return self.payment_reference

    def mark_verified(self, verifying_user, notes: str = None) -> None:
        """Mark payment as verified by an authorized user."""
        self.verification_status = self.VERIFICATION_VERIFIED
        self.verified_by_user_id = verifying_user.id
        self.verified_at = datetime.now(timezone.utc)
        if notes:
            self.verification_notes = notes
        if self.challan:
            self.challan.sync_payment_status()

    def mark_rejected(self, verifying_user, reason: str) -> None:
        """Mark payment as rejected with a reason."""
        self.verification_status = self.VERIFICATION_REJECTED
        self.verified_by_user_id = verifying_user.id
        self.verified_at = datetime.now(timezone.utc)
        self.verification_notes = reason
        if self.challan:
            self.challan.sync_payment_status()

    def __repr__(self) -> str:
        return f"<Payment {self.id}: Challan #{self.challan_id} ₹{self.amount_paid} ({self.verification_status})>"
