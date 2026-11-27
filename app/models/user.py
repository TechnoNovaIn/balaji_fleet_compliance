"""User model for authentication and role-based access control."""
from datetime import datetime, timezone
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db, login_manager


class User(UserMixin, db.Model):
    __tablename__ = "users"

    ROLE_ADMIN = "admin"
    ROLE_MANAGER = "manager"
    ROLE_ACCOUNTS = "accounts"
    ROLE_VIEWER = "viewer"

    ROLES = {
        ROLE_ADMIN: "Administrator",
        ROLE_MANAGER: "Transport Manager",
        ROLE_ACCOUNTS: "Accounts Team",
        ROLE_VIEWER: "Viewer",
    }

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(30), nullable=False, default=ROLE_ADMIN)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    last_login_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    payments_recorded = db.relationship(
        "Payment",
        foreign_keys="Payment.recorded_by_user_id",
        backref="recorded_by_user",
        lazy="dynamic",
    )
    payments_verified = db.relationship(
        "Payment",
        foreign_keys="Payment.verified_by_user_id",
        backref="verified_by_user",
        lazy="dynamic",
    )
    audit_logs = db.relationship("AuditLog", backref="user", lazy="dynamic")

    def set_password(self, password: str) -> None:
        """Hash and set the user's password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Verify the user's password against the stored hash."""
        return check_password_hash(self.password_hash, password)

    def has_role(self, *roles: str) -> bool:
        """Check whether the user holds any of the specified roles."""
        return self.role in roles

    @property
    def role_label(self) -> str:
        """Human-readable role title."""
        return self.ROLES.get(self.role, (self.role or "User").title())

    @property
    def is_admin(self) -> bool:
        return self.role == self.ROLE_ADMIN

    @property
    def is_manager(self) -> bool:
        return self.role in (self.ROLE_ADMIN, self.ROLE_MANAGER)

    @property
    def is_accounts(self) -> bool:
        return self.role in (self.ROLE_ADMIN, self.ROLE_ACCOUNTS)

    @property
    def is_viewer(self) -> bool:
        return self.role == self.ROLE_VIEWER

    def __repr__(self) -> str:
        return f"<User {self.username} ({self.role})>"


@login_manager.user_loader
def load_user(user_id: str):
    """Load user by ID for Flask-Login session."""
    return db.session.get(User, int(user_id))
