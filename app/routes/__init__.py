"""Routes package."""
from app.routes.auth import auth_bp
from app.routes.dashboard import dashboard_bp
from app.routes.vehicles import vehicles_bp
from app.routes.challans import challans_bp
from app.routes.payments import payments_bp
from app.routes.reports import reports_bp

__all__ = [
    "auth_bp",
    "dashboard_bp",
    "vehicles_bp",
    "challans_bp",
    "payments_bp",
    "reports_bp",
]
