"""Root blueprint redirecting directly to Challan Management."""
from flask import Blueprint, redirect, url_for
from flask_login import login_required

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
@login_required
def index():
    """Redirect root directly to Challans management as requested."""
    return redirect(url_for("challans.index"))
