"""Monitoring log model for tracking daily automated and manual provider check attempts."""
from datetime import datetime, timezone
from app.extensions import db


class MonitoringLog(db.Model):
    __tablename__ = "monitoring_logs"

    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_RATE_LIMITED = "rate_limited"
    STATUS_AUTH_ERROR = "auth_error"
    STATUS_SERVICE_UNAVAILABLE = "service_unavailable"

    STATUSES = [
        STATUS_SUCCESS,
        STATUS_FAILED,
        STATUS_IN_PROGRESS,
        STATUS_RATE_LIMITED,
        STATUS_AUTH_ERROR,
        STATUS_SERVICE_UNAVAILABLE,
    ]

    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True, index=True)

    check_start_time = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    check_completion_time = db.Column(db.DateTime, nullable=True)

    status = db.Column(db.String(40), nullable=False, default=STATUS_IN_PROGRESS, index=True)
    data_source = db.Column(db.String(100), nullable=False, default="Manual / Not Configured")
    challans_found = db.Column(db.Integer, default=0, nullable=False)
    error_details = db.Column(db.Text, nullable=True)

    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    @property
    def is_successful(self) -> bool:
        return self.status == self.STATUS_SUCCESS

    @property
    def duration_seconds(self) -> float:
        if self.check_start_time and self.check_completion_time:
            return (self.check_completion_time - self.check_start_time).total_seconds()
        return 0.0

    def __repr__(self) -> str:
        return f"<MonitoringLog {self.id}: Vehicle {self.vehicle_id} - {self.status}>"
