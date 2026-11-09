"""Audit log model for immutable compliance record keeping."""
from datetime import datetime, timezone
import json
from app.extensions import db


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    action = db.Column(db.String(80), nullable=False, index=True)
    entity_type = db.Column(db.String(60), nullable=True, index=True)  # Vehicle, Challan, Payment, User, etc.
    entity_id = db.Column(db.String(80), nullable=True, index=True)
    details = db.Column(db.Text, nullable=True)  # JSON or descriptive text
    ip_address = db.Column(db.String(45), nullable=True)
    timestamp = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    @classmethod
    def record(
        cls,
        action: str,
        user=None,
        entity_type: str = None,
        entity_id=None,
        details=None,
        ip_address: str = None,
    ):
        """Create and persist an audit log entry."""
        user_id = getattr(user, "id", None) if user else None
        details_str = details
        if isinstance(details, (dict, list)):
            details_str = json.dumps(details)

        entry = cls(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            details=details_str,
            ip_address=ip_address,
            timestamp=datetime.now(timezone.utc),
        )
        db.session.add(entry)
        return entry

    def __repr__(self) -> str:
        return f"<AuditLog {self.action} on {self.entity_type} #{self.entity_id} by User {self.user_id}>"
