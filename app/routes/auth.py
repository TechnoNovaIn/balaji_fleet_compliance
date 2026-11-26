"""Authentication blueprint handling single-login authentication and password management."""
from urllib.parse import urlsplit
from datetime import datetime, timezone
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from app.extensions import db
from app.models.user import User
from app.models.audit_log import AuditLog

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def is_safe_redirect_url(target: str) -> bool:
    """Validate that the redirect target stays on the same host (prevents open redirects)."""
    if not target:
        return False
    ref_url = urlsplit(request.host_url)
    test_url = urlsplit(target)
    return test_url.scheme in ("", "http", "https") and test_url.netloc in ("", ref_url.netloc)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Authenticate administrator to access the fleet monitoring portal."""
    if current_user.is_authenticated:
        return redirect(url_for("challans.index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        remember = bool(request.form.get("remember"))

        if not username or not password:
            flash("Please provide both username and password.", "danger")
            return render_template("auth/login.html", username=username)

        # Allow logging in with either username or registered email
        user = User.query.filter(
            (User.username == username) | (User.email == username)
        ).first()

        if user is None or not user.check_password(password):
            AuditLog.record(
                action="LOGIN_FAILED",
                user=None,
                entity_type="User",
                entity_id=username,
                details={"reason": "Invalid credentials", "attempted_username": username},
                ip_address=request.remote_addr,
            )
            db.session.commit()
            flash("Invalid username or password. Please try again.", "danger")
            return render_template("auth/login.html", username=username)

        if not user.is_active:
            flash("Your account has been deactivated. Please contact support.", "danger")
            return render_template("auth/login.html", username=username)

        # Successful login
        login_user(user, remember=remember)
        user.last_login_at = datetime.now(timezone.utc)

        AuditLog.record(
            action="LOGIN_SUCCESS",
            user=user,
            entity_type="User",
            entity_id=user.id,
            details={"username": user.username},
            ip_address=request.remote_addr,
        )
        db.session.commit()

        flash(f"Welcome back, {user.full_name}.", "success")

        next_page = request.args.get("next")
        if next_page and is_safe_redirect_url(next_page):
            return redirect(next_page)
        return redirect(url_for("challans.index"))

    return render_template("auth/login.html")


@auth_bp.route("/logout", methods=["GET", "POST"])
@login_required
def logout():
    """Log out current user and clear session."""
    user = current_user._get_current_object()
    AuditLog.record(
        action="LOGOUT",
        user=user,
        entity_type="User",
        entity_id=user.id,
        ip_address=request.remote_addr,
    )
    db.session.commit()
    logout_user()
    flash("You have been securely logged out.", "info")
    return redirect(url_for("auth.login"))


