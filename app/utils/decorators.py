"""Role-based access control decorators and permission utilities."""
from functools import wraps
from flask import abort, redirect, url_for
from flask_login import current_user


def roles_required(*allowed_roles: str):
    """Enforce authentication and require one of the specified roles."""
    def decorator(fn):
        @wraps(fn)
        def decorated_view(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("auth.login"))
            if not current_user.has_role(*allowed_roles):
                abort(403)
            return fn(*args, **kwargs)

        return decorated_view

    return decorator


def admin_required(fn):
    """Shorthand decorator for Administrator access."""
    return roles_required("admin")(fn)


def manager_or_admin_required(fn):
    """Access for fleet management functions (Admin or Transport Manager)."""
    return roles_required("admin", "manager")(fn)


def accounts_or_admin_required(fn):
    """Access for payment and verification functions (Admin or Accounts Team)."""
    return roles_required("admin", "accounts")(fn)
